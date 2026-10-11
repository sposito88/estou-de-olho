import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  rotulo: string;
  valor: string;
  detalhe?: string;
  icone: LucideIcon;
  destaque?: boolean;
}

export function StatCard({ rotulo, valor, detalhe, icone: Icone, destaque = false }: StatCardProps) {
  return (
    <div
      className={`card flex min-w-0 items-start gap-4 ${destaque ? "border-primary bg-primary text-on-primary" : ""}`}
    >
      <span
        aria-hidden
        className={`grid size-11 shrink-0 place-items-center rounded-lg ${
          destaque ? "bg-white/10 text-sky-300" : "bg-accent-soft text-accent"
        }`}
      >
        <Icone className="size-6" />
      </span>
      <div className="@container min-w-0 flex-1">
        <p className={`text-sm font-bold ${destaque ? "text-slate-300" : "text-muted-foreground"}`}>{rotulo}</p>
        <p className="numero mt-0.5 whitespace-nowrap text-lg font-bold leading-tight @[13rem]:text-xl @[16rem]:text-2xl @[20rem]:text-3xl">{valor}</p>
        {detalhe && <p className={`mt-1 text-sm ${destaque ? "text-slate-300" : "text-muted-foreground"}`}>{detalhe}</p>}
      </div>
    </div>
  );
}
