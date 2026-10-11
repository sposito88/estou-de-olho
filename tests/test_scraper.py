from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from civic import scraper
from civic.config import Settings
from civic.models import Despesa, SyncCheckpoint
from tests.conftest import deputado

CABECALHO = scraper.COLUNAS_CSV_CAMARA


def _zip_csv(destino: Path, linhas: list[dict[str, str]]) -> Path:
    texto = ";".join(f'"{c}"' for c in CABECALHO) + "\n"
    for linha in linhas:
        texto += ";".join(f'"{linha.get(c, "")}"' for c in CABECALHO) + "\n"
    with zipfile.ZipFile(destino, "w") as zf:
        zf.writestr("Ano-2024.csv", "﻿" + texto)
    return destino


def _linha(deputado_id: int, num: str) -> dict[str, str]:
    return {
        "ideCadastro": str(deputado_id), "codLegislatura": "57", "txtDescricao": "COMBUSTÍVEIS",
        "txtFornecedor": "Posto", "txtCNPJCPF": "12.345.678/0001-95", "txtNumero": num,
        "indTipoDocumento": "0", "datEmissao": "2024-03-10T00:00:00", "vlrDocumento": "100.50",
        "vlrGlosa": "0", "vlrLiquido": "100.50", "numMes": "3", "numAno": "2024", "numParcela": "0",
        "ideDocumento": num, "urlDocumento": "",
    }


def test_bulk_marca_ausentes_e_pula_ano_completo(
    db: Session, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.add_all([deputado(1, "Ana"), deputado(2, "Suplente")])
    db.commit()
    arquivo = _zip_csv(tmp_path / "Ano-2024.csv.zip", [_linha(1, "10"), _linha(1, "11")])
    downloads: list[str] = []

    def baixar_falso(_sessao: Any, url: str, _destino: Path, **_: Any) -> Path:
        downloads.append(url)
        return arquivo

    monkeypatch.setattr(scraper, "baixar_arquivo", baixar_falso)

    resumo = scraper.Resumo()
    scraper.coletar_despesas_bulk(None, db, [2024], settings, resumo, progresso=False)  # type: ignore[arg-type]
    assert resumo.despesas_inseridas == 2
    assert db.scalar(select(func.count()).select_from(Despesa)) == 2
    # O suplente sem despesa também ganha checkpoint do ano fechado.
    assert set(db.execute(select(SyncCheckpoint.deputado_id, SyncCheckpoint.ano))) == {(1, 2024), (2, 2024)}

    # Segunda rodada: ano completo, nem baixa o arquivo.
    segundo = scraper.Resumo()
    scraper.coletar_despesas_bulk(None, db, [2024], settings, segundo, progresso=False)  # type: ignore[arg-type]
    assert len(downloads) == 1
    assert segundo.pares_pulados == 2
    assert segundo.despesas_inseridas == 0


def test_upsert_e_idempotente(db: Session) -> None:
    from civic.cleaning import despesa_do_csv

    db.add(deputado(1, "Ana"))
    db.commit()
    registros = [despesa_do_csv(_linha(1, "10")), despesa_do_csv(_linha(1, "10")), despesa_do_csv(_linha(1, "11"))]
    primeira = scraper.upsert_despesas(db, registros)
    assert (primeira.inseridas, primeira.atualizadas) == (2, 0)  # repetido dentro do lote colapsa
    segunda = scraper.upsert_despesas(db, registros)
    assert (segunda.inseridas, segunda.atualizadas) == (0, 2)


def test_remover_obsoletas_protege_coleta_vazia(db: Session) -> None:
    from civic.cleaning import despesa_do_csv

    db.add(deputado(1, "Ana"))
    db.commit()
    antigo = despesa_do_csv(_linha(1, "10"))
    scraper.upsert_despesas(db, [antigo, despesa_do_csv(_linha(1, "11"))])
    assert scraper.remover_obsoletas(db, 1, 2024, set()) == 0  # resposta vazia: não apaga nada
    assert scraper.remover_obsoletas(db, 1, 2024, {antigo["hash_unico"]}) == 1
