"""Consultas agregadas reutilizáveis.

Regra de negócio: todo gasto da cota exibido ou somado usa `valor_liquido`
(o que foi de fato reembolsado), nunca `valor_documento`.

As funções devolvem dicionários/ORM com valores em centavos; a conversão para
reais acontece nos schemas.
"""

from __future__ import annotations

import fnmatch
import re
import statistics
import time
from datetime import date, datetime
from collections.abc import Callable
from typing import Any

from sqlalchemy import Integer, Select, and_, case, distinct, func, or_, select, union_all
from sqlalchemy import String, cast, literal
from sqlalchemy.orm import Session, contains_eager

from civic.cleaning import normalizar_nome
from civic.config import get_settings
from civic.models import (
    Alerta,
    Candidato,
    ContaMunicipal,
    ContratoMunicipal,
    ContratoPncp,
    Deputado,
    DeputadoEstadual,
    Despesa,
    DespesaMunicipal,
    DoacaoCampanha,
    Emenda,
    EmendaConvenio,
    EmendaPagamento,
    EnteSiconfi,
    FolhaMensal,
    Fornecedor,
    Municipio,
    PagamentoMunicipal,
    PlanoPix,
    RepassePix,
    Senador,
    DespesaSenado,
    ServidorMunicipal,
    SyncPncpDia,
    SyncExecucao,
    UnidadeGestora,
    VerbaIndenizatoria,
)

SEM_FUNCAO = "Não informada"


def _filtrar_despesas(
    stmt: Select[Any], ano: int | None, uf: str | None, partido: str | None
) -> Select[Any]:
    """Aplica ano/UF/partido. O `stmt` precisa ter Despesa e Deputado no FROM."""
    if ano is not None:
        stmt = stmt.where(Despesa.ano == ano)
    if uf:
        stmt = stmt.where(Deputado.sigla_uf == uf)
    if partido:
        stmt = stmt.where(Deputado.sigla_partido == partido)
    return stmt


def _ordem_recentes() -> tuple[Any, ...]:
    return (
        Despesa.data_documento.desc().nulls_last(),
        Despesa.ano.desc(),
        Despesa.mes.desc(),
        Despesa.id.desc(),
    )


# --------------------------------------------------------------------------- deputados / filtros


def listar_deputados(db: Session, uf: str | None = None, partido: str | None = None) -> list[Deputado]:
    stmt = select(Deputado).order_by(Deputado.nome)
    if uf:
        stmt = stmt.where(Deputado.sigla_uf == uf)
    if partido:
        stmt = stmt.where(Deputado.sigla_partido == partido)
    return list(db.scalars(stmt))


def filtros_disponiveis(db: Session) -> dict[str, list[Any]]:
    """UFs e partidos dos deputados e anos que têm despesas / pagamentos de emendas."""
    ufs = db.scalars(
        select(distinct(Deputado.sigla_uf)).where(Deputado.sigla_uf.is_not(None)).order_by(Deputado.sigla_uf)
    )
    partidos = db.scalars(
        select(distinct(Deputado.sigla_partido))
        .where(Deputado.sigla_partido.is_not(None))
        .order_by(Deputado.sigla_partido)
    )
    anos = db.scalars(select(distinct(Despesa.ano)).order_by(Despesa.ano.desc()))
    anos_emendas = db.scalars(select(distinct(EmendaPagamento.ano)).order_by(EmendaPagamento.ano.desc()))
    return {
        "ufs": list(ufs),
        "partidos": list(partidos),
        "anos": list(anos),
        "anos_emendas": list(anos_emendas),
    }


# --------------------------------------------------------------------------- CEAP


def resumo_gastos(
    db: Session, ano: int | None = None, uf: str | None = None, partido: str | None = None
) -> dict[str, int]:
    """Total líquido, nº de deputados com gasto e nº de despesas no filtro."""
    stmt = select(
        func.coalesce(func.sum(Despesa.valor_liquido_centavos), 0),
        func.count(distinct(Despesa.deputado_id)),
        func.count(Despesa.id),
    ).join(Deputado, Despesa.deputado_id == Deputado.id)
    total, deputados, despesas = db.execute(_filtrar_despesas(stmt, ano, uf, partido)).one()
    return {"total_liquido": int(total), "qtd_deputados": deputados, "qtd_despesas": despesas}


def ranking_gastos(
    db: Session,
    ano: int | None = None,
    uf: str | None = None,
    partido: str | None = None,
    limit: int = 10,
    ordem: str = "total",
) -> list[dict[str, Any]]:
    """Deputados ordenados pelo total líquido ou pelo quanto gastam acima da média do estado.

    O teto da cota varia por UF, então comparar o total bruto favorece estados
    com teto maior. `ordem="relativo"` divide o total pela média dos colegas do
    mesmo estado no período (só quem tem 6+ meses com despesas entra na média,
    para suplentes de passagem não puxarem a média para baixo).
    """
    filtro_ano = [Despesa.ano == ano] if ano is not None else []
    totais = (
        select(
            Despesa.deputado_id.label("deputado_id"),
            func.sum(Despesa.valor_liquido_centavos).label("total"),
            func.count(Despesa.id).label("qtd"),
            func.count(distinct(Despesa.ano * 100 + Despesa.mes)).label("meses"),
        )
        .where(*filtro_ano)
        .group_by(Despesa.deputado_id)
        .subquery()
    )
    medias = (
        select(Deputado.sigla_uf.label("sigla_uf"), func.avg(totais.c.total).label("media"))
        .join(totais, totais.c.deputado_id == Deputado.id)
        .where(totais.c.meses >= 6)
        .group_by(Deputado.sigla_uf)
        .subquery()
    )
    indice = (totais.c.total * 1.0 / medias.c.media).label("indice")
    stmt = (
        select(Deputado, totais.c.total, totais.c.qtd, medias.c.media, indice)
        .join(totais, totais.c.deputado_id == Deputado.id)
        .outerjoin(medias, medias.c.sigla_uf == Deputado.sigla_uf)
        .limit(limit)
    )
    if uf:
        stmt = stmt.where(Deputado.sigla_uf == uf)
    if partido:
        stmt = stmt.where(Deputado.sigla_partido == partido)
    if ordem == "relativo":
        stmt = stmt.order_by(indice.desc().nulls_last(), Deputado.nome)
    else:
        stmt = stmt.order_by(totais.c.total.desc(), Deputado.nome)
    return [
        {
            "deputado": dep,
            "total_liquido": int(total),
            "qtd_despesas": qtd,
            "media_uf": int(round(media)) if media is not None else None,
            "indice_uf": round(float(ind), 2) if ind is not None else None,
        }
        for dep, total, qtd, media, ind in db.execute(stmt).all()
    ]


def gastos_por_tipo(
    db: Session, ano: int | None = None, uf: str | None = None, partido: str | None = None
) -> list[dict[str, Any]]:
    """Total líquido por `tipo_despesa`, do maior para o menor."""
    total = func.sum(Despesa.valor_liquido_centavos).label("total")
    stmt = (
        select(Despesa.tipo_despesa, total, func.count(Despesa.id))
        .join(Deputado, Despesa.deputado_id == Deputado.id)
        .group_by(Despesa.tipo_despesa)
        .order_by(total.desc())
    )
    linhas = db.execute(_filtrar_despesas(stmt, ano, uf, partido)).all()
    return [
        {"tipo_despesa": tipo, "total_liquido": int(soma), "qtd_despesas": qtd} for tipo, soma, qtd in linhas
    ]


