from __future__ import annotations

from pathlib import Path

from civic import monitor

LOG = """== 2026-10-09T03:30:01-03:00 início
tudo certo
== 2026-10-09T10:24:14-03:00 fim
== 2026-10-10T03:30:01-03:00 início
03:31 INFO coleta ok
!! contratos do PNCP terminaram com falhas (ver acima)
Traceback (most recent call last):
== 2026-10-10T13:33:03-03:00 fim
"""


def test_le_so_a_ultima_execucao_e_acha_falhas(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    quando, linhas = monitor.ultima_execucao(LOG)
    assert quando == "2026-10-10T03:30:01-03:00"
    assert monitor.falhas(linhas) == ["!! contratos do PNCP terminaram com falhas (ver acima)",
                                      "Traceback (most recent call last):"]
    enviados: list[str] = []
    monkeypatch.setattr(monitor, "enviar_telegram", lambda texto, s: enviados.append(texto) or True)
    arquivo = tmp_path / "rotina.log"
    arquivo.write_text(LOG, encoding="utf-8")
    assert monitor.main([str(arquivo)]) == 1
    assert "2 falha(s)" in enviados[0]
    arquivo.write_text(LOG.split("== 2026-10-10")[0], encoding="utf-8")
    assert monitor.main([str(arquivo)]) == 0 and len(enviados) == 1  # sem falha: só avisa com --sempre
    assert monitor.main([str(arquivo), "--sempre"]) == 0 and "sem falhas" in enviados[1]
