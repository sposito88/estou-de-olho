from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civic.api import app
from civic.cleaning import gerar_hash, normalizar_nome
from civic.database import Base, get_db
from civic.models import Deputado, Despesa, Emenda, EmendaPagamento, SyncExecucao

AGORA = datetime(2026, 10, 7, 12, 0, 0)


def _deputado(id_: int, nome: str, partido: str, uf: str) -> Deputado:
    return Deputado(
        id=id_,
        nome=nome,
        nome_normalizado=normalizar_nome(nome) or "",
        sigla_partido=partido,
        sigla_uf=uf,
        url_foto=f"https://exemplo/{id_}.jpg",
        id_legislatura=57,
        atualizado_em=AGORA,
    )


def _despesa(
    deputado_id: int,
    ano: int,
    mes: int,
    tipo: str,
    documento: int,
    liquido: int,
    data: date | None,
    num: str,
) -> Despesa:
    return Despesa(
        hash_unico=gerar_hash(deputado_id, ano, mes, None, num, "12345678000195", documento, 0),
        deputado_id=deputado_id,
        ano=ano,
        mes=mes,
        data_documento=data,
        tipo_despesa=tipo,
        tipo_documento="Nota Fiscal",
        num_documento=num,
        cod_documento=None,
        fornecedor="Fornecedor X",
        cnpj_cpf="12345678000195",
        tipo_pessoa="PJ",
        valor_documento_centavos=documento,
        valor_glosa_centavos=documento - liquido,
        valor_liquido_centavos=liquido,
        url_documento=None if data is None else f"https://exemplo/{num}.pdf",
        parcela=0,
    )


def _pagamento(
    autor: str, deputado_id: int | None, municipio: str, ano: int, mes: int, valor: int, codigo: str
) -> EmendaPagamento:
    return EmendaPagamento(
        codigo_emenda=codigo,
        ano_emenda=int(codigo[:4]),
        ano=ano,
        mes=mes,
        tipo_emenda="Emenda Individual",
        codigo_autor="1",
        nome_autor=autor,
        nome_autor_normalizado=normalizar_nome(autor),
        deputado_id=deputado_id,
        numero_emenda="0001",
        codigo_favorecido="11222333000144",
        favorecido="FUNDO MUNICIPAL DE SAUDE",
        tipo_favorecido="Pessoa Jurídica",
        sigla_uf="PE",
        municipio=municipio,
        municipio_normalizado=normalizar_nome(municipio),
        valor_recebido_centavos=valor,
    )


def _popular(db: Session) -> None:
    db.add_all(
        [
            _deputado(1, "Ana Souza", "PT", "SP"),
            _deputado(2, "Túlio Gadêlha", "PSD", "PE"),
            _deputado(3, "Sem Gastos", "PL", "PE"),
        ]
    )
    db.flush()
    db.add_all(
        [
            # Ana: documento 1.050,00 / líquido 950,00 em 2024
            _despesa(1, 2024, 3, "COMBUSTÍVEIS", 100_000, 90_000, date(2024, 3, 10), "A1"),
            _despesa(1, 2024, 5, "TELEFONIA", 5_000, 5_000, None, "A2"),
            _despesa(1, 2023, 7, "TELEFONIA", 1_000, 1_000, date(2023, 7, 1), "A3"),
            # Túlio: documento 2.000,00 mas líquido só 600,00 (glosa)
            _despesa(2, 2024, 4, "COMBUSTÍVEIS", 200_000, 60_000, date(2024, 4, 20), "T1"),
        ]
    )
    db.add_all(
        [
            Emenda(
                codigo_emenda="202400020001",
                ano=2024,
                tipo_emenda="Emenda Individual",
                nome_autor="TULIO GADELHA",
                nome_autor_normalizado="TULIO GADELHA",
                deputado_id=2,
                funcao="Saúde",
                valor_empenhado_centavos=100_000,
                valor_liquidado_centavos=40_000,
                valor_pago_centavos=40_000,
                valor_rp_pago_centavos=10_000,
            ),
            _pagamento("TULIO GADELHA", 2, "CARPINA", 2024, 3, 30_000, "202400020001"),
            _pagamento("BANCADA DE PERNAMBUCO", None, "CARPINA", 2024, 5, 100_000, "202471000001"),
            _pagamento("TULIO GADELHA", 2, "RECIFE", 2023, 1, 5_000, "202300020009"),
            SyncExecucao(fonte="camara-api", concluido_em=AGORA, registros=4),
            SyncExecucao(fonte="emendas", concluido_em=datetime(2026, 10, 6), registros=3),
        ]
    )
    db.commit()


