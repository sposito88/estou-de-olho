import { AlertTriangle, Inbox, RefreshCw, ServerOff } from "lucide-react";
import type { ApiError } from "../lib/api";
import { API_URL } from "../lib/config";

export function Carregando({ linhas = 3, rotulo = "Carregando dados" }: { linhas?: number; rotulo?: string }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3">
      <span className="sr-only">{rotulo}…</span>
      {Array.from({ length: linhas }, (_, i) => (
        <div key={i} className="h-5 animate-pulse rounded bg-muted" style={{ width: `${92 - i * 14}%` }} />
      ))}
    </div>
  );
}

export function ErroApi({ erro, onTentarDeNovo }: { erro: ApiError; onTentarDeNovo?: () => void }) {
  const foraDoAr = erro.foraDoAr;
  const Icone = foraDoAr ? ServerOff : AlertTriangle;
  return (
    <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive-soft p-4 text-foreground">
      <div className="flex items-start gap-3">
        <Icone aria-hidden className="mt-0.5 size-5 shrink-0 text-destructive" />
        <div className="space-y-2">
          <p className="font-bold">{foraDoAr ? "A API está fora do ar" : "Não foi possível carregar"}</p>
          <p className="text-sm text-secondary">
            {foraDoAr ? (
              <>
                O site não conseguiu falar com <code className="break-all">{API_URL}</code>. Confira se a API está
                rodando com <code>uvicorn civic.api:app</code>.
              </>
            ) : (
              erro.message
            )}
          </p>
          {onTentarDeNovo && (
            <button type="button" onClick={onTentarDeNovo} className="btn-secondary min-h-10 text-sm">
              <RefreshCw aria-hidden className="size-4" /> Tentar de novo
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function Vazio({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-2 rounded-lg bg-muted px-4 py-3 text-secondary">
      <Inbox aria-hidden className="size-5 shrink-0" />
      {children}
    </p>
  );
}
