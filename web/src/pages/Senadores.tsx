import { FileText, Users, Wallet } from "lucide-react";
import { useId } from "react";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { ListaBarras } from "../components/ListaBarras";
import { Secao } from "../components/Secao";
import { StatCard } from "../components/StatCard";
import { useApi } from "../lib/api";
import { capitalizar, formatarBRL, formatarInteiro, plural } from "../lib/format";
import type { ResumoEstaduais, SenadorListaItem } from "../lib/types";
import { useParametros } from "../lib/useParametros";

export function Senadores() {
  const { valores, definir } = useParametros(["ano", "busca", "uf"] as const);
  const resumo = useApi<ResumoEstaduais>("/api/senadores/resumo", { ano: valores.ano });
  const lista = useApi<SenadorListaItem[]>("/api/senadores", { ano: valores.ano, busca: valores.busca, uf: valores.uf });
  const idBusca = useId();
  const periodo = valores.ano ? `em ${valores.ano}` : "na legislatura";

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold text-primary sm:text-4xl">Senadores</h1>
        <p className="max-w-2xl text-lg text-secondary">
          Cada senador tem uma <strong>cota para o exercício da atividade parlamentar (CEAPS)</strong>: aluguel de
          escritório, passagens, combustível, consultorias e divulgação. Aqui está cada despesa reembolsada pelo
          Senado, com a empresa que recebeu.
        </p>
      </div>

      {resumo.erro ? (
        <ErroApi erro={resumo.erro} onTentarDeNovo={resumo.recarregar} />
      ) : (
        <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-3">
          <StatCard
            destaque
            icone={Wallet}
            rotulo="Cota dos senadores"
            valor={resumo.dados ? formatarBRL(resumo.dados.total) : "…"}
            detalhe={periodo}
          />
          <StatCard
            icone={Users}
            rotulo="Senadores com gasto"
            valor={resumo.dados ? formatarInteiro(resumo.dados.qtd_deputados) : "…"}
          />
          <StatCard
            icone={FileText}
            rotulo="Despesas"
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
            placeholder="Ex.: Humberto"
            autoComplete="off"
            value={valores.busca}
            onChange={(e) => definir({ busca: e.target.value })}
          />
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <Secao id="ranking" titulo="Quem mais usou a cota" descricao={`Total reembolsado ${periodo}. O teto varia por estado.`}>
          {lista.erro ? (
            <ErroApi erro={lista.erro} onTentarDeNovo={lista.recarregar} />
          ) : !lista.dados ? (
            <Carregando linhas={8} />
          ) : lista.dados.length === 0 ? (
            <Vazio>Nenhum senador encontrado.</Vazio>
          ) : (
            <ListaBarras
              rotuloLista="Senadores por cota usada"
              itens={lista.dados.map((i) => ({
                chave: i.senador.id,
                rotulo: i.senador.nome,
                rotuloTexto: i.senador.nome,
                detalhe: [
                  [i.senador.sigla_partido, i.senador.sigla_uf].filter(Boolean).join("-"),
                  plural(i.qtd_notas, "despesa", "despesas"),
                  i.senador.em_exercicio ? null : "fora de exercício",
                ]
                  .filter(Boolean)
                  .join(" · "),
                valor: i.total,
                href: `/senadores/${i.senador.id}${valores.ano ? `?ano=${valores.ano}` : ""}`,
                imagem: i.senador.url_foto,
              }))}
            />
          )}
        </Secao>

        <Secao id="rubricas" titulo="Em que foi gasto" descricao="Total por tipo de despesa.">
          {!resumo.dados ? (
            <Carregando linhas={6} />
          ) : (
            <ListaBarras
              numerada={false}
              rotuloLista="Cota por tipo de despesa"
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
