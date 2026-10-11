import { ArrowDownToLine, Receipt, Wrench } from "lucide-react";
import { useParams } from "react-router";
import { CabecalhoCidade } from "../components/CabecalhoCidade";
import { AvisoAlertas, CartaoAlerta, useTiposAlerta } from "../components/CartaoAlerta";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { ListaBarras } from "../components/ListaBarras";
import { Secao } from "../components/Secao";
import { StatCard } from "../components/StatCard";
import { TabelaEmpenhos } from "../components/TabelaEmpenhos";
import { useApi } from "../lib/api";
import { capitalizar, formatarBRL, formatarData, formatarDocumento, nomeProprio, paraNumero, plural } from "../lib/format";
import type { Alerta, EmendaPix as DadosPix, Pagina, PlanoPix } from "../lib/types";

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

function pct(parte: string | number, total: string | number): string {
  const t = paraNumero(total);
  return t ? `${Math.round((paraNumero(parte) / t) * 100)}%` : "—";
}

function CartaoPlano({ plano }: { plano: PlanoPix }) {
  const impedido = plano.situacao === "IMPEDIDO";
  const declarado = paraNumero(plano.custeio) + paraNumero(plano.investimento);
  return (
    <li className="rounded-lg border border-border p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="font-bold text-primary">
          {plano.ano} · {plano.parlamentar ?? "Parlamentar não informado"}
        </p>
        <p className="numero font-bold">
          {paraNumero(plano.recebido) > 0 ? (
            <>
              {formatarBRL(plano.recebido)}{" "}
              <span className="font-normal text-muted-foreground">
                recebidos{plano.ultimo_repasse && ` em ${formatarData(plano.ultimo_repasse)}`}
              </span>
            </>
          ) : (
            <span className="font-normal text-muted-foreground">nada repassado ainda</span>
          )}
        </p>
      </div>
      {impedido && (
        <p className="mt-2 rounded bg-warning-soft px-3 py-1.5 text-sm text-primary">
          <strong>Impedido</strong>
          {plano.motivo_impedimento ? `: ${plano.motivo_impedimento}` : " (o plano não pôde ser executado e foi substituído ou cancelado)."}
        </p>
      )}
      <p className="mt-2">{plano.objeto ?? "Objeto não informado."}</p>
      {plano.metas && plano.metas !== plano.objeto && (
        <p className="mt-1 text-sm text-secondary">
          <strong>Metas:</strong> {plano.metas}
        </p>
      )}
      <p className="mt-2 text-sm text-muted-foreground">
        Declarado: {formatarBRL(plano.investimento)} em investimento e {formatarBRL(plano.custeio)} em custeio
        {declarado > 0 && ` (${pct(plano.investimento, declarado)} investimento)`}
        {plano.area && ` · ${plano.area}`}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">
        Relatório de gestão:{" "}
        {plano.relatorio_situacao
          ? `${capitalizar(plano.relatorio_situacao.replaceAll("_", " "))}${plano.relatorio_parecer ? ` — "${plano.relatorio_parecer}"` : ""}`
          : "não enviado"}
      </p>
    </li>
  );
}

