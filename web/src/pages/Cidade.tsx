import { Building2, Info, Landmark, Rss, Search, Users, Zap } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Link, useParams } from "react-router";
import { CabecalhoCidade } from "../components/CabecalhoCidade";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Compartilhar } from "../components/Compartilhar";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { ListaBarras } from "../components/ListaBarras";
import { Paginacao } from "../components/Paginacao";
import { Secao } from "../components/Secao";
import { SerieMensal } from "../components/SerieMensal";
import { StatCard } from "../components/StatCard";
import { montarUrl, useApi } from "../lib/api";
import { LINKS_EXTERNOS } from "../lib/config";
import {
  capitalizar,
  formatarBRL,
  formatarDocumento,
  formatarInteiro,
  formatarBRLCompacto,
  mesLongo,
  paraNumero,
  nomeProprio,
  partidoUf,
  plural,
} from "../lib/format";
import type {
  ComparacaoRegiao,
  CotaNaCidade,
  EmendasMunicipio,
  Filtros,
  Municipio,
  Pagina,
  PagamentoEmenda,
} from "../lib/types";
import { useParametros } from "../lib/useParametros";

const POR_PAGINA = 20;

export function Cidade() {
  const { uf = "", municipio = "" } = useParams();
  const { valores, definir, pagina } = useParametros(["ano"] as const);
  const filtros = useApi<Filtros>("/api/filtros");
  const base = `/api/municipios/${encodeURIComponent(uf)}/${encodeURIComponent(municipio)}`;
  const resumo = useApi<EmendasMunicipio>(`${base}/emendas`, { ano: valores.ano });
  const pagamentos = useApi<Pagina<PagamentoEmenda>>(`${base}/pagamentos`, {
    ano: valores.ano,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });

  const nome = resumo.dados ? nomeProprio(resumo.dados.municipio) : nomeProprio(municipio);
  const periodo = valores.ano ? `em ${valores.ano}` : "desde 2023";

  return (
    <div className="space-y-6">
      <CabecalhoCidade uf={uf} municipio={municipio} nome={nome} />

      <BuscaMunicipio />

      <aside className="flex gap-3 rounded-xl border border-sky-200 bg-accent-soft p-4 text-primary">
        <Info aria-hidden className="mt-0.5 size-5 shrink-0 text-accent" />
        <p>
          Deputado federal é eleito pelo estado inteiro, não pela cidade. O que liga um parlamentar a {nome} é a{" "}
          <strong>emenda parlamentar</strong>: dinheiro do orçamento federal que ele indica para um destino. Abaixo
          está tudo o que foi <strong>efetivamente pago</strong> a prefeitura, fundos e entidades da cidade, e quem
          mandou.
        </p>
      </aside>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="w-full sm:w-56">
          <CampoSelect
            rotulo="Ano do pagamento"
            valor={valores.ano}
            todos="Todos os anos"
            opcoes={opcoesSimples(filtros.dados?.anos_emendas ?? [])}
            onMudar={(ano) => definir({ ano })}
          />
        </div>
      </div>

      {resumo.erro?.status === 404 ? (
        <Vazio>
          Nenhum pagamento de emenda para {nome} {periodo}. Confira o nome da cidade ou escolha outro ano.
        </Vazio>
      ) : resumo.erro ? (
        <ErroApi erro={resumo.erro} onTentarDeNovo={resumo.recarregar} />
      ) : !resumo.dados ? (
        <Carregando linhas={8} rotulo="Carregando emendas" />
      ) : (
        <ConteudoCidade resumo={resumo.dados} periodo={periodo} base={base} ano={valores.ano} />
      )}

      {resumo.dados && (
        <Secao
          id="pagamentos"
          titulo="Todos os pagamentos"
          descricao="Cada repasse de emenda a um favorecido da cidade, do mais recente para o mais antigo."
        >
          {pagamentos.erro ? (
            <ErroApi erro={pagamentos.erro} onTentarDeNovo={pagamentos.recarregar} />
          ) : !pagamentos.dados ? (
            <Carregando linhas={6} />
          ) : (
            <>
              <TabelaPagamentos itens={pagamentos.dados.itens} />
              <Paginacao
                rotulo="Páginas dos pagamentos"
                pagina={pagina}
                porPagina={POR_PAGINA}
                total={pagamentos.dados.total}
                onMudar={(p) => definir({ pagina: p })}
              />
            </>
          )}
        </Secao>
      )}

      <p className="text-sm text-muted-foreground">
        Fonte: download de emendas parlamentares do{" "}
        <a className="link" href={LINKS_EXTERNOS.portalTransparencia} target="_blank" rel="noreferrer noopener">
          Portal da Transparência
        </a>{" "}
        (arquivo de pagamentos por favorecido). Emendas de bancada e de comissão aparecem pelo nome do colegiado.
      </p>
    </div>
  );
}

