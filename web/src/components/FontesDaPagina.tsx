import { useLocation } from "react-router";
import { useApi } from "../lib/api";
import { formatarDataHora } from "../lib/format";
import type { Health } from "../lib/types";

const NOMES: Record<string, string> = {
  "camara-bulk": "Câmara dos Deputados",
  deputados: "cadastro de deputados",
  emendas: "Portal da Transparência (emendas)",
  senado: "Senado",
  alepe: "ALEPE",
  tce: "TCE-PE",
  tce_sp: "TCE-SP",
  tce_pb: "TCE-PB",
  pncp: "PNCP",
  siconfi: "Siconfi (balanço anual)",
  siconfi_rreo: "Siconfi (relatório bimestral)",
  transferegov: "Transferegov",
  tse: "TSE",
  cnpj: "Receita Federal (CNPJ)",
  ibge: "IBGE",
};

// Rota -> fontes usadas pela página (a primeira regra que casar vale).
const REGRAS: [RegExp, string[]][] = [
  [/^\/cidade\/[^/]+\/[^/]+\/emenda-pix/, ["transferegov", "tce"]],
  [/^\/cidade\/[^/]+\/[^/]+\/contratos/, ["pncp", "tce"]],
  [/^\/cidade\/[^/]+\/[^/]+\/contas/, ["siconfi", "siconfi_rreo"]],
  [/^\/cidade\/[^/]+\/[^/]+\/eleitos/, ["tse"]],
  [/^\/cidade\/[^/]+\/[^/]+\/(camara|prefeitura|pessoal)/, ["tce", "tce_sp", "tce_pb"]],
  [/^\/cidade\/[^/]+\/[^/]+\/busca/, ["cnpj", "tse", "tce", "pncp"]],
  [/^\/cidade\//, ["emendas", "camara-bulk", "ibge"]],
  [/^\/deputados/, ["camara-bulk", "emendas"]],
  [/^\/senadores/, ["senado"]],
  [/^\/estaduais/, ["alepe"]],
  [/^\/fornecedores/, ["cnpj", "camara-bulk", "pncp"]],
  [/^\/alertas/, ["camara-bulk", "tce", "pncp", "cnpj", "transferegov"]],
  [/^\/$/, ["camara-bulk"]],
];

/** "Dados desta página: Siconfi, coletado em 11/10/2026 03:44 · ..." — de onde vêm os números e de quando. */
export function FontesDaPagina() {
  const { pathname } = useLocation();
  const saude = useApi<Health>("/health").dados;
  const fontes = REGRAS.find(([padrao]) => padrao.test(pathname))?.[1] ?? [];
  const itens = fontes.filter((f) => saude?.fontes?.[f]);
  if (!itens.length) return null;
  return (
    <p className="mt-8 border-t border-border pt-3 text-sm text-muted-foreground">
      <strong>Dados desta página:</strong>{" "}
      {itens.map((f) => `${NOMES[f] ?? f}, coletado em ${formatarDataHora(saude!.fontes[f])}`).join(" · ")}.
      As fontes têm atraso próprio (o órgão pode demorar a publicar).
    </p>
  );
}
