"""Sinais de alerta sobre os gastos da cota parlamentar.

Cada sinal é um "vale olhar", não uma acusação: aponta padrões que merecem
verificação por quem lê a nota fiscal. Os alertas são recalculados por inteiro
depois de cada coleta e gravados na tabela `alertas`.

Federais, estaduais (verba da ALEPE) e municipais (empenhos do TCE-PE) passam
pelas regras que fazem sentido para cada fonte (ver `REGRAS_POR_FONTE`).

Tipos:
    concentracao         fornecedor pequeno com grande fatia da cota de um deputado
    notas_sequenciais    notas fiscais de um fornecedor em sequência quase contínua
    empresa_nova         empresa aberta pouco antes do primeiro pagamento
    fornecedor_inativo   pagamento depois de o CNPJ ser baixado/inapto/suspenso
    mei_acima_limite     MEI que recebeu da cota mais que o limite anual do MEI
    divulgacao_eleitoral gasto com divulgação que dispara em ano de eleição
    padrao_atipico       muitas notas em fim de semana ou com valores redondos
"""

from __future__ import annotations

import logging
import re
import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, insert, text
from sqlalchemy.orm import Session

from civic.cleaning import normalizar_nome
from civic.config import Settings
from civic.models import Alerta

logger = logging.getLogger("civic.alertas")


@dataclass(frozen=True)
class Fonte:
    """Uma origem de gastos, vista pelas regras como (pessoa, ano, mês, cnpj, fornecedor, data, valor)."""

    esfera: str
    coluna: str  # coluna de `alertas` que identifica quem gastou
    gastos: str  # SELECT com as colunas padronizadas
    quem: str
    evento: str  # "primeira nota" / "primeiro empenho"
    antes_de: str  # "da primeira nota" / "do primeiro empenho"


FONTES: dict[str, Fonte] = {
    "federal": Fonte(
        "federal",
        "deputado_id",
        "SELECT deputado_id AS pessoa, ano, mes, cnpj_cpf AS cnpj, fornecedor, data_documento AS data, "
        "valor_liquido_centavos AS valor, tipo_pessoa, tipo_despesa AS tipo FROM despesas",
        "o deputado",
        "primeira nota",
        "da primeira nota",
    ),
    "estadual": Fonte(
        "estadual",
        "deputado_estadual_id",
        "SELECT deputado_estadual_id AS pessoa, ano, mes, cnpj_cpf AS cnpj, fornecedor, data, "
        "valor_centavos AS valor, tipo_pessoa, rubrica_nome AS tipo FROM verbas_indenizatorias",
        "o deputado estadual",
        "primeira nota",
        "da primeira nota",
    ),
    "senado": Fonte(
        "senado",
        "senador_id",
        "SELECT senador_id AS pessoa, ano, mes, cnpj_cpf AS cnpj, fornecedor, data, "
        "valor_centavos AS valor, tipo_pessoa, tipo_despesa AS tipo FROM despesas_senado "
        "WHERE senador_id IS NOT NULL",
        "o senador",
        "primeira nota",
        "da primeira nota",
    ),
    "pncp": Fonte(
        "municipal",
        "orgao_cnpj",
        "SELECT orgao_cnpj AS pessoa, ano, CAST(strftime('%m', data_assinatura) AS INTEGER) AS mes, "
        "fornecedor_ni AS cnpj, fornecedor_nome AS fornecedor, data_assinatura AS data, "
        "valor_global_centavos AS valor, tipo_pessoa, categoria AS tipo FROM contratos_pncp "
        "WHERE tipo_pessoa = 'PJ' AND orgao_cnpj IS NOT NULL",
        "o órgão contratante",
        "primeiro contrato",
        "do primeiro contrato",
    ),
    "municipal": Fonte(
        "municipal",
        "unidade_gestora_id",
        "SELECT unidade_gestora_id AS pessoa, ano, mes, cpf_cnpj AS cnpj, fornecedor, data_empenho AS data, "
        "valor_pago_centavos AS valor, tipo_pessoa, elemento_despesa AS tipo FROM despesas_municipais "
        "WHERE valor_pago_centavos > 0",
        "o órgão",
        "primeiro empenho",
        "do primeiro empenho",
    ),
}

FORNECEDOR_NICHO_MAX_DEPUTADOS = 5
LIMITE_ATENCAO_CENTAVOS = 1_000_000  # cruzamentos com doador: "atenção" a partir de R$ 10 mil
TIPOS_NOTA_FISCAL = ("Nota Fiscal", "Nota Fiscal Eletrônica")
SITUACOES_INATIVAS = ("BAIXADA", "INAPTA", "SUSPENSA", "NULA")

TITULOS_TIPO: dict[str, str] = {
    "concentracao": "Fornecedor concentrado",
    "notas_sequenciais": "Notas fiscais em sequência",
    "empresa_nova": "Empresa aberta pouco antes",
    "fornecedor_inativo": "Pagamento a CNPJ inativo",
    "mei_acima_limite": "MEI acima do limite",
    "divulgacao_eleitoral": "Divulgação em ano eleitoral",
    "padrao_atipico": "Padrão atípico de notas",
    "servidor_socio": "Servidor sócio de fornecedor",
    "eleito_socio": "Eleito com nome de sócio de fornecedor",
    "doador_socio": "Doador de campanha sócio de fornecedor",
    "pix_parado": "Emenda Pix sem gasto registrado",
    "pix_custeio": "Emenda Pix gasta em custeio",
    "pix_gasto_maior": "Gasto com Emenda Pix maior que o recebido",
    "contrato_capital": "Contratos muito acima do capital social",
}
CONTRATO_CAPITAL_FATOR = 10
CONTRATO_CAPITAL_MINIMO = 100_000_000  # R$ 1 milhão

# Nos cruzamentos, CROSS JOIN fixa a ordem das tabelas no SQLite: primeiro acha o sócio pelo nome
# (poucos casos) e só então os pagamentos daquele CNPJ, em vez de ler todos os pagamentos da cidade.
# Quadro de sócios PF sem repetição: a mesma pessoa pode aparecer mais de uma vez na mesma empresa
# (qualificações diferentes), e cada repetição multiplicaria os valores somados no cruzamento.
SOCIOS_PF = """(SELECT cnpj_basico, nome_normalizado, documento, MAX(qualificacao) AS qualificacao
           FROM socios WHERE tipo = 'PF' GROUP BY cnpj_basico, nome_normalizado, documento)"""
# Idem, só por nome (quando a outra ponta não tem CPF, como os candidatos do TSE).
SOCIOS_PF_NOME = """(SELECT cnpj_basico, nome_normalizado, MAX(qualificacao) AS qualificacao
           FROM socios WHERE tipo = 'PF' GROUP BY cnpj_basico, nome_normalizado)"""

MESES_ABREV = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
PIX_PARADO_JANELA_MESES = 24
PIX_PARADO_FRACAO_GASTA = 0.2
PIX_CORRENTE_MAXIMO = 0.3  # Constituição, art. 166-A, § 5º: ao menos 70% em despesa de capital
PIX_GASTO_MAIOR_FATOR = 1.2


def formatar_brl(centavos: int) -> str:
    """123456 -> 'R$ 1.234,56'."""
    reais, cents = divmod(abs(int(centavos)), 100)
    texto = f"{reais:,}".replace(",", ".")
    return f"{'-' if centavos < 0 else ''}R$ {texto},{cents:02d}"


