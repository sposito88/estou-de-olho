from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from civic.api import app
from civic.config import get_settings
from civic.limites import Limitador, limitador


def test_janela_deslizante() -> None:
    lim = Limitador()
    assert [lim.permitir("1.1.1.1", "geral", 2, agora=t)[0] for t in (0, 1, 2)] == [True, True, False]
    assert lim.permitir("2.2.2.2", "geral", 2, agora=2)[0]  # outro IP não é afetado
    assert lim.permitir("1.1.1.1", "geral", 2, agora=61)[0]  # a janela andou


def test_api_responde_429_e_cacheia(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "api_limite_por_minuto", 3)
    limitador.chamadas.clear()
    cliente = TestClient(app)
    respostas = [cliente.get("/api/alertas/tipos") for _ in range(4)]
    assert [r.status_code for r in respostas] == [200, 200, 200, 429]
    assert respostas[0].headers["cache-control"] == "public, max-age=300"
    assert int(respostas[3].headers["retry-after"]) >= 1
    limitador.chamadas.clear()
