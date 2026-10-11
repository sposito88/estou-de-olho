from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from civic import queries
from civic.api import app
from civic.database import get_db
from civic.models import (
    Alerta,
    Candidato,
    ContaMunicipal,
    ContratoPncp,
    DespesaSenado,
    Municipio,
    Senador,
    SyncPncpDia,
)
from tests.conftest import AGORA


def _conta(ibge: str, cod: str, nome: str, nivel: str, pago: int) -> ContaMunicipal:
    return ContaMunicipal(codigo_ibge=ibge, ano=2024, cod_conta=cod, conta=nome, nivel=nivel,
                          empenhado_centavos=pago, liquidado_centavos=pago, pago_centavos=pago)


def _popular(db: Session) -> None:
    # 6 municípios de PE com 1.000 habitantes; saúde de R$ 100 a R$ 600 por habitante.
    for i in range(6):
        ibge = f"26000{i:02d}"
        db.add(Municipio(codigo_ibge=ibge, nome=f"Cidade {i}", nome_normalizado=f"CIDADE {i}", sigla_uf="PE",
                         populacao=1000))
        db.add(_conta(ibge, "10", "10 - Saúde", "funcao", (i + 1) * 100 * 100 * 1000))
        db.add(_conta(ibge, "TOTAL", "Despesas Exceto Intraorçamentárias", "total", (i + 1) * 1000 * 100 * 1000))
    db.add(_conta("2600000", "04.131", "04.131 - Comunicação Social", "subfuncao", 5_000_000))
    db.add_all(
        [
            ContratoPncp(numero_controle="08985624000117-2-000001/2025", orgao_cnpj="08985624000117",
                         orgao_nome="CAMARA MUNICIPAL", municipio_ibge="2600000", fornecedor_ni="39727407000150",
                         fornecedor_nome="ADVOGADOS ASSOCIADOS", tipo_pessoa="PJ", objeto="Serviços jurídicos",
                         objeto_normalizado="SERVICOS JURIDICOS", categoria="Serviços",
                         valor_global_centavos=16_800_000, valor_inicial_centavos=16_800_000,
                         data_assinatura=date(2025, 1, 3), ano=2025, atualizado_em=AGORA),
            ContratoPncp(numero_controle="x-2-000002/2025", orgao_cnpj="11111111000199", orgao_nome="PREFEITURA",
                         municipio_ibge="2600000", fornecedor_ni="22222222000122", fornecedor_nome="CONSTRUTORA",
                         tipo_pessoa="PJ", objeto="Pavimentação da Rua A", objeto_normalizado="PAVIMENTACAO DA RUA A",
                         categoria="Obras", valor_global_centavos=50_000_000, valor_inicial_centavos=50_000_000,
                         data_assinatura=date(2025, 6, 1), ano=2025, atualizado_em=AGORA),
            SyncPncpDia(data=date(2024, 1, 1), registros=0, concluido_em=AGORA),
            Candidato(sq_candidato="1", ano=2024, cargo="VEREADOR", municipio_ibge="2600000", nome="ANA SOUZA LIMA",
                      nome_normalizado="ANA SOUZA LIMA", sigla_partido="DC", eleito=True, bens_centavos=10_000_000),
            Candidato(sq_candidato="2", ano=2024, cargo="PREFEITO", municipio_ibge="2600000", nome="JOSE PREFEITO",
                      nome_normalizado="JOSE PREFEITO", sigla_partido="PSB", eleito=True, bens_centavos=0),
            Candidato(sq_candidato="3", ano=2024, cargo="VEREADOR", municipio_ibge="2600000", nome="SUPLENTE",
                      nome_normalizado="SUPLENTE", eleito=False),
            Senador(id=5672, nome="Alan Rick", nome_normalizado="ALAN RICK", sigla_partido="UNIÃO", sigla_uf="AC",
                    em_exercicio=True, atualizado_em=AGORA),
            DespesaSenado(senador_id=5672, nome_senador="ALAN RICK", ano=2025, mes=1, tipo_despesa="Aluguel",
                          cnpj_cpf="66970229013226", tipo_pessoa="PJ", fornecedor="CLARO", data=date(2025, 1, 18),
                          valor_centavos=39_944),
        ]
    )
    db.flush()
    db.add_all(
        [
            Alerta(tipo="empresa_nova", gravidade="alta", esfera="municipal", orgao_cnpj="11111111000199",
                   orgao_nome="PREFEITURA", municipio_ibge="2600000", cnpj="22222222000122", ano=2025,
                   valor_centavos=50_000_000, titulo="Construtora aberta 10 dias antes", descricao="...",
                   calculado_em=AGORA),
            Alerta(tipo="empresa_nova", gravidade="media", esfera="senado", senador_id=5672, ano=2025,
                   valor_centavos=1, titulo="Senado", descricao="...", calculado_em=AGORA),
        ]
    )
    db.commit()


