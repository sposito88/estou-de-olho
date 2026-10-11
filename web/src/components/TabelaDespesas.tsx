import { ExternalLink } from "lucide-react";
import { Link } from "react-router";
import { formatarBRL, rotuloDespesa, formatarData, formatarDocumento, mesCurto, partidoUf, paraNumero } from "../lib/format";
import type { Despesa, DespesaComDeputado } from "../lib/types";

interface TabelaDespesasProps {
  despesas: (Despesa | DespesaComDeputado)[];
  legenda: string;
  mostrarDeputado?: boolean;
}

const temDeputado = (d: Despesa | DespesaComDeputado): d is DespesaComDeputado => "deputado" in d;

/** Tabela de despesas com rolagem horizontal própria (a página nunca rola de lado). */
export function TabelaDespesas({ despesas, legenda, mostrarDeputado = false }: TabelaDespesasProps) {
  return (
    <div className="-mx-5 overflow-x-auto sm:mx-0 sm:rounded-lg sm:border sm:border-border" tabIndex={0} role="region" aria-label={legenda}>
      <table className="w-full min-w-[44rem] text-left text-sm">
        <caption className="sr-only">{legenda}</caption>
        <thead className="bg-muted text-secondary">
          <tr>
            <th scope="col" className="px-3 py-2.5 font-bold">Data</th>
            {mostrarDeputado && <th scope="col" className="px-3 py-2.5 font-bold">Deputado</th>}
            <th scope="col" className="px-3 py-2.5 font-bold">Tipo</th>
            <th scope="col" className="px-3 py-2.5 font-bold">Fornecedor</th>
            <th scope="col" className="px-3 py-2.5 text-right font-bold">Valor reembolsado</th>
            <th scope="col" className="px-3 py-2.5 font-bold">Nota</th>
          </tr>
        </thead>
        <tbody>
          {despesas.map((d) => {
            const glosa = paraNumero(d.valor_glosa);
            return (
              <tr key={d.id} className="border-t border-border align-top hover:bg-background">
                <td className="numero whitespace-nowrap px-3 py-2.5">
                  {d.data_documento ? formatarData(d.data_documento) : <span title="Sem data no documento">{mesCurto(d.ano, d.mes)}</span>}
                </td>
                {mostrarDeputado && temDeputado(d) && (
                  <td className="px-3 py-2.5">
                    <Link to={`/deputados/${d.deputado.id}`} className="link">
                      {d.deputado.nome}
                    </Link>
                    <span className="block text-muted-foreground">{partidoUf(d.deputado.sigla_partido, d.deputado.sigla_uf)}</span>
                  </td>
                )}
                <td className="px-3 py-2.5">{rotuloDespesa(d.tipo_despesa)}</td>
                <td className="px-3 py-2.5">
                  {d.tipo_pessoa === "PJ" && d.cnpj_cpf ? (
                    <Link to={`/fornecedores/${d.cnpj_cpf}`} className="link">
                      {d.fornecedor ?? "—"}
                    </Link>
                  ) : (
                    d.fornecedor ?? "—"
                  )}
                  {d.cnpj_cpf && <span className="numero block text-muted-foreground">{formatarDocumento(d.cnpj_cpf)}</span>}
                </td>
                <td className="numero whitespace-nowrap px-3 py-2.5 text-right font-bold">
                  {formatarBRL(d.valor_liquido)}
                  {glosa !== 0 && (
                    <span className="block font-normal text-muted-foreground">
                      nota de {formatarBRL(d.valor_documento)}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  {d.url_documento ? (
                    <a
                      href={d.url_documento}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="link inline-flex min-h-11 items-center gap-1 whitespace-nowrap"
                    >
                      Ver nota <ExternalLink aria-hidden className="size-4" />
                      <span className="sr-only">(abre em nova aba)</span>
                    </a>
                  ) : (
                    <span className="text-muted-foreground">Sem nota</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
