"""Quanto cada prefeitura cumpre o dever de prestar contas, medido pelo que ela entrega às fontes oficiais.

Para cada município:
- RREO (relatório bimestral ao Tesouro): último bimestre entregue no ano corrente × o esperado;
- DCA (balanço anual) do ano anterior: entregue ou não (prazo: 30 de abril);
- tribunal de contas (onde coletamos: PE, SP, PB): último mês com dados informados;
- PNCP: data do último contrato publicado;
- observações verificadas à mão (portal fora do ar, bloqueado, desatualizado), em `dados/observacoes_portais.json`.

Pendências viram uma lista em linguagem simples; o ranking ordena por número de pendências.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from civic.siconfi import bimestre_esperado

OBSERVACOES = Path(__file__).parent / "dados" / "observacoes_portais.json"
MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
FIM_BIMESTRE = ("fev", "abr", "jun", "ago", "out", "dez")
ATRASO_TRIBUNAL_MESES = 3  # mais que isso sem dado novo no tribunal vira pendência
ATRASO_PNCP_DIAS = 180
BRASILIA = "5300108"  # o Distrito Federal presta contas como estado, não como município
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def observacoes() -> dict[str, list[dict[str, str]]]:
    try:
        dados = json.loads(OBSERVACOES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in dados.items() if not k.startswith("_")}


def calcular(db: Session, hoje: date | None = None) -> list[dict[str, Any]]:
    hoje = hoje or date.today()
    ano, esperado = hoje.year, bimestre_esperado(hoje)
    dca_exigida = hoje > date(hoje.year, 4, 30)
    linhas = db.execute(text(
        """
        WITH rreo AS (
            SELECT codigo_ibge, MAX(periodo) AS bimestre FROM contas_municipais
            WHERE ano = :ano AND demonstrativo = 'RREO' AND cod_conta = 'TOTAL' GROUP BY codigo_ibge
        ),
        dca AS (
            SELECT DISTINCT codigo_ibge FROM contas_municipais
            WHERE ano = :anterior AND (demonstrativo IS NULL OR demonstrativo = 'DCA') AND cod_conta = 'TOTAL'
        ),
        pncp AS (SELECT municipio_ibge AS codigo_ibge, MAX(data_assinatura) AS ultimo FROM contratos_pncp GROUP BY 1),
        tribunal AS (
            SELECT m.codigo_ibge, MAX(ug.fonte) AS fonte, MAX(x.indice) AS indice
            FROM municipios m
            JOIN unidades_gestoras ug ON ug.sigla_uf = m.sigla_uf AND ug.municipio_normalizado = m.nome_normalizado
            JOIN (
                SELECT unidade_gestora_id, MAX(ano * 12 + COALESCE(mes, 1) - 1) AS indice
                FROM despesas_municipais GROUP BY unidade_gestora_id
                UNION ALL
                SELECT unidade_gestora_id, MAX(ano * 12 + mes - 1) FROM folhas_mensais GROUP BY unidade_gestora_id
            ) x ON x.unidade_gestora_id = ug.id
            GROUP BY m.codigo_ibge
        )
        SELECT m.codigo_ibge, m.nome, m.sigla_uf, m.populacao, rreo.bimestre, dca.codigo_ibge IS NOT NULL AS tem_dca,
               pncp.ultimo AS ultimo_contrato, tribunal.fonte, tribunal.indice
        FROM municipios m
        LEFT JOIN rreo ON rreo.codigo_ibge = m.codigo_ibge
        LEFT JOIN dca ON dca.codigo_ibge = m.codigo_ibge
        LEFT JOIN pncp ON pncp.codigo_ibge = m.codigo_ibge
        LEFT JOIN tribunal ON tribunal.codigo_ibge = m.codigo_ibge
        WHERE m.codigo_ibge != :brasilia
        """
    ), {"ano": ano, "anterior": ano - 1, "brasilia": BRASILIA}).mappings().all()
    obs = observacoes()
    indice_hoje = hoje.year * 12 + hoje.month - 1
    resultado = []
    for l in linhas:
        pendencias: list[str] = []
        if esperado and (l["bimestre"] or 0) < esperado:
            entregue = f"o último entregue foi o de {FIM_BIMESTRE[l['bimestre'] - 1]}" if l["bimestre"] else "nenhum entregue no ano"
            pendencias.append(f"Relatório bimestral (RREO) de {FIM_BIMESTRE[esperado - 1]}/{ano} não consta no Siconfi, do Tesouro ({entregue}).")
        if dca_exigida and not l["tem_dca"]:
            pendencias.append(f"Balanço anual (DCA) de {ano - 1} não consta no Siconfi, do Tesouro (prazo: 30 de abril).")
        if l["indice"] is not None and indice_hoje - l["indice"] > ATRASO_TRIBUNAL_MESES:
            pendencias.append(f"Último dado de despesas ou folha no {l['fonte']}: {MESES[l['indice'] % 12]}/{l['indice'] // 12}.")
        ultimo = l["ultimo_contrato"]
        if ultimo is None:
            pendencias.append("Nenhum contrato publicado no PNCP (obrigatório pela Lei 14.133/2021).")
        else:
            dias = (hoje - date.fromisoformat(str(ultimo)[:10])).days
            if dias > ATRASO_PNCP_DIAS:
                pendencias.append(f"Nenhum contrato novo no PNCP há {dias} dias.")
        manuais = obs.get(l["codigo_ibge"], [])
        pendencias += [o["texto"] for o in manuais]
        resultado.append({
            "codigo_ibge": l["codigo_ibge"], "nome": l["nome"], "sigla_uf": l["sigla_uf"], "populacao": l["populacao"],
            "rreo_bimestre": l["bimestre"], "rreo_esperado": esperado or None, "dca_anterior": bool(l["tem_dca"]),
            "tribunal": l["fonte"], "tribunal_ultimo_mes": (l["indice"] // 12) * 100 + l["indice"] % 12 + 1
            if l["indice"] is not None else None,
            "ultimo_contrato_pncp": ultimo, "pendencias": pendencias, "observacoes": manuais,
        })
    resultado.sort(key=lambda r: (-len(r["pendencias"]), -(r["populacao"] or 0)))
    return resultado


def ranking(db: Session) -> list[dict[str, Any]]:
    """Calculado e guardado por 1 hora (percorre as contas de todos os municípios)."""
    agora = time.monotonic()
    if "todos" in _CACHE and agora - _CACHE["todos"][0] < 3600:
        return _CACHE["todos"][1]
    dados = calcular(db)
    _CACHE["todos"] = (agora, dados)
    return dados
