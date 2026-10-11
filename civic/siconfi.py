"""Contas dos municípios (Siconfi, Tesouro Nacional): despesa por função e subfunção.

Uso:
    python -m civic.siconfi [--ano 2024 ...] [--uf PE ...] [--forcar] [--rreo]

Anos fechados vêm da DCA (declaração anual, sai até abril do ano seguinte): uma
chamada por município e ano (≈5.570 por ano); município/ano já carregado é pulado,
exceto com --forcar (a DCA pode ser retificada).

Com --rreo, o ano corrente vem do RREO (relatório bimestral, Anexo 02): dotação,
empenhado e liquidado até o último bimestre publicado. Município que já tem o
bimestre esperado é pulado; quando a DCA do ano chega, ela substitui o RREO.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from difflib import get_close_matches
from typing import Any

from sqlalchemy import delete, distinct, func, insert, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from civic.cleaning import normalizar_nome, para_centavos
from civic.config import Settings, get_settings
from civic.database import SessionLocal, init_db
from civic.models import ContaMunicipal, EnteSiconfi
from civic.pernambuco import ClienteJson
from civic.scraper import Resumo, barra, registrar_execucao

logger = logging.getLogger("civic.siconfi")

ANEXO_DESPESA_FUNCAO = "DCA-Anexo I-E"
COLUNAS = {"Despesas Empenhadas": "empenhado_centavos", "Despesas Liquidadas": "liquidado_centavos",
           "Despesas Pagas": "pago_centavos"}
_FUNCAO = re.compile(r"^\d{2} - ")
_SUBFUNCAO = re.compile(r"^\d{2}\.\d{3} - ")


def nivel_da_conta(conta: str) -> str | None:
    """'Despesas Exceto Intraorçamentárias' -> total; '10 - Saúde' -> funcao; '10.301 - ...' -> subfuncao."""
    if conta.startswith("Despesas Exceto Intraor"):
        return "total"
    if _FUNCAO.match(conta):
        return "funcao"
    if _SUBFUNCAO.match(conta):
        return "subfuncao"
    return None  # "FU04 - Demais Subfunções" e afins


def codigo_da_conta(conta: str, nivel: str) -> str:
    """'10.301 - Atenção Básica' -> '10.301'; o total vira 'TOTAL'.

    (O campo `cod_conta` do Siconfi é o mesmo para todas as linhas do anexo.)
    """
    return "TOTAL" if nivel == "total" else conta.split(" - ", 1)[0].strip()


def contas_da_dca(itens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Junta as colunas (empenhado/liquidado/pago) de cada conta numa linha."""
    contas: dict[str, dict[str, Any]] = defaultdict(dict)
    for i in itens:
        coluna = COLUNAS.get(i.get("coluna", ""))
        nivel = nivel_da_conta(i.get("conta", ""))
        if not coluna or not nivel:
            continue
        codigo = codigo_da_conta(i["conta"], nivel)
        linha = contas[codigo]
        linha.update(
            {
                "codigo_ibge": str(i["cod_ibge"]),
                "ano": int(i["exercicio"]),
                "cod_conta": codigo,
                "conta": i["conta"],
                "nivel": nivel,
            }
        )
        linha[coluna] = para_centavos(i.get("valor"))
    return [{"empenhado_centavos": 0, "liquidado_centavos": 0, "pago_centavos": 0, **l} for l in contas.values()]


# --------------------------------------------------------------------------- RREO (ano corrente)

