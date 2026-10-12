import { Building2, CalendarDays, ExternalLink, FileText, Wallet } from "lucide-react";
import { Link, useParams } from "react-router";
import { AvisoAlertas, CartaoAlerta, useTiposAlerta } from "../components/CartaoAlerta";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { ListaBarras } from "../components/ListaBarras";
import { Paginacao } from "../components/Paginacao";
import { Secao } from "../components/Secao";
import { StatCard } from "../components/StatCard";
import { useApi } from "../lib/api";
import {
  capitalizar,
  formatarBRL,
  paraNumero,
  formatarData,
  formatarDocumento,
  formatarInteiro,
  nomeProprio,
  partidoUf,
  plural,
} from "../lib/format";
import type { Alerta, CadastroFornecedor, DocumentoFornecedor, Fornecedor as FornecedorDados, Pagina } from "../lib/types";
import { useParametros } from "../lib/useParametros";
import { NaoEncontrado } from "./NaoEncontrado";
import { BotaoContestar } from "../components/Contestar";
import { Seguir } from "../components/Seguir";

export function Fornecedor() {
  const { cnpj = "" } = useParams();
  const valido = /^\d{14}$/.test(cnpj);
  const dados = useApi<FornecedorDados>(valido ? `/api/fornecedores/${cnpj}` : null);
  const alertas = useApi<Pagina<Alerta>>(valido ? "/api/alertas" : null, { cnpj, limit: 50 });
  const tipos = useTiposAlerta();

  if (!valido || dados.erro?.status === 404) {
    return <NaoEncontrado mensagem="Esse CNPJ não aparece nas despesas da cota parlamentar." />;
  }
  if (dados.erro) return <ErroApi erro={dados.erro} onTentarDeNovo={dados.recarregar} />;
  if (!dados.dados) return <Carregando linhas={8} rotulo="Carregando fornecedor" />;

  const f = dados.dados;
  const cad = f.cadastro;
  const nome = cad?.nome_fantasia || cad?.razao_social || f.nome || "Fornecedor";

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <p className="flex items-center gap-1.5 font-bold text-accent">
          <Building2 aria-hidden className="size-5" /> Fornecedor de dinheiro público
        </p>
        <h1 className="text-3xl font-bold text-primary">{nome}</h1>
        <p className="numero text-secondary">CNPJ {formatarDocumento(f.cnpj)}</p>
        <div className="flex flex-wrap items-center gap-3">
          <Seguir filtro={{ cnpj: f.cnpj }} titulo={nome} />
          <BotaoContestar alvo={`Fornecedor: ${nome}`} />
        </div>
      </div>

      <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-3">
        <StatCard
          destaque
          icone={Wallet}
          rotulo="Recebeu de dinheiro público"
          valor={formatarBRL(f.total_recebido)}
          detalhe={[
            paraNumero(f.total_cota) ? `cota federal ${formatarBRL(f.total_cota)}` : null,
            paraNumero(f.total_estadual) ? `verba estadual ${formatarBRL(f.total_estadual)}` : null,
            paraNumero(f.total_municipal) ? `prefeituras e câmaras ${formatarBRL(f.total_municipal)}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        />
        <StatCard
          icone={FileText}
          rotulo="Notas e recibos"
          valor={formatarInteiro(f.qtd_despesas)}
          detalhe={plural(f.por_deputado.length + f.por_deputado_estadual.length + f.por_orgao.length, "pagador", "pagadores")}
        />
        <StatCard
          icone={CalendarDays}
          rotulo="Período"
          valor={`${formatarData(f.primeira_nota)}`}
          detalhe={`até ${formatarData(f.ultima_nota)}`}
        />
      </section>

      {(alertas.dados?.total ?? 0) > 0 && (
        <Secao id="alertas" titulo="Sinais de alerta" descricao="Padrões que envolvem esta empresa.">
          <div className="space-y-3">
            <AvisoAlertas />
            {alertas.dados!.itens.map((a) => (
              <CartaoAlerta key={a.id} alerta={a} tipos={tipos} mostrarFornecedor={false} />
            ))}
          </div>
        </Secao>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Secao id="cadastro" titulo="Cadastro na Receita Federal">
          {cad ? <Cadastro cad={cad} /> : (
            <Vazio>A base de CNPJ da Receita ainda não foi carregada para este fornecedor.</Vazio>
          )}
        </Secao>

        <Secao id="deputados" titulo="Quem pagou" descricao="Deputados federais (cota), deputados estaduais (verba) e órgãos municipais.">
          {f.por_deputado.length === 0 && f.por_deputado_estadual.length === 0 && f.por_orgao.length === 0 && (
            <Vazio>Nenhum pagamento encontrado.</Vazio>
          )}
          {(f.por_deputado_estadual.length > 0 || f.por_orgao.length > 0) && (
            <div className="mb-5 space-y-5">
              {f.por_deputado_estadual.length > 0 && (
                <ListaBarras
                  rotuloLista="Deputados estaduais que pagaram este fornecedor"
                  itens={f.por_deputado_estadual.map((d) => ({
                    chave: `e${d.deputado.id}`,
                    rotulo: d.deputado.nome,
                    rotuloTexto: d.deputado.nome,
                    detalhe: `Deputado(a) estadual · ${plural(d.qtd_despesas, "nota", "notas")}`,
                    valor: d.total_liquido,
                    href: `/estaduais/${d.deputado.id}`,
                    imagem: d.deputado.url_foto,
                  }))}
                />
              )}
              {f.por_orgao.length > 0 && (
                <ListaBarras
                  rotuloLista="Órgãos municipais que pagaram este fornecedor"
                  itens={f.por_orgao.map((o) => ({
                    chave: `m${o.orgao.id}`,
                    rotulo: o.orgao.nome,
                    rotuloTexto: o.orgao.nome,
                    detalhe: plural(o.qtd_empenhos, "empenho", "empenhos"),
                    valor: o.total_pago,
                    href: `/cidade/${o.orgao.sigla_uf}/${encodeURIComponent(o.orgao.municipio)}/${
                      (o.orgao.natureza ?? "").startsWith("Câmara") ? "camara" : "prefeitura"
                    }`,
                  }))}
                />
              )}
            </div>
          )}
          <ListaBarras
            rotuloLista="Deputados que pagaram este fornecedor"
            itens={f.por_deputado.map((d) => ({
              chave: d.deputado.id,
              rotulo: d.deputado.nome,
              rotuloTexto: d.deputado.nome,
              detalhe: `${partidoUf(d.deputado.sigla_partido, d.deputado.sigla_uf)} · ${plural(d.qtd_despesas, "nota", "notas")}`,
              valor: d.total_liquido,
              href: `/deputados/${d.deputado.id}`,
              imagem: d.deputado.url_foto,
            }))}
          />
        </Secao>
      </div>

      <Secao
        id="documentos"
        titulo="Pagamentos e documentos"
        descricao="Cada nota, empenho ou contrato com esta empresa, de todas as fontes. O link aparece quando a fonte publica o documento."
      >
        <TabelaDocumentos cnpj={f.cnpj} />
      </Secao>

      <Secao id="anos" titulo="Por ano">
        <ListaBarras
          numerada={false}
          rotuloLista="Recebido por ano"
          itens={f.por_ano.map((a) => ({ chave: a.ano, rotulo: String(a.ano), rotuloTexto: String(a.ano), valor: a.total }))}
        />
      </Secao>
    </div>
  );
}

function Cadastro({ cad }: { cad: CadastroFornecedor }) {
  const inativa = cad.situacao_cadastral && cad.situacao_cadastral !== "ATIVA";
  const linhas: [string, React.ReactNode][] = [
    ["Razão social", cad.razao_social ?? "—"],
    [
      "Situação",
      <span className={inativa ? "font-bold text-destructive" : ""}>
        {cad.situacao_cadastral ?? "—"}
        {cad.data_situacao_cadastral && ` desde ${formatarData(cad.data_situacao_cadastral)}`}
      </span>,
    ],
    ["Aberta em", formatarData(cad.data_inicio_atividade)],
    ["Porte", cad.porte ?? "—"],
    ["MEI", cad.opcao_mei ? `Sim, desde ${formatarData(cad.data_opcao_mei)}` : cad.data_opcao_mei ? `Foi MEI até ${formatarData(cad.data_exclusao_mei)}` : "Não"],
    ["Capital social", cad.capital_social ? formatarBRL(cad.capital_social) : "—"],
    ["Sede", cad.municipio ? `${nomeProprio(cad.municipio)} – ${cad.sigla_uf ?? ""}${cad.bairro ? ` (${nomeProprio(cad.bairro)})` : ""}` : "—"],
    ["Atividade (CNAE)", cad.cnae_principal ?? "—"],
  ];
  return (
    <>
      <dl className="divide-y divide-border">
        {linhas.map(([rotulo, valor]) => (
          <div key={rotulo} className="grid grid-cols-[9rem_1fr] gap-3 py-2">
            <dt className="text-sm font-bold text-muted-foreground">{rotulo}</dt>
            <dd>{valor}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-sm text-muted-foreground">Base da Receita de {cad.referencia}.</p>
    </>
  );
}

const SEM_DOCUMENTO: Record<DocumentoFornecedor["fonte"], string> = {
  cota_federal: "Sem nota publicada",
  cota_senado: "O Senado não publica a nota",
  verba_estadual: "A ALEPE não publica a nota",
  empenho_municipal: "O tribunal de contas publica só o empenho",
  contrato_pncp: "Sem link",
};

function linkPagador(d: DocumentoFornecedor): string | null {
  if (!d.pagador_id) return null;
  if (d.fonte === "cota_federal") return `/deputados/${d.pagador_id}`;
  if (d.fonte === "verba_estadual") return `/estaduais/${d.pagador_id}`;
  return null;
}

const POR_PAGINA_DOCS = 20;

function TabelaDocumentos({ cnpj }: { cnpj: string }) {
  const { pagina, definir } = useParametros([] as const);
  const docs = useApi<Pagina<DocumentoFornecedor>>(`/api/fornecedores/${cnpj}/documentos`, {
    limit: POR_PAGINA_DOCS,
    offset: (pagina - 1) * POR_PAGINA_DOCS,
  });
  if (docs.erro) return <ErroApi erro={docs.erro} onTentarDeNovo={docs.recarregar} />;
  if (!docs.dados) return <Carregando linhas={5} rotulo="Carregando documentos" />;
  if (docs.dados.total === 0) return <Vazio>Nenhum documento encontrado.</Vazio>;
  return (
    <>
      <div className="-mx-5 overflow-x-auto sm:mx-0 sm:rounded-lg sm:border sm:border-border" tabIndex={0} role="region" aria-label="Pagamentos e documentos">
        <table className="w-full min-w-[48rem] text-left text-sm">
          <caption className="sr-only">Pagamentos e documentos do fornecedor</caption>
          <thead className="bg-muted text-secondary">
            <tr>
              <th scope="col" className="px-3 py-2.5 font-bold">Data</th>
              <th scope="col" className="px-3 py-2.5 font-bold">Quem pagou</th>
              <th scope="col" className="px-3 py-2.5 font-bold">Descrição</th>
              <th scope="col" className="px-3 py-2.5 text-right font-bold">Valor</th>
              <th scope="col" className="px-3 py-2.5 font-bold">Documento</th>
            </tr>
          </thead>
          <tbody>
            {docs.dados.itens.map((d, i) => {
              const link = linkPagador(d);
              return (
                <tr key={`${d.fonte}-${d.documento}-${i}`} className="border-t border-border align-top hover:bg-background">
                  <td className="numero whitespace-nowrap px-3 py-2.5">
                    {d.data ? formatarData(d.data) : d.ano ? `${String(d.mes ?? "").padStart(2, "0")}/${d.ano}` : "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    {link ? (
                      <Link to={link} className="link">{d.pagador}</Link>
                    ) : (
                      d.pagador ?? "—"
                    )}
                    <span className="block text-muted-foreground">{d.fonte_nome}</span>
                  </td>
                  <td className="max-w-sm px-3 py-2.5">{capitalizar(d.descricao) || "—"}</td>
                  <td className="numero whitespace-nowrap px-3 py-2.5 text-right font-bold">{formatarBRL(d.valor)}</td>
                  <td className="px-3 py-2.5">
                    {d.url ? (
                      <a href={d.url} target="_blank" rel="noreferrer noopener" className="link inline-flex min-h-11 items-center gap-1 whitespace-nowrap">
                        {d.fonte === "contrato_pncp" ? "Ver contrato" : "Ver nota"} <ExternalLink aria-hidden className="size-4" />
                        <span className="sr-only">(abre em nova aba)</span>
                      </a>
                    ) : (
                      <span className="text-muted-foreground">
                        {d.documento && <span className="numero block">nº {d.documento}</span>}
                        {SEM_DOCUMENTO[d.fonte]}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Paginacao
        rotulo="Páginas de documentos"
        pagina={pagina}
        porPagina={POR_PAGINA_DOCS}
        total={docs.dados.total}
        onMudar={(p) => definir({ pagina: p })}
      />
    </>
  );
}
