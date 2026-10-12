"""Resumo dos alertas novos no canal público do Telegram.

Uso (a rotina chama depois de recalcular os alertas):
    python -m civic.canal                 # publica os alertas fortes surgidos desde o último resumo
    python -m civic.canal --apresentacao  # publica a mensagem de apresentação do canal
    python -m civic.canal --simular       # mostra o texto sem publicar

Só entram alertas com prioridade >= CANAL_MIN_PRIORIDADE. Alertas que citam pessoa física
pelo nome (servidor, eleito ou doador sócio de fornecedor) não vão para o canal, só a contagem
com link para o site: num canal público, um homônimo ou um erro se espalha rápido demais.
Na primeira execução, só marca o ponto de partida (todos os alertas já existentes seriam "novos").
"""

from __future__ import annotations

import argparse
import html
import logging
import sys
from collections.abc import Sequence
from datetime import datetime

import requests

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from civic.alertas import TITULOS_TIPO, formatar_brl
from civic.avisos import enviar_telegram
from civic.config import Settings, get_settings
from civic.database import SessionLocal, init_db
from civic.models import Alerta, Municipio, SyncExecucao
from civic.scraper import registrar_execucao

logger = logging.getLogger("civic.canal")

FONTE = "canal_alertas"
TIPOS_PESSOA_FISICA = {"servidor_socio", "eleito_socio", "doador_socio"}
MAXIMO_ITENS = 8


def ultimo_resumo(db: Session) -> datetime | None:
    return db.scalar(select(func.max(SyncExecucao.concluido_em)).where(SyncExecucao.fonte == FONTE))


def montar_resumo(db: Session, s: Settings, desde: datetime) -> str | None:
    novos = list(db.scalars(
        select(Alerta).where(Alerta.primeira_vez > desde, Alerta.prioridade >= s.canal_min_prioridade)
        .order_by(Alerta.prioridade.desc(), Alerta.valor_centavos.desc())
    ))
    if not novos:
        return None
    publicaveis = [a for a in novos if a.tipo not in TIPOS_PESSOA_FISICA]
    pessoas = len(novos) - len(publicaveis)
    cidades = {m.codigo_ibge: m for m in db.scalars(
        select(Municipio).where(Municipio.codigo_ibge.in_({a.municipio_ibge for a in publicaveis if a.municipio_ibge}))
    )}
    linhas = [f"<b>🔎 {len(novos)} novo(s) sinal(is) de alerta forte(s)</b>", ""]
    for a in publicaveis[:MAXIMO_ITENS]:
        link = f"{s.site_url}/fornecedores/{a.cnpj}" if a.cnpj else f"{s.site_url}/alertas?forca={s.canal_min_prioridade}"
        cidade = cidades.get(a.municipio_ibge or "")
        onde = f" · {cidade.nome}-{cidade.sigla_uf}" if cidade else ""
        valor = f" · {formatar_brl(a.valor_centavos)}" if a.valor_centavos else ""
        linhas.append(
            f"• <b>{html.escape(TITULOS_TIPO.get(a.tipo, a.tipo))}</b>{html.escape(onde)}{valor}\n"
            f"  {html.escape(a.titulo[:220])}\n  <a href=\"{html.escape(link)}\">ver</a>"
        )
    restantes = len(publicaveis) - min(len(publicaveis), MAXIMO_ITENS)
    if restantes > 0 or pessoas:
        extra = []
        if restantes > 0:
            extra.append(f"mais {restantes}")
        if pessoas:
            extra.append(f"{pessoas} que envolvem pessoas físicas (só no site)")
        linhas += ["", f"E {' e '.join(extra)}: {html.escape(s.site_url)}/alertas?forca={s.canal_min_prioridade}&amp;ordem=recentes"]
    linhas += ["", "<i>Alerta não é acusação: é um padrão nos dados oficiais que vale verificar. "
               "Em cada alerta há o botão “Pedir explicação”.</i>"]
    return "\n".join(linhas)


