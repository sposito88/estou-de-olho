"""Municípios do IBGE: código, região imediata (para comparar vizinhos) e população estimada."""

from __future__ import annotations

import logging
from typing import Any

import requests
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from civic.cleaning import normalizar_nome
from civic.config import Settings
from civic.models import Municipio

logger = logging.getLogger("civic.ibge")


def municipio_do_ibge(item: dict[str, Any], populacao: dict[str, tuple[int, int]]) -> dict[str, Any]:
    """Normaliza um item de `/localidades/municipios` e junta a população estimada."""
    codigo = str(item["id"])
    regiao = item.get("regiao-imediata") or {}
    uf = (((regiao.get("regiao-intermediaria") or {}).get("UF")) or {}).get("sigla")
    if not uf:
        uf = (((item.get("microrregiao") or {}).get("mesorregiao") or {}).get("UF") or {}).get("sigla")
    habitantes, ano = populacao.get(codigo, (None, None))
    return {
        "codigo_ibge": codigo,
        "nome": item["nome"],
        "nome_normalizado": normalizar_nome(item["nome"]) or "",
        "sigla_uf": uf or "",
        "regiao_imediata_id": str(regiao["id"]) if regiao.get("id") else None,
        "regiao_imediata_nome": regiao.get("nome"),
        "populacao": habitantes,
        "ano_populacao": ano,
    }


def ler_populacao(resposta: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Extrai {código IBGE: (habitantes, ano)} da resposta da API de agregados (SIDRA)."""
    populacao: dict[str, tuple[int, int]] = {}
    for serie in resposta[0]["resultados"][0]["series"]:
        valores = {int(ano): v for ano, v in serie["serie"].items() if v and v.isdigit()}
        if valores:
            ano = max(valores)
            populacao[str(serie["localidade"]["id"])] = (int(valores[ano]), ano)
    return populacao


def atualizar_municipios(sessao: requests.Session, db: Session, settings: Settings) -> int:
    """Recarrega a tabela de municípios (≈5.570 linhas, duas chamadas à API do IBGE)."""
    timeout = max(settings.timeout, 120)
    municipios = sessao.get(settings.ibge_municipios_url, timeout=timeout)
    municipios.raise_for_status()
    populacao_resp = sessao.get(settings.ibge_populacao_url, timeout=timeout)
    populacao_resp.raise_for_status()
    populacao = ler_populacao(populacao_resp.json())

    linhas = [municipio_do_ibge(item, populacao) for item in municipios.json()]
    db.execute(delete(Municipio))
    db.execute(insert(Municipio), linhas)
    db.commit()
    logger.info("%d municípios do IBGE (%d com população)", len(linhas), sum(1 for l in linhas if l["populacao"]))
    return len(linhas)
