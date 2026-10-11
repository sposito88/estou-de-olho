import { useEffect } from "react";

/** Pede aos buscadores (Google etc.) que não indexem a página enquanto ela estiver aberta.
 * Usado onde aparecem nomes de pessoas físicas sem cargo público (busca, pessoal). */
export function useSemIndexacao(): void {
  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex, nofollow";
    document.head.appendChild(meta);
    return () => meta.remove();
  }, []);
}