export function EmendaPix() {
  const { uf = "", municipio = "" } = useParams();
  const base = `/api/municipios/${encodeURIComponent(uf)}/${encodeURIComponent(municipio)}`;
  const dados = useApi<DadosPix>(`${base}/emenda-pix`);
  const alertas = useApi<Pagina<Alerta>>(dados.dados ? "/api/alertas" : null, {
    municipio_ibge: dados.dados?.municipio.codigo_ibge,
    tipo: "pix_*",
    limit: 20,
  });
  const tipos = useTiposAlerta();
  const nome = nomeProprio(municipio);
  const d = dados.dados;
  const ate = d?.gastos_ate ? `${d.gastos_ate.mes ? MESES[d.gastos_ate.mes - 1] + "/" : ""}${d.gastos_ate.ano}` : "";

  return (
    <div className="space-y-6">
      <CabecalhoCidade uf={uf} municipio={municipio} />
      {dados.erro?.status === 404 ? (
        <Vazio>Nenhuma Emenda Pix registrada no Transferegov para {nome}.</Vazio>
      ) : dados.erro ? (
        <ErroApi erro={dados.erro} onTentarDeNovo={dados.recarregar} />
      ) : !d ? (
        <Carregando linhas={8} rotulo="Carregando Emenda Pix" />
      ) : (
        <>
          <p className="max-w-3xl text-secondary">
            A <strong>Emenda Pix</strong> (transferência especial) cai direto na conta da prefeitura, sem convênio. Aqui
            está o que chegou e o plano que a prefeitura declarou no <strong>Transferegov</strong>
            {d.tem_gastos
              ? ", ao lado do que ela informou ao tribunal de contas como gasto pago com esse dinheiro (fonte de recurso “Transferência Especial da União”)."
              : "."}
          </p>

          <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-3">
            <StatCard destaque icone={ArrowDownToLine} rotulo="Chegou à prefeitura" valor={formatarBRL(d.total_recebido)} detalhe={`${plural(d.planos.length, "plano", "planos")} de ação`} />
            {d.tem_gastos ? (
              <>
                <StatCard icone={Receipt} rotulo="Gasto informado com a fonte" valor={formatarBRL(d.total_gasto)} detalhe={`até ${ate}, segundo o tribunal de contas`} />
                <StatCard icone={Wrench} rotulo="Em despesa corrente" valor={pct(d.total_gasto_corrente, d.total_gasto)} detalhe="a Constituição pede ao menos 70% em investimento" />
              </>
            ) : (
              <p className="rounded-lg bg-muted px-4 py-3 text-secondary sm:col-span-2">
                O tribunal de contas deste estado não publica a fonte de recurso de cada gasto (ou ainda não coletamos).
                Por isso não dá para separar aqui o que foi pago com Emenda Pix.
              </p>
            )}
          </section>

          {(alertas.dados?.total ?? 0) > 0 && (
            <Secao id="alertas" titulo={`Sinais de alerta (${alertas.dados!.total})`}>
              <div className="space-y-3">
                <AvisoAlertas />
                {alertas.dados!.itens.map((a) => (
                  <CartaoAlerta key={a.id} alerta={a} tipos={tipos} mostrarDeputado={false} />
                ))}
              </div>
            </Secao>
          )}

          <Secao id="anos" titulo="Ano a ano" descricao="O que chegou e o que foi lançado como gasto com a fonte Emenda Pix em cada ano.">
            <div className="-mx-5 overflow-x-auto sm:mx-0" tabIndex={0} role="region" aria-label="Emenda Pix por ano">
              <table className="w-full min-w-[36rem] text-left text-sm">
                <caption className="sr-only">Emenda Pix por ano</caption>
                <thead className="bg-muted text-secondary">
                  <tr>
                    <th scope="col" className="px-3 py-2.5 font-bold">Ano</th>
                    <th scope="col" className="px-3 py-2.5 text-right font-bold">Chegou</th>
                    {d.tem_gastos && (
                      <>
                        <th scope="col" className="px-3 py-2.5 text-right font-bold">Gasto informado</th>
                        <th scope="col" className="px-3 py-2.5 text-right font-bold">Em despesa corrente</th>
                        <th scope="col" className="px-3 py-2.5 text-right font-bold">Pix estadual gasto</th>
                      </>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {d.anos.map((a) => (
                    <tr key={a.ano} className="border-t border-border">
                      <th scope="row" className="numero px-3 py-2.5 font-bold">{a.ano}</th>
                      <td className="numero px-3 py-2.5 text-right">{formatarBRL(a.recebido)}</td>
                      {d.tem_gastos && (
                        <>
                          <td className="numero px-3 py-2.5 text-right">{formatarBRL(a.gasto)}</td>
                          <td className="numero px-3 py-2.5 text-right">
                            {paraNumero(a.gasto) ? `${formatarBRL(a.gasto_corrente)} (${pct(a.gasto_corrente, a.gasto)})` : "—"}
                          </td>
                          <td className="numero px-3 py-2.5 text-right">{formatarBRL(a.gasto_estadual)}</td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {d.tem_gastos && (
              <p className="mt-3 text-sm text-muted-foreground">
                O tribunal de contas só tem os gastos a partir de 2023 e até {ate}. "Pix estadual" é a transferência
                especial dos deputados estaduais (fonte “Transferência Especial dos Estados”); o valor recebido do
                estado não está nas bases abertas que coletamos.
              </p>
            )}
          </Secao>

          <Secao id="planos" titulo="O que foi prometido" descricao="Planos de ação declarados no Transferegov, do mais recente ao mais antigo.">
            <ul className="space-y-3">
              {d.planos.map((p) => (
                <CartaoPlano key={p.id} plano={p} />
              ))}
            </ul>
          </Secao>

          {d.tem_gastos && (
            <>
              <Secao id="credores" titulo="Quem recebeu o dinheiro" descricao="Credores pagos com a fonte Emenda Pix (federal), todos os anos.">
                {d.credores.length === 0 ? (
                  <Vazio>Nenhum pagamento lançado com essa fonte.</Vazio>
                ) : (
                  <ListaBarras
                    rotuloLista="Credores pagos com Emenda Pix"
                    itens={d.credores.map((f) => ({
                      chave: `${f.nome}-${f.cpf_cnpj}`,
                      rotulo: capitalizar(f.nome),
                      rotuloTexto: capitalizar(f.nome),
                      detalhe: `${formatarDocumento(f.cpf_cnpj)} · ${plural(f.qtd_empenhos, "empenho", "empenhos")}`,
                      valor: f.total_pago,
                      href: f.tipo_pessoa === "PJ" && f.cpf_cnpj ? `/fornecedores/${f.cpf_cnpj}` : undefined,
                    }))}
                  />
                )}
              </Secao>
              <Secao id="empenhos" titulo="Cada gasto com Emenda Pix" descricao="Empenhos pagos com a fonte “Transferência Especial da União”.">
                <TabelaEmpenhos base={base} ano="" fonte="pix" />
              </Secao>
            </>
          )}

          <p className="text-sm text-muted-foreground">
            Fontes: Transferegov (planos de ação, metas, repasses e relatórios de gestão das transferências especiais)
            {d.tem_gastos && " e dados abertos do tribunal de contas (empenhos com a fonte de recurso)"}. O cruzamento é um
            ponto de partida para perguntar à prefeitura, não uma acusação.
          </p>
        </>
      )}
    </div>
  );
}
