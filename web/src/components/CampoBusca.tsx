import { Search } from "lucide-react";
import { useId, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

interface CampoBuscaProps {
  /** Texto inicial; por padrão, o `q` da URL atual. */
  inicial?: string;
  /** Página de resultados (padrão: busca geral). */
  destino?: string;
  placeholder?: string;
  /** Rótulo visível acima do campo. */
  rotulo?: string;
  grande?: boolean;
}

/** Busca por nome de pessoa ou empresa (ou CNPJ): leva para /busca?q=... */
export function CampoBusca({
  inicial,
  destino = "/busca",
  placeholder = "Ex.: nome de uma empresa, de um servidor, de um vereador ou um CNPJ",
  rotulo = "Buscar pessoa ou empresa",
  grande = false,
}: CampoBuscaProps) {
  const [parametros] = useSearchParams();
  const [texto, setTexto] = useState(inicial ?? parametros.get("q") ?? "");
  const navegar = useNavigate();
  const id = useId();
  return (
    <form
      role="search"
      className="w-full"
      onSubmit={(e) => {
        e.preventDefault();
        const termo = texto.trim();
        if (termo) navegar(`${destino}?q=${encodeURIComponent(termo)}`);
      }}
    >
      <label htmlFor={id} className="mb-1 block text-sm font-bold">
        {rotulo}
      </label>
      <div className="flex gap-2">
        <div className="relative min-w-0 flex-1">
          <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" />
          <input
            id={id}
            type="search"
            className={`input pl-10 text-primary ${grande ? "min-h-12 text-lg" : ""}`}
            placeholder={placeholder}
            autoComplete="off"
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
          />
        </div>
        <button type="submit" className="btn-primary shrink-0">
          Buscar
        </button>
      </div>
    </form>
  );
}
