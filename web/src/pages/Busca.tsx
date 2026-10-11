import {
  Briefcase,
  Building2,
  ExternalLink,
  FileSignature,
  HandCoins,
  Landmark,
  type LucideIcon,
  Receipt,
  Users,
  Vote,
} from "lucide-react";
import { Link, useParams } from "react-router";
import { CabecalhoCidade } from "../components/CabecalhoCidade";
import { CampoBusca } from "../components/CampoBusca";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { useApi } from "../lib/api";
import { capitalizar, formatarBRL, formatarDocumento, nomeProprio, paraNumero } from "../lib/format";
import type { Busca as DadosBusca, PapelBusca, ResultadoBusca } from "../lib/types";
import { useParametros } from "../lib/useParametros";
import { useSemIndexacao } from "../lib/semIndexacao";
import { BotaoContestar } from "../components/Contestar";

const TIPOS: Record<PapelBusca["tipo"], { rotulo: string; Icone: LucideIcon; valor?: string }> = {
  empresa: { rotulo: "Empresa fornecedora", Icone: Building2, valor: "recebeu de órgãos públicos (total)" },
  pagamento: { rotulo: "Paga por órgão municipal", Icone: Receipt, valor: "pagos por este órgão" },
  contrato: { rotulo: "Contratada (PNCP)", Icone: FileSignature, valor: "em contratos com este órgão" },
  deputado: { rotulo: "Deputado(a) federal", Icone: Landmark },
  senador: { rotulo: "Senador(a)", Icone: Landmark },
  estadual: { rotulo: "Deputado(a) estadual", Icone: Landmark },
  servidor: { rotulo: "Servidor(a) municipal", Icone: Briefcase },
  socio: { rotulo: "Sócio(a) de fornecedor", Icone: Users },
  candidato: { rotulo: "Candidato(a)", Icone: Vote, valor: "bens declarados" },
  doador: { rotulo: "Doador(a) de campanha", Icone: HandCoins, valor: "doados" },
  credor: { rotulo: "Recebeu como pessoa física", Icone: Receipt, valor: "recebidos" },
};

function Papel({ p }: { p: PapelBusca }) {
  const tipo = TIPOS[p.tipo];
  const Icone = tipo.Icone;
  const onde = [p.orgao && capitalizar(p.orgao), p.lugar, p.ano].filter(Boolean).join(" · ");
  const conteudo = (
    <div className="flex items-start gap-3">
      <span aria-hidden className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
        <Icone className="size-5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold text-muted-foreground">{tipo.rotulo}</p>
        <p className="font-bold text-primary">{p.papel}</p>
        {onde && <p className="text-sm text-secondary">{onde}</p>}
        {p.valor !== null && paraNumero(p.valor) > 0 && tipo.valor && (
          <p className="text-sm">
            <strong className="numero">{formatarBRL(p.valor)}</strong> {tipo.valor}
          </p>
        )}
      </div>
      {p.url && <ExternalLink aria-hidden className="mt-1 size-4 shrink-0 text-muted-foreground" />}
    </div>
  );
  return (
    <li>
      {p.url ? (
        <Link to={p.url} className="-mx-2 block rounded-lg px-2 py-2 transition-colors duration-150 hover:bg-background">
          {conteudo}
        </Link>
      ) : (
        <div className="py-2">{conteudo}</div>
      )}
    </li>
  );
}

