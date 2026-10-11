"""Modelos Pydantic de resposta da API.

Valores monetários chegam das consultas como inteiros em centavos e saem como
`Decimal` com 2 casas (serializado em JSON como string, ex.: "1234.56", para
não perder precisão).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, field_serializer

T = TypeVar("T")

DUAS_CASAS = Decimal("0.01")


def centavos_para_reais(centavos: int) -> Decimal:
    """1234 -> Decimal('12.34')."""
    return (Decimal(centavos) / 100).quantize(DUAS_CASAS)


def _de_centavos(valor: Any) -> Any:
    """Inteiros são centavos (contrato interno com `queries.py`); o resto passa direto."""
    if valor is None:
        return Decimal("0.00")
    if isinstance(valor, int) and not isinstance(valor, bool):
        return centavos_para_reais(valor)
    return valor


Reais = Annotated[Decimal, BeforeValidator(_de_centavos)]


def _campo_reais(nome: str) -> Any:
    """Campo em reais que aceita tanto `nome` quanto `nome_centavos` na entrada."""
    return Field(validation_alias=AliasChoices(nome, f"{nome}_centavos"))


def mascarar_cpf(doc: str | None) -> str | None:
    """CPF de pessoa física sai parcialmente oculto (LGPD): 12345678909 -> ***.456.789-**."""
    if doc and len(doc) == 11 and doc.isdigit():
        return f"***.{doc[3:6]}.{doc[6:9]}-**"
    return doc


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Pagina(Schema, Generic[T]):
    total: int
    itens: list[T]


# --------------------------------------------------------------------------- deputados / CEAP


class DeputadoOut(Schema):
    id: int
    nome: str
    sigla_partido: str | None
    sigla_uf: str | None
    url_foto: str | None


class FiltrosOut(Schema):
    ufs: list[str]
    partidos: list[str]
    anos: list[int]
    anos_emendas: list[int]


class ResumoGastosOut(Schema):
    total_liquido: Reais
    qtd_deputados: int
    qtd_despesas: int


class RankingItem(Schema):
    deputado: DeputadoOut
    total_liquido: Reais
    qtd_despesas: int
    media_uf: Reais | None = None
    indice_uf: float | None = None


class TipoDespesaItem(Schema):
    tipo_despesa: str
    total_liquido: Reais
    qtd_despesas: int


class DespesaOut(Schema):
    id: int
    ano: int
    mes: int
    data_documento: date | None
    tipo_despesa: str
    tipo_documento: str | None
    num_documento: str | None
    fornecedor: str | None
    cnpj_cpf: str | None
    tipo_pessoa: str | None
    valor_documento: Reais = _campo_reais("valor_documento")
    valor_glosa: Reais = _campo_reais("valor_glosa")
    valor_liquido: Reais = _campo_reais("valor_liquido")
    url_documento: str | None
    parcela: int

    @field_serializer("cnpj_cpf")
    def _mascarar_cpf(self, valor: str | None) -> str | None:
        return mascarar_cpf(valor)


class DespesaComDeputadoOut(DespesaOut):
    deputado: DeputadoOut


class SerieMensalItem(Schema):
    ano: int
    mes: int
    total_liquido: Reais


class GastosDeputadoOut(Schema):
    deputado: DeputadoOut
    ano: int | None
    total_liquido: Reais
    qtd_despesas: int
    serie_mensal: list[SerieMensalItem]
    despesas: Pagina[DespesaOut]


class HealthOut(Schema):
    status: str
    ultimo_sync: datetime | None
    fontes: dict[str, datetime]


# --------------------------------------------------------------------------- emendas


class MunicipioOut(Schema):
    sigla_uf: str
    municipio: str
    total_recebido: Reais
    qtd_pagamentos: int


class AutorEmendaItem(Schema):
    nome_autor: str
    deputado: DeputadoOut | None
    total_recebido: Reais
    qtd_pagamentos: int


class FavorecidoItem(Schema):
    favorecido: str
    codigo_favorecido: str | None
    tipo_favorecido: str | None
    total_recebido: Reais
    qtd_pagamentos: int


class FuncaoItem(Schema):
    funcao: str
    total: Reais


class AcaoItem(Schema):
    acao: str
    total: Reais


class SerieEmendasItem(Schema):
    ano: int
    mes: int
    total_recebido: Reais


class EmendasMunicipioOut(Schema):
    sigla_uf: str
    municipio: str
    ano: int | None
    total_recebido: Reais
    qtd_pagamentos: int
    qtd_autores: int
    por_autor: list[AutorEmendaItem]
    por_favorecido: list[FavorecidoItem]
    por_funcao: list[FuncaoItem]
    por_acao: list[AcaoItem]
    serie_mensal: list[SerieEmendasItem]
    codigo_ibge: str | None
    populacao: int | None
    ano_populacao: int | None
    regiao_imediata: str | None
    por_habitante: Reais | None
    total_pix: Reais


class PagamentoEmendaOut(Schema):
    id: int
    codigo_emenda: str | None
    ano: int
    mes: int
    tipo_emenda: str | None
    nome_autor: str | None
    deputado_id: int | None
    favorecido: str | None
    tipo_favorecido: str | None
    valor_recebido: Reais = _campo_reais("valor_recebido")
    acao: str | None = None
    objeto: str | None = None


class DestinoEmendaItem(Schema):
    sigla_uf: str | None
    municipio: str | None
    total_recebido: Reais
    qtd_pagamentos: int


class EmendasDeputadoOut(Schema):
    deputado: DeputadoOut
    ano: int | None
    qtd_emendas: int
    total_empenhado: Reais
    total_pago: Reais
    total_recebido_municipios: Reais
    por_funcao: list[FuncaoItem]
    por_destino: list[DestinoEmendaItem]


class ComparacaoMunicipio(Schema):
    codigo_ibge: str
    municipio: str
    sigla_uf: str
    populacao: int | None
    total_recebido: Reais
    por_habitante: Reais | None
    atual: bool


class ComparacaoRegiaoOut(Schema):
    regiao_imediata: str | None
    ano: int | None
    municipios: list[ComparacaoMunicipio]


class GastoDeputadoItem(Schema):
    deputado: DeputadoOut
    total_liquido: Reais
    qtd_despesas: int


class FornecedorNaCidade(Schema):
    cnpj: str
    nome: str | None
    total_liquido: Reais
    qtd_deputados: int


class CotaNaCidadeOut(Schema):
    base_cnpj_carregada: bool
    total_liquido: Reais
    qtd_despesas: int
    por_deputado: list[GastoDeputadoItem]
    por_fornecedor: list[FornecedorNaCidade]


# --------------------------------------------------------------------------- alertas / fornecedores


class DeputadoEstadualOut(Schema):
    id: int
    nome: str
    sigla_partido: str | None
    url_foto: str | None
    em_exercicio: bool


class OrgaoOut(Schema):
    id: int
    nome: str
    natureza: str | None
    fonte: str | None = None
    municipio: str
    sigla_uf: str


class SenadorOut(Schema):
    id: int
    nome: str
    sigla_partido: str | None
    sigla_uf: str | None
    url_foto: str | None
    em_exercicio: bool


class MunicipioRefOut(Schema):
    codigo_ibge: str
    nome: str
    sigla_uf: str


class OrgaoContratanteOut(Schema):
    cnpj: str
    nome: str


class AlertaOut(Schema):
    id: int
    tipo: str
    gravidade: str
    prioridade: int = 0
    esfera: str
    deputado: DeputadoOut | None
    senador: SenadorOut | None
    deputado_estadual: DeputadoEstadualOut | None
    orgao: OrgaoOut | None
    orgao_contratante: OrgaoContratanteOut | None
    municipio_ibge: str | None
    municipio: MunicipioRefOut | None = None
    cnpj: str | None
    ano: int | None
    valor: Reais
    titulo: str
    descricao: str


class AlertasPorTipo(Schema):
    tipo: str
    alta: int
    media: int


class ResumoAlertasOut(Schema):
    total: int
    altas: int
    qtd_deputados: int
    por_tipo: list[AlertasPorTipo]
    por_esfera: dict[str, int]


class CadastroFornecedorOut(Schema):
    razao_social: str | None
    nome_fantasia: str | None
    matriz: bool | None
    situacao_cadastral: str | None
    data_situacao_cadastral: date | None
    data_inicio_atividade: date | None
    cnae_principal: str | None
    natureza_juridica: str | None
    capital_social: Reais | None = _campo_reais("capital_social")
    porte: str | None
    opcao_simples: bool | None
    opcao_mei: bool | None
    data_opcao_mei: date | None
    data_exclusao_mei: date | None
    sigla_uf: str | None
    municipio: str | None
    codigo_municipio_ibge: str | None
    bairro: str | None
    referencia: str


class AnoValorItem(Schema):
    ano: int
    total: Reais


class GastoEstadualItem(Schema):
    deputado: DeputadoEstadualOut
    total_liquido: Reais
    qtd_despesas: int


class GastoOrgaoItem(Schema):
    orgao: OrgaoOut
    total_pago: Reais
    qtd_empenhos: int


class FornecedorOut(Schema):
    cnpj: str
    nome: str | None
    cadastro: CadastroFornecedorOut | None
    total_recebido: Reais
    total_cota: Reais
    total_estadual: Reais
    total_municipal: Reais
    qtd_despesas: int
    primeira_nota: date | None
    ultima_nota: date | None
    por_deputado: list[GastoDeputadoItem]
    por_deputado_estadual: list[GastoEstadualItem]
    por_orgao: list[GastoOrgaoItem]
    por_ano: list[AnoValorItem]


# --------------------------------------------------------------------------- deputados estaduais


class EstadualListaItem(Schema):
    deputado: DeputadoEstadualOut
    total: Reais
    qtd_notas: int
    meses: int


class RubricaItem(Schema):
    rubrica: str
    total: Reais


class ResumoEstaduaisOut(Schema):
    total: Reais
    qtd_notas: int
    qtd_deputados: int
    por_rubrica: list[RubricaItem]
    anos: list[int]


class NotaVerbaOut(Schema):
    id: int
    docid: str
    ano: int
    mes: int
    rubrica_nome: str | None
    data: date | None
    cnpj_cpf: str | None
    tipo_pessoa: str | None
    fornecedor: str | None
    valor: Reais = _campo_reais("valor")

    @field_serializer("cnpj_cpf")
    def _mascarar_cpf(self, valor: str | None) -> str | None:
        return mascarar_cpf(valor)


class SerieValorItem(Schema):
    ano: int
    mes: int
    total: Reais


class FornecedorEstadualItem(Schema):
    cnpj: str | None
    nome: str | None
    total: Reais
    qtd_notas: int

    @field_serializer("cnpj")
    def _mascarar_cpf(self, valor: str | None) -> str | None:
        return mascarar_cpf(valor)


class DetalheEstadualOut(Schema):
    deputado: DeputadoEstadualOut
    ano: int | None
    total: Reais
    qtd_notas: int
    por_rubrica: list[RubricaItem]
    serie_mensal: list[SerieValorItem]
    por_fornecedor: list[FornecedorEstadualItem]
    notas: Pagina[NotaVerbaOut]


# --------------------------------------------------------------------------- municípios (TCE-PE)


class NomeTotalItem(Schema):
    nome: str
    total_pago: Reais


class NomeQtdItem(Schema):
    nome: str
    qtd: int


class FornecedorMunicipalItem(Schema):
    nome: str
    cpf_cnpj: str | None
    tipo_pessoa: str | None
    total_pago: Reais
    qtd_empenhos: int


class VereadorItem(Schema):
    nome: str
    mandato_atual: bool
    total_recebido: Reais
    qtd_pagamentos: int
    por_tipo: list[NomeTotalItem]


class CamaraOut(Schema):
    orgao: OrgaoOut
    ano: int | None
    inicio_mandato: int
    total_pago: Reais
    qtd_empenhos: int
    vereadores: list[VereadorItem]
    qtd_vereadores_mandato: int
    nomeados_no_mandato: int
    por_vinculo: list[NomeQtdItem]
    comissionados_por_cargo: list[NomeQtdItem]
    por_elemento: list[NomeTotalItem]
    fornecedores: list[FornecedorMunicipalItem]
    sem_credor_identificado: Reais


class OrgaoTotalItem(Schema):
    orgao: OrgaoOut
    total_pago: Reais


class PrefeituraOut(Schema):
    ano: int | None
    anos: list[int]
    total_pago: Reais
    total_empenhado: Reais
    qtd_empenhos: int
    por_orgao: list[OrgaoTotalItem]
    por_funcao: list[NomeTotalItem]
    por_elemento: list[NomeTotalItem]
    fornecedores: list[FornecedorMunicipalItem]
    sem_credor_identificado: Reais


class EmpenhoOut(Schema):
    id: int
    orgao: str
    ano: int
    mes: int | None
    data_empenho: date | None
    numero_empenho: str | None
    fornecedor: str | None
    cpf_cnpj: str | None
    tipo_pessoa: str | None
    elemento_despesa: str | None
    funcao: str | None
    historico: str | None
    fonte_recurso: str | None = None
    categoria_economica: str | None = None
    qtd_empenhos: int = 1
    valor_empenhado: Reais = _campo_reais("valor_empenhado")
    valor_pago: Reais = _campo_reais("valor_pago")


class MesAnoOut(Schema):
    ano: int
    mes: int | None


class VinculoPessoalItem(Schema):
    nome: str
    vinculos: int
    pessoas: int
    no_mandato: int


class QtdNomeItem(Schema):
    nome: str
    qtd: int


class AdmissoesAnoItem(Schema):
    ano: int
    por_vinculo: list[QtdNomeItem]


class CargoPessoalItem(Schema):
    cargo: str
    vinculo: str
    pessoas: int


class NomeTotalCategoria(Schema):
    nome: str
    total: Reais


class FolhaAnoItem(Schema):
    ano: int
    total: Reais
    por_categoria: list[NomeTotalCategoria]


class FolhaMesItem(Schema):
    mes: int
    total: Reais
    por_categoria: list[NomeTotalCategoria]


class ServidorResumo(Schema):
    cargo: str | None
    vinculo: str | None
    data_admissao: date | None


class PrestadorPfItem(Schema):
    nome: str
    cpf: str | None
    total_pago: Reais
    qtd_empenhos: int
    tipo: str
    exemplo: str | None
    servidor: ServidorResumo | None


class DoadorNomeadoItem(Schema):
    nome: str
    cargo: str | None
    vinculo: str | None
    data_admissao: date | None
    doado: Reais
    candidato: str
    cargo_candidato: str | None
    partido: str | None
    eleito: bool


class PessoalMunicipioOut(Schema):
    ano: int | None
    anos: list[int]
    inicio_mandato: int
    remessa: MesAnoOut | None
    qtd_vinculos: int
    qtd_pessoas: int
    por_vinculo: list[VinculoPessoalItem]
    admissoes_por_ano: list[AdmissoesAnoItem]
    cargos: list[CargoPessoalItem]
    categorias_folha: list[str]
    folha_pela_data_do_pagamento: bool = False
    folha_por_ano: list[FolhaAnoItem]
    folha_por_mes: list[FolhaMesItem]
    prestadores_total: Reais
    prestadores_qtd: int
    prestadores: list[PrestadorPfItem]
    doadores_nomeados: list[DoadorNomeadoItem]


class ServidorOut(Schema):
    nome: str
    cargo: str | None
    vinculo: str | None
    data_admissao: date | None
    matricula: str | None
    cpf: str | None
    orgao: str


class PlanoPixOut(Schema):
    id: int
    codigo: str | None
    ano: int
    situacao: str | None
    motivo_impedimento: str | None
    parlamentar: str | None
    area: str | None
    objeto: str | None
    metas: str | None
    custeio: Reais = _campo_reais("custeio")
    investimento: Reais = _campo_reais("investimento")
    recebido: Reais = _campo_reais("recebido")
    ultimo_repasse: date | None
    relatorio_situacao: str | None
    relatorio_parecer: str | None


class AnoPixOut(Schema):
    ano: int
    recebido: Reais
    gasto: Reais
    gasto_corrente: Reais
    gasto_capital: Reais
    gasto_estadual: Reais


class EmendaPixOut(Schema):
    municipio: MunicipioRefOut
    tem_gastos: bool
    gastos_ate: MesAnoOut | None
    total_recebido: Reais
    total_gasto: Reais
    total_gasto_corrente: Reais
    total_gasto_estadual: Reais
    anos: list[AnoPixOut]
    planos: list[PlanoPixOut]
    credores: list[FornecedorMunicipalItem]


class DocumentoFornecedorOut(Schema):
    fonte: str
    fonte_nome: str
    data: date | None
    ano: int | None
    mes: int | None
    pagador: str | None
    pagador_id: str | None
    descricao: str | None
    documento: str | None
    valor: Reais
    url: str | None


# --------------------------------------------------------------------------- senadores


class SenadorListaItem(Schema):
    senador: SenadorOut
    total: Reais
    qtd_notas: int


class DetalheSenadorOut(Schema):
    senador: SenadorOut
    ano: int | None
    total: Reais
    qtd_notas: int
    por_rubrica: list[RubricaItem]
    serie_mensal: list[SerieValorItem]
    por_fornecedor: list[FornecedorEstadualItem]
    notas: Pagina[NotaVerbaOut]


# --------------------------------------------------------------------------- cidade: contratos, contas, eleitos


class OrgaoContratosItem(Schema):
    cnpj: str | None
    nome: str
    total: Reais
    qtd: int


class ContratosMunicipioOut(Schema):
    codigo_ibge: str
    ano: int | None
    anos: list[int]
    cobertura_desde: date | None
    cobertura_pct: int
    total_contratado: Reais
    qtd_contratos: int
    por_orgao: list[OrgaoContratosItem]
    por_categoria: list[NomeTotalItem]
    fornecedores: list[FornecedorMunicipalItem]


class ContratoOut(Schema):
    numero_controle: str
    orgao_cnpj: str | None
    orgao_nome: str | None
    unidade_nome: str | None
    fornecedor_ni: str | None
    fornecedor_nome: str | None
    tipo_pessoa: str | None
    objeto: str | None
    tipo_contrato: str | None
    categoria: str | None
    valor_global: Reais = _campo_reais("valor_global")
    valor_inicial: Reais = _campo_reais("valor_inicial")
    data_assinatura: date | None
    vigencia_inicio: date | None
    vigencia_fim: date | None
    url: str | None


class FuncaoContaItem(Schema):
    codigo: str
    nome: str
    pago: Reais  # no RREO (ano corrente), o liquidado até o bimestre
    empenhado: Reais
    dotacao: Reais | None = None
    por_habitante: Reais | None
    mediana_uf: Reais | None
    mediana_brasil: Reais | None


class ContasMunicipioOut(Schema):
    codigo_ibge: str
    ano: int | None
    anos: list[int]
    demonstrativo: str = "DCA"  # DCA (ano fechado) | RREO (ano corrente, parcial)
    bimestre: int | None = None
    populacao: int | None
    total_pago: Reais
    total_empenhado: Reais
    total_dotacao: Reais | None = None
    por_habitante: Reais | None
    mediana_uf_total: Reais | None = None
    mediana_brasil_total: Reais | None = None
    amostra_uf: int = 0
    amostra_brasil: int = 0
    funcoes: list[FuncaoContaItem]
    destaques: list[FuncaoContaItem]


class EleitoItem(Schema):
    nome: str
    nome_urna: str | None
    cargo: str
    sigla_partido: str | None
    resultado: str | None
    ocupacao: str | None
    instrucao: str | None
    genero: str | None
    bens: Reais


class EleitosOut(Schema):
    codigo_ibge: str
    ano: int
    qtd_candidaturas: int
    eleitos: list[EleitoItem]


# --------------------------------------------------------------------------- busca por nome


class PapelBusca(Schema):
    tipo: str
    papel: str | None
    orgao: str | None
    lugar: str | None
    ano: int | None
    valor: Reais | None = None
    url: str | None
    documento: str | None

    @field_serializer("valor")
    def _sem_zero(self, valor: Decimal | None) -> str | None:
        return None if valor is None else str(valor)


class ResultadoBusca(Schema):
    titulo: str
    tipo_pessoa: str
    documento: str | None
    homonimos_possiveis: bool = False
    papeis: list[PapelBusca]


class BuscaOut(Schema):
    termo: str
    cidade: str | None = None
    total: int
    indice_disponivel: bool
    resultados: list[ResultadoBusca]


# --------------------------------------------------------------------------- contestações


class ContestacaoIn(BaseModel):
    tipo: Literal["erro", "resposta", "privacidade"]
    url: str = Field(min_length=1, max_length=500, pattern=r"^/")
    alvo: str | None = Field(default=None, max_length=300)
    mensagem: str = Field(min_length=20, max_length=4000)
    nome: str | None = Field(default=None, max_length=200)
    contato: str | None = Field(default=None, max_length=200)
    site: str | None = Field(default=None, max_length=200, description="não preencher (anti-spam)")


class ContestacaoRecebida(Schema):
    protocolo: str
    status: str


class ContestacaoPublica(Schema):
    protocolo: str
    tipo: str
    url: str
    alvo: str | None
    mensagem: str
    status: str
    resposta_publica: str | None
    criado_em: datetime
    respondido_em: datetime | None


class ContestacaoAdmin(ContestacaoPublica):
    id: int
    nome: str | None
    contato: str | None


class ContestacaoAtualizacao(BaseModel):
    status: Literal["recebida", "em_analise", "corrigida", "mantida", "resposta_publicada"]
    resposta_publica: str | None = Field(default=None, max_length=4000)


# --------------------------------------------------------------------------- contratos do tribunal (LICON)


class TipoProcessoItem(Schema):
    nome: str
    qtd: int
    total: Reais


class FornecedorContratoItem(Schema):
    nome: str
    cpf_cnpj: str | None
    tipo_pessoa: str | None
    total: Reais
    qtd: int


class ContratosTceOut(Schema):
    ano: int | None
    anos: list[int]
    total: Reais
    qtd: int
    total_sem_disputa: Reais
    por_tipo_processo: list[TipoProcessoItem]
    fornecedores: list[FornecedorContratoItem]


class ContratoTceOut(Schema):
    id: int
    orgao: str
    ano: int
    numero: str | None
    tipo_processo: str | None
    numero_processo: str | None
    ano_processo: int | None
    objeto: str | None
    fornecedor: str | None
    cpf_cnpj: str | None
    tipo_pessoa: str | None
    valor: Reais = _campo_reais("valor")
    vigencia_inicio: date | None
    vigencia_fim: date | None
    situacao: str | None
    estagio: str | None
    url_documento: str | None
