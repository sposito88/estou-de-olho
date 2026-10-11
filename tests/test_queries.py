from __future__ import annotations

from sqlalchemy.orm import Session

from civic import queries
from tests.conftest import deputado, despesa


def test_ranking_relativo_compara_com_media_do_estado(db: Session) -> None:
    db.add_all([deputado(1, "Ana", uf="SP"), deputado(2, "Bia", uf="SP"), deputado(3, "Caio", uf="PE"),
                deputado(4, "Suplente", uf="SP")])
    db.flush()
    for mes in range(1, 7):
        db.add(despesa(1, 2025, mes, 10_000, num=f"a{mes}"))
        db.add(despesa(2, 2025, mes, 30_000, num=f"b{mes}"))
        db.add(despesa(3, 2025, mes, 10_000, num=f"c{mes}"))
    db.add(despesa(4, 2025, 1, 1_000, num="s1"))  # só 1 mês: fica fora da média
    db.commit()

    relativo = queries.ranking_gastos(db, ano=2025, ordem="relativo")
    assert [(r["deputado"].nome, r["indice_uf"], r["media_uf"]) for r in relativo] == [
        ("Bia", 1.5, 120_000),
        ("Caio", 1.0, 60_000),
        ("Ana", 0.5, 120_000),
        ("Suplente", 0.01, 120_000),
    ]
    total = queries.ranking_gastos(db, ano=2025)
    assert [r["deputado"].nome for r in total] == ["Bia", "Ana", "Caio", "Suplente"]
