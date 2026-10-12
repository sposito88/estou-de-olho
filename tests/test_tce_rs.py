from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from civic import tce_rs
from civic.config import Settings
from civic.models import DespesaMunicipal, Municipio, UnidadeGestora
from civic.scraper import Resumo

CAMPOS = ["ano_recebimento", "mes_recebimento", "cd_orgao", "nome_orgao", "tp_unidade", "tipo_operacao", "ano_empenho",
          "dt_empenho", "nr_empenho", "ds_funcao", "cd_elemento", "ds_rubrica", "nm_recurso", "cd_credor", "nm_credor",
          "tp_pessoa", "cnpj_cpf", "historico", "vl_empenho", "vl_liquidacao", "vl_pagamento"]


def _linha(**kw: str) -> dict[str, str]:
    base = {"ano_recebimento": "2025", "mes_recebimento": "12", "cd_orgao": "40100", "nome_orgao": "PM DE AGUDO",
            "tp_unidade": "PRM", "ano_empenho": "2025", "dt_empenho": "2025-03-05", "ds_funcao": "Urbanismo",
            "cd_elemento": "3.3.90.39", "ds_rubrica": "LIMPEZA E CONSERVACAO", "nm_recurso": "Recurso Livre",
            "cd_credor": "6333", "nm_credor": "SM SOARES & CIA LTDA", "tp_pessoa": "PJ", "cnpj_cpf": "11804625000122",
            "historico": "COLETA DE LIXO", "vl_empenho": "", "vl_liquidacao": "", "vl_pagamento": ""}
    return {**base, **kw}


LINHAS = [
    _linha(tipo_operacao="E", nr_empenho="1", vl_empenho="480000.00"),
    _linha(tipo_operacao="E", nr_empenho="2", vl_empenho="20000.00", dt_empenho="2025-01-10"),
    _linha(tipo_operacao="L", nr_empenho="1", vl_liquidacao="50178.09"),
    _linha(tipo_operacao="P", nr_empenho="1", vl_pagamento="2759.79"),
    # Pessoa física: CPF completo (sem zeros à esquerda) no arquivo.
    _linha(cd_orgao="40101", nome_orgao="CM DE AGUDO", tipo_operacao="P", nr_empenho="7", tp_pessoa="PF",
           cnpj_cpf="4237081800", nm_credor="FULANO DE TAL", vl_pagamento="1000.00"),
    _linha(cd_orgao="88227", nome_orgao="CONSORCIO INTERMUNICIPAL X", tipo_operacao="E", nr_empenho="9", vl_empenho="5.00"),
]


def _zip(tmp_path: Path) -> Path:
    texto = io.StringIO()
    escritor = csv.DictWriter(texto, fieldnames=CAMPOS)
    escritor.writeheader()
    escritor.writerows(LINHAS)
    caminho = tmp_path / "2025.csv.zip"
    with zipfile.ZipFile(caminho, "w") as zf:
        zf.writestr("2025.csv", ("﻿" + texto.getvalue()).encode("utf-8"))
    return caminho


def test_carga_rs(fabrica: sessionmaker[Session], settings: Settings, tmp_path: Path) -> None:
    with fabrica() as db:
        db.add(Municipio(codigo_ibge="4300109", nome="Agudo", nome_normalizado="AGUDO", sigla_uf="RS"))
        db.commit()
        n = tce_rs.carregar_ano(db, settings, 2025, _zip(tmp_path), {1: "4300109"}, Resumo())
        assert n == 2
        orgaos = {u.natureza: u for u in db.scalars(select(UnidadeGestora))}
        assert set(orgaos) == {"Prefeitura Municipal", "Câmara Municipal"}  # consórcio fora
        assert orgaos["Prefeitura Municipal"].nome == "Prefeitura Municipal de Agudo"
        assert orgaos["Prefeitura Municipal"].municipio == "Agudo" and orgaos["Prefeitura Municipal"].fonte == "TCE-RS"
        linhas = {d.tipo_pessoa: d for d in db.scalars(select(DespesaMunicipal))}
    pj = linhas["PJ"]
    assert (pj.valor_empenhado_centavos, pj.valor_liquidado_centavos, pj.valor_pago_centavos) == (50_000_000, 5_017_809, 275_979)
    assert pj.qtd_empenhos == 2 and pj.data_empenho.isoformat() == "2025-01-10" and pj.historico == "COLETA DE LIXO"
    assert pj.categoria_economica == "Despesa Corrente" and pj.fonte_recurso == "Recurso Livre"
    pf = linhas["PF"]
    assert pf.cpf_cnpj == "***.370.818-**" and pf.valor_pago_centavos == 100_000  # 042.370.818-00
    assert "4237081800" not in str({c.name: getattr(pf, c.name) for c in DespesaMunicipal.__table__.columns})


def test_ibge_do_orgao_pelo_nome() -> None:
    from civic.tse import MapaMunicipios

    mapa = MapaMunicipios([("4300109", "RS", "AGUDO")])
    assert tce_rs.ibge_do_orgao("40100", "PM DE AGUDO", {1: "4300109"}, mapa) == "4300109"
    assert tce_rs.ibge_do_orgao("91234", "INSTITUTO DE PREVIDENCIA DE AGUDO", {}, mapa) == "4300109"
    assert tce_rs.ibge_do_orgao("91235", "FUNDACAO QUALQUER", {}, mapa) is None
