import { AlertTriangle, Eye, Users } from "lucide-react";
import { AvisoAlertas, CartaoAlerta, ROTULO_ESFERA, useTiposAlerta } from "../components/CartaoAlerta";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { Paginacao } from "../components/Paginacao";
import { StatCard } from "../components/StatCard";
import { useApi } from "../lib/api";
import { formatarInteiro } from "../lib/format";
import type { Alerta, Filtros, Pagina, ResumoAlertas } from "../lib/types";
import { useParametros } from "../lib/useParametros";

const POR_PAGINA = 20;

/** O que cada tipo de alerta significa, em linguagem simples. */
const EXPLICACOES: Record<string, string> = {
  concentracao: "Uma empresa que atende pouquíssimos deputados ficou com fatia grande da cota de um deles.",
  notas_sequenciais: "O deputado recebeu notas com numeração quase seguida: a empresa parece ter poucos outros clientes.",
  empresa_nova: "A empresa foi aberta poucos meses antes de começar a receber da cota.",
  fornecedor_inativo: "Há notas emitidas depois de a Receita marcar o CNPJ como baixado, inapto ou suspenso.",
  mei_acima_limite: "Um microempreendedor individual recebeu da cota mais do que o MEI pode faturar no ano.",
  divulgacao_eleitoral: "O gasto com divulgação do mandato disparou no 1º semestre do ano da eleição.",
  padrao_atipico: "Proporção fora do comum de notas em fim de semana ou com valores redondos.",
};

export function Alertas() {
  const { valores, definir, pagina } = useParametros(["tipo", "gravidade", "ano", "uf", "partido", "esfera", "forca"] as const);
  const tipos = useTiposAlerta();
  const filtros = useApi<Filtros>("/api/filtros");
  const params = { ano: valores.ano, uf: valores.uf, partido: valores.partido, esfera: valores.esfera };
  const resumo = useApi<ResumoAlertas>("/api/alertas/resumo", params);
  const alertas = useApi<Pagina<Alerta>>("/api/alertas", {
    ...params,
    tipo: valores.tipo,
    gravidade: valores.gravidade,
    min_prioridade: valores.forca,
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold text-primary sm:text-4xl">Sinais de alerta</h1>
        <p className="max-w-2xl text-lg text-secondary">
          Padrões nos gastos de deputados federais, deputados estaduais de PE e prefeituras e câmaras que merecem
          verificação: empresas recém-abertas, fornecedores que vivem de um só pagador, CNPJ baixado recebendo e outros.
        </p>
      </div>

      <AvisoAlertas />

      {resumo.erro ? (
        <ErroApi erro={resumo.erro} onTentarDeNovo={resumo.recarregar} />
      ) : (
        <section aria-label="Resumo" className="grid gap-4 sm:grid-cols-3">
          <StatCard
            destaque
            icone={AlertTriangle}
            rotulo="Alertas de atenção"
            valor={resumo.dados ? formatarInteiro(resumo.dados.altas) : "…"}
            detalhe="os mais fortes"
          />
          <StatCard icone={Eye} rotulo="Total de alertas" valor={resumo.dados ? formatarInteiro(resumo.dados.total) : "…"} />
          <StatCard
            icone={Users}
            rotulo="Deputados e órgãos com alerta"
            valor={resumo.dados ? formatarInteiro(resumo.dados.qtd_deputados) : "…"}
          />
        </section>
      )}

      <section aria-label="Filtros" className="card grid gap-4 sm:grid-cols-3 lg:grid-cols-7">
        <CampoSelect
          rotulo="Quais"
          valor={valores.forca}
          todos="Todos (mais fortes primeiro)"
          opcoes={[
            { valor: "60", rotulo: "Só os mais fortes" },
            { valor: "40", rotulo: "Fortes e médios" },
          ]}
          onMudar={(forca) => definir({ forca })}
        />
        <CampoSelect
          rotulo="De quem"
          valor={valores.esfera}
          opcoes={(Object.entries(ROTULO_ESFERA) as [string, string][]).map(([valor, rotulo]) => ({ valor, rotulo }))}
          onMudar={(esfera) => definir({ esfera })}
        />
        <CampoSelect
          rotulo="Tipo"
          valor={valores.tipo}
          opcoes={Object.entries(tipos).map(([valor, rotulo]) => ({ valor, rotulo }))}
          onMudar={(tipo) => definir({ tipo })}
        />
        <CampoSelect
          rotulo="Gravidade"
          valor={valores.gravidade}
          todos="Todas"
          opcoes={[
            { valor: "alta", rotulo: "Atenção" },
            { valor: "media", rotulo: "Vale olhar" },
          ]}
          onMudar={(gravidade) => definir({ gravidade })}
        />
        <CampoSelect
          rotulo="Ano"
          valor={valores.ano}
          todos="Todos os anos"
          opcoes={opcoesSimples(filtros.dados?.anos ?? [])}
          onMudar={(ano) => definir({ ano })}
        />
        <CampoSelect
          rotulo="Estado"
          valor={valores.uf}
          opcoes={opcoesSimples(filtros.dados?.ufs ?? [])}
          onMudar={(uf) => definir({ uf })}
        />
        <CampoSelect
          rotulo="Partido"
          valor={valores.partido}
          opcoes={opcoesSimples(filtros.dados?.partidos ?? [])}
          onMudar={(partido) => definir({ partido })}
        />
      </section>

      {valores.tipo && EXPLICACOES[valores.tipo] && (
        <p className="rounded-lg bg-accent-soft px-4 py-3 text-primary">
          <strong>{tipos[valores.tipo]}:</strong> {EXPLICACOES[valores.tipo]}
        </p>
      )}

      <section aria-label="Lista de alertas" className="space-y-3">
        {alertas.erro ? (
          <ErroApi erro={alertas.erro} onTentarDeNovo={alertas.recarregar} />
        ) : !alertas.dados ? (
          <Carregando linhas={6} rotulo="Carregando alertas" />
        ) : alertas.dados.total === 0 ? (
          <Vazio>Nenhum alerta com esses filtros.</Vazio>
        ) : (
          <>
            <p className="font-bold text-secondary" aria-live="polite">
              {formatarInteiro(alertas.dados.total)} {alertas.dados.total === 1 ? "alerta" : "alertas"}
            </p>
            {alertas.dados.itens.map((a) => (
              <CartaoAlerta key={a.id} alerta={a} tipos={tipos} />
            ))}
            <Paginacao
              rotulo="Páginas de alertas"
              pagina={pagina}
              porPagina={POR_PAGINA}
              total={alertas.dados.total}
              onMudar={(p) => definir({ pagina: p })}
            />
          </>
        )}
      </section>

      <section aria-labelledby="como-funciona" className="card space-y-3">
        <h2 id="como-funciona" className="text-xl font-bold text-primary">
          Como cada alerta é calculado
        </h2>
        <dl className="grid gap-3 sm:grid-cols-2">
          {Object.entries(EXPLICACOES).map(([tipo, texto]) => (
            <div key={tipo}>
              <dt className="font-bold text-primary">{tipos[tipo] ?? tipo}</dt>
              <dd className="text-secondary">{texto}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
