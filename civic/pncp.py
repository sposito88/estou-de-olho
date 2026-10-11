"""Contratos públicos do PNCP (Portal Nacional de Contratações Públicas).

Uso:
    python -m civic.pncp [--desde 2024-01-01] [--ate 2026-10-07] [--forcar] [--sem-progresso]

Percorre dia a dia a data de publicação, em páginas de 500, e guarda os
contratos das esferas em PNCP_ESFERAS (padrão: só municipais). Dias completos
ganham checkpoint; os últimos 7 dias são sempre relidos (retificações).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Iterator, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from urllib3.util import Retry

from civic import __version__
from civic.cleaning import contrato_do_pncp
from civic.config import Settings, get_settings
from civic.database import SessionLocal, init_db
from civic.models import ContratoPncp, SyncPncpDia
from civic.pernambuco import ClienteJson
from civic.scraper import Resumo, barra, em_lotes, registrar_execucao

logger = logging.getLogger("civic.pncp")

TAMANHO_PAGINA = 500
DIAS_SEMPRE_RELIDOS = 7
PAUSA_APOS_FALHA_S = 60


def sessao_paciente() -> requests.Session:
    """O PNCP responde 429 quando há muitas consultas: espera mais e por mais vezes que o padrão."""
    retry = Retry(
        total=8,
        backoff_factor=4,
        status_forcelist=[429, 500, 502, 503, 504],
        respect_retry_after_header=True,
        allowed_methods=frozenset({"GET"}),
    )
    sessao = requests.Session()
    sessao.mount("https://", HTTPAdapter(max_retries=retry))
    sessao.headers.update({"Accept": "application/json", "User-Agent": f"estou-de-olho/{__version__}"})
    return sessao
COLUNAS_ATUALIZAVEIS = [c.name for c in ContratoPncp.__table__.columns if c.name != "numero_controle"]


def dias(inicio: date, fim: date) -> Iterator[date]:
    atual = inicio
    while atual <= fim:
        yield atual
        atual += timedelta(days=1)


def contratos_do_dia(cliente: ClienteJson, s: Settings, dia: date) -> Iterator[dict[str, Any]]:
    """Itera todos os contratos publicados no dia (todas as páginas)."""
    pagina, total_paginas = 1, 1
    while pagina <= total_paginas:
        corpo = cliente.get(
            f"{s.pncp_url}/contratos",
            {
                "dataInicial": dia.strftime("%Y%m%d"),
                "dataFinal": dia.strftime("%Y%m%d"),
                "pagina": pagina,
                "tamanhoPagina": TAMANHO_PAGINA,
            },
        )
        # O PNCP responde 204 (corpo vazio) em dias sem publicação.
        if not corpo:
            return
        total_paginas = int(corpo.get("totalPaginas") or 0)
        yield from corpo.get("data") or []
        pagina += 1


def gravar_contratos(db: Session, linhas: list[dict[str, Any]]) -> None:
    """Upsert pelo número de controle do PNCP (estável entre retificações)."""
    agora = datetime.now()
    unicos = list({l["numero_controle"]: {**l, "atualizado_em": agora} for l in linhas}.values())
    for lote in em_lotes(unicos, 500):
        stmt = sqlite_insert(ContratoPncp).values(list(lote))
        stmt = stmt.on_conflict_do_update(
            index_elements=[ContratoPncp.numero_controle],
            set_={c: stmt.excluded[c] for c in COLUNAS_ATUALIZAVEIS},
        )
        db.execute(stmt)


def coletar_pncp(
    cliente: ClienteJson,
    db: Session,
    s: Settings,
    resumo: Resumo,
    desde: date | None = None,
    ate: date | None = None,
    forcar: bool = False,
    progresso: bool = True,
) -> int:
    """Baixa os dias pendentes, um por vez, com commit e checkpoint por dia."""
    hoje = date.today()
    inicio, fim = desde or s.pncp_data_inicial, min(ate or hoje, hoje)
    feitos = set(db.scalars(select(SyncPncpDia.data)))
    esferas = set(s.pncp_esferas)
    total = 0
    pendentes = [
        d for d in dias(inicio, fim)
        if forcar or d not in feitos or (hoje - d).days < DIAS_SEMPRE_RELIDOS
    ]
    logger.info("PNCP: %d dias a processar (%s a %s), esferas %s", len(pendentes), inicio, fim, sorted(esferas))
    for dia in barra(pendentes, progresso, desc="PNCP", unit="dia"):
        try:
            linhas = []
            for item in contratos_do_dia(cliente, s, dia):
                if ((item.get("orgaoEntidade") or {}).get("esferaId") or "") not in esferas:
                    continue
                try:
                    linhas.append(contrato_do_pncp(item))
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("Contrato ignorado (%s): %s", dia, exc)
            gravar_contratos(db, linhas)
            stmt = sqlite_insert(SyncPncpDia).values(data=dia, registros=len(linhas), concluido_em=datetime.now())
            db.execute(stmt.on_conflict_do_update(
                index_elements=[SyncPncpDia.data],
                set_={"registros": stmt.excluded.registros, "concluido_em": stmt.excluded.concluido_em},
            ))
            db.commit()
            total += len(linhas)
        except Exception as exc:  # noqa: BLE001 - um dia com erro não pode parar a carga
            db.rollback()
            resumo.registrar_falha(f"PNCP {dia}", exc)
            time.sleep(PAUSA_APOS_FALHA_S)  # provável limite de requisições: dá um respiro ao PNCP
    registrar_execucao(db, "pncp", total)
    logger.info("PNCP: %d contratos gravados", total)
    return total


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.pncp", description=__doc__.splitlines()[0])
    parser.add_argument("--desde", type=date.fromisoformat, help="primeiro dia (padrão: PNCP_DATA_INICIAL)")
    parser.add_argument("--ate", type=date.fromisoformat, help="último dia (padrão: hoje)")
    parser.add_argument("--forcar", action="store_true", help="relê dias já concluídos")
    parser.add_argument("--sem-progresso", action="store_true")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)

    s = get_settings()
    logging.basicConfig(
        level=(args.log_level or s.log_level).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    init_db()
    resumo = Resumo()
    db = SessionLocal()
    inicio = time.monotonic()
    try:
        coletar_pncp(
            ClienteJson(s.pncp_req_per_sec, max(s.timeout, 120), sessao_paciente()),
            db, s, resumo, args.desde, args.ate, args.forcar,
            progresso=not args.sem_progresso and sys.stderr.isatty(),
        )
    finally:
        db.close()
    logger.info("PNCP concluído em %.1f min; falhas: %d", (time.monotonic() - inicio) / 60, len(resumo.falhas))
    for falha in resumo.falhas[:20]:
        logger.info("  - %s", falha)
    return 1 if resumo.falhas else 0


if __name__ == "__main__":
    sys.exit(main())
