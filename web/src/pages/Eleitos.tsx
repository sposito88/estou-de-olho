import { Users, Vote } from "lucide-react";
import { useParams } from "react-router";
import { CabecalhoCidade } from "../components/CabecalhoCidade";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { Secao } from "../components/Secao";
import { StatCard } from "../components/StatCard";
import { useApi } from "../lib/api";
import { capitalizar, formatarBRL, formatarInteiro, nomeProprio, paraNumero } from "../lib/format";
import type { Eleitos as DadosEleitos } from "../lib/types";

export function Eleitos() {
  const { uf = "", municipio = "" } = useParams();
  const base = `/api/municipios/${encodeURIComponent(uf)}/${encodeURIComponent(municipio)}`;
  const dados = useApi<DadosEleitos>(`${base}/eleitos`);
  const nome = nomeProprio(municipio);
  const executivo = dados.dados?.eleitos.filter((e) => e.cargo !== "VEREADOR") ?? [];
  const vereadores = dados.dados?.eleitos.filter((e) => e.cargo === "VEREADOR") ?? [];

  return (
    <div className="space-y-6">
      <CabecalhoCidade uf={uf} municipio={municipio} />
      {dados.erro ? (
        <ErroApi erro={dados.erro} onTentarDeNovo={dados.recarregar} />
      ) : !dados.dados ? (
        <Carregando linhas={8} rotulo="Carregando eleitos" />
      ) : dados.dados.eleitos.length === 0 ? (
        <Vazio>Nenhum eleito encontrado para {nome} em {dados.dados.ano}.</Vazio>
      ) : (
        <>
          <p className="max-w-2xl text-secondary">
            Quem o TSE registrou como eleito em {nome} na eleição de {dados.dados.ano}, com o patrimônio que cada um
            declarou ao se candidatar.
          </p>
          <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-2">
            <StatCard destaque icone={Vote} rotulo="Eleitos" valor={formatarInteiro(dados.dados.eleitos.length)}
                      detalhe={`${vereadores.length} vereadores`} />
            <StatCard icone={Users} rotulo="Candidaturas" valor={formatarInteiro(dados.dados.qtd_candidaturas)} />
          </section>

          <div className="grid gap-4 sm:grid-cols-2">
            {executivo.map((e) => (
              <div key={`${e.cargo}-${e.nome}`} className="card">
                <p className="text-sm font-bold text-accent">{capitalizar(e.cargo)}</p>
                <p className="text-xl font-bold text-primary">{e.nome_urna ?? nomeProprio(e.nome)}</p>
                <p className="text-secondary">{nomeProprio(e.nome)} · {e.sigla_partido}</p>
                <p className="mt-2 text-sm text-muted-foreground">
                  Bens declarados: <strong className="numero text-primary">{formatarBRL(e.bens)}</strong>
                </p>
              </div>
            ))}
          </div>

          <Secao id="vereadores" titulo="Vereadores eleitos" descricao="Em ordem de patrimônio declarado ao TSE.">
            <div className="-mx-5 overflow-x-auto sm:mx-0 sm:rounded-lg sm:border sm:border-border" tabIndex={0} role="region" aria-label="Vereadores eleitos">
              <table className="w-full min-w-[40rem] text-left text-sm">
                <caption className="sr-only">Vereadores eleitos</caption>
                <thead className="bg-muted text-secondary">
                  <tr>
                    <th scope="col" className="px-3 py-2.5 font-bold">Vereador(a)</th>
                    <th scope="col" className="px-3 py-2.5 font-bold">Partido</th>
                    <th scope="col" className="px-3 py-2.5 font-bold">Ocupação</th>
                    <th scope="col" className="px-3 py-2.5 text-right font-bold">Bens declarados</th>
                  </tr>
                </thead>
                <tbody>
                  {[...vereadores].sort((a, b) => paraNumero(b.bens) - paraNumero(a.bens)).map((v) => (
                    <tr key={v.nome} className="border-t border-border align-top hover:bg-background">
                      <td className="px-3 py-2.5">
                        <span className="font-bold">{v.nome_urna ?? nomeProprio(v.nome)}</span>
                        <span className="block text-muted-foreground">{nomeProprio(v.nome)}</span>
                      </td>
                      <td className="px-3 py-2.5">{v.sigla_partido ?? "—"}</td>
                      <td className="px-3 py-2.5">{capitalizar(v.ocupacao) || "—"}</td>
                      <td className="numero whitespace-nowrap px-3 py-2.5 text-right font-bold">{formatarBRL(v.bens)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Secao>
          <p className="text-sm text-muted-foreground">
            Fonte: dados abertos do TSE (candidaturas e bens de candidatos). O TSE não publica mais o CPF dos
            candidatos.
          </p>
        </>
      )}
    </div>
  );
}
