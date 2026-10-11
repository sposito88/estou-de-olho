"""Busca por nome (pessoa ou empresa) em todas as bases: índice de texto (SQLite FTS5).

Uso:
    python -m civic.busca          # reconstrói o índice (alguns minutos)

Cada linha do índice é um "papel" de um nome numa base: fornecedor que recebeu
dinheiro público (e de quais órgãos, em cada cidade), parlamentar, servidor municipal,
sócio de fornecedor, candidato, doador de campanha ou pessoa física paga por
prefeitura/câmara. A coluna `cidade` permite buscar só dentro de uma cidade. A busca junta os
papéis do mesmo nome (e, quando há, dos mesmos dígitos de CPF) num só resultado.

Só entram dados já publicados pelas fontes oficiais; CPF aparece mascarado.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from civic.cleaning import normalizar_nome
from civic.config import get_settings
from civic.database import SessionLocal, init_db

logger = logging.getLogger("civic.busca")

TABELA = "busca_indice"
COLUNAS = (
    "nome",  # texto indexado: nome normalizado (+ CNPJ, para achar pelo número)
    "cidade",  # texto indexado: cidade + UF sem espaços ("CARPINAPE"), para a busca dentro da cidade
    "tipo",  # empresa | deputado | senador | estadual | servidor | socio | candidato | doador | credor
    "titulo",  # nome como a fonte escreve
    "chave",  # agrupa papéis da mesma pessoa/empresa
    "documento",  # CNPJ ou CPF mascarado
    "papel",
    "orgao",
    "lugar",
    "ano",
    "valor",  # centavos
    "url",
)
COLUNAS_INDEXADAS = ("nome", "cidade")
MINIMO_CARACTERES = 3
LIMITE_LINHAS = 400

# Ordem de exibição dos papéis dentro de um resultado.
ORDEM_TIPOS = ("deputado", "senador", "estadual", "candidato", "servidor", "empresa", "pagamento", "contrato",
               "socio", "doador", "credor")

CPF_MASCARADO = "'***.' || substr({c}, 1, 3) || '.' || substr({c}, 4, 3) || '-**'"


def _cidade_url(uf: str, municipio: str) -> str:
    return f"'/cidade/' || {uf} || '/' || {municipio}"


# Cada consulta devolve as colunas de COLUNAS, nessa ordem. `norm()` é a normalização do
# Python registrada na conexão (o SQLite não tira acentos sozinho).
CONSULTAS: dict[str, str] = {
    "empresa": """
        WITH tot AS (
            SELECT cnpj, SUM(valor) AS valor FROM (
                SELECT cnpj_cpf AS cnpj, valor_liquido_centavos AS valor FROM despesas WHERE length(cnpj_cpf) = 14
                UNION ALL SELECT cnpj_cpf, valor_centavos FROM verbas_indenizatorias WHERE length(cnpj_cpf) = 14
                UNION ALL SELECT cnpj_cpf, valor_centavos FROM despesas_senado WHERE tipo_pessoa = 'PJ'
                UNION ALL SELECT cpf_cnpj, valor_pago_centavos FROM despesas_municipais WHERE tipo_pessoa = 'PJ'
                UNION ALL SELECT fornecedor_ni, valor_global_centavos FROM contratos_pncp WHERE tipo_pessoa = 'PJ'
            ) GROUP BY cnpj
        )
        SELECT norm(coalesce(f.razao_social, '') || ' ' || coalesce(f.nome_fantasia, '')) || ' ' || f.cnpj,
               'empresa', coalesce(f.razao_social, f.nome_fantasia, f.cnpj), 'PJ:' || f.cnpj, f.cnpj,
               'Fornecedor de órgãos públicos' || CASE WHEN f.situacao_cadastral NOT IN ('ATIVA') AND f.situacao_cadastral IS NOT NULL
                                                       THEN ' (situação na Receita: ' || f.situacao_cadastral || ')' ELSE '' END,
               f.nome_fantasia, f.municipio || '/' || f.sigla_uf, NULL, tot.valor, '/fornecedores/' || f.cnpj
        FROM fornecedores f LEFT JOIN tot ON tot.cnpj = f.cnpj
    """,
    "pagamento": f"""
        SELECT norm(coalesce(MAX(f.razao_social), MAX(d.fornecedor), '')) || ' ' || d.cpf_cnpj, 'pagamento',
               coalesce(MAX(f.razao_social), MAX(d.fornecedor), d.cpf_cnpj), 'PJ:' || d.cpf_cnpj, d.cpf_cnpj,
               'Recebeu pagamentos (' || SUM(d.qtd_empenhos) || ' empenho(s))',
               ug.nome, ug.municipio || '/' || ug.sigla_uf, MAX(d.ano), SUM(d.valor_pago_centavos),
               '/fornecedores/' || d.cpf_cnpj
        FROM despesas_municipais d
        JOIN unidades_gestoras ug ON ug.id = d.unidade_gestora_id
        LEFT JOIN fornecedores f ON f.cnpj = d.cpf_cnpj
        WHERE d.tipo_pessoa = 'PJ' AND d.valor_pago_centavos > 0
        GROUP BY d.cpf_cnpj, d.unidade_gestora_id
    """,
    "contrato": f"""
        SELECT norm(coalesce(MAX(f.razao_social), MAX(p.fornecedor_nome), '')) || ' ' || p.fornecedor_ni, 'contrato',
               coalesce(MAX(f.razao_social), MAX(p.fornecedor_nome), p.fornecedor_ni), 'PJ:' || p.fornecedor_ni,
               p.fornecedor_ni, 'Contratada (' || COUNT(*) || ' contrato(s) no PNCP)',
               MAX(p.orgao_nome), m.nome || '/' || m.sigla_uf, MAX(p.ano), SUM(p.valor_global_centavos),
               '/fornecedores/' || p.fornecedor_ni
        FROM contratos_pncp p
        JOIN municipios m ON m.codigo_ibge = p.municipio_ibge
        LEFT JOIN fornecedores f ON f.cnpj = p.fornecedor_ni
        WHERE p.tipo_pessoa = 'PJ'
        GROUP BY p.fornecedor_ni, p.orgao_cnpj
    """,
    "deputado": """
        SELECT nome_normalizado, 'deputado', nome, 'PF:' || nome_normalizado, NULL,
               'Deputado(a) federal (' || coalesce(sigla_partido, '') || '-' || coalesce(sigla_uf, '') || ')',
               'Câmara dos Deputados', sigla_uf, NULL, NULL, '/deputados/' || id
        FROM deputados
    """,
    "senador": """
        SELECT nome_normalizado, 'senador', nome, 'PF:' || nome_normalizado, NULL,
               'Senador(a) (' || coalesce(sigla_partido, '') || '-' || coalesce(sigla_uf, '') || ')',
               'Senado Federal', sigla_uf, NULL, NULL, '/senadores/' || id
        FROM senadores
    """,
    "estadual": """
        SELECT nome_normalizado, 'estadual', nome, 'PF:' || nome_normalizado, NULL,
               'Deputado(a) estadual (' || coalesce(sigla_partido, '') || ')',
               'Assembleia Legislativa de Pernambuco', 'PE', NULL, NULL, '/estaduais/' || id
        FROM deputados_estaduais
    """,
    "servidor": f"""
        WITH v AS (
            SELECT sv.*, ug.nome AS orgao, ug.natureza, ug.municipio AS mun, ug.sigla_uf AS uf,
                   ROW_NUMBER() OVER (PARTITION BY sv.nome_normalizado, sv.cpf_meio, sv.unidade_gestora_id
                                      ORDER BY sv.data_admissao DESC) AS ordem,
                   COUNT(*) OVER (PARTITION BY sv.nome_normalizado, sv.cpf_meio, sv.unidade_gestora_id) AS qtd
            FROM servidores_municipais sv JOIN unidades_gestoras ug ON ug.id = sv.unidade_gestora_id
        )
        SELECT nome_normalizado, 'servidor', nome, 'PF:' || nome_normalizado || '|' || coalesce(cpf_meio, ''),
               CASE WHEN cpf_meio IS NOT NULL THEN {CPF_MASCARADO.format(c='cpf_meio')} END,
               coalesce(cargo, 'Cargo não informado') || ' (' || coalesce(vinculo, 'vínculo não informado') || ')'
                   || CASE WHEN qtd > 1 THEN ', ' || qtd || ' vínculos' ELSE '' END,
               orgao, mun || '/' || uf, CAST(strftime('%Y', data_admissao) AS INTEGER), NULL,
               {_cidade_url('uf', 'mun')} || CASE WHEN natureza LIKE 'Câmara%' THEN '/camara' ELSE '/pessoal?busca=' || nome_normalizado END
        FROM v WHERE ordem = 1
    """,
    "socio": f"""
        WITH emp AS (
            SELECT substr(cnpj, 1, 8) AS basico, MIN(cnpj) AS cnpj, MAX(razao_social) AS razao,
                   MAX(municipio || '/' || sigla_uf) AS lugar
            FROM fornecedores GROUP BY substr(cnpj, 1, 8)
        )
        SELECT so.nome_normalizado, 'socio', so.nome, 'PF:' || so.nome_normalizado || '|' || coalesce(so.documento, ''),
               CASE WHEN length(so.documento) = 6 THEN {CPF_MASCARADO.format(c='so.documento')} END,
               'Sócio(a)' || CASE WHEN so.qualificacao IS NOT NULL THEN ' – ' || so.qualificacao ELSE '' END,
               emp.razao, emp.lugar, CAST(strftime('%Y', so.data_entrada) AS INTEGER), NULL, '/fornecedores/' || emp.cnpj
        FROM socios so JOIN emp ON emp.basico = so.cnpj_basico
        WHERE so.tipo = 'PF'
    """,
    "candidato": f"""
        SELECT c.nome_normalizado, 'candidato', coalesce(c.nome_urna, c.nome), 'PF:' || c.nome_normalizado, NULL,
               'Candidato(a) a ' || lower(c.cargo) || ' (' || coalesce(c.sigla_partido, 'sem partido') || ')'
                   || CASE WHEN c.eleito THEN ' – eleito(a)' ELSE '' END,
               NULL, coalesce(m.nome || '/' || m.sigla_uf, c.sigla_uf), c.ano, c.bens_centavos,
               CASE WHEN c.deputado_id IS NOT NULL THEN '/deputados/' || c.deputado_id
                    WHEN c.senador_id IS NOT NULL THEN '/senadores/' || c.senador_id
                    WHEN c.deputado_estadual_id IS NOT NULL THEN '/estaduais/' || c.deputado_estadual_id
                    WHEN m.codigo_ibge IS NOT NULL THEN {_cidade_url('m.sigla_uf', 'm.nome')} || '/eleitos' END
        FROM candidatos c LEFT JOIN municipios m ON m.codigo_ibge = c.municipio_ibge
    """,
    "doador": f"""
        SELECT d.doador_nome_normalizado, 'doador', MAX(d.doador_nome),
               'PF:' || d.doador_nome_normalizado || '|' || coalesce(d.doador_cpf_meio, ''),
               CASE WHEN length(d.doador_cpf_meio) = 6 THEN {CPF_MASCARADO.format(c='d.doador_cpf_meio')} END,
               'Doou para a campanha de ' || MAX(coalesce(c.nome_urna, c.nome)) || ' (' || lower(MAX(c.cargo)) || ')',
               NULL, MAX(coalesce(m.nome || '/' || m.sigla_uf, c.sigla_uf)), MAX(d.ano), SUM(d.valor_centavos),
               MAX(CASE WHEN c.deputado_id IS NOT NULL THEN '/deputados/' || c.deputado_id
                        WHEN c.senador_id IS NOT NULL THEN '/senadores/' || c.senador_id
                        WHEN c.deputado_estadual_id IS NOT NULL THEN '/estaduais/' || c.deputado_estadual_id
                        WHEN m.codigo_ibge IS NOT NULL THEN {_cidade_url('m.sigla_uf', 'm.nome')} || '/eleitos' END)
        FROM doacoes_campanha d
        JOIN candidatos c ON c.sq_candidato = d.sq_candidato
        LEFT JOIN municipios m ON m.codigo_ibge = c.municipio_ibge
        GROUP BY d.doador_nome_normalizado, d.doador_cpf_meio, d.sq_candidato
    """,
    "credor": f"""
        SELECT d.fornecedor_normalizado, 'credor', MAX(d.fornecedor), 'PF:' || d.fornecedor_normalizado,
               MAX(d.cpf_cnpj),
               'Recebeu pagamentos como pessoa física (' || SUM(d.qtd_empenhos) || ' empenho(s))',
               ug.nome, ug.municipio || '/' || ug.sigla_uf, MAX(d.ano), SUM(d.valor_pago_centavos),
               {_cidade_url('ug.sigla_uf', 'ug.municipio')}
                   || CASE WHEN ug.natureza LIKE 'Câmara%' THEN '/camara' ELSE '/prefeitura' END
                   || '?busca=' || d.fornecedor_normalizado
        FROM despesas_municipais d JOIN unidades_gestoras ug ON ug.id = d.unidade_gestora_id
        WHERE d.tipo_pessoa = 'PF' AND d.fornecedor_normalizado IS NOT NULL AND d.valor_pago_centavos > 0
        GROUP BY d.fornecedor_normalizado, d.unidade_gestora_id
    """,
}


def cidade_token(lugar: str | None) -> str | None:
    """'Carpina/PE' -> 'CARPINAPE'; 'São José do Egito/PE' -> 'SAOJOSEDOEGITOPE'."""
    if not lugar or "/" not in lugar:
        return None
    return re.sub(r"[^0-9A-Z]", "", normalizar_nome(lugar) or "") or None


def _registrar_normalizacao(conexao: Connection) -> None:
    bruta = conexao.connection.dbapi_connection
    bruta.create_function("norm", 1, normalizar_nome, deterministic=True)  # type: ignore[union-attr]
    bruta.create_function("cidade_token", 1, cidade_token, deterministic=True)  # type: ignore[union-attr]


def reconstruir_indice(db: Session) -> dict[str, int]:
    """Monta o índice numa tabela nova e troca pela antiga no fim (a busca não fica fora do ar)."""
    conexao = db.connection()
    _registrar_normalizacao(conexao)
    nova = f"{TABELA}_novo"
    colunas_fts = ", ".join(c if c in COLUNAS_INDEXADAS else f"{c} UNINDEXED" for c in COLUNAS)
    conexao.execute(text(f"DROP TABLE IF EXISTS {nova}"))
    conexao.execute(text(
        f"CREATE VIRTUAL TABLE {nova} USING fts5({colunas_fts}, tokenize = 'unicode61 remove_diacritics 2')"
    ))
    contagem: dict[str, int] = {}
    for tipo, sql in CONSULTAS.items():
        inicio = time.monotonic()
        sem_cidade = [c for c in COLUNAS if c != "cidade"]
        conexao.execute(text(
            f"INSERT INTO {nova} ({', '.join(COLUNAS)}) "
            f"WITH q({', '.join(sem_cidade)}) AS ({sql}) "
            f"SELECT {', '.join('cidade_token(lugar)' if c == 'cidade' else c for c in COLUNAS)} FROM q"
        ))
        contagem[tipo] = int(conexao.execute(text("SELECT changes()")).scalar() or 0)
        logger.info("Índice de busca: %s, %d linhas em %.0f s", tipo, contagem[tipo], time.monotonic() - inicio)
    conexao.execute(text(f"INSERT INTO {nova}({nova}) VALUES ('optimize')"))
    conexao.execute(text(f"DROP TABLE IF EXISTS {TABELA}"))
    conexao.execute(text(f"ALTER TABLE {nova} RENAME TO {TABELA}"))
    db.commit()
    return contagem


# --------------------------------------------------------------------------- consulta


def expressao_fts(termo: str) -> str | None:
    """'joão  da silva' -> '"JOAO"* AND "DA"* AND "SILVA"*' (prefixo em cada palavra)."""
    palavras = [p for p in re.split(r"[^0-9A-Z]+", normalizar_nome(termo) or "") if p]
    if sum(len(p) for p in palavras) < MINIMO_CARACTERES:
        return None
    return " AND ".join(f'"{p}"*' for p in palavras)


def _uf(lugar: str | None) -> str | None:
    """'Carpina/PE' -> 'PE'; 'PE' -> 'PE'."""
    if not lugar:
        return None
    sigla = lugar.rsplit("/", 1)[-1].strip().upper()
    return sigla if len(sigla) == 2 else None


def buscar(db: Session, termo: str, limite: int = 30, cidade: str | None = None) -> dict[str, Any]:
    """Resultados agrupados por pessoa/empresa, os mais parecidos com o termo primeiro.

    `cidade` ("Carpina/PE") limita aos papéis ligados à cidade: servidores e credores dos órgãos
    dela, empresas pagas ou contratadas por eles, candidatos e doadores de lá, sócios de empresas de lá.
    """
    expressao = expressao_fts(termo)
    token = cidade_token(cidade) if cidade else None
    if expressao is None:
        return {"termo": termo, "cidade": cidade, "total": 0, "resultados": [], "indice_disponivel": True}
    existe = db.execute(text("SELECT 1 FROM sqlite_master WHERE name = :t"), {"t": TABELA}).first()
    if not existe:
        return {"termo": termo, "cidade": cidade, "total": 0, "resultados": [], "indice_disponivel": False}
    linhas = db.execute(
        text(f"SELECT {', '.join(COLUNAS)} FROM {TABELA} WHERE {TABELA} MATCH :q ORDER BY rank LIMIT :lim"),
        {"q": f'nome : ({expressao})' + (f' AND cidade : "{token}"' if token else ""), "lim": LIMITE_LINHAS},
    ).mappings().all()
    alvo = normalizar_nome(termo) or ""
    grupos: dict[str, dict[str, Any]] = {}
    for posicao, l in enumerate(linhas):
        chave = l["chave"]
        if chave.startswith("PF:") and ("|" not in chave or chave.endswith("|")):
            # Papel sem CPF (parlamentar, candidato, credor): agrupa por nome dentro do mesmo estado.
            chave = f"{chave.rstrip('|')}@{_uf(l['lugar']) or '?'}"
        grupo = grupos.setdefault(chave, {
            "titulo": l["titulo"], "tipo_pessoa": "PJ" if chave.startswith("PJ:") else "PF",
            "documento": l["documento"] if chave.startswith("PJ:") else None,
            "posicao": posicao, "nome": l["nome"], "papeis": [],
        })
        if l["tipo"] in ("servidor", "socio", "doador") and l["documento"] and not grupo["documento"]:
            grupo["documento"] = l["documento"]
        grupo["papeis"].append({c: l[c] for c in ("tipo", "papel", "orgao", "lugar", "ano", "valor", "url", "documento")})
    # Papéis sem CPF entram no grupo do mesmo nome com CPF quando há uma só pessoa com esse nome
    # no mesmo estado; com dois CPFs diferentes no estado (homônimos), ficam separados.
    com_cpf: dict[str, list[str]] = {}
    for chave in grupos:
        if chave.startswith("PF:") and "@" not in chave:
            com_cpf.setdefault(chave[3:].split("|", 1)[0], []).append(chave)
    for chave in [c for c in grupos if "@" in c]:
        nome, uf = chave[3:].rsplit("@", 1)
        destinos = [c for c in com_cpf.get(nome, []) if uf in {_uf(p["lugar"]) for p in grupos[c]["papeis"]}]
        if len(destinos) == 1:
            destino = grupos[destinos[0]]
            destino["papeis"].extend(grupos[chave]["papeis"])
            destino["posicao"] = min(destino["posicao"], grupos[chave]["posicao"])
            del grupos[chave]

    def relevancia(g: dict[str, Any]) -> tuple[int, int, int]:
        nome = re.sub(r" \d{14}$", "", g["nome"])
        exato = 0 if nome == alvo else (1 if nome.startswith(alvo) else 2)
        return (exato, g["posicao"], -len(g["papeis"]))

    resultados = sorted(grupos.values(), key=relevancia)
    for g in resultados:
        g["papeis"].sort(key=lambda p: (ORDEM_TIPOS.index(p["tipo"]) if p["tipo"] in ORDEM_TIPOS else 99,
                                        -(p["valor"] or 0)))
        g["homonimos_possiveis"] = g["tipo_pessoa"] == "PF" and any(
            p["tipo"] in ("candidato", "credor", "deputado", "senador", "estadual") for p in g["papeis"]
        ) and any(p["tipo"] in ("servidor", "socio", "doador") for p in g["papeis"])
        del g["posicao"], g["nome"]
    return {"termo": termo, "cidade": cidade, "total": len(resultados), "resultados": resultados[:limite],
            "indice_disponivel": True}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.busca", description=__doc__.splitlines()[0])
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)
    s = get_settings()
    logging.basicConfig(
        level=(args.log_level or s.log_level).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    init_db()
    inicio = time.monotonic()
    with SessionLocal() as db:
        contagem = reconstruir_indice(db)
    logger.info("Índice de busca pronto em %.1f min: %s", (time.monotonic() - inicio) / 60, contagem)
    return 0


if __name__ == "__main__":
    sys.exit(main())