ANEXO_RREO = "RREO-Anexo 02"
ROTULO_RREO = "Total das Despesas Exceto Intra"
COLUNAS_RREO = {
    "DOTAÇÃO ATUALIZADA (a)": "dotacao_centavos",
    "DESPESAS EMPENHADAS ATÉ O BIMESTRE (b)": "empenhado_centavos",
    "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)": "liquidado_centavos",
}
TOTAL_RREO = "DESPESAS (EXCETO INTRA"
# Funções de governo (Portaria MOG 42/1999): o RREO traz só o nome, sem o código.
FUNCOES = {
    "LEGISLATIVA": "01", "JUDICIARIA": "02", "ESSENCIAL A JUSTICA": "03", "ADMINISTRACAO": "04",
    "DEFESA NACIONAL": "05", "SEGURANCA PUBLICA": "06", "RELACOES EXTERIORES": "07", "ASSISTENCIA SOCIAL": "08",
    "PREVIDENCIA SOCIAL": "09", "SAUDE": "10", "TRABALHO": "11", "EDUCACAO": "12", "CULTURA": "13",
    "DIREITOS DA CIDADANIA": "14", "URBANISMO": "15", "HABITACAO": "16", "SANEAMENTO": "17",
    "GESTAO AMBIENTAL": "18", "CIENCIA E TECNOLOGIA": "19", "AGRICULTURA": "20", "ORGANIZACAO AGRARIA": "21",
    "INDUSTRIA": "22", "COMERCIO E SERVICOS": "23", "COMUNICACOES": "24", "ENERGIA": "25", "TRANSPORTE": "26",
    "DESPORTO E LAZER": "27", "ENCARGOS ESPECIAIS": "28", "RESERVA DE CONTINGENCIA": "99",
}
NOMES_FUNCOES = {
    "01": "Legislativa", "02": "Judiciária", "03": "Essencial à Justiça", "04": "Administração", "05": "Defesa Nacional",
    "06": "Segurança Pública", "07": "Relações Exteriores", "08": "Assistência Social", "09": "Previdência Social",
    "10": "Saúde", "11": "Trabalho", "12": "Educação", "13": "Cultura", "14": "Direitos da Cidadania",
    "15": "Urbanismo", "16": "Habitação", "17": "Saneamento", "18": "Gestão Ambiental", "19": "Ciência e Tecnologia",
    "20": "Agricultura", "21": "Organização Agrária", "22": "Indústria", "23": "Comércio e Serviços",
    "24": "Comunicações", "25": "Energia", "26": "Transporte", "27": "Desporto e Lazer", "28": "Encargos Especiais",
    "99": "Reserva de Contingência",
}


def bimestre_esperado(hoje: date) -> int:
    """Último bimestre do ano corrente que já deveria estar publicado (prazo: 30 dias após o fim)."""
    return (hoje.month - 1) // 2


def mapa_subfuncoes(db: Session) -> dict[str, str]:
    """Nome normalizado da subfunção -> código de 3 dígitos, a partir das DCAs já carregadas."""
    mapa: dict[str, str] = {}
    for codigo, conta in db.execute(
        select(distinct(ContaMunicipal.cod_conta), ContaMunicipal.conta)
        .where(ContaMunicipal.nivel == "subfuncao", ContaMunicipal.demonstrativo.is_not("RREO"))
    ):
        nome = normalizar_nome(conta.split(" - ", 1)[-1])
        if nome and "." in codigo:
            mapa.setdefault(nome, codigo.split(".", 1)[1])
    return mapa


def contas_do_rreo(itens: list[dict[str, Any]], subfuncoes: dict[str, str]) -> list[dict[str, Any]]:
    """Monta as contas do Anexo 02 do RREO. As linhas vêm em ordem: cada função seguida das
    suas subfunções, só pelo nome; o código da subfunção sai das DCAs (`subfuncoes`)."""
    contas: dict[str, dict[str, Any]] = {}
    por_coluna: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for i in itens:
        if (i.get("rotulo") or "").startswith(ROTULO_RREO) and i.get("coluna") in COLUNAS_RREO:
            por_coluna[i["coluna"]].append(i)
    desconhecidas: set[str] = set()
    for coluna, linhas in por_coluna.items():
        campo = COLUNAS_RREO[coluna]
        funcao: str | None = None
        for i in linhas:
            conta = (i.get("conta") or "").strip()
            nome = normalizar_nome(conta) or ""
            if conta.upper().startswith(TOTAL_RREO):
                codigo, nivel, rotulo = "TOTAL", "total", "Despesas Exceto Intraorçamentárias"
            elif nome in FUNCOES:
                funcao = FUNCOES[nome]
                codigo, nivel, rotulo = funcao, "funcao", f"{funcao} - {NOMES_FUNCOES[funcao]}"
            elif re.match(r"^FU\d{2} - ", conta) or funcao is None:
                continue  # "FU04 - Administração Geral" e afins
            else:
                sub = subfuncoes.get(nome)
                if sub is None:
                    parecidos = get_close_matches(nome, list(subfuncoes), n=1, cutoff=0.9)
                    sub = subfuncoes[parecidos[0]] if parecidos else None
                if sub is None:
                    desconhecidas.add(conta)
                    continue
                codigo, nivel, rotulo = f"{funcao}.{sub}", "subfuncao", f"{funcao}.{sub} - {conta}"
            linha = contas.setdefault(codigo, {
                "codigo_ibge": str(i["cod_ibge"]), "ano": int(i["exercicio"]), "cod_conta": codigo, "conta": rotulo,
                "nivel": nivel, "demonstrativo": "RREO", "periodo": int(i["periodo"]),
                "empenhado_centavos": 0, "liquidado_centavos": 0, "pago_centavos": 0, "dotacao_centavos": 0,
            })
            linha[campo] += para_centavos(i.get("valor"))  # subfunção repetida em blocos "intra" já filtrados
    if desconhecidas:
        logger.debug("Subfunções do RREO sem código: %s", sorted(desconhecidas))
    return list(contas.values())


