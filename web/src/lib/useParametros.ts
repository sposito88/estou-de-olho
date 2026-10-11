import { useCallback } from "react";
import { useSearchParams } from "react-router";

/** Lê e grava filtros na query string, para que todo estado da tela vire um link compartilhável. */
export function useParametros<K extends string>(chaves: readonly K[]) {
  const [busca, setBusca] = useSearchParams();

  const valores = Object.fromEntries(chaves.map((c) => [c, busca.get(c) ?? ""])) as Record<K, string>;

  const definir = useCallback(
    (mudancas: Partial<Record<K | "pagina", string | number | null>>) => {
      setBusca(
        (atual) => {
          const proxima = new URLSearchParams(atual);
          for (const [chave, valor] of Object.entries(mudancas)) {
            if (valor === null || valor === undefined || valor === "") proxima.delete(chave);
            else proxima.set(chave, String(valor));
          }
          // Mudou um filtro: volta para a primeira página.
          if (!("pagina" in mudancas)) proxima.delete("pagina");
          return proxima;
        },
        { replace: true },
      );
    },
    [setBusca],
  );

  const pagina = Math.max(1, Number(busca.get("pagina")) || 1);
  return { valores, definir, pagina };
}
