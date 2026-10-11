/** Tipos das respostas da FastAPI. Valores em reais chegam como string ("1234.56"). */

export type Reais = string;

export interface Deputado {
  id: number;
  nome: string;
  sigla_partido: string | null;
  sigla_uf: string | null;
  url_foto: string | null;
}

export interface Filtros {
  ufs: string[];
  partidos: string[];
  anos: number[];
  anos_emendas: number[];
}

export interface Pagina<T> {
  total: number;
  itens: T[];
}

export interface ResumoGastos {
  total_liquido: Reais;
  qtd_deputados: number;
  qtd_despesas: number;
}

export interface RankingItem {
  deputado: Deputado;
  total_liquido: Reais;
  qtd_despesas: number;
  media_uf: Reais | null;
  indice_uf: number | null;
}

export interface TipoDespesaItem {
  tipo_despesa: string;
  total_liquido: Reais;
  qtd_despesas: number;
}

export interface Despesa {
  id: number;
  ano: number;
  mes: number;
  data_documento: string | null;
  tipo_despesa: string;
  tipo_documento: string | null;
  num_documento: string | null;
  fornecedor: string | null;
  cnpj_cpf: string | null;
  tipo_pessoa: "PF" | "PJ" | null;
  valor_documento: Reais;
  valor_glosa: Reais;
  valor_liquido: Reais;
  url_documento: string | null;
  parcela: number;
}

export interface DespesaComDeputado extends Despesa {
  deputado: Deputado;
}

export interface SerieMensalItem {
  ano: number;
  mes: number;
  total_liquido: Reais;
}

export interface GastosDeputado {
  deputado: Deputado;
  ano: number | null;
  total_liquido: Reais;
  qtd_despesas: number;
  serie_mensal: SerieMensalItem[];
  despesas: Pagina<Despesa>;
}

export interface Health {
  status: string;
  ultimo_sync: string | null;
  fontes: Record<string, string>;
}

export interface Municipio {
  sigla_uf: string;
  municipio: string;
  total_recebido: Reais;
  qtd_pagamentos: number;
}

export interface AutorEmenda {
  nome_autor: string;
  deputado: Deputado | null;
  total_recebido: Reais;
  qtd_pagamentos: number;
}

export interface Favorecido {
  favorecido: string;
  codigo_favorecido: string | null;
  tipo_favorecido: string | null;
  total_recebido: Reais;
  qtd_pagamentos: number;
}

export interface FuncaoItem {
  funcao: string;
  total: Reais;
}

export interface SerieEmendasItem {
  ano: number;
  mes: number;
  total_recebido: Reais;
}

export interface EmendasMunicipio {
  sigla_uf: string;
  municipio: string;
  ano: number | null;
  total_recebido: Reais;
  qtd_pagamentos: number;
  qtd_autores: number;
  por_autor: AutorEmenda[];
  por_favorecido: Favorecido[];
  por_funcao: FuncaoItem[];
  por_acao: { acao: string; total: Reais }[];
  serie_mensal: SerieEmendasItem[];
  codigo_ibge: string | null;
  populacao: number | null;
  ano_populacao: number | null;
  regiao_imediata: string | null;
  por_habitante: Reais | null;
  total_pix: Reais;
}

export interface PagamentoEmenda {
  id: number;
  codigo_emenda: string | null;
  ano: number;
  mes: number;
  tipo_emenda: string | null;
  nome_autor: string | null;
  deputado_id: number | null;
  favorecido: string | null;
  tipo_favorecido: string | null;
  valor_recebido: Reais;
  acao: string | null;
  objeto: string | null;
}

export interface DestinoEmenda {
  sigla_uf: string | null;
  municipio: string | null;
  total_recebido: Reais;
  qtd_pagamentos: number;
}

export interface EmendasDeputado {
  deputado: Deputado;
  ano: number | null;
  qtd_emendas: number;
  total_empenhado: Reais;
  total_pago: Reais;
  total_recebido_municipios: Reais;
  por_funcao: FuncaoItem[];
  por_destino: DestinoEmenda[];
}

export interface ComparacaoRegiao {
  regiao_imediata: string | null;
  ano: number | null;
  municipios: {
    codigo_ibge: string;
    municipio: string;
    sigla_uf: string;
    populacao: number | null;
    total_recebido: Reais;
    por_habitante: Reais | null;
    atual: boolean;
  }[];
}

