from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civic import tce_sp
from civic.api import app
from civic.config import Settings
from civic.database import Base, get_db, init_db
from civic.models import DespesaMunicipal, EnteSiconfi, Municipio, SyncMunicipioAno, UnidadeGestora
from civic.scraper import Resumo
from tests.test_pernambuco import ClienteFalso

PJ = "CNPJ - PESSOA JURÍDICA - 22669384000172"
PREFEITURA = "PREFEITURA MUNICIPAL DE ADAMANTINA"
CAMARA = "CÂMARA MUNICIPAL DE ADAMANTINA"


def _ev(evento: str, valor: str, orgao: str = PREFEITURA, fornecedor: str = PJ, empenho: str = "10-2025",
        dia: str = "10/03/2025", nome: str = "REAL PLACAS LTDA") -> dict[str, str]:
    return {"orgao": orgao, "mes": "Março", "evento": evento, "nr_empenho": empenho, "id_fornecedor": fornecedor,
            "nm_fornecedor": nome, "dt_emissao_despesa": dia, "vl_despesa": valor}


EVENTOS = [
    _ev("Empenhado", "1.000,00", dia="05/02/2025"),
    _ev("Anulação", "100,00"),
    _ev("Valor Liquidado", "900,00"),
    _ev("Valor Pago", "900,00"),
    _ev("Empenhado", "50,00", empenho="11-2025", dia="20/03/2025"),
    _ev("Empenhado", "300,00", orgao=CAMARA, fornecedor="PESSOA FÍSICA - 405568", nome="JOAO DA SILVA"),
    _ev("Valor Pago", "300,00", orgao=CAMARA, fornecedor="PESSOA FÍSICA - 405568", nome="JOAO DA SILVA"),
    _ev("Valor Pago", "70,00", orgao="CONSÓRCIO INTERMUNICIPAL DE SAÚDE"),
    # Repasse da prefeitura à câmara: não é fornecedor.
    _ev("Valor Pago", "200,00", fornecedor="CNPJ - PESSOA JURÍDICA - 01234567000189", empenho="13-2025",
        nome="CÂMARA MUNICIPAL DE ADAMANTINA"),
    # Folha e encargos: o próprio município aparece como credor.
    _ev("Valor Pago", "5.000,00", fornecedor="CNPJ - PESSOA JURÍDICA - 43008291000177", empenho="12-2025",
        nome="MUNICIPIO DE ADAMANTINA"),
]


# --------------------------------------------------------------------------- limpeza


def test_credor_do_tce_sp() -> None:
    assert tce_sp.credor_do_tce_sp(PJ) == ("22669384000172", "PJ", "22669384000172")
    assert tce_sp.credor_do_tce_sp("PESSOA FÍSICA - 405568") == (None, "PF", "PF:405568")
    assert tce_sp.credor_do_tce_sp("INTERNACIONAL - 77") == (None, None, "OUTRO:77")


def test_natureza_do_orgao() -> None:
    assert tce_sp.natureza_do_orgao(CAMARA) == "Câmara Municipal"
    assert tce_sp.natureza_do_orgao(PREFEITURA) == "Prefeitura Municipal"
    assert tce_sp.natureza_do_orgao("CENTRO UNIVERSITÁRIO DE ADAMANTINA") == "Administração Indireta"
    assert tce_sp.natureza_do_orgao("CONSÓRCIO INTERMUNICIPAL DE SAÚDE") is None


def test_agregar_eventos_por_orgao_e_credor() -> None:
    somas = {(s.orgao, s.credor): s for s in tce_sp.agregar_eventos(EVENTOS)}
    pj = somas[(PREFEITURA, "22669384000172")]
    assert (pj.empenhado, pj.liquidado, pj.pago) == (95_000, 90_000, 90_000)  # 1.000 - 100 + 50
    assert pj.empenhos == {"10-2025", "11-2025"}
    linha = tce_sp.linha_da_soma(pj, 10_000_000, 2025)
    assert (linha["data_empenho"], linha["mes"], linha["qtd_empenhos"]) == (date(2025, 2, 5), 2, 2)
    assert linha["numero_empenho"] is None and linha["cpf_cnpj"] == "22669384000172"
    pf = tce_sp.linha_da_soma(somas[(CAMARA, "PF:405568")], 10_000_001, 2025)
    assert (pf["cpf_cnpj"], pf["tipo_pessoa"], pf["numero_empenho"]) == (None, "PF", "10-2025")


def test_ano_fechado() -> None:
    assert tce_sp.ano_fechado(2023, date(2025, 3, 1))
    assert not tce_sp.ano_fechado(2024, date(2025, 3, 1))  # até junho o ano anterior ainda muda
    assert tce_sp.ano_fechado(2024, date(2025, 7, 1))
    assert not tce_sp.ano_fechado(2025, date(2025, 12, 31))


# --------------------------------------------------------------------------- coleta


def _cliente() -> ClienteFalso:
    def despesas(_: dict[str, Any]) -> list[dict[str, str]]:
        return EVENTOS

    return ClienteFalso({
        "/municipios": [{"municipio": "adamantina", "municipio_extenso": "Adamantina"},
                        {"municipio": "adolfo", "municipio_extenso": "Adolfo"}],
        "/despesas/adamantina/2025/1": despesas,
        "/despesas/adamantina/2025/": [],
        "/despesas/adamantina/2023/": None,  # 204: mês sem dados
    })


