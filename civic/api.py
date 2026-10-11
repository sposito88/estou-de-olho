"""Rotas FastAPI. Só validam parâmetros e serializam; a lógica fica em `queries.py`.

Rodar:  uvicorn civic.api:app --reload
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import quote
from xml.etree import ElementTree as ET

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from civic import __version__, queries
from civic.config import get_settings
from civic.database import get_db, init_db
from civic.limites import limitar_e_cachear
from civic.alertas import TITULOS_TIPO, formatar_brl
from civic.schemas import (
    AlertaOut,
    ContasMunicipioOut,
    ContratoOut,
    ContratosMunicipioOut,
    DetalheSenadorOut,
    EleitosOut,
    SenadorListaItem,
    DocumentoFornecedorOut,
    CamaraOut,
    DetalheEstadualOut,
    BuscaOut,
    ContestacaoAdmin,
    ContestacaoAtualizacao,
    ContestacaoIn,
    ContestacaoPublica,
    ContestacaoRecebida,
    EmendaPixOut,
    PessoalMunicipioOut,
    ServidorOut,
    EmpenhoOut,
    EstadualListaItem,
    PrefeituraOut,
    ResumoEstaduaisOut,
    ComparacaoRegiaoOut,
    CotaNaCidadeOut,
    DeputadoOut,
    DespesaComDeputadoOut,
    EmendasDeputadoOut,
    EmendasMunicipioOut,
    FiltrosOut,
    FornecedorOut,
    GastosDeputadoOut,
    HealthOut,
    MunicipioOut,
    PagamentoEmendaOut,
    Pagina,
    RankingItem,
    ResumoAlertasOut,
    ResumoGastosOut,
    TipoDespesaItem,
)

Db = Annotated[Session, Depends(get_db)]
Ano = Annotated[int | None, Query(ge=2008, le=2100, description="Ano (ex.: 2025)")]
Uf = Annotated[
    str | None, Query(min_length=2, max_length=2, pattern="^[A-Za-z]{2}$", description="Sigla da UF")
]
Partido = Annotated[str | None, Query(min_length=1, max_length=30, description="Sigla do partido")]
Esfera = Annotated[
    Literal["federal", "senado", "estadual", "municipal"] | None,
    Query(description="federal (cota da Câmara), senado (CEAPS), estadual (verba ALEPE) ou municipal (TCE-PE e PNCP)"),
]
Offset = Annotated[int, Query(ge=0)]
DeputadoId = Annotated[int, Path(ge=1, description="Id do deputado na Câmara")]
UfPath = Annotated[str, Path(min_length=2, max_length=2, pattern="^[A-Za-z]{2}$")]
MunicipioPath = Annotated[str, Path(min_length=2, max_length=120)]


def _uf(valor: str | None) -> str | None:
    return valor.upper() if valor else None


def _partido(valor: str | None) -> str | None:
    return valor.strip().upper() if valor and valor.strip() else None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Estou de Olho — API",
        description=(
            "Dinheiro público aberto: cota parlamentar, emendas e Emenda Pix, prefeituras e câmaras, contratos, "
            "contas municipais, eleitos e sinais de alerta. Limite: 240 consultas por minuto por IP (40 na busca); "
            "para volume, baixe os arquivos em /dados/."
        ),
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=settings.cors_origin_regex,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.middleware("http")(limitar_e_cachear)

    # ------------------------------------------------------------------ deputados / CEAP

    @app.get("/api/deputados", response_model=list[DeputadoOut], tags=["deputados"])
    def listar_deputados(db: Db, uf: Uf = None, partido: Partido = None) -> object:
        return queries.listar_deputados(db, _uf(uf), _partido(partido))

    @app.get("/api/filtros", response_model=FiltrosOut, tags=["deputados"])
    def filtros(db: Db) -> object:
        return queries.filtros_disponiveis(db)

    @app.get("/api/gastos/resumo", response_model=ResumoGastosOut, tags=["cota parlamentar"])
    def resumo(db: Db, ano: Ano = None, uf: Uf = None, partido: Partido = None) -> object:
        return queries.resumo_gastos(db, ano, _uf(uf), _partido(partido))

    @app.get("/api/gastos/ranking", response_model=list[RankingItem], tags=["cota parlamentar"])
    def ranking(
        db: Db,
        ano: Ano = None,
        uf: Uf = None,
        partido: Partido = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
        ordem: Annotated[
            Literal["total", "relativo"],
            Query(description="total = maior gasto; relativo = mais acima da média do próprio estado"),
        ] = "total",
    ) -> object:
        return queries.ranking_gastos(db, ano, _uf(uf), _partido(partido), limit, ordem)

    @app.get("/api/gastos/por-tipo", response_model=list[TipoDespesaItem], tags=["cota parlamentar"])
    def por_tipo(db: Db, ano: Ano = None, uf: Uf = None, partido: Partido = None) -> object:
        return queries.gastos_por_tipo(db, ano, _uf(uf), _partido(partido))

    @app.get(
        "/api/deputados/{deputado_id}/gastos", response_model=GastosDeputadoOut, tags=["cota parlamentar"]
    )
    def gastos_deputado(
        db: Db,
        deputado_id: DeputadoId,
        ano: Ano = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Offset = 0,
    ) -> object:
        dados = queries.gastos_deputado(db, deputado_id, ano, limit, offset)
        if dados is None:
            raise HTTPException(status_code=404, detail="Deputado não encontrado")
        return dados

    @app.get("/api/despesas", response_model=Pagina[DespesaComDeputadoOut], tags=["cota parlamentar"])
    def despesas(
        db: Db,
        ano: Ano = None,
        uf: Uf = None,
        partido: Partido = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Offset = 0,
    ) -> object:
        total, itens = queries.ultimas_despesas(db, ano, _uf(uf), _partido(partido), limit, offset)
        return {"total": total, "itens": itens}

    # ------------------------------------------------------------------ emendas

    @app.get("/api/municipios", response_model=list[MunicipioOut], tags=["emendas"])
    def municipios(
        db: Db,
        busca: Annotated[str | None, Query(max_length=120, description="Parte do nome")] = None,
        uf: Uf = None,
        ano: Ano = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> object:
        return queries.buscar_municipios(db, busca, _uf(uf), ano, limit)

    @app.get(
        "/api/municipios/{uf}/{municipio}/emendas", response_model=EmendasMunicipioOut, tags=["emendas"]
    )
    def emendas_municipio(db: Db, uf: UfPath, municipio: MunicipioPath, ano: Ano = None) -> object:
        dados = queries.emendas_municipio(db, uf.upper(), municipio, ano)
        if dados is None:
            raise HTTPException(status_code=404, detail="Nenhum pagamento de emenda para este município")
        return {**dados, **queries.extras_municipio(db, uf.upper(), municipio, ano)}

    @app.get(
        "/api/municipios/{uf}/{municipio}/comparacao", response_model=ComparacaoRegiaoOut, tags=["emendas"]
    )
    def comparacao_municipio(db: Db, uf: UfPath, municipio: MunicipioPath, ano: Ano = None) -> object:
        dados = queries.comparacao_regiao(db, uf.upper(), municipio, ano)
        if dados is None:
            raise HTTPException(status_code=404, detail="Município não encontrado no IBGE")
        return dados

    @app.get("/api/municipios/{uf}/{municipio}/cota", response_model=CotaNaCidadeOut, tags=["cota parlamentar"])
    def cota_no_municipio(db: Db, uf: UfPath, municipio: MunicipioPath, ano: Ano = None) -> object:
        dados = queries.cota_na_cidade(db, uf.upper(), municipio, ano)
        if dados is None:
            raise HTTPException(status_code=404, detail="Município não encontrado no IBGE")
        return dados

    @app.get("/api/municipios/{uf}/{municipio}/feed.xml", tags=["emendas"], response_class=Response)
    def feed_municipio(db: Db, uf: UfPath, municipio: MunicipioPath) -> Response:
        """Feed Atom com os últimos pagamentos de emenda do município."""
        _, itens = queries.pagamentos_municipio(db, uf.upper(), municipio, None, 50, 0)
        return Response(
            content=_montar_feed(uf.upper(), municipio, itens, settings.site_url),
            media_type="application/atom+xml; charset=utf-8",
        )

    @app.get(
        "/api/municipios/{uf}/{municipio}/pagamentos",
        response_model=Pagina[PagamentoEmendaOut],
        tags=["emendas"],
    )
    def pagamentos_municipio(
        db: Db,
        uf: UfPath,
        municipio: MunicipioPath,
        ano: Ano = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Offset = 0,
    ) -> object:
        total, itens = queries.pagamentos_municipio(db, uf.upper(), municipio, ano, limit, offset)
        return {"total": total, "itens": itens}

    @app.get(
        "/api/deputados/{deputado_id}/emendas", response_model=EmendasDeputadoOut, tags=["emendas"]
    )
    def emendas_deputado(db: Db, deputado_id: DeputadoId, ano: Ano = None) -> object:
        dados = queries.emendas_deputado(db, deputado_id, ano)
        if dados is None:
            raise HTTPException(status_code=404, detail="Deputado não encontrado")
        return dados

    # ------------------------------------------------------------------ alertas / fornecedores

    @app.get("/api/alertas", response_model=Pagina[AlertaOut], tags=["alertas"])
    def alertas(
        db: Db,
        tipo: Annotated[str | None, Query(max_length=40)] = None,
        gravidade: Annotated[Literal["alta", "media"] | None, Query()] = None,
        ano: Ano = None,
        uf: Uf = None,
        partido: Partido = None,
        deputado_id: Annotated[int | None, Query(ge=1)] = None,
        cnpj: Annotated[str | None, Query(pattern=r"^\d{14}$")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Offset = 0,
        esfera: Esfera = None,
        deputado_estadual_id: Annotated[int | None, Query(ge=1)] = None,
        orgao_id: Annotated[int | None, Query(ge=1, description="Órgão municipal (TCE-PE)")] = None,
        senador_id: Annotated[int | None, Query(ge=1)] = None,
        municipio_ibge: Annotated[str | None, Query(pattern=r"^\d{7}$")] = None,
        min_prioridade: Annotated[int | None, Query(ge=0, le=100, description="só alertas com nota ≥ este valor")] = None,
    ) -> object:
        total, itens = queries.listar_alertas(
            db, tipo, gravidade, ano, _uf(uf), _partido(partido), deputado_id, cnpj, limit, offset,
            esfera, deputado_estadual_id, orgao_id, senador_id, municipio_ibge, min_prioridade,
        )
        return {"total": total, "itens": itens}

    @app.get("/api/alertas/resumo", response_model=ResumoAlertasOut, tags=["alertas"])
    def resumo_alertas(
        db: Db, ano: Ano = None, uf: Uf = None, partido: Partido = None, esfera: Esfera = None
    ) -> object:
        return queries.resumo_alertas(db, ano, _uf(uf), _partido(partido), esfera)

    @app.get("/api/alertas/tipos", tags=["alertas"])
    def tipos_alerta() -> dict[str, str]:
        return TITULOS_TIPO

    @app.get(
        "/api/fornecedores/{cnpj}/documentos", response_model=Pagina[DocumentoFornecedorOut], tags=["fornecedores"]
    )
    def documentos_fornecedor(
        db: Db,
        cnpj: Annotated[str, Path(pattern=r"^\d{14}$")],
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Offset = 0,
    ) -> object:
        total, itens = queries.documentos_fornecedor(db, cnpj, limit, offset)
        return {"total": total, "itens": itens}

    @app.get("/api/fornecedores/{cnpj}", response_model=FornecedorOut, tags=["fornecedores"])
    def fornecedor(db: Db, cnpj: Annotated[str, Path(pattern=r"^\d{14}$")]) -> object:
        dados = queries.detalhe_fornecedor(db, cnpj)
        if dados is None:
            raise HTTPException(status_code=404, detail="Fornecedor não encontrado nas despesas da cota")
        return dados

    # ------------------------------------------------------------------ deputados estaduais (ALEPE)

    @app.get("/api/estaduais", response_model=list[EstadualListaItem], tags=["deputados estaduais"])
    def estaduais(
        db: Db,
        ano: Ano = None,
        partido: Partido = None,
        busca: Annotated[str | None, Query(max_length=100)] = None,
    ) -> object:
        return queries.listar_estaduais(db, ano, _partido(partido), busca)

    @app.get("/api/estaduais/resumo", response_model=ResumoEstaduaisOut, tags=["deputados estaduais"])
    def resumo_estaduais(db: Db, ano: Ano = None) -> object:
        return queries.resumo_estaduais(db, ano)

    @app.get("/api/estaduais/{deputado_id}", response_model=DetalheEstadualOut, tags=["deputados estaduais"])
    def estadual(
        db: Db,
        deputado_id: Annotated[int, Path(ge=1)],
        ano: Ano = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Offset = 0,
    ) -> object:
        dados = queries.detalhe_estadual(db, deputado_id, ano, limit, offset)
        if dados is None:
            raise HTTPException(status_code=404, detail="Deputado estadual não encontrado")
        return dados

    # ------------------------------------------------------------------ senadores

    @app.get("/api/senadores", response_model=list[SenadorListaItem], tags=["senadores"])
    def senadores(
        db: Db, ano: Ano = None, uf: Uf = None, busca: Annotated[str | None, Query(max_length=100)] = None
    ) -> object:
        return queries.listar_senadores(db, ano, _uf(uf), busca)

    @app.get("/api/senadores/resumo", response_model=ResumoEstaduaisOut, tags=["senadores"])
    def resumo_senado(db: Db, ano: Ano = None) -> object:
        return queries.resumo_senado(db, ano)

    @app.get("/api/senadores/{senador_id}", response_model=DetalheSenadorOut, tags=["senadores"])
    def senador(
        db: Db,
        senador_id: Annotated[int, Path(ge=1)],
        ano: Ano = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Offset = 0,
    ) -> object:
        dados = queries.detalhe_senador(db, senador_id, ano, limit, offset)
        if dados is None:
            raise HTTPException(status_code=404, detail="Senador não encontrado")
        return dados

    # ------------------------------------------------------------------ cidade: contratos, contas, eleitos

    @app.get("/api/municipios/{uf}/{municipio}/contratos", response_model=ContratosMunicipioOut, tags=["municípios"])
    def contratos(db: Db, uf: UfPath, municipio: MunicipioPath, ano: Ano = None) -> object:
        dados = queries.contratos_municipio(db, uf.upper(), municipio, ano)
        if dados is None:
            raise HTTPException(status_code=404, detail="Município não encontrado no IBGE")
        return dados

    @app.get(
        "/api/municipios/{uf}/{municipio}/contratos/lista", response_model=Pagina[ContratoOut], tags=["municípios"]
    )
    def lista_contratos(
        db: Db,
        uf: UfPath,
        municipio: MunicipioPath,
        ano: Ano = None,
        busca: Annotated[str | None, Query(max_length=100)] = None,
        orgao_cnpj: Annotated[str | None, Query(pattern=r"^\d{14}$")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Offset = 0,
    ) -> object:
        total, itens = queries.lista_contratos(db, uf.upper(), municipio, ano, busca, orgao_cnpj, limit, offset)
        return {"total": total, "itens": itens}

    @app.get("/api/municipios/{uf}/{municipio}/contas", response_model=ContasMunicipioOut, tags=["municípios"])
    def contas(db: Db, uf: UfPath, municipio: MunicipioPath, ano: Ano = None) -> object:
        dados = queries.contas_municipio(db, uf.upper(), municipio, ano)
        if dados is None:
            raise HTTPException(status_code=404, detail="Município não encontrado no IBGE")
        return dados

    @app.get("/api/municipios/{uf}/{municipio}/eleitos", response_model=EleitosOut, tags=["municípios"])
    def eleitos(
        db: Db, uf: UfPath, municipio: MunicipioPath, ano: Annotated[int, Query(ge=2000, le=2100)] = 2024
    ) -> object:
        dados = queries.eleitos_municipio(db, uf.upper(), municipio, ano)
        if dados is None:
            raise HTTPException(status_code=404, detail="Município não encontrado no IBGE")
        return dados

    # ------------------------------------------------------------------ municípios (TCE-PE)

    @app.get("/api/municipios/{uf}/{municipio}/camara", response_model=CamaraOut, tags=["municípios"])
    def camara(db: Db, uf: UfPath, municipio: MunicipioPath, ano: Ano = None) -> object:
        dados = queries.camara_municipio(db, uf.upper(), municipio, ano)
        if dados is None:
            raise HTTPException(status_code=404, detail="Sem dados da câmara municipal para este município")
        return dados

    @app.get("/api/municipios/{uf}/{municipio}/prefeitura", response_model=PrefeituraOut, tags=["municípios"])
    def prefeitura(db: Db, uf: UfPath, municipio: MunicipioPath, ano: Ano = None) -> object:
        dados = queries.prefeitura_municipio(db, uf.upper(), municipio, ano)
        if dados is None:
            raise HTTPException(status_code=404, detail="Sem dados da prefeitura para este município")
        return dados

    @app.get("/api/municipios/{uf}/{municipio}/empenhos", response_model=Pagina[EmpenhoOut], tags=["municípios"])
    def empenhos(
        db: Db,
        uf: UfPath,
        municipio: MunicipioPath,
        ano: Ano = None,
        orgao_id: Annotated[int | None, Query(ge=1)] = None,
        busca: Annotated[str | None, Query(max_length=100)] = None,
        fonte: Annotated[Literal["pix", "pix_estadual"] | None, Query(description="só gastos com Emenda Pix")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Offset = 0,
    ) -> object:
        total, itens = queries.empenhos_municipio(
            db, uf.upper(), municipio, ano, orgao_id, busca, limit, offset, fonte
        )
        return {"total": total, "itens": itens}

    @app.get("/api/municipios/{uf}/{municipio}/pessoal", response_model=PessoalMunicipioOut, tags=["municípios"])
    def pessoal(db: Db, uf: UfPath, municipio: MunicipioPath, ano: Ano = None) -> object:
        """Pessoal da prefeitura: quadro (TCE-PE), custo da folha, pessoas físicas pagas e doadores nomeados."""
        dados = queries.pessoal_municipio(db, uf.upper(), municipio, ano)
        if dados is None:
            raise HTTPException(status_code=404, detail="Sem dados de pessoal para este município")
        return dados

    @app.get("/api/municipios/{uf}/{municipio}/pessoal/lista", response_model=Pagina[ServidorOut], tags=["municípios"])
    def pessoal_lista(
        db: Db,
        uf: UfPath,
        municipio: MunicipioPath,
        busca: Annotated[str | None, Query(max_length=100)] = None,
        vinculo: Annotated[str | None, Query(max_length=100)] = None,
        desde: Annotated[int | None, Query(ge=1950, le=2100, description="admitidos a partir deste ano")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Offset = 0,
    ) -> object:
        total, itens = queries.lista_pessoal(db, uf.upper(), municipio, busca, vinculo, desde, limit, offset)
        return {"total": total, "itens": itens}

    @app.get("/api/municipios/{uf}/{municipio}/emenda-pix", response_model=EmendaPixOut, tags=["municípios"])
    def emenda_pix(db: Db, uf: UfPath, municipio: MunicipioPath) -> object:
        """Emenda Pix: o que chegou (Transferegov), o plano declarado e o gasto informado ao tribunal de contas."""
        dados = queries.emenda_pix_municipio(db, uf.upper(), municipio)
        if dados is None:
            raise HTTPException(status_code=404, detail="Sem Emenda Pix registrada para este município")
        return dados

    # ------------------------------------------------------------------ contestações

    def _ip(request: Request) -> str | None:
        encaminhado = request.headers.get("x-forwarded-for", "")
        return encaminhado.split(",")[0].strip() or (request.client.host if request.client else None)

    def _admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
        token = get_settings().admin_token
        if token is None:
            raise HTTPException(status_code=404, detail="Área administrativa desligada")
        if not x_admin_token or not secrets.compare_digest(x_admin_token, token.get_secret_value()):
            raise HTTPException(status_code=401, detail="Token inválido")

    @app.post("/api/contestacoes", response_model=ContestacaoRecebida, status_code=201, tags=["contestações"])
    def contestar(db: Db, dados: ContestacaoIn, request: Request) -> object:
        """Aponta erro, publica resposta de quem foi citado ou faz pedido sobre dados pessoais (LGPD)."""
        from civic import contestacoes

        if dados.site:  # campo invisível: só robô preenche
            return {"protocolo": "recebido", "status": "recebida"}
        try:
            item = contestacoes.registrar(db, dados.model_dump(), _ip(request), get_settings())
        except contestacoes.LimiteExcedido:
            raise HTTPException(status_code=429, detail="Muitos pedidos hoje. Tente amanhã ou escreva para o projeto.")
        return item

    @app.get("/api/contestacoes", response_model=Pagina[ContestacaoPublica], tags=["contestações"])
    def contestacoes_publicas(
        db: Db,
        url: Annotated[str | None, Query(max_length=500)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Offset = 0,
    ) -> object:
        """Correções e respostas já analisadas (sem o contato de quem enviou)."""
        from civic import contestacoes

        total, itens = contestacoes.publicas(db, url, limit, offset)
        return {"total": total, "itens": itens}

    @app.get("/api/admin/contestacoes", response_model=Pagina[ContestacaoAdmin], tags=["contestações"],
             dependencies=[Depends(_admin)])
    def contestacoes_admin(
        db: Db,
        status: Annotated[str | None, Query(max_length=20)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Offset = 0,
    ) -> object:
        from civic import contestacoes

        total, itens = contestacoes.listar_admin(db, status, limit, offset)
        return {"total": total, "itens": itens}

    @app.patch("/api/admin/contestacoes/{id_}", response_model=ContestacaoAdmin, tags=["contestações"],
               dependencies=[Depends(_admin)])
    def contestacao_atualizar(db: Db, id_: Annotated[int, Path(ge=1)], dados: ContestacaoAtualizacao) -> object:
        from civic import contestacoes

        item = contestacoes.atualizar(db, id_, dados.status, dados.resposta_publica)
        if item is None:
            raise HTTPException(status_code=404, detail="Contestação não encontrada")
        return item

    # ------------------------------------------------------------------ busca

    @app.get("/api/busca", response_model=BuscaOut, tags=["busca"])
    def busca(
        db: Db,
        q: Annotated[str, Query(min_length=1, max_length=120, description="nome de pessoa ou empresa, ou CNPJ")],
        limit: Annotated[int, Query(ge=1, le=100)] = 30,
        uf: Uf = None,
        municipio: Annotated[str | None, Query(max_length=120, description="só dentro desta cidade (com uf)")] = None,
    ) -> object:
        """Onde um nome aparece: fornecedor, parlamentar, servidor, sócio, candidato, doador ou credor."""
        from civic.busca import buscar

        cidade = f"{municipio}/{uf.upper()}" if municipio and uf else None
        return buscar(db, q, limit, cidade)

    # ------------------------------------------------------------------ saúde

    @app.get("/health", response_model=HealthOut, tags=["infra"])
    def health(db: Db) -> object:
        fontes = queries.ultimo_sync(db)
        return {"status": "ok", "ultimo_sync": max(fontes.values(), default=None), "fontes": fontes}

    return app


def _montar_feed(uf: str, municipio: str, itens: list[dict[str, object]], site_url: str) -> bytes:
    """Atom com um item por pagamento (id estável: emenda + mês + favorecido + valor)."""
    ns = "http://www.w3.org/2005/Atom"
    ET.register_namespace("", ns)
    link_cidade = f"{site_url}/cidade/{uf}/{quote(municipio)}"
    feed = ET.Element(f"{{{ns}}}feed")
    ET.SubElement(feed, f"{{{ns}}}title").text = f"Emendas pagas em {municipio.title()} – {uf}"
    ET.SubElement(feed, f"{{{ns}}}id").text = link_cidade
    ET.SubElement(feed, f"{{{ns}}}link", href=link_cidade)
    ET.SubElement(feed, f"{{{ns}}}updated").text = datetime.now(timezone.utc).isoformat(timespec="seconds")
    autor = ET.SubElement(feed, f"{{{ns}}}author")
    ET.SubElement(autor, f"{{{ns}}}name").text = "Estou de Olho"
    for p in itens:
        entrada = ET.SubElement(feed, f"{{{ns}}}entry")
        valor = formatar_brl(int(p["valor_recebido_centavos"]))  # type: ignore[call-overload]
        autor_emenda = str(p["nome_autor"] or "Autor não informado").title()
        ET.SubElement(entrada, f"{{{ns}}}title").text = f"{valor} de {autor_emenda} para {str(p['favorecido'] or '').title()}"
        chave = f"{p['codigo_emenda']}-{p['ano']}{int(p['mes']):02d}-{p['codigo_favorecido']}-{p['valor_recebido_centavos']}"  # type: ignore[call-overload]
        ET.SubElement(entrada, f"{{{ns}}}id").text = f"{link_cidade}#{chave}"
        ET.SubElement(entrada, f"{{{ns}}}link", href=link_cidade)
        ET.SubElement(entrada, f"{{{ns}}}updated").text = f"{p['ano']}-{int(p['mes']):02d}-01T00:00:00Z"  # type: ignore[call-overload]
        resumo = " · ".join(str(x) for x in (p.get("tipo_emenda"), p.get("objeto") or p.get("acao")) if x)
        ET.SubElement(entrada, f"{{{ns}}}summary").text = resumo or valor
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)


app = create_app()
