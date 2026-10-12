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
    return "\n".join([
        "<b>👁 Estou de Olho</b>",
        "",
        "Auditoria cidadã do dinheiro público, com dados oficiais abertos: cota de deputados e senadores, "
        "emendas e Emenda Pix, prefeituras, câmaras, contratos e pessoal.",
        "",
        "Aqui no canal você recebe:",
        "• os sinais de alerta mais fortes que aparecerem nos dados;",
        "• avisos quando chega dinheiro de emenda nas cidades acompanhadas.",
        "",
        f"Busque qualquer empresa ou pessoa pública: {html.escape(s.site_url)}/busca",
        f"Veja sua cidade: {html.escape(s.site_url)}/cidade",
        "",
        "<i>Alerta não é acusação. Viu um erro? Use “Contestar ou corrigir” no site.</i>",
    ])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.canal", description=__doc__.splitlines()[0])
    parser.add_argument("--apresentacao", action="store_true", help="publica a mensagem de apresentação")
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
        return 0 if enviar_telegram(texto, s) else 1
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
