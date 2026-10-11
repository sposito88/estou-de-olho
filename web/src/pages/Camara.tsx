import { Briefcase, FileText, Landmark, Users } from "lucide-react";
import { useParams } from "react-router";
import { CabecalhoCidade, SemDadosMunicipais } from "../components/CabecalhoCidade";
import { AvisoAlertas, CartaoAlerta, useTiposAlerta } from "../components/CartaoAlerta";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { ListaBarras } from "../components/ListaBarras";
import { Secao } from "../components/Secao";
import { StatCard } from "../components/StatCard";
import { TabelaEmpenhos } from "../components/TabelaEmpenhos";
import { useApi } from "../lib/api";
import { tribunal } from "../lib/tribunal";
import { capitalizar, formatarBRL, formatarDocumento, formatarInteiro, nomeProprio, paraNumero, plural } from "../lib/format";
import type { Alerta, Camara as DadosCamara, Pagina, Prefeitura } from "../lib/types";
import { useParametros } from "../lib/useParametros";

export function Camara() {
  const { uf = "", municipio = "" } = useParams();
  const { valores, definir } = useParametros(["ano"] as const);
  const base = `/api/municipios/${encodeURIComponent(uf)}/${encodeURIComponent(municipio)}`;
  const camara = useApi<DadosCamara>(`${base}/camara`, { ano: valores.ano });
  // A prefeitura informa os anos disponíveis do município.
  const anos = useApi<Prefeitura>(`${base}/prefeitura`).dados?.anos ?? [];
  const alertas = useApi<Pagina<Alerta>>(camara.dados ? "/api/alertas" : null, {
    orgao_id: camara.dados?.orgao.id,
    ano: valores.ano,
    limit: 20,
  });
  const tipos = useTiposAlerta();
  const nome = nomeProprio(municipio);
  const periodo = valores.ano ? `em ${valores.ano}` : "nos últimos anos";
  const tce = tribunal(camara.dados?.orgao.fonte);
  const comSalario = Boolean(camara.dados?.vereadores.some((v) => v.salario));

  return (
    <div className="space-y-6">
      <CabecalhoCidade uf={uf} municipio={municipio} />

      {camara.erro?.status === 404 ? (
        <SemDadosMunicipais nome={nome} />
      ) : camara.erro ? (
        <ErroApi erro={camara.erro} onTentarDeNovo={camara.recarregar} />
      ) : !camara.dados ? (
        <Carregando linhas={8} rotulo="Carregando câmara" />
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <p className="max-w-2xl text-secondary">
              Gastos da <strong>{camara.dados.orgao.nome}</strong> informados ao {tce.nome} ({tce.sigla})
              {tce.pessoal && ", e o que cada vereador recebeu em seu nome além do salário"}.
            </p>
            <div className="w-full sm:w-56">
              <CampoSelect
                rotulo="Ano"
                valor={valores.ano}
                todos="Últimos anos"
                opcoes={opcoesSimples(anos)}
                onMudar={(ano) => definir({ ano })}
              />
            </div>
          </div>

          <section
            aria-label="Resumo"
            className={`grid gap-4 sm:grid-cols-2 ${tce.pessoal ? "lg:grid-cols-4" : ""}`}
          >
            <StatCard
              destaque
              icone={Landmark}
              rotulo="Gasto da Câmara"
              valor={formatarBRL(camara.dados.total_pago)}
              detalhe={`pago ${periodo}`}
            />
            {tce.pessoal && (
              <>
                <StatCard
                  icone={Users}
                  rotulo="Vereadores"
                  valor={formatarInteiro(camara.dados.qtd_vereadores_mandato)}
                  detalhe={`mandato ${camara.dados.inicio_mandato}–${camara.dados.inicio_mandato + 3}`}
                />
                <StatCard
                  icone={Briefcase}
                  rotulo="Nomeações no mandato"
                  valor={formatarInteiro(camara.dados.nomeados_no_mandato)}
                  detalhe={`desde jan/${camara.dados.inicio_mandato}, todos os vínculos`}
                />
              </>
            )}
            <StatCard icone={FileText} rotulo="Empenhos" valor={formatarInteiro(camara.dados.qtd_empenhos)} />
          </section>

          {tce.pessoal && (
          <Secao
            id="vereadores"
            titulo={comSalario ? "Vereadores e salário" : "O que cada vereador recebeu em seu nome"}
            descricao={
              comSalario
                ? `Salário (subsídio) do mês mais recente informado ao ${tce.sigla}.`
                : `Diárias, indenizações e outros pagamentos com o vereador como credor. O salário (subsídio) não entra: o ${tce.sigla} só publica a folha somada.`
            }
          >
            {camara.dados.vereadores.length === 0 ? (
              <Vazio>Nenhum vereador encontrado na base de pessoal do {tce.sigla}.</Vazio>
            ) : (
              <ListaBarras
                rotuloLista="Pagamentos nominais a vereadores"
                itens={camara.dados.vereadores.map((v) => ({
                  chave: v.nome,
                  rotulo: nomeProprio(v.nome),
                  rotuloTexto: nomeProprio(v.nome),
                  detalhe: [
                    v.mandato_atual ? "mandato atual" : "ex-vereador(a)",
                    v.salario ? `salário ${formatarBRL(v.salario)}/mês` : null,
                    v.qtd_pagamentos ? plural(v.qtd_pagamentos, "pagamento", "pagamentos") : "nenhum pagamento nominal",
                    ...v.por_tipo.map((t) => `${t.nome}: ${formatarBRL(t.total_pago)}`),
                  ].filter(Boolean).join(" · "),
                  valor: comSalario ? (v.salario ?? 0) : v.total_recebido,
                }))}
              />
            )}
          </Secao>
          )}

          {(alertas.dados?.total ?? 0) > 0 && (
            <Secao id="alertas" titulo={`Sinais de alerta (${formatarInteiro(alertas.dados!.total)})`}>
              <div className="space-y-3">
                <AvisoAlertas />
                {alertas.dados!.itens.map((a) => (
                  <CartaoAlerta key={a.id} alerta={a} tipos={tipos} mostrarDeputado={false} />
                ))}
              </div>
            </Secao>
          )}

          {tce.pessoal && (
            <div className="grid gap-6 lg:grid-cols-2">
              <Secao id="elementos" titulo="Em que a Câmara gastou" descricao="Total pago por tipo de despesa.">
                <ListaBarras
                  numerada={false}
                  rotuloLista="Gasto por tipo de despesa"
                  itens={camara.dados.por_elemento.map((e) => ({
                    chave: e.nome,
                    rotulo: e.nome,
                    rotuloTexto: e.nome,
                    valor: e.total_pago,
                  }))}
                />
              </Secao>

              <Secao
                id="pessoal"
                titulo="Quem foi nomeado neste mandato"
                descricao={`Vínculos com admissão a partir de jan/${camara.dados.inicio_mandato}, segundo o TCE-PE. A base não informa desligamentos, então pode incluir quem já saiu.`}
              >
                <ul className="space-y-1.5">
                  {camara.dados.por_vinculo.map((v) => (
                    <li key={v.nome} className="flex justify-between gap-3">
                      <span>{v.nome}</span>
                      <span className="numero font-bold">{formatarInteiro(v.qtd)}</span>
                    </li>
                  ))}
                </ul>
                {camara.dados.comissionados_por_cargo.length > 0 && (
                  <>
                    <h3 className="mb-2 mt-5 font-bold text-secondary">Cargos comissionados mais comuns</h3>
                    <ul className="space-y-1.5 text-sm">
                      {camara.dados.comissionados_por_cargo.map((c) => (
                        <li key={c.nome} className="flex justify-between gap-3">
                          <span>{capitalizar(c.nome)}</span>
                          <span className="numero font-bold">{formatarInteiro(c.qtd)}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </Secao>
            </div>
          )}

          <Secao id="fornecedores" titulo="Quem mais recebeu da Câmara" descricao="Empresas e pessoas, pelo total pago.">
            <ListaBarras
              rotuloLista="Fornecedores da Câmara"
              itens={camara.dados.fornecedores.map((f) => ({
                chave: `${f.nome}-${f.cpf_cnpj}`,
                rotulo: capitalizar(f.nome),
                rotuloTexto: capitalizar(f.nome),
                detalhe: `${formatarDocumento(f.cpf_cnpj)} · ${plural(f.qtd_empenhos, "empenho", "empenhos")}`,
                valor: f.total_pago,
                href: f.tipo_pessoa === "PJ" && f.cpf_cnpj ? `/fornecedores/${f.cpf_cnpj}` : undefined,
              }))}
            />
            {paraNumero(camara.dados.sem_credor_identificado) > 0 && (
              <p className="mt-4 text-sm text-muted-foreground">
                Fora da lista: {formatarBRL(camara.dados.sem_credor_identificado)} pagos sem credor identificado, ao próprio município ou a outros órgãos da cidade
                (em geral folha de pagamento, encargos, repasses à câmara e às autarquias, aposentadorias e
                sentenças judiciais).
              </p>
            )}
          </Secao>

          <Secao
            id="empenhos"
            titulo={tce.porEmpenho ? "Todos os empenhos da Câmara" : "Todos os credores da Câmara"}
            descricao={
              tce.porEmpenho
                ? "Busque pelo credor ou pelo histórico."
                : `Uma linha por credor no ano, com a soma dos empenhos (o ${tce.sigla} não publica o histórico).`
            }
          >
            <TabelaEmpenhos base={base} ano={valores.ano} orgaoId={camara.dados.orgao.id} />
          </Secao>

          <p className="text-sm text-muted-foreground">
            {tce.pessoal
              ? `Fonte: dados abertos do ${tce.sigla} (empenhos e base Sagres Pessoal). O vínculo de cada pagamento a um vereador é feito pelo nome do credor.`
              : `Fonte: dados abertos do ${tce.nome} (${tce.sigla}). Esta base não traz a lista de vereadores e de pessoal; veja os eleitos na aba Eleitos.`}
          </p>
        </>
      )}
    </div>
  );
}
