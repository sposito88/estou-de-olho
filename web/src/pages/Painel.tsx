import { AlertTriangle, ArrowRight, FileText, Landmark, MapPin, Users, Wallet } from "lucide-react";
import { CampoBusca } from "../components/CampoBusca";
import { Link } from "react-router";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { ListaBarras } from "../components/ListaBarras";
import { Paginacao } from "../components/Paginacao";
import { Secao } from "../components/Secao";
import { StatCard } from "../components/StatCard";
import { TabelaDespesas } from "../components/TabelaDespesas";
import { useApi } from "../lib/api";
import { MUNICIPIO_PADRAO } from "../lib/config";
import { capitalizar, formatarBRL, rotuloDespesa, formatarInteiro, partidoUf, plural } from "../lib/format";
import type {
  DespesaComDeputado,
  Filtros,
  Pagina,
  RankingItem,
  ResumoAlertas,
  ResumoGastos,
  TipoDespesaItem,
} from "../lib/types";
import { useParametros } from "../lib/useParametros";

const POR_PAGINA = 20;
const TIPOS_VISIVEIS = 8;

export function Painel() {
  const { valores, definir, pagina } = useParametros(["ano", "uf", "partido", "ordem"] as const);
  const relativo = valores.ordem === "relativo";
  const filtros = useApi<Filtros>("/api/filtros");
  const params = { ano: valores.ano, uf: valores.uf, partido: valores.partido };

  const resumo = useApi<ResumoGastos>("/api/gastos/resumo", params);
  const ranking = useApi<RankingItem[]>("/api/gastos/ranking", { ...params, limit: 10, ordem: valores.ordem || "total" });
  const alertas = useApi<ResumoAlertas>("/api/alertas/resumo", params);
  const porTipo = useApi<TipoDespesaItem[]>("/api/gastos/por-tipo", params);
  const despesas = useApi<Pagina<DespesaComDeputado>>("/api/despesas", {
    ...params,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });

  const recorte = [valores.ano || "todos os anos", valores.uf || null, valores.partido || null].filter(Boolean).join(" · ");
  const cidade = `/cidade/${MUNICIPIO_PADRAO.uf}/${encodeURIComponent(MUNICIPIO_PADRAO.nome)}`;

  return (
    <div className="space-y-6">
      <section aria-labelledby="titulo-pagina" className="space-y-4 pb-2">
        <h1 id="titulo-pagina" className="max-w-3xl text-3xl font-bold leading-tight text-primary sm:text-4xl">
          Para onde vai o dinheiro público
        </h1>
        <p className="max-w-3xl text-lg text-secondary">
          Acompanhe o que gastam deputados federais, senadores e deputados estaduais, os contratos e as contas das
          prefeituras e câmaras de todo o Brasil e o dinheiro de emenda que chegou à sua cidade. Sempre com a nota, o
          contrato ou o empenho, e com sinais de alerta quando algo foge do padrão.
        </p>
        <div className="max-w-3xl">
          <CampoBusca rotulo="Busque o nome de uma pessoa ou empresa e veja onde ela aparece" grande />
        </div>
        <div className="flex flex-wrap gap-3">
          <Link to={cidade} className="btn-primary">
            <MapPin aria-hidden className="size-5" /> Ver {MUNICIPIO_PADRAO.nome}
          </Link>
          <Link to="/alertas" className="btn-secondary">
            <AlertTriangle aria-hidden className="size-5" /> Ver sinais de alerta
          </Link>
        </div>
      </section>

      <nav aria-label="Áreas do site">
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {AREAS.map(({ para, titulo, texto, Icone }) => (
            <li key={para}>
              <Link
                to={para === "/cidade" ? cidade : para}
                className="card flex h-full items-start gap-3 p-4 transition-colors duration-150 hover:border-accent sm:p-4"
              >
                <span aria-hidden className="grid size-10 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
                  <Icone className="size-5" />
                </span>
                <span>
                  <span className="block font-bold text-primary">{titulo}</span>
                  <span className="block text-sm text-secondary">{texto}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <div className="space-y-1 pt-4">
        <h2 className="text-2xl font-bold text-primary">Cota dos deputados federais</h2>
        <p className="max-w-3xl text-secondary">
          Cada deputado tem uma cota mensal para gastos do mandato: combustível, passagens, escritório e divulgação.
          Abaixo, quanto foi reembolsado, para quem e com qual nota fiscal.
        </p>
      </div>

      <section aria-labelledby="titulo-filtros" className="card">
        <h2 id="titulo-filtros" className="sr-only">Filtros</h2>
        {filtros.erro ? (
          <ErroApi erro={filtros.erro} onTentarDeNovo={filtros.recarregar} />
        ) : (
          <div className="grid gap-4 sm:grid-cols-3">
            <CampoSelect
              rotulo="Ano"
              valor={valores.ano}
              todos="Todos os anos"
              opcoes={opcoesSimples(filtros.dados?.anos ?? [])}
              onMudar={(ano) => definir({ ano })}
            />
            <CampoSelect
              rotulo="Estado"
              valor={valores.uf}
              opcoes={opcoesSimples(filtros.dados?.ufs ?? [])}
              onMudar={(uf) => definir({ uf })}
            />
            <CampoSelect
              rotulo="Partido"
              valor={valores.partido}
              opcoes={opcoesSimples(filtros.dados?.partidos ?? [])}
              onMudar={(partido) => definir({ partido })}
            />
          </div>
        )}
      </section>

      <section aria-labelledby="titulo-resumo">
        <h2 id="titulo-resumo" className="sr-only">
          Resumo de {recorte}
        </h2>
        {resumo.erro ? (
          <ErroApi erro={resumo.erro} onTentarDeNovo={resumo.recarregar} />
        ) : (
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard
              destaque
              icone={Wallet}
              rotulo="Total reembolsado"
              valor={resumo.dados ? formatarBRL(resumo.dados.total_liquido) : "…"}
              detalhe={capitalizar(recorte)}
            />
            <StatCard
              icone={Users}
              rotulo="Deputados com gastos"
              valor={resumo.dados ? formatarInteiro(resumo.dados.qtd_deputados) : "…"}
            />
            <StatCard
              icone={FileText}
              rotulo="Despesas"
              valor={resumo.dados ? formatarInteiro(resumo.dados.qtd_despesas) : "…"}
              detalhe="notas, recibos e bilhetes"
            />
          </div>
        )}
      </section>

      {alertas.dados && alertas.dados.total > 0 && (
        <Link
          to={`/alertas?${new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][])}`}
          className="card flex flex-wrap items-center justify-between gap-4 border-amber-300 bg-warning-soft transition-colors duration-150 hover:border-amber-500"
        >
          <span className="flex items-start gap-3">
            <AlertTriangle aria-hidden className="mt-0.5 size-6 shrink-0 text-warning" />
            <span>
              <span className="block text-lg font-bold text-primary">
                {formatarInteiro(alertas.dados.total)} sinais de alerta ({formatarInteiro(alertas.dados.altas)} de atenção)
              </span>
              <span className="block text-secondary">
                Empresas recém-abertas, fornecedores que vivem de um só pagador, CNPJ baixado recebendo, servidores e
                doadores de campanha sócios de fornecedores, e mais.
              </span>
            </span>
          </span>
          <span className="inline-flex items-center gap-1 font-bold text-accent">
            Ver alertas <ArrowRight aria-hidden className="size-5" />
          </span>
        </Link>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Secao
          id="ranking"
          titulo={relativo ? "Quem mais gastou para o próprio estado" : "Quem mais gastou"}
          descricao={
            relativo
              ? "O teto da cota muda de estado para estado. Aqui cada deputado é comparado à média dos colegas do mesmo estado."
              : "Os 10 maiores totais reembolsados no filtro. Estados distantes de Brasília têm teto maior."
          }
          acoes={
            <div role="group" aria-label="Ordenar ranking" className="flex rounded-lg border border-border p-1">
              {[
                ["total", "Total"],
                ["relativo", "Comparado ao estado"],
              ].map(([valor, rotulo]) => {
                const ativo = (valores.ordem || "total") === valor;
                return (
                  <button
                    key={valor}
                    type="button"
                    aria-pressed={ativo}
                    onClick={() => definir({ ordem: valor === "total" ? null : valor })}
                    className={`min-h-10 cursor-pointer rounded-md px-3 text-sm font-bold transition-colors duration-150 ${
                      ativo ? "bg-primary text-on-primary" : "text-secondary hover:bg-muted"
                    }`}
                  >
                    {rotulo}
                  </button>
                );
              })}
            </div>
          }
        >
          {ranking.erro ? (
            <ErroApi erro={ranking.erro} onTentarDeNovo={ranking.recarregar} />
          ) : !ranking.dados ? (
            <Carregando linhas={6} />
          ) : ranking.dados.length === 0 ? (
            <Vazio>Nenhum gasto encontrado para esse filtro.</Vazio>
          ) : (
            <ListaBarras
              rotuloLista="Deputados que mais gastaram"
              itens={ranking.dados.map((r) => ({
                chave: r.deputado.id,
                rotulo: r.deputado.nome,
                rotuloTexto: `${r.deputado.nome} (${partidoUf(r.deputado.sigla_partido, r.deputado.sigla_uf)})`,
                detalhe:
                  relativo && r.indice_uf !== null
                    ? `${partidoUf(r.deputado.sigla_partido, r.deputado.sigla_uf)} · ${descreverIndice(r.indice_uf)} da média do estado`
                    : `${partidoUf(r.deputado.sigla_partido, r.deputado.sigla_uf)} · ${plural(r.qtd_despesas, "despesa", "despesas")}`,
                valor: r.total_liquido,
                // No modo relativo a barra mostra o quanto o gasto passa da média do estado.
                medida: relativo && r.indice_uf !== null ? Math.max(r.indice_uf - 1, 0) : undefined,
                href: `/deputados/${r.deputado.id}${valores.ano ? `?ano=${valores.ano}` : ""}`,
                imagem: r.deputado.url_foto,
              }))}
            />
          )}
        </Secao>

        <Secao id="tipos" titulo="Em que o dinheiro foi gasto" descricao="Total reembolsado por tipo de despesa.">
          {porTipo.erro ? (
            <ErroApi erro={porTipo.erro} onTentarDeNovo={porTipo.recarregar} />
          ) : !porTipo.dados ? (
            <Carregando linhas={6} />
          ) : porTipo.dados.length === 0 ? (
            <Vazio>Nenhum gasto encontrado para esse filtro.</Vazio>
          ) : (
            <ListaBarras
              numerada={false}
              rotuloLista="Gastos por tipo de despesa"
              itens={agruparOutros(porTipo.dados).map((t) => ({
                chave: t.tipo_despesa,
                rotulo: rotuloDespesa(t.tipo_despesa),
                rotuloTexto: rotuloDespesa(t.tipo_despesa),
                detalhe: plural(t.qtd_despesas, "despesa", "despesas"),
                valor: t.total_liquido,
              }))}
            />
          )}
        </Secao>
      </div>

      <Secao
        id="ultimas"
        titulo="Últimas despesas"
        descricao="Os lançamentos mais recentes. O valor é o que a Câmara reembolsou; quando houve corte (glosa), o valor da nota aparece embaixo."
      >
        {despesas.erro ? (
          <ErroApi erro={despesas.erro} onTentarDeNovo={despesas.recarregar} />
        ) : !despesas.dados ? (
          <Carregando linhas={8} />
        ) : despesas.dados.total === 0 ? (
          <Vazio>Nenhuma despesa encontrada para esse filtro.</Vazio>
        ) : (
          <>
            <TabelaDespesas despesas={despesas.dados.itens} legenda="Últimas despesas" mostrarDeputado />
            <Paginacao
              rotulo="Páginas das últimas despesas"
              pagina={pagina}
              porPagina={POR_PAGINA}
              total={despesas.dados.total}
              onMudar={(p) => definir({ pagina: p })}
            />
          </>
        )}
      </Secao>
    </div>
  );
}

const AREAS = [
  { para: "/cidade", titulo: "Minha cidade", texto: "Emendas, contratos, contas e eleitos de qualquer município", Icone: MapPin },
  { para: "/deputados", titulo: "Deputados federais", texto: "Cota parlamentar e emendas, nota por nota", Icone: Users },
  { para: "/senadores", titulo: "Senadores", texto: "Cota dos senadores, despesa por despesa", Icone: Landmark },
  { para: "/estaduais", titulo: "Deputados estaduais (PE)", texto: "Verba indenizatória da ALEPE", Icone: FileText },
] as const;

/** Mantém os maiores tipos e soma o resto em "Outros" (valores em centavos para não perder precisão). */
function agruparOutros(tipos: TipoDespesaItem[]): TipoDespesaItem[] {
  if (tipos.length <= TIPOS_VISIVEIS + 1) return tipos;
  const visiveis = tipos.slice(0, TIPOS_VISIVEIS);
  const resto = tipos.slice(TIPOS_VISIVEIS);
  const centavos = resto.reduce((s, t) => s + Math.round(Number(t.total_liquido) * 100), 0);
  return [
    ...visiveis,
    {
      tipo_despesa: `Outros (${resto.length} tipos)`,
      total_liquido: (centavos / 100).toFixed(2),
      qtd_despesas: resto.reduce((s, t) => s + t.qtd_despesas, 0),
    },
  ];
}

/** 1.34 -> "34% acima"; 0.8 -> "20% abaixo". */
function descreverIndice(indice: number): string {
  const diferenca = Math.round((indice - 1) * 100);
  if (diferenca === 0) return "na";
  return `${Math.abs(diferenca)}% ${diferenca > 0 ? "acima" : "abaixo"}`;
}