def ultimas_despesas(
    db: Session,
    ano: int | None = None,
    uf: str | None = None,
    partido: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[int, list[Despesa]]:
    """Despesas mais recentes (data desc, depois ano/mês desc) com o deputado carregado."""
    contagem = select(func.count(Despesa.id)).join(Deputado, Despesa.deputado_id == Deputado.id)
    total = db.scalar(_filtrar_despesas(contagem, ano, uf, partido)) or 0
    stmt = (
        select(Despesa)
        .join(Despesa.deputado)
        .options(contains_eager(Despesa.deputado))
        .order_by(*_ordem_recentes())
        .limit(limit)
        .offset(offset)
    )
    return total, list(db.scalars(_filtrar_despesas(stmt, ano, uf, partido)))


def gastos_deputado(
    db: Session, deputado_id: int, ano: int | None = None, limit: int = 20, offset: int = 0
) -> dict[str, Any] | None:
    """Total, série mensal e despesas paginadas de um deputado. `None` se não existir."""
    deputado = db.get(Deputado, deputado_id)
    if deputado is None:
        return None

    filtro = [Despesa.deputado_id == deputado_id]
    if ano is not None:
        filtro.append(Despesa.ano == ano)

    total, qtd = db.execute(
        select(func.coalesce(func.sum(Despesa.valor_liquido_centavos), 0), func.count(Despesa.id)).where(*filtro)
    ).one()
    serie = db.execute(
        select(Despesa.ano, Despesa.mes, func.sum(Despesa.valor_liquido_centavos))
        .where(*filtro)
        .group_by(Despesa.ano, Despesa.mes)
        .order_by(Despesa.ano, Despesa.mes)
    ).all()
    despesas = db.scalars(
        select(Despesa).where(*filtro).order_by(*_ordem_recentes()).limit(limit).offset(offset)
    )
    return {
        "deputado": deputado,
        "ano": ano,
        "total_liquido": int(total),
        "qtd_despesas": qtd,
        "serie_mensal": [{"ano": a, "mes": m, "total_liquido": int(s)} for a, m, s in serie],
        "despesas": {"total": qtd, "itens": list(despesas)},
    }


def ultimo_sync(db: Session) -> dict[str, datetime]:
    """Data da última execução concluída de cada fonte."""
    linhas = db.execute(
        select(SyncExecucao.fonte, func.max(SyncExecucao.concluido_em)).group_by(SyncExecucao.fonte)
    ).all()
    return {fonte: quando for fonte, quando in linhas}


# --------------------------------------------------------------------------- emendas


def _deputados_por_id(db: Session, ids: set[int]) -> dict[int, Deputado]:
    if not ids:
        return {}
    return {d.id: d for d in db.scalars(select(Deputado).where(Deputado.id.in_(ids)))}


def _funcao_por_emenda() -> Any:
    """Subconsulta código da emenda -> função (área), a partir do catálogo de emendas."""
    return (
        select(Emenda.codigo_emenda, func.min(Emenda.funcao).label("funcao"))
        .where(Emenda.codigo_emenda.is_not(None))
        .group_by(Emenda.codigo_emenda)
        .subquery()
    )


def buscar_municipios(
    db: Session,
    busca: str | None = None,
    uf: str | None = None,
    ano: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Municípios que receberam pagamentos de emendas, do maior total para o menor.

    A busca ignora acentos e caixa ("carpina" encontra "CARPINA").
    """
    total = func.sum(EmendaPagamento.valor_recebido_centavos).label("total")
    stmt = (
        select(
            EmendaPagamento.sigla_uf,
            func.max(EmendaPagamento.municipio),
            total,
            func.count(EmendaPagamento.id),
        )
        .where(EmendaPagamento.municipio_normalizado.is_not(None), EmendaPagamento.sigla_uf.is_not(None))
        .group_by(EmendaPagamento.sigla_uf, EmendaPagamento.municipio_normalizado)
        .order_by(total.desc())
        .limit(limit)
    )
    termo = normalizar_nome(busca)
    if termo:
        stmt = stmt.where(EmendaPagamento.municipio_normalizado.contains(termo))
    if uf:
        stmt = stmt.where(EmendaPagamento.sigla_uf == uf)
    if ano is not None:
        stmt = stmt.where(EmendaPagamento.ano == ano)
    return [
        {"sigla_uf": sigla, "municipio": nome, "total_recebido": int(soma), "qtd_pagamentos": qtd}
        for sigla, nome, soma, qtd in db.execute(stmt).all()
    ]


def _filtro_municipio(uf: str, municipio: str, ano: int | None) -> list[Any]:
    filtro = [
        EmendaPagamento.sigla_uf == uf,
        EmendaPagamento.municipio_normalizado == normalizar_nome(municipio),
    ]
    if ano is not None:
        filtro.append(EmendaPagamento.ano == ano)
    return filtro


def emendas_municipio(db: Session, uf: str, municipio: str, ano: int | None = None) -> dict[str, Any] | None:
    """O que chegou de emendas a um município: totais, autores, favorecidos, áreas e série.

    `None` se o município não tiver nenhum pagamento (no ano, se informado).
    """
    filtro = _filtro_municipio(uf, municipio, ano)
    total, qtd, autores, nome = db.execute(
        select(
            func.coalesce(func.sum(EmendaPagamento.valor_recebido_centavos), 0),
            func.count(EmendaPagamento.id),
            func.count(distinct(EmendaPagamento.nome_autor_normalizado)),
            func.max(EmendaPagamento.municipio),
        ).where(*filtro)
    ).one()
    if not qtd:
        return None

    soma = func.sum(EmendaPagamento.valor_recebido_centavos).label("total")
    por_autor = db.execute(
        select(
            func.max(EmendaPagamento.nome_autor),
            func.max(EmendaPagamento.deputado_id),
            soma,
            func.count(EmendaPagamento.id),
        )
        .where(*filtro)
        .group_by(EmendaPagamento.nome_autor_normalizado)
        .order_by(soma.desc())
    ).all()
    deputados = _deputados_por_id(db, {dep for _, dep, _, _ in por_autor if dep is not None})

    por_favorecido = db.execute(
        select(
            EmendaPagamento.favorecido,
            EmendaPagamento.codigo_favorecido,
            func.max(EmendaPagamento.tipo_favorecido),
            soma,
            func.count(EmendaPagamento.id),
        )
        .where(*filtro)
        .group_by(EmendaPagamento.codigo_favorecido, EmendaPagamento.favorecido)
        .order_by(soma.desc())
    ).all()

    funcoes = _funcao_por_emenda()
    por_funcao = db.execute(
        select(funcoes.c.funcao, soma)
        .select_from(EmendaPagamento)
        .outerjoin(funcoes, funcoes.c.codigo_emenda == EmendaPagamento.codigo_emenda)
        .where(*filtro)
        .group_by(funcoes.c.funcao)
        .order_by(soma.desc())
    ).all()

    serie = db.execute(
        select(EmendaPagamento.ano, EmendaPagamento.mes, soma)
        .where(*filtro)
        .group_by(EmendaPagamento.ano, EmendaPagamento.mes)
        .order_by(EmendaPagamento.ano, EmendaPagamento.mes)
    ).all()

    acoes = (
        select(Emenda.codigo_emenda, func.min(Emenda.acao).label("acao"))
        .where(Emenda.codigo_emenda.is_not(None))
        .group_by(Emenda.codigo_emenda)
        .subquery()
    )
    por_acao = db.execute(
        select(acoes.c.acao, soma)
        .select_from(EmendaPagamento)
        .outerjoin(acoes, acoes.c.codigo_emenda == EmendaPagamento.codigo_emenda)
        .where(*filtro)
        .group_by(acoes.c.acao)
        .order_by(soma.desc())
        .limit(10)
    ).all()

    return {
        "sigla_uf": uf,
        "municipio": nome,
        "ano": ano,
        "total_recebido": int(total),
        "qtd_pagamentos": qtd,
        "qtd_autores": autores,
        "por_autor": [
            {
                "nome_autor": autor or "Sem informação",
                "deputado": deputados.get(dep) if dep is not None else None,
                "total_recebido": int(s),
                "qtd_pagamentos": n,
            }
            for autor, dep, s, n in por_autor
        ],
        "por_favorecido": [
            {
                "favorecido": fav or "Sem informação",
                "codigo_favorecido": cod,
                "tipo_favorecido": tipo,
                "total_recebido": int(s),
                "qtd_pagamentos": n,
            }
            for fav, cod, tipo, s, n in por_favorecido
        ],
        "por_funcao": [{"funcao": f or SEM_FUNCAO, "total": int(s)} for f, s in por_funcao],
        "por_acao": [{"acao": a or "Ação não informada", "total": int(s)} for a, s in por_acao],
        "serie_mensal": [{"ano": a, "mes": m, "total_recebido": int(s)} for a, m, s in serie],
    }


def pagamentos_municipio(
    db: Session, uf: str, municipio: str, ano: int | None = None, limit: int = 20, offset: int = 0
) -> tuple[int, list[dict[str, Any]]]:
    """Pagamentos de emendas a favorecidos do município, mais recentes primeiro.

    Cada pagamento traz a ação orçamentária (catálogo) e, se houver convênio,
    o objeto contratado: é o "para quê" do dinheiro.
    """
    filtro = _filtro_municipio(uf, municipio, ano)
    total = db.scalar(select(func.count(EmendaPagamento.id)).where(*filtro)) or 0
    acoes = (
        select(Emenda.codigo_emenda, func.min(Emenda.acao).label("acao"))
        .where(Emenda.codigo_emenda.is_not(None))
        .group_by(Emenda.codigo_emenda)
        .subquery()
    )
    objetos = (
        select(EmendaConvenio.codigo_emenda, func.min(EmendaConvenio.objeto).label("objeto"))
        .where(EmendaConvenio.codigo_emenda.is_not(None))
        .group_by(EmendaConvenio.codigo_emenda)
        .subquery()
    )
    linhas = db.execute(
        select(EmendaPagamento, acoes.c.acao, objetos.c.objeto)
        .outerjoin(acoes, acoes.c.codigo_emenda == EmendaPagamento.codigo_emenda)
        .outerjoin(objetos, objetos.c.codigo_emenda == EmendaPagamento.codigo_emenda)
        .where(*filtro)
        .order_by(
            EmendaPagamento.ano.desc(),
            EmendaPagamento.mes.desc(),
            EmendaPagamento.valor_recebido_centavos.desc(),
            EmendaPagamento.id,
        )
        .limit(limit)
        .offset(offset)
    ).all()
    itens = [
        {**{c.name: getattr(p, c.name) for c in EmendaPagamento.__table__.columns}, "acao": acao, "objeto": objeto}
        for p, acao, objeto in linhas
    ]
    return total, itens


def emendas_deputado(
    db: Session, deputado_id: int, ano: int | None = None, limite_destinos: int = 15
) -> dict[str, Any] | None:
    """Emendas de um deputado: empenhado, pago, áreas e municípios que receberam.

    `ano` filtra o ano da emenda no catálogo e o ano do pagamento nos destinos;
    sem `ano`, considera a legislatura atual. `total_pago` soma o pago no
    exercício e os restos a pagar já pagos.
    """
    deputado = db.get(Deputado, deputado_id)
    if deputado is None:
        return None

    inicio = get_settings().ano_inicial_legislatura
    filtro_emenda = [Emenda.deputado_id == deputado_id]
    filtro_emenda.append(Emenda.ano == ano if ano is not None else Emenda.ano >= inicio)
    qtd, empenhado, pago = db.execute(
        select(
            func.count(distinct(Emenda.codigo_emenda)),
            func.coalesce(func.sum(Emenda.valor_empenhado_centavos), 0),
            func.coalesce(func.sum(Emenda.valor_pago_centavos + Emenda.valor_rp_pago_centavos), 0),
        ).where(*filtro_emenda)
    ).one()
    pago_funcao = func.sum(Emenda.valor_pago_centavos + Emenda.valor_rp_pago_centavos).label("total")
    por_funcao = db.execute(
        select(Emenda.funcao, pago_funcao)
        .where(*filtro_emenda)
        .group_by(Emenda.funcao)
        .order_by(pago_funcao.desc())
    ).all()

    filtro_pag = [EmendaPagamento.deputado_id == deputado_id]
    filtro_pag.append(EmendaPagamento.ano == ano if ano is not None else EmendaPagamento.ano >= inicio)
    recebido = db.scalar(
        select(func.coalesce(func.sum(EmendaPagamento.valor_recebido_centavos), 0)).where(*filtro_pag)
    )
    soma = func.sum(EmendaPagamento.valor_recebido_centavos).label("total")
    destinos = db.execute(
        select(
            EmendaPagamento.sigla_uf,
            func.max(EmendaPagamento.municipio),
            soma,
            func.count(EmendaPagamento.id),
        )
        .where(*filtro_pag)
        .group_by(EmendaPagamento.sigla_uf, EmendaPagamento.municipio_normalizado)
        .order_by(soma.desc())
        .limit(limite_destinos)
    ).all()

    return {
        "deputado": deputado,
        "ano": ano,
        "qtd_emendas": qtd,
        "total_empenhado": int(empenhado),
        "total_pago": int(pago),
        "total_recebido_municipios": int(recebido or 0),
        "por_funcao": [{"funcao": f or SEM_FUNCAO, "total": int(s or 0)} for f, s in por_funcao],
        "por_destino": [
            {"sigla_uf": uf, "municipio": mun, "total_recebido": int(s), "qtd_pagamentos": n}
            for uf, mun, s, n in destinos
        ],
    }


# --------------------------------------------------------------------------- alertas


def _filtro_alertas(
    tipo: str | None,
    gravidade: str | None,
    ano: int | None,
    uf: str | None,
    partido: str | None,
    esfera: str | None = None,
) -> list[Any]:
    """Filtros comuns. UF e partido valem para federais e estaduais (estaduais e órgãos são de PE)."""
    filtro: list[Any] = []
    if tipo:
        # "pix_*" filtra pelo prefixo (todos os alertas de Emenda Pix).
        filtro.append(Alerta.tipo.startswith(tipo[:-1]) if tipo.endswith("*") else Alerta.tipo == tipo)
    if gravidade:
        filtro.append(Alerta.gravidade == gravidade)
    if ano is not None:
        filtro.append(Alerta.ano == ano)
    if esfera:
        filtro.append(Alerta.esfera == esfera)
    if uf:
        filtro.append(or_(Deputado.sigla_uf == uf, and_(Alerta.esfera != "federal", uf == "PE")))
    if partido:
        filtro.append(or_(Deputado.sigla_partido == partido, DeputadoEstadual.sigla_partido == partido))
    return filtro


def _alertas_base(*colunas: Any) -> Select[Any]:
    return (
        select(*colunas)
        .select_from(Alerta)
        .outerjoin(Deputado, Alerta.deputado_id == Deputado.id)
        .outerjoin(DeputadoEstadual, Alerta.deputado_estadual_id == DeputadoEstadual.id)
        .outerjoin(UnidadeGestora, Alerta.unidade_gestora_id == UnidadeGestora.id)
        .outerjoin(Senador, Alerta.senador_id == Senador.id)
    )


def listar_alertas(
    db: Session,
    tipo: str | None = None,
    gravidade: str | None = None,
    ano: int | None = None,
    uf: str | None = None,
    partido: str | None = None,
    deputado_id: int | None = None,
    cnpj: str | None = None,
    limit: int = 20,
    offset: int = 0,
    esfera: str | None = None,
    deputado_estadual_id: int | None = None,
    unidade_gestora_id: int | None = None,
    senador_id: int | None = None,
    municipio_ibge: str | None = None,
    min_prioridade: int | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Alertas com quem gastou (deputado, deputado estadual ou órgão); os de maior prioridade primeiro."""
    filtro = _filtro_alertas(tipo, gravidade, ano, uf, partido, esfera)
    if min_prioridade:
        filtro.append(Alerta.prioridade >= min_prioridade)
    if deputado_id is not None:
        filtro.append(Alerta.deputado_id == deputado_id)
    if deputado_estadual_id is not None:
        filtro.append(Alerta.deputado_estadual_id == deputado_estadual_id)
    if unidade_gestora_id is not None:
        filtro.append(Alerta.unidade_gestora_id == unidade_gestora_id)
    if senador_id is not None:
        filtro.append(Alerta.senador_id == senador_id)
    if municipio_ibge:
        ugs = select(UnidadeGestora.id).join(
            Municipio,
            and_(Municipio.sigla_uf == UnidadeGestora.sigla_uf,
                 Municipio.nome_normalizado == UnidadeGestora.municipio_normalizado),
        ).where(Municipio.codigo_ibge == municipio_ibge)
        filtro.append(or_(Alerta.municipio_ibge == municipio_ibge, Alerta.unidade_gestora_id.in_(ugs)))
    if cnpj:
        filtro.append(Alerta.cnpj == cnpj)
    total = db.scalar(_alertas_base(func.count(Alerta.id)).where(*filtro)) or 0
    linhas = db.execute(
        _alertas_base(Alerta, Deputado, DeputadoEstadual, UnidadeGestora, Senador)
        .where(*filtro)
        .order_by(Alerta.prioridade.desc(), Alerta.valor_centavos.desc(), Alerta.id)
        .limit(limit)
        .offset(offset)
    ).all()
    itens = [_alerta_dict(a, d, e, u, sen) for a, d, e, u, sen in linhas]
    codigos = {i["municipio_ibge"] for i in itens if i["municipio_ibge"]}
    cidades = {
        m.codigo_ibge: {"codigo_ibge": m.codigo_ibge, "nome": m.nome, "sigla_uf": m.sigla_uf}
        for m in db.scalars(select(Municipio).where(Municipio.codigo_ibge.in_(codigos)))
    } if codigos else {}
    for i in itens:
        i["municipio"] = cidades.get(i["municipio_ibge"] or "")
    return total, itens


def _alerta_dict(
    alerta: Alerta,
    deputado: Deputado | None,
    estadual: DeputadoEstadual | None = None,
    orgao: UnidadeGestora | None = None,
    senador: Senador | None = None,
) -> dict[str, Any]:
    return {
        "senador": senador,
        "orgao_contratante": {"cnpj": alerta.orgao_cnpj, "nome": alerta.orgao_nome or "Órgão contratante"}
        if alerta.orgao_cnpj else None,
        "municipio_ibge": alerta.municipio_ibge,
        "id": alerta.id,
        "tipo": alerta.tipo,
        "gravidade": alerta.gravidade,
        "prioridade": alerta.prioridade or 0,
        "esfera": alerta.esfera,
        "deputado": deputado,
        "deputado_estadual": estadual,
        "orgao": orgao,
        "cnpj": alerta.cnpj,
        "ano": alerta.ano,
        "valor": alerta.valor_centavos,
        "titulo": alerta.titulo,
        "descricao": alerta.descricao,
    }


def resumo_alertas(
    db: Session,
    ano: int | None = None,
    uf: str | None = None,
    partido: str | None = None,
    esfera: str | None = None,
) -> dict[str, Any]:
    """Quantidade de alertas por tipo e gravidade, e de quem (deputados/órgãos) tem algum alerta."""
    filtro = _filtro_alertas(None, None, ano, uf, partido, esfera)
    por_tipo: dict[str, dict[str, int]] = {}
    for tipo, gravidade, qtd in db.execute(
        _alertas_base(Alerta.tipo, Alerta.gravidade, func.count(Alerta.id))
        .where(*filtro)
        .group_by(Alerta.tipo, Alerta.gravidade)
    ):
        por_tipo.setdefault(tipo, {"alta": 0, "media": 0})[gravidade] = qtd
    alvo = func.coalesce(
        literal("f") + cast(Alerta.deputado_id, String),
        literal("s") + cast(Alerta.senador_id, String),
        literal("e") + cast(Alerta.deputado_estadual_id, String),
        literal("m") + cast(Alerta.unidade_gestora_id, String),
        literal("o") + Alerta.orgao_cnpj,
    )
    envolvidos = db.scalar(_alertas_base(func.count(distinct(alvo))).where(*filtro)) or 0
    por_esfera = dict(
        db.execute(_alertas_base(Alerta.esfera, func.count(Alerta.id)).where(*filtro).group_by(Alerta.esfera)).all()
    )
    return {
        "total": sum(v["alta"] + v["media"] for v in por_tipo.values()),
        "altas": sum(v["alta"] for v in por_tipo.values()),
        "qtd_deputados": envolvidos,
        "por_tipo": [{"tipo": t, "alta": v["alta"], "media": v["media"]} for t, v in sorted(por_tipo.items())],
        "por_esfera": por_esfera,
    }


# --------------------------------------------------------------------------- fornecedores


def detalhe_fornecedor(db: Session, cnpj: str) -> dict[str, Any] | None:
    """Cadastro na Receita e quanto recebeu da cota federal, da verba estadual e de órgãos municipais."""
    soma = func.sum(Despesa.valor_liquido_centavos).label("total")
    por_deputado = db.execute(
        select(Deputado, soma, func.count(Despesa.id))
        .join(Despesa, Despesa.deputado_id == Deputado.id)
        .where(Despesa.cnpj_cpf == cnpj)
        .group_by(Deputado.id)
        .order_by(soma.desc())
    ).all()
    soma_e = func.sum(VerbaIndenizatoria.valor_centavos).label("total")
    por_estadual = db.execute(
        select(DeputadoEstadual, soma_e, func.count(VerbaIndenizatoria.id))
        .join(VerbaIndenizatoria, VerbaIndenizatoria.deputado_estadual_id == DeputadoEstadual.id)
        .where(VerbaIndenizatoria.cnpj_cpf == cnpj)
        .group_by(DeputadoEstadual.id)
        .order_by(soma_e.desc())
    ).all()
    soma_m = func.sum(DespesaMunicipal.valor_pago_centavos).label("total")
    por_orgao = db.execute(
        select(UnidadeGestora, soma_m, func.coalesce(func.sum(DespesaMunicipal.qtd_empenhos), 0))
        .join(DespesaMunicipal, DespesaMunicipal.unidade_gestora_id == UnidadeGestora.id)
        .where(DespesaMunicipal.cpf_cnpj == cnpj)
        .group_by(UnidadeGestora.id)
        .order_by(soma_m.desc())
    ).all()
    if not (por_deputado or por_estadual or por_orgao):
        return None

    uniao = (
        select(Despesa.ano.label("ano"), Despesa.valor_liquido_centavos.label("valor"), Despesa.data_documento.label("data"),
               Despesa.fornecedor.label("nome"))
        .where(Despesa.cnpj_cpf == cnpj)
        .union_all(
            select(VerbaIndenizatoria.ano, VerbaIndenizatoria.valor_centavos, VerbaIndenizatoria.data,
                   VerbaIndenizatoria.fornecedor).where(VerbaIndenizatoria.cnpj_cpf == cnpj),
            select(DespesaMunicipal.ano, DespesaMunicipal.valor_pago_centavos, DespesaMunicipal.data_empenho,
                   DespesaMunicipal.fornecedor).where(DespesaMunicipal.cpf_cnpj == cnpj),
        )
        .subquery()
    )
    qtd, nome, primeira, ultima = db.execute(
        select(func.count(), func.max(uniao.c.nome), func.min(uniao.c.data), func.max(uniao.c.data))
    ).one()
    por_ano = db.execute(
        select(uniao.c.ano, func.sum(uniao.c.valor)).group_by(uniao.c.ano).order_by(uniao.c.ano)
    ).all()
    total_cota = sum(int(t) for _, t, _ in por_deputado)
    total_estadual = sum(int(t) for _, t, _ in por_estadual)
    total_municipal = sum(int(t) for _, t, _ in por_orgao)
    return {
        "cnpj": cnpj,
        "nome": nome,
        "cadastro": db.get(Fornecedor, cnpj),
        "total_recebido": total_cota + total_estadual + total_municipal,
        "total_cota": total_cota,
        "total_estadual": total_estadual,
        "total_municipal": total_municipal,
        "qtd_despesas": qtd,
        "primeira_nota": primeira,
        "ultima_nota": ultima,
        "por_deputado": [{"deputado": d, "total_liquido": int(t), "qtd_despesas": n} for d, t, n in por_deputado],
        "por_deputado_estadual": [
            {"deputado": d, "total_liquido": int(t), "qtd_despesas": n} for d, t, n in por_estadual
        ],
        "por_orgao": [{"orgao": o, "total_pago": int(t), "qtd_empenhos": n} for o, t, n in por_orgao],
        "por_ano": [{"ano": a, "total": int(t)} for a, t in por_ano],
    }


# --------------------------------------------------------------------------- cidade: extras


def municipio_ibge(db: Session, uf: str, municipio: str) -> Municipio | None:
    return db.scalar(
        select(Municipio).where(
            Municipio.sigla_uf == uf, Municipio.nome_normalizado == normalizar_nome(municipio)
        )
    )


def extras_municipio(db: Session, uf: str, municipio: str, ano: int | None = None) -> dict[str, Any]:
    """População, valor por habitante e quanto veio por transferência especial ("emenda Pix")."""
    filtro = _filtro_municipio(uf, municipio, ano)
    total, pix = db.execute(
        select(
            func.coalesce(func.sum(EmendaPagamento.valor_recebido_centavos), 0),
            func.coalesce(
                func.sum(
                    case(
                        (EmendaPagamento.tipo_emenda.like("%Transferências Especiais%"), EmendaPagamento.valor_recebido_centavos),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(*filtro)
    ).one()
    cidade = municipio_ibge(db, uf, municipio)
    populacao = cidade.populacao if cidade else None
    return {
        "codigo_ibge": cidade.codigo_ibge if cidade else None,
        "populacao": populacao,
        "ano_populacao": cidade.ano_populacao if cidade else None,
        "regiao_imediata": cidade.regiao_imediata_nome if cidade else None,
        "por_habitante": int(round(total / populacao)) if populacao else None,
        "total_pix": int(pix),
    }


def comparacao_regiao(db: Session, uf: str, municipio: str, ano: int | None = None) -> dict[str, Any] | None:
    """Emendas recebidas por habitante nos municípios da mesma região imediata do IBGE."""
    cidade = municipio_ibge(db, uf, municipio)
    if cidade is None or cidade.regiao_imediata_id is None:
        return None
    filtro_ano = [EmendaPagamento.ano == ano] if ano is not None else []
    recebido = (
        select(
            EmendaPagamento.sigla_uf.label("uf"),
            EmendaPagamento.municipio_normalizado.label("nome"),
            func.sum(EmendaPagamento.valor_recebido_centavos).label("total"),
        )
        .where(*filtro_ano)
        .group_by(EmendaPagamento.sigla_uf, EmendaPagamento.municipio_normalizado)
        .subquery()
    )
    linhas = db.execute(
        select(Municipio, func.coalesce(recebido.c.total, 0))
        .outerjoin(
            recebido,
            and_(recebido.c.uf == Municipio.sigla_uf, recebido.c.nome == Municipio.nome_normalizado),
        )
        .where(Municipio.regiao_imediata_id == cidade.regiao_imediata_id)
    ).all()
    itens = [
        {
            "codigo_ibge": m.codigo_ibge,
            "municipio": m.nome,
            "sigla_uf": m.sigla_uf,
            "populacao": m.populacao,
            "total_recebido": int(total),
            "por_habitante": int(round(total / m.populacao)) if m.populacao else None,
            "atual": m.codigo_ibge == cidade.codigo_ibge,
        }
        for m, total in linhas
    ]
    itens.sort(key=lambda i: -(i["por_habitante"] or 0))
    return {"regiao_imediata": cidade.regiao_imediata_nome, "ano": ano, "municipios": itens}


def cota_na_cidade(db: Session, uf: str, municipio: str, ano: int | None = None) -> dict[str, Any] | None:
    """Gastos da cota (de qualquer deputado) com empresas sediadas no município.

    Depende da base de CNPJ carregada; `None` se o município não estiver no IBGE.
    """
    cidade = municipio_ibge(db, uf, municipio)
    if cidade is None:
        return None
    filtro = [Fornecedor.codigo_municipio_ibge == cidade.codigo_ibge]
    if ano is not None:
        filtro.append(Despesa.ano == ano)
    base = select().select_from(Despesa).join(Fornecedor, Fornecedor.cnpj == Despesa.cnpj_cpf).where(*filtro)
    total, qtd = db.execute(
        base.add_columns(func.coalesce(func.sum(Despesa.valor_liquido_centavos), 0), func.count(Despesa.id))
    ).one()
    soma = func.sum(Despesa.valor_liquido_centavos).label("total")
    por_deputado = db.execute(
        base.add_columns(Despesa.deputado_id, soma, func.count(Despesa.id))
        .group_by(Despesa.deputado_id)
        .order_by(soma.desc())
        .limit(20)
    ).all()
    deputados = _deputados_por_id(db, {d for d, _, _ in por_deputado})
    por_fornecedor = db.execute(
        base.add_columns(
            Despesa.cnpj_cpf,
            func.coalesce(func.max(Fornecedor.nome_fantasia), func.max(Fornecedor.razao_social), func.max(Despesa.fornecedor)),
            soma,
            func.count(distinct(Despesa.deputado_id)),
        )
        .group_by(Despesa.cnpj_cpf)
        .order_by(soma.desc())
        .limit(20)
    ).all()
    carregada = db.scalar(select(func.count()).select_from(Fornecedor)) or 0
    return {
        "base_cnpj_carregada": carregada > 0,
        "total_liquido": int(total),
        "qtd_despesas": qtd,
        "por_deputado": [
            {"deputado": deputados[d], "total_liquido": int(s), "qtd_despesas": n}
            for d, s, n in por_deputado
            if d in deputados
        ],
        "por_fornecedor": [
            {"cnpj": c, "nome": n, "total_liquido": int(s), "qtd_deputados": q} for c, n, s, q in por_fornecedor
        ],
    }


# --------------------------------------------------------------------------- deputados estaduais (ALEPE)


def _filtro_verba(ano: int | None) -> list[Any]:
    return [VerbaIndenizatoria.ano == ano] if ano is not None else [
        VerbaIndenizatoria.ano >= get_settings().ano_inicial_legislatura
    ]


def listar_estaduais(
    db: Session, ano: int | None = None, partido: str | None = None, busca: str | None = None
) -> list[dict[str, Any]]:
    """Deputados estaduais com verba no período (ou em exercício), do maior gasto para o menor."""
    totais = (
        select(
            VerbaIndenizatoria.deputado_estadual_id.label("dep"),
            func.sum(VerbaIndenizatoria.valor_centavos).label("total"),
            func.count(VerbaIndenizatoria.id).label("qtd"),
            func.count(distinct(VerbaIndenizatoria.ano * 100 + VerbaIndenizatoria.mes)).label("meses"),
        )
        .where(*_filtro_verba(ano))
        .group_by(VerbaIndenizatoria.deputado_estadual_id)
        .subquery()
    )
    stmt = (
        select(DeputadoEstadual, totais.c.total, totais.c.qtd, totais.c.meses)
        .outerjoin(totais, totais.c.dep == DeputadoEstadual.id)
        .where(or_(totais.c.total.is_not(None), DeputadoEstadual.em_exercicio.is_(True)))
        .order_by(func.coalesce(totais.c.total, 0).desc(), DeputadoEstadual.nome)
    )
    if partido:
        stmt = stmt.where(DeputadoEstadual.sigla_partido == partido)
    termo = normalizar_nome(busca)
    if termo:
        stmt = stmt.where(DeputadoEstadual.nome_normalizado.contains(termo))
    return [
        {"deputado": d, "total": int(t or 0), "qtd_notas": int(q or 0), "meses": int(m or 0)}
        for d, t, q, m in db.execute(stmt).all()
    ]


def resumo_estaduais(db: Session, ano: int | None = None) -> dict[str, Any]:
    filtro = _filtro_verba(ano)
    total, qtd, deputados = db.execute(
        select(
            func.coalesce(func.sum(VerbaIndenizatoria.valor_centavos), 0),
            func.count(VerbaIndenizatoria.id),
            func.count(distinct(VerbaIndenizatoria.deputado_estadual_id)),
        ).where(*filtro)
    ).one()
    soma = func.sum(VerbaIndenizatoria.valor_centavos).label("total")
    rubricas = db.execute(
        select(VerbaIndenizatoria.rubrica_nome, soma).where(*filtro)
        .group_by(VerbaIndenizatoria.rubrica_nome).order_by(soma.desc())
    ).all()
    anos = list(db.scalars(select(distinct(VerbaIndenizatoria.ano)).order_by(VerbaIndenizatoria.ano.desc())))
    return {
        "total": int(total),
        "qtd_notas": qtd,
        "qtd_deputados": deputados,
        "por_rubrica": [{"rubrica": r or "Não informada", "total": int(t)} for r, t in rubricas],
        "anos": anos,
    }


def detalhe_estadual(
    db: Session, deputado_id: int, ano: int | None = None, limit: int = 20, offset: int = 0
) -> dict[str, Any] | None:
    deputado = db.get(DeputadoEstadual, deputado_id)
    if deputado is None:
        return None
    filtro = [VerbaIndenizatoria.deputado_estadual_id == deputado_id, *_filtro_verba(ano)]
    total, qtd = db.execute(
        select(func.coalesce(func.sum(VerbaIndenizatoria.valor_centavos), 0), func.count(VerbaIndenizatoria.id))
        .where(*filtro)
    ).one()
    soma = func.sum(VerbaIndenizatoria.valor_centavos).label("total")
    rubricas = db.execute(
        select(VerbaIndenizatoria.rubrica_nome, soma).where(*filtro)
        .group_by(VerbaIndenizatoria.rubrica_nome).order_by(soma.desc())
    ).all()
    serie = db.execute(
        select(VerbaIndenizatoria.ano, VerbaIndenizatoria.mes, soma).where(*filtro)
        .group_by(VerbaIndenizatoria.ano, VerbaIndenizatoria.mes)
        .order_by(VerbaIndenizatoria.ano, VerbaIndenizatoria.mes)
    ).all()
    fornecedores = db.execute(
        select(VerbaIndenizatoria.cnpj_cpf, func.max(VerbaIndenizatoria.fornecedor), soma, func.count(VerbaIndenizatoria.id))
        .where(*filtro)
        .group_by(VerbaIndenizatoria.cnpj_cpf)
        .order_by(soma.desc())
        .limit(20)
    ).all()
    notas = db.scalars(
        select(VerbaIndenizatoria).where(*filtro)
        .order_by(VerbaIndenizatoria.ano.desc(), VerbaIndenizatoria.mes.desc(), VerbaIndenizatoria.valor_centavos.desc())
        .limit(limit).offset(offset)
    )
    return {
        "deputado": deputado,
        "ano": ano,
        "total": int(total),
        "qtd_notas": qtd,
        "por_rubrica": [{"rubrica": r or "Não informada", "total": int(t)} for r, t in rubricas],
        "serie_mensal": [{"ano": a, "mes": m, "total": int(t)} for a, m, t in serie],
        "por_fornecedor": [
            {"cnpj": c, "nome": n, "total": int(t), "qtd_notas": q} for c, n, t, q in fornecedores
        ],
        "notas": {"total": qtd, "itens": list(notas)},
    }


# --------------------------------------------------------------------------- municípios (tribunais de contas)


def inicio_mandato_municipal(hoje: date | None = None) -> int:
    """Ano de posse do mandato municipal em curso (2021, 2025, 2029...)."""
    ano = (hoje or date.today()).year
    return ano - ((ano - 2021) % 4)


def _orgaos(db: Session, uf: str, municipio: str) -> list[UnidadeGestora]:
    return list(
        db.scalars(
            select(UnidadeGestora).where(
                UnidadeGestora.sigla_uf == uf,
                UnidadeGestora.municipio_normalizado == normalizar_nome(municipio),
            )
        )
    )


def _eh_camara(o: UnidadeGestora) -> bool:
    return (o.natureza or "").startswith("Câmara")


# O TCE-PE agrega folha, aposentadorias e contratações temporárias neste "credor".
CREDOR_NAO_IDENTIFICADO = "FORNECEDOR NAO CADASTRADO NA RECEITA FEDERAL"


def _credor_interno(db: Session, uf: str, municipio: str) -> Any:
    """Condição dos pagamentos que não vão a um fornecedor: o agregado de folha do TCE-PE, o
    próprio município como credor (no TCE-SP, folha e encargos aparecem assim) e repasses
    entre órgãos da mesma cidade (prefeitura -> câmara, autarquia, fundação)."""
    cnpjs: list[str] = []
    codigo = _codigo_ibge(db, uf, municipio)
    if codigo:
        cnpj = db.scalar(select(EnteSiconfi.cnpj).where(EnteSiconfi.codigo_ibge == codigo))
        cnpjs = [cnpj] if cnpj else []
    nomes = [CREDOR_NAO_IDENTIFICADO, *(normalizar_nome(o.nome) for o in _orgaos(db, uf, municipio))]
    return or_(DespesaMunicipal.fornecedor_normalizado.in_(nomes), DespesaMunicipal.cpf_cnpj.in_(cnpjs))


def _sem_credor(db: Session, filtro: list[Any], interno: Any) -> int:
    return int(
        db.scalar(select(func.coalesce(func.sum(DespesaMunicipal.valor_pago_centavos), 0)).where(*filtro, interno))
        or 0
    )


def _top_fornecedores(db: Session, filtro: list[Any], interno: Any, limite: int = 15) -> list[dict[str, Any]]:
    """Maiores credores identificados (sem o agregado de folha nem o próprio município)."""
    soma = func.sum(DespesaMunicipal.valor_pago_centavos).label("total")
    linhas = db.execute(
        select(
            DespesaMunicipal.fornecedor_normalizado,
            func.max(DespesaMunicipal.fornecedor),
            func.max(DespesaMunicipal.cpf_cnpj),
            func.max(DespesaMunicipal.tipo_pessoa),
            soma,
            func.coalesce(func.sum(DespesaMunicipal.qtd_empenhos), 0),
        )
        .where(*filtro, DespesaMunicipal.valor_pago_centavos > 0, func.coalesce(interno, False).is_(False))
        .group_by(DespesaMunicipal.fornecedor_normalizado)
        .order_by(soma.desc())
        .limit(limite)
    ).all()
    return [
        {"nome": n or "Não informado", "cpf_cnpj": c, "tipo_pessoa": tp, "total_pago": int(t), "qtd_empenhos": q}
        for _, n, c, tp, t, q in linhas
    ]


def _agrupar(db: Session, coluna: Any, filtro: list[Any], limite: int = 12) -> list[dict[str, Any]]:
    soma = func.sum(DespesaMunicipal.valor_pago_centavos).label("total")
    return [
        {"nome": n or "Não informado", "total_pago": int(t)}
        for n, t in db.execute(
            select(coluna, soma).where(*filtro).group_by(coluna).having(soma > 0).order_by(soma.desc()).limit(limite)
        ).all()
    ]


def _filtro_municipal(ids: list[int], ano: int | None) -> list[Any]:
    filtro: list[Any] = [DespesaMunicipal.unidade_gestora_id.in_(ids)]
    filtro.append(
        DespesaMunicipal.ano == ano if ano is not None else DespesaMunicipal.ano >= inicio_mandato_municipal() - 2
    )
    return filtro


def camara_municipio(db: Session, uf: str, municipio: str, ano: int | None = None) -> dict[str, Any] | None:
    """Câmara de vereadores: gastos, quanto cada vereador recebeu nominalmente e pessoal nomeado."""
    camaras = [o for o in _orgaos(db, uf, municipio) if _eh_camara(o)]
    if not camaras:
        return None
    ids = [o.id for o in camaras]
    filtro = _filtro_municipal(ids, ano)
    interno = _credor_interno(db, uf, municipio)
    total, qtd = db.execute(
        select(
            func.coalesce(func.sum(DespesaMunicipal.valor_pago_centavos), 0),
            func.coalesce(func.sum(DespesaMunicipal.qtd_empenhos), 0),
        )
        .where(*filtro)
    ).one()

    inicio = inicio_mandato_municipal()
    vinculos = list(db.scalars(select(ServidorMunicipal).where(ServidorMunicipal.unidade_gestora_id.in_(ids))))
    vereadores: dict[str, dict[str, Any]] = {}
    for v in vinculos:
        if not (v.cargo or "").upper().startswith("VEREADOR"):
            continue
        atual = v.data_admissao is not None and v.data_admissao.year >= inicio
        item = vereadores.setdefault(v.nome_normalizado, {"nome": v.nome, "mandato_atual": False, "salario": None,
                                                          "salario_mes": None})
        item["mandato_atual"] = item["mandato_atual"] or atual
        if v.remuneracao_centavos and (v.remuneracao_mes or 0) >= (item["salario_mes"] or 0):
            item["salario"], item["salario_mes"] = v.remuneracao_centavos, v.remuneracao_mes

    soma = func.sum(DespesaMunicipal.valor_pago_centavos).label("total")
    nominais = db.execute(
        select(DespesaMunicipal.fornecedor_normalizado, DespesaMunicipal.elemento_despesa, soma,
               func.sum(DespesaMunicipal.qtd_empenhos))
        .where(*filtro, DespesaMunicipal.fornecedor_normalizado.in_(list(vereadores)))
        .group_by(DespesaMunicipal.fornecedor_normalizado, DespesaMunicipal.elemento_despesa)
    ).all()
    for nome, elemento, t, n in nominais:
        item = vereadores[nome]
        item["total_recebido"] = item.get("total_recebido", 0) + int(t)
        item["qtd_pagamentos"] = item.get("qtd_pagamentos", 0) + n
        item.setdefault("por_tipo", []).append({"nome": elemento or "Não informado", "total_pago": int(t)})
    lista_vereadores = sorted(
        (
            {"total_recebido": 0, "qtd_pagamentos": 0, "por_tipo": [], **v}
            for v in vereadores.values()
            if v["mandato_atual"] or v.get("total_recebido")
        ),
        key=lambda v: (-v["total_recebido"], v["nome"]),
    )

    nomeados = [v for v in vinculos if v.data_admissao is not None and v.data_admissao.year >= inicio]
    por_vinculo: dict[str, int] = {}
    por_cargo: dict[str, int] = {}
    for v in nomeados:
        por_vinculo[v.vinculo or "Não informado"] = por_vinculo.get(v.vinculo or "Não informado", 0) + 1
        if (v.vinculo or "").startswith("Cargo Comissionado"):
            por_cargo[v.cargo or "Não informado"] = por_cargo.get(v.cargo or "Não informado", 0) + 1

    return {
        "orgao": camaras[0],
        "ano": ano,
        "inicio_mandato": inicio,
        "total_pago": int(total),
        "qtd_empenhos": qtd,
        "vereadores": lista_vereadores,
        "qtd_vereadores_mandato": sum(1 for v in lista_vereadores if v["mandato_atual"]),
        "nomeados_no_mandato": len(nomeados),
        "por_vinculo": [{"nome": k, "qtd": n} for k, n in sorted(por_vinculo.items(), key=lambda x: -x[1])],
        "comissionados_por_cargo": [
            {"nome": k, "qtd": n} for k, n in sorted(por_cargo.items(), key=lambda x: -x[1])[:12]
        ],
        "por_elemento": _agrupar(db, DespesaMunicipal.elemento_despesa, filtro),
        "fornecedores": _top_fornecedores(db, filtro, interno),
        "sem_credor_identificado": _sem_credor(db, filtro, interno),
    }


def prefeitura_municipio(db: Session, uf: str, municipio: str, ano: int | None = None) -> dict[str, Any] | None:
    """Prefeitura e demais órgãos do município (exceto a câmara): para onde foi o dinheiro."""
    orgaos = [o for o in _orgaos(db, uf, municipio) if not _eh_camara(o)]
    if not orgaos:
        return None
    ids = [o.id for o in orgaos]
    filtro = _filtro_municipal(ids, ano)
    interno = _credor_interno(db, uf, municipio)
    total, empenhado, qtd = db.execute(
        select(
            func.coalesce(func.sum(DespesaMunicipal.valor_pago_centavos), 0),
            func.coalesce(func.sum(DespesaMunicipal.valor_empenhado_centavos), 0),
            func.coalesce(func.sum(DespesaMunicipal.qtd_empenhos), 0),
        ).where(*filtro)
    ).one()
    soma = func.sum(DespesaMunicipal.valor_pago_centavos).label("total")
    por_orgao = db.execute(
        select(DespesaMunicipal.unidade_gestora_id, soma).where(*filtro).group_by(DespesaMunicipal.unidade_gestora_id)
    ).all()
    nomes = {o.id: o for o in orgaos}
    anos = list(
        db.scalars(
            select(distinct(DespesaMunicipal.ano))
            .where(DespesaMunicipal.unidade_gestora_id.in_(ids))
            .order_by(DespesaMunicipal.ano.desc())
        )
    )
    return {
        "ano": ano,
        "anos": anos,
        "total_pago": int(total),
        "total_empenhado": int(empenhado),
        "qtd_empenhos": qtd,
        "por_orgao": [
            {"orgao": nomes[i], "total_pago": int(t)} for i, t in sorted(por_orgao, key=lambda x: -x[1]) if i in nomes
        ],
        "por_funcao": _agrupar(db, DespesaMunicipal.funcao, filtro),
        "por_elemento": _agrupar(db, DespesaMunicipal.elemento_despesa, filtro),
        "fornecedores": _top_fornecedores(db, filtro, interno, 20),
        "sem_credor_identificado": _sem_credor(db, filtro, interno),
    }


def empenhos_municipio(
    db: Session,
    uf: str,
    municipio: str,
    ano: int | None = None,
    orgao_id: int | None = None,
    busca: str | None = None,
    limit: int = 20,
    offset: int = 0,
    fonte: str | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Empenhos do município, mais recentes primeiro; `busca` procura no credor e no histórico.

    `fonte`: "pix" ou "pix_estadual" limita aos gastos pagos com Emenda Pix (todos os anos).
    """
    orgaos = {o.id: o for o in _orgaos(db, uf, municipio)}
    ids = [orgao_id] if orgao_id in orgaos else list(orgaos)
    if not ids:
        return 0, []
    if fonte in FONTES_PIX:
        filtro = [DespesaMunicipal.unidade_gestora_id.in_(ids), DespesaMunicipal.fonte_recurso == FONTES_PIX[fonte]()]
        if ano is not None:
            filtro.append(DespesaMunicipal.ano == ano)
    else:
        filtro = _filtro_municipal(ids, ano)
    termo = normalizar_nome(busca)
    if termo:
        filtro.append(
            or_(
                DespesaMunicipal.fornecedor_normalizado.contains(termo),
                DespesaMunicipal.historico_normalizado.contains(termo),
            )
        )
    total = db.scalar(select(func.count(DespesaMunicipal.id)).where(*filtro)) or 0  # linhas, para paginar
    itens = db.scalars(
        select(DespesaMunicipal).where(*filtro)
        .order_by(DespesaMunicipal.data_empenho.desc().nulls_last(), DespesaMunicipal.id.desc())
        .limit(limit).offset(offset)
    )
    return total, [{**{c.name: getattr(d, c.name) for c in DespesaMunicipal.__table__.columns},
                    "orgao": orgaos[d.unidade_gestora_id].nome} for d in itens]


# --------------------------------------------------------------------------- cidade: pessoal da prefeitura

# Despesas de pessoal (elemento de despesa) e como aparecem para o cidadão.
CATEGORIAS_FOLHA = (
    ("Efetivos e comissionados", "Vencimentos e Vantagens Fixas%"),
    ("Contratados temporários", "Contrata%Tempo Determinado%"),
    ("Encargos (INSS, previdência)", "Obriga%Patronais%"),
    ("Aposentadorias e pensões", "Aposentadorias%"),
    ("Aposentadorias e pensões", "Pens%es%"),
    ("Outras despesas de pessoal", "Outras Despesas Vari%Pessoal%"),
)
ELEMENTO_SERVICO_PF = "Outros Servi%Pessoa F%sica"
# Onde a folha vem por pessoa (TCE-PB), as categorias são os tipos de vínculo.
CATEGORIA_VINCULO = (
    ("Efetivos", ("EFETIVO", "EMPREGO PUBLICO")),
    ("Comissionados e funções de confiança", ("COMISSIONADO", "FUNCAO DE CONFIANCA")),
    ("Contratados temporários", ("CONTRATACAO", "EXCEPCIONAL")),
    ("Eletivos", ("ELETIVO",)),
    ("Aposentados e pensionistas", ("INATIVO", "PENSION", "BENEFICIO PREVIDENCIARIO")),
)


def _categoria_vinculo(vinculo: str | None) -> str:
    norm = normalizar_nome(vinculo) or ""
    for nome, chaves in CATEGORIA_VINCULO:
        if any(c in norm for c in chaves):
            return nome
    return "Outros"


def _orgaos_sem_camara(db: Session, uf: str, municipio: str) -> list[UnidadeGestora]:
    return [o for o in _orgaos(db, uf, municipio) if not _eh_camara(o)]


def _cpf_mascarado(cpf_meio: str | None) -> str | None:
    return f"***.{cpf_meio[:3]}.{cpf_meio[3:]}-**" if cpf_meio and len(cpf_meio) == 6 else None


def _categoria_folha(elemento: str | None) -> str | None:
    for nome, padrao in CATEGORIAS_FOLHA:
        if elemento and fnmatch.fnmatch(elemento.upper(), padrao.replace("%", "*").upper()):
            return nome
    return None


def pessoal_municipio(db: Session, uf: str, municipio: str, ano: int | None = None) -> dict[str, Any] | None:
    """Quem trabalha para a prefeitura (lista de pessoal do TCE-PE), quanto custa a folha mês a mês
    (empenhos de pessoal), quem recebe como pessoa física e quem, nomeado no mandato, doou para
    campanhas de 2024 no município."""
    orgaos = _orgaos_sem_camara(db, uf, municipio)
    if not orgaos:
        return None
    ids = [o.id for o in orgaos]
    nomes_orgaos = {o.id: o.nome for o in orgaos}
    inicio = inicio_mandato_municipal()

    # 1. Quadro de pessoal
    vinculos = list(db.scalars(select(ServidorMunicipal).where(ServidorMunicipal.unidade_gestora_id.in_(ids))))

    def pessoa(v: ServidorMunicipal) -> str:
        return v.hash_cpf or f"{v.nome_normalizado}|{v.cpf_meio}"

    por_vinculo: dict[str, dict[str, Any]] = {}
    admissoes: dict[int, dict[str, int]] = {}
    cargos: dict[tuple[str, str], set[str]] = {}
    for v in vinculos:
        tipo = v.vinculo or "Não informado"
        item = por_vinculo.setdefault(tipo, {"nome": tipo, "vinculos": 0, "pessoas": set(), "no_mandato": set()})
        item["vinculos"] += 1
        item["pessoas"].add(pessoa(v))
        if v.data_admissao and v.data_admissao.year >= inicio:
            item["no_mandato"].add(pessoa(v))
        if v.data_admissao and v.data_admissao.year >= inicio - 8:
            admissoes.setdefault(v.data_admissao.year, {}).setdefault(tipo, 0)
            admissoes[v.data_admissao.year][tipo] += 1
        cargos.setdefault((v.cargo or "Não informado", tipo), set()).add(pessoa(v))
    remessa = max(((v.ano_remessa or 0, v.mes_remessa or 0) for v in vinculos), default=None)

    # 2. Folha (empenhos de pessoal)
    anos = list(db.scalars(
        select(distinct(DespesaMunicipal.ano)).where(DespesaMunicipal.unidade_gestora_id.in_(ids))
        .order_by(DespesaMunicipal.ano.desc())
    ))
    ano = ano if ano in anos else (anos[0] if anos else None)
    padroes = or_(*(DespesaMunicipal.elemento_despesa.like(p) for _, p in CATEGORIAS_FOLHA))
    folha_meses: dict[int, dict[str, int]] = {}
    folha_anos: dict[int, dict[str, int]] = {}

    def somar(a: int, mes: int | None, elemento: str | None, total: Any) -> None:
        categoria = _categoria_folha(elemento)
        if categoria is None or a is None:
            return
        folha_anos.setdefault(a, {}).setdefault(categoria, 0)
        folha_anos[a][categoria] += int(total or 0)
        if a == ano and mes:
            folha_meses.setdefault(mes, {}).setdefault(categoria, 0)
            folha_meses[mes][categoria] += int(total or 0)

    folha_publicada = db.scalar(
        select(func.count()).select_from(FolhaMensal).where(FolhaMensal.unidade_gestora_id.in_(ids))
    ) or 0
    if folha_publicada:
        anos_folha = list(db.scalars(select(distinct(FolhaMensal.ano)).where(FolhaMensal.unidade_gestora_id.in_(ids))
                                     .order_by(FolhaMensal.ano.desc())))
        anos = sorted(set(anos) | set(anos_folha), reverse=True)
        ano = ano if ano in anos else anos[0]
        for a, mes, vinculo, total in db.execute(
            select(FolhaMensal.ano, FolhaMensal.mes, FolhaMensal.vinculo, func.sum(FolhaMensal.total_centavos))
            .where(FolhaMensal.unidade_gestora_id.in_(ids))
            .group_by(FolhaMensal.ano, FolhaMensal.mes, FolhaMensal.vinculo)
        ):
            categoria = _categoria_vinculo(vinculo)
            folha_anos.setdefault(a, {}).setdefault(categoria, 0)
            folha_anos[a][categoria] += int(total or 0)
            if a == ano:
                folha_meses.setdefault(mes, {}).setdefault(categoria, 0)
                folha_meses[mes][categoria] += int(total or 0)

    # A folha é empenhada de uma vez no começo do ano e paga mês a mês: a data do pagamento
    # (TCE-PE, EmpenhoPagamento) mostra o custo real de cada mês.
    tem_pagamentos = 0 if folha_publicada else db.scalar(
        select(func.count()).select_from(PagamentoMunicipal).where(PagamentoMunicipal.unidade_gestora_id.in_(ids))
    ) or 0
    if tem_pagamentos:
        ano_pag = cast(func.strftime("%Y", PagamentoMunicipal.data), Integer)
        mes_pag = cast(func.strftime("%m", PagamentoMunicipal.data), Integer)
        for a, mes, elemento, total in db.execute(
            select(ano_pag, mes_pag, DespesaMunicipal.elemento_despesa, func.sum(PagamentoMunicipal.valor_centavos))
            .join(DespesaMunicipal, and_(
                DespesaMunicipal.unidade_gestora_id == PagamentoMunicipal.unidade_gestora_id,
                DespesaMunicipal.ano == PagamentoMunicipal.ano,
                DespesaMunicipal.id_empenho == PagamentoMunicipal.id_empenho,
            ))
            .where(PagamentoMunicipal.unidade_gestora_id.in_(ids), padroes, PagamentoMunicipal.data.is_not(None))
            .group_by(ano_pag, mes_pag, DespesaMunicipal.elemento_despesa)
        ):
            somar(a, mes, elemento, total)
    elif not folha_publicada:
        for a, mes, elemento, total in db.execute(
            select(DespesaMunicipal.ano, DespesaMunicipal.mes, DespesaMunicipal.elemento_despesa,
                   func.sum(DespesaMunicipal.valor_pago_centavos))
            .where(DespesaMunicipal.unidade_gestora_id.in_(ids), padroes)
            .group_by(DespesaMunicipal.ano, DespesaMunicipal.mes, DespesaMunicipal.elemento_despesa)
        ):
            somar(a, mes, elemento, total)
    possiveis = ([nome for nome, _ in CATEGORIA_VINCULO] + ["Outros"]) if folha_publicada \
        else list(dict.fromkeys(nome for nome, _ in CATEGORIAS_FOLHA))
    categorias = [c for c in possiveis if any(v.get(c) for v in folha_anos.values())]  # sem colunas sempre zeradas

    # 3. Pessoas físicas pagas por serviço (prestadores, locadores de imóveis...)
    filtro_pf = [
        DespesaMunicipal.unidade_gestora_id.in_(ids), DespesaMunicipal.tipo_pessoa == "PF",
        DespesaMunicipal.elemento_despesa.like(ELEMENTO_SERVICO_PF), DespesaMunicipal.valor_pago_centavos > 0,
    ]
    if ano is not None:
        filtro_pf.append(DespesaMunicipal.ano == ano)
    soma = func.sum(DespesaMunicipal.valor_pago_centavos).label("total")
    prestadores_linhas = db.execute(
        select(DespesaMunicipal.fornecedor_normalizado, func.max(DespesaMunicipal.fornecedor),
               func.max(DespesaMunicipal.cpf_cnpj), soma, func.sum(DespesaMunicipal.qtd_empenhos),
               func.max(DespesaMunicipal.historico),
               func.sum(case((DespesaMunicipal.historico_normalizado.like("%LOCACAO%"), 1), else_=0)),
               func.count())
        .where(*filtro_pf).group_by(DespesaMunicipal.fornecedor_normalizado).order_by(soma.desc()).limit(40)
    ).all()
    total_prestadores, qtd_prestadores = db.execute(
        select(func.coalesce(func.sum(DespesaMunicipal.valor_pago_centavos), 0),
               func.count(distinct(DespesaMunicipal.fornecedor_normalizado))).where(*filtro_pf)
    ).one()
    # Também na lista de pessoal? Nome igual e os 3 dígitos do CPF que as duas bases mostram batem
    # (empenho: "***.***.004-04" -> 7º a 11º dígitos; pessoal: 4º a 9º).
    servidores_por_nome: dict[str, list[ServidorMunicipal]] = {}
    for v in vinculos:
        servidores_por_nome.setdefault(v.nome_normalizado, []).append(v)
    prestadores = []
    for nome_norm, nome, cpf, total, qtd, historico, locacoes, linhas_qtd in prestadores_linhas:
        digitos = "".join(ch for ch in (cpf or "") if ch.isdigit())
        tambem = [
            v for v in servidores_por_nome.get(nome_norm or "", [])
            if len(digitos) >= 3 and v.cpf_meio and v.cpf_meio[3:6] == digitos[:3]
        ]
        recente = max(tambem, key=lambda v: v.data_admissao or date.min) if tambem else None
        prestadores.append({
            "nome": nome or "Não informado",
            "cpf": cpf,
            "total_pago": int(total or 0),
            "qtd_empenhos": int(qtd or 0),
            "tipo": "Aluguel de imóvel" if locacoes and locacoes * 2 >= linhas_qtd else "Serviço",
            "exemplo": historico,
            "servidor": ({"cargo": recente.cargo, "vinculo": recente.vinculo, "data_admissao": recente.data_admissao}
                         if recente else None),
        })

    # 4. Nomeados no mandato que doaram para campanhas de 2024 no município
    cidade = municipio_ibge(db, uf, municipio)
    doadores: list[dict[str, Any]] = []
    if cidade:
        nomeados = {
            (v.nome_normalizado, v.cpf_meio): v for v in sorted(vinculos, key=lambda v: v.data_admissao or date.min)
            if v.cpf_meio and v.data_admissao and v.data_admissao.year >= inicio
        }
        if nomeados:
            for nome_norm, cpf_meio, doado, candidato, cargo_cand, partido, eleito in db.execute(
                select(DoacaoCampanha.doador_nome_normalizado, DoacaoCampanha.doador_cpf_meio,
                       func.sum(DoacaoCampanha.valor_centavos), Candidato.nome, Candidato.cargo,
                       Candidato.sigla_partido, Candidato.eleito)
                .join(Candidato, Candidato.sq_candidato == DoacaoCampanha.sq_candidato)
                .where(Candidato.municipio_ibge == cidade.codigo_ibge, Candidato.ano == 2024,
                       DoacaoCampanha.doador_nome_normalizado.in_({n for n, _ in nomeados}))
                .group_by(DoacaoCampanha.doador_nome_normalizado, DoacaoCampanha.doador_cpf_meio,
                          DoacaoCampanha.sq_candidato)
            ):
                v = nomeados.get((nome_norm, cpf_meio))
                if v is None:
                    continue
                doadores.append({
                    "nome": v.nome, "cargo": v.cargo, "vinculo": v.vinculo, "data_admissao": v.data_admissao,
                    "doado": int(doado or 0), "candidato": candidato, "cargo_candidato": cargo_cand,
                    "partido": partido, "eleito": bool(eleito),
                })
    doadores.sort(key=lambda d: -d["doado"])

    return {
        "ano": ano,
        "anos": anos,
        "inicio_mandato": inicio,
        "remessa": {"ano": remessa[0], "mes": remessa[1]} if remessa and remessa[0] else None,
        "qtd_vinculos": len(vinculos),
        "qtd_pessoas": len({pessoa(v) for v in vinculos}),
        "por_vinculo": sorted(
            ({"nome": k, "vinculos": v["vinculos"], "pessoas": len(v["pessoas"]), "no_mandato": len(v["no_mandato"])}
             for k, v in por_vinculo.items()),
            key=lambda x: -x["pessoas"],
        ),
        "admissoes_por_ano": [
            {"ano": a, "por_vinculo": [{"nome": k, "qtd": n} for k, n in sorted(v.items(), key=lambda x: -x[1])]}
            for a, v in sorted(admissoes.items())
        ],
        "cargos": [
            {"cargo": c, "vinculo": t, "pessoas": len(p)}
            for (c, t), p in sorted(cargos.items(), key=lambda x: -len(x[1]))[:20]
        ],
        "categorias_folha": categorias,
        "folha_pela_data_do_pagamento": bool(tem_pagamentos),
        "folha_fonte": "folha" if folha_publicada else ("pagamentos" if tem_pagamentos else "empenhos"),
        "tem_salarios": any(v.remuneracao_centavos is not None for v in vinculos),
        "maiores_salarios": [
            {"nome": v.nome, "cargo": v.cargo, "vinculo": v.vinculo, "orgao": nomes_orgaos.get(v.unidade_gestora_id),
             "remuneracao": v.remuneracao_centavos, "remuneracao_mes": v.remuneracao_mes,
             "remuneracao_ano": v.remuneracao_ano_centavos, "meses_pagos": v.meses_pagos}
            for v in sorted((v for v in vinculos if v.remuneracao_centavos),
                            key=lambda v: (v.remuneracao_mes or 0, v.remuneracao_centavos or 0), reverse=True)
            if v.remuneracao_mes == max((x.remuneracao_mes or 0 for x in vinculos), default=0)
        ][:25],
        "folha_por_ano": [
            {"ano": a, "total": sum(v.values()), "por_categoria": [{"nome": c, "total": v.get(c, 0)} for c in categorias]}
            for a, v in sorted(folha_anos.items(), reverse=True)
        ],
        "folha_por_mes": [
            {"mes": m, "total": sum(v.values()), "por_categoria": [{"nome": c, "total": v.get(c, 0)} for c in categorias]}
            for m, v in sorted(folha_meses.items())
        ],
        "prestadores_total": int(total_prestadores or 0),
        "prestadores_qtd": int(qtd_prestadores or 0),
        "prestadores": prestadores,
        "doadores_nomeados": doadores,
    }


def lista_pessoal(
    db: Session,
    uf: str,
    municipio: str,
    busca: str | None = None,
    vinculo: str | None = None,
    desde: int | None = None,
    limit: int = 20,
    offset: int = 0,
    ordem: str = "recentes",
) -> tuple[int, list[dict[str, Any]]]:
    """Vínculos da lista de pessoal (sem a câmara): mais recentes primeiro ou maiores salários; busca por nome ou cargo."""
    orgaos = {o.id: o for o in _orgaos_sem_camara(db, uf, municipio)}
    if not orgaos:
        return 0, []
    filtro: list[Any] = [ServidorMunicipal.unidade_gestora_id.in_(list(orgaos))]
    termo = normalizar_nome(busca)
    if termo:
        filtro.append(or_(ServidorMunicipal.nome_normalizado.contains(termo),
                          func.upper(ServidorMunicipal.cargo).contains(termo)))
    if vinculo:
        filtro.append(ServidorMunicipal.vinculo == vinculo)
    if desde:
        filtro.append(ServidorMunicipal.data_admissao >= date(desde, 1, 1))
    total = db.scalar(select(func.count()).select_from(ServidorMunicipal).where(*filtro)) or 0
    ordenacao = (
        (ServidorMunicipal.remuneracao_centavos.desc().nulls_last(), ServidorMunicipal.nome)
        if ordem == "salario" else (ServidorMunicipal.data_admissao.desc().nulls_last(), ServidorMunicipal.nome)
    )
    itens = db.scalars(select(ServidorMunicipal).where(*filtro).order_by(*ordenacao).limit(limit).offset(offset))
    return total, [
        {"nome": v.nome, "cargo": v.cargo, "vinculo": v.vinculo, "data_admissao": v.data_admissao,
         "matricula": v.matricula, "cpf": _cpf_mascarado(v.cpf_meio), "orgao": orgaos[v.unidade_gestora_id].nome,
         "remuneracao": v.remuneracao_centavos, "remuneracao_mes": v.remuneracao_mes,
         "remuneracao_ano": v.remuneracao_ano_centavos, "meses_pagos": v.meses_pagos}
        for v in itens
    ]


# --------------------------------------------------------------------------- cidade: contratos do tribunal (LICON)

PROCESSOS_SEM_DISPUTA = ("DISPENSA", "INEXIGIBILIDADE")


def _filtro_contratos_tce(ids: list[int], ano: int | None, busca: str | None = None,
                          tipo_processo: str | None = None) -> list[Any]:
    filtro: list[Any] = [ContratoMunicipal.unidade_gestora_id.in_(ids)]
    if ano is not None:
        filtro.append(ContratoMunicipal.ano == ano)
    termo = normalizar_nome(busca)
    if termo:
        filtro.append(or_(ContratoMunicipal.objeto_normalizado.contains(termo),
                          ContratoMunicipal.fornecedor_normalizado.contains(termo),
                          ContratoMunicipal.cpf_cnpj == re.sub(r"\D", "", busca or "")))
    if tipo_processo:
        filtro.append(ContratoMunicipal.tipo_processo == tipo_processo)
    return filtro


def contratos_tce_municipio(db: Session, uf: str, municipio: str, ano: int | None = None) -> dict[str, Any] | None:
    """Contratos informados ao tribunal de contas (TCE-PE/LICON): totais, modalidades e maiores fornecedores."""
    orgaos = {o.id: o for o in _orgaos(db, uf, municipio)}
    if not orgaos:
        return None
    ids = list(orgaos)
    anos = list(db.scalars(select(distinct(ContratoMunicipal.ano)).where(ContratoMunicipal.unidade_gestora_id.in_(ids))
                           .order_by(ContratoMunicipal.ano.desc())))
    if not anos:
        return None
    filtro = _filtro_contratos_tce(ids, ano)
    soma = func.coalesce(func.sum(ContratoMunicipal.valor_centavos), 0)
    total, qtd = db.execute(select(soma, func.count()).where(*filtro)).one()
    por_tipo = [
        {"nome": t or "Não informado", "qtd": n, "total": int(v)}
        for t, n, v in db.execute(
            select(ContratoMunicipal.tipo_processo, func.count(), soma).where(*filtro)
            .group_by(ContratoMunicipal.tipo_processo).order_by(soma.desc())
        )
    ]
    sem_disputa = sum(t["total"] for t in por_tipo if any(p in (normalizar_nome(t["nome"]) or "") for p in PROCESSOS_SEM_DISPUTA))
    soma_f = func.sum(ContratoMunicipal.valor_centavos).label("total")
    fornecedores = [
        {"nome": n or "Não informado", "cpf_cnpj": c, "tipo_pessoa": tp, "total": int(t), "qtd": q}
        for _, n, c, tp, t, q in db.execute(
            select(ContratoMunicipal.fornecedor_normalizado, func.max(ContratoMunicipal.fornecedor),
                   func.max(ContratoMunicipal.cpf_cnpj), func.max(ContratoMunicipal.tipo_pessoa), soma_f, func.count())
            .where(*filtro).group_by(ContratoMunicipal.fornecedor_normalizado).order_by(soma_f.desc()).limit(15)
        )
    ]
    return {"ano": ano, "anos": anos, "total": int(total), "qtd": qtd, "total_sem_disputa": sem_disputa,
            "por_tipo_processo": por_tipo, "fornecedores": fornecedores}


def lista_contratos_tce(
    db: Session, uf: str, municipio: str, ano: int | None = None, busca: str | None = None,
    tipo_processo: str | None = None, limit: int = 20, offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    orgaos = {o.id: o for o in _orgaos(db, uf, municipio)}
    if not orgaos:
        return 0, []
    filtro = _filtro_contratos_tce(list(orgaos), ano, busca, tipo_processo)
    total = db.scalar(select(func.count()).select_from(ContratoMunicipal).where(*filtro)) or 0
    itens = db.scalars(
        select(ContratoMunicipal).where(*filtro)
        .order_by(ContratoMunicipal.valor_centavos.desc(), ContratoMunicipal.id).limit(limit).offset(offset)
    )
    return total, [{**{c.name: getattr(x, c.name) for c in ContratoMunicipal.__table__.columns},
                    "orgao": orgaos[x.unidade_gestora_id].nome} for x in itens]


# --------------------------------------------------------------------------- cidade: Emenda Pix

FONTES_PIX: dict[str, Callable[[], str]] = {
    "pix": lambda: get_settings().fonte_pix_federal,
    "pix_estadual": lambda: get_settings().fonte_pix_estadual,
}


def emenda_pix_municipio(db: Session, uf: str, municipio: str) -> dict[str, Any] | None:
    """Emenda Pix na cidade: o que chegou (Transferegov), o plano declarado e o que a
    prefeitura informou ao tribunal de contas como gasto com esse dinheiro."""
    cidade = municipio_ibge(db, uf, municipio)
    if cidade is None:
        return None
    planos = list(db.scalars(select(PlanoPix).where(PlanoPix.municipio_ibge == cidade.codigo_ibge)))
    repasses: dict[int, list[RepassePix]] = {}
    if planos:
        for r in db.scalars(select(RepassePix).where(RepassePix.plano_id.in_([p.id for p in planos]))):
            repasses.setdefault(r.plano_id, []).append(r)

    s = get_settings()
    ids = [o.id for o in _orgaos(db, uf, municipio)]
    com_fonte = bool(ids) and db.scalar(
        select(func.count()).select_from(DespesaMunicipal)
        .where(DespesaMunicipal.unidade_gestora_id.in_(ids), DespesaMunicipal.fonte_recurso.is_not(None))
    ) > 0
    if not planos and not com_fonte:
        return None

    por_ano: dict[int, dict[str, int]] = {}

    def ano_(a: int) -> dict[str, int]:
        return por_ano.setdefault(a, {"recebido": 0, "gasto": 0, "gasto_corrente": 0, "gasto_capital": 0,
                                      "gasto_estadual": 0})

    itens_planos = []
    for p in sorted(planos, key=lambda p: (-p.ano, -p.id)):
        recebidos = repasses.get(p.id, [])
        for r in recebidos:
            if r.data:
                ano_(r.data.year)["recebido"] += r.valor_centavos
        itens_planos.append(
            {
                **{c.name: getattr(p, c.name) for c in PlanoPix.__table__.columns},
                "recebido_centavos": sum(r.valor_centavos for r in recebidos),
                "ultimo_repasse": max((r.data for r in recebidos if r.data), default=None),
            }
        )

    credores: list[dict[str, Any]] = []
    cobertura = None
    if com_fonte:
        soma = func.sum(DespesaMunicipal.valor_pago_centavos)
        for fonte, a, categoria, total in db.execute(
            select(DespesaMunicipal.fonte_recurso, DespesaMunicipal.ano, DespesaMunicipal.categoria_economica, soma)
            .where(DespesaMunicipal.unidade_gestora_id.in_(ids),
                   DespesaMunicipal.fonte_recurso.in_([s.fonte_pix_federal, s.fonte_pix_estadual]))
            .group_by(DespesaMunicipal.fonte_recurso, DespesaMunicipal.ano, DespesaMunicipal.categoria_economica)
        ):
            item = ano_(a)
            if fonte == s.fonte_pix_estadual:
                item["gasto_estadual"] += int(total or 0)
                continue
            item["gasto"] += int(total or 0)
            chave = "gasto_capital" if "CAPITAL" in (normalizar_nome(categoria) or "") else "gasto_corrente"
            item[chave] += int(total or 0)
        filtro = [DespesaMunicipal.unidade_gestora_id.in_(ids), DespesaMunicipal.fonte_recurso == s.fonte_pix_federal]
        credores = _top_fornecedores(db, filtro, literal(False), 15)
        ultimo = db.execute(
            select(DespesaMunicipal.ano, func.max(DespesaMunicipal.mes))
            .where(DespesaMunicipal.unidade_gestora_id.in_(ids))
            .group_by(DespesaMunicipal.ano).order_by(DespesaMunicipal.ano.desc()).limit(1)
        ).first()
        cobertura = {"ano": ultimo[0], "mes": ultimo[1]} if ultimo else None

    anos = [{"ano": a, **v} for a, v in sorted(por_ano.items(), reverse=True)]
    return {
        "municipio": cidade,
        "tem_gastos": com_fonte,
        "gastos_ate": cobertura,
        "total_recebido": sum(a["recebido"] for a in anos),
        "total_gasto": sum(a["gasto"] for a in anos),
        "total_gasto_corrente": sum(a["gasto_corrente"] for a in anos),
        "total_gasto_estadual": sum(a["gasto_estadual"] for a in anos),
        "anos": anos,
        "planos": itens_planos,
        "credores": credores,
    }


# --------------------------------------------------------------------------- documentos de um fornecedor

FONTES_DOCUMENTO = {
    "cota_federal": "Cota de deputado federal",
    "cota_senado": "Cota de senador",
    "verba_estadual": "Verba de deputado estadual",
    "empenho_municipal": "Despesa municipal (tribunal de contas)",
    "contrato_pncp": "Contrato público (PNCP)",
}


def url_contrato_pncp(numero_controle: str) -> str | None:
    """'08985624000117-2-000001/2025' -> página do contrato no PNCP."""
    try:
        cnpj, _, resto = numero_controle.split("-", 2)
        sequencial, ano = resto.split("/")
        return f"https://pncp.gov.br/app/contratos/{cnpj}/{ano}/{int(sequencial)}"
    except ValueError:
        return None


def documentos_fornecedor(db: Session, cnpj: str, limit: int = 20, offset: int = 0) -> tuple[int, list[dict[str, Any]]]:
    """Cada pagamento ou contrato do fornecedor, de todas as fontes, mais recentes primeiro."""
    def coluna(valor: Any, nome: str) -> Any:
        return literal(valor).label(nome) if not hasattr(valor, "label") else valor.label(nome)

    partes = [
        select(
            coluna("cota_federal", "fonte"), Despesa.data_documento.label("data"), Despesa.ano, Despesa.mes,
            Deputado.nome.label("pagador"), cast(Deputado.id, String).label("pagador_id"),
            Despesa.tipo_despesa.label("descricao"), Despesa.num_documento.label("documento"),
            Despesa.valor_liquido_centavos.label("valor"), Despesa.url_documento.label("url"),
        ).join(Deputado, Despesa.deputado_id == Deputado.id).where(Despesa.cnpj_cpf == cnpj),
        select(
            coluna("cota_senado", "fonte"), DespesaSenado.data, DespesaSenado.ano, DespesaSenado.mes,
            DespesaSenado.nome_senador, cast(DespesaSenado.senador_id, String),
            func.coalesce(DespesaSenado.detalhamento, DespesaSenado.tipo_despesa), DespesaSenado.documento,
            DespesaSenado.valor_centavos, literal(None),
        ).where(DespesaSenado.cnpj_cpf == cnpj),
        select(
            coluna("verba_estadual", "fonte"), VerbaIndenizatoria.data, VerbaIndenizatoria.ano, VerbaIndenizatoria.mes,
            DeputadoEstadual.nome, cast(DeputadoEstadual.id, String), VerbaIndenizatoria.rubrica_nome,
            VerbaIndenizatoria.docid, VerbaIndenizatoria.valor_centavos, literal(None),
        ).join(DeputadoEstadual, VerbaIndenizatoria.deputado_estadual_id == DeputadoEstadual.id)
        .where(VerbaIndenizatoria.cnpj_cpf == cnpj),
        select(
            coluna("empenho_municipal", "fonte"), DespesaMunicipal.data_empenho, DespesaMunicipal.ano,
            DespesaMunicipal.mes, UnidadeGestora.nome, cast(UnidadeGestora.id, String),
            # TCE-SP: a linha soma os empenhos do ano ao credor e não traz histórico.
            func.coalesce(DespesaMunicipal.historico, literal("Soma de ") + cast(DespesaMunicipal.qtd_empenhos, String)
                          + literal(" empenho(s) no ano (") + func.coalesce(UnidadeGestora.fonte, "") + literal(")")),
            DespesaMunicipal.numero_empenho, DespesaMunicipal.valor_pago_centavos, literal(None),
        ).join(UnidadeGestora, DespesaMunicipal.unidade_gestora_id == UnidadeGestora.id)
        .where(DespesaMunicipal.cpf_cnpj == cnpj),
        select(
            coluna("contrato_pncp", "fonte"), ContratoPncp.data_assinatura, ContratoPncp.ano,
            cast(func.strftime("%m", ContratoPncp.data_assinatura), Integer), ContratoPncp.orgao_nome,
            ContratoPncp.orgao_cnpj, ContratoPncp.objeto, ContratoPncp.numero_controle,
            ContratoPncp.valor_global_centavos, literal(None),
        ).where(ContratoPncp.fornecedor_ni == cnpj),
    ]
    uniao = union_all(*partes).subquery()
    total = db.scalar(select(func.count()).select_from(uniao)) or 0
    linhas = db.execute(
        select(uniao).order_by(uniao.c.data.desc().nulls_last(), uniao.c.ano.desc(), uniao.c.valor.desc())
        .limit(limit).offset(offset)
    ).mappings().all()
    itens = []
    for l in linhas:
        item = dict(l)
        item["fonte_nome"] = FONTES_DOCUMENTO[item["fonte"]]
        if item["fonte"] == "contrato_pncp" and item["documento"]:
            item["url"] = url_contrato_pncp(item["documento"])
        itens.append(item)
    return total, itens


# --------------------------------------------------------------------------- cidade: contratos (PNCP)


def _codigo_ibge(db: Session, uf: str, municipio: str) -> str | None:
    cidade = municipio_ibge(db, uf, municipio)
    return cidade.codigo_ibge if cidade else None


def _filtro_contratos(codigo: str, ano: int | None) -> list[Any]:
    filtro: list[Any] = [ContratoPncp.municipio_ibge == codigo]
    if ano is not None:
        filtro.append(ContratoPncp.ano == ano)
    return filtro


def contratos_municipio(db: Session, uf: str, municipio: str, ano: int | None = None) -> dict[str, Any] | None:
    """Contratos dos órgãos do município publicados no PNCP: totais, órgãos, categorias e fornecedores."""
    codigo = _codigo_ibge(db, uf, municipio)
    if codigo is None:
        return None
    filtro = _filtro_contratos(codigo, ano)
    total, qtd = db.execute(
        select(func.coalesce(func.sum(ContratoPncp.valor_global_centavos), 0), func.count()).where(*filtro)
    ).one()
    soma = func.sum(ContratoPncp.valor_global_centavos).label("total")
    por_orgao = db.execute(
        select(ContratoPncp.orgao_cnpj, func.max(ContratoPncp.orgao_nome), soma, func.count())
        .where(*filtro).group_by(ContratoPncp.orgao_cnpj).order_by(soma.desc()).limit(15)
    ).all()
    por_categoria = db.execute(
        select(ContratoPncp.categoria, soma).where(*filtro).group_by(ContratoPncp.categoria).order_by(soma.desc())
    ).all()
    fornecedores = db.execute(
        select(ContratoPncp.fornecedor_ni, func.max(ContratoPncp.fornecedor_nome), func.max(ContratoPncp.tipo_pessoa),
               soma, func.count())
        .where(*filtro).group_by(ContratoPncp.fornecedor_ni).order_by(soma.desc()).limit(20)
    ).all()
    anos = list(db.scalars(
        select(distinct(ContratoPncp.ano)).where(ContratoPncp.municipio_ibge == codigo, ContratoPncp.ano.is_not(None))
        .order_by(ContratoPncp.ano.desc())
    ))
    desde = get_settings().pncp_data_inicial
    dias_total = max((date.today() - desde).days + 1, 1)
    dias_coletados = db.scalar(select(func.count()).select_from(SyncPncpDia).where(SyncPncpDia.data >= desde)) or 0
    return {
        "cobertura_pct": min(100, round(100 * dias_coletados / dias_total)),
        "codigo_ibge": codigo,
        "ano": ano,
        "anos": anos,
        "cobertura_desde": desde,
        "total_contratado": int(total),
        "qtd_contratos": qtd,
        "por_orgao": [{"cnpj": c, "nome": n or "Órgão", "total": int(t), "qtd": q} for c, n, t, q in por_orgao],
        "por_categoria": [{"nome": c or "Não informada", "total_pago": int(t)} for c, t in por_categoria],
        "fornecedores": [
            {"nome": n or "Não informado", "cpf_cnpj": ni, "tipo_pessoa": tp, "total_pago": int(t), "qtd_empenhos": q}
            for ni, n, tp, t, q in fornecedores
        ],
    }


def lista_contratos(
    db: Session, uf: str, municipio: str, ano: int | None = None, busca: str | None = None,
    orgao_cnpj: str | None = None, limit: int = 20, offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    codigo = _codigo_ibge(db, uf, municipio)
    if codigo is None:
        return 0, []
    filtro = _filtro_contratos(codigo, ano)
    if orgao_cnpj:
        filtro.append(ContratoPncp.orgao_cnpj == orgao_cnpj)
    termo = normalizar_nome(busca)
    if termo:
        filtro.append(or_(ContratoPncp.objeto_normalizado.contains(termo),
                          func.upper(ContratoPncp.fornecedor_nome).contains(termo)))
    total = db.scalar(select(func.count()).select_from(ContratoPncp).where(*filtro)) or 0
    itens = db.scalars(
        select(ContratoPncp).where(*filtro)
        .order_by(ContratoPncp.data_assinatura.desc().nulls_last(), ContratoPncp.numero_controle)
        .limit(limit).offset(offset)
    )
    return total, [
        {**{c.name: getattr(x, c.name) for c in ContratoPncp.__table__.columns}, "url": url_contrato_pncp(x.numero_controle)}
        for x in itens
    ]


# --------------------------------------------------------------------------- cidade: contas (Siconfi)

_MEDIANAS_CACHE: dict[tuple[int, str | None, int | None], tuple[float, dict[str, int]]] = {}


def _filtro_periodo(ano: int, periodo: int | None) -> list[Any]:
    """DCA (periodo None) ou RREO de um bimestre: só se compara município com município do mesmo período."""
    if periodo is None:
        return [ContaMunicipal.ano == ano, ContaMunicipal.demonstrativo.is_not("RREO")]
    return [ContaMunicipal.ano == ano, ContaMunicipal.demonstrativo == "RREO", ContaMunicipal.periodo == periodo]


def _amostra(db: Session, ano: int, uf: str | None, periodo: int | None = None) -> int:
    """Quantos municípios têm contas carregadas no ano e período (na UF ou no Brasil)."""
    stmt = select(func.count(distinct(ContaMunicipal.codigo_ibge))).where(*_filtro_periodo(ano, periodo))
    if uf:
        stmt = stmt.join(Municipio, Municipio.codigo_ibge == ContaMunicipal.codigo_ibge).where(Municipio.sigla_uf == uf)
    return db.scalar(stmt) or 0


def _medianas_por_habitante(db: Session, ano: int, uf: str | None, periodo: int | None = None) -> dict[str, int]:
    """Mediana do gasto por habitante, por função, entre os municípios (da UF ou do Brasil):
    pago na DCA; liquidado até o bimestre no RREO.

    Calculada em Python (o SQLite não tem mediana) e guardada por 1 hora.
    """
    chave = (ano, uf, periodo)
    agora = time.monotonic()
    if chave in _MEDIANAS_CACHE and agora - _MEDIANAS_CACHE[chave][0] < 3600:
        return _MEDIANAS_CACHE[chave][1]
    medida = ContaMunicipal.pago_centavos if periodo is None else ContaMunicipal.liquidado_centavos
    stmt = (
        select(ContaMunicipal.cod_conta, medida, Municipio.populacao)
        .join(Municipio, Municipio.codigo_ibge == ContaMunicipal.codigo_ibge)
        .where(*_filtro_periodo(ano, periodo), ContaMunicipal.nivel.in_(("funcao", "total")), Municipio.populacao > 0)
    )
    if uf:
        stmt = stmt.where(Municipio.sigla_uf == uf)
    valores: dict[str, list[float]] = {}
    for conta, valor, pop in db.execute(stmt):
        valores.setdefault(conta, []).append(valor / pop)
    medianas = {conta: int(round(statistics.median(v))) for conta, v in valores.items() if len(v) >= 5}
    _MEDIANAS_CACHE[chave] = (agora, medianas)
    return medianas


def contas_municipio(db: Session, uf: str, municipio: str, ano: int | None = None) -> dict[str, Any] | None:
    """Despesa por função (Siconfi), por habitante, comparada à mediana da UF e do Brasil.

    Ano fechado: DCA, valor pago. Ano corrente: RREO do último bimestre, valor liquidado
    até ali (o RREO não traz o pago por função), com a dotação (orçamento) ao lado.
    """
    cidade = municipio_ibge(db, uf, municipio)
    if cidade is None:
        return None
    anos = list(db.scalars(
        select(distinct(ContaMunicipal.ano)).where(ContaMunicipal.codigo_ibge == cidade.codigo_ibge)
        .order_by(ContaMunicipal.ano.desc())
    ))
    if not anos:
        return {"codigo_ibge": cidade.codigo_ibge, "ano": None, "anos": [], "populacao": cidade.populacao,
                "total_pago": 0, "total_empenhado": 0, "por_habitante": None, "funcoes": [], "destaques": []}
    ano = ano if ano in anos else anos[0]
    contas = list(db.scalars(
        select(ContaMunicipal).where(ContaMunicipal.codigo_ibge == cidade.codigo_ibge, ContaMunicipal.ano == ano)
    ))
    rreo = all(c.demonstrativo == "RREO" for c in contas)
    periodo = max((c.periodo or 0 for c in contas), default=0) if rreo else None
    if rreo:
        contas = [c for c in contas if c.periodo == periodo]

    def valor(c: ContaMunicipal) -> int:
        return c.liquidado_centavos if rreo else c.pago_centavos

    pop = cidade.populacao or 0
    med_uf = _medianas_por_habitante(db, ano, cidade.sigla_uf, periodo)
    med_br = _medianas_por_habitante(db, ano, None, periodo)
    total = next((c for c in contas if c.nivel == "total"), None)

    def item(c: ContaMunicipal) -> dict[str, Any]:
        return {
            "codigo": c.cod_conta,
            "nome": c.conta.split(" - ", 1)[-1],
            "pago": valor(c),
            "empenhado": c.empenhado_centavos,
            "dotacao": c.dotacao_centavos if rreo else None,
            "por_habitante": int(round(valor(c) / pop)) if pop else None,
            "mediana_uf": med_uf.get(c.cod_conta),
            "mediana_brasil": med_br.get(c.cod_conta),
        }

    funcoes = sorted((item(c) for c in contas if c.nivel == "funcao"), key=lambda f: -f["pago"])
    # Subfunções que costumam interessar ao cidadão.
    destaques = [item(c) for c in contas if c.cod_conta in ("04.131", "13.392", "27.812") and valor(c) > 0]
    return {
        "codigo_ibge": cidade.codigo_ibge,
        "ano": ano,
        "anos": anos,
        "demonstrativo": "RREO" if rreo else "DCA",
        "bimestre": periodo,
        "populacao": pop or None,
        "total_pago": valor(total) if total else sum(f["pago"] for f in funcoes),
        "total_empenhado": total.empenhado_centavos if total else sum(f["empenhado"] for f in funcoes),
        "total_dotacao": total.dotacao_centavos if total and rreo else None,
        "por_habitante": int(round(valor(total) / pop)) if pop and total else None,
        "mediana_uf_total": med_uf.get("TOTAL"),
        "mediana_brasil_total": med_br.get("TOTAL"),
        "amostra_uf": _amostra(db, ano, cidade.sigla_uf, periodo),
        "amostra_brasil": _amostra(db, ano, None, periodo),
        "funcoes": funcoes,
        "destaques": destaques,
    }


# --------------------------------------------------------------------------- cidade: eleitos (TSE)


def eleitos_municipio(db: Session, uf: str, municipio: str, ano: int = 2024) -> dict[str, Any] | None:
    codigo = _codigo_ibge(db, uf, municipio)
    if codigo is None:
        return None
    candidatos = list(db.scalars(
        select(Candidato).where(Candidato.municipio_ibge == codigo, Candidato.ano == ano)
    ))
    eleitos = [c for c in candidatos if c.eleito]
    ordem = {"PREFEITO": 0, "VICE-PREFEITO": 1, "VEREADOR": 2}
    eleitos.sort(key=lambda c: (ordem.get(c.cargo, 9), -c.bens_centavos, c.nome))
    return {
        "codigo_ibge": codigo,
        "ano": ano,
        "qtd_candidaturas": len(candidatos),
        "eleitos": [
            {
                "nome": c.nome, "nome_urna": c.nome_urna, "cargo": c.cargo, "sigla_partido": c.sigla_partido,
                "resultado": c.resultado, "ocupacao": c.ocupacao, "instrucao": c.instrucao, "genero": c.genero,
                "bens": c.bens_centavos,
            }
            for c in eleitos
        ],
    }


# --------------------------------------------------------------------------- senadores


def _filtro_senado(ano: int | None) -> list[Any]:
    return [DespesaSenado.ano == ano] if ano is not None else [
        DespesaSenado.ano >= get_settings().ano_inicial_legislatura
    ]


def listar_senadores(db: Session, ano: int | None = None, uf: str | None = None, busca: str | None = None) -> list[dict[str, Any]]:
    totais = (
        select(DespesaSenado.senador_id.label("sen"), func.sum(DespesaSenado.valor_centavos).label("total"),
               func.count().label("qtd"))
        .where(*_filtro_senado(ano), DespesaSenado.senador_id.is_not(None))
        .group_by(DespesaSenado.senador_id).subquery()
    )
    stmt = (
        select(Senador, totais.c.total, totais.c.qtd)
        .outerjoin(totais, totais.c.sen == Senador.id)
        .where(or_(totais.c.total.is_not(None), Senador.em_exercicio.is_(True)))
        .order_by(func.coalesce(totais.c.total, 0).desc(), Senador.nome)
    )
    if uf:
        stmt = stmt.where(Senador.sigla_uf == uf)
    termo = normalizar_nome(busca)
    if termo:
        stmt = stmt.where(Senador.nome_normalizado.contains(termo))
    return [{"senador": s, "total": int(t or 0), "qtd_notas": int(q or 0)} for s, t, q in db.execute(stmt).all()]


def resumo_senado(db: Session, ano: int | None = None) -> dict[str, Any]:
    filtro = _filtro_senado(ano)
    total, qtd, senadores = db.execute(
        select(func.coalesce(func.sum(DespesaSenado.valor_centavos), 0), func.count(),
               func.count(distinct(DespesaSenado.senador_id))).where(*filtro)
    ).one()
    soma = func.sum(DespesaSenado.valor_centavos).label("total")
    tipos = db.execute(
        select(DespesaSenado.tipo_despesa, soma).where(*filtro).group_by(DespesaSenado.tipo_despesa).order_by(soma.desc())
    ).all()
    anos = list(db.scalars(select(distinct(DespesaSenado.ano)).order_by(DespesaSenado.ano.desc())))
    return {"total": int(total), "qtd_notas": qtd, "qtd_deputados": senadores,
            "por_rubrica": [{"rubrica": t or "Não informado", "total": int(v)} for t, v in tipos], "anos": anos}


def detalhe_senador(db: Session, senador_id: int, ano: int | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any] | None:
    senador = db.get(Senador, senador_id)
    if senador is None:
        return None
    filtro = [DespesaSenado.senador_id == senador_id, *_filtro_senado(ano)]
    total, qtd = db.execute(
        select(func.coalesce(func.sum(DespesaSenado.valor_centavos), 0), func.count()).where(*filtro)
    ).one()
    soma = func.sum(DespesaSenado.valor_centavos).label("total")
    tipos = db.execute(select(DespesaSenado.tipo_despesa, soma).where(*filtro)
                       .group_by(DespesaSenado.tipo_despesa).order_by(soma.desc())).all()
    serie = db.execute(select(DespesaSenado.ano, DespesaSenado.mes, soma).where(*filtro)
                       .group_by(DespesaSenado.ano, DespesaSenado.mes).order_by(DespesaSenado.ano, DespesaSenado.mes)).all()
    fornecedores = db.execute(
        select(DespesaSenado.cnpj_cpf, func.max(DespesaSenado.fornecedor), soma, func.count())
        .where(*filtro).group_by(DespesaSenado.cnpj_cpf).order_by(soma.desc()).limit(20)
    ).all()
    notas = db.scalars(select(DespesaSenado).where(*filtro)
                       .order_by(DespesaSenado.data.desc().nulls_last(), DespesaSenado.id.desc()).limit(limit).offset(offset))
    return {
        "senador": senador,
        "ano": ano,
        "total": int(total),
        "qtd_notas": qtd,
        "por_rubrica": [{"rubrica": t or "Não informado", "total": int(v)} for t, v in tipos],
        "serie_mensal": [{"ano": a, "mes": m, "total": int(v)} for a, m, v in serie],
        "por_fornecedor": [{"cnpj": c, "nome": n, "total": int(v), "qtd_notas": q} for c, n, v, q in fornecedores],
        "notas": {"total": qtd, "itens": [
            {"id": n.id, "docid": n.cod_documento or "", "ano": n.ano, "mes": n.mes,
             "rubrica_nome": n.detalhamento or n.tipo_despesa, "data": n.data, "cnpj_cpf": n.cnpj_cpf,
             "tipo_pessoa": n.tipo_pessoa, "fornecedor": n.fornecedor, "valor_centavos": n.valor_centavos}
            for n in notas
        ]},
    }
