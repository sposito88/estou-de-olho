import { ArrowLeft, ExternalLink, FileText, Landmark, MapPin, Wallet } from "lucide-react";
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
import { TabelaDespesas } from "../components/TabelaDespesas";
import { useApi } from "../lib/api";
import { LINKS_EXTERNOS } from "../lib/config";
import { formatarBRL, formatarInteiro, nomeProprio, partidoUf, plural } from "../lib/format";
import type { Alerta, EmendasDeputado, Filtros, GastosDeputado, Pagina } from "../lib/types";
import { useParametros } from "../lib/useParametros";
import { NaoEncontrado } from "./NaoEncontrado";
import { semFoto } from "../lib/foto";

const POR_PAGINA = 20;

export function Deputado() {
  const { id } = useParams();
  const { valores, definir, pagina } = useParametros(["ano"] as const);
  const filtros = useApi<Filtros>("/api/filtros");
  const gastos = useApi<GastosDeputado>(`/api/deputados/${id}/gastos`, {
    ano: valores.ano,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });
  const emendas = useApi<EmendasDeputado>(`/api/deputados/${id}/emendas`, { ano: valores.ano });
  const alertas = useApi<Pagina<Alerta>>("/api/alertas", { deputado_id: id, ano: valores.ano, limit: 30 });
  const tipos = useTiposAlerta();

  if (gastos.erro?.status === 404 || !/^\d+$/.test(id ?? "")) {
    return <NaoEncontrado mensagem="Não encontramos esse deputado na legislatura atual." />;
  }
  if (gastos.erro) return <ErroApi erro={gastos.erro} onTentarDeNovo={gastos.recarregar} />;
  if (!gastos.dados) return <Carregando linhas={8} rotulo="Carregando deputado" />;

  const { deputado } = gastos.dados;
  const periodo = valores.ano ? `em ${valores.ano}` : "na legislatura";
  const anos = [...new Set([...(filtros.dados?.anos ?? []), ...(filtros.dados?.anos_emendas ?? [])])].sort((a, b) => b - a);

  return (
    <div className="space-y-6">
      <Link to="/deputados" className="link inline-flex min-h-11 items-center gap-1">
        <ArrowLeft aria-hidden className="size-4" /> Todos os deputados
      </Link>

      <section aria-labelledby="titulo-deputado" className="card flex flex-col gap-5 sm:flex-row sm:items-center">
        <img
          onError={semFoto}
          src={deputado.url_foto ?? undefined}
          alt={`Foto de ${deputado.nome}`}
          width={112}
          height={112}
          className="size-28 shrink-0 rounded-xl bg-muted object-cover"
        />
        <div className="min-w-0 flex-1 space-y-1">
          <h1 id="titulo-deputado" className="text-3xl font-bold text-primary">
            {deputado.nome}
          </h1>
          <p className="text-lg text-secondary">{partidoUf(deputado.sigla_partido, deputado.sigla_uf)}</p>
          <a
            href={LINKS_EXTERNOS.perfilDeputado(deputado.id)}
            target="_blank"
            rel="noreferrer noopener"
            className="link inline-flex min-h-11 items-center gap-1"
          >
            Perfil na Câmara <ExternalLink aria-hidden className="size-4" />
            <span className="sr-only">(abre em nova aba)</span>
          </a>
        </div>
        <div className="sm:w-48">
          <CampoSelect
            rotulo="Período"
            valor={valores.ano}
            todos="Toda a legislatura"
            opcoes={opcoesSimples(anos)}
            onMudar={(ano) => definir({ ano })}
          />
        </div>
      </section>

      <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          destaque
          icone={Wallet}
          rotulo="Cota reembolsada"
          valor={formatarBRL(gastos.dados.total_liquido)}
          detalhe={periodo}
        />
        <StatCard icone={FileText} rotulo="Despesas" valor={formatarInteiro(gastos.dados.qtd_despesas)} />
        <StatCard
          icone={Landmark}
          rotulo="Emendas pagas"
          valor={emendas.dados ? formatarBRL(emendas.dados.total_pago) : "…"}
          detalhe={emendas.dados ? `de ${formatarBRL(emendas.dados.total_empenhado)} empenhados ${periodo}` : undefined}
        />
        <StatCard
          icone={MapPin}
          rotulo="Chegou aos municípios"
          valor={emendas.dados ? formatarBRL(emendas.dados.total_recebido_municipios) : "…"}
          detalhe="pagamentos a favorecidos"
        />
      </section>

      <section aria-label="Compartilhar" className="card">
        <Compartilhar
          texto={`${deputado.nome} recebeu ${formatarBRL(gastos.dados.total_liquido)} de reembolso da cota parlamentar ${periodo}. Veja as notas:`}
          dados={{
            chamada: `Cota parlamentar ${periodo}`,
            titulo: `${deputado.nome} (${partidoUf(deputado.sigla_partido, deputado.sigla_uf)})`,
            destaque: formatarBRL(gastos.dados.total_liquido),
            legendaDestaque: "reembolsados com notas fiscais",
            linhas: [
              { rotulo: "Despesas", valor: formatarInteiro(gastos.dados.qtd_despesas) },
              ...(emendas.dados ? [{ rotulo: "Emendas pagas", valor: formatarBRL(emendas.dados.total_pago) }] : []),
              ...(alertas.dados ? [{ rotulo: "Sinais de alerta", valor: formatarInteiro(alertas.dados.total) }] : []),
              ...(emendas.dados?.por_destino[0]
                ? [{
                    rotulo: `Maior destino: ${nomeProprio(emendas.dados.por_destino[0].municipio)}`,
                    valor: formatarBRL(emendas.dados.por_destino[0].total_recebido),
                  }]
                : []),
            ],
            arquivo: `estou-de-olho-${deputado.id}`,
          }}
        />
      </section>

      {(alertas.dados?.total ?? 0) > 0 && (
        <Secao
          id="alertas"
          titulo={`Sinais de alerta (${formatarInteiro(alertas.dados!.total)})`}
          descricao={`Padrões nos gastos ${periodo} que merecem uma olhada na nota.`}
        >
          <div className="space-y-3">
            <AvisoAlertas />
            {alertas.dados!.itens.map((a) => (
              <CartaoAlerta key={a.id} alerta={a} tipos={tipos} mostrarDeputado={false} />
            ))}
          </div>
        </Secao>
      )}

      <Secao id="serie" titulo="Gastos da cota mês a mês" descricao={`Valor reembolsado por mês ${periodo}.`}>
        {gastos.dados.serie_mensal.length === 0 ? (
          <Vazio>Sem despesas {periodo}.</Vazio>
        ) : (
          <SerieMensal
            titulo={`Gastos mensais de ${deputado.nome}`}
            pontos={gastos.dados.serie_mensal.map((s) => ({ ano: s.ano, mes: s.mes, valor: s.total_liquido }))}
          />
        )}
      </Secao>

      <div className="grid gap-6 lg:grid-cols-2">
        <Secao
          id="destinos"
          titulo="Para onde mandou emendas"
          descricao="Municípios que receberam pagamentos de emendas deste deputado."
        >
          {emendas.erro ? (
            <ErroApi erro={emendas.erro} onTentarDeNovo={emendas.recarregar} />
          ) : !emendas.dados ? (
            <Carregando linhas={5} />
          ) : emendas.dados.por_destino.length === 0 ? (
            <Vazio>Nenhum pagamento de emenda encontrado {periodo}.</Vazio>
          ) : (
            <ListaBarras
              rotuloLista="Municípios que mais receberam"
              itens={emendas.dados.por_destino.map((d) => ({
                chave: `${d.sigla_uf}-${d.municipio}`,
                rotulo: `${nomeProprio(d.municipio)} – ${d.sigla_uf ?? ""}`,
                rotuloTexto: `${nomeProprio(d.municipio)}, ${d.sigla_uf ?? ""}`,
                detalhe: plural(d.qtd_pagamentos, "pagamento", "pagamentos"),
                valor: d.total_recebido,
                href: d.sigla_uf && d.municipio ? `/cidade/${d.sigla_uf}/${encodeURIComponent(d.municipio)}` : undefined,
              }))}
            />
          )}
        </Secao>

        <Secao id="areas" titulo="Áreas das emendas" descricao="Valor pago por área do orçamento (saúde, urbanismo…).">
          {!emendas.dados ? (
            <Carregando linhas={5} />
          ) : emendas.dados.por_funcao.length === 0 ? (
            <Vazio>Nenhuma emenda encontrada {periodo}.</Vazio>
          ) : (
            <ListaBarras
              numerada={false}
              rotuloLista="Valor pago por área"
              itens={emendas.dados.por_funcao.map((f) => ({
                chave: f.funcao,
                rotulo: f.funcao,
                rotuloTexto: f.funcao,
                valor: f.total,
              }))}
            />
          )}
        </Secao>
      </div>

      <Secao id="despesas" titulo="Todas as despesas da cota" descricao="Da mais recente para a mais antiga.">
        {gastos.dados.despesas.total === 0 ? (
          <Vazio>Sem despesas {periodo}.</Vazio>
        ) : (
          <>
            <TabelaDespesas despesas={gastos.dados.despesas.itens} legenda={`Despesas de ${deputado.nome}`} />
            <Paginacao
              rotulo="Páginas das despesas"
              pagina={pagina}
              porPagina={POR_PAGINA}
              total={gastos.dados.despesas.total}
              onMudar={(p) => definir({ pagina: p })}
            />
          </>
        )}
      </Secao>
    </div>
  );
}