interface ConteudoCidadeProps {
  resumo: EmendasMunicipio;
  periodo: string;
  base: string;
  ano: string;
}

function ConteudoCidade({ resumo, periodo, base, ano }: ConteudoCidadeProps) {
  const deputados = resumo.por_autor.filter((a) => a.deputado).length;
  const nome = nomeProprio(resumo.municipio);
  const comparacao = useApi<ComparacaoRegiao>(`${base}/comparacao`, { ano });
  const cota = useApi<CotaNaCidade>(`${base}/cota`, { ano });
  const pctPix = paraNumero(resumo.total_recebido) ? paraNumero(resumo.total_pix) / paraNumero(resumo.total_recebido) : 0;
  const posicao = comparacao.dados ? comparacao.dados.municipios.findIndex((m) => m.atual) + 1 : 0;

  return (
    <>
      <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          destaque
          icone={Landmark}
          rotulo="Recebido em emendas"
          valor={formatarBRL(resumo.total_recebido)}
          detalhe={`${periodo} · ${plural(resumo.qtd_pagamentos, "pagamento", "pagamentos")}`}
        />
        <StatCard
          icone={Users}
          rotulo="Por habitante"
          valor={resumo.por_habitante ? formatarBRL(resumo.por_habitante) : "—"}
          detalhe={resumo.populacao ? `${formatarInteiro(resumo.populacao)} habitantes (IBGE ${resumo.ano_populacao})` : undefined}
        />
        <StatCard
          icone={Zap}
          rotulo="Emenda Pix"
          valor={formatarBRL(resumo.total_pix)}
          detalhe={`${Math.round(pctPix * 100)}% do total, com menos rastreio`}
        />
        <StatCard
          icone={Building2}
          rotulo="Autores"
          valor={formatarInteiro(resumo.qtd_autores)}
          detalhe={`${plural(deputados, "deputado(a) atual", "deputados atuais")}; o resto são bancadas, comissões ou senadores`}
        />
      </section>

      <section aria-label="Compartilhar e acompanhar" className="card flex flex-wrap items-start justify-between gap-4">
        <Compartilhar
          texto={`${nome} recebeu ${formatarBRL(resumo.total_recebido)} em emendas parlamentares ${periodo}. Veja quem mandou:`}
          dados={{
            chamada: `Emendas parlamentares ${periodo}`,
            titulo: `${nome} – ${resumo.sigla_uf}`,
            destaque: formatarBRL(resumo.total_recebido),
            legendaDestaque: resumo.por_habitante
              ? `${formatarBRL(resumo.por_habitante)} por habitante`
              : "recebidos em emendas",
            linhas: resumo.por_autor.slice(0, 4).map((a) => ({
              rotulo: a.deputado ? a.deputado.nome : nomeProprio(a.nome_autor),
              valor: formatarBRLCompacto(a.total_recebido),
            })),
            arquivo: `estou-de-olho-${resumo.sigla_uf}-${resumo.municipio}`.toLowerCase().replace(/\s+/g, "-"),
          }}
        />
        <a href={montarUrl(`${base}/feed.xml`)} className="link inline-flex min-h-11 items-center gap-1.5">
          <Rss aria-hidden className="size-5" /> Acompanhar novos pagamentos (feed RSS)
        </a>
      </section>

      {resumo.total_pix !== "0.00" && (
        <aside className="flex gap-3 rounded-xl border border-amber-300 bg-warning-soft p-4 text-primary">
          <Zap aria-hidden className="mt-0.5 size-5 shrink-0 text-warning" />
          <p>
            <strong>Emenda Pix</strong> (transferência especial) cai direto no caixa da prefeitura, sem projeto nem
            convênio definidos antes. {formatarBRL(resumo.total_pix)} chegaram assim a {nome}.{" "}
            <Link to="emenda-pix" relative="path" className="link font-bold">
              Veja o que a prefeitura prometeu fazer e o que informou como gasto
            </Link>
            .
          </p>
        </aside>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Secao id="autores" titulo="Quem mandou dinheiro" descricao="Autores das emendas, pelo total pago à cidade.">
          <ListaBarras
            rotuloLista="Autores das emendas"
            itens={resumo.por_autor.map((a) => ({
              chave: a.nome_autor,
              rotulo: a.deputado ? a.deputado.nome : nomeProprio(a.nome_autor),
              rotuloTexto: a.deputado ? a.deputado.nome : nomeProprio(a.nome_autor),
              detalhe: a.deputado
                ? `Deputado(a) · ${partidoUf(a.deputado.sigla_partido, a.deputado.sigla_uf)}`
                : "Bancada, comissão, senador(a) ou ex-deputado(a)",
              valor: a.total_recebido,
              href: a.deputado ? `/deputados/${a.deputado.id}` : undefined,
              imagem: a.deputado ? a.deputado.url_foto : undefined,
            }))}
          />
        </Secao>

        <Secao
          id="regiao"
          titulo="Comparada com a região"
          descricao={
            comparacao.dados
              ? `Emendas por habitante nas cidades da região de ${comparacao.dados.regiao_imediata} (IBGE). ${nome} está em ${posicao}º de ${comparacao.dados.municipios.length}.`
              : "Emendas por habitante nas cidades vizinhas."
          }
        >
          {comparacao.erro ? (
            <ErroApi erro={comparacao.erro} onTentarDeNovo={comparacao.recarregar} />
          ) : !comparacao.dados ? (
            <Carregando linhas={5} />
          ) : (
            <ListaBarras
              rotuloLista="Emendas por habitante na região"
              itens={comparacao.dados.municipios.map((m) => ({
                chave: m.codigo_ibge,
                rotulo: m.atual ? `${m.municipio} (esta cidade)` : m.municipio,
                rotuloTexto: m.municipio,
                detalhe: `${formatarBRLCompacto(m.total_recebido)} no total${m.populacao ? ` · ${formatarInteiro(m.populacao)} hab.` : ""}`,
                valor: m.por_habitante ?? "0",
                href: m.atual ? undefined : `/cidade/${m.sigla_uf}/${encodeURIComponent(m.municipio)}`,
              }))}
            />
          )}
        </Secao>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Secao id="acoes" titulo="O que foi financiado" descricao="Ação do orçamento federal de cada pagamento.">
          <ListaBarras
            numerada={false}
            rotuloLista="Valor recebido por ação"
            itens={resumo.por_acao.map((a) => ({
              chave: a.acao,
              rotulo: capitalizar(a.acao),
              rotuloTexto: capitalizar(a.acao),
              valor: a.total,
            }))}
          />
        </Secao>

        <Secao id="areas" titulo="Por área" descricao="Área do orçamento de cada emenda paga.">
          <ListaBarras
            numerada={false}
            rotuloLista="Valor recebido por área"
            itens={resumo.por_funcao.map((f) => ({ chave: f.funcao, rotulo: f.funcao, rotuloTexto: f.funcao, valor: f.total }))}
          />
        </Secao>
      </div>

      {resumo.serie_mensal.length > 0 && (
        <Secao id="serie" titulo="Quando o dinheiro chegou" descricao="Total pago por mês.">
          <SerieMensal
            titulo={`Emendas pagas em ${nome}`}
            pontos={resumo.serie_mensal.map((s) => ({ ano: s.ano, mes: s.mes, valor: s.total_recebido }))}
          />
        </Secao>
      )}

      <Secao id="favorecidos" titulo="Quem recebeu" descricao="Órgãos e entidades da cidade que receberam os pagamentos.">
        <ListaBarras
          numerada={false}
          rotuloLista="Favorecidos"
          itens={resumo.por_favorecido.map((f) => ({
            chave: `${f.codigo_favorecido}-${f.favorecido}`,
            rotulo: capitalizar(f.favorecido),
            rotuloTexto: capitalizar(f.favorecido),
            detalhe: [formatarDocumento(f.codigo_favorecido), plural(f.qtd_pagamentos, "pagamento", "pagamentos")].join(" · "),
            valor: f.total_recebido,
          }))}
        />
      </Secao>

      <Secao
        id="cota"
        titulo={`Cota parlamentar gasta em empresas de ${nome}`}
        descricao="Notas fiscais de qualquer deputado federal emitidas por empresas com sede na cidade."
      >
        {cota.erro ? (
          <ErroApi erro={cota.erro} onTentarDeNovo={cota.recarregar} />
        ) : !cota.dados ? (
          <Carregando linhas={4} />
        ) : !cota.dados.base_cnpj_carregada ? (
          <Vazio>A base de CNPJ da Receita ainda está sendo carregada. Volte mais tarde.</Vazio>
        ) : cota.dados.qtd_despesas === 0 ? (
          <Vazio>Nenhuma nota da cota emitida por empresa de {nome} {periodo}.</Vazio>
        ) : (
          <div className="space-y-5">
            <p className="text-lg">
              <strong className="numero">{formatarBRL(cota.dados.total_liquido)}</strong> em{" "}
              {plural(cota.dados.qtd_despesas, "nota", "notas")}.
            </p>
            <div className="grid gap-6 lg:grid-cols-2">
              <div>
                <h3 className="mb-3 font-bold text-secondary">Empresas</h3>
                <ListaBarras
                  rotuloLista={`Empresas de ${nome} pagas com a cota`}
                  itens={cota.dados.por_fornecedor.map((f) => ({
                    chave: f.cnpj,
                    rotulo: f.nome ?? formatarDocumento(f.cnpj),
                    rotuloTexto: f.nome ?? f.cnpj,
                    detalhe: plural(f.qtd_deputados, "deputado", "deputados"),
                    valor: f.total_liquido,
                    href: `/fornecedores/${f.cnpj}`,
                  }))}
                />
              </div>
              <div>
                <h3 className="mb-3 font-bold text-secondary">Deputados que pagaram</h3>
                <ListaBarras
                  rotuloLista={`Deputados que pagaram empresas de ${nome}`}
                  itens={cota.dados.por_deputado.map((d) => ({
                    chave: d.deputado.id,
                    rotulo: d.deputado.nome,
                    rotuloTexto: d.deputado.nome,
                    detalhe: partidoUf(d.deputado.sigla_partido, d.deputado.sigla_uf),
                    valor: d.total_liquido,
                    href: `/deputados/${d.deputado.id}`,
                    imagem: d.deputado.url_foto,
                  }))}
                />
              </div>
            </div>
          </div>
        )}
      </Secao>
    </>
  );
}

function TabelaPagamentos({ itens }: { itens: PagamentoEmenda[] }) {
  if (itens.length === 0) return <Vazio>Nenhum pagamento.</Vazio>;
  return (
    <div className="-mx-5 overflow-x-auto sm:mx-0 sm:rounded-lg sm:border sm:border-border" tabIndex={0} role="region" aria-label="Pagamentos de emendas">
      <table className="w-full min-w-[52rem] text-left text-sm">
        <caption className="sr-only">Pagamentos de emendas</caption>
        <thead className="bg-muted text-secondary">
          <tr>
            <th scope="col" className="px-3 py-2.5 font-bold">Mês</th>
            <th scope="col" className="px-3 py-2.5 font-bold">Autor</th>
            <th scope="col" className="px-3 py-2.5 font-bold">Favorecido</th>
            <th scope="col" className="px-3 py-2.5 font-bold">Para quê</th>
            <th scope="col" className="px-3 py-2.5 font-bold">Emenda</th>
            <th scope="col" className="px-3 py-2.5 text-right font-bold">Valor</th>
          </tr>
        </thead>
        <tbody>
          {itens.map((p) => (
            <tr key={p.id} className="border-t border-border align-top hover:bg-background">
              <td className="whitespace-nowrap px-3 py-2.5">{mesLongo(p.ano, p.mes)}</td>
              <td className="px-3 py-2.5">
                {p.deputado_id ? (
                  <Link to={`/deputados/${p.deputado_id}`} className="link">
                    {nomeProprio(p.nome_autor)}
                  </Link>
                ) : (
                  nomeProprio(p.nome_autor) || "—"
                )}
              </td>
              <td className="px-3 py-2.5">{capitalizar(p.favorecido) || "—"}</td>
              <td className="max-w-xs px-3 py-2.5">{capitalizar(p.objeto ?? p.acao) || "—"}</td>
              <td className="numero px-3 py-2.5">
                {p.codigo_emenda ?? "—"}
                {p.tipo_emenda && <span className="block font-sans text-muted-foreground">{p.tipo_emenda}</span>}
              </td>
              <td className="numero whitespace-nowrap px-3 py-2.5 text-right font-bold">{formatarBRL(p.valor_recebido)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Busca de município com resultados como links (sem combobox customizado: mais simples e acessível). */
function BuscaMunicipio() {
  const id = useId();
  const [texto, setTexto] = useState("");
  const [termo, setTermo] = useState("");

  useEffect(() => {
    const espera = setTimeout(() => setTermo(texto.trim()), 300);
    return () => clearTimeout(espera);
  }, [texto]);

  const resultados = useApi<Municipio[]>(termo.length >= 2 ? "/api/municipios" : null, { busca: termo, limit: 8 });

  return (
    <section aria-label="Trocar de cidade" className="card">
      <label htmlFor={id} className="mb-1 block font-bold text-secondary">
        Ver outra cidade
      </label>
      <div className="relative">
        <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" />
        <input
          id={id}
          type="search"
          className="input pl-10"
          placeholder="Digite o nome do município"
          autoComplete="off"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          aria-describedby={`${id}-ajuda`}
        />
      </div>
      <p id={`${id}-ajuda`} className="mt-1 text-sm text-muted-foreground">
        Pelo menos 2 letras. Acentos não importam.
      </p>
      {termo.length >= 2 && (
        <div className="mt-3" aria-live="polite">
          {resultados.erro ? (
            <ErroApi erro={resultados.erro} />
          ) : !resultados.dados ? (
            <Carregando linhas={2} rotulo="Buscando municípios" />
          ) : resultados.dados.length === 0 ? (
            <Vazio>Nenhum município com pagamentos de emenda encontrado para “{termo}”.</Vazio>
          ) : (
            <ul className="divide-y divide-border rounded-lg border border-border">
              {resultados.dados.map((m) => (
                <li key={`${m.sigla_uf}-${m.municipio}`}>
                  <Link
                    to={`/cidade/${m.sigla_uf}/${encodeURIComponent(m.municipio)}`}
                    onClick={() => setTexto("")}
                    className="flex min-h-11 items-center justify-between gap-3 px-3 py-2 hover:bg-background"
                  >
                    <span className="font-bold text-primary">
                      {nomeProprio(m.municipio)} – {m.sigla_uf}
                    </span>
                    <span className="numero text-sm text-muted-foreground">{formatarBRL(m.total_recebido)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
