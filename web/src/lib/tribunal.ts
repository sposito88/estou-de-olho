/** Tribunal de contas que publica os dados de um órgão municipal. */
export interface Tribunal {
  sigla: string;
  nome: string;
  /** Publica empenho a empenho, com histórico, área e tipo de despesa? */
  porEmpenho: boolean;
  /** Publica a lista de pessoal de cada órgão (vereadores e nomeados)? */
  pessoal: boolean;
}

const TRIBUNAIS: Record<string, Tribunal> = {
  "TCE-PE": { sigla: "TCE-PE", nome: "Tribunal de Contas de Pernambuco", porEmpenho: true, pessoal: true },
  "TCE-PB": { sigla: "TCE-PB", nome: "Tribunal de Contas do Estado da Paraíba", porEmpenho: false, pessoal: true },
  "TCE-SP": { sigla: "TCE-SP", nome: "Tribunal de Contas do Estado de São Paulo", porEmpenho: false, pessoal: false },
};

export function tribunal(fonte: string | null | undefined): Tribunal {
  return TRIBUNAIS[fonte ?? "TCE-PE"] ?? { sigla: fonte ?? "", nome: fonte ?? "", porEmpenho: false, pessoal: false };
}
