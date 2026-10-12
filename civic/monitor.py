"""Confere o log da última execução da rotina e avisa no Telegram se algo falhou.

Uso (no fim de deploy/rotina.sh):
    python -m civic.monitor data/logs/rotina-2026-10.log [--sempre]

Lê só o trecho desde o último "== ... início". Falha = linha que começa com "!!"
(a rotina escreve assim quando um passo termina com erro) ou um Traceback.
Com --sempre, manda também o resumo quando deu tudo certo.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from civic.avisos import enviar_admin
from civic.config import get_settings

INICIO = re.compile(r"^== (\S+) início")


def ultima_execucao(texto: str) -> tuple[str | None, list[str]]:
    """(data de início, linhas) da última execução registrada no log."""
    linhas = texto.splitlines()
    inicio, quando = 0, None
    for i, linha in enumerate(linhas):
        m = INICIO.match(linha)
        if m:
            inicio, quando = i, m.group(1)
    return quando, linhas[inicio:]


def falhas(linhas: list[str]) -> list[str]:
    return [l.strip() for l in linhas if l.startswith("!!") or l.startswith("Traceback")]


def mensagem(quando: str | None, linhas: list[str], problemas: list[str]) -> str:
    terminou = any(l.startswith("== ") and l.rstrip().endswith("fim") for l in linhas)
    if problemas:
        itens = "\n".join(f"• {html.escape(p[:200])}" for p in problemas[:15])
        return f"<b>⚠️ Rotina do Estou de Olho com {len(problemas)} falha(s)</b> ({quando})\n\n{itens}"
    estado = "terminou sem falhas" if terminou else "ainda não terminou"
    return f"<b>✅ Rotina do Estou de Olho {estado}</b> ({quando})"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.monitor", description=__doc__.splitlines()[0])
    parser.add_argument("log", type=Path)
    parser.add_argument("--sempre", action="store_true", help="avisa também quando deu tudo certo")
    args = parser.parse_args(argv)
    if not args.log.exists():
        print(f"Log não encontrado: {args.log}", file=sys.stderr)
        return 2
    quando, linhas = ultima_execucao(args.log.read_text(encoding="utf-8", errors="replace"))
    problemas = falhas(linhas)
    texto = mensagem(quando, linhas, problemas)
    print(re.sub(r"<[^>]+>", "", texto))
    if problemas or args.sempre:
        enviar_admin(texto, get_settings())
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