def coletar_rreo(
    cliente: ClienteJson,
    db: Session,
    s: Settings,
    resumo: Resumo,
    ufs: list[str] | None = None,
    forcar: bool = False,
    progresso: bool = True,
    hoje: date | None = None,
) -> int:
    """Ano corrente pelo RREO: tenta o bimestre esperado e volta até achar um publicado."""
    hoje = hoje or date.today()
    ano, esperado = hoje.year, bimestre_esperado(hoje)
    if esperado < 1:
        logger.info("RREO: nenhum bimestre de %d publicado ainda", ano)
        return 0
    codigos = sincronizar_entes(cliente, db, s)
    if ufs:
        alvo = set(db.scalars(select(EnteSiconfi.codigo_ibge).where(EnteSiconfi.sigla_uf.in_(ufs))))
        codigos = [c for c in codigos if c in alvo]
    atual: dict[str, int | None] = {}
    for codigo, demonstrativo, periodo in db.execute(
        select(ContaMunicipal.codigo_ibge, ContaMunicipal.demonstrativo, func.max(ContaMunicipal.periodo))
        .where(ContaMunicipal.ano == ano).group_by(ContaMunicipal.codigo_ibge, ContaMunicipal.demonstrativo)
    ):
        atual[codigo] = 99 if demonstrativo != "RREO" else periodo  # DCA do ano já chegou: nada a fazer
    pendentes = [c for c in codigos if forcar or (atual.get(c) or 0) < esperado]
    subfuncoes = mapa_subfuncoes(db)
    logger.info("RREO %d: %d municípios a consultar (bimestre esperado: %d)", ano, len(pendentes), esperado)
    total = 0
    for codigo in barra(pendentes, progresso, desc=f"RREO {ano}", unit="mun"):
        try:
            linhas: list[dict[str, Any]] = []
            for periodo in range(esperado, (atual.get(codigo) or 0) if not forcar else 0, -1):
                corpo = cliente.get(
                    f"{s.siconfi_url}/rreo",
                    {"an_exercicio": ano, "nr_periodo": periodo, "co_tipo_demonstrativo": "RREO",
                     "no_anexo": ANEXO_RREO, "id_ente": codigo},
                )
                linhas = contas_do_rreo((corpo or {}).get("items") or [], subfuncoes)
                if linhas:
                    break
            if not linhas:
                continue
            db.execute(delete(ContaMunicipal).where(
                ContaMunicipal.codigo_ibge == codigo, ContaMunicipal.ano == ano, ContaMunicipal.demonstrativo == "RREO"
            ))
            db.execute(insert(ContaMunicipal), linhas)
            db.commit()
            total += len(linhas)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            resumo.registrar_falha(f"RREO {codigo}/{ano}", exc)
    registrar_execucao(db, "siconfi_rreo", total)
    return total


def sincronizar_entes(cliente: ClienteJson, db: Session, s: Settings) -> list[str]:
    """Municípios do Siconfi (com CNPJ da prefeitura). Retorna os códigos IBGE."""
    itens = [e for e in cliente.get(f"{s.siconfi_url}/entes")["items"] if e.get("esfera") == "M"]
    linhas = [
        {
            "codigo_ibge": str(e["cod_ibge"]),
            "nome": e["ente"],
            "sigla_uf": e["uf"],
            "cnpj": (e.get("cnpj") or "").strip() or None,
            "populacao": e.get("populacao"),
            "capital": str(e.get("capital", "")).strip() == "1",
        }
        for e in itens
    ]
    stmt = sqlite_insert(EnteSiconfi).values(linhas)
    db.execute(stmt.on_conflict_do_update(
        index_elements=[EnteSiconfi.codigo_ibge], set_={c: stmt.excluded[c] for c in linhas[0] if c != "codigo_ibge"}
    ))
    db.commit()
    logger.info("%d municípios no Siconfi", len(linhas))
    return [l["codigo_ibge"] for l in linhas]


