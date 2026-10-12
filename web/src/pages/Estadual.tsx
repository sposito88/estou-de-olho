import { ArrowLeft, FileText, Wallet } from "lucide-react";
import { Link, useParams } from "react-router";
import { AvisoAlertas, CartaoAlerta, useTiposAlerta } from "../components/CartaoAlerta";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Compartilhar } from "../components/Compartilhar";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { ListaBarras } from "../components/ListaBarras";
import { Paginacao } from "../components/Paginacao";
import { Secao } from "../components/Secao";
import { SerieMensal } from "../components/SerieMensal";
import { StatCard } from "../components/StatCard";
import { useApi } from "../lib/api";
import {
  capitalizar,
  formatarBRL,
  formatarData,
  formatarDocumento,
  formatarInteiro,
  mesCurto,
} from "../lib/format";
import type { Alerta, DetalheEstadual, NotaVerba, Pagina, ResumoEstaduais } from "../lib/types";
import { useParametros } from "../lib/useParametros";
import { NaoEncontrado } from "./NaoEncontrado";
import { semFoto } from "../lib/foto";
import { Seguir } from "../components/Seguir";

const POR_PAGINA = 20;

export function Estadual() {
  const { id = "" } = useParams();
  const { valores, definir, pagina } = useParametros(["ano"] as const);
  const valido = /^\d+$/.test(id);
  const dados = useApi<DetalheEstadual>(valido ? `/api/estaduais/${id}` : null, {
    ano: valores.ano,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });
  const resumo = useApi<ResumoEstaduais>("/api/estaduais/resumo");
  const alertas = useApi<Pagina<Alerta>>(valido ? "/api/alertas" : null, {
    deputado_estadual_id: id,
    ano: valores.ano,
    limit: 30,
  });
  const tipos = useTiposAlerta();

  if (!valido || dados.erro?.status === 404) {
    return <NaoEncontrado mensagem="Não encontramos esse deputado estadual." />;
  }
  if (dados.erro) return <ErroApi erro={dados.erro} onTentarDeNovo={dados.recarregar} />;
  if (!dados.dados) return <Carregando linhas={8} rotulo="Carregando deputado estadual" />;

  const d = dados.dados;
  const periodo = valores.ano ? `em ${valores.ano}` : "na legislatura";

  return (
    <div className="space-y-6">
      <Link to="/estaduais" className="link inline-flex min-h-11 items-center gap-1">
        <ArrowLeft aria-hidden className="size-4" /> Todos os deputados estaduais
      </Link>

      <section aria-labelledby="titulo-estadual" className="card flex flex-col gap-5 sm:flex-row sm:items-center">
        {d.deputado.url_foto && (
          <img
            onError={semFoto}
            src={d.deputado.url_foto}
            alt={`Foto de ${d.deputado.nome}`}
            width={112}
            height={112}
            className="size-28 shrink-0 rounded-xl bg-muted object-cover"
          />
        )}
        <div className="min-w-0 flex-1 space-y-1">
          <p className="font-bold text-accent">Deputado(a) estadual · ALEPE</p>
          <h1 id="titulo-estadual" className="text-3xl font-bold text-primary">
            {d.deputado.nome}
          </h1>
          <p className="text-lg text-secondary">
            {[d.deputado.sigla_partido, "PE"].filter(Boolean).join("-")}
            {!d.deputado.em_exercicio && " · fora de exercício"}
          </p>
          <Seguir filtro={{ deputado_estadual_id: d.deputado.id }} titulo={d.deputado.nome} />
        </div>
        <div className="sm:w-48">
          <CampoSelect
            rotulo="Período"
            valor={valores.ano}
            todos="Toda a legislatura"
            opcoes={opcoesSimples(resumo.dados?.anos ?? [])}
            onMudar={(ano) => definir({ ano })}
          />
        </div>
      </section>

      <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-2">
        <StatCard destaque icone={Wallet} rotulo="Verba indenizatória" valor={formatarBRL(d.total)} detalhe={periodo} />
        <StatCard icone={FileText} rotulo="Notas declaradas" valor={formatarInteiro(d.qtd_notas)} />
      </section>

      <section aria-label="Compartilhar" className="card">
        <Compartilhar
          texto={`O deputado estadual ${d.deputado.nome} declarou ${formatarBRL(d.total)} de verba indenizatória ${periodo}. Veja as notas:`}
          dados={{
            chamada: `Verba indenizatória ${periodo}`,
            titulo: `${d.deputado.nome} (dep. estadual)`,
            destaque: formatarBRL(d.total),
            legendaDestaque: `em ${formatarInteiro(d.qtd_notas)} notas declaradas`,
            linhas: d.por_fornecedor.slice(0, 4).map((f) => ({
              rotulo: capitalizar(f.nome) || "Fornecedor",
              valor: formatarBRL(f.total),
            })),
            arquivo: `estou-de-olho-estadual-${d.deputado.id}`,
          }}
        />
      </section>

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

      {d.serie_mensal.length > 0 && (
        <Secao id="serie" titulo="Verba usada mês a mês" descricao="O teto atual é de R$ 60 mil por mês.">
          <SerieMensal
            titulo={`Verba mensal de ${d.deputado.nome}`}
            pontos={d.serie_mensal.map((s) => ({ ano: s.ano, mes: s.mes, valor: s.total }))}
          />
        </Secao>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Secao id="fornecedores" titulo="Quem recebeu" descricao="Empresas e pessoas pagas com a verba.">
          {d.por_fornecedor.length === 0 ? (
            <Vazio>Sem notas {periodo}.</Vazio>
          ) : (
            <ListaBarras
              rotuloLista="Fornecedores da verba"
              itens={d.por_fornecedor.map((f) => ({
                chave: f.cnpj ?? f.nome ?? "",
                rotulo: capitalizar(f.nome) || "Não informado",
                rotuloTexto: capitalizar(f.nome) || "Não informado",
                detalhe: `${formatarDocumento(f.cnpj)} · ${formatarInteiro(f.qtd_notas)} notas`,
                valor: f.total,
                href: f.cnpj && f.cnpj.length === 14 ? `/fornecedores/${f.cnpj}` : undefined,
              }))}
            />
          )}
        </Secao>

        <Secao id="rubricas" titulo="Em que foi gasto" descricao="Total por rubrica.">
          <ListaBarras
            numerada={false}
            rotuloLista="Verba por rubrica"
            itens={d.por_rubrica.map((r) => ({
              chave: r.rubrica,
              rotulo: capitalizar(r.rubrica),
              rotuloTexto: capitalizar(r.rubrica),
              valor: r.total,
            }))}
          />
        </Secao>
      </div>

      <Secao id="notas" titulo="Todas as notas" descricao="Da mais recente para a mais antiga.">
        {d.notas.total === 0 ? (
          <Vazio>Sem notas {periodo}.</Vazio>
        ) : (
          <>
            <TabelaNotas notas={d.notas.itens} />
            <Paginacao
              rotulo="Páginas das notas"
              pagina={pagina}
              porPagina={POR_PAGINA}
              total={d.notas.total}
              onMudar={(p) => definir({ pagina: p })}
            />
          </>
        )}
      </Secao>
    </div>
  );
}

function TabelaNotas({ notas }: { notas: NotaVerba[] }) {
  return (
    <div className="-mx-5 overflow-x-auto sm:mx-0 sm:rounded-lg sm:border sm:border-border" tabIndex={0} role="region" aria-label="Notas da verba">
      <table className="w-full min-w-[40rem] text-left text-sm">
        <caption className="sr-only">Notas da verba indenizatória</caption>
        <thead className="bg-muted text-secondary">
          <tr>
            <th scope="col" className="px-3 py-2.5 font-bold">Mês</th>
            <th scope="col" className="px-3 py-2.5 font-bold">Rubrica</th>
            <th scope="col" className="px-3 py-2.5 font-bold">Fornecedor</th>
            <th scope="col" className="px-3 py-2.5 text-right font-bold">Valor</th>
          </tr>
        </thead>
        <tbody>
          {notas.map((n) => (
            <tr key={n.id} className="border-t border-border align-top hover:bg-background">
              <td className="numero whitespace-nowrap px-3 py-2.5">
                {mesCurto(n.ano, n.mes)}
                {n.data && <span className="block text-muted-foreground">nota de {formatarData(n.data)}</span>}
              </td>
              <td className="px-3 py-2.5">{capitalizar(n.rubrica_nome) || "—"}</td>
              <td className="px-3 py-2.5">
                {n.tipo_pessoa === "PJ" && n.cnpj_cpf ? (
                  <Link to={`/fornecedores/${n.cnpj_cpf}`} className="link">
                    {capitalizar(n.fornecedor) || "—"}
                  </Link>
                ) : (
                  capitalizar(n.fornecedor) || "—"
                )}
                {n.cnpj_cpf && <span className="numero block text-muted-foreground">{formatarDocumento(n.cnpj_cpf)}</span>}
              </td>
              <td className="numero whitespace-nowrap px-3 py-2.5 text-right font-bold">{formatarBRL(n.valor)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
