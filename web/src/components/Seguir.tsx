import { Check, Copy, Rss } from "lucide-react";
import { useState } from "react";
import { montarUrl } from "../lib/api";

interface SeguirProps {
  /** Filtros do feed de alertas: municipio_ibge, cnpj, deputado_id, senador_id ou deputado_estadual_id. */
  filtro: Record<string, string | number>;
  titulo: string;
}

/** "Seguir": endereço do feed de alertas novos, para leitor de RSS ou serviço de RSS por e-mail. */
export function Seguir({ filtro, titulo }: SeguirProps) {
  const [aberto, setAberto] = useState(false);
  const [copiado, setCopiado] = useState(false);
  const url = montarUrl("/api/alertas/feed.xml", { ...filtro, titulo });
  return (
    <div className="text-sm">
      <button type="button" className="btn-secondary min-h-10" aria-expanded={aberto} onClick={() => setAberto((v) => !v)}>
        <Rss aria-hidden className="size-4" /> Seguir alertas
      </button>
      {aberto && (
        <div className="mt-2 max-w-xl space-y-2 rounded-lg border border-border bg-card p-3 text-primary">
          <p>
            Receba os alertas novos de <strong>{titulo}</strong> num leitor de RSS (Feedly, Inoreader, o app de notícias do
            celular) ou por e-mail, colando este endereço num serviço como Blogtrottr ou FeedRabbit:
          </p>
          <div className="flex gap-2">
            <input readOnly value={url} className="input min-h-10 font-mono text-xs" aria-label="Endereço do feed" />
            <button
              type="button"
              className="btn-secondary min-h-10 shrink-0"
              onClick={async () => {
                await navigator.clipboard.writeText(url);
                setCopiado(true);
                setTimeout(() => setCopiado(false), 2500);
              }}
            >
              {copiado ? <Check aria-hidden className="size-4" /> : <Copy aria-hidden className="size-4" />}
              {copiado ? "Copiado" : "Copiar"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
