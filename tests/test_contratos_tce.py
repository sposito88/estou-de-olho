from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from civic.alertas import alertas_contrato_capital
from civic.api import app
from civic.cleaning import contrato_do_tce
from civic.config import Settings
from civic.database import get_db
from civic.models import ContratoMunicipal, Fornecedor, UnidadeGestora
from tests.conftest import AGORA
from tests.test_pernambuco import CONTRATO


def _popular(db: Session) -> None:
    db.add(UnidadeGestora(id=169, nome="Prefeitura Municipal de Carpina", natureza="Prefeitura Municipal",
                          codigo_municipio_tce="P042", municipio="Carpina", municipio_normalizado="CARPINA"))
    db.add(Fornecedor(cnpj="36575014000180", razao_social="CONSTRUTORA STH LTDA", capital_social_centavos=253_000_000,
                      referencia="2026-09", atualizado_em=AGORA))
    db.flush()
    for i, (valor, tipo) in enumerate((("20000000.00", "Concorrência"), ("19585850.35", "Pregão Eletrônico"),
                                       ("100000.00", "Dispensa"))):
        db.add(ContratoMunicipal(**contrato_do_tce({**CONTRATO, "CodigoContrato": str(i), "CPF_CNPJ": "36575014000180",
                                                    "RazaoSocial": "STH CONSTRUCOES", "Valor": valor,
                                                    "TipoProcesso": tipo}, 169)))
    db.add(ContratoMunicipal(**contrato_do_tce(CONTRATO, 169)))  # pessoa física, CPF mascarado
    db.commit()


@pytest.fixture()
def cliente(fabrica: sessionmaker[Session]) -> Iterator[TestClient]:
    with fabrica() as db:
        _popular(db)

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_resumo_e_lista_de_contratos(cliente: TestClient) -> None:
    d = cliente.get("/api/municipios/PE/Carpina/contratos-tce").json()
    assert d["anos"] == [2025] and d["qtd"] == 4
    assert d["total"] == "39732849.55" and d["total_sem_disputa"] == "100000.00"
    assert d["fornecedores"][0]["cpf_cnpj"] == "36575014000180" and d["fornecedores"][0]["qtd"] == 3
    lista = cliente.get("/api/municipios/PE/Carpina/contratos-tce/lista", params={"busca": "fulano"}).json()
    assert lista["total"] == 1
    item = lista["itens"][0]
    assert item["cpf_cnpj"] == "***.***.724-69" and item["url_documento"].endswith(".pdf")
    assert item["vigencia_fim"] == "2026-08-11" and item["orgao"] == "Prefeitura Municipal de Carpina"
    assert cliente.get("/api/municipios/PE/Carpina/contratos-tce/lista",
                       params={"tipo_processo": "Dispensa"}).json()["total"] == 1
    assert cliente.get("/api/municipios/PE/Recife/contratos-tce").status_code == 404


def test_alerta_contrato_acima_do_capital(fabrica: sessionmaker[Session], settings: Settings) -> None:
    with fabrica() as db:
        _popular(db)
        [alerta] = alertas_contrato_capital(db, settings)
    assert alerta["cnpj"] == "36575014000180" and alerta["unidade_gestora_id"] == 169
    assert alerta["valor_centavos"] == 3_968_585_035 and alerta["gravidade"] == "media"  # ~16x o capital
    assert "16 vezes" in alerta["descricao"]
    assert date(2025, 1, 1).year == alerta["ano"]
