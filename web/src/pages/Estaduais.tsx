import { FileText, Users, Wallet } from "lucide-react";
import { useId } from "react";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { ListaBarras } from "../components/ListaBarras";
import { Secao } from "../components/Secao";
import { StatCard } from "../components/StatCard";
import { useApi } from "../lib/api";
import { capitalizar, formatarBRL, formatarInteiro, plural } from "../lib/format";
import type { EstadualListaItem, ResumoEstaduais } from "../lib/types";
import { useParametros } from "../lib/useParametros";

export function Estaduais() {
  const { valores, definir } = useParametros(["ano", "busca"] as const);
  const resumo = useApi<ResumoEstaduais>("/api/estaduais/resumo", { ano: valores.ano });
  const lista = useApi<EstadualListaItem[]>("/api/estaduais", { ano: valores.ano, busca: valores.busca });
  const idBusca = useId();
  const periodo = valores.ano ? `em ${valores.ano}` : "na legislatura";

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold text-primary sm:text-4xl">Deputados estaduais de Pernambuco</h1>
        <p className="max-w-2xl text-lg text-secondary">
          Cada deputado da Assembleia Legislativa (ALEPE) recebe até R$ 60 mil por mês de{" "}
          <strong>verba indenizatória</strong> para aluguel de escritório, carro, assessoria e divulgação. Aqui está
          cada nota declarada, com a empresa que recebeu.
        </p>
      </div>

      {resumo.erro ? (
        <ErroApi erro={resumo.erro} onTentarDeNovo={resumo.recarregar} />
      ) : (
        <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-3">
          <StatCard
            destaque
            icone={Wallet}
            rotulo="Verba indenizatória"
            valor={resumo.dados ? formatarBRL(resumo.dados.total) : "…"}
            detalhe={periodo}
          />
          <StatCard
            icone={Users}
            rotulo="Deputados com gasto"
            valor={resumo.dados ? formatarInteiro(resumo.dados.qtd_deputados) : "…"}
          />
          <StatCard
            icone={FileText}
            rotulo="Notas declaradas"
            valor={resumo.dados ? formatarInteiro(resumo.dados.qtd_notas) : "…"}
          />
        </section>
      )}

      <section aria-label="Filtros" className="card grid gap-4 sm:grid-cols-2">
        <CampoSelect
          rotulo="Ano"
          valor={valores.ano}
          todos="Toda a legislatura"
          opcoes={opcoesSimples(resumo.dados?.anos ?? [])}
          onMudar={(ano) => definir({ ano })}
        />
        <div>
          <label htmlFor={idBusca} className="mb-1 block text-sm font-bold text-secondary">
            Nome
          </label>
          <input
            id={idBusca}
            type="search"
            className="input"
            placeholder="Ex.: Abimael"
            autoComplete="off"
            value={valores.busca}
            onChange={(e) => definir({ busca: e.target.value })}
          />
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <Secao id="ranking" titulo="Quem mais usou a verba" descricao={`Total de notas declaradas ${periodo}.`}>
          {lista.erro ? (
            <ErroApi erro={lista.erro} onTentarDeNovo={lista.recarregar} />
          ) : !lista.dados ? (
            <Carregando linhas={8} />
          ) : lista.dados.length === 0 ? (
            <Vazio>Nenhum deputado encontrado.</Vazio>
          ) : (
            <ListaBarras
              rotuloLista="Deputados estaduais por verba usada"
              itens={lista.dados.map((i) => ({
                chave: i.deputado.id,
                rotulo: i.deputado.nome,
                rotuloTexto: i.deputado.nome,
                detalhe: [
                  i.deputado.sigla_partido,
                  plural(i.qtd_notas, "nota", "notas"),
                  i.deputado.em_exercicio ? null : "fora de exercício",
                ]
                  .filter(Boolean)
                  .join(" · "),
                valor: i.total,
                href: `/estaduais/${i.deputado.id}${valores.ano ? `?ano=${valores.ano}` : ""}`,
                imagem: i.deputado.url_foto,
              }))}
            />
          )}
        </Secao>

        <Secao id="rubricas" titulo="Em que foi gasto" descricao="Total por rubrica da verba.">
          {!resumo.dados ? (
            <Carregando linhas={6} />
          ) : (
            <ListaBarras
              numerada={false}
              rotuloLista="Verba por rubrica"
              itens={resumo.dados.por_rubrica.map((r) => ({
                chave: r.rubrica,
                rotulo: capitalizar(r.rubrica),
                rotuloTexto: capitalizar(r.rubrica),
                valor: r.total,
              }))}
            />
          )}
        </Secao>
      </div>
    </div>
  );
}
