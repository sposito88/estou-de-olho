"""Emendas Pix (transferências especiais) do Transferegov: plano de ação, objeto, metas e repasses.

Uso:
    python -m civic.transferegov [--sem-alertas]

A API pública (PostgREST) em api.transferegov.gestao.gov.br/transferenciasespeciais
tem poucas dezenas de milhares de linhas por tabela: baixamos tudo a cada execução
e substituímos as tabelas `planos_pix` e `repasses_pix`.

- plano_acao_especial: quem recebeu, parlamentar, ano, valores declarados de custeio e investimento;
- executor_especial + meta_especial: o objeto ("construção de UBS...") e as metas;
- relatorio_gestao_especial: o relatório de gestão (prestação de contas) do plano;
- empenho_especial + documento_habil_especial: cada repasse efetivamente enviado, com data.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from civic.alertas import recalcular_se_configurado
from civic.cleaning import limpar_documento, limpar_texto, para_centavos, parse_data
from civic.config import Settings, get_settings
from civic.database import SessionLocal, init_db
from civic.models import EnteSiconfi, PlanoPix, RepassePix
from civic.pernambuco import ClienteJson
from civic.pncp import sessao_paciente
from civic.scraper import Resumo, em_lotes, registrar_execucao

logger = logging.getLogger("civic.transferegov")

TAMANHO_PAGINA = 1_000  # o servidor corta qualquer página em 1.000 linhas
DH_ENVIADO = 3  # situação do documento hábil "Enviado com Sucesso"


def paginas(cliente: ClienteJson, s: Settings, tabela: str, colunas: str, ordem: str) -> Iterator[dict[str, Any]]:
    """Todas as linhas de uma tabela do PostgREST, em páginas ordenadas pela chave.

    Avança pelo tamanho do lote recebido até vir uma página vazia: o servidor pode
    devolver menos linhas que o `limit` pedido mesmo quando ainda há mais.
    """
    offset = 0
    while True:
        lote = cliente.get(
            f"{s.transferegov_url}/{tabela}",
            {"select": colunas, "order": ordem, "limit": TAMANHO_PAGINA, "offset": offset},
        ) or []
        if not lote:
            return
        yield from lote
        offset += len(lote)


def _juntar(textos: list[str], limite: int = 4_000) -> str | None:
    unicos = list(dict.fromkeys(t for t in textos if t))
    return " | ".join(unicos)[:limite] or None


def montar_planos(
    planos: list[dict[str, Any]],
    executores: list[dict[str, Any]],
    metas: list[dict[str, Any]],
    relatorios: list[dict[str, Any]],
    municipio_por_cnpj: dict[str, str],
) -> list[dict[str, Any]]:
    """Uma linha por plano, com objeto e metas dos executores e o relatório de gestão mais recente."""
    executores_do_plano: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for e in executores:
        executores_do_plano[int(e["id_plano_acao"])].append(e)
    metas_do_executor: dict[int, list[str]] = defaultdict(list)
    for m in metas:
        nome = limpar_texto(m.get("nome_meta"))
        desc = limpar_texto(m.get("desc_meta"))
        texto = desc if desc and (not nome or nome.upper().startswith("META")) else nome
        metas_do_executor[int(m["id_executor"])].append(texto or "")
    relatorio: dict[int, dict[str, Any]] = {}
    for r in sorted(relatorios, key=lambda r: int(r["id_relatorio_gestao"])):
        relatorio[int(r["id_plano_acao"])] = r

    agora = datetime.now()
    linhas = []
    for p in planos:
        pid = int(p["id_plano_acao"])
        cnpj = limpar_documento(p.get("cnpj_beneficiario_plano_acao"))
        execs = executores_do_plano.get(pid, [])
        rel = relatorio.get(pid, {})
        linhas.append(
            {
                "id": pid,
                "codigo": limpar_texto(p.get("codigo_plano_acao")),
                "ano": int(p["ano_plano_acao"]),
                "situacao": limpar_texto(p.get("situacao_plano_acao")),
                "motivo_impedimento": limpar_texto(p.get("motivo_impedimento_plano_acao")),
                "cnpj_beneficiario": cnpj,
                "nome_beneficiario": limpar_texto(p.get("nome_beneficiario_plano_acao")),
                "sigla_uf": limpar_texto(p.get("uf_beneficiario_plano_acao")),
                "municipio_ibge": municipio_por_cnpj.get(cnpj or ""),
                "parlamentar": limpar_texto(p.get("nome_parlamentar_emenda_plano_acao")),
                "codigo_parlamentar": limpar_texto(p.get("codigo_parlamentar_emenda_plano_acao")),
                "numero_emenda": limpar_texto(p.get("numero_emenda_parlamentar_plano_acao")),
                "area": limpar_texto(p.get("codigo_descricao_areas_politicas_publicas_plano_acao")),
                "objeto": _juntar([limpar_texto(e.get("objeto_executor")) or "" for e in execs]),
                "metas": _juntar([t for e in execs for t in metas_do_executor.get(int(e["id_executor"]), [])]),
                "custeio_centavos": para_centavos(p.get("valor_custeio_plano_acao")),
                "investimento_centavos": para_centavos(p.get("valor_investimento_plano_acao")),
                "relatorio_situacao": limpar_texto(rel.get("situacao_relatorio_gestao")),
                "relatorio_parecer": limpar_texto(rel.get("parecer_relatorio_gestao")),
                "atualizado_em": agora,
            }
        )
    return linhas


def montar_repasses(empenhos: list[dict[str, Any]], documentos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Repasses enviados (documento hábil com sucesso), ligados ao plano pelo empenho."""
    plano_do_empenho = {int(e["id_empenho"]): int(e["id_plano_acao"]) for e in empenhos if e.get("id_plano_acao")}
    linhas = []
    for d in documentos:
        if int(d.get("situacao_dh") or 0) != DH_ENVIADO:
            continue
        plano = plano_do_empenho.get(int(d.get("id_empenho") or 0))
        if plano is None:
            continue
        linhas.append(
            {
                "id": int(d["id_dh"]),
                "plano_id": plano,
                "data": parse_data(d.get("data_emissao_dh")),
                "valor_centavos": para_centavos(d.get("valor_dh")),
            }
        )
    return linhas