def pct(valor: float) -> str:
    return f"{valor * 100:.0f}%"


def _linhas(db: Session, sql: str, **params: Any) -> list[Any]:
    return list(db.execute(text(sql), params).mappings())


def _data(valor: Any) -> date | None:
    if valor is None or isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


# --------------------------------------------------------------------------- regras


def alertas_concentracao(db: Session, s: Settings) -> list[dict[str, Any]]:
    """Fornecedor que atende poucos deputados e leva grande fatia da cota de um deles no ano."""
    minimo = round(s.alerta_concentracao_minimo * 100)
    linhas = _linhas(
        db,
        """
        WITH forn AS (
            SELECT cnpj_cpf, COUNT(DISTINCT deputado_id) AS deputados
            FROM despesas WHERE tipo_pessoa = 'PJ' GROUP BY cnpj_cpf
        ), por_dep AS (
            SELECT deputado_id, ano, SUM(valor_liquido_centavos) AS total
            FROM despesas GROUP BY deputado_id, ano
        )
        SELECT d.deputado_id, d.ano, d.cnpj_cpf, MAX(d.fornecedor) AS fornecedor,
               SUM(d.valor_liquido_centavos) AS valor, p.total, f.deputados
        FROM despesas d
        JOIN forn f ON f.cnpj_cpf = d.cnpj_cpf
        JOIN por_dep p ON p.deputado_id = d.deputado_id AND p.ano = d.ano
        WHERE d.tipo_pessoa = 'PJ' AND f.deputados <= :max_dep
        GROUP BY d.deputado_id, d.ano, d.cnpj_cpf
        HAVING SUM(d.valor_liquido_centavos) >= :minimo
           AND SUM(d.valor_liquido_centavos) * 1.0 / p.total >= :pct
        """,
        max_dep=FORNECEDOR_NICHO_MAX_DEPUTADOS,
        minimo=minimo,
        pct=s.alerta_concentracao_pct,
    )
    alertas = []
    for r in linhas:
        fatia = r["valor"] / r["total"]
        atende = "só este deputado" if r["deputados"] == 1 else f"apenas {r['deputados']} deputados"
        alertas.append(
            {
                "tipo": "concentracao",
                "gravidade": "alta" if fatia >= 0.5 else "media",
                "pessoa": r["deputado_id"],
                "cnpj": r["cnpj_cpf"],
                "ano": r["ano"],
                "valor_centavos": r["valor"],
                "titulo": f"{r['fornecedor']} recebeu {pct(fatia)} da cota em {r['ano']}",
                "descricao": (
                    f"{formatar_brl(r['valor'])} de {formatar_brl(r['total'])} reembolsados no ano foram para "
                    f"esta empresa, que na cota atende {atende}."
                ),
            }
        )
    return alertas


def numeros_em_sequencia(numeros: list[str], minimo: int) -> tuple[int, int, int] | None:
    """Analisa números de notas fiscais de um mesmo fornecedor.

    Retorna (quantidade, menor, maior) se houver pelo menos `minimo` números e
    80% ou mais dos intervalos entre eles forem de no máximo 2, sinal de que o
    fornecedor emite poucas notas além dessas. Caso contrário, `None`.
    """
    valores = sorted(
        {int(d) for n in numeros if (d := re.sub(r"\D", "", n or "")) and len(d) <= 12 and int(d) > 0}
    )
    if len(valores) < minimo:
        return None
    pequenos = sum(1 for a, b in zip(valores, valores[1:]) if b - a <= 2)
    if pequenos / (len(valores) - 1) >= 0.8:
        return len(valores), valores[0], valores[-1]
    return None


def alertas_notas_sequenciais(db: Session, s: Settings) -> list[dict[str, Any]]:
    linhas = _linhas(
        db,
        """
        SELECT deputado_id, ano, cnpj_cpf, MAX(fornecedor) AS fornecedor,
               GROUP_CONCAT(num_documento, '|') AS numeros, SUM(valor_liquido_centavos) AS valor
        FROM despesas
        WHERE tipo_pessoa = 'PJ' AND tipo_documento IN (:nf1, :nf2) AND num_documento IS NOT NULL
        GROUP BY deputado_id, ano, cnpj_cpf
        HAVING COUNT(*) >= :minimo
        """,
        nf1=TIPOS_NOTA_FISCAL[0],
        nf2=TIPOS_NOTA_FISCAL[1],
        minimo=s.alerta_sequencia_min_notas,
    )
    alertas = []
    for r in linhas:
        resultado = numeros_em_sequencia(r["numeros"].split("|"), s.alerta_sequencia_min_notas)
        if resultado is None:
            continue
        qtd, menor, maior = resultado
        alertas.append(
            {
                "tipo": "notas_sequenciais",
                "gravidade": "media",
                "pessoa": r["deputado_id"],
                "cnpj": r["cnpj_cpf"],
                "ano": r["ano"],
                "valor_centavos": r["valor"],
                "titulo": f"{qtd} notas quase seguidas de {r['fornecedor']} em {r['ano']}",
                "descricao": (
                    f"As notas vão do nº {menor} ao nº {maior}, quase sem intervalo. Isso sugere que a empresa "
                    "emitiu poucas notas para outros clientes no período."
                ),
            }
        )
    return alertas


def alertas_empresa_nova(db: Session, s: Settings, f: Fonte) -> list[dict[str, Any]]:
    linhas = _linhas(
        db,
        f"""
        WITH g AS ({f.gastos})
        SELECT g.pessoa, g.cnpj, MAX(g.fornecedor) AS fornecedor, MIN(g.data) AS primeira,
               SUM(g.valor) AS valor, fo.data_inicio_atividade AS abertura
        FROM g JOIN fornecedores fo ON fo.cnpj = g.cnpj
        WHERE g.data IS NOT NULL AND fo.data_inicio_atividade IS NOT NULL
        GROUP BY g.pessoa, g.cnpj
        """,
    )
    alertas = []
    for r in linhas:
        primeira, abertura = _data(r["primeira"]), _data(r["abertura"])
        if primeira is None or abertura is None:
            continue
        dias = (primeira - abertura).days
        if not 0 <= dias <= s.alerta_empresa_nova_dias:
            continue
        alertas.append(
            {
                "tipo": "empresa_nova",
                "gravidade": "alta" if dias <= 90 and r["valor"] >= 1_000_000 else "media",
                "pessoa": r["pessoa"],
                "cnpj": r["cnpj"],
                "ano": primeira.year,
                "valor_centavos": r["valor"],
                "titulo": f"{r['fornecedor']} foi aberta {dias} dias antes {f.antes_de}",
                "descricao": (
                    f"CNPJ aberto em {abertura:%d/%m/%Y}; {f.evento} para {f.quem} em {primeira:%d/%m/%Y}. "
                    f"Total recebido: {formatar_brl(r['valor'])}."
                ),
            }
        )
    return alertas


