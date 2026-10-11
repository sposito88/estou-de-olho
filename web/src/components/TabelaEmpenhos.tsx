import { Search } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { useApi } from "../lib/api";
import { capitalizar, formatarBRL, formatarData, formatarDocumento, paraNumero, plural } from "../lib/format";
import type { Empenho, Pagina } from "../lib/types";
import { useParametros } from "../lib/useParametros";
import { Carregando, ErroApi, Vazio } from "./Estado";
import { Paginacao } from "./Paginacao";

const POR_PAGINA = 20;

interface TabelaEmpenhosProps {
  /** `/api/municipios/{uf}/{municipio}` */
  base: string;
  ano: string;
  orgaoId?: number;
  /** "pix" ou "pix_estadual": só gastos pagos com Emenda Pix. */
  fonte?: string;
}

/** Empenhos com busca (credor ou histórico, sem acento) e paginação na URL. */
export function TabelaEmpenhos({ base, ano, orgaoId, fonte }: TabelaEmpenhosProps) {
  const { valores, definir, pagina } = useParametros(["busca"] as const);
  const [texto, setTexto] = useState(valores.busca);
  const id = useId();

  useEffect(() => {
    const espera = setTimeout(() => {
      if (texto.trim() !== valores.busca) definir({ busca: texto.trim() });
    }, 400);
    return () => clearTimeout(espera);
  }, [texto, valores.busca, definir]);

  const empenhos = useApi<Pagina<Empenho>>(`${base}/empenhos`, {
    ano,
    orgao_id: orgaoId,
    fonte,
    busca: valores.busca,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor={id} className="mb-1 block text-sm font-bold text-secondary">
          Buscar empenho
        </label>
        <div className="relative max-w-xl">
          <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" />
          <input
            id={id}
            type="search"
            className="input pl-10"
            placeholder="Ex.: pavimentação, diária, nome da empresa"
            autoComplete="off"
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
          />
        </div>
      </div>

      {empenhos.erro ? (
        <ErroApi erro={empenhos.erro} onTentarDeNovo={empenhos.recarregar} />
      ) : !empenhos.dados ? (
        <Carregando linhas={6} rotulo="Carregando empenhos" />
      ) : empenhos.dados.total === 0 ? (
        <Vazio>Nenhum empenho encontrado.</Vazio>
      ) : (
        <>
          <div className="-mx-5 overflow-x-auto sm:mx-0 sm:rounded-lg sm:border sm:border-border" tabIndex={0} role="region" aria-label="Empenhos">
            <table className="w-full min-w-[52rem] text-left text-sm">
              <caption className="sr-only">Empenhos</caption>
              <thead className="bg-muted text-secondary">
                <tr>
                  <th scope="col" className="px-3 py-2.5 font-bold">Data</th>
                  <th scope="col" className="px-3 py-2.5 font-bold">Credor</th>
                  <th scope="col" className="px-3 py-2.5 font-bold">Para quê</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-bold">Pago</th>
                </tr>
              </thead>
              <tbody>
                {empenhos.dados.itens.map((e) => (
                  <tr key={e.id} className="border-t border-border align-top hover:bg-background">
                    <td className="numero whitespace-nowrap px-3 py-2.5">
                      {formatarData(e.data_empenho)}
                      <span className="block text-muted-foreground">
                        {(e.qtd_empenhos ?? 1) > 1
                          ? plural(e.qtd_empenhos ?? 0, "empenho", "empenhos")
                          : `nº ${e.numero_empenho ?? "—"}`}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      {e.tipo_pessoa === "PJ" && e.cpf_cnpj ? (
                        <Link to={`/fornecedores/${e.cpf_cnpj}`} className="link">
                          {capitalizar(e.fornecedor) || "—"}
                        </Link>
                      ) : (
                        capitalizar(e.fornecedor) || "—"
                      )}
                      {e.cpf_cnpj && <span className="numero block text-muted-foreground">{formatarDocumento(e.cpf_cnpj)}</span>}
                    </td>
                    <td className="max-w-md px-3 py-2.5">
                      {capitalizar(e.historico) || "—"}
                      <span className="block text-muted-foreground">
                        {[e.elemento_despesa, e.orgao].filter(Boolean).join(" · ")}
                      </span>
                    </td>
                    <td className="numero whitespace-nowrap px-3 py-2.5 text-right font-bold">
                      {formatarBRL(e.valor_pago)}
                      {paraNumero(e.valor_empenhado) !== paraNumero(e.valor_pago) && (
                        <span className="block font-normal text-muted-foreground">
                          de {formatarBRL(e.valor_empenhado)} empenhados
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Paginacao
            rotulo="Páginas de empenhos"
            pagina={pagina}
            porPagina={POR_PAGINA}
            total={empenhos.dados.total}
            onMudar={(p) => definir({ pagina: p })}
          />
        </>
      )}
    </div>
  );
}