def _semear(db: Session) -> None:
    db.add(Municipio(codigo_ibge="3500105", nome="Adamantina", nome_normalizado="ADAMANTINA", sigla_uf="SP",
                     populacao=33_000))
    db.add(EnteSiconfi(codigo_ibge="3500105", nome="Adamantina", sigla_uf="SP", cnpj="43008291000177"))
    db.commit()


def test_coletar_tce_sp(fabrica: sessionmaker[Session], settings: Settings) -> None:
    hoje = date(2025, 3, 10)
    s = settings.model_copy(update={"tce_sp_url": "https://tce.sp/api", "tce_sp_municipios": ["Adamantina"]})
    with fabrica() as db:
        _semear(db)
        cliente, resumo = _cliente(), Resumo()
        assert tce_sp.coletar_tce_sp(cliente, db, s, [2023, 2025], resumo, progresso=False, hoje=hoje) == 4
        assert resumo.falhas == []
        meses_2025 = [u for u, _ in cliente.chamadas if "/2025/" in u]
        assert len(meses_2025) == 3  # só até o mês corrente
        orgaos = {u.natureza: u for u in db.scalars(select(UnidadeGestora))}
        assert set(orgaos) == {"Prefeitura Municipal", "Câmara Municipal"}  # consórcio fica de fora
        assert all(u.id >= tce_sp.PRIMEIRO_ID and u.fonte == "TCE-SP" for u in orgaos.values())
        assert orgaos["Câmara Municipal"].municipio_normalizado == "ADAMANTINA"
        # 2023 (fechado) ganha checkpoint; 2025 não.
        assert set(db.scalars(select(SyncMunicipioAno.ano))) == {2023}

        # Segunda execução: pula 2023, substitui 2025 sem duplicar e reaproveita os ids.
        cliente2 = _cliente()
        tce_sp.coletar_tce_sp(cliente2, db, s, [2023, 2025], Resumo(), progresso=False, hoje=hoje)
        assert not any("/2023/" in u for u, _ in cliente2.chamadas)
        assert db.scalar(select(func.count()).select_from(DespesaMunicipal)) == 4
        assert db.scalar(select(func.count()).select_from(UnidadeGestora)) == 2


@pytest.fixture()
def cliente_sp(fabrica: sessionmaker[Session], settings: Settings) -> Iterator[TestClient]:
    s = settings.model_copy(update={"tce_sp_url": "https://tce.sp/api", "tce_sp_municipios": ["todos"]})
    with fabrica() as db:
        _semear(db)
        tce_sp.coletar_tce_sp(_cliente(), db, s, [2025], Resumo(), progresso=False, hoje=date(2025, 3, 10))

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_prefeitura_e_camara_de_sp(cliente_sp: TestClient) -> None:
    pref = cliente_sp.get("/api/municipios/SP/Adamantina/prefeitura", params={"ano": 2025}).json()
    assert pref["total_pago"] == "6100.00" and pref["total_empenhado"] == "950.00"
    assert pref["qtd_empenhos"] == 4  # soma dos empenhos, não das linhas
    assert pref["por_orgao"][0]["orgao"]["fonte"] == "TCE-SP"
    # O próprio município (folha, encargos) e o repasse à câmara ficam fora do ranking de fornecedores.
    assert [f["cpf_cnpj"] for f in pref["fornecedores"]] == ["22669384000172"]
    assert pref["sem_credor_identificado"] == "5200.00"
    camara = cliente_sp.get("/api/municipios/SP/Adamantina/camara", params={"ano": 2025}).json()
    assert camara["orgao"]["natureza"] == "Câmara Municipal" and camara["total_pago"] == "300.00"
    empenhos = cliente_sp.get("/api/municipios/SP/Adamantina/empenhos", params={"busca": "real placas"}).json()
    assert empenhos["total"] == 1 and empenhos["itens"][0]["qtd_empenhos"] == 2
    docs = cliente_sp.get("/api/fornecedores/22669384000172/documentos").json()
    assert docs["itens"][0]["descricao"] == "Soma de 2 empenho(s) no ano (TCE-SP)"


# --------------------------------------------------------------------------- migração


def test_init_db_acrescenta_colunas_sem_perder_dados() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.begin() as con:
        con.execute(text("ALTER TABLE unidades_gestoras DROP COLUMN fonte"))
        con.execute(text("ALTER TABLE despesas_municipais DROP COLUMN qtd_empenhos"))
        con.execute(text(
            "INSERT INTO unidades_gestoras (id, nome, codigo_municipio_tce, municipio, municipio_normalizado, sigla_uf)"
            " VALUES (170, 'Câmara', 'P042', 'Carpina', 'CARPINA', 'PE')"
        ))
        con.execute(text(
            "INSERT INTO despesas_municipais (chave, unidade_gestora_id, ano, valor_empenhado_centavos,"
            " valor_liquidado_centavos, valor_pago_centavos) VALUES ('x', 170, 2025, 1, 1, 1)"
        ))
    init_db(engine)
    with engine.connect() as con:
        assert con.execute(text("SELECT fonte FROM unidades_gestoras")).scalar() == "TCE-PE"
        assert con.execute(text("SELECT qtd_empenhos FROM despesas_municipais")).scalar() == 1
    engine.dispose()