def apresentacao(s: Settings) -> str:
    site = html.escape(s.site_url)
    return "\n".join([
        "<b>👁 Bem-vindo ao Estou de Olho</b>",
        "",
        "Um projeto cidadão, aberto e sem fins lucrativos, que junta os dados oficiais sobre o dinheiro público "
        "e mostra, em linguagem simples, <b>quem recebeu, quanto e por quê</b>.",
        "",
        "<b>O que acompanhamos</b>",
        "• Cota de deputados federais e senadores, nota por nota",
        "• Emendas parlamentares e Emenda Pix que chegam a cada cidade",
        "• Gastos de prefeituras e câmaras (PE, SP, RS e PB), contratos de todo o país e as contas dos 5.570 municípios",
        "• Pessoal das prefeituras e, na Paraíba, o salário de cada servidor",
        "",
        "<b>O que chega aqui no canal</b>",
        "🔎 Os sinais de alerta mais fortes, quando aparecem nos dados: empresa aberta pouco antes de receber, "
        "contrato muito acima do capital da empresa, Emenda Pix parada ou gasta fora da regra, entre outros",
        "💰 Aviso quando chega dinheiro de emenda nas cidades acompanhadas",
        "No máximo um resumo por dia, só quando há novidade.",
        "",
        "<b>Use o site</b>",
        f"• Busque qualquer empresa ou pessoa pública: {site}/busca",
        f"• Veja a sua cidade: {site}/cidade",
        f"• Quem está em dia com a prestação de contas: {site}/transparencia",
        "",
        "<b>Combinados</b>",
        "• Alerta não é acusação: é um padrão nos dados oficiais que vale verificar. Em cada um há o botão "
        "“Pedir explicação”, com o pedido pronto pela Lei de Acesso à Informação.",
        f"• Viu um erro, ou foi citado e quer responder? Use “Contestar ou corrigir”: {site}/contestar",
        "• Não publicamos aqui nomes de pessoas físicas em alertas; esses ficam só no site, com aviso de possível homônimo.",
        "• O código e os dados são abertos: https://github.com/sposito88/estou-de-olho",
        "",
        "Compartilhe com quem quer saber para onde vai o dinheiro da sua cidade. 👁",
    ])


def publicar_apresentacao(s: Settings, fixar: bool) -> bool:
    """Publica a apresentação no canal e, se pedido, fixa no topo."""
    if s.telegram_bot_token is None or not s.telegram_chat_id:
        logger.warning("Telegram não configurado")
        return False
    base = f"{s.telegram_api_url}/bot{s.telegram_bot_token.get_secret_value()}"
    try:
        resposta = requests.post(f"{base}/sendMessage", timeout=s.timeout, json={
            "chat_id": s.telegram_chat_id, "text": apresentacao(s), "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        resposta.raise_for_status()
        mensagem = resposta.json()["result"]["message_id"]
        logger.info("Apresentação publicada (mensagem %s)", mensagem)
        if fixar:
            fixada = requests.post(f"{base}/pinChatMessage", timeout=s.timeout, json={
                "chat_id": s.telegram_chat_id, "message_id": mensagem, "disable_notification": True,
            })
            fixada.raise_for_status()
            logger.info("Apresentação fixada no topo do canal")
        return True
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.error("Falha ao publicar a apresentação (%s, status %s)", type(exc).__name__, status)
        return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.canal", description=__doc__.splitlines()[0])
    parser.add_argument("--apresentacao", action="store_true", help="publica a mensagem de apresentação")
    parser.add_argument("--fixar", action="store_true", help="com --apresentacao: fixa a mensagem no topo do canal")
    parser.add_argument("--simular", action="store_true", help="mostra o texto sem publicar")
    args = parser.parse_args(argv)
    s = get_settings()
    logging.basicConfig(level=s.log_level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stderr)
    init_db()
    if args.apresentacao:
        texto = apresentacao(s)
        if args.simular:
            print(texto)
            return 0
        return 0 if publicar_apresentacao(s, args.fixar) else 1
    with SessionLocal() as db:
        desde = ultimo_resumo(db)
        if desde is None:
            registrar_execucao(db, FONTE, 0, detalhes="ponto de partida (nada publicado)")
            logger.info("Primeira execução: ponto de partida marcado, nada publicado")
            return 0
        texto = montar_resumo(db, s, desde)
        if texto is None:
            logger.info("Nenhum alerta forte novo desde %s", desde)
            return 0
        if args.simular:
            print(texto)
            return 0
        if enviar_telegram(texto, s):
            registrar_execucao(db, FONTE, texto.count("\n• ") + 1, detalhes=f"desde {desde:%Y-%m-%d %H:%M}")
            logger.info("Resumo publicado no canal")
            return 0
        logger.warning("Resumo não publicado (Telegram não configurado ou falha no envio)")
        return 1 if s.telegram_bot_token else 0


if __name__ == "__main__":
    sys.exit(main())
