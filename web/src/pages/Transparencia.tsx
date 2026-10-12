import { Link } from "react-router";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { Paginacao } from "../components/Paginacao";
import { useApi } from "../lib/api";
import { formatarData, formatarInteiro } from "../lib/format";
import type { TransparenciaItem } from "../lib/types";
import { useParametros } from "../lib/useParametros";

const POR_PAGINA = 50;
const UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ",
  "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"];
const FIM_BIMESTRE = ["fev", "abr", "jun", "ago", "out", "dez"];
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

export function Transparencia() {
  const { valores, definir, pagina } = useParametros(["uf", "todos"] as const);
  const dados = useApi<{ total: number; com_pendencia: number; itens: TransparenciaItem[] }>("/api/transparencia", {
    uf: valores.uf, so_pendencias: valores.todos ? undefined : "true", limit: POR_PAGINA, offset: (pagina - 1) * POR_PAGINA,
  });
  return (
    <div className="space-y-6">
      <div className="max-w-3xl space-y-2">
        <h1 className="text-3xl font-bold text-primary sm:text-4xl">Transparência das prefeituras</h1>
        <p className="text-lg text-secondary">
          Prestar contas é obrigação. Aqui está quem não entregou o que a lei manda: relatórios ao Tesouro (bimestral
          e anual), dados ao tribunal de contas e contratos no Portal Nacional de Contratações, além de problemas que
          verificamos nos portais. As maiores cidades com pendência aparecem primeiro.
        </p>
      </div>
      <section aria-label="Filtros" className="card grid gap-4 sm:grid-cols-3">
        <CampoSelect rotulo="Estado" valor={valores.uf} opcoes={opcoesSimples(UFS)} onMudar={(uf) => definir({ uf })} />
        <CampoSelect rotulo="Mostrar" valor={valores.todos} todos="Só com pendência"
                     opcoes={[{ valor: "1", rotulo: "Todas as cidades" }]} onMudar={(todos) => definir({ todos })} />
        {dados.dados && (
          <p className="self-end text-secondary">
            <strong className="numero">{formatarInteiro(dados.dados.com_pendencia)}</strong> de{" "}
            {valores.todos ? formatarInteiro(dados.dados.total) : "todas as"} cidades{valores.uf ? ` de ${valores.uf}` : ""} com
            alguma pendência.
          </p>
        )}
      </section>
      {dados.erro ? (
        <ErroApi erro={dados.erro} onTentarDeNovo={dados.recarregar} />
      ) : !dados.dados ? (
        <Carregando linhas={8} rotulo="Calculando" />
      ) : dados.dados.itens.length === 0 ? (
        <Vazio>Nenhuma cidade com pendência neste filtro.</Vazio>
      ) : (
        <>
          <ul className="space-y-3">
            {dados.dados.itens.map((c) => (
              <li key={c.codigo_ibge} className="card space-y-2">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <h2 className="text-lg font-bold">
                    <Link to={`/cidade/${c.sigla_uf}/${encodeURIComponent(c.nome)}`} className="link">
                      {c.nome} – {c.sigla_uf}
                    </Link>
                  </h2>
                  <p className="numero text-sm text-muted-foreground">
                    {c.populacao ? `${formatarInteiro(c.populacao)} habitantes` : ""}
                  </p>
                </div>
                {c.pendencias.length > 0 ? (
                  <ul className="list-disc space-y-0.5 pl-5">
                    {c.pendencias.map((p) => <li key={p}>{p}</li>)}
                  </ul>
                ) : (
                  <p className="text-secondary">Sem pendências nas fontes que acompanhamos.</p>
                )}
                <p className="text-sm text-muted-foreground">
                  RREO: {c.rreo_bimestre ? `até ${FIM_BIMESTRE[c.rreo_bimestre - 1]}` : "nenhum no ano"}
                  {" · "}DCA do ano passado: {c.dca_anterior ? "entregue" : "não entregue"}
                  {c.tribunal && c.tribunal_ultimo_mes && ` · ${c.tribunal}: até ${MESES[(c.tribunal_ultimo_mes % 100) - 1]}/${Math.floor(c.tribunal_ultimo_mes / 100)}`}
                  {" · "}PNCP: {c.ultimo_contrato_pncp ? `último contrato em ${formatarData(c.ultimo_contrato_pncp)}` : "nenhum contrato"}
                </p>
              </li>
            ))}
          </ul>
          <Paginacao rotulo="Páginas" pagina={pagina} porPagina={POR_PAGINA} total={valores.todos ? dados.dados.total : dados.dados.com_pendencia}
                     onMudar={(p) => definir({ pagina: p })} />
        </>
      )}
      <p className="text-sm text-muted-foreground">
        Fontes: Siconfi/Tesouro Nacional (RREO e DCA), tribunais de contas de PE, SP e PB, PNCP e verificação manual dos
        portais. Uma pendência pode ter explicação (sistema fora do ar, entrega em andamento); a prefeitura pode
        contestar pelo link “Contestar ou corrigir”.
      </p>
    </div>
  );
}
