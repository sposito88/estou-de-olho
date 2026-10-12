import { ShieldAlert, ShieldCheck } from "lucide-react";
import { Link } from "react-router";
import { useApi } from "../lib/api";
import type { TransparenciaItem } from "../lib/types";

/** Pendências de prestação de contas da cidade (Tesouro, tribunal de contas, PNCP, portal). */
export function TransparenciaCidade({ uf, municipio }: { uf: string; municipio: string }) {
  const t = useApi<TransparenciaItem>(`/api/municipios/${encodeURIComponent(uf)}/${encodeURIComponent(municipio)}/transparencia`);
  if (!t.dados) return null;
  const ok = t.dados.pendencias.length === 0;
  const Icone = ok ? ShieldCheck : ShieldAlert;
  return (
    <aside className={`flex gap-3 rounded-xl border p-4 ${ok ? "border-border bg-card" : "border-amber-300 bg-warning-soft"} text-primary`}>
      <Icone aria-hidden className={`mt-0.5 size-5 shrink-0 ${ok ? "text-accent" : "text-warning"}`} />
      <div className="min-w-0 space-y-1">
        <p className="font-bold">
          {ok
            ? "A prefeitura está em dia com a prestação de contas que acompanhamos."
            : `Prestação de contas: ${t.dados.pendencias.length} pendência(s)`}
        </p>
        {!ok && (
          <ul className="list-disc space-y-0.5 pl-5 text-sm">
            {t.dados.pendencias.map((p) => <li key={p}>{p}</li>)}
          </ul>
        )}
        <Link to={`/transparencia?uf=${uf.toUpperCase()}`} className="link text-sm">Comparar com outras cidades</Link>
      </div>
    </aside>
  );
}
