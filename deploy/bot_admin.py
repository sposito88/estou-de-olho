#!/usr/bin/env python3
"""Comandos de administração pelo Telegram (só na conversa privada da equipe com o bot).

Roda no servidor (fora do Docker), só com a biblioteca padrão do Python. O cron chama a
cada 5 minutos com `flock -n`, então fica sempre uma instância só e ela volta sozinha se cair:

    */5 * * * * cd ~/estoudeolho && flock -n /tmp/estoudeolho-bot.lock python3 deploy/bot_admin.py >> data/logs/bot.log 2>&1

Segurança:
- só aceita mensagens da conversa TELEGRAM_ADMIN_CHAT_ID (o Telegram garante quem enviou);
- só executa comandos de uma lista fixa; nenhum texto digitado vira comando no servidor;
- uma tarefa por vez, e nunca junto com a rotina diária (mesmo trava da rotina).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TRAVA_ROTINA = "/tmp/estoudeolho-rotina.lock"
COMPOSE = ["docker", "compose", "run", "--rm", "-e", "ALERTAS_AO_FINAL=false"]
PYTHON = ["docker", "compose", "run", "--rm", "--no-deps", "--entrypoint", "python", "coleta", "-m"]

# nome -> (descrição, comando). Nada aqui recebe texto do usuário.
FONTES: dict[str, tuple[str, list[str]]] = {
    "camara": ("cota dos deputados e emendas", COMPOSE + ["coleta"]),
    "pernambuco": ("ALEPE e TCE-PE", COMPOSE + ["pernambuco"]),
    "senado": ("cota dos senadores", COMPOSE + ["senado"]),
    "pncp": ("contratos do PNCP", COMPOSE + ["pncp"]),
    "siconfi": ("balanços anuais (DCA)", COMPOSE + ["siconfi"]),
    "rreo": ("relatório bimestral (RREO)", COMPOSE + ["siconfi", "python", "-m", "civic.siconfi", "--rreo",
                                                      "--sem-progresso"]),
    "transferegov": ("Emendas Pix", COMPOSE + ["transferegov"]),
    "tce_sp": ("TCE-SP", COMPOSE + ["tce_sp"]),
    "tce_rs": ("TCE-RS", COMPOSE + ["tce_rs"]),
    "tce_pb": ("TCE-PB (pessoal e salários)", COMPOSE + ["tce_pb"]),
    "tse": ("TSE (candidatos e doações)", COMPOSE + ["tse"]),
    "cnpj": ("base de CNPJ da Receita", COMPOSE + ["cnpj"]),
    "alertas": ("recalcular os alertas", PYTHON + ["civic.alertas"]),
    "busca": ("refazer o índice da busca", PYTHON + ["civic.busca"]),
    "canal": ("publicar o resumo de alertas no canal", PYTHON + ["civic.canal"]),
    "exportar": ("gerar os arquivos de dados abertos", PYTHON + ["civic.exportar"]),
}

AJUDA = "\n".join([
    "<b>Comandos do Estou de Olho</b>",
    "/status – última coleta de cada fonte, o que está rodando e disco",
    "/rotina – roda a rotina completa agora (coletas, alertas, busca, canal, backup)",
    "/atualizar &lt;fonte&gt; – atualiza uma fonte só. Fontes:",
    *[f"  • <code>{nome}</code> – {descricao}" for nome, (descricao, _) in FONTES.items()],
    "/log – últimas linhas do log da rotina",
    "/ajuda – esta lista",
])


def ler_env() -> dict[str, str]:
    valores: dict[str, str] = {}
    for linha in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in linha and not linha.lstrip().startswith("#"):
            chave, valor = linha.split("=", 1)
            valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def interpretar(texto: str) -> tuple[str, str | None]:
    """'/atualizar pncp' -> ('atualizar', 'pncp'). Aceita '/cmd@nome_do_bot'."""
    partes = (texto or "").strip().split()
    if not partes or not partes[0].startswith("/"):
        return "", None
    comando = partes[0][1:].split("@", 1)[0].lower()
    argumento = partes[1].lower() if len(partes) > 1 else None
    return comando, argumento


class Bot:
    def __init__(self, token: str, admin: str) -> None:
        self.base = f"https://api.telegram.org/bot{token}"
        self.admin = str(admin)
        self.tarefa: threading.Thread | None = None
        self.nome_tarefa = ""

    def chamar(self, metodo: str, dados: dict | None = None, timeout: float = 70) -> dict:
        requisicao = urllib.request.Request(
            f"{self.base}/{metodo}", data=json.dumps(dados or {}).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            return json.load(resposta)

    def responder(self, texto: str) -> None:
        try:
            self.chamar("sendMessage", {"chat_id": self.admin, "text": texto[:4000], "parse_mode": "HTML",
                                        "disable_web_page_preview": True})
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"{datetime.now():%H:%M:%S} falha ao responder: {type(exc).__name__}", flush=True)

    # ------------------------------------------------------------------ tarefas

    def ocupado(self) -> str | None:
        if self.tarefa and self.tarefa.is_alive():
            return f"Já estou rodando <b>{self.nome_tarefa}</b>. Espere terminar."
        with open(TRAVA_ROTINA, "a") as trava:
            try:
                import fcntl

                fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(trava, fcntl.LOCK_UN)
            except OSError:
                return "A rotina diária está rodando agora. Espere terminar (use /status)."
        return None

    def executar(self, nome: str, comando: list[str]) -> None:
        motivo = self.ocupado()
        if motivo:
            self.responder(motivo)
            return
        self.nome_tarefa = nome

        def trabalho() -> None:
            inicio = time.monotonic()
            log = RAIZ / "data" / "logs" / f"bot-{datetime.now():%Y-%m}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            import fcntl

            with open(log, "a", encoding="utf-8") as saida, open(TRAVA_ROTINA, "a") as trava:
                if comando[:2] != ["bash", "deploy/rotina.sh"]:
                    fcntl.flock(trava, fcntl.LOCK_EX)  # a rotina das 3h30 espera esta tarefa terminar
                saida.write(f"== {datetime.now().isoformat(timespec='seconds')} {nome}\n")
                saida.flush()
                processo = subprocess.run(comando, cwd=RAIZ, stdout=saida, stderr=subprocess.STDOUT)
            minutos = (time.monotonic() - inicio) / 60
            final = log.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]
            resumo = "\n".join(l[:180] for l in final if "Container" not in l)
            estado = "✅ terminou" if processo.returncode == 0 else f"⚠️ terminou com falhas (código {processo.returncode})"
            self.responder(f"<b>{nome}</b> {estado} em {minutos:.1f} min\n<pre>{escapar(resumo)}</pre>")

        self.tarefa = threading.Thread(target=trabalho, daemon=True)
        self.tarefa.start()
        self.responder(f"⏳ Comecei: <b>{nome}</b>. Aviso quando terminar.")

    # ------------------------------------------------------------------ comandos

    def status(self) -> str:
        linhas = ["<b>Status</b>"]
        try:
            with urllib.request.urlopen("http://localhost:8088/health", timeout=20) as r:
                saude = json.load(r)
            for fonte, quando in sorted(saude.get("fontes", {}).items(), key=lambda x: x[1], reverse=True):
                linhas.append(f"• {fonte}: {quando[:16].replace('T', ' ')}")
        except (urllib.error.URLError, TimeoutError, ValueError):
            linhas.append("⚠️ o site não respondeu em /health")
        rodando = subprocess.run(["docker", "ps", "--format", "{{.Names}} ({{.RunningFor}})"], capture_output=True,
                                 text=True).stdout.split("\n")
        coletas = [r for r in rodando if r.startswith("estoudeolho-") and "-run-" in r]
        linhas.append("")
        linhas.append("<b>Rodando agora:</b> " + (", ".join(c.replace("estoudeolho-", "") for c in coletas) or "nada"))
        if self.tarefa and self.tarefa.is_alive():
            linhas.append(f"Tarefa pedida aqui: {self.nome_tarefa}")
        disco = shutil.disk_usage(RAIZ)
        banco = RAIZ / "data" / "gastos.db"
        linhas.append(f"Disco livre: {disco.free / 1e9:.0f} GB · banco: {banco.stat().st_size / 1e9:.1f} GB"
                      if banco.exists() else f"Disco livre: {disco.free / 1e9:.0f} GB")
        return "\n".join(linhas)

    def log(self) -> str:
        arquivo = RAIZ / "data" / "logs" / f"rotina-{datetime.now():%Y-%m}.log"
        if not arquivo.exists():
            return "Ainda não há log da rotina neste mês."
        linhas = [l for l in arquivo.read_text(encoding="utf-8", errors="replace").splitlines() if "Container" not in l]
        return "<pre>" + escapar("\n".join(l[:160] for l in linhas[-20:])) + "</pre>"

    def tratar(self, mensagem: dict) -> None:
        conversa = mensagem.get("chat", {})
        if str(conversa.get("id")) != self.admin or conversa.get("type") != "private":
            return  # outras conversas e o canal: ignorados em silêncio
        comando, argumento = interpretar(mensagem.get("text", ""))
        if comando in ("start", "ajuda", "help"):
            self.responder(AJUDA)
        elif comando == "status":
            self.responder(self.status())
        elif comando == "log":
            self.responder(self.log())
        elif comando == "rotina":
            self.executar("rotina completa", ["bash", "deploy/rotina.sh"])
        elif comando == "atualizar":
            if argumento not in FONTES:
                self.responder("Diga qual fonte, por exemplo <code>/atualizar pncp</code>.\n\n" + AJUDA)
            else:
                self.executar(f"atualizar {argumento}", FONTES[argumento][1])
        elif comando:
            self.responder("Não conheço esse comando.\n\n" + AJUDA)

    def rodar(self) -> None:
        print(f"{datetime.now():%Y-%m-%d %H:%M:%S} bot de administração ligado", flush=True)
        deslocamento = 0
        while True:
            try:
                resposta = self.chamar("getUpdates", {"offset": deslocamento, "timeout": 50,
                                                      "allowed_updates": ["message"]})
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                print(f"{datetime.now():%H:%M:%S} getUpdates falhou: {type(exc).__name__}", flush=True)
                time.sleep(15)
                continue
            for atualizacao in resposta.get("result", []):
                deslocamento = atualizacao["update_id"] + 1
                if "message" in atualizacao:
                    try:
                        self.tratar(atualizacao["message"])
                    except Exception as exc:  # noqa: BLE001 - o bot não pode cair por um comando
                        print(f"{datetime.now():%H:%M:%S} erro ao tratar comando: {exc!r}", flush=True)
                        self.responder("Deu erro ao tratar esse comando; veja data/logs/bot.log no servidor.")


def escapar(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> int:
    env = {**ler_env(), **{k: v for k, v in os.environ.items() if k.startswith("TELEGRAM_")}}
    token, admin = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_ADMIN_CHAT_ID")
    if not token or not admin:
        print("TELEGRAM_BOT_TOKEN e TELEGRAM_ADMIN_CHAT_ID precisam estar no .env", file=sys.stderr)
        return 2
    Bot(token, admin).rodar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
