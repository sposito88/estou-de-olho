import { ExternalLink, FileSignature, Landmark, Search, Wallet } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Link, useParams } from "react-router";
import { CabecalhoCidade } from "../components/CabecalhoCidade";
import { AvisoAlertas, CartaoAlerta, useTiposAlerta } from "../components/CartaoAlerta";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { ListaBarras } from "../components/ListaBarras";
import { Paginacao } from "../components/Paginacao";
import { Secao } from "../components/Secao";
import { StatCard } from "../components/StatCard";
import { useApi } from "../lib/api";
import { capitalizar, formatarBRL, formatarData, formatarDocumento, formatarInteiro, nomeProprio, plural } from "../lib/format";
import type { Alerta, Contrato, ContratosMunicipio, Pagina } from "../lib/types";
import { useParametros } from "../lib/useParametros";

const POR_PAGINA = 20;

export function Contratos() {
  const { uf = "", municipio = "" } = useParams();
  const { valores, definir, pagina } = useParametros(["ano", "orgao", "busca"] as const);
  const base = `/api/municipios/${encodeURIComponent(uf)}/${encodeURIComponent(municipio)}`;
  const resumo = useApi<ContratosMunicipio>(`${base}/contratos`, { ano: valores.ano });
  const lista = useApi<Pagina<Contrato>>(`${base}/contratos/lista`, {
    ano: valores.ano,
    orgao_cnpj: valores.orgao,
    busca: valores.busca,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });
  const alertas = useApi<Pagina<Alerta>>(resumo.dados ? "/api/alertas" : null, {
    municipio_ibge: resumo.dados?.codigo_ibge,
    ano: valores.ano,
    limit: 20,
  });
  const tipos = useTiposAlerta();
  const [texto, setTexto] = useState(valores.busca);
  const idBusca = useId();
  useEffect(() => {
    const espera = setTimeout(() => {
      if (texto.trim() !== valores.busca) definir({ busca: texto.trim() });
    }, 400);
    return () => clearTimeout(espera);
  }, [texto, valores.busca, definir]);

  const nome = nomeProprio(municipio);
  const periodo = valores.ano ? `em ${valores.ano}` : "desde 2024";
  const orgaoSelecionado = resumo.dados?.por_orgao.find((o) => o.cnpj === valores.orgao);

  return (
    <div className="space-y-6">
      <CabecalhoCidade uf={uf} municipio={municipio} />
      {resumo.erro ? (
        <ErroApi erro={resumo.erro} onTentarDeNovo={resumo.recarregar} />
      ) : !resumo.dados ? (
        <Carregando linhas={8} rotulo="Carregando contratos" />
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <p className="max-w-2xl text-secondary">
              Contratos que a prefeitura, a câmara e os demais órgãos de {nome} publicaram no{" "}
              <strong>Portal Nacional de Contratações Públicas</strong> (PNCP), obrigatório pela Lei 14.133/2021.
              {resumo.dados.cobertura_desde && ` Dados desde ${formatarData(resumo.dados.cobertura_desde)}.`}
            </p>
            <div className="w-full sm:w-56">
              <CampoSelect
                rotulo="Ano da assinatura"
                valor={valores.ano}
                todos="Todos os anos"
                opcoes={opcoesSimples(resumo.dados.anos)}
                onMudar={(ano) => definir({ ano })}
              />
            </div>
          </div>

          {resumo.dados.cobertura_pct < 100 && (
            <p role="status" className="rounded-lg bg-accent-soft px-4 py-3 text-primary">
              <strong>Coleta nacional em andamento:</strong> {resumo.dados.cobertura_pct}% dos dias desde{" "}
              {formatarData(resumo.dados.cobertura_desde)} já foram baixados do PNCP. Os números desta página ainda vão
              crescer.
            </p>
          )}

          {resumo.dados.qtd_contratos === 0 ? (
            <Vazio>
              Nenhum contrato de {nome} encontrado no PNCP {periodo}. Municípios pequenos ainda publicam pouco, e a
              coleta nacional pode estar em andamento.
            </Vazio>
          ) : (
            <>
              <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-3">
                <StatCard destaque icone={Wallet} rotulo="Valor contratado" valor={formatarBRL(resumo.dados.total_contratado)} detalhe={periodo} />
                <StatCard icone={FileSignature} rotulo="Contratos" valor={formatarInteiro(resumo.dados.qtd_contratos)} />
                <StatCard icone={Landmark} rotulo="Órgãos contratantes" valor={formatarInteiro(resumo.dados.por_orgao.length)} />
              </section>

              {(alertas.dados?.total ?? 0) > 0 && (
                <Secao id="alertas" titulo={`Sinais de alerta na cidade (${formatarInteiro(alertas.dados!.total)})`}>
                  <div className="space-y-3">
                    <AvisoAlertas />
                    {alertas.dados!.itens.map((a) => (
                      <CartaoAlerta key={a.id} alerta={a} tipos={tipos} />
                    ))}
                  </div>
                </Secao>
              )}

              <div className="grid gap-6 lg:grid-cols-2">
                <Secao id="fornecedores" titulo="Quem mais foi contratado" descricao="Pelo valor total dos contratos.">
                  <ListaBarras
                    rotuloLista="Maiores contratados"
                    itens={resumo.dados.fornecedores.map((f) => ({
                      chave: `${f.cpf_cnpj}-${f.nome}`,
                      rotulo: capitalizar(f.nome),
                      rotuloTexto: capitalizar(f.nome),
                      detalhe: `${formatarDocumento(f.cpf_cnpj)} · ${plural(f.qtd_empenhos, "contrato", "contratos")}`,
                      valor: f.total_pago,
                      href: f.tipo_pessoa === "PJ" && f.cpf_cnpj ? `/fornecedores/${f.cpf_cnpj}` : undefined,
                    }))}
                  />
                </Secao>
                <div className="space-y-6">
                  <Secao id="orgaos" titulo="Quem contratou" descricao="Clique para ver só os contratos do órgão.">
                    <ListaBarras
                      numerada={false}
                      rotuloLista="Órgãos contratantes"
                      itens={resumo.dados.por_orgao.map((o) => ({
                        chave: o.cnpj ?? o.nome,
                        rotulo: capitalizar(o.nome),
                        rotuloTexto: capitalizar(o.nome),
                        detalhe: plural(o.qtd, "contrato", "contratos"),
                        valor: o.total,
                        href: o.cnpj ? `?${new URLSearchParams({ ...(valores.ano ? { ano: valores.ano } : {}), orgao: o.cnpj })}#lista` : undefined,
                      }))}
                    />
                  </Secao>
                  <Secao id="categorias" titulo="O quê" descricao="Por categoria da contratação.">
                    <ListaBarras
                      numerada={false}
                      rotuloLista="Contratos por categoria"
                      itens={resumo.dados.por_categoria.map((c) => ({ chave: c.nome, rotulo: c.nome, rotuloTexto: c.nome, valor: c.total_pago }))}
                    />
                  </Secao>
                </div>
              </div>

              <section id="lista" aria-labelledby="titulo-lista" className="card min-w-0 space-y-4">
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <h2 id="titulo-lista" className="text-xl font-bold text-primary">Todos os contratos</h2>
                    {orgaoSelecionado && (
                      <p className="mt-1 text-sm text-secondary">
                        Só de {capitalizar(orgaoSelecionado.nome)} ·{" "}
                        <button type="button" className="link cursor-pointer" onClick={() => definir({ orgao: null })}>
                          ver todos
                        </button>
                      </p>
                    )}
                  </div>
                  <div className="w-full max-w-md">
                    <label htmlFor={idBusca} className="mb-1 block text-sm font-bold text-secondary">Buscar no objeto ou no contratado</label>
                    <div className="relative">
                      <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" />
                      <input id={idBusca} type="search" className="input pl-10" placeholder="Ex.: merenda, pavimentação, show"
                             autoComplete="off" value={texto} onChange={(e) => setTexto(e.target.value)} />
                    </div>
                  </div>
                </div>
                {lista.erro ? (
                  <ErroApi erro={lista.erro} onTentarDeNovo={lista.recarregar} />
                ) : !lista.dados ? (
                  <Carregando linhas={6} />
                ) : lista.dados.total === 0 ? (
                  <Vazio>Nenhum contrato encontrado.</Vazio>
                ) : (
                  <>
                    <div className="-mx-5 overflow-x-auto sm:mx-0 sm:rounded-lg sm:border sm:border-border" tabIndex={0} role="region" aria-label="Contratos">
                      <table className="w-full min-w-[52rem] text-left text-sm">
                        <caption className="sr-only">Contratos do município</caption>
                        <thead className="bg-muted text-secondary">
                          <tr>
                            <th scope="col" className="px-3 py-2.5 font-bold">Assinatura</th>
                            <th scope="col" className="px-3 py-2.5 font-bold">Contratado</th>
                            <th scope="col" className="px-3 py-2.5 font-bold">Objeto</th>
                            <th scope="col" className="px-3 py-2.5 text-right font-bold">Valor</th>
                            <th scope="col" className="px-3 py-2.5 font-bold">Contrato</th>
                          </tr>
                        </thead>
                        <tbody>
                          {lista.dados.itens.map((c) => (
                            <tr key={c.numero_controle} className="border-t border-border align-top hover:bg-background">
                              <td className="numero whitespace-nowrap px-3 py-2.5">
                                {formatarData(c.data_assinatura)}
                                {c.vigencia_fim && <span className="block text-muted-foreground">até {formatarData(c.vigencia_fim)}</span>}
                              </td>
                              <td className="px-3 py-2.5">
                                {c.tipo_pessoa === "PJ" && c.fornecedor_ni ? (
                                  <Link to={`/fornecedores/${c.fornecedor_ni}`} className="link">{capitalizar(c.fornecedor_nome)}</Link>
                                ) : (
                                  capitalizar(c.fornecedor_nome) || "—"
                                )}
                                <span className="numero block text-muted-foreground">{formatarDocumento(c.fornecedor_ni)}</span>
                              </td>
                              <td className="max-w-md px-3 py-2.5">
                                {c.objeto ?? "—"}
                                <span className="block text-muted-foreground">{capitalizar(c.orgao_nome)}</span>
                              </td>
                              <td className="numero whitespace-nowrap px-3 py-2.5 text-right font-bold">{formatarBRL(c.valor_global)}</td>
                              <td className="px-3 py-2.5">
                                {c.url ? (
                                  <a href={c.url} target="_blank" rel="noreferrer noopener" className="link inline-flex min-h-11 items-center gap-1 whitespace-nowrap">
                                    Ver no PNCP <ExternalLink aria-hidden className="size-4" />
                                    <span className="sr-only">(abre em nova aba)</span>
                                  </a>
                                ) : "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <Paginacao rotulo="Páginas de contratos" pagina={pagina} porPagina={POR_PAGINA} total={lista.dados.total}
                               onMudar={(p) => definir({ pagina: p })} />
                  </>
                )}
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}
