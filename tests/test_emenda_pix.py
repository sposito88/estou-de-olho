from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from civic import transferegov
from civic.alertas import alertas_emenda_pix
from civic.api import app
from civic.cleaning import despesa_municipal_do_tce
from civic.config import Settings
from civic.database import get_db
from civic.models import DespesaMunicipal, Municipio, PlanoPix, RepassePix, UnidadeGestora
from tests.conftest import AGORA
from tests.test_pernambuco import EMPENHO

PIX = "Transferência Especial da União"


def test_montar_planos_e_repasses() -> None:
    planos = transferegov.montar_planos(
        [{"id_plano_acao": 1, "codigo_plano_acao": "X-1", "ano_plano_acao": 2023, "situacao_plano_acao": "CIENTE",
          "cnpj_beneficiario_plano_acao": "11.097.342/0001-98", "nome_parlamentar_emenda_plano_acao": "Fulano",
          "valor_custeio_plano_acao": 0, "valor_investimento_plano_acao": 500000.0}],
        [{"id_plano_acao": 1, "id_executor": 9, "objeto_executor": "Construção de UBS"}],
        [{"id_executor": 9, "id_meta": 1, "nome_meta": "Meta 1", "desc_meta": "UBS no bairro Santo Antônio"},
         {"id_executor": 9, "id_meta": 2, "nome_meta": "Meta 1", "desc_meta": "UBS no bairro Santo Antônio"}],
        [{"id_relatorio_gestao": 1, "id_plano_acao": 1, "situacao_relatorio_gestao": "EM_ELABORACAO",
          "parecer_relatorio_gestao": "x"},
         {"id_relatorio_gestao": 2, "id_plano_acao": 1, "situacao_relatorio_gestao": "DISPONIBILIZADO",
          "parecer_relatorio_gestao": "Obra concluída"}],
        {"11097342000198": "2604007"},
    )
    assert len(planos) == 1
    p = planos[0]
    assert (p["municipio_ibge"], p["investimento_centavos"], p["objeto"]) == ("2604007", 50_000_000, "Construção de UBS")
    assert p["metas"] == "UBS no bairro Santo Antônio"  # sem repetir
    assert p["relatorio_situacao"] == "DISPONIBILIZADO"  # o mais recente

    repasses = transferegov.montar_repasses(
        [{"id_empenho": 5, "id_plano_acao": 1}],
        [{"id_dh": 10, "id_empenho": 5, "situacao_dh": 3, "data_emissao_dh": "2023-09-28", "valor_dh": 500000.0},
         {"id_dh": 11, "id_empenho": 5, "situacao_dh": 1, "data_emissao_dh": "2023-10-01", "valor_dh": 1.0}],
    )
    assert repasses == [{"id": 10, "plano_id": 1, "data": date(2023, 9, 28), "valor_centavos": 50_000_000}]


def test_paginas_segue_ate_pagina_vazia(settings: Settings) -> None:
    class Cliente:
        def __init__(self) -> None:
            self.offsets: list[int] = []

        def get(self, url: str, params: dict[str, int]) -> list[dict[str, int]]:
            self.offsets.append(params["offset"])
            restantes = max(0, 2_500 - params["offset"])
            return [{"id": params["offset"] + i} for i in range(min(1_000, restantes))]  # corta em 1.000

    cliente = Cliente()
    linhas = list(transferegov.paginas(cliente, settings, "t", "*", "id"))  # type: ignore[arg-type]
    assert len(linhas) == 2_500 and cliente.offsets == [0, 1_000, 2_000, 2_500]


def _gasto(chave: str, ano: int, mes: int, valor: str, categoria: str = "Despesa Corrente",
           fonte: str = PIX, cnpj: str = "08777708000165") -> DespesaMunicipal:
    d = despesa_municipal_do_tce({
        **EMPENHO, "ID_EMPENHO": chave, "ID_UNIDADE_GESTORA": "169", "ANOREFERENCIA": str(ano),
        "MESREFERENCIA": str(mes), "DATAEMPENHO": f"{ano}-{mes:02d}-10", "CPF_CNPJ": cnpj, "FORNECEDOR": "AXIALMED",
        "VALORPAGO": valor, "VALOREMPENHADO": valor, "FONTERECURSO": fonte, "CATEGORIA": categoria,
    })
    return DespesaMunicipal(**d)


