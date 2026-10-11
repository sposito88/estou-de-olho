"""Modelos ORM (SQLAlchemy 2.0).

Todos os valores monetários são inteiros em centavos.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from civic.database import Base


class Deputado(Base):
    __tablename__ = "deputados"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    nome: Mapped[str] = mapped_column(String(200))
    # Nome sem acentos/pontuação, em maiúsculas: chave para casar autores de emendas.
    nome_normalizado: Mapped[str] = mapped_column(String(200), index=True)
    sigla_partido: Mapped[str | None] = mapped_column(String(30), index=True)
    sigla_uf: Mapped[str | None] = mapped_column(String(2), index=True)
    url_foto: Mapped[str | None] = mapped_column(String(300))
    id_legislatura: Mapped[int] = mapped_column(Integer)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime)

    despesas: Mapped[list[Despesa]] = relationship(back_populates="deputado")


class Despesa(Base):
    """Despesa da Cota Parlamentar (CEAP)."""

    __tablename__ = "despesas"
    __table_args__ = (Index("ix_despesas_ano_deputado", "ano", "deputado_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hash_unico: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    deputado_id: Mapped[int] = mapped_column(ForeignKey("deputados.id"), index=True)
    ano: Mapped[int] = mapped_column(Integer, index=True)
    mes: Mapped[int] = mapped_column(Integer, index=True)
    data_documento: Mapped[date | None] = mapped_column(Date, nullable=True)

    tipo_despesa: Mapped[str] = mapped_column(String(200), index=True)
    tipo_documento: Mapped[str | None] = mapped_column(String(60))
    num_documento: Mapped[str | None] = mapped_column(String(100))
    cod_documento: Mapped[int | None] = mapped_column(BigInteger)

    fornecedor: Mapped[str | None] = mapped_column(String(300))
    cnpj_cpf: Mapped[str | None] = mapped_column(String(14), index=True)
    tipo_pessoa: Mapped[str | None] = mapped_column(String(2))

    valor_documento_centavos: Mapped[int] = mapped_column(Integer)
    valor_glosa_centavos: Mapped[int] = mapped_column(Integer)
    valor_liquido_centavos: Mapped[int] = mapped_column(Integer)

    url_documento: Mapped[str | None] = mapped_column(String(300), nullable=True)
    parcela: Mapped[int] = mapped_column(Integer, default=0)

    deputado: Mapped[Deputado] = relationship(back_populates="despesas")


class SyncCheckpoint(Base):
    """Marca (deputado, ano) já coletados, para retomar uma coleta interrompida."""

    __tablename__ = "sync_checkpoints"

    deputado_id: Mapped[int] = mapped_column(ForeignKey("deputados.id"), primary_key=True)
    ano: Mapped[int] = mapped_column(Integer, primary_key=True)
    concluido_em: Mapped[datetime] = mapped_column(DateTime)
    fonte: Mapped[str] = mapped_column(String(20), default="api")


class SyncExecucao(Base):
    """Histórico de execuções da coleta (usado no /health)."""

    __tablename__ = "sync_execucoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fonte: Mapped[str] = mapped_column(String(30), index=True)
    concluido_em: Mapped[datetime] = mapped_column(DateTime, index=True)
    registros: Mapped[int] = mapped_column(Integer, default=0)
    detalhes: Mapped[str | None] = mapped_column(Text)


class Emenda(Base):
    """Emenda parlamentar (arquivo `EmendasParlamentares.csv` do Portal da Transparência).

    Uma emenda pode ter várias linhas (uma por localidade/ação orçamentária).
    """

    __tablename__ = "emendas"
    __table_args__ = (Index("ix_emendas_ano_deputado", "ano", "deputado_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_emenda: Mapped[str | None] = mapped_column(String(20), index=True)
    ano: Mapped[int] = mapped_column(Integer, index=True)
    tipo_emenda: Mapped[str | None] = mapped_column(String(120))
    codigo_autor: Mapped[str | None] = mapped_column(String(20))
    nome_autor: Mapped[str | None] = mapped_column(String(200))
    nome_autor_normalizado: Mapped[str | None] = mapped_column(String(200), index=True)
    deputado_id: Mapped[int | None] = mapped_column(ForeignKey("deputados.id"), index=True)
    numero_emenda: Mapped[str | None] = mapped_column(String(20))

    localidade: Mapped[str | None] = mapped_column(String(200))
    codigo_municipio_ibge: Mapped[str | None] = mapped_column(String(7), index=True)
    municipio: Mapped[str | None] = mapped_column(String(120))
    sigla_uf: Mapped[str | None] = mapped_column(String(2))

    funcao: Mapped[str | None] = mapped_column(String(120))
    subfuncao: Mapped[str | None] = mapped_column(String(200))
    acao: Mapped[str | None] = mapped_column(String(400))

    valor_empenhado_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    valor_liquidado_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    valor_pago_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    valor_rp_inscrito_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    valor_rp_cancelado_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    valor_rp_pago_centavos: Mapped[int] = mapped_column(BigInteger, default=0)


class EmendaPagamento(Base):
    """Pagamento de emenda a um favorecido (`EmendasParlamentares_PorFavorecido.csv`).

    É a única fonte que diz em qual município o dinheiro chegou de fato.
    """

    __tablename__ = "emendas_pagamentos"
    __table_args__ = (
        Index("ix_pagamentos_uf_municipio", "sigla_uf", "municipio_normalizado"),
        Index("ix_pagamentos_ano_deputado", "ano", "deputado_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_emenda: Mapped[str | None] = mapped_column(String(20), index=True)
    ano_emenda: Mapped[int | None] = mapped_column(Integer)
    ano: Mapped[int] = mapped_column(Integer, index=True)
    mes: Mapped[int] = mapped_column(Integer)
    tipo_emenda: Mapped[str | None] = mapped_column(String(120))
    codigo_autor: Mapped[str | None] = mapped_column(String(20))
    nome_autor: Mapped[str | None] = mapped_column(String(200))
    nome_autor_normalizado: Mapped[str | None] = mapped_column(String(200), index=True)
    deputado_id: Mapped[int | None] = mapped_column(ForeignKey("deputados.id"), index=True)
    numero_emenda: Mapped[str | None] = mapped_column(String(20))

    codigo_favorecido: Mapped[str | None] = mapped_column(String(20))
    favorecido: Mapped[str | None] = mapped_column(String(300))
    natureza_juridica: Mapped[str | None] = mapped_column(String(200))
    tipo_favorecido: Mapped[str | None] = mapped_column(String(60))
    sigla_uf: Mapped[str | None] = mapped_column(String(2))
    municipio: Mapped[str | None] = mapped_column(String(120))
    municipio_normalizado: Mapped[str | None] = mapped_column(String(120))

    valor_recebido_centavos: Mapped[int] = mapped_column(BigInteger, default=0)


class EmendaConvenio(Base):
    """Convênio firmado com dinheiro de emenda (`EmendasParlamentares_Convenios.csv`).

    Traz o objeto contratado ("construção de UBS...") e quem executa (convenente).
    """

    __tablename__ = "emendas_convenios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_emenda: Mapped[str | None] = mapped_column(String(20), index=True)
    localidade: Mapped[str | None] = mapped_column(String(200))
    funcao: Mapped[str | None] = mapped_column(String(120))
    tipo_emenda: Mapped[str | None] = mapped_column(String(120))
    data_publicacao: Mapped[date | None] = mapped_column(Date)
    convenente: Mapped[str | None] = mapped_column(String(300))
    objeto: Mapped[str | None] = mapped_column(Text)
    numero_convenio: Mapped[str | None] = mapped_column(String(30))
    valor_centavos: Mapped[int] = mapped_column(BigInteger, default=0)


class Municipio(Base):
    """Município do IBGE, com região imediata (usada para comparar vizinhos) e população."""

    __tablename__ = "municipios"
    __table_args__ = (Index("ix_municipios_uf_nome", "sigla_uf", "nome_normalizado"),)

    codigo_ibge: Mapped[str] = mapped_column(String(7), primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    nome_normalizado: Mapped[str] = mapped_column(String(120))
    sigla_uf: Mapped[str] = mapped_column(String(2))
    regiao_imediata_id: Mapped[str | None] = mapped_column(String(6), index=True)
    regiao_imediata_nome: Mapped[str | None] = mapped_column(String(120))
    populacao: Mapped[int | None] = mapped_column(Integer)
    ano_populacao: Mapped[int | None] = mapped_column(Integer)


class Fornecedor(Base):
    """Dados cadastrais do CNPJ (base aberta da Receita) dos fornecedores da cota."""

    __tablename__ = "fornecedores"

    cnpj: Mapped[str] = mapped_column(String(14), primary_key=True)
    razao_social: Mapped[str | None] = mapped_column(String(300))
    nome_fantasia: Mapped[str | None] = mapped_column(String(300))
    matriz: Mapped[bool | None] = mapped_column()
    situacao_cadastral: Mapped[str | None] = mapped_column(String(20))
    data_situacao_cadastral: Mapped[date | None] = mapped_column(Date)
    data_inicio_atividade: Mapped[date | None] = mapped_column(Date)
    cnae_principal: Mapped[str | None] = mapped_column(String(7))
    natureza_juridica: Mapped[str | None] = mapped_column(String(4))
    capital_social_centavos: Mapped[int | None] = mapped_column(BigInteger)
    porte: Mapped[str | None] = mapped_column(String(30))
    opcao_simples: Mapped[bool | None] = mapped_column()
    opcao_mei: Mapped[bool | None] = mapped_column()
    data_opcao_mei: Mapped[date | None] = mapped_column(Date)
    data_exclusao_mei: Mapped[date | None] = mapped_column(Date)
    sigla_uf: Mapped[str | None] = mapped_column(String(2))
    municipio: Mapped[str | None] = mapped_column(String(120))
    codigo_municipio_ibge: Mapped[str | None] = mapped_column(String(7), index=True)
    bairro: Mapped[str | None] = mapped_column(String(120))
    cep: Mapped[str | None] = mapped_column(String(8))
    referencia: Mapped[str] = mapped_column(String(7))  # mês da base da Receita, ex.: 2026-09
    atualizado_em: Mapped[datetime] = mapped_column(DateTime)


class Alerta(Base):
    """Sinal de alerta calculado a partir dos dados ("vale olhar", não acusação).

    `esfera` diz de quem é o gasto: deputado federal, senador, deputado estadual
    ou órgão municipal; só a coluna correspondente (`deputado_id`, `senador_id`,
    `deputado_estadual_id`, `unidade_gestora_id` ou `orgao_cnpj` para contratos
    do PNCP) vem preenchida.
    """

    __tablename__ = "alertas"
    __table_args__ = (Index("ix_alertas_tipo_ano", "tipo", "ano"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String(40))
    gravidade: Mapped[str] = mapped_column(String(10))  # alta | media
    esfera: Mapped[str] = mapped_column(String(10), default="federal", index=True)
    deputado_id: Mapped[int | None] = mapped_column(ForeignKey("deputados.id"), index=True)
    deputado_estadual_id: Mapped[int | None] = mapped_column(ForeignKey("deputados_estaduais.id"), index=True)
    unidade_gestora_id: Mapped[int | None] = mapped_column(ForeignKey("unidades_gestoras.id"), index=True)
    senador_id: Mapped[int | None] = mapped_column(ForeignKey("senadores.id"), index=True)
    # Contratos do PNCP: órgão contratante (CNPJ) e município.
    orgao_cnpj: Mapped[str | None] = mapped_column(String(14), index=True)
    orgao_nome: Mapped[str | None] = mapped_column(String(300))
    municipio_ibge: Mapped[str | None] = mapped_column(String(7), index=True)
    cnpj: Mapped[str | None] = mapped_column(String(14), index=True)
    ano: Mapped[int | None] = mapped_column(Integer)
    valor_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    titulo: Mapped[str] = mapped_column(String(300))
    descricao: Mapped[str] = mapped_column(Text)
    prioridade: Mapped[int] = mapped_column(Integer, default=0, index=True)  # 0 a 100 (ver alertas.pontuar)
    calculado_em: Mapped[datetime] = mapped_column(DateTime)



# --------------------------------------------------------------------------- Pernambuco: ALEPE


class DeputadoEstadual(Base):
    """Deputado estadual de PE (cadastro do portal de transparência da ALEPE)."""

    __tablename__ = "deputados_estaduais"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    nome: Mapped[str] = mapped_column(String(200))
    nome_normalizado: Mapped[str] = mapped_column(String(200), index=True)
    sigla_partido: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    url_foto: Mapped[str | None] = mapped_column(String(300))
    em_exercicio: Mapped[bool] = mapped_column(default=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime)


class VerbaIndenizatoria(Base):
    """Nota da verba indenizatória de um deputado estadual (uma linha por nota)."""

    __tablename__ = "verbas_indenizatorias"
    __table_args__ = (Index("ix_verbas_ano_deputado", "ano", "deputado_estadual_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    docid: Mapped[str] = mapped_column(String(20), index=True)
    deputado_estadual_id: Mapped[int] = mapped_column(ForeignKey("deputados_estaduais.id"), index=True)
    ano: Mapped[int] = mapped_column(Integer)
    mes: Mapped[int] = mapped_column(Integer)
    rubrica: Mapped[int | None] = mapped_column(Integer)
    rubrica_nome: Mapped[str | None] = mapped_column(String(120))
    sequencial: Mapped[int | None] = mapped_column(Integer)
    data: Mapped[date | None] = mapped_column(Date)
    cnpj_cpf: Mapped[str | None] = mapped_column(String(14), index=True)
    tipo_pessoa: Mapped[str | None] = mapped_column(String(2))
    fornecedor: Mapped[str | None] = mapped_column(String(300))
    valor_centavos: Mapped[int] = mapped_column(BigInteger)


class SyncCheckpointEstadual(Base):
    """Mês de verba indenizatória já coletado para um deputado estadual."""

    __tablename__ = "sync_checkpoints_estaduais"

    deputado_estadual_id: Mapped[int] = mapped_column(ForeignKey("deputados_estaduais.id"), primary_key=True)
    ano: Mapped[int] = mapped_column(Integer, primary_key=True)
    mes: Mapped[int] = mapped_column(Integer, primary_key=True)
    concluido_em: Mapped[datetime] = mapped_column(DateTime)


# --------------------------------------------------------------------------- Pernambuco: TCE-PE


class UnidadeGestora(Base):
    """Órgão municipal que presta contas a um tribunal de contas (prefeitura, câmara, autarquia...)."""

    __tablename__ = "unidades_gestoras"

    # TCE-PE: o próprio ID_UNIDADE_GESTORA; outros tribunais: ids a partir de 10.000.000.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    nome: Mapped[str] = mapped_column(String(200))
    natureza: Mapped[str | None] = mapped_column(String(40))  # "Prefeitura Municipal", "Câmara Municipal"...
    fonte: Mapped[str | None] = mapped_column(String(20), default="TCE-PE")
    codigo_origem: Mapped[str | None] = mapped_column(String(200), index=True)
    codigo_municipio_tce: Mapped[str] = mapped_column(String(10), index=True)  # TCE-PE: "P042"; outros: IBGE
    municipio: Mapped[str] = mapped_column(String(120))
    municipio_normalizado: Mapped[str] = mapped_column(String(120), index=True)
    sigla_uf: Mapped[str] = mapped_column(String(2), default="PE")


class DespesaMunicipal(Base):
    """Despesa de um órgão municipal, com valores empenhado, liquidado e pago.

    TCE-PE: um empenho por linha. TCE-SP: soma dos empenhos do órgão a um credor no ano.
    """

    __tablename__ = "despesas_municipais"
    __table_args__ = (Index("ix_desp_mun_ug_ano", "unidade_gestora_id", "ano"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chave: Mapped[str] = mapped_column(String(80), unique=True)
    unidade_gestora_id: Mapped[int] = mapped_column(ForeignKey("unidades_gestoras.id"))
    ano: Mapped[int] = mapped_column(Integer, index=True)
    mes: Mapped[int | None] = mapped_column(Integer)
    data_empenho: Mapped[date | None] = mapped_column(Date)
    numero_empenho: Mapped[str | None] = mapped_column(String(20))
    fornecedor: Mapped[str | None] = mapped_column(String(300))
    fornecedor_normalizado: Mapped[str | None] = mapped_column(String(300), index=True)
    cpf_cnpj: Mapped[str | None] = mapped_column(String(20), index=True)
    tipo_pessoa: Mapped[str | None] = mapped_column(String(2))
    elemento_despesa: Mapped[str | None] = mapped_column(String(200))
    funcao: Mapped[str | None] = mapped_column(String(120))
    acao: Mapped[str | None] = mapped_column(String(300))
    modalidade: Mapped[str | None] = mapped_column(String(120))
    historico: Mapped[str | None] = mapped_column(Text)
    historico_normalizado: Mapped[str | None] = mapped_column(Text)  # para busca sem acento
    id_empenho: Mapped[str | None] = mapped_column(String(20), index=True)  # TCE-PE: liga aos pagamentos
    fonte_recurso: Mapped[str | None] = mapped_column(String(200))  # TCE-PE: "Transferência Especial da União"...
    categoria_economica: Mapped[str | None] = mapped_column(String(40))  # "Despesa Corrente" / "Despesa de Capital"
    qtd_empenhos: Mapped[int] = mapped_column(Integer, default=1)
    valor_empenhado_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    valor_liquidado_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    valor_pago_centavos: Mapped[int] = mapped_column(BigInteger, default=0)


class PagamentoMunicipal(Base):
    """Pagamento de um empenho municipal (TCE-PE, EmpenhoPagamento), com a data em que saiu do caixa.

    Anulações e estornos vêm com valor negativo. Os dados bancários publicados não são guardados.
    """

    __tablename__ = "pagamentos_municipais"
    __table_args__ = (Index("ix_pag_mun_ug_ano", "unidade_gestora_id", "ano"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unidade_gestora_id: Mapped[int] = mapped_column(ForeignKey("unidades_gestoras.id"))
    ano: Mapped[int] = mapped_column(Integer)  # ano do empenho
    id_empenho: Mapped[str] = mapped_column(String(20), index=True)
    data: Mapped[date | None] = mapped_column(Date, index=True)
    tipo: Mapped[str | None] = mapped_column(String(60))
    valor_centavos: Mapped[int] = mapped_column(BigInteger, default=0)


class ContratoMunicipal(Base):
    """Contrato de órgão municipal informado ao TCE-PE (sistema LICON), com link para o PDF."""

    __tablename__ = "contratos_municipais"
    __table_args__ = (Index("ix_contr_mun_ug_ano", "unidade_gestora_id", "ano"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(20), index=True)  # CodigoContrato do TCE-PE
    unidade_gestora_id: Mapped[int] = mapped_column(ForeignKey("unidades_gestoras.id"))
    ano: Mapped[int] = mapped_column(Integer)
    numero: Mapped[str | None] = mapped_column(String(30))
    tipo_processo: Mapped[str | None] = mapped_column(String(80))  # Pregão, Dispensa, Inexigibilidade...
    numero_processo: Mapped[str | None] = mapped_column(String(30))
    ano_processo: Mapped[int | None] = mapped_column(Integer)
    objeto: Mapped[str | None] = mapped_column(Text)
    objeto_normalizado: Mapped[str | None] = mapped_column(Text)
    fornecedor: Mapped[str | None] = mapped_column(String(300))
    fornecedor_normalizado: Mapped[str | None] = mapped_column(String(300))
    cpf_cnpj: Mapped[str | None] = mapped_column(String(20), index=True)  # CPF só mascarado
    tipo_pessoa: Mapped[str | None] = mapped_column(String(2))
    valor_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    vigencia_inicio: Mapped[date | None] = mapped_column(Date)
    vigencia_fim: Mapped[date | None] = mapped_column(Date)
    situacao: Mapped[str | None] = mapped_column(String(60))
    estagio: Mapped[str | None] = mapped_column(String(60))
    url_documento: Mapped[str | None] = mapped_column(String(500))


class ServidorMunicipal(Base):
    """Vínculo de pessoal informado ao TCE-PE (Sagres Pessoal): nome, cargo e vínculo, sem salário."""

    __tablename__ = "servidores_municipais"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unidade_gestora_id: Mapped[int] = mapped_column(ForeignKey("unidades_gestoras.id"), index=True)
    nome: Mapped[str] = mapped_column(String(255))
    nome_normalizado: Mapped[str] = mapped_column(String(255), index=True)
    cargo: Mapped[str | None] = mapped_column(String(200))
    vinculo: Mapped[str | None] = mapped_column(String(100))
    data_admissao: Mapped[date | None] = mapped_column(Date)
    matricula: Mapped[str | None] = mapped_column(String(20))
    hash_cpf: Mapped[str | None] = mapped_column(String(64))
    cpf_meio: Mapped[str | None] = mapped_column(String(6))  # 6 dígitos centrais do CPF ("***.063.774-**")
    ano_remessa: Mapped[int | None] = mapped_column(Integer)
    mes_remessa: Mapped[int | None] = mapped_column(Integer)



# --------------------------------------------------------------------------- PNCP (contratos públicos)


class ContratoPncp(Base):
    """Contrato publicado no Portal Nacional de Contratações Públicas (Lei 14.133/2021)."""

    __tablename__ = "contratos_pncp"
    __table_args__ = (Index("ix_pncp_municipio_data", "municipio_ibge", "data_assinatura"),)

    numero_controle: Mapped[str] = mapped_column(String(60), primary_key=True)
    orgao_cnpj: Mapped[str | None] = mapped_column(String(14), index=True)
    orgao_nome: Mapped[str | None] = mapped_column(String(300))
    esfera: Mapped[str | None] = mapped_column(String(1))
    poder: Mapped[str | None] = mapped_column(String(1))
    sigla_uf: Mapped[str | None] = mapped_column(String(2))
    municipio_ibge: Mapped[str | None] = mapped_column(String(7))
    municipio_nome: Mapped[str | None] = mapped_column(String(120))
    unidade_nome: Mapped[str | None] = mapped_column(String(300))
    fornecedor_ni: Mapped[str | None] = mapped_column(String(20), index=True)
    fornecedor_nome: Mapped[str | None] = mapped_column(String(300))
    tipo_pessoa: Mapped[str | None] = mapped_column(String(2))
    objeto: Mapped[str | None] = mapped_column(Text)
    objeto_normalizado: Mapped[str | None] = mapped_column(Text)
    tipo_contrato: Mapped[str | None] = mapped_column(String(80))
    categoria: Mapped[str | None] = mapped_column(String(80))
    valor_inicial_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    valor_global_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    data_assinatura: Mapped[date | None] = mapped_column(Date)
    vigencia_inicio: Mapped[date | None] = mapped_column(Date)
    vigencia_fim: Mapped[date | None] = mapped_column(Date)
    data_publicacao: Mapped[date | None] = mapped_column(Date)
    ano: Mapped[int | None] = mapped_column(Integer, index=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime)


class SyncMunicipioAno(Base):
    """Município × ano já baixado por inteiro de um tribunal de contas (TCE-SP...)."""

    __tablename__ = "sync_municipios_anos"

    fonte: Mapped[str] = mapped_column(String(20), primary_key=True)
    municipio: Mapped[str] = mapped_column(String(120), primary_key=True)  # código do município na fonte
    ano: Mapped[int] = mapped_column(Integer, primary_key=True)
    registros: Mapped[int] = mapped_column(Integer, default=0)
    concluido_em: Mapped[datetime] = mapped_column(DateTime)


class SyncPncpDia(Base):
    """Dia de publicação do PNCP já baixado por inteiro."""

    __tablename__ = "sync_pncp_dias"

    data: Mapped[date] = mapped_column(Date, primary_key=True)
    registros: Mapped[int] = mapped_column(Integer, default=0)
    concluido_em: Mapped[datetime] = mapped_column(DateTime)



# --------------------------------------------------------------------------- Senado


class Senador(Base):
    """Senador da legislatura (titulares e suplentes que exerceram mandato)."""

    __tablename__ = "senadores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # CodigoParlamentar
    nome: Mapped[str] = mapped_column(String(200))
    nome_normalizado: Mapped[str] = mapped_column(String(200), index=True)
    sigla_partido: Mapped[str | None] = mapped_column(String(30))
    sigla_uf: Mapped[str | None] = mapped_column(String(2), index=True)
    url_foto: Mapped[str | None] = mapped_column(String(300))
    em_exercicio: Mapped[bool] = mapped_column(default=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime)


class DespesaSenado(Base):
    """Despesa da cota dos senadores (CEAPS)."""

    __tablename__ = "despesas_senado"
    __table_args__ = (Index("ix_desp_senado_ano_senador", "ano", "senador_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    senador_id: Mapped[int | None] = mapped_column(ForeignKey("senadores.id"), index=True)
    nome_senador: Mapped[str] = mapped_column(String(200))
    ano: Mapped[int] = mapped_column(Integer)
    mes: Mapped[int] = mapped_column(Integer)
    tipo_despesa: Mapped[str | None] = mapped_column(String(300))
    cnpj_cpf: Mapped[str | None] = mapped_column(String(20), index=True)
    tipo_pessoa: Mapped[str | None] = mapped_column(String(2))
    fornecedor: Mapped[str | None] = mapped_column(String(300))
    documento: Mapped[str | None] = mapped_column(String(100))
    data: Mapped[date | None] = mapped_column(Date)
    detalhamento: Mapped[str | None] = mapped_column(Text)
    cod_documento: Mapped[str | None] = mapped_column(String(30))
    valor_centavos: Mapped[int] = mapped_column(BigInteger)



# --------------------------------------------------------------------------- Siconfi


class EnteSiconfi(Base):
    """Município no Siconfi: CNPJ da prefeitura e população usada pelo Tesouro."""

    __tablename__ = "entes_siconfi"

    codigo_ibge: Mapped[str] = mapped_column(String(7), primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    sigla_uf: Mapped[str] = mapped_column(String(2), index=True)
    cnpj: Mapped[str | None] = mapped_column(String(14), index=True)
    populacao: Mapped[int | None] = mapped_column(Integer)
    capital: Mapped[bool] = mapped_column(default=False)


class ContaMunicipal(Base):
    """Despesa do município por função/subfunção no Siconfi.

    Anos fechados: DCA (Anexo I-E), com o pago. Ano corrente: RREO (Anexo 02) do último
    bimestre publicado, com dotação, empenhado e liquidado até o bimestre (sem o pago).
    """

    __tablename__ = "contas_municipais"

    codigo_ibge: Mapped[str] = mapped_column(String(7), primary_key=True)
    ano: Mapped[int] = mapped_column(Integer, primary_key=True)
    cod_conta: Mapped[str] = mapped_column(String(40), primary_key=True)
    conta: Mapped[str] = mapped_column(String(200))
    nivel: Mapped[str] = mapped_column(String(10))  # total | funcao | subfuncao
    empenhado_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    liquidado_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    pago_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    demonstrativo: Mapped[str | None] = mapped_column(String(4), default="DCA")  # DCA | RREO
    periodo: Mapped[int | None] = mapped_column(Integer)  # RREO: bimestre (1 a 6)
    dotacao_centavos: Mapped[int] = mapped_column(BigInteger, default=0)  # RREO: dotação atualizada



# --------------------------------------------------------------------------- TSE


class Candidato(Base):
    """Candidatura registrada no TSE (eleições municipais e gerais)."""

    __tablename__ = "candidatos"
    __table_args__ = (Index("ix_candidatos_municipio", "municipio_ibge", "ano", "eleito"),)

    sq_candidato: Mapped[str] = mapped_column(String(20), primary_key=True)
    ano: Mapped[int] = mapped_column(Integer, index=True)
    cargo: Mapped[str] = mapped_column(String(60))
    sigla_uf: Mapped[str | None] = mapped_column(String(2))
    codigo_ue: Mapped[str | None] = mapped_column(String(10))
    nome_ue: Mapped[str | None] = mapped_column(String(120))
    municipio_ibge: Mapped[str | None] = mapped_column(String(7))
    nome: Mapped[str] = mapped_column(String(200))
    nome_normalizado: Mapped[str] = mapped_column(String(200), index=True)
    nome_urna: Mapped[str | None] = mapped_column(String(120))
    numero: Mapped[str | None] = mapped_column(String(10))
    sigla_partido: Mapped[str | None] = mapped_column(String(30))
    situacao_candidatura: Mapped[str | None] = mapped_column(String(60))
    resultado: Mapped[str | None] = mapped_column(String(60))
    eleito: Mapped[bool] = mapped_column(default=False)
    ocupacao: Mapped[str | None] = mapped_column(String(120))
    genero: Mapped[str | None] = mapped_column(String(30))
    instrucao: Mapped[str | None] = mapped_column(String(60))
    bens_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    # Vínculo do eleito com o cadastro do parlamentar (feito pelo nome de urna + UF).
    deputado_id: Mapped[int | None] = mapped_column(ForeignKey("deputados.id"), index=True)
    senador_id: Mapped[int | None] = mapped_column(ForeignKey("senadores.id"), index=True)
    deputado_estadual_id: Mapped[int | None] = mapped_column(ForeignKey("deputados_estaduais.id"), index=True)



class Socio(Base):
    """Sócio (quadro societário da Receita) de um fornecedor público.

    Para pessoa física a Receita publica só os 6 dígitos centrais do CPF; é o
    que fica em `documento`. Para pessoa jurídica, o CNPJ completo.
    """

    __tablename__ = "socios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cnpj_basico: Mapped[str] = mapped_column(String(8), index=True)
    tipo: Mapped[str] = mapped_column(String(2))  # PF | PJ | EX
    nome: Mapped[str] = mapped_column(String(300))
    nome_normalizado: Mapped[str] = mapped_column(String(300), index=True)
    documento: Mapped[str | None] = mapped_column(String(14))
    qualificacao: Mapped[str | None] = mapped_column(String(120))
    data_entrada: Mapped[date | None] = mapped_column(Date)



class DoacaoCampanha(Base):
    """Doação de pessoa física a candidato eleito (prestação de contas no TSE).

    Do CPF do doador guarda só os 6 dígitos centrais (o mesmo que a Receita
    publica para sócios), suficiente para o cruzamento e sem expor o CPF.
    """

    __tablename__ = "doacoes_campanha"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ano: Mapped[int] = mapped_column(Integer)
    sq_candidato: Mapped[str] = mapped_column(String(20), index=True)
    doador_nome: Mapped[str] = mapped_column(String(300))
    doador_nome_normalizado: Mapped[str] = mapped_column(String(300), index=True)
    doador_cpf_meio: Mapped[str | None] = mapped_column(String(6))
    valor_centavos: Mapped[int] = mapped_column(BigInteger)


# --------------------------------------------------------------------------- Emenda Pix (Transferegov)


class PlanoPix(Base):
    """Plano de ação de uma transferência especial ("Emenda Pix") no Transferegov."""

    __tablename__ = "planos_pix"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # id_plano_acao
    codigo: Mapped[str | None] = mapped_column(String(40))
    ano: Mapped[int] = mapped_column(Integer, index=True)
    situacao: Mapped[str | None] = mapped_column(String(40))
    motivo_impedimento: Mapped[str | None] = mapped_column(Text)
    cnpj_beneficiario: Mapped[str | None] = mapped_column(String(14), index=True)
    nome_beneficiario: Mapped[str | None] = mapped_column(String(200))
    sigla_uf: Mapped[str | None] = mapped_column(String(2))
    municipio_ibge: Mapped[str | None] = mapped_column(String(7), index=True)
    parlamentar: Mapped[str | None] = mapped_column(String(200))
    codigo_parlamentar: Mapped[str | None] = mapped_column(String(10))
    numero_emenda: Mapped[str | None] = mapped_column(String(20))
    area: Mapped[str | None] = mapped_column(String(200))
    objeto: Mapped[str | None] = mapped_column(Text)  # dos executores, concatenado
    metas: Mapped[str | None] = mapped_column(Text)  # nomes/descrições das metas, separados por " | "
    custeio_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    investimento_centavos: Mapped[int] = mapped_column(BigInteger, default=0)
    relatorio_situacao: Mapped[str | None] = mapped_column(String(40))
    relatorio_parecer: Mapped[str | None] = mapped_column(Text)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime)


class RepassePix(Base):
    """Transferência financeira de uma Emenda Pix (documento hábil "enviado com sucesso")."""

    __tablename__ = "repasses_pix"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # id_dh
    plano_id: Mapped[int] = mapped_column(Integer, index=True)
    data: Mapped[date | None] = mapped_column(Date)
    valor_centavos: Mapped[int] = mapped_column(BigInteger, default=0)


# --------------------------------------------------------------------------- contestações / direito de resposta


class Contestacao(Base):
    """Pedido de correção, resposta de pessoa/empresa citada ou pedido sobre dados pessoais (LGPD).

    O contato de quem enviou nunca é publicado. O IP não é guardado: só um resumo (hash)
    que muda a cada dia, para limitar abusos.
    """

    __tablename__ = "contestacoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    protocolo: Mapped[str] = mapped_column(String(20), unique=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, index=True)
    tipo: Mapped[str] = mapped_column(String(20))  # erro | resposta | privacidade
    url: Mapped[str] = mapped_column(String(500), index=True)  # página contestada (caminho do site)
    alvo: Mapped[str | None] = mapped_column(String(300))  # o que foi contestado ("Alerta: ...")
    mensagem: Mapped[str] = mapped_column(Text)
    nome: Mapped[str | None] = mapped_column(String(200))
    contato: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="recebida", index=True)
    resposta_publica: Mapped[str | None] = mapped_column(Text)
    respondido_em: Mapped[datetime | None] = mapped_column(DateTime)
    origem_hash: Mapped[str | None] = mapped_column(String(64), index=True)
