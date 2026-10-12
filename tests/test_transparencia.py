from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from civic import demo, transparencia
from civic.api import app
from civic.database import get_db
from civic.models import ContaMunicipal


def test_calcular_pendencias(fabrica: sessionmaker[Session]) -> None:
    with fabrica() as db:
        demo.popular(db)  # contas DCA 2024 e 2025, sem RREO de 2026; contratos PNCP de 2025 só na Vila Exemplo
        db.add(ContaMunicipal(codigo_ibge="2699902", ano=2026, cod_conta="TOTAL", conta="Total", nivel="total",
                              demonstrativo="RREO", periodo=4, empenhado_centavos=1, liquidado_centavos=1,
                              pago_centavos=0))
        db.commit()
        itens = {i["codigo_ibge"]: i for i in transparencia.calcular(db, hoje=date(2026, 10, 11))}
    vila = itens["2699901"]
    assert any("RREO" in p and "nenhum entregue" in p for p in vila["pendencias"])
    assert not any("DCA" in p for p in vila["pendencias"])  # DCA 2025 entregue
    assert any("PNCP há" in p for p in vila["pendencias"])  # último contrato em 2025: mais de 180 dias
    vizinha = itens["2699902"]
    assert vizinha["rreo_bimestre"] == 4 and not any("RREO" in p for p in vizinha["pendencias"])
    assert any("Nenhum contrato publicado no PNCP" in p for p in vizinha["pendencias"])
    assert vila["tribunal"] == "TCE-PE" and vila["tribunal_ultimo_mes"] == 202608


@pytest.fixture()
def cliente(fabrica: sessionmaker[Session]) -> Iterator[TestClient]:
    with fabrica() as db:
        demo.popular(db)
    transparencia._CACHE.clear()

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()
    transparencia._CACHE.clear()


def test_api_transparencia(cliente: TestClient) -> None:
    d = cliente.get("/api/transparencia", params={"uf": "PE", "limit": 3}).json()
    assert d["total"] == 7 and d["com_pendencia"] >= 1 and len(d["itens"]) == 3
    um = cliente.get("/api/municipios/PE/Vila Exemplo/transparencia").json()
    assert um["nome"] == "Vila Exemplo" and um["pendencias"]
    assert cliente.get("/api/municipios/PE/Atlantida/transparencia").status_code == 404
