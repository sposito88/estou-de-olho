from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from civic import pncp
from civic.cleaning import contrato_do_pncp
from civic.config import Settings
from civic.models import ContratoPncp, SyncPncpDia
from civic.scraper import Resumo

pncp.PAUSA_APOS_FALHA_S = 0

ITEM = {
    "numeroControlePNCP": "08985624000117-2-000001/2025",
    "orgaoEntidade": {"cnpj": "08985624000117", "razaoSocial": "CAMARA MUNICIPAL DE CARPINA", "poderId": "L", "esferaId": "M"},
    "unidadeOrgao": {"ufSigla": "PE", "municipioNome": "Carpina", "nomeUnidade": "CAMARA", "codigoIbge": "2604007"},
    "niFornecedor": "39727407000150",
    "nomeRazaoSocialFornecedor": "OLIVEIRA, FARIAS E LAURINDO ADVOGADOS ASSOCIADOS",
    "tipoPessoa": "PJ",
    "objetoContrato": "Contratação de serviços jurídicos especializados",
    "tipoContrato": {"id": 1, "nome": "Contrato (termo inicial)"},
    "categoriaProcesso": {"id": 8, "nome": "Serviços"},
    "valorInicial": 168000.0,
    "valorGlobal": 168000.0,
    "dataAssinatura": "2025-01-03",
    "dataVigenciaInicio": "2025-01-03",
    "dataVigenciaFim": "2025-12-31",
    "dataPublicacaoPncp": "2025-01-10T10:00:00",
    "anoContrato": 2025,
}


def test_contrato_do_pncp() -> None:
    c = contrato_do_pncp(ITEM)
    assert c["municipio_ibge"] == "2604007"
    assert (c["orgao_cnpj"], c["esfera"], c["poder"]) == ("08985624000117", "M", "L")
    assert c["valor_global_centavos"] == 16_800_000
    assert (c["data_assinatura"], c["data_publicacao"], c["ano"]) == (date(2025, 1, 3), date(2025, 1, 10), 2025)
    assert c["objeto_normalizado"] == "CONTRATACAO DE SERVICOS JURIDICOS ESPECIALIZADOS"
    pf = contrato_do_pncp({**ITEM, "tipoPessoa": "PF", "niFornecedor": "12345678909"})
    assert pf["fornecedor_ni"] == "***.456.789-**"


class Cliente:
    def __init__(self, por_dia: dict[str, list[dict[str, Any]]]) -> None:
        self.por_dia = por_dia
        self.chamadas: list[dict[str, Any]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, *, latin1: bool = False) -> Any:
        params = params or {}
        self.chamadas.append(params)
        itens = self.por_dia.get(params["dataInicial"], [])
        if not itens:
            return None  # 204
        paginas = [itens[i : i + 2] for i in range(0, len(itens), 2)]
        return {"totalPaginas": len(paginas), "data": paginas[params["pagina"] - 1]}


def test_coleta_pncp_filtra_esfera_pagina_e_faz_checkpoint(db: Session) -> None:
    s = Settings(_env_file=None, pncp_esferas="M")  # type: ignore[call-arg]
    estadual = {**ITEM, "numeroControlePNCP": "x-est", "orgaoEntidade": {**ITEM["orgaoEntidade"], "esferaId": "E"}}
    itens = [ITEM, estadual, {**ITEM, "numeroControlePNCP": "x-2"}, {**ITEM, "numeroControlePNCP": "x-3"}]
    cliente = Cliente({"20250110": itens})
    total = pncp.coletar_pncp(cliente, db, s, Resumo(), date(2025, 1, 9), date(2025, 1, 11), progresso=False)  # type: ignore[arg-type]
    assert total == 3  # o estadual fica de fora
    assert db.scalar(select(func.count()).select_from(ContratoPncp)) == 3
    assert {d for d in db.scalars(select(SyncPncpDia.data))} == {date(2025, 1, 9), date(2025, 1, 10), date(2025, 1, 11)}

    # Segunda rodada: dias antigos com checkpoint não são consultados de novo.
    cliente.chamadas.clear()
    pncp.coletar_pncp(cliente, db, s, Resumo(), date(2025, 1, 9), date(2025, 1, 11), progresso=False)  # type: ignore[arg-type]
    assert cliente.chamadas == []

    # Retificação: o mesmo número de controle atualiza em vez de duplicar.
    cliente2 = Cliente({"20250110": [{**ITEM, "valorGlobal": 200000.0}]})
    pncp.coletar_pncp(cliente2, db, s, Resumo(), date(2025, 1, 10), date(2025, 1, 10), forcar=True, progresso=False)  # type: ignore[arg-type]
    assert db.get(ContratoPncp, ITEM["numeroControlePNCP"]).valor_global_centavos == 20_000_000  # type: ignore[union-attr]
    assert db.scalar(select(func.count()).select_from(ContratoPncp)) == 3
