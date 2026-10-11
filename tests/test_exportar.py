from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from civic import demo, exportar
from civic.models import Despesa


def test_mascarar() -> None:
    assert exportar.mascarar("12345678909") == "***.456.789-**"
    assert exportar.mascarar("12345678000199") == "12345678000199"  # CNPJ fica
    assert exportar.mascarar(1234) == 1234


def test_exporta_conjuntos_com_cpf_mascarado(fabrica: sessionmaker[Session], tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    with fabrica() as db:
        demo.popular(db)
        db.add(Despesa(hash_unico="pf", deputado_id=900001, ano=2025, mes=1, tipo_despesa="TÁXI", fornecedor="FULANO",
                       cnpj_cpf="12345678909", valor_documento_centavos=1, valor_glosa_centavos=0,
                       valor_liquido_centavos=1))
        db.commit()
        monkeypatch.setattr(exportar, "engine", db.get_bind())
    itens = {i["arquivo"]: i for i in exportar.exportar(tmp_path)}
    assert set(itens) == {f"{n}.csv.gz" for n in exportar.CONJUNTOS}
    with gzip.open(tmp_path / "cota_deputados_federais.csv.gz", "rt", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    assert len(linhas) == itens["cota_deputados_federais.csv.gz"]["linhas"] == 41
    assert "12345678909" not in {l["cnpj_cpf"] for l in linhas}
    assert "***.456.789-**" in {l["cnpj_cpf"] for l in linhas}
    indice = json.loads((tmp_path / "indice.json").read_text(encoding="utf-8"))
    assert indice["licenca_codigo"] == "AGPL-3.0" and len(indice["conjuntos"]) == len(exportar.CONJUNTOS)
    assert not list(tmp_path.glob(".*.tmp"))  # nada pela metade