def alertas_fornecedor_inativo(db: Session, _s: Settings, f: Fonte) -> list[dict[str, Any]]:
    situacoes = ",".join(f"'{x}'" for x in SITUACOES_INATIVAS)
    linhas = _linhas(
        db,
        f"""
        WITH g AS ({f.gastos})
        SELECT g.pessoa, g.cnpj, MAX(g.fornecedor) AS fornecedor, fo.situacao_cadastral AS situacao,
               fo.data_situacao_cadastral AS desde, COUNT(*) AS qtd, SUM(g.valor) AS valor, MIN(g.ano) AS ano
        FROM g JOIN fornecedores fo ON fo.cnpj = g.cnpj
        WHERE fo.situacao_cadastral IN ({situacoes})
          AND fo.data_situacao_cadastral IS NOT NULL
          AND g.data > fo.data_situacao_cadastral
        GROUP BY g.pessoa, g.cnpj
        """,
    )
    documento = "empenhos" if f.esfera == "municipal" else "notas"
    return [
        {
            "tipo": "fornecedor_inativo",
            "gravidade": "alta",
            "pessoa": r["pessoa"],
            "cnpj": r["cnpj"],
            "ano": r["ano"],
            "valor_centavos": r["valor"],
            "titulo": f"{r['qtd']} {documento} de {r['fornecedor']} depois de o CNPJ ficar {r['situacao'].lower()}",
            "descricao": (
                f"A Receita registra o CNPJ como {r['situacao'].lower()} desde {_data(r['desde']):%d/%m/%Y}, "
                f"mas há {documento} com data posterior somando {formatar_brl(r['valor'])}."
            ),
        }
        for r in linhas
    ]


def alertas_mei_acima_limite(db: Session, s: Settings) -> list[dict[str, Any]]:
    """MEI que, somando todas as fontes (cotas, verba estadual, prefeituras e contratos), passou do limite anual.

    Gera um alerta para cada pagador, com a fonte já definida.
    """
    limite = round(s.alerta_mei_limite_anual * 100)
    uniao = " UNION ALL ".join(
        f"SELECT '{nome}' AS fonte, pessoa, ano, cnpj, fornecedor, valor FROM ({f.gastos})" for nome, f in FONTES.items()
    )
    linhas = _linhas(
        db,
        f"""
        WITH g AS ({uniao}),
        anual AS (
            SELECT g.cnpj, g.ano, SUM(g.valor) AS total
            FROM g JOIN fornecedores fo ON fo.cnpj = g.cnpj
            WHERE fo.data_opcao_mei IS NOT NULL
              AND fo.data_opcao_mei <= (g.ano || '-12-31')
              AND (fo.data_exclusao_mei IS NULL OR fo.data_exclusao_mei >= (g.ano || '-01-01'))
            GROUP BY g.cnpj, g.ano
            HAVING SUM(g.valor) > :limite
        )
        SELECT g.fonte, g.pessoa, g.cnpj, g.ano, MAX(g.fornecedor) AS fornecedor,
               SUM(g.valor) AS valor, a.total
        FROM g JOIN anual a ON a.cnpj = g.cnpj AND a.ano = g.ano
        GROUP BY g.fonte, g.pessoa, g.cnpj, g.ano
        """,
        limite=limite,
    )
    return [
        {
            "fonte": r["fonte"],
            "tipo": "mei_acima_limite",
            "gravidade": "alta",
            "pessoa": r["pessoa"],
            "cnpj": r["cnpj"],
            "ano": r["ano"],
            "valor_centavos": r["valor"],
            "titulo": f"MEI {r['fornecedor']} recebeu {formatar_brl(r['total'])} de dinheiro público em {r['ano']}",
            "descricao": (
                f"O limite de faturamento do MEI é {formatar_brl(limite)} por ano. Somando cotas de deputados e "
                f"senadores, verba de deputado estadual, pagamentos e contratos de prefeituras, esta empresa recebeu "
                f"{formatar_brl(r['total'])} ({formatar_brl(r['valor'])} deste pagador)."
            ),
        }
        for r in linhas
    ]


def alertas_divulgacao_eleitoral(db: Session, s: Settings, f: Fonte) -> list[dict[str, Any]]:
    """Divulgação no 1º semestre de ano de eleição geral vs. o mesmo período do ano anterior."""
    minimo = round(s.alerta_divulgacao_minimo * 100)
    linhas = _linhas(
        db,
        f"""
        WITH g AS ({f.gastos})
        SELECT pessoa, ano, SUM(valor) AS total FROM g
        WHERE tipo LIKE 'DIVULGA%' AND mes <= 6
        GROUP BY pessoa, ano
        """,
    )
    por_pessoa: dict[int, dict[int, int]] = defaultdict(dict)
    for r in linhas:
        por_pessoa[r["pessoa"]][r["ano"]] = r["total"]
    alertas = []
    for pessoa, anos in por_pessoa.items():
        for ano, total in anos.items():
            if ano % 4 != 2 or total < minimo:
                continue
            anterior = anos.get(ano - 1, 0)
            if anterior and total >= s.alerta_divulgacao_fator * anterior:
                fator = total / anterior
                alertas.append(
                    {
                        "tipo": "divulgacao_eleitoral",
                        "gravidade": "media",
                        "pessoa": pessoa,
                        "cnpj": None,
                        "ano": ano,
                        "valor_centavos": total,
                        "titulo": f"Divulgação {fator:.1f}× maior no 1º semestre de {ano}, ano de eleição",
                        "descricao": (
                            f"De janeiro a junho de {ano} foram {formatar_brl(total)} em divulgação do mandato, "
                            f"contra {formatar_brl(anterior)} no mesmo período de {ano - 1}."
                        ),
                    }
                )
    return alertas


def alertas_padrao_atipico(db: Session, s: Settings) -> list[dict[str, Any]]:
    """Proporção de notas em fim de semana e de valores redondos, comparada à mediana do ano."""
    linhas = _linhas(
        db,
        """
        SELECT deputado_id, ano, COUNT(*) AS qtd,
               SUM(CASE WHEN strftime('%w', data_documento) IN ('0', '6') THEN 1 ELSE 0 END) AS fds,
               SUM(CASE WHEN valor_documento_centavos >= 100000 THEN 1 ELSE 0 END) AS grandes,
               SUM(CASE WHEN valor_documento_centavos >= 100000 AND valor_documento_centavos % 10000 = 0
                        THEN 1 ELSE 0 END) AS redondos
        FROM despesas
        WHERE data_documento IS NOT NULL
        GROUP BY deputado_id, ano
        HAVING COUNT(*) >= :minimo
        """,
        minimo=s.alerta_padrao_min_notas,
    )
    por_ano: dict[int, list[Any]] = defaultdict(list)
    for r in linhas:
        por_ano[r["ano"]].append(r)

    # (numerador, denominador, rótulo, piso, texto)
    regras: list[tuple[str, str, str, float, Callable[[str, str], str]]] = [
        ("fds", "qtd", "das notas com data em fim de semana", 0.20,
         lambda v, m: f"{v} das notas têm data de sábado ou domingo; a mediana dos deputados no ano é {m}."),
        ("redondos", "grandes", "das notas acima de R$ 1.000 com valor redondo", 0.30,
         lambda v, m: f"{v} das notas de R$ 1.000 ou mais têm valor redondo (múltiplo de R$ 100); a mediana é {m}."),
    ]
    alertas = []
    for ano, grupo in por_ano.items():
        for campo, base, rotulo, piso, texto in regras:
            validos = [r for r in grupo if r[base] >= 10]
            if not validos:
                continue
            proporcoes = {r["deputado_id"]: r[campo] / r[base] for r in validos}
            mediana = statistics.median(proporcoes.values())
            corte = max(3 * mediana, piso)
            for r in validos:
                valor = proporcoes[r["deputado_id"]]
                if valor >= corte:
                    alertas.append(
                        {
                            "tipo": "padrao_atipico",
                            "gravidade": "media",
                            "pessoa": r["deputado_id"],
                            "cnpj": None,
                            "ano": ano,
                            "valor_centavos": 0,
                            "titulo": f"{pct(valor)} {rotulo} em {ano}",
                            "descricao": texto(pct(valor), pct(mediana)),
                        }
                    )
    return alertas


