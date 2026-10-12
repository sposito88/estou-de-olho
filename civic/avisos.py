"""Avisos no Telegram quando chegam pagamentos de emenda nos municípios monitorados."""

from __future__ import annotations

import html
import logging
from collections import defaultdict
from collections.abc import Sequence
from urllib.parse import quote

import requests

from civic.alertas import formatar_brl
from civic.config import Settings
from civic.models import EmendaPagamento

logger = logging.getLogger("civic.avisos")

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
LIMITE_ITENS = 8


def montar_mensagens(novos: Sequence[EmendaPagamento], site_url: str) -> list[str]:
    """Uma mensagem (HTML do Telegram) por município, com total e os maiores pagamentos."""
    por_municipio: dict[tuple[str, str], list[EmendaPagamento]] = defaultdict(list)
    for p in novos:
        por_municipio[(p.sigla_uf or "", p.municipio or "")].append(p)

    mensagens = []
    for (uf, municipio), pagamentos in sorted(por_municipio.items()):
        pagamentos.sort(key=lambda p: -p.valor_recebido_centavos)
        total = sum(p.valor_recebido_centavos for p in pagamentos)
        nome = html.escape(municipio.title())
        linhas = [
            f"<b>💰 Chegou dinheiro de emenda em {nome} – {uf}</b>",
            f"{len(pagamentos)} pagamento(s) novo(s), total de <b>{formatar_brl(total)}</b>:",
            "",
        ]
        for p in pagamentos[:LIMITE_ITENS]:
            autor = html.escape((p.nome_autor or "Autor não informado").title())
            favorecido = html.escape((p.favorecido or "favorecido não informado").title())
            linhas.append(
                f"• {formatar_brl(p.valor_recebido_centavos)} – {autor} → {favorecido} ({MESES[p.mes - 1]}/{p.ano})"
            )
        if len(pagamentos) > LIMITE_ITENS:
            linhas.append(f"• … e mais {len(pagamentos) - LIMITE_ITENS}")
        link = f"{site_url}/cidade/{uf}/{quote(municipio)}"
        linhas += ["", f'<a href="{html.escape(link)}">Ver tudo no Estou de Olho</a>']
        mensagens.append("\n".join(linhas))
    return mensagens


def enviar_telegram(
    texto: str, settings: Settings, sessao: requests.Session | None = None, chat_id: str | None = None
) -> bool:
    """Envia uma mensagem (HTML do Telegram) ao canal público (ou a `chat_id`). Sem bot configurado, não faz nada.

    Falhas são registradas no log sem expor o token (que vai na URL).
    """
    destino = chat_id or settings.telegram_chat_id
    if settings.telegram_bot_token is None or not destino:
        return False
    sessao = sessao or requests.Session()
    url = f"{settings.telegram_api_url}/bot{settings.telegram_bot_token.get_secret_value()}/sendMessage"
    try:
        resposta = sessao.post(
            url,
            json={"chat_id": destino, "text": texto, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=settings.timeout,
        )
        resposta.raise_for_status()
        return True
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.error("Falha ao enviar aviso ao Telegram (%s, status %s)", type(exc).__name__, status)
        return False


def enviar_admin(texto: str, settings: Settings, sessao: requests.Session | None = None) -> bool:
    """Aviso interno (falha da rotina, contestação nova): só para a conversa privada da equipe, nunca o canal."""
    if not settings.telegram_admin_chat_id:
        logger.info("Aviso interno não enviado: TELEGRAM_ADMIN_CHAT_ID não configurado")
        return False
    return enviar_telegram(texto, settings, sessao, chat_id=settings.telegram_admin_chat_id)


def notificar_telegram(
    novos: Sequence[EmendaPagamento], settings: Settings, sessao: requests.Session | None = None
) -> int:
    """Envia os avisos de emenda se o bot estiver configurado. Retorna quantas mensagens foram enviadas."""
    if not novos:
        return 0
    if settings.telegram_bot_token is None or not settings.telegram_chat_id:
        logger.info("%d pagamentos novos, mas o Telegram não está configurado", len(novos))
        return 0
    sessao = sessao or requests.Session()
    return sum(enviar_telegram(texto, settings, sessao) for texto in montar_mensagens(novos, settings.site_url))
