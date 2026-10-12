from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ARQUIVO = Path(__file__).resolve().parent.parent / "deploy" / "bot_admin.py"
spec = importlib.util.spec_from_file_location("bot_admin", ARQUIVO)
bot_admin = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(bot_admin)


class BotFalso(bot_admin.Bot):
    def __init__(self) -> None:
        super().__init__("1:x", "42")
        self.respostas: list[str] = []
        self.executados: list[tuple[str, list[str]]] = []

    def responder(self, texto: str) -> None:
        self.respostas.append(texto)

    def executar(self, nome: str, comando: list[str]) -> None:
        self.executados.append((nome, comando))


def _msg(texto: str, chat: int = 42, tipo: str = "private") -> dict:
    return {"chat": {"id": chat, "type": tipo}, "text": texto}


def test_interpretar() -> None:
    assert bot_admin.interpretar("/atualizar PNCP") == ("atualizar", "pncp")
    assert bot_admin.interpretar("/status@xyzestoudeolho_bot") == ("status", None)
    assert bot_admin.interpretar("oi") == ("", None)


def test_so_a_conversa_da_equipe_manda() -> None:
    bot = BotFalso()
    bot.tratar(_msg("/rotina", chat=999))  # outra pessoa
    bot.tratar(_msg("/rotina", chat=42, tipo="channel"))  # o canal
    assert bot.executados == [] and bot.respostas == []


def test_comandos_da_lista_fixa() -> None:
    bot = BotFalso()
    bot.tratar(_msg("/atualizar pncp"))
    assert bot.executados == [("atualizar pncp", bot_admin.FONTES["pncp"][1])]
    bot.tratar(_msg("/atualizar ; rm -rf /"))  # nada fora da lista vira comando
    bot.tratar(_msg("/atualizar inexistente"))
    assert len(bot.executados) == 1 and "Diga qual fonte" in bot.respostas[-1]
    bot.tratar(_msg("/rotina"))
    assert bot.executados[-1] == ("rotina completa", ["bash", "deploy/rotina.sh"])
    bot.tratar(_msg("/ajuda"))
    assert "/atualizar" in bot.respostas[-1]


@pytest.mark.parametrize("nome", list(bot_admin.FONTES))
def test_comandos_fixos_nao_usam_shell(nome: str) -> None:
    descricao, comando = bot_admin.FONTES[nome]
    assert descricao and comando[:2] == ["docker", "compose"] and all(";" not in parte for parte in comando)