def coletar_transferegov(cliente: ClienteJson, db: Session, s: Settings) -> tuple[int, int]:
    def baixar(tabela: str, colunas: str, ordem: str) -> list[dict[str, Any]]:
        linhas = list(paginas(cliente, s, tabela, colunas, ordem))
        logger.info("%s: %d linhas", tabela, len(linhas))
        return linhas

    planos = baixar(
        "plano_acao_especial",
        "id_plano_acao,codigo_plano_acao,ano_plano_acao,situacao_plano_acao,motivo_impedimento_plano_acao,"
        "cnpj_beneficiario_plano_acao,nome_beneficiario_plano_acao,uf_beneficiario_plano_acao,"
        "nome_parlamentar_emenda_plano_acao,codigo_parlamentar_emenda_plano_acao,"
        "numero_emenda_parlamentar_plano_acao,codigo_descricao_areas_politicas_publicas_plano_acao,"
        "valor_custeio_plano_acao,valor_investimento_plano_acao",
        "id_plano_acao",
    )
    executores = baixar("executor_especial", "id_plano_acao,id_executor,objeto_executor", "id_executor")
    metas = baixar("meta_especial", "id_executor,id_meta,nome_meta,desc_meta", "id_meta")
    relatorios = baixar(
        "relatorio_gestao_especial", "id_relatorio_gestao,id_plano_acao,situacao_relatorio_gestao,parecer_relatorio_gestao",
        "id_relatorio_gestao",
    )
    empenhos = baixar("empenho_especial", "id_empenho,id_plano_acao", "id_empenho")
    documentos = baixar("documento_habil_especial", "id_dh,id_empenho,situacao_dh,data_emissao_dh,valor_dh", "id_dh")

    municipio_por_cnpj = {
        cnpj: codigo for codigo, cnpj in db.execute(select(EnteSiconfi.codigo_ibge, EnteSiconfi.cnpj)) if cnpj
    }
    linhas_planos = montar_planos(planos, executores, metas, relatorios, municipio_por_cnpj)
    linhas_repasses = montar_repasses(empenhos, documentos)
    if not linhas_planos:
        raise ValueError("Transferegov não devolveu nenhum plano de ação; nada foi substituído")
    db.execute(delete(PlanoPix))
    db.execute(delete(RepassePix))
    for lote in em_lotes(linhas_planos, 2_000):
        db.execute(insert(PlanoPix), list(lote))
    for lote in em_lotes(linhas_repasses, 2_000):
        db.execute(insert(RepassePix), list(lote))
    db.commit()
    sem_municipio = sum(1 for l in linhas_planos if l["municipio_ibge"] is None)
    logger.info(
        "Emendas Pix: %d planos (%d sem município: estados ou CNPJ fora do Siconfi), %d repasses",
        len(linhas_planos), sem_municipio, len(linhas_repasses),
    )
    registrar_execucao(db, "transferegov", len(linhas_planos))
    return len(linhas_planos), len(linhas_repasses)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.transferegov", description=__doc__.splitlines()[0])
    parser.add_argument("--sem-alertas", action="store_true", help="não recalcula os alertas ao final")
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
        try:
            coletar_transferegov(ClienteJson(s.transferegov_req_per_sec, max(s.timeout, 120), sessao_paciente()), db, s)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            resumo.registrar_falha("Transferegov", exc)
        if not args.sem_alertas and not resumo.falhas:
            try:
                logger.info("Alertas recalculados: %s", recalcular_se_configurado(db, s))
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                resumo.registrar_falha("alertas", exc)
    finally:
        db.close()
    logger.info("Transferegov concluído em %.1f min; falhas: %d", (time.monotonic() - inicio) / 60, len(resumo.falhas))
    for falha in resumo.falhas:
        logger.info("  - %s", falha)
    return 1 if resumo.falhas else 0


if __name__ == "__main__":
    sys.exit(main())