def alertas_servidor_socio(db: Session, _s: Settings) -> list[dict[str, Any]]:
    """Servidor ou vereador (TCE-PE) que é sócio de empresa paga por órgão do mesmo município.

    O vínculo usa nome completo + 6 dígitos centrais do CPF (o TCE e a Receita
    publicam o CPF mascarado do mesmo jeito), o que torna o casamento confiável.
    Só conta fornecedor que é empresa privada (natureza 2xxx, menos empresa pública
    e economia mista) na base da Receita: em órgãos públicos e associações, o
    "sócio" é o dirigente nomeado.

    A pessoa pode ter vários vínculos (cargos): ela vira uma linha só antes do
    cruzamento, senão os valores dos empenhos se multiplicam. O CNPJ é casado pela
    faixa "raiz + 000000 a 999999", que usa o índice (substr() leria a tabela inteira).
    """
    linhas = _linhas(
        db,
        f"""
        WITH vinculos AS (
            SELECT sv.nome_normalizado, sv.cpf_meio, ug.codigo_municipio_tce AS municipio, sv.nome, sv.cargo,
                   sv.data_admissao, ug.nome AS orgao,
                   ROW_NUMBER() OVER (PARTITION BY sv.nome_normalizado, sv.cpf_meio, ug.codigo_municipio_tce
                                      ORDER BY sv.data_admissao DESC) AS ordem,
                   COUNT(*) OVER (PARTITION BY sv.nome_normalizado, sv.cpf_meio, ug.codigo_municipio_tce) AS qtd_vinculos,
                   MIN(sv.data_admissao) OVER (PARTITION BY sv.nome_normalizado, sv.cpf_meio, ug.codigo_municipio_tce)
                       AS primeira_admissao
            FROM servidores_municipais sv
            JOIN unidades_gestoras ug ON ug.id = sv.unidade_gestora_id
            WHERE sv.cpf_meio IS NOT NULL
        ),
        pessoas AS (SELECT * FROM vinculos WHERE ordem = 1)
        SELECT p.nome AS servidor, p.cargo, p.data_admissao AS admissao, p.orgao AS orgao_servidor,
               p.qtd_vinculos, p.primeira_admissao, so.qualificacao,
               d.unidade_gestora_id AS pagador, ug_d.nome AS orgao_pagador,
               MAX(d.cpf_cnpj) AS cnpj, MAX(d.fornecedor) AS fornecedor,
               SUM(d.valor_pago_centavos) AS valor, MIN(d.ano) AS ano, SUM(d.qtd_empenhos) AS qtd
        FROM pessoas p
        JOIN {SOCIOS_PF} so ON so.nome_normalizado = p.nome_normalizado AND so.documento = p.cpf_meio
        JOIN despesas_municipais d ON d.cpf_cnpj BETWEEN so.cnpj_basico || '000000' AND so.cnpj_basico || '999999'
                                  AND d.tipo_pessoa = 'PJ' AND d.valor_pago_centavos > 0
        JOIN unidades_gestoras ug_d ON ug_d.id = d.unidade_gestora_id AND ug_d.codigo_municipio_tce = p.municipio
        JOIN fornecedores fo ON fo.cnpj = d.cpf_cnpj AND fo.natureza_juridica LIKE '2%'
                            AND fo.natureza_juridica NOT IN ('2011', '2038')
        GROUP BY p.nome_normalizado, p.cpf_meio, d.unidade_gestora_id, so.cnpj_basico
        """,
    )
    alertas = []
    for r in linhas:
        cargo = (r["cargo"] or "servidor").strip().lower()
        data_admissao = _data(r["admissao"])
        primeira = _data(r["primeira_admissao"])
        historico = (
            f" Ao todo, tem {r['qtd_vinculos']} vínculos na base desde {primeira:%d/%m/%Y}."
            if r["qtd_vinculos"] > 1 and primeira else ""
        )
        admissao = (
            f" (vínculo mais recente, admissão em {data_admissao:%d/%m/%Y}; a base não informa desligamento)"
            if data_admissao else ""
        )
        alertas.append(
            {
                "tipo": "servidor_socio",
                "gravidade": "alta",
                "esfera": "municipal",
                "unidade_gestora_id": r["pagador"],
                "cnpj": r["cnpj"],
                "ano": r["ano"],
                "valor_centavos": r["valor"],
                "titulo": f"{r['servidor'].title()} ({cargo}) é sócio(a) de {r['fornecedor']}, paga pela {r['orgao_pagador']}",
                "descricao": (
                    f"Na base de pessoal do TCE-PE, {r['servidor'].title()} aparece como {cargo} na {r['orgao_servidor']}"
                    f"{admissao}.{historico} "
                    f"Na Receita, a mesma pessoa (nome e 6 dígitos do CPF iguais) é sócia ({(r['qualificacao'] or 'sócio').lower()}) "
                    f"da empresa, que recebeu {formatar_brl(r['valor'])} em {r['qtd']} empenho(s)."
                ),
            }
        )
    return alertas