def coletar_siconfi(
    cliente: ClienteJson,
    db: Session,
    anos: list[int],
    s: Settings,
    resumo: Resumo,
    ufs: list[str] | None = None,
    forcar: bool = False,
    progresso: bool = True,
) -> int:
    codigos = sincronizar_entes(cliente, db, s)
    if ufs:
        alvo = set(db.scalars(select(EnteSiconfi.codigo_ibge).where(EnteSiconfi.sigla_uf.in_(ufs))))
        codigos = [c for c in codigos if c in alvo]
    total = 0
    for ano in anos:
        feitos = set(db.scalars(select(distinct(ContaMunicipal.codigo_ibge)).where(
            ContaMunicipal.ano == ano, ContaMunicipal.demonstrativo.is_not("RREO")
        )))
        pendentes = [c for c in codigos if forcar or c not in feitos]
        logger.info("Siconfi %d: %d municípios a consultar", ano, len(pendentes))
        for codigo in barra(pendentes, progresso, desc=f"Siconfi {ano}", unit="mun"):
            try:
                corpo = cliente.get(
                    f"{s.siconfi_url}/dca",
                    {"an_exercicio": ano, "no_anexo": ANEXO_DESPESA_FUNCAO, "id_ente": codigo},
                )
                linhas = contas_da_dca((corpo or {}).get("items") or [])
                db.execute(delete(ContaMunicipal).where(ContaMunicipal.codigo_ibge == codigo, ContaMunicipal.ano == ano))
                if linhas:
                    db.execute(insert(ContaMunicipal), linhas)
                db.commit()
                total += len(linhas)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                resumo.registrar_falha(f"Siconfi {codigo}/{ano}", exc)
    registrar_execucao(db, "siconfi", total)
    return total


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.siconfi", description=__doc__.splitlines()[0])
    parser.add_argument("--ano", type=int, nargs="+", help="anos (padrão: os fechados entre ANOS)")
    parser.add_argument("--uf", nargs="+", help="só estas UFs (ex.: PE)")
    parser.add_argument("--forcar", action="store_true")
    parser.add_argument("--rreo", action="store_true", help="ano corrente pelo RREO bimestral (em vez da DCA)")
    parser.add_argument("--sem-progresso", action="store_true")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)
    s = get_settings()
    logging.basicConfig(
        level=(args.log_level or s.log_level).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # A DCA de um ano sai até abril do ano seguinte: só anos fechados.
    anos = sorted(args.ano or [a for a in s.anos if a < date.today().year])
    init_db()
    resumo = Resumo()
    db = SessionLocal()
    inicio = time.monotonic()
    try:
        if args.rreo:
            total = coletar_rreo(
                ClienteJson(s.siconfi_req_per_sec, max(s.timeout, 120)), db, s, resumo,
                [u.upper() for u in args.uf] if args.uf else None, args.forcar,
                progresso=not args.sem_progresso and sys.stderr.isatty(),
            )
            logger.info("RREO: %d contas gravadas", total)
            return 1 if resumo.falhas else 0
        total = coletar_siconfi(
            ClienteJson(s.siconfi_req_per_sec, max(s.timeout, 120)), db, anos, s, resumo,
            [u.upper() for u in args.uf] if args.uf else None, args.forcar,
            progresso=not args.sem_progresso and sys.stderr.isatty(),
        )
        logger.info("Siconfi: %d contas gravadas", total)
    finally:
        db.close()
    logger.info("Siconfi concluído em %.1f min; falhas: %d", (time.monotonic() - inicio) / 60, len(resumo.falhas))
    for falha in resumo.falhas[:20]:
        logger.info("  - %s", falha)
    return 1 if resumo.falhas else 0


if __name__ == "__main__":
    sys.exit(main())