@pytest.fixture()
def client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with fabrica() as db:
        _popular(db)

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    # Sem o bloco `with`, o lifespan (init_db no banco real) não roda.
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


# --------------------------------------------------------------------------- deputados / filtros


def test_lista_deputados(client: TestClient) -> None:
    r = client.get("/api/deputados")
    assert r.status_code == 200
    assert [d["nome"] for d in r.json()] == ["Ana Souza", "Sem Gastos", "Túlio Gadêlha"]


def test_lista_deputados_filtra_uf_sem_diferenciar_caixa(client: TestClient) -> None:
    r = client.get("/api/deputados", params={"uf": "pe"})
    assert {d["id"] for d in r.json()} == {2, 3}


def test_lista_deputados_filtra_partido(client: TestClient) -> None:
    assert [d["id"] for d in client.get("/api/deputados", params={"partido": "pt"}).json()] == [1]


def test_filtros(client: TestClient) -> None:
    corpo = client.get("/api/filtros").json()
    assert corpo == {
        "ufs": ["PE", "SP"],
        "partidos": ["PL", "PSD", "PT"],
        "anos": [2024, 2023],
        "anos_emendas": [2024, 2023],
    }


# --------------------------------------------------------------------------- CEAP


def test_ranking_usa_valor_liquido(client: TestClient) -> None:
    corpo = client.get("/api/gastos/ranking", params={"ano": 2024}).json()
    assert [item["deputado"]["id"] for item in corpo] == [1, 2]
    assert corpo[0]["total_liquido"] == "950.00"
    assert corpo[0]["qtd_despesas"] == 2
    assert corpo[1]["total_liquido"] == "600.00"


def test_ranking_respeita_limit_e_filtros(client: TestClient) -> None:
    assert len(client.get("/api/gastos/ranking", params={"limit": 1}).json()) == 1
    corpo = client.get("/api/gastos/ranking", params={"uf": "PE"}).json()
    assert [item["deputado"]["id"] for item in corpo] == [2]


@pytest.mark.parametrize("limit", [0, 101])
def test_ranking_valida_limit(client: TestClient, limit: int) -> None:
    assert client.get("/api/gastos/ranking", params={"limit": limit}).status_code == 422


@pytest.mark.parametrize("params", [{"uf": "PER"}, {"uf": "1A"}, {"ano": 1999}, {"ano": "x"}])
def test_parametros_invalidos(client: TestClient, params: dict[str, object]) -> None:
    assert client.get("/api/gastos/ranking", params=params).status_code == 422


def test_por_tipo(client: TestClient) -> None:
    corpo = client.get("/api/gastos/por-tipo", params={"ano": 2024}).json()
    assert corpo == [
        {"tipo_despesa": "COMBUSTÍVEIS", "total_liquido": "1500.00", "qtd_despesas": 2},
        {"tipo_despesa": "TELEFONIA", "total_liquido": "50.00", "qtd_despesas": 1},
    ]


def test_resumo(client: TestClient) -> None:
    assert client.get("/api/gastos/resumo").json() == {
        "total_liquido": "1560.00",
        "qtd_deputados": 2,
        "qtd_despesas": 4,
    }
    assert client.get("/api/gastos/resumo", params={"uf": "PE", "ano": 2023}).json() == {
        "total_liquido": "0.00",
        "qtd_deputados": 0,
        "qtd_despesas": 0,
    }


def test_gastos_deputado(client: TestClient) -> None:
    corpo = client.get("/api/deputados/1/gastos", params={"limit": 2}).json()
    assert corpo["deputado"]["nome"] == "Ana Souza"
    assert corpo["total_liquido"] == "960.00"
    assert corpo["qtd_despesas"] == 3
    assert corpo["serie_mensal"] == [
        {"ano": 2023, "mes": 7, "total_liquido": "10.00"},
        {"ano": 2024, "mes": 3, "total_liquido": "900.00"},
        {"ano": 2024, "mes": 5, "total_liquido": "50.00"},
    ]
    pagina = corpo["despesas"]
    assert pagina["total"] == 3
    assert [d["num_documento"] for d in pagina["itens"]] == ["A1", "A3"]
    primeira = pagina["itens"][0]
    assert primeira["valor_documento"] == "1000.00"
    assert primeira["valor_glosa"] == "100.00"
    assert primeira["valor_liquido"] == "900.00"
    assert primeira["data_documento"] == "2024-03-10"