def alertas_eleito_socio(db: Session, _s: Settings) -> list[dict[str, Any]]:
    """Eleito em 2024 (prefeito, vice, vereador) com o mesmo nome completo de um sócio de
    empresa contratada (PNCP) ou paga (TCE-PE) por órgão do município onde foi eleito.

    O TSE não publica mais o CPF dos candidatos, então o vínculo é só pelo nome
    (com pelo menos 3 palavras): é um "vale olhar", não uma confirmação. Só conta
    fornecedor que é empresa privada (natureza 2xxx, menos empresa pública e
    economia mista): prefeitos aparecem como "sócios" de associações e
    autarquias por serem dirigentes natos. E o nome precisa ser único entre as
    candidaturas do ano, para reduzir homônimos ("João Batista da Silva").
    """
    contratos = _linhas(
        db,
        f"""
        SELECT c.nome, c.cargo, c.sigla_partido, c.municipio_ibge, so.qualificacao,
               p.orgao_cnpj AS pagador, MAX(p.orgao_nome) AS orgao, MAX(p.fornecedor_ni) AS cnpj,
               MAX(p.fornecedor_nome) AS fornecedor, SUM(p.valor_global_centavos) AS valor,
               MIN(p.ano) AS ano, COUNT(*) AS qtd
        FROM candidatos c
        CROSS JOIN {SOCIOS_PF_NOME} so ON so.nome_normalizado = c.nome_normalizado
        CROSS JOIN contratos_pncp p ON p.fornecedor_ni BETWEEN so.cnpj_basico || '000000' AND so.cnpj_basico || '999999' AND p.tipo_pessoa = 'PJ'
                             AND p.municipio_ibge = c.municipio_ibge
        JOIN fornecedores fo ON fo.cnpj = p.fornecedor_ni AND fo.natureza_juridica LIKE '2%' AND fo.natureza_juridica NOT IN ('2011', '2038')
        WHERE c.eleito = 1 AND c.ano = 2024 AND length(c.nome_normalizado) - length(replace(c.nome_normalizado, ' ', '')) >= 2
          AND c.nome_normalizado IN (SELECT nome_normalizado FROM candidatos WHERE ano = 2024
                                     GROUP BY nome_normalizado HAVING COUNT(*) = 1)
        GROUP BY c.sq_candidato, p.orgao_cnpj, so.cnpj_basico
        """,
    )
    empenhos = _linhas(
        db,
        f"""
        SELECT c.nome, c.cargo, c.sigla_partido, c.municipio_ibge, so.qualificacao,
               d.unidade_gestora_id AS pagador, MAX(ug.nome) AS orgao, MAX(d.cpf_cnpj) AS cnpj,
               MAX(d.fornecedor) AS fornecedor, SUM(d.valor_pago_centavos) AS valor,
               MIN(d.ano) AS ano, COUNT(*) AS qtd
        FROM candidatos c
        CROSS JOIN {SOCIOS_PF_NOME} so ON so.nome_normalizado = c.nome_normalizado
        CROSS JOIN despesas_municipais d ON d.cpf_cnpj BETWEEN so.cnpj_basico || '000000' AND so.cnpj_basico || '999999'
                                  AND d.tipo_pessoa = 'PJ' AND d.valor_pago_centavos > 0
        JOIN unidades_gestoras ug ON ug.id = d.unidade_gestora_id
        JOIN municipios m ON m.codigo_ibge = c.municipio_ibge AND m.sigla_uf = ug.sigla_uf
                         AND m.nome_normalizado = ug.municipio_normalizado
        JOIN fornecedores fo ON fo.cnpj = d.cpf_cnpj AND fo.natureza_juridica LIKE '2%' AND fo.natureza_juridica NOT IN ('2011', '2038')
        WHERE c.eleito = 1 AND c.ano = 2024 AND length(c.nome_normalizado) - length(replace(c.nome_normalizado, ' ', '')) >= 2
          AND c.nome_normalizado IN (SELECT nome_normalizado FROM candidatos WHERE ano = 2024
                                     GROUP BY nome_normalizado HAVING COUNT(*) = 1)
        GROUP BY c.sq_candidato, d.unidade_gestora_id, so.cnpj_basico
        """,
    )
    alertas = []
    for r, fonte in [(r, "pncp") for r in contratos] + [(r, "tce") for r in empenhos]:
        cargo = (r["cargo"] or "").lower()
        forma = "contratos" if fonte == "pncp" else "empenhos pagos"
        alertas.append(
            {
                "tipo": "eleito_socio",
                "gravidade": "media",
                "esfera": "municipal",
                "orgao_cnpj": r["pagador"] if fonte == "pncp" else None,
                "unidade_gestora_id": r["pagador"] if fonte == "tce" else None,
                "municipio_ibge": r["municipio_ibge"],
                "cnpj": r["cnpj"],
                "ano": r["ano"],
                "valor_centavos": r["valor"],
                "titulo": f"{cargo.capitalize()} eleito(a) {r['nome'].title()} tem o mesmo nome de sócio(a) de {r['fornecedor']}",
                "descricao": (
                    f"{r['nome'].title()} ({r['sigla_partido'] or 'sem partido'}) foi eleito(a) {cargo} em 2024. Um(a) sócio(a) "
                    f"({(r['qualificacao'] or 'sócio').lower()}) da empresa tem o nome idêntico, e a empresa tem {r['qtd']} "
                    f"{forma} com {r['orgao']} somando {formatar_brl(r['valor'])}. O TSE não publica o CPF dos candidatos: "
                    "pode ser homônimo."
                ),
            }
        )
    return alertas


def alertas_doador_socio(db: Session, _s: Settings) -> list[dict[str, Any]]:
    """Doador (pessoa física) de campanha de eleito em 2024 que é sócio de empresa contratada (PNCP)
    ou paga (TCE-PE) por órgão do mesmo município. Vínculo por nome + 6 dígitos do CPF."""
    # Soma as doações por doador e candidato antes de cruzar (senão os contratos multiplicam o valor).
    comum = f"""
        FROM (
            SELECT sq_candidato, doador_nome_normalizado, doador_cpf_meio, MAX(doador_nome) AS doador_nome,
                   SUM(valor_centavos) AS valor_centavos
            FROM doacoes_campanha
            GROUP BY sq_candidato, doador_nome_normalizado, doador_cpf_meio
        ) dc
        CROSS JOIN {SOCIOS_PF} so ON so.nome_normalizado = dc.doador_nome_normalizado
                      AND so.documento = dc.doador_cpf_meio
        CROSS JOIN candidatos c ON c.sq_candidato = dc.sq_candidato AND c.eleito = 1
    """
    contratos = _linhas(
        db,
        f"""
        SELECT dc.doador_nome, MAX(dc.valor_centavos) AS doado, c.nome AS eleito, c.cargo, c.sigla_partido,
               c.municipio_ibge, p.orgao_cnpj AS pagador, MAX(p.orgao_nome) AS orgao, MAX(p.fornecedor_ni) AS cnpj,
               MAX(p.fornecedor_nome) AS fornecedor, SUM(p.valor_global_centavos) AS valor, MIN(p.ano) AS ano,
               COUNT(DISTINCT p.numero_controle) AS qtd
        {comum}
        CROSS JOIN contratos_pncp p ON p.fornecedor_ni BETWEEN so.cnpj_basico || '000000' AND so.cnpj_basico || '999999' AND p.tipo_pessoa = 'PJ'
                             AND p.municipio_ibge = c.municipio_ibge
        JOIN fornecedores fo ON fo.cnpj = p.fornecedor_ni AND fo.natureza_juridica LIKE '2%'
                            AND fo.natureza_juridica NOT IN ('2011', '2038')
        GROUP BY dc.doador_nome_normalizado, dc.doador_cpf_meio, c.sq_candidato, p.orgao_cnpj, so.cnpj_basico
        """,
    )
    empenhos = _linhas(
        db,
        f"""
        SELECT dc.doador_nome, MAX(dc.valor_centavos) AS doado, c.nome AS eleito, c.cargo, c.sigla_partido,
               c.municipio_ibge, d.unidade_gestora_id AS pagador, MAX(ug.nome) AS orgao, MAX(d.cpf_cnpj) AS cnpj,
               MAX(d.fornecedor) AS fornecedor, SUM(d.valor_pago_centavos) AS valor, MIN(d.ano) AS ano,
               COUNT(DISTINCT d.id) AS qtd
        {comum}
        CROSS JOIN despesas_municipais d ON d.cpf_cnpj BETWEEN so.cnpj_basico || '000000' AND so.cnpj_basico || '999999'
                                  AND d.tipo_pessoa = 'PJ' AND d.valor_pago_centavos > 0
        JOIN unidades_gestoras ug ON ug.id = d.unidade_gestora_id
        JOIN municipios m ON m.codigo_ibge = c.municipio_ibge AND m.sigla_uf = ug.sigla_uf
                         AND m.nome_normalizado = ug.municipio_normalizado
        JOIN fornecedores fo ON fo.cnpj = d.cpf_cnpj AND fo.natureza_juridica LIKE '2%'
                            AND fo.natureza_juridica NOT IN ('2011', '2038')
        GROUP BY dc.doador_nome_normalizado, dc.doador_cpf_meio, c.sq_candidato, d.unidade_gestora_id, so.cnpj_basico
        """,
    )
    alertas = []
    for r, fonte in [(r, "pncp") for r in contratos] + [(r, "tce") for r in empenhos]:
        forma = "contratos" if fonte == "pncp" else "empenhos pagos"
        alertas.append(
            {
                "tipo": "doador_socio",
                "gravidade": "alta" if r["valor"] >= LIMITE_ATENCAO_CENTAVOS else "media",
                "esfera": "municipal",
                "orgao_cnpj": r["pagador"] if fonte == "pncp" else None,
                "unidade_gestora_id": r["pagador"] if fonte == "tce" else None,
                "municipio_ibge": r["municipio_ibge"],
                "cnpj": r["cnpj"],
                "ano": r["ano"],
                "valor_centavos": r["valor"],
                "titulo": (
                    f"Doador(a) da campanha de {r['eleito'].title()} ({(r['cargo'] or '').lower()}) é sócio(a) de "
                    f"{r['fornecedor']}"
                ),
                "descricao": (
                    f"{r['doador_nome'].title()} doou {formatar_brl(r['doado'])} à campanha de {r['eleito'].title()} "
                    f"({r['sigla_partido'] or 'sem partido'}), eleito(a) {(r['cargo'] or '').lower()} em 2024. A mesma "
                    f"pessoa (nome e 6 dígitos do CPF iguais) é sócia da empresa, que tem {r['qtd']} {forma} com "
                    f"{r['orgao']} somando {formatar_brl(r['valor'])}."
                ),
            }
        )
    return alertas


