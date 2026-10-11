import { Link } from "react-router";
import { ROTULO_STATUS } from "../components/Contestar";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { Paginacao } from "../components/Paginacao";
import { useApi } from "../lib/api";
import { formatarData } from "../lib/format";
import type { ContestacaoPublica, Pagina } from "../lib/types";
import { useParametros } from "../lib/useParametros";

const POR_PAGINA = 20;

export function Correcoes() {
  const { definir, pagina } = useParametros([] as const);
  const lista = useApi<Pagina<ContestacaoPublica>>("/api/contestacoes", {
    limit: POR_PAGINA,
    offset: (pagina - 1) * POR_PAGINA,
  });
  return (
    <div className="space-y-6">
      <div className="max-w-3xl space-y-2">
        <h1 className="text-3xl font-bold text-primary sm:text-4xl">Correções e direito de resposta</h1>
        <p className="text-secondary">
          Tudo o que foi contestado e já analisado: o que corrigimos, o que mantivemos (e por quê) e as respostas de
          pessoas e empresas citadas. Viu um erro? Use o link “Contestar ou corrigir” na própria página.
        </p>
      </div>
      {lista.erro ? (
        <ErroApi erro={lista.erro} onTentarDeNovo={lista.recarregar} />
      ) : !lista.dados ? (
        <Carregando linhas={4} />
      ) : lista.dados.total === 0 ? (
        <Vazio>Nenhuma contestação analisada até agora.</Vazio>
      ) : (
        <>
          <ul className="space-y-4">
            {lista.dados.itens.map((r) => (
              <li key={r.protocolo} className="card space-y-2">
                <p className="text-sm font-bold text-muted-foreground">
                  {ROTULO_STATUS[r.status]} · {formatarData(r.respondido_em)} · protocolo {r.protocolo}
                </p>
                <p>
                  <Link to={r.url} className="link">{r.alvo ?? r.url}</Link>
                </p>
                {r.resposta_publica && <p className="whitespace-pre-line">{r.resposta_publica}</p>}
              </li>
            ))}
          </ul>
          <Paginacao rotulo="Páginas de correções" pagina={pagina} porPagina={POR_PAGINA} total={lista.dados.total}
                     onMudar={(p) => definir({ pagina: p })} />
        </>
      )}
    </div>
  );
}