export interface GastoDeputadoItem {
  deputado: Deputado;
  total_liquido: Reais;
  qtd_despesas: number;
}

export interface CotaNaCidade {
  base_cnpj_carregada: boolean;
  total_liquido: Reais;
  qtd_despesas: number;
  por_deputado: GastoDeputadoItem[];
  por_fornecedor: { cnpj: string; nome: string | null; total_liquido: Reais; qtd_deputados: number }[];
}

export type Gravidade = "alta" | "media";
export type Esfera = "federal" | "senado" | "estadual" | "municipal";

export interface DeputadoEstadual {
  id: number;
  nome: string;
  sigla_partido: string | null;
  url_foto: string | null;
  em_exercicio: boolean;
}

export interface Orgao {
  id: number;
  nome: string;
  natureza: string | null;
  fonte?: string | null;
  municipio: string;
  sigla_uf: string;
}

export interface Senador {
  id: number;
  nome: string;
  sigla_partido: string | null;
  sigla_uf: string | null;
  url_foto: string | null;
  em_exercicio: boolean;
}

export interface Alerta {
  id: number;
  tipo: string;
  gravidade: Gravidade;
  /** 0 a 100: tipo, gravidade, valor e evidências que se somam. */
  prioridade?: number;
  esfera: Esfera;
  deputado: Deputado | null;
  senador: Senador | null;
  deputado_estadual: DeputadoEstadual | null;
  orgao: Orgao | null;
  orgao_contratante: { cnpj: string; nome: string } | null;
  municipio_ibge: string | null;
  municipio: { codigo_ibge: string; nome: string; sigla_uf: string } | null;
  cnpj: string | null;
  ano: number | null;
  valor: Reais;
  titulo: string;
  descricao: string;
}

export interface ResumoAlertas {
  total: number;
  altas: number;
  qtd_deputados: number;
  por_tipo: { tipo: string; alta: number; media: number }[];
  por_esfera: Partial<Record<Esfera, number>>;
}

export interface CadastroFornecedor {
  razao_social: string | null;
  nome_fantasia: string | null;
  matriz: boolean | null;
  situacao_cadastral: string | null;
  data_situacao_cadastral: string | null;
  data_inicio_atividade: string | null;
  cnae_principal: string | null;
  natureza_juridica: string | null;
  capital_social: Reais | null;
  porte: string | null;
  opcao_simples: boolean | null;
  opcao_mei: boolean | null;
  data_opcao_mei: string | null;
  data_exclusao_mei: string | null;
  sigla_uf: string | null;
  municipio: string | null;
  codigo_municipio_ibge: string | null;
  bairro: string | null;
  referencia: string;
}

export interface Fornecedor {
  cnpj: string;
  nome: string | null;
  cadastro: CadastroFornecedor | null;
  total_recebido: Reais;
  total_cota: Reais;
  total_estadual: Reais;
  total_municipal: Reais;
  por_deputado_estadual: { deputado: DeputadoEstadual; total_liquido: Reais; qtd_despesas: number }[];
  por_orgao: { orgao: Orgao; total_pago: Reais; qtd_empenhos: number }[];
  qtd_despesas: number;
  primeira_nota: string | null;
  ultima_nota: string | null;
  por_deputado: GastoDeputadoItem[];
  por_ano: { ano: number; total: Reais }[];
}

export interface EstadualListaItem {
  deputado: DeputadoEstadual;
  total: Reais;
  qtd_notas: number;
  meses: number;
}

export interface ResumoEstaduais {
  total: Reais;
  qtd_notas: number;
  qtd_deputados: number;
  por_rubrica: { rubrica: string; total: Reais }[];
  anos: number[];
}

export interface NotaVerba {
  id: number;
  docid: string;
  ano: number;
  mes: number;
  rubrica_nome: string | null;
  data: string | null;
  cnpj_cpf: string | null;
  tipo_pessoa: "PF" | "PJ" | null;
  fornecedor: string | null;
  valor: Reais;
}

export interface DetalheEstadual {
  deputado: DeputadoEstadual;
  ano: number | null;
  total: Reais;
  qtd_notas: number;
  por_rubrica: { rubrica: string; total: Reais }[];
  serie_mensal: { ano: number; mes: number; total: Reais }[];
  por_fornecedor: { cnpj: string | null; nome: string | null; total: Reais; qtd_notas: number }[];
  notas: Pagina<NotaVerba>;
}

