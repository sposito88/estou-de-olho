import { ArrowDown, ArrowUp, Landmark, Users, Wallet } from "lucide-react";
import { useParams } from "react-router";
import { CabecalhoCidade } from "../components/CabecalhoCidade";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { Secao } from "../components/Secao";
import { StatCard } from "../components/StatCard";
import { useApi } from "../lib/api";
import { formatarBRL, formatarInteiro, nomeProprio, paraNumero } from "../lib/format";
import type { ContasMunicipio, FuncaoConta } from "../lib/types";
import { useParametros } from "../lib/useParametros";

/** "+34%" / "−20%" do valor em relação à mediana; null se não der para comparar. */
function comparar(valor: string | null, mediana: string | null): number | null {
  const v = paraNumero(valor);
  const m = paraNumero(mediana);
  return valor !== null && mediana !== null && m > 0 ? Math.round(((v - m) / m) * 100) : null;
}

const FIM_BIMESTRE = ["fev", "abr", "jun", "ago", "out", "dez"];

function Diferenca({ pct }: { pct: number | null }) {
  if (pct === null) return <span className="text-muted-foreground">—</span>;
  if (Math.abs(pct) < 10) return <span className="text-muted-foreground">na média</span>;
  const acima = pct > 0;
  const Icone = acima ? ArrowUp : ArrowDown;
  return (
    <span className={`inline-flex items-center gap-0.5 font-bold ${acima ? "text-warning" : "text-accent"}`}>
      <Icone aria-hidden className="size-4" />
      {Math.abs(pct)}% {acima ? "acima" : "abaixo"}
    </span>
  );
}

export function Contas() {
  const { uf = "", municipio = "" } = useParams();
  const { valores, definir } = useParametros(["ano"] as const);
  const base = `/api/municipios/${encodeURIComponent(uf)}/${encodeURIComponent(municipio)}`;
  const contas = useApi<ContasMunicipio>(`${base}/contas`, { ano: valores.ano });
  const nome = nomeProprio(municipio);
  const ufMaiuscula = uf.toUpperCase();
  const parcial = contas.dados?.demonstrativo === "RREO";
  const ate = parcial && contas.dados?.bimestre ? `até ${FIM_BIMESTRE[contas.dados.bimestre - 1]}/${contas.dados.ano}` : "";
  const medida = parcial ? "liquidado" : "pago";

  return (
    <div className="space-y-6">
      <CabecalhoCidade uf={uf} municipio={municipio} />
      {contas.erro ? (
        <ErroApi erro={contas.erro} onTentarDeNovo={contas.recarregar} />
      ) : !contas.dados ? (
        <Carregando linhas={8} rotulo="Carregando contas" />
      ) : contas.dados.ano === null ? (
        <Vazio>As contas de {nome} ainda não foram carregadas do Siconfi (a coleta nacional pode estar em andamento).</Vazio>
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-4">
            {parcial ? (
              <p className="max-w-2xl text-secondary">
                <strong>{contas.dados.ano} ainda não terminou.</strong> Estes são os valores <strong>liquidados</strong>{" "}
                (serviço prestado ou material entregue) {ate}, segundo o relatório bimestral (RREO) enviado ao Tesouro
                Nacional, comparados com os municípios que já enviaram o mesmo bimestre. O balanço do ano inteiro (DCA)
                sai até abril de {contas.dados.ano + 1}.
              </p>
            ) : (
              <p className="max-w-2xl text-secondary">
                Quanto a prefeitura de {nome} pagou em cada área, segundo a declaração de contas anual (DCA) enviada ao
                Tesouro Nacional (Siconfi), e como isso se compara, por habitante, com os outros municípios.
              </p>
            )}
            <div className="w-full sm:w-48">
              <CampoSelect rotulo="Ano" valor={String(contas.dados.ano)} todos={null}
                           opcoes={opcoesSimples(contas.dados.anos)} onMudar={(ano) => definir({ ano })} />
            </div>
          </div>

          <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-3">
            <StatCard
              destaque
              icone={Wallet}
              rotulo={parcial ? "Despesa liquidada" : "Despesa paga"}
              valor={formatarBRL(contas.dados.total_pago)}
              detalhe={
                parcial
                  ? `${ate}${contas.dados.total_dotacao ? `, ${Math.round((paraNumero(contas.dados.total_pago) / paraNumero(contas.dados.total_dotacao)) * 100)}% do orçamento de ${formatarBRL(contas.dados.total_dotacao)}` : ""}`
                  : `em ${contas.dados.ano}`
              }
            />
            <StatCard
              icone={Users}
              rotulo="Por habitante"
              valor={contas.dados.por_habitante ? formatarBRL(contas.dados.por_habitante) : "—"}
              detalhe={contas.dados.mediana_uf_total ? `mediana em ${ufMaiuscula}: ${formatarBRL(contas.dados.mediana_uf_total)}` : undefined}
            />
            <StatCard
              icone={Landmark}
              rotulo="Habitantes"
              valor={contas.dados.populacao ? formatarInteiro(contas.dados.populacao) : "—"}
              detalhe="estimativa do IBGE"
            />
          </section>

          {contas.dados.destaques.length > 0 && (
            <aside className="space-y-2 rounded-xl border border-amber-300 bg-warning-soft p-4 text-primary">
              <p className="font-bold">Gastos que costumam chamar atenção</p>
              <ul className="space-y-1">
                {contas.dados.destaques.map((d) => (
                  <li key={d.codigo}>
                    <strong>{d.nome}</strong>: {formatarBRL(d.pago)}
                    {d.por_habitante && ` (${formatarBRL(d.por_habitante)} por habitante)`}
                  </li>
                ))}
              </ul>
            </aside>
          )}

          <Secao
            id="funcoes"
            titulo="Por área"
            descricao={`Valor ${medida}${parcial ? ` ${ate}` : ""} e por habitante, comparado à mediana dos ${contas.dados.amostra_uf} municípios de ${ufMaiuscula}${contas.dados.amostra_brasil > contas.dados.amostra_uf ? ` e dos ${contas.dados.amostra_brasil} do Brasil` : ""} ${parcial ? "no mesmo bimestre" : "no mesmo ano"}.`}
          >
            <TabelaFuncoes
              funcoes={contas.dados.funcoes}
              uf={ufMaiuscula}
              parcial={parcial}
              comBrasil={contas.dados.amostra_brasil > contas.dados.amostra_uf}
            />
            {contas.dados.amostra_brasil <= contas.dados.amostra_uf && (
              <p className="mt-3 text-sm text-muted-foreground">
                A comparação com o Brasil aparece quando as contas dos outros estados terminarem de ser carregadas.
              </p>
            )}
          </Secao>
          <p className="text-sm text-muted-foreground">
            Fonte: Siconfi/Tesouro Nacional, {parcial ? "RREO, Anexo 02 (despesa por função, até o bimestre)" : "DCA, Anexo I-E (despesa por função)"}.
            Mediana: o valor do meio entre todos os municípios, menos sensível a extremos que a média.
          </p>
        </>
      )}
    </div>
  );
}