def test_gastos_deputado_por_ano_e_offset(client: TestClient) -> None:
    corpo = client.get("/api/deputados/1/gastos", params={"ano": 2024, "offset": 1}).json()
    assert corpo["total_liquido"] == "950.00"
    assert [d["num_documento"] for d in corpo["despesas"]["itens"]] == ["A2"]


def test_gastos_deputado_inexistente(client: TestClient) -> None:
    r = client.get("/api/deputados/999/gastos")
    assert r.status_code == 404
    assert r.json()["detail"] == "Deputado não encontrado"


def test_despesas_ordem_e_paginacao(client: TestClient) -> None:
    corpo = client.get("/api/despesas").json()
    assert corpo["total"] == 4
    # Datas desc; a despesa sem data vai para o fim.
    assert [d["num_documento"] for d in corpo["itens"]] == ["T1", "A1", "A3", "A2"]
    assert corpo["itens"][0]["deputado"]["nome"] == "Túlio Gadêlha"
    assert corpo["itens"][-1]["url_documento"] is None

    pagina = client.get("/api/despesas", params={"limit": 1, "offset": 1, "ano": 2024}).json()
    assert pagina["total"] == 3
    assert [d["num_documento"] for d in pagina["itens"]] == ["A1"]


# --------------------------------------------------------------------------- emendas


def test_busca_municipio_ignora_acento_e_caixa(client: TestClient) -> None:
    corpo = client.get("/api/municipios", params={"busca": "carpína"}).json()
    assert corpo == [
        {"sigla_uf": "PE", "municipio": "CARPINA", "total_recebido": "1300.00", "qtd_pagamentos": 2}
    ]


def test_busca_municipio_ordena_por_total(client: TestClient) -> None:
    corpo = client.get("/api/municipios", params={"uf": "pe"}).json()
    assert [m["municipio"] for m in corpo] == ["CARPINA", "RECIFE"]


def test_emendas_municipio(client: TestClient) -> None:
    corpo = client.get("/api/municipios/pe/Carpina/emendas").json()
    assert corpo["municipio"] == "CARPINA"
    assert corpo["total_recebido"] == "1300.00"
    assert corpo["qtd_pagamentos"] == 2
    assert corpo["qtd_autores"] == 2

    bancada, tulio = corpo["por_autor"]
    assert bancada["nome_autor"] == "BANCADA DE PERNAMBUCO"
    assert bancada["deputado"] is None
    assert tulio["deputado"]["id"] == 2
    assert tulio["total_recebido"] == "300.00"

    assert corpo["por_funcao"] == [
        {"funcao": "Não informada", "total": "1000.00"},
        {"funcao": "Saúde", "total": "300.00"},
    ]
    assert corpo["serie_mensal"] == [
        {"ano": 2024, "mes": 3, "total_recebido": "300.00"},
        {"ano": 2024, "mes": 5, "total_recebido": "1000.00"},
    ]
    assert corpo["por_favorecido"][0]["favorecido"] == "FUNDO MUNICIPAL DE SAUDE"


def test_emendas_municipio_inexistente(client: TestClient) -> None:
    assert client.get("/api/municipios/PE/Atlantida/emendas").status_code == 404
    assert client.get("/api/municipios/PE/Carpina/emendas", params={"ano": 2023}).status_code == 404


def test_pagamentos_municipio(client: TestClient) -> None:
    corpo = client.get("/api/municipios/PE/CARPINA/pagamentos", params={"limit": 1}).json()
    assert corpo["total"] == 2
    assert len(corpo["itens"]) == 1
    assert corpo["itens"][0]["mes"] == 5
    assert corpo["itens"][0]["valor_recebido"] == "1000.00"


