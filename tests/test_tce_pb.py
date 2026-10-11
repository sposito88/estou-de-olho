from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from civic import tce_pb
from civic.api import app
from civic.config import Settings
from civic.database import get_db
from civic.models import FolhaMensal, Municipio, ServidorMunicipal, UnidadeGestora
from civic.scraper import Resumo

CABECALHO = ("nome_municipio;codigo_unidade_gestora;descricao_unidade_gestora;cpf_cnpj;nome_servidor;tipo_cargo;"
             "descricao_cargo;valor_vantagem;data_admissao;matricula;ano_mes")
LINHAS = [
    "Agua Branca;101001;Câmara Municipal de Água Branca;***.956.804-**;JOSE ALEX;Eletivos;00000001 - VEREADOR;6.000;01/01/2025;56;202601",
    "Agua Branca;101001;Câmara Municipal de Água Branca;***.956.804-**;JOSE ALEX;Eletivos;00000001 - VEREADOR;6.000;01/01/2025;56;202602",
    "Agua Branca;201001;Prefeitura Municipal de Água Branca;***.193.458-**;MARIA DA SILVA;Efetivos;00000014 - PROFESSORA;3.734,8;19/03/2008;5;202601",
    # Em fevereiro passou a cargo comissionado com outro valor: vale o mês mais recente.
    "Agua Branca;201001;Prefeitura Municipal de Água Branca;***.193.458-**;MARIA DA SILVA;Cargo Comissionado;00000020 - SECRETARIA;9.500;19/03/2008;5;202602",
    "Agua Branca;201002;Consórcio Intermunicipal de Saúde;***.111.222-**;FULANO;Efetivos;1 - MEDICO;20.000;01/01/2020;9;202602",
    "Cidade Fantasma;301001;Prefeitura Municipal de Cidade Fantasma;***.000.111-**;BELTRANO;Efetivos;1 - X;1.000;01/01/2020;1;202602",
]


def _zip(tmp_path: Path) -> Path:
    caminho = tmp_path / "servidores-2026.zip"
    with zipfile.ZipFile(caminho, "w") as zf:
        zf.writestr("servidores-2026.csv", ("﻿" + "\n".join([CABECALHO, *LINHAS]) + "\n").encode("utf-8"))
    return caminho


@pytest.fixture()
def cliente(fabrica: sessionmaker[Session], settings: Settings, tmp_path: Path) -> Iterator[TestClient]:
    with fabrica() as db:
        db.add(Municipio(codigo_ibge="2500106", nome="Água Branca", nome_normalizado="AGUA BRANCA", sigla_uf="PB"))
        db.commit()
        resumo = Resumo()
        assert tce_pb.carregar_ano(db, settings, 2026, _zip(tmp_path), resumo) == 2
        assert any("Cidade Fantasma" in f for f in resumo.falhas)  # sem par no IBGE: avisado, fora da carga

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_valor_pb() -> None:
    assert [tce_pb.valor_pb(v) for v in ("1.734,8", "6.000", "999,99", "", None)] == [173480, 600000, 99999, 0, 0]


def test_carga_e_aba_pessoal_com_salarios(cliente: TestClient, fabrica: sessionmaker[Session]) -> None:
    with fabrica() as db:
        orgaos = {u.nome: u for u in db.scalars(select(UnidadeGestora))}
        assert set(orgaos) == {"Câmara Municipal de Água Branca", "Prefeitura Municipal de Água Branca"}  # sem consórcio
        assert all(u.fonte == "TCE-PB" and u.municipio == "Água Branca" for u in orgaos.values())
        maria = db.scalars(select(ServidorMunicipal).where(ServidorMunicipal.nome == "MARIA DA SILVA")).one()
        assert (maria.cargo, maria.vinculo, maria.remuneracao_centavos, maria.remuneracao_mes) == (
            "SECRETARIA", "Cargo Comissionado", 950_000, 202602)
        assert (maria.remuneracao_ano_centavos, maria.meses_pagos, maria.cpf_meio) == (1_323_480, 2, "193458")
        assert db.scalar(select(func.count()).select_from(FolhaMensal)) == 4

    d = cliente.get("/api/municipios/PB/Água Branca/pessoal").json()
    assert d["tem_salarios"] and d["folha_fonte"] == "folha" and d["ano"] == 2026
    fevereiro = next(m for m in d["folha_por_mes"] if m["mes"] == 2)
    assert fevereiro["total"] == "9500.00"  # só a prefeitura (a câmara fica na aba Câmara)
    assert d["maiores_salarios"][0]["nome"] == "MARIA DA SILVA" and d["maiores_salarios"][0]["remuneracao"] == "9500.00"
    lista = cliente.get("/api/municipios/PB/Água Branca/pessoal/lista", params={"ordem": "salario"}).json()
    assert lista["itens"][0]["remuneracao"] == "9500.00" and lista["itens"][0]["cpf"] == "***.193.458-**"