function CartaoResultado({ r }: { r: ResultadoBusca }) {
  const titulo = r.tipo_pessoa === "PJ" ? r.titulo : nomeProprio(r.titulo);
  return (
    <article className="card space-y-3">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-xl font-bold text-primary">
          {r.tipo_pessoa === "PJ" && r.documento ? (
            <Link to={`/fornecedores/${r.documento}`} className="link">{titulo}</Link>
          ) : (
            titulo
          )}
        </h2>
        <p className="numero text-sm text-muted-foreground">
          {r.tipo_pessoa === "PJ" ? `CNPJ ${formatarDocumento(r.documento)}` : r.documento ? `CPF ${r.documento}` : "pessoa física"}
        </p>
      </header>
      {r.homonimos_possiveis && (
        <p className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">
          Alguns itens foram ligados só pelo nome (sem CPF). Pode ser outra pessoa com o mesmo nome.
        </p>
      )}
      <ul className="divide-y divide-border">
        {r.papeis.map((p, i) => (
          <Papel key={`${p.tipo}-${p.url}-${i}`} p={p} />
        ))}
      </ul>
      <BotaoContestar alvo={`Busca: ${r.titulo}`} />
    </article>
  );
}

export function Busca() {
  const { uf, municipio } = useParams();
  const naCidade = Boolean(uf && municipio);
  useSemIndexacao();
  const { valores } = useParametros(["q"] as const);
  const termo = valores.q.trim();
  const busca = useApi<DadosBusca>(termo ? "/api/busca" : null, { q: termo, limit: 30, uf, municipio });
  const cidade = nomeProprio(municipio);

  return (
    <div className="space-y-6">
      {naCidade ? (
        <>
          <CabecalhoCidade key={termo} uf={uf!} municipio={municipio!} />
          <p className="max-w-3xl text-secondary">
            Só o que tem ligação com {cidade}: servidores e pessoas pagas pela prefeitura e pela câmara, empresas pagas
            ou contratadas por elas, sócios de empresas daqui, candidatos e doadores das eleições locais.{" "}
            <Link to={`/busca?q=${encodeURIComponent(termo)}`} className="link">Buscar “{termo}” no Brasil todo</Link>.
          </p>
        </>
      ) : (
        <div className="space-y-3">
          <h1 className="text-3xl font-bold text-primary sm:text-4xl">Buscar pessoa ou empresa</h1>
          <p className="max-w-3xl text-secondary">
            Digite um nome ou CNPJ e veja onde ele aparece: empresa que recebeu dinheiro público (e de quais órgãos),
            parlamentar, servidor municipal, sócio de fornecedor, candidato, doador de campanha ou pessoa paga por
            prefeitura e câmara.
          </p>
          <div className="max-w-3xl">
            <CampoBusca key={termo} inicial={termo} rotulo="Nome ou CNPJ" grande />
          </div>
        </div>
      )}

      {!termo ? null : busca.erro ? (
        <ErroApi erro={busca.erro} onTentarDeNovo={busca.recarregar} />
      ) : !busca.dados ? (
        <Carregando linhas={5} rotulo="Buscando" />
      ) : !busca.dados.indice_disponivel ? (
        <Vazio>O índice de busca ainda está sendo montado. Tente de novo em alguns minutos.</Vazio>
      ) : busca.dados.total === 0 ? (
        <Vazio>
          Nada encontrado para “{termo}”{naCidade ? ` em ${cidade}` : ""}. Confira a grafia ou use menos palavras (ex.:
          só nome e sobrenome).
        </Vazio>
      ) : (
        <>
          <p role="status" className="text-secondary">
            {busca.dados.total > busca.dados.resultados.length
              ? `Mostrando os ${busca.dados.resultados.length} resultados mais próximos de ${busca.dados.total}. Refine a busca para ver outros.`
              : `${busca.dados.total} resultado(s) para “${termo}”.`}
          </p>
          <div className="space-y-4">
            {busca.dados.resultados.map((r, i) => (
              <CartaoResultado key={`${r.titulo}-${r.documento}-${i}`} r={r} />
            ))}
          </div>
        </>
      )}

      <p className="text-sm text-muted-foreground">
        Só aparecem dados que as fontes oficiais já publicam (Receita, TSE, tribunais de contas, Câmara, Senado, ALEPE,
        PNCP). O CPF aparece mascarado, como nas fontes. Itens com o mesmo nome e os mesmos dígitos de CPF são juntados
        como a mesma pessoa; sem CPF, a ligação é só pelo nome.
      </p>
    </div>
  );
}
