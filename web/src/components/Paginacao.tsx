import { ChevronLeft, ChevronRight } from "lucide-react";
import { formatarInteiro } from "../lib/format";

interface PaginacaoProps {
  pagina: number;
  porPagina: number;
  total: number;
  onMudar: (pagina: number) => void;
  rotulo: string;
}

export function Paginacao({ pagina, porPagina, total, onMudar, rotulo }: PaginacaoProps) {
  const ultima = Math.max(1, Math.ceil(total / porPagina));
  if (total <= porPagina) return null;
  const inicio = (pagina - 1) * porPagina + 1;
  const fim = Math.min(pagina * porPagina, total);

  return (
    <nav aria-label={rotulo} className="mt-4 flex flex-wrap items-center justify-between gap-3">
      <p className="numero text-sm text-muted-foreground" aria-live="polite">
        {formatarInteiro(inicio)}–{formatarInteiro(fim)} de {formatarInteiro(total)}
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          className="btn-secondary"
          onClick={() => onMudar(pagina - 1)}
          disabled={pagina <= 1}
        >
          <ChevronLeft aria-hidden className="size-5" /> Anterior
        </button>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => onMudar(pagina + 1)}
          disabled={pagina >= ultima}
        >
          Próxima <ChevronRight aria-hidden className="size-5" />
        </button>
      </div>
    </nav>
  );
}