export interface NomeTotal {
  nome: string;
  total_pago: Reais;
}

export interface FornecedorMunicipal {
  nome: string;
  cpf_cnpj: string | null;
  tipo_pessoa: "PF" | "PJ" | null;
  total_pago: Reais;
  qtd_empenhos: number;
}

export interface Camara {
  orgao: Orgao;
  ano: number | null;
  inicio_mandato: number;
  total_pago: Reais;
  qtd_empenhos: number;
  vereadores: {
    nome: string;
    mandato_atual: boolean;
    total_recebido: Reais;
    qtd_pagamentos: number;
    por_tipo: NomeTotal[];
  }[];
  qtd_vereadores_mandato: number;
  nomeados_no_mandato: number;
  por_vinculo: { nome: string; qtd: number }[];
  comissionados_por_cargo: { nome: string; qtd: number }[];
  por_elemento: NomeTotal[];
  fornecedores: FornecedorMunicipal[];
  sem_credor_identificado: Reais;
}

export interface Prefeitura {
  ano: number | null;
  anos: number[];
  total_pago: Reais;
  total_empenhado: Reais;
  qtd_empenhos: number;
  por_orgao: { orgao: Orgao; total_pago: Reais }[];
  por_funcao: NomeTotal[];
  por_elemento: NomeTotal[];
  fornecedores: FornecedorMunicipal[];
  sem_credor_identificado: Reais;
}

export interface Empenho {
  id: number;
  orgao: string;
  ano: number;
  mes: number | null;
  data_empenho: string | null;
  numero_empenho: string | null;
  fornecedor: string | null;
  cpf_cnpj: string | null;
  tipo_pessoa: "PF" | "PJ" | null;
  elemento_despesa: string | null;
  funcao: string | null;
  historico: string | null;
  fonte_recurso?: string | null;
  categoria_economica?: string | null;
  qtd_empenhos?: number;
  valor_empenhado: Reais;
  valor_pago: Reais;
}

export interface DocumentoFornecedor {
  fonte: "cota_federal" | "cota_senado" | "verba_estadual" | "empenho_municipal" | "contrato_pncp";
  fonte_nome: string;
  data: string | null;
  ano: number | null;
  mes: number | null;
  pagador: string | null;
  pagador_id: string | null;
  descricao: string | null;
  documento: string | null;
  valor: Reais;
  url: string | null;
}

export interface SenadorListaItem {
  senador: Senador;
  total: Reais;
  qtd_notas: number;
}

export interface DetalheSenador extends Omit<DetalheEstadual, "deputado"> {
  senador: Senador;
}

export interface ContratosMunicipio {
  codigo_ibge: string;
  ano: number | null;
  anos: number[];
  cobertura_desde: string | null;
  cobertura_pct: number;
  total_contratado: Reais;
  qtd_contratos: number;
  por_orgao: { cnpj: string | null; nome: string; total: Reais; qtd: number }[];
  por_categoria: NomeTotal[];
  fornecedores: FornecedorMunicipal[];
}

export interface Contrato {
  numero_controle: string;
  orgao_cnpj: string | null;
  orgao_nome: string | null;
  unidade_nome: string | null;
  fornecedor_ni: string | null;
  fornecedor_nome: string | null;
  tipo_pessoa: string | null;
  objeto: string | null;
  tipo_contrato: string | null;
  categoria: string | null;
  valor_global: Reais;
  valor_inicial: Reais;
  data_assinatura: string | null;
  vigencia_inicio: string | null;
  vigencia_fim: string | null;
  url: string | null;
}

export interface FuncaoConta {
  codigo: string;
  nome: string;
  /** No ano corrente (RREO), o liquidado até o bimestre. */
  pago: Reais;
  empenhado: Reais;
  dotacao?: Reais | null;
  por_habitante: Reais | null;
  mediana_uf: Reais | null;
  mediana_brasil: Reais | null;
}

export interface ContasMunicipio {
  codigo_ibge: string;
  ano: number | null;
  anos: number[];
  demonstrativo?: "DCA" | "RREO";
  bimestre?: number | null;
  populacao: number | null;
  total_pago: Reais;
  total_empenhado: Reais;
  total_dotacao?: Reais | null;
  por_habitante: Reais | null;
  mediana_uf_total: Reais | null;
  mediana_brasil_total: Reais | null;
  amostra_uf: number;
  amostra_brasil: number;
  funcoes: FuncaoConta[];
  destaques: FuncaoConta[];
}