# Fonte da cota -> coluna de `candidatos` que liga o eleito ao pagador daquela fonte.
VINCULO_CANDIDATO = {"federal": "deputado_id", "senado": "senador_id", "estadual": "deputado_estadual_id"}


def alertas_doador_socio_cota(db: Session, _s: Settings, f: Fonte) -> list[dict[str, Any]]:
    """Doador (pessoa física) da campanha de 2022 de um parlamentar que é sócio de empresa
    paga pela cota/verba desse mesmo parlamentar. Vínculo por nome + 6 dígitos do CPF."""
    coluna = VINCULO_CANDIDATO[[k for k, v in FONTES.items() if v is f][0]]
    linhas = _linhas(
        db,
        f"""
        WITH g AS ({f.gastos}),
        dc AS (
            SELECT sq_candidato, doador_nome_normalizado, doador_cpf_meio, MAX(doador_nome) AS doador_nome,
                   SUM(valor_centavos) AS doado
            FROM doacoes_campanha WHERE ano = 2022
            GROUP BY sq_candidato, doador_nome_normalizado, doador_cpf_meio
        )
        SELECT c.{coluna} AS pessoa, dc.doador_nome, dc.doado, g.cnpj, MAX(g.fornecedor) AS fornecedor,
               SUM(g.valor) AS valor, MIN(g.ano) AS ano, COUNT(*) AS qtd, so.qualificacao
        FROM dc
        JOIN candidatos c ON c.sq_candidato = dc.sq_candidato AND c.{coluna} IS NOT NULL
        JOIN {SOCIOS_PF} so ON so.nome_normalizado = dc.doador_nome_normalizado
                      AND so.documento = dc.doador_cpf_meio
        JOIN g ON g.pessoa = c.{coluna} AND substr(g.cnpj, 1, 8) = so.cnpj_basico AND g.tipo_pessoa = 'PJ'
        GROUP BY c.{coluna}, dc.doador_nome_normalizado, dc.doador_cpf_meio, g.cnpj
        """,
    )
    return [
        {
            "tipo": "doador_socio",
            "gravidade": "alta" if r["valor"] >= LIMITE_ATENCAO_CENTAVOS else "media",
            "pessoa": r["pessoa"],
            "cnpj": r["cnpj"],
            "ano": r["ano"],
            "valor_centavos": r["valor"],
            "titulo": f"Doador(a) da campanha de 2022 é sócio(a) de {r['fornecedor']}, paga pela {'verba' if f.esfera == 'estadual' else 'cota'}",
            "descricao": (
                f"{r['doador_nome'].title()} doou {formatar_brl(r['doado'])} à campanha de 2022 de {f.quem}. A mesma pessoa "
                f"(nome e 6 dígitos do CPF iguais) é sócia ({(r['qualificacao'] or 'sócio').lower()}) da empresa, que recebeu "
                f"{formatar_brl(r['valor'])} em {r['qtd']} nota(s) de {f.quem}."
            ),
        }
        for r in linhas
    ]


def _mes_ano(indice: int) -> str:
    """Índice ano*12 + (mês-1) -> 'dez/2025'."""
    return f"{MESES_ABREV[indice % 12]}/{indice // 12}"


