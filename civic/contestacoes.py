"""Contestações e direito de resposta: quem é citado (ou qualquer pessoa) pode apontar erro,
responder publicamente ou pedir algo sobre seus dados pessoais (LGPD).

Fluxo: o pedido chega com status "recebida" e avisa a equipe no Telegram (se configurado).
A equipe analisa e muda para "em_analise", "corrigida", "mantida" ou "resposta_publicada",
com um texto público. Pedidos respondidos aparecem na página /correcoes e na página contestada.
"""

from __future__ import annotations

import hashlib
import html
import logging
import secrets
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from civic.avisos import enviar_telegram
from civic.config import Settings
from civic.models import Contestacao

logger = logging.getLogger("civic.contestacoes")

TIPOS = {
    "erro": "Erro nos dados",
    "resposta": "Resposta de pessoa ou empresa citada",
    "privacidade": "Pedido sobre dados pessoais (LGPD)",
}
STATUS = ("recebida", "em_analise", "corrigida", "mantida", "resposta_publicada")
STATUS_PUBLICOS = ("corrigida", "mantida", "resposta_publicada")


class LimiteExcedido(Exception):
    """Muitos pedidos da mesma origem no mesmo dia."""


def resumo_origem(ip: str | None, dia: date | None = None) -> str | None:
    """Hash do IP com a data: permite contar pedidos do dia sem guardar o IP."""
    if not ip:
        return None
    return hashlib.sha256(f"{ip}|{(dia or date.today()).isoformat()}".encode()).hexdigest()


def novo_protocolo(agora: datetime) -> str:
    return f"{agora:%Y%m%d}-{secrets.token_hex(3).upper()}"


def registrar(db: Session, dados: dict[str, Any], ip: str | None, s: Settings) -> Contestacao:
    origem = resumo_origem(ip)
    agora = datetime.now()
    if origem:
        hoje = db.scalar(
            select(func.count()).select_from(Contestacao)
            .where(Contestacao.origem_hash == origem, Contestacao.criado_em >= agora - timedelta(days=1))
        ) or 0
        if hoje >= s.contestacoes_por_dia:
            raise LimiteExcedido
    item = Contestacao(
        protocolo=novo_protocolo(agora), criado_em=agora, tipo=dados["tipo"], url=dados["url"][:500],
        alvo=(dados.get("alvo") or None), mensagem=dados["mensagem"].strip(), nome=(dados.get("nome") or None),
        contato=(dados.get("contato") or None), status="recebida", origem_hash=origem,
    )
    db.add(item)
    db.commit()
    enviar_telegram(
        "\n".join([
            f"<b>📨 Nova contestação {item.protocolo}</b> ({html.escape(TIPOS[item.tipo])})",
            f"Página: {html.escape(s.site_url + item.url)}",
            *( [f"Sobre: {html.escape(item.alvo)}"] if item.alvo else [] ),
            "",
            html.escape(item.mensagem[:1500]),
        ]),
        s,
    )
    logger.info("Contestação %s registrada (%s)", item.protocolo, item.tipo)
    return item


def publicas(db: Session, url: str | None = None, limit: int = 50, offset: int = 0) -> tuple[int, list[Contestacao]]:
    filtro = [Contestacao.status.in_(STATUS_PUBLICOS)]
    if url:
        filtro.append(Contestacao.url == url)
    total = db.scalar(select(func.count()).select_from(Contestacao).where(*filtro)) or 0
    itens = list(db.scalars(
        select(Contestacao).where(*filtro)
        .order_by(Contestacao.respondido_em.desc().nulls_last(), Contestacao.id.desc()).limit(limit).offset(offset)
    ))
    return total, itens


def listar_admin(db: Session, status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[int, list[Contestacao]]:
    filtro = [Contestacao.status == status] if status else []
    total = db.scalar(select(func.count()).select_from(Contestacao).where(*filtro)) or 0
    itens = list(db.scalars(
        select(Contestacao).where(*filtro).order_by(Contestacao.id.desc()).limit(limit).offset(offset)
    ))
    return total, itens


def atualizar(db: Session, id_: int, status: str, resposta_publica: str | None) -> Contestacao | None:
    item = db.get(Contestacao, id_)
    if item is None:
        return None
    item.status = status
    if resposta_publica is not None:
        item.resposta_publica = resposta_publica.strip() or None
    if status in STATUS_PUBLICOS:
        item.respondido_em = datetime.now()
    db.commit()
    return item