export interface Eleitos {
  codigo_ibge: string;
  ano: number;
  qtd_candidaturas: number;
  eleitos: {
    nome: string;
    nome_urna: string | null;
    cargo: string;
    sigla_partido: string | null;
    resultado: string | null;
    ocupacao: string | null;
    instrucao: string | null;
    genero: string | null;
    bens: Reais;
  }[];
}

export interface PlanoPix {
  id: number;
  codigo: string | null;
  ano: number;
  situacao: string | null;
  motivo_impedimento: string | null;
  parlamentar: string | null;
  area: string | null;
  objeto: string | null;
  metas: string | null;
  custeio: Reais;
  investimento: Reais;
  recebido: Reais;
  ultimo_repasse: string | null;
  relatorio_situacao: string | null;
  relatorio_parecer: string | null;
}

export interface AnoPix {
  ano: number;
  recebido: Reais;
  gasto: Reais;
  gasto_corrente: Reais;
  gasto_capital: Reais;
  gasto_estadual: Reais;
}

export interface EmendaPix {
  municipio: { codigo_ibge: string; nome: string; sigla_uf: string };
  tem_gastos: boolean;
  gastos_ate: { ano: number; mes: number | null } | null;
  total_recebido: Reais;
  total_gasto: Reais;
  total_gasto_corrente: Reais;
  total_gasto_estadual: Reais;
  anos: AnoPix[];
  planos: PlanoPix[];
  credores: FornecedorMunicipal[];
}

export interface PessoalMunicipio {
  ano: number | null;
  anos: number[];
  inicio_mandato: number;
  remessa: { ano: number; mes: number | null } | null;
  qtd_vinculos: number;
  qtd_pessoas: number;
  por_vinculo: { nome: string; vinculos: number; pessoas: number; no_mandato: number }[];
  admissoes_por_ano: { ano: number; por_vinculo: { nome: string; qtd: number }[] }[];
  cargos: { cargo: string; vinculo: string; pessoas: number }[];
  categorias_folha: string[];
  folha_pela_data_do_pagamento?: boolean;
  folha_por_ano: { ano: number; total: Reais; por_categoria: { nome: string; total: Reais }[] }[];
  folha_por_mes: { mes: number; total: Reais; por_categoria: { nome: string; total: Reais }[] }[];
  prestadores_total: Reais;
  prestadores_qtd: number;
  prestadores: {
    nome: string;
    cpf: string | null;
    total_pago: Reais;
    qtd_empenhos: number;
    tipo: string;
    exemplo: string | null;
    servidor: { cargo: string | null; vinculo: string | null; data_admissao: string | null } | null;
  }[];
  doadores_nomeados: {
    nome: string;
    cargo: string | null;
    vinculo: string | null;
    data_admissao: string | null;
    doado: Reais;
    candidato: string;
    cargo_candidato: string | null;
    partido: string | null;
    eleito: boolean;
  }[];
}

export interface Servidor {
  nome: string;
  cargo: string | null;
  vinculo: string | null;
  data_admissao: string | null;
  matricula: string | null;
  cpf: string | null;
  orgao: string;
}

export interface PapelBusca {
  tipo:
    | "empresa"
    | "pagamento"
    | "contrato"
    | "deputado"
    | "senador"
    | "estadual"
    | "servidor"
    | "socio"
    | "candidato"
    | "doador"
    | "credor";
  papel: string | null;
  orgao: string | null;
  lugar: string | null;
  ano: number | null;
  valor: Reais | null;
  url: string | null;
  documento: string | null;
}

export interface ResultadoBusca {
  titulo: string;
  tipo_pessoa: "PF" | "PJ";
  documento: string | null;
  homonimos_possiveis: boolean;
  papeis: PapelBusca[];
}

export interface Busca {
  termo: string;
  cidade?: string | null;
  total: number;
  indice_disponivel: boolean;
  resultados: ResultadoBusca[];
}

export interface ContestacaoPublica {
  protocolo: string;
  tipo: "erro" | "resposta" | "privacidade";
  url: string;
  alvo: string | null;
  mensagem: string;
  status: "corrigida" | "mantida" | "resposta_publicada";
  resposta_publica: string | null;
  criado_em: string;
  respondido_em: string | null;
}