def alertas_emenda_pix(db: Session, s: Settings) -> list[dict[str, Any]]:
    """Emenda Pix recebida (Transferegov) × gasto informado ao tribunal de contas com a fonte
    "Transferência Especial da União". Só para municípios cujo tribunal publica a fonte (TCE-PE).

    - pix_parado: repasses de 6 a 24 meses atrás com menos de 20% de gasto registrado desde então;
    - pix_custeio: ano em que mais de 30% do gasto com a fonte foi despesa corrente;
    - pix_gasto_maior: gasto acumulado com a fonte bem acima do que tinha sido recebido.
    """
    minimo = round(s.alerta_pix_minimo * 100)
    municipios = _linhas(
        db,
        """
        SELECT m.codigo_ibge AS ibge, m.nome, MIN(CASE WHEN ug.natureza LIKE 'Prefeitura%' THEN ug.id END) AS prefeitura,
               GROUP_CONCAT(DISTINCT ug.id) AS ugs
        FROM unidades_gestoras ug
        JOIN municipios m ON m.sigla_uf = ug.sigla_uf AND m.nome_normalizado = ug.municipio_normalizado
        WHERE EXISTS (SELECT 1 FROM despesas_municipais d WHERE d.unidade_gestora_id = ug.id AND d.fonte_recurso IS NOT NULL)
        GROUP BY m.codigo_ibge
        """,
    )
    alertas: list[dict[str, Any]] = []
    for mun in municipios:
        ugs = [int(u) for u in str(mun["ugs"]).split(",")]
        marcadores = ",".join(str(u) for u in ugs)
        fim = db.execute(text(
            f"SELECT MAX(ano * 12 + COALESCE(mes, 1) - 1) FROM despesas_municipais WHERE unidade_gestora_id IN ({marcadores})"
        )).scalar()
        if fim is None:
            continue
        repasses = _linhas(
            db,
            """
            SELECT r.data, r.valor_centavos AS valor, p.parlamentar, p.objeto, p.investimento_centavos AS inv,
                   p.custeio_centavos AS cust
            FROM repasses_pix r JOIN planos_pix p ON p.id = r.plano_id
            WHERE p.municipio_ibge = :ibge AND r.data IS NOT NULL ORDER BY r.data
            """,
            ibge=mun["ibge"],
        )
        gastos = _linhas(
            db,
            f"""
            SELECT ano, COALESCE(mes, 1) AS mes, categoria_economica AS categoria, SUM(valor_pago_centavos) AS valor
            FROM despesas_municipais
            WHERE unidade_gestora_id IN ({marcadores}) AND fonte_recurso = :fonte
            GROUP BY ano, mes, categoria_economica
            """,
            fonte=s.fonte_pix_federal,
        )
        base = {"esfera": "municipal", "unidade_gestora_id": mun["prefeitura"] or ugs[0], "municipio_ibge": mun["ibge"]}
        cidade = mun["nome"]

        # 1. Dinheiro parado (ou gasto sem a fonte certa).
        def indice(d: date) -> int:
            return d.year * 12 + d.month - 1

        maduros = [
            r for r in repasses
            if fim - PIX_PARADO_JANELA_MESES <= indice(_data(r["data"])) <= fim - s.alerta_pix_parado_meses
        ]
        if maduros:
            desde = min(indice(_data(r["data"])) for r in maduros)
            recebido = sum(r["valor"] for r in maduros)
            gasto = sum(g["valor"] for g in gastos if g["ano"] * 12 + g["mes"] - 1 >= desde)
            if recebido >= minimo and gasto < PIX_PARADO_FRACAO_GASTA * recebido:
                origem = "; ".join(
                    f"{formatar_brl(r['valor'])} em {_data(r['data']):%d/%m/%Y} ({(r['parlamentar'] or '?')}"
                    f"{': ' + r['objeto'][:90] if r['objeto'] else ''})"
                    for r in maduros
                )
                alertas.append({
                    **base,
                    "tipo": "pix_parado",
                    "gravidade": "alta" if recebido - gasto >= 10 * minimo else "media",  # R$ 1 mi com o mínimo padrão
                    "ano": desde // 12,
                    "valor_centavos": recebido - gasto,
                    "titulo": f"{formatar_brl(recebido)} de Emenda Pix recebidos desde {_mes_ano(desde)} "
                              f"e só {formatar_brl(gasto)} de gasto registrado",
                    "descricao": (
                        f"Repasses a {cidade}: {origem}. Desde {_mes_ano(desde)} até {_mes_ano(fim)} (último mês "
                        f"informado ao tribunal de contas), a prefeitura lançou {formatar_brl(gasto)} de despesa com a "
                        f"fonte \"{s.fonte_pix_federal}\". O dinheiro pode estar parado na conta específica ou ter sido "
                        "gasto com outra fonte informada."
                    ),
                })

        # 2. Custeio acima do permitido, por ano.
        por_ano: dict[int, dict[str, int]] = defaultdict(lambda: {"corrente": 0, "total": 0})
        for g in gastos:
            item = por_ano[g["ano"]]
            item["total"] += g["valor"]
            if "CAPITAL" not in (normalizar_nome(g["categoria"]) or ""):
                item["corrente"] += g["valor"]
        investimento_declarado = sum(r["inv"] for r in repasses)
        planejado = investimento_declarado + sum(r["cust"] for r in repasses)
        for ano, v in sorted(por_ano.items()):
            if v["total"] < minimo or v["corrente"] <= PIX_CORRENTE_MAXIMO * v["total"]:
                continue
            fracao = v["corrente"] / v["total"]
            declarado = (
                f" Nos planos de ação do Transferegov, {pct(investimento_declarado / planejado)} do valor foi "
                "declarado como investimento." if planejado else ""
            )
            alertas.append({
                **base,
                "tipo": "pix_custeio",
                "gravidade": "alta" if fracao > 0.7 else "media",
                "ano": ano,
                "valor_centavos": v["corrente"],
                "titulo": f"{pct(fracao)} do gasto com Emenda Pix de {cidade} em {ano} foi despesa corrente",
                "descricao": (
                    f"Em {ano}, a prefeitura lançou {formatar_brl(v['total'])} com a fonte \"{s.fonte_pix_federal}\", "
                    f"dos quais {formatar_brl(v['corrente'])} em despesa corrente (material de consumo, serviços, "
                    "pessoal). A Constituição (art. 166-A, § 5º) exige que ao menos 70% da Emenda Pix vá para "
                    f"investimento (obras, equipamentos).{declarado}"
                ),
            })

        # 3. Gasto lançado com a fonte maior que o recebido até então.
        pior: tuple[int, int, int] | None = None
        for ano in sorted(por_ano):
            recebido = sum(r["valor"] for r in repasses if _data(r["data"]).year <= ano)
            gasto = sum(v["total"] for a, v in por_ano.items() if a <= ano)
            excesso = gasto - recebido
            if gasto > PIX_GASTO_MAIOR_FATOR * recebido and excesso >= minimo and (pior is None or excesso > pior[2]):
                pior = (ano, recebido, excesso)
        if pior:
            ano, recebido, excesso = pior
            gasto = recebido + excesso
            alertas.append({
                **base,
                "tipo": "pix_gasto_maior",
                "gravidade": "media",
                "ano": ano,
                "valor_centavos": excesso,
                "titulo": f"Até {ano}, {cidade} lançou {formatar_brl(gasto)} de gasto com Emenda Pix, "
                          f"mas tinha recebido {formatar_brl(recebido)}",
                "descricao": (
                    f"Somando os repasses do Transferegov até {ano}, chegaram {formatar_brl(recebido)} de Emenda Pix. "
                    f"No mesmo período, a prefeitura informou ao tribunal de contas {formatar_brl(gasto)} de despesas "
                    f"com a fonte \"{s.fonte_pix_federal}\". Pode ser erro de classificação da fonte, o que impede "
                    "saber, pelos dados abertos, onde a Emenda Pix foi realmente gasta."
                ),
            })
    return alertas


def alertas_contrato_capital(db: Session, _s: Settings) -> list[dict[str, Any]]:
    """Fornecedor com contratos no ano, com o mesmo órgão, de pelo menos R$ 1 milhão e 10 vezes
    o capital social declarado na Receita. Capital baixo não é ilegal, mas indica empresa pequena
    para o tamanho do compromisso (risco de não entregar, ou de ser intermediária)."""
    linhas = _linhas(
        db,
        """
        SELECT c.unidade_gestora_id AS pagador, ug.nome AS orgao, c.ano, c.cpf_cnpj AS cnpj,
               MAX(c.fornecedor) AS fornecedor, SUM(c.valor_centavos) AS valor, COUNT(*) AS qtd,
               f.capital_social_centavos AS capital, f.razao_social
        FROM contratos_municipais c
        JOIN fornecedores f ON f.cnpj = c.cpf_cnpj
        JOIN unidades_gestoras ug ON ug.id = c.unidade_gestora_id
        WHERE c.tipo_pessoa = 'PJ' AND f.capital_social_centavos > 0
        GROUP BY c.unidade_gestora_id, c.ano, c.cpf_cnpj
        HAVING SUM(c.valor_centavos) >= :minimo AND SUM(c.valor_centavos) >= :fator * f.capital_social_centavos
        """,
        minimo=CONTRATO_CAPITAL_MINIMO, fator=CONTRATO_CAPITAL_FATOR,
    )
    return [
        {
            "tipo": "contrato_capital",
            "gravidade": "alta" if r["valor"] >= 50 * r["capital"] else "media",
            "esfera": "municipal",
            "unidade_gestora_id": r["pagador"],
            "cnpj": r["cnpj"],
            "ano": r["ano"],
            "valor_centavos": r["valor"],
            "titulo": f"{r['razao_social'] or r['fornecedor']} tem {formatar_brl(r['valor'])} em contratos com "
                      f"capital social de {formatar_brl(r['capital'])}",
            "descricao": (
                f"Em {r['ano']}, a {r['orgao']} assinou {r['qtd']} contrato(s) com a empresa, somando "
                f"{formatar_brl(r['valor'])} — {r['valor'] / r['capital']:.0f} vezes o capital social declarado na "
                "Receita. Capital baixo não é irregular, mas vale conferir se a empresa tem estrutura para entregar "
                "e se não está só intermediando."
            ),
        }
        for r in linhas
    ]


