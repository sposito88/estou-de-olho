import { MessageSquareWarning } from "lucide-react";
import { Link, useLocation } from "react-router";
import { useApi } from "../lib/api";
import { formatarData } from "../lib/format";
import type { ContestacaoPublica, Pagina } from "../lib/types";

/** Link para contestar/corrigir o que está na página (ou um item dela). */
export function BotaoContestar({ alvo, url }: { alvo?: string; url?: string }) {
  const { pathname, search } = useLocation();
  const params = new URLSearchParams({ url: url ?? `${pathname}${search}` });
  if (alvo) params.set("alvo", alvo.slice(0, 300));
  return (
    <Link
      to={`/contestar?${params.toString()}`}
      className="inline-flex min-h-11 items-center gap-1 text-sm font-bold text-muted-foreground underline decoration-1 underline-offset-2 hover:text-primary"
    >
      <MessageSquareWarning aria-hidden className="size-4" /> Contestar ou corrigir
    </Link>
  );
}

export const ROTULO_STATUS: Record<ContestacaoPublica["status"], string> = {
  corrigida: "Corrigido",
  mantida: "Analisado e mantido",
  resposta_publicada: "Resposta de quem foi citado",
};

/** Correções e respostas já analisadas sobre a página atual. */
export function RespostasPublicas() {
  const { pathname } = useLocation();
  const respostas = useApi<Pagina<ContestacaoPublica>>("/api/contestacoes", { url: pathname, limit: 10 });
  if (!respostas.dados?.total) return null;
  return (
    <section aria-labelledby="respostas-titulo" className="mt-8 rounded-xl border border-border bg-card p-5">
      <h2 id="respostas-titulo" className="text-lg font-bold text-primary">
        Correções e direito de resposta
      </h2>
      <ul className="mt-3 space-y-4">
        {respostas.dados.itens.map((r) => (
          <li key={r.protocolo} className="border-l-4 border-accent pl-3">
            <p className="text-sm font-bold text-muted-foreground">
              {ROTULO_STATUS[r.status]} · {formatarData(r.respondido_em)} · protocolo {r.protocolo}
            </p>
            {r.alvo && <p className="text-sm text-secondary">Sobre: {r.alvo}</p>}
            {r.resposta_publica && <p className="mt-1 whitespace-pre-line">{r.resposta_publica}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