function TabelaFuncoes({
  funcoes,
  uf,
  comBrasil,
  parcial,
}: {
  funcoes: FuncaoConta[];
  uf: string;
  comBrasil: boolean;
  parcial: boolean;
}) {
  return (
    <div className="-mx-5 overflow-x-auto sm:mx-0 sm:rounded-lg sm:border sm:border-border" tabIndex={0} role="region" aria-label="Despesa por área">
      <table className="w-full min-w-[44rem] text-left text-sm">
        <caption className="sr-only">Despesa por área</caption>
        <thead className="bg-muted text-secondary">
          <tr>
            <th scope="col" className="px-3 py-2.5 font-bold">Área</th>
            <th scope="col" className="px-3 py-2.5 text-right font-bold">{parcial ? "Liquidado" : "Pago"}</th>
            {parcial && <th scope="col" className="px-3 py-2.5 text-right font-bold">Do orçamento</th>}
            <th scope="col" className="px-3 py-2.5 text-right font-bold">Por habitante</th>
            <th scope="col" className="px-3 py-2.5 font-bold">vs. {uf}</th>
            {comBrasil && <th scope="col" className="px-3 py-2.5 font-bold">vs. Brasil</th>}
          </tr>
        </thead>
        <tbody>
          {funcoes.map((f) => (
            <tr key={f.codigo} className="border-t border-border hover:bg-background">
              <th scope="row" className="px-3 py-2.5 text-left font-bold">{f.nome}</th>
              <td className="numero whitespace-nowrap px-3 py-2.5 text-right">{formatarBRL(f.pago)}</td>
              {parcial && (
                <td className="numero whitespace-nowrap px-3 py-2.5 text-right">
                  {paraNumero(f.dotacao) ? `${Math.round((paraNumero(f.pago) / paraNumero(f.dotacao)) * 100)}%` : "—"}
                  {paraNumero(f.dotacao) > 0 && (
                    <span className="block text-muted-foreground">de {formatarBRL(f.dotacao)}</span>
                  )}
                </td>
              )}
              <td className="numero whitespace-nowrap px-3 py-2.5 text-right font-bold">{f.por_habitante ? formatarBRL(f.por_habitante) : "—"}</td>
              <td className="whitespace-nowrap px-3 py-2.5">
                <Diferenca pct={comparar(f.por_habitante, f.mediana_uf)} />
                {f.mediana_uf && <span className="numero block text-muted-foreground">mediana {formatarBRL(f.mediana_uf)}</span>}
              </td>
              {comBrasil && (
                <td className="whitespace-nowrap px-3 py-2.5">
                  <Diferenca pct={comparar(f.por_habitante, f.mediana_brasil)} />
                  {f.mediana_brasil && <span className="numero block text-muted-foreground">mediana {formatarBRL(f.mediana_brasil)}</span>}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