@pytest.fixture()
def cliente(fabrica: sessionmaker[Session]) -> Iterator[TestClient]:
    with fabrica() as db:
        _popular(db)
    queries._MEDIANAS_CACHE.clear()

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_contratos_do_municipio(cliente: TestClient) -> None:
    corpo = cliente.get("/api/municipios/PE/Cidade 0/contratos").json()
    assert corpo["total_contratado"] == "668000.00"
    assert corpo["qtd_contratos"] == 2
    assert corpo["cobertura_desde"] == "2024-01-01"
    assert 0 <= corpo["cobertura_pct"] < 5  # só 1 dia coletado
    assert [o["nome"] for o in corpo["por_orgao"]] == ["PREFEITURA", "CAMARA MUNICIPAL"]
    lista = cliente.get("/api/municipios/PE/Cidade 0/contratos/lista", params={"busca": "pavimentação"}).json()
    assert lista["total"] == 1 and lista["itens"][0]["fornecedor_nome"] == "CONSTRUTORA"
    juridico = cliente.get("/api/municipios/PE/Cidade 0/contratos/lista", params={"orgao_cnpj": "08985624000117"}).json()
    assert juridico["itens"][0]["url"] == "https://pncp.gov.br/app/contratos/08985624000117/2025/1"
    assert cliente.get("/api/municipios/PE/Atlantida/contratos").status_code == 404


def test_contas_com_medianas(cliente: TestClient) -> None:
    corpo = cliente.get("/api/municipios/PE/Cidade 5/contas").json()
    assert corpo["ano"] == 2024 and corpo["populacao"] == 1000
    saude = next(f for f in corpo["funcoes"] if f["codigo"] == "10")
    assert saude["nome"] == "Saúde"
    assert saude["por_habitante"] == "600.00"
    assert saude["mediana_uf"] == "350.00"  # mediana de 100..600
    assert corpo["por_habitante"] == "6000.00"
    assert (corpo["amostra_uf"], corpo["amostra_brasil"]) == (6, 6)
    destaques = cliente.get("/api/municipios/PE/Cidade 0/contas").json()["destaques"]
    assert [d["nome"] for d in destaques] == ["Comunicação Social"]


def test_eleitos(cliente: TestClient) -> None:
    corpo = cliente.get("/api/municipios/PE/Cidade 0/eleitos").json()
    assert corpo["qtd_candidaturas"] == 3
    assert [(e["cargo"], e["nome"]) for e in corpo["eleitos"]] == [("PREFEITO", "JOSE PREFEITO"), ("VEREADOR", "ANA SOUZA LIMA")]
    assert corpo["eleitos"][1]["bens"] == "100000.00"


def test_senadores(cliente: TestClient) -> None:
    lista = cliente.get("/api/senadores", params={"ano": 2025}).json()
    assert [(i["senador"]["nome"], i["total"]) for i in lista] == [("Alan Rick", "399.44")]
    det = cliente.get("/api/senadores/5672", params={"ano": 2025}).json()
    assert det["notas"]["itens"][0]["valor"] == "399.44"
    assert det["por_fornecedor"][0]["cnpj"] == "66970229013226"
    assert cliente.get("/api/senadores/1").status_code == 404
    assert cliente.get("/api/senadores/resumo").json()["por_rubrica"][0]["rubrica"] == "Aluguel"


def test_alertas_da_cidade_e_do_senador(cliente: TestClient) -> None:
    cidade = cliente.get("/api/alertas", params={"municipio_ibge": "2600000"}).json()
    assert cidade["total"] == 1
    assert cidade["itens"][0]["orgao_contratante"] == {"cnpj": "11111111000199", "nome": "PREFEITURA"}
    senado = cliente.get("/api/alertas", params={"senador_id": 5672}).json()
    assert senado["itens"][0]["senador"]["nome"] == "Alan Rick"
    assert cliente.get("/api/alertas", params={"esfera": "senado"}).json()["total"] == 1