def _popular(db: Session) -> None:
    db.add(Municipio(codigo_ibge="2604007", nome="Carpina", nome_normalizado="CARPINA", sigla_uf="PE"))
    db.add(UnidadeGestora(id=169, nome="Prefeitura Municipal de Carpina", natureza="Prefeitura Municipal",
                          codigo_municipio_tce="P042", municipio="Carpina", municipio_normalizado="CARPINA"))
    db.flush()
    for i, (ano, inv, data) in enumerate([(2023, 500_000, date(2023, 9, 28)), (2024, 500_000, date(2024, 6, 28)),
                                          (2025, 990_000, date(2025, 12, 2))], start=1):
        db.add(PlanoPix(id=i, ano=ano, situacao="CIENTE", municipio_ibge="2604007", parlamentar=f"Dep {i}",
                        objeto="Obra", investimento_centavos=inv * 100, custeio_centavos=0, atualizado_em=AGORA))
        db.add(RepassePix(id=i, plano_id=i, data=data, valor_centavos=inv * 100))
    db.add_all([
        _gasto("1", 2024, 6, "4000000.00"),  # R$ 4 mi corrente em 2024 (recebido até 2024: R$ 1 mi)
        _gasto("2", 2024, 7, "60000.00", categoria="Despesa de Capital"),
        _gasto("3", 2026, 3, "77.00"),  # quase nada depois do repasse de dez/2025
        _gasto("4", 2026, 8, "100.00", fonte="Recursos Ordinários"),  # cobertura até ago/2026
        _gasto("5", 2026, 2, "300000.00", fonte="Transferência Especial dos Estados"),
    ])
    db.commit()


def test_alertas_emenda_pix(fabrica: sessionmaker[Session], settings: Settings) -> None:
    with fabrica() as db:
        _popular(db)
        alertas = {a["tipo"]: a for a in alertas_emenda_pix(db, settings)}
    assert set(alertas) == {"pix_parado", "pix_custeio", "pix_gasto_maior"}
    parado = alertas["pix_parado"]
    assert parado["valor_centavos"] == 99_000_000 - 7_700 and parado["gravidade"] == "media"
    assert "dez/2025" in parado["titulo"] and "ago/2026" in parado["descricao"]
    custeio = alertas["pix_custeio"]
    assert custeio["ano"] == 2024 and custeio["gravidade"] == "alta" and custeio["valor_centavos"] == 400_000_000
    maior = alertas["pix_gasto_maior"]
    assert maior["ano"] == 2024 and maior["valor_centavos"] == 406_000_000 - 100_000_000
    assert all(a["unidade_gestora_id"] == 169 and a["municipio_ibge"] == "2604007" for a in alertas.values())


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


def test_api_emenda_pix(cliente: TestClient) -> None:
    d = cliente.get("/api/municipios/PE/Carpina/emenda-pix").json()
    assert d["tem_gastos"] and d["gastos_ate"] == {"ano": 2026, "mes": 8}
    assert d["total_recebido"] == "1990000.00" and d["total_gasto"] == "4060077.00"
    assert d["total_gasto_estadual"] == "300000.00"
    ano_2024 = next(a for a in d["anos"] if a["ano"] == 2024)
    assert (ano_2024["recebido"], ano_2024["gasto_corrente"], ano_2024["gasto_capital"]) == (
        "500000.00", "4000000.00", "60000.00")
    assert [p["ano"] for p in d["planos"]] == [2025, 2024, 2023]
    assert d["planos"][0]["recebido"] == "990000.00" and d["planos"][0]["ultimo_repasse"] == "2025-12-02"
    assert d["credores"][0]["cpf_cnpj"] == "08777708000165"
    gastos = cliente.get("/api/municipios/PE/Carpina/empenhos", params={"fonte": "pix"}).json()
    assert gastos["total"] == 3 and gastos["itens"][0]["fonte_recurso"] == PIX
    assert cliente.get("/api/municipios/PE/Recife/emenda-pix").status_code == 404
