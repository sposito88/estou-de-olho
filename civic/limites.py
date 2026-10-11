"""Limite de requisições por IP (janela deslizante de 60 s) e cache HTTP das respostas da API.

Fica em memória, por processo: basta para conter robôs e abusos numa instância pequena.
Atrás de vários processos/servidores, troque por um limitador no proxy ou num Redis.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from civic.config import get_settings

JANELA_S = 60.0
MAX_IPS = 50_000


class Limitador:
    def __init__(self) -> None:
        self.chamadas: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def permitir(self, ip: str, grupo: str, limite: int, agora: float | None = None) -> tuple[bool, int]:
        """(permitido?, segundos até liberar)."""
        agora = time.monotonic() if agora is None else agora
        if len(self.chamadas) > MAX_IPS:
            self.chamadas.clear()  # proteção de memória: recomeça a contagem
        fila = self.chamadas[(ip, grupo)]
        while fila and agora - fila[0] > JANELA_S:
            fila.popleft()
        if len(fila) >= limite:
            return False, max(1, int(JANELA_S - (agora - fila[0])) + 1)
        fila.append(agora)
        return True, 0


limitador = Limitador()


def _grupo(caminho: str) -> str | None:
    if not caminho.startswith("/api/") or caminho.startswith("/api/admin/"):
        return None
    return "busca" if caminho.startswith("/api/busca") else "geral"


async def limitar_e_cachear(request: Request, chamar: Callable[[Request], Awaitable[Response]]) -> Response:
    s = get_settings()
    grupo = _grupo(request.url.path)
    if grupo and s.api_limite_por_minuto > 0:
        limite = s.api_limite_busca_por_minuto if grupo == "busca" else s.api_limite_por_minuto
        ip = request.client.host if request.client else "?"
        ok, espera = limitador.permitir(ip, grupo, limite)
        if not ok:
            return JSONResponse(
                {"detail": "Muitas consultas em pouco tempo. Espere um pouco e tente de novo. "
                           "Para baixar muitos dados, use os arquivos em /dados/."},
                status_code=429, headers={"Retry-After": str(espera)},
            )
    resposta = await chamar(request)
    if request.method == "GET" and resposta.status_code == 200 and "cache-control" not in resposta.headers:
        if request.url.path.startswith("/api/admin/"):
            resposta.headers["Cache-Control"] = "no-store"
        elif request.url.path.startswith(("/api/", "/health")):
            idade = 60 if request.url.path in ("/health", "/api/contestacoes") else 300
            resposta.headers["Cache-Control"] = f"public, max-age={idade}"
    return resposta