def test_emendas_deputado(client: TestClient) -> None:
    corpo = client.get("/api/deputados/2/emendas").json()
    assert corpo["qtd_emendas"] == 1
    assert corpo["total_empenhado"] == "1000.00"
    assert corpo["total_pago"] == "500.00"
    assert corpo["total_recebido_municipios"] == "350.00"
    assert [d["municipio"] for d in corpo["por_destino"]] == ["CARPINA", "RECIFE"]
    assert corpo["por_funcao"] == [{"funcao": "Saúde", "total": "500.00"}]

    assert client.get("/api/deputados/2/emendas", params={"ano": 2023}).json()["qtd_emendas"] == 0
    assert client.get("/api/deputados/999/emendas").status_code == 404


# --------------------------------------------------------------------------- infra


def test_health(client: TestClient) -> None:
    corpo = client.get("/health").json()
    assert corpo["status"] == "ok"
    assert corpo["ultimo_sync"] == "2026-10-07T12:00:00"
    assert set(corpo["fontes"]) == {"camara-api", "emendas"}


def test_cors_localhost(client: TestClient) -> None:
    r = client.get("/api/filtros", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    r = client.get("/api/filtros", headers={"Origin": "https://malicioso.example"})
    assert "access-control-allow-origin" not in r.headers


# --------------------------------------------------------------------------- etapa 2-4: extras


@pytest.fixture()
def client_completo() -> Iterator[TestClient]:
    """Base de teste com município do IBGE, fornecedor da Receita, convênio e alertas."""
    from civic.models import Alerta, EmendaConvenio, Fornecedor, Municipio

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with fabrica() as db:
        _popular(db)
        db.add_all(
            [
                Municipio(codigo_ibge="2604007", nome="Carpina", nome_normalizado="CARPINA", sigla_uf="PE",
                          regiao_imediata_id="260006", regiao_imediata_nome="Carpina", populacao=1000,
                          ano_populacao=2026),
                Municipio(codigo_ibge="2610400", nome="Paudalho", nome_normalizado="PAUDALHO", sigla_uf="PE",
                          regiao_imediata_id="260006", regiao_imediata_nome="Carpina", populacao=500,
                          ano_populacao=2026),
                Municipio(codigo_ibge="2611606", nome="Recife", nome_normalizado="RECIFE", sigla_uf="PE",
                          regiao_imediata_id="260001", regiao_imediata_nome="Recife", populacao=1_500_000,
                          ano_populacao=2026),
                Fornecedor(cnpj="12345678000195", razao_social="FORNECEDOR X LTDA", sigla_uf="PE",
                           municipio="CARPINA", codigo_municipio_ibge="2604007", situacao_cadastral="ATIVA",
                           capital_social_centavos=None, referencia="2026-09", atualizado_em=AGORA),
                EmendaConvenio(codigo_emenda="202400020001", objeto="CONSTRUCAO DE UBS", valor_centavos=30_000),
                Alerta(tipo="concentracao", gravidade="alta", deputado_id=1, cnpj="12345678000195", ano=2024,
                       valor_centavos=95_000, titulo="Fornecedor X recebeu 95%", descricao="...", calculado_em=AGORA),
                Alerta(tipo="padrao_atipico", gravidade="media", deputado_id=2, cnpj=None, ano=2024,
                       valor_centavos=0, titulo="Notas no fim de semana", descricao="...", calculado_em=AGORA),
            ]
        )
        db.get(EmendaPagamento, 1).tipo_emenda = "Emenda Individual - Transferências Especiais"  # type: ignore[union-attr]
        # Despesa de pessoa física, para testar a máscara de CPF.
        db.add(
            Despesa(
                hash_unico="pf", deputado_id=3, ano=2024, mes=1, data_documento=date(2024, 1, 2),
                tipo_despesa="TELEFONIA", tipo_documento="Recibos/Outros", num_documento="9", cod_documento=None,
                fornecedor="Pessoa Física", cnpj_cpf="12345678909", tipo_pessoa="PF",
                valor_documento_centavos=100, valor_glosa_centavos=0, valor_liquido_centavos=100,
                url_documento=None, parcela=0,
            )
        )
        db.commit()

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def test_api_mascara_cpf(client_completo: TestClient) -> None:
    corpo = client_completo.get("/api/deputados/3/gastos").json()
    assert corpo["despesas"]["itens"][0]["cnpj_cpf"] == "***.456.789-**"
    cnpj = client_completo.get("/api/deputados/1/gastos").json()["despesas"]["itens"][0]["cnpj_cpf"]
    assert cnpj == "12345678000195"


def test_ranking_relativo_ao_estado(client_completo: TestClient) -> None:
    corpo = client_completo.get("/api/gastos/ranking", params={"ordem": "relativo"}).json()
    # Ninguém tem 6+ meses com despesa nesta base: sem média, índice nulo.
    assert all(item["indice_uf"] is None for item in corpo)
    assert client_completo.get("/api/gastos/ranking", params={"ordem": "outra"}).status_code == 422


def test_alertas_e_resumo(client_completo: TestClient) -> None:
    corpo = client_completo.get("/api/alertas").json()
    assert corpo["total"] == 2
    assert corpo["itens"][0]["gravidade"] == "alta"
    assert corpo["itens"][0]["valor"] == "950.00"
    assert corpo["itens"][0]["deputado"]["nome"] == "Ana Souza"
    assert client_completo.get("/api/alertas", params={"uf": "PE"}).json()["total"] == 1
    assert client_completo.get("/api/alertas", params={"cnpj": "12345678000195"}).json()["total"] == 1
    assert client_completo.get("/api/alertas", params={"gravidade": "baixa"}).status_code == 422

    resumo = client_completo.get("/api/alertas/resumo").json()
    assert resumo == {
        "total": 2,
        "altas": 1,
        "qtd_deputados": 2,
        "por_tipo": [
            {"tipo": "concentracao", "alta": 1, "media": 0},
            {"tipo": "padrao_atipico", "alta": 0, "media": 1},
        ],
        "por_esfera": {"federal": 2},
    }
    assert "concentracao" in client_completo.get("/api/alertas/tipos").json()


def test_fornecedor(client_completo: TestClient) -> None:
    corpo = client_completo.get("/api/fornecedores/12345678000195").json()
    assert corpo["cadastro"]["razao_social"] == "FORNECEDOR X LTDA"
    assert corpo["cadastro"]["capital_social"] is None
    assert corpo["total_recebido"] == "1560.00"
    assert [d["deputado"]["id"] for d in corpo["por_deputado"]] == [1, 2]
    assert client_completo.get("/api/fornecedores/00000000000000").status_code == 404
    assert client_completo.get("/api/fornecedores/123").status_code == 422


def test_emendas_municipio_com_extras(client_completo: TestClient) -> None:
    corpo = client_completo.get("/api/municipios/PE/carpina/emendas").json()
    assert corpo["populacao"] == 1000
    assert corpo["por_habitante"] == "1.30"  # R$ 1.300,00 / 1.000 habitantes
    assert corpo["total_pix"] == "300.00"
    assert corpo["regiao_imediata"] == "Carpina"
    assert {a["acao"] for a in corpo["por_acao"]} == {"Ação não informada"}


def test_pagamentos_trazem_objeto_do_convenio(client_completo: TestClient) -> None:
    itens = client_completo.get("/api/municipios/PE/carpina/pagamentos").json()["itens"]
    objetos = {i["codigo_emenda"]: i["objeto"] for i in itens}
    assert objetos["202400020001"] == "CONSTRUCAO DE UBS"
    assert objetos["202471000001"] is None


def test_comparacao_regiao(client_completo: TestClient) -> None:
    corpo = client_completo.get("/api/municipios/PE/Carpina/comparacao").json()
    assert corpo["regiao_imediata"] == "Carpina"
    assert [(m["municipio"], m["por_habitante"], m["atual"]) for m in corpo["municipios"]] == [
        ("Carpina", "1.30", True),
        ("Paudalho", "0.00", False),
    ]
    assert client_completo.get("/api/municipios/PE/Atlantida/comparacao").status_code == 404


def test_cota_na_cidade(client_completo: TestClient) -> None:
    corpo = client_completo.get("/api/municipios/PE/Carpina/cota").json()
    assert corpo["base_cnpj_carregada"] is True
    assert corpo["total_liquido"] == "1560.00"
    assert [f["nome"] for f in corpo["por_fornecedor"]] == ["FORNECEDOR X LTDA"]
    assert client_completo.get("/api/municipios/PE/Carpina/cota", params={"ano": 2023}).json()["total_liquido"] == "10.00"


def test_feed_atom(client_completo: TestClient) -> None:
    r = client_completo.get("/api/municipios/PE/Carpina/feed.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/atom+xml")
    assert r.text.count("<entry>") == 2
    assert "R$ 1.000,00 de Bancada De Pernambuco" in r.text
    assert "CONSTRUCAO DE UBS" in r.text
