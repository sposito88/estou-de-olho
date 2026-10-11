import { FileText, Landmark, Wallet } from "lucide-react";
import { useParams } from "react-router";
import { CabecalhoCidade, SemDadosMunicipais } from "../components/CabecalhoCidade";
import { AvisoAlertas, CartaoAlerta, useTiposAlerta } from "../components/CartaoAlerta";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Carregando, ErroApi } from "../components/Estado";
import { ListaBarras } from "../components/ListaBarras";
import { Secao } from "../components/Secao";
import { StatCard } from "../components/StatCard";
import { TabelaEmpenhos } from "../components/TabelaEmpenhos";
import { useApi } from "../lib/api";
import { tribunal } from "../lib/tribunal";
import { capitalizar, formatarBRL, formatarDocumento, formatarInteiro, nomeProprio, paraNumero, plural } from "../lib/format";
import type { Alerta, Pagina, Prefeitura as DadosPrefeitura } from "../lib/types";
import { useParametros } from "../lib/useParametros";

export function Prefeitura() {
  const { uf = "", municipio = "" } = useParams();
  const { valores, definir } = useParametros(["ano"] as const);
  const base = `/api/municipios/${encodeURIComponent(uf)}/${encodeURIComponent(municipio)}`;
  const dados = useApi<DadosPrefeitura>(`${base}/prefeitura`, { ano: valores.ano });
  const prefeituraId = dados.dados?.por_orgao.find((o) => o.orgao.natureza?.startsWith("Prefeitura"))?.orgao.id;
  const alertas = useApi<Pagina<Alerta>>(prefeituraId ? "/api/alertas" : null, {
    orgao_id: prefeituraId,
    ano: valores.ano,
    limit: 30,
  });
  const tipos = useTiposAlerta();
  const nome = nomeProprio(municipio);
  const periodo = valores.ano ? `em ${valores.ano}` : "nos últimos anos";
  const alertasDaCidade = alertas.dados?.itens ?? [];
  const tce = tribunal(dados.dados?.por_orgao[0]?.orgao.fonte);
  const temAreas = (dados.dados?.por_funcao.length ?? 0) + (dados.dados?.por_elemento.length ?? 0) > 0;

  return (
    <div className="space-y-6">
      <CabecalhoCidade uf={uf} municipio={municipio} />

      {dados.erro?.status === 404 ? (
        <SemDadosMunicipais nome={nome} />
      ) : dados.erro ? (
        <ErroApi erro={dados.erro} onTentarDeNovo={dados.recarregar} />
      ) : !dados.dados ? (
        <Carregando linhas={8} rotulo="Carregando prefeitura" />
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <p className="max-w-2xl text-secondary">
              Tudo o que a Prefeitura de {nome} e seus órgãos empenharam e pagaram, segundo a prestação de contas
              ao {tce.nome} ({tce.sigla}).
            </p>
            <div className="w-full sm:w-56">
              <CampoSelect
                rotulo="Ano"
                valor={valores.ano}
                todos="Últimos anos"
                opcoes={opcoesSimples(dados.dados.anos)}
                onMudar={(ano) => definir({ ano })}
              />
            </div>
          </div>

          <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-3">
            <StatCard destaque icone={Wallet} rotulo="Pago" valor={formatarBRL(dados.dados.total_pago)} detalhe={periodo} />
            <StatCard icone={Landmark} rotulo="Empenhado" valor={formatarBRL(dados.dados.total_empenhado)} detalhe="valor comprometido" />
            <StatCard icone={FileText} rotulo="Empenhos" valor={formatarInteiro(dados.dados.qtd_empenhos)} />
          </section>

          {alertasDaCidade.length > 0 && (
            <Secao id="alertas" titulo={`Sinais de alerta (${formatarInteiro(alertas.dados?.total ?? 0)})`}>
              <div className="space-y-3">
                <AvisoAlertas />
                {alertasDaCidade.map((a) => (
                  <CartaoAlerta key={a.id} alerta={a} tipos={tipos} mostrarDeputado={false} />
                ))}
              </div>
            </Secao>
          )}

          {temAreas ? (
            <div className="grid gap-6 lg:grid-cols-2">
              <Secao id="funcoes" titulo="Para onde foi o dinheiro" descricao="Total pago por área (função de governo).">
                <ListaBarras
                  numerada={false}
                  rotuloLista="Pago por área"
                  itens={dados.dados.por_funcao.map((f) => ({ chave: f.nome, rotulo: f.nome, rotuloTexto: f.nome, valor: f.total_pago }))}
                />
              </Secao>
              <Secao id="elementos" titulo="Em quê" descricao="Total pago por tipo de despesa.">
                <ListaBarras
                  numerada={false}
                  rotuloLista="Pago por tipo de despesa"
                  itens={dados.dados.por_elemento.map((e) => ({ chave: e.nome, rotulo: e.nome, rotuloTexto: e.nome, valor: e.total_pago }))}
                />
              </Secao>
            </div>
          ) : (
            <p className="rounded-lg bg-muted px-4 py-3 text-secondary">
              O {tce.sigla} não informa a área nem o tipo de cada despesa nesta base. Para ver o gasto por área (saúde,
              educação...), use a aba <strong>Contas</strong>.
            </p>
          )}

          <Secao id="fornecedores" titulo="Quem mais recebeu" descricao="Empresas e pessoas, pelo total pago no período.">
            <ListaBarras
              rotuloLista="Maiores credores da prefeitura"
              itens={dados.dados.fornecedores.map((f) => ({
                chave: `${f.nome}-${f.cpf_cnpj}`,
                rotulo: capitalizar(f.nome),
                rotuloTexto: capitalizar(f.nome),
                detalhe: `${formatarDocumento(f.cpf_cnpj)} · ${plural(f.qtd_empenhos, "empenho", "empenhos")}`,
                valor: f.total_pago,
                href: f.tipo_pessoa === "PJ" && f.cpf_cnpj ? `/fornecedores/${f.cpf_cnpj}` : undefined,
              }))}
            />
            {paraNumero(dados.dados.sem_credor_identificado) > 0 && (
              <p className="mt-4 text-sm text-muted-foreground">
                Fora da lista: {formatarBRL(dados.dados.sem_credor_identificado)} pagos sem credor identificado, ao próprio município ou a outros órgãos da cidade
                (em geral folha de pagamento, encargos, repasses à câmara e às autarquias, aposentadorias e
                sentenças judiciais).
              </p>
            )}
          </Secao>

          {dados.dados.por_orgao.length > 1 && (
            <Secao id="orgaos" titulo="Por órgão">
              <ListaBarras
                numerada={false}
                rotuloLista="Pago por órgão"
                itens={dados.dados.por_orgao.map((o) => ({
                  chave: o.orgao.id,
                  rotulo: o.orgao.nome,
                  rotuloTexto: o.orgao.nome,
                  valor: o.total_pago,
                }))}
              />
            </Secao>
          )}

          <Secao
            id="empenhos"
            titulo={tce.porEmpenho ? "Todos os empenhos" : "Todos os credores"}
            descricao={
              tce.porEmpenho
                ? "Busque pelo credor ou pelo histórico (ex.: merenda, pavimentação, show)."
                : `Uma linha por órgão e credor no ano, com a soma dos empenhos (o ${tce.sigla} não publica o histórico). Busque pelo nome do credor.`
            }
          >
            <TabelaEmpenhos base={base} ano={valores.ano} />
          </Secao>

          <p className="text-sm text-muted-foreground">
            Fonte: dados abertos do {tce.nome} ({tce.sigla}). "Empenhado" é o valor comprometido; "pago" é o que
            saiu do caixa.
          </p>
        </>
      )}
    </div>
  );
}