Regra = Callable[[Session, Settings], list[dict[str, Any]]]
RegraPorFonte = Callable[[Session, Settings, Fonte], list[dict[str, Any]]]

# Regras só da cota federal (usam campos que só ela tem: número da nota, data diária...).
REGRAS_FEDERAIS: list[Regra] = [alertas_concentracao, alertas_notas_sequenciais, alertas_padrao_atipico]
# Regras que valem para cada fonte de gasto.
REGRAS_POR_FONTE: list[tuple[RegraPorFonte, tuple[str, ...]]] = [
    (alertas_empresa_nova, ("federal", "senado", "estadual", "municipal", "pncp")),
    (alertas_fornecedor_inativo, ("federal", "senado", "estadual", "municipal", "pncp")),
    (alertas_divulgacao_eleitoral, ("federal", "senado", "estadual")),
    (alertas_doador_socio_cota, ("federal", "senado", "estadual")),
]
COLUNAS_PAGADOR = ("deputado_id", "senador_id", "deputado_estadual_id", "unidade_gestora_id", "orgao_cnpj")


def _com_fonte(alerta: dict[str, Any], nome_fonte: str, orgaos: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """Converte `pessoa` na coluna certa de `alertas` conforme a fonte."""
    fonte = FONTES[nome_fonte]
    a = {k: v for k, v in alerta.items() if k not in ("pessoa", "fonte")}
    a.update({c: None for c in COLUNAS_PAGADOR})
    a.update({"esfera": fonte.esfera, "municipio_ibge": None, "orgao_nome": None})
    a[fonte.coluna] = alerta["pessoa"]
    if nome_fonte == "pncp":
        a["municipio_ibge"], a["orgao_nome"] = orgaos.get(alerta["pessoa"], (None, None))
    return a


def _completar(alerta: dict[str, Any], orgaos: dict[str, tuple[str, str]]) -> dict[str, Any]:
    a = {**{c: None for c in COLUNAS_PAGADOR}, "municipio_ibge": None, "orgao_nome": None, **alerta}
    if a["orgao_cnpj"] and not a["orgao_nome"]:
        a["orgao_nome"] = orgaos.get(a["orgao_cnpj"], (None, None))[1]
    return a


def _municipio_por_orgao(db: Session) -> dict[str, tuple[str, str]]:
    """CNPJ do órgão contratante (PNCP) -> (código IBGE do município, nome do órgão)."""
    return {
        cnpj: (ibge, nome)
        for cnpj, ibge, nome in db.execute(
            text("SELECT orgao_cnpj, MAX(municipio_ibge), MAX(orgao_nome) FROM contratos_pncp GROUP BY orgao_cnpj")
        )
    }


# Peso de cada tipo na nota de prioridade: quanto a evidência sozinha já diz.
PESO_TIPO = {
    "servidor_socio": 40, "pix_gasto_maior": 35, "pix_parado": 35, "pix_custeio": 35, "doador_socio": 30,
    "fornecedor_inativo": 25, "eleito_socio": 25, "concentracao": 20, "notas_sequenciais": 20,
    "padrao_atipico": 15, "divulgacao_eleitoral": 15, "mei_acima_limite": 10, "empresa_nova": 10,
    "contrato_capital": 20,
}


def pontuar(alerta: dict[str, Any], tipos_do_cnpj: int = 1) -> int:
    """Nota de 0 a 100 para ordenar os alertas: tipo + gravidade + valor + evidências que se somam.

    Valor: R$ 1 mil = 0, R$ 10 mil = 10, R$ 100 mil = 20, R$ 1 mi = 30, R$ 10 mi ou mais = 35.
    Cada tipo diferente de alerta sobre o mesmo CNPJ soma 10 (até 20).
    """
    import math

    reais = max(alerta.get("valor_centavos") or 0, 0) / 100
    nota = PESO_TIPO.get(alerta["tipo"], 10)
    nota += 15 if alerta.get("gravidade") == "alta" else 0
    nota += min(35, max(0, int((math.log10(reais) - 3) * 10))) if reais > 0 else 0
    nota += min(20, 10 * (tipos_do_cnpj - 1))
    return max(0, min(100, nota))


def recalcular_alertas(db: Session, settings: Settings) -> dict[str, int]:
    """Apaga e recalcula todos os alertas, numa transação. Retorna a contagem por tipo."""
    agora = datetime.now()
    todos: list[dict[str, Any]] = []

    def somar(nome: str, novos: list[dict[str, Any]]) -> None:
        logger.info("Alertas %s: %d", nome, len(novos))
        todos.extend(novos)

    municipios = _municipio_por_orgao(db)
    for regra in REGRAS_FEDERAIS:
        somar(regra.__name__.removeprefix("alertas_"), [_com_fonte(a, "federal", municipios) for a in regra(db, settings)])
    for regra_f, fontes in REGRAS_POR_FONTE:
        for nome in fontes:
            novos = regra_f(db, settings, FONTES[nome])
            somar(f"{regra_f.__name__.removeprefix('alertas_')} ({nome})", [_com_fonte(a, nome, municipios) for a in novos])
    somar("mei_acima_limite", [_com_fonte(a, a["fonte"], municipios) for a in alertas_mei_acima_limite(db, settings)])
    # Regras de cruzamento já devolvem a esfera e o pagador certos.
    for regra in (alertas_servidor_socio, alertas_eleito_socio, alertas_doador_socio, alertas_emenda_pix,
                  alertas_contrato_capital):
        somar(regra.__name__.removeprefix("alertas_"), [_completar(a, municipios) for a in regra(db, settings)])

    tipos_por_cnpj: dict[str, set[str]] = defaultdict(set)
    for a in todos:
        if a.get("cnpj"):
            tipos_por_cnpj[a["cnpj"]].add(a["tipo"])
    for a in todos:
        a["prioridade"] = pontuar(a, len(tipos_por_cnpj.get(a.get("cnpj") or "", ())) or 1)

    db.execute(delete(Alerta))
    if todos:
        db.execute(insert(Alerta), [{**a, "calculado_em": agora} for a in todos])
    db.commit()
    contagem: dict[str, int] = defaultdict(int)
    for a in todos:
        contagem[a["tipo"]] += 1
    return dict(contagem)


def recalcular_se_configurado(db: Session, settings: Settings) -> dict[str, int] | None:
    """Recalcula ao fim de uma coleta, a menos que ALERTAS_AO_FINAL=false (a rotina recalcula uma vez no fim)."""
    if not settings.alertas_ao_final:
        logger.info("Alertas não recalculados (ALERTAS_AO_FINAL=false)")
        return None
    return recalcular_alertas(db, settings)


def main(argv: list[str] | None = None) -> int:
    """`python -m civic.alertas`: recalcula todos os alertas."""
    import argparse
    import sys
    import time

    from civic.config import get_settings
    from civic.database import SessionLocal, init_db

    parser = argparse.ArgumentParser(prog="python -m civic.alertas", description=main.__doc__)
    parser.parse_args(argv)
    s = get_settings()
    logging.basicConfig(level=s.log_level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stderr)
    init_db()
    inicio = time.monotonic()
    with SessionLocal() as db:
        contagem = recalcular_alertas(db, s)
    logger.info("Alertas recalculados em %.1f min: %s", (time.monotonic() - inicio) / 60, contagem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
