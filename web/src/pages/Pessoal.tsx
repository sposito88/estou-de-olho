import { Search, UserPlus, Users, Wallet } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { useParams } from "react-router";
import { CabecalhoCidade, SemDadosMunicipais } from "../components/CabecalhoCidade";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { ListaBarras } from "../components/ListaBarras";
import { Paginacao } from "../components/Paginacao";
import { Secao } from "../components/Secao";
import { StatCard } from "../components/StatCard";
import { useApi } from "../lib/api";
import { capitalizar, formatarBRL, formatarData, formatarInteiro, nomeProprio, paraNumero, plural } from "../lib/format";
import type { Pagina, PessoalMunicipio, Servidor } from "../lib/types";
import { useParametros } from "../lib/useParametros";
import { useSemIndexacao } from "../lib/semIndexacao";

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const POR_PAGINA = 20;

export function Pessoal() {
  useSemIndexacao();
  const { uf = "", municipio = "" } = useParams();
  const { valores, definir } = useParametros(["ano"] as const);
  const base = `/api/municipios/${encodeURIComponent(uf)}/${encodeURIComponent(municipio)}`;
  const dados = useApi<PessoalMunicipio>(`${base}/pessoal`, { ano: valores.ano });
  const nome = nomeProprio(municipio);
  const d = dados.dados;
  const folhaAno = d?.folha_por_ano.find((f) => f.ano === d.ano);
  const nomeadosMandato = d?.por_vinculo.reduce((s, v) => s + v.no_mandato, 0) ?? 0;

  return (
    <div className="space-y-6">
      <CabecalhoCidade uf={uf} municipio={municipio} />
      {dados.erro?.status === 404 ? (
        <SemDadosMunicipais nome={nome} />
      ) : dados.erro ? (
        <ErroApi erro={dados.erro} onTentarDeNovo={dados.recarregar} />
      ) : !d ? (
        <Carregando linhas={8} rotulo="Carregando pessoal" />
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <p className="max-w-2xl text-secondary">
              Quem trabalha para a Prefeitura de {nome} e seus órgãos (sem a câmara), segundo a lista de pessoal que a
              prefeitura informa ao Tribunal de Contas, quanto custa a folha e quais pessoas físicas recebem por serviço
              ou aluguel.
            </p>
            {d.anos.length > 0 && (
              <div className="w-full sm:w-48">
                <CampoSelect rotulo="Ano" valor={String(d.ano ?? "")} todos={null} opcoes={opcoesSimples(d.anos)}
                             onMudar={(ano) => definir({ ano })} />
              </div>
            )}
          </div>

          <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-3">
            <StatCard
              destaque
              icone={Users}
              rotulo="Pessoas na lista de pessoal"
              valor={formatarInteiro(d.qtd_pessoas)}
              detalhe={`${formatarInteiro(d.qtd_vinculos)} vínculos${d.remessa ? `, lista de ${MESES[(d.remessa.mes ?? 1) - 1]}/${d.remessa.ano}` : ""}`}
            />
            <StatCard
              icone={UserPlus}
              rotulo="Admitidas no mandato"
              valor={formatarInteiro(nomeadosMandato)}
              detalhe={`desde jan/${d.inicio_mandato}, todos os vínculos`}
            />
            <StatCard
              icone={Wallet}
              rotulo={`Folha paga em ${d.ano ?? "—"}`}
              valor={folhaAno ? formatarBRL(folhaAno.total) : "—"}
              detalhe="salários, temporários, encargos e aposentadorias"
            />
          </section>

          <p className="rounded-lg bg-muted px-4 py-3 text-sm text-secondary">
            <strong>Como ler:</strong> a lista do Tribunal de Contas acumula os vínculos informados ao longo dos anos e{" "}
            <strong>não traz a data de saída</strong>; por isso pode incluir quem já não trabalha mais na prefeitura. O{" "}
            <strong>salário de cada pessoa não está nos dados abertos</strong>: a folha aparece somada, por secretaria e
            tipo de vínculo. O valor individual só está no portal de transparência da prefeitura.
          </p>

          {d.doadores_nomeados.length > 0 && (
            <Secao
              id="doadores"
              titulo={`Admitidos no mandato que doaram para campanhas de 2024 (${d.doadores_nomeados.length})`}
              descricao="Mesmo nome e mesmos 6 dígitos do CPF na lista de pessoal e na prestação de contas eleitoral do TSE."
            >
              <p className="mb-3 rounded-lg bg-warning-soft px-4 py-3 text-sm text-warning">
                <strong>Não é acusação.</strong> Doar para campanha é legal, e cargos comissionados são de livre
                nomeação. O cruzamento mostra uma relação que o cidadão tem o direito de conhecer.
              </p>
              <ul className="space-y-2">
                {d.doadores_nomeados.map((p) => (
                  <li key={`${p.nome}-${p.candidato}`} className="rounded-lg border border-border p-3">
                    <p className="font-bold text-primary">{nomeProprio(p.nome)}</p>
                    <p className="text-sm">
                      {capitalizar(p.cargo) || "Cargo não informado"} · {p.vinculo ?? "vínculo não informado"}
                      {p.data_admissao && `, admissão em ${formatarData(p.data_admissao)}`}
                    </p>
                    <p className="text-sm text-secondary">
                      Doou <strong className="numero">{formatarBRL(p.doado)}</strong> para{" "}
                      {nomeProprio(p.candidato)} ({capitalizar(p.cargo_candidato)}, {p.partido ?? "sem partido"}
                      {p.eleito ? ", eleito" : ""}) em 2024.
                    </p>
                  </li>
                ))}
              </ul>
            </Secao>
          )}

          <div className="grid gap-6 lg:grid-cols-2">
            <Secao id="vinculos" titulo="Por tipo de vínculo" descricao="Pessoas diferentes, vínculos e quantas foram admitidas no mandato atual.">
              <div className="-mx-5 overflow-x-auto sm:mx-0" tabIndex={0} role="region" aria-label="Pessoal por vínculo">
                <table className="w-full min-w-[28rem] text-left text-sm">
                  <caption className="sr-only">Pessoal por tipo de vínculo</caption>
                  <thead className="bg-muted text-secondary">
                    <tr>
                      <th scope="col" className="px-3 py-2.5 font-bold">Vínculo</th>
                      <th scope="col" className="px-3 py-2.5 text-right font-bold">Pessoas</th>
                      <th scope="col" className="px-3 py-2.5 text-right font-bold">Vínculos</th>
                      <th scope="col" className="px-3 py-2.5 text-right font-bold">No mandato</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.por_vinculo.map((v) => (
                      <tr key={v.nome} className="border-t border-border">
                        <th scope="row" className="px-3 py-2.5 text-left font-bold">{v.nome}</th>
                        <td className="numero px-3 py-2.5 text-right">{formatarInteiro(v.pessoas)}</td>
                        <td className="numero px-3 py-2.5 text-right">{formatarInteiro(v.vinculos)}</td>
                        <td className="numero px-3 py-2.5 text-right">{formatarInteiro(v.no_mandato)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-sm text-muted-foreground">
                Contratos temporários costumam ser renovados: a mesma pessoa aparece em vários vínculos.
              </p>
            </Secao>

            <Secao id="admissoes" titulo="Admissões por ano" descricao="Vínculos novos a cada ano, de todos os tipos.">
              <ListaBarras
                numerada={false}
                rotuloLista="Admissões por ano"
                itens={[...d.admissoes_por_ano].reverse().map((a) => {
                  const total = a.por_vinculo.reduce((s, v) => s + v.qtd, 0);
                  return {
                    chave: a.ano,
                    rotulo: String(a.ano),
                    rotuloTexto: String(a.ano),
                    detalhe: a.por_vinculo.map((v) => `${v.nome}: ${formatarInteiro(v.qtd)}`).join(" · "),
                    valor: total,
                  };
                })}
                formatarValor={(v) => formatarInteiro(paraNumero(v))}
              />
            </Secao>
          </div>

          {d.folha_por_mes.length > 0 && (
            <Secao
              id="folha"
              titulo={`Custo da folha mês a mês em ${d.ano}`}
              descricao={
                d.folha_pela_data_do_pagamento
                  ? "Valor pago com despesas de pessoal, pelo mês em que o dinheiro saiu do caixa."
                  : "Valor pago nos empenhos de pessoal, pelo mês do empenho (a folha costuma ser empenhada de uma vez no início do ano)."
              }
            >
              <div className="-mx-5 overflow-x-auto sm:mx-0" tabIndex={0} role="region" aria-label="Folha por mês">
                <table className="w-full min-w-[48rem] text-left text-sm">
                  <caption className="sr-only">Folha de pagamento por mês e categoria</caption>
                  <thead className="bg-muted text-secondary">
                    <tr>
                      <th scope="col" className="px-3 py-2.5 font-bold">Mês</th>
                      {d.categorias_folha.map((c) => (
                        <th key={c} scope="col" className="px-3 py-2.5 text-right font-bold">{c}</th>
                      ))}
                      <th scope="col" className="px-3 py-2.5 text-right font-bold">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.folha_por_mes.map((m) => (
                      <tr key={m.mes} className="border-t border-border">
                        <th scope="row" className="px-3 py-2.5 text-left font-bold">{MESES[m.mes - 1]}</th>
                        {m.por_categoria.map((c) => (
                          <td key={c.nome} className="numero whitespace-nowrap px-3 py-2.5 text-right">
                            {paraNumero(c.total) ? formatarBRL(c.total) : "—"}
                          </td>
                        ))}
                        <td className="numero whitespace-nowrap px-3 py-2.5 text-right font-bold">{formatarBRL(m.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {d.folha_por_ano.length > 1 && (
                <p className="mt-3 text-sm text-muted-foreground">
                  Por ano:{" "}
                  {d.folha_por_ano.map((f) => `${f.ano}: ${formatarBRL(f.total)}`).join(" · ")}. Dezembro costuma ser
                  maior por causa do 13º salário.
                </p>
              )}
            </Secao>
          )}

          <Secao
            id="prestadores"
            titulo={`Pessoas físicas pagas por serviço ou aluguel em ${d.ano}`}
            descricao={`${formatarBRL(d.prestadores_total)} para ${plural(d.prestadores_qtd, "pessoa", "pessoas")} (elemento "outros serviços de terceiros – pessoa física").`}
          >
            {d.prestadores.length === 0 ? (
              <Vazio>Nenhum pagamento a pessoa física por serviço neste ano.</Vazio>
            ) : (
              <ListaBarras
                rotuloLista="Pessoas físicas pagas pela prefeitura"
                itens={d.prestadores.map((p) => ({
                  chave: `${p.nome}-${p.cpf}`,
                  rotulo: nomeProprio(p.nome),
                  rotuloTexto: nomeProprio(p.nome),
                  detalhe: (
                    <>
                      {p.tipo} · {p.cpf ?? "CPF não informado"} · {plural(p.qtd_empenhos, "empenho", "empenhos")}
                      {p.servidor && (
                        <strong className="block text-warning">
                          Também na lista de pessoal: {capitalizar(p.servidor.cargo)} ({p.servidor.vinculo}
                          {p.servidor.data_admissao && `, admissão em ${formatarData(p.servidor.data_admissao)}`})
                        </strong>
                      )}
                      {p.exemplo && <span className="block">“{capitalizar(p.exemplo).slice(0, 160)}”</span>}
                    </>
                  ),
                  valor: p.total_pago,
                }))}
              />
            )}
          </Secao>

          <Secao id="cargos" titulo="Cargos com mais gente" descricao="Pessoas diferentes por cargo e vínculo, em toda a lista.">
            <ul className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
              {d.cargos.map((c) => (
                <li key={`${c.cargo}-${c.vinculo}`} className="flex justify-between gap-3 border-b border-border py-1">
                  <span>
                    {capitalizar(c.cargo)} <span className="text-muted-foreground">· {c.vinculo}</span>
                  </span>
                  <span className="numero font-bold">{formatarInteiro(c.pessoas)}</span>
                </li>
              ))}
            </ul>
          </Secao>

          <Secao id="lista" titulo="Lista de pessoal" descricao="Busque por nome ou cargo. Mais recentes primeiro.">
            <ListaPessoal base={base} vinculos={d.por_vinculo.map((v) => v.nome)} inicioMandato={d.inicio_mandato} />
          </Secao>

          <p className="text-sm text-muted-foreground">
            Fontes: API de dados abertos do TCE-PE (lista de pessoal, base Sagres, e empenhos) e TSE (doações de
            campanha). O CPF aparece mascarado, como o Tribunal publica.
          </p>
        </>
      )}
    </div>
  );
}

function ListaPessoal({ base, vinculos, inicioMandato }: { base: string; vinculos: string[]; inicioMandato: number }) {
  const { valores, definir, pagina } = useParametros(["busca", "vinculo", "desde"] as const);
  const [texto, setTexto] = useState(valores.busca);
  const id = useId();
  useEffect(() => {
    const espera = setTimeout(() => {
      if (texto.trim() !== valores.busca) definir({ busca: texto.trim() });
    }, 400);
    return () => clearTimeout(espera);
  }, [texto, valores.busca, definir]);
  const lista = useApi<Pagina<Servidor>>(`${base}/pessoal/lista`, {
    busca: valores.busca,
    vinculo: valores.vinculo,
    desde: valores.desde,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-[2fr_1fr_1fr]">
        <div>
          <label htmlFor={id} className="mb-1 block text-sm font-bold text-secondary">Nome ou cargo</label>
          <div className="relative">
            <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" />
            <input id={id} type="search" className="input pl-10" placeholder="Ex.: professor, secretário, Maria"
                   autoComplete="off" value={texto} onChange={(e) => setTexto(e.target.value)} />
          </div>
        </div>
        <CampoSelect rotulo="Vínculo" valor={valores.vinculo} opcoes={opcoesSimples(vinculos)}
                     onMudar={(vinculo) => definir({ vinculo })} />
        <CampoSelect rotulo="Admitidos" valor={valores.desde} todos="Em qualquer ano"
                     opcoes={[{ valor: String(inicioMandato), rotulo: `No mandato (desde ${inicioMandato})` },
                              { valor: String(inicioMandato - 4), rotulo: `Desde ${inicioMandato - 4}` }]}
                     onMudar={(desde) => definir({ desde })} />
      </div>
      {lista.erro ? (
        <ErroApi erro={lista.erro} onTentarDeNovo={lista.recarregar} />
      ) : !lista.dados ? (
        <Carregando linhas={6} rotulo="Carregando lista de pessoal" />
      ) : lista.dados.total === 0 ? (
        <Vazio>Ninguém encontrado com esses filtros.</Vazio>
      ) : (
        <>
          <div className="-mx-5 overflow-x-auto sm:mx-0 sm:rounded-lg sm:border sm:border-border" tabIndex={0} role="region" aria-label="Lista de pessoal">
            <table className="w-full min-w-[44rem] text-left text-sm">
              <caption className="sr-only">Lista de pessoal</caption>
              <thead className="bg-muted text-secondary">
                <tr>
                  <th scope="col" className="px-3 py-2.5 font-bold">Nome</th>
                  <th scope="col" className="px-3 py-2.5 font-bold">Cargo</th>
                  <th scope="col" className="px-3 py-2.5 font-bold">Vínculo</th>
                  <th scope="col" className="px-3 py-2.5 font-bold">Admissão</th>
                </tr>
              </thead>
              <tbody>
                {lista.dados.itens.map((s, i) => (
                  <tr key={`${s.nome}-${s.matricula}-${i}`} className="border-t border-border align-top">
                    <td className="px-3 py-2.5">
                      <span className="font-bold">{nomeProprio(s.nome)}</span>
                      {s.cpf && <span className="numero block text-muted-foreground">{s.cpf}</span>}
                    </td>
                    <td className="px-3 py-2.5">
                      {capitalizar(s.cargo) || "—"}
                      <span className="block text-muted-foreground">{s.orgao}</span>
                    </td>
                    <td className="px-3 py-2.5">{s.vinculo ?? "—"}</td>
                    <td className="numero whitespace-nowrap px-3 py-2.5">{formatarData(s.data_admissao)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Paginacao rotulo="Páginas da lista de pessoal" pagina={pagina} porPagina={POR_PAGINA}
                     total={lista.dados.total} onMudar={(p) => definir({ pagina: p })} />
        </>
      )}
    </div>
  );
}
