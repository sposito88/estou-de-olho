import type { ReactNode } from "react";

interface SecaoProps {
  id: string;
  titulo: string;
  descricao?: ReactNode;
  acoes?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** Bloco de conteúdo com título ligado por aria-labelledby. */
export function Secao({ id, titulo, descricao, acoes, children, className = "" }: SecaoProps) {
  return (
    <section aria-labelledby={`${id}-titulo`} className={`card min-w-0 ${className}`}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={`${id}-titulo`} className="text-xl font-bold text-primary">
            {titulo}
          </h2>
          {descricao && <p className="mt-1 text-sm text-muted-foreground">{descricao}</p>}
        </div>
        {acoes}
      </div>
      {children}
    </section>
  );
}
