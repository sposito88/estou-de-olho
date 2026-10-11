import { useCallback, useEffect, useState } from "react";
import { API_URL, CACHE_TTL_MS } from "./config";

export type Params = Record<string, string | number | null | undefined>;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** A API não respondeu (fora do ar, CORS, rede). */
  get foraDoAr(): boolean {
    return this.status === null;
  }
}

const cache = new Map<string, { quando: number; dados: unknown }>();

export function montarUrl(caminho: string, params: Params = {}): string {
  const url = new URL(`${API_URL}${caminho}`);
  for (const [chave, valor] of Object.entries(params)) {
    if (valor !== null && valor !== undefined && valor !== "") url.searchParams.set(chave, String(valor));
  }
  return url.toString();
}

/** GET com cache em memória de 10 minutos (equivalente ao st.cache_data(ttl=600)). */
export async function buscar<T>(caminho: string, params: Params = {}, signal?: AbortSignal): Promise<T> {
  const url = montarUrl(caminho, params);
  const emCache = cache.get(url);
  if (emCache && Date.now() - emCache.quando < CACHE_TTL_MS) return emCache.dados as T;

  let resposta: Response;
  try {
    resposta = await fetch(url, { signal, headers: { Accept: "application/json" } });
  } catch (erro) {
    if (erro instanceof DOMException && erro.name === "AbortError") throw erro;
    throw new ApiError(`Não foi possível falar com a API em ${API_URL}.`, null);
  }
  if (!resposta.ok) {
    let detalhe = resposta.statusText;
    try {
      const corpo = (await resposta.json()) as { detail?: unknown };
      if (typeof corpo.detail === "string") detalhe = corpo.detail;
    } catch {
      /* corpo não-JSON: mantém o statusText */
    }
    throw new ApiError(detalhe || `Erro ${resposta.status}`, resposta.status);
  }
  const dados = (await resposta.json()) as T;
  cache.set(url, { quando: Date.now(), dados });
  return dados;
}

export interface EstadoApi<T> {
  dados: T | undefined;
  erro: ApiError | undefined;
  carregando: boolean;
  recarregar: () => void;
}

/** Busca `caminho` sempre que ele ou os parâmetros mudarem. `caminho` nulo não busca. */
export function useApi<T>(caminho: string | null, params: Params = {}): EstadoApi<T> {
  const chave = caminho ? montarUrl(caminho, params) : null;
  const [estado, setEstado] = useState<{ chave: string | null; dados?: T; erro?: ApiError }>({ chave: null });
  const [versao, setVersao] = useState(0);

  useEffect(() => {
    if (!caminho || !chave) return;
    const controle = new AbortController();
    buscar<T>(caminho, params, controle.signal)
      .then((dados) => setEstado({ chave, dados }))
      .catch((erro: unknown) => {
        if (erro instanceof DOMException && erro.name === "AbortError") return;
        setEstado({ chave, erro: erro instanceof ApiError ? erro : new ApiError(String(erro), null) });
      });
    return () => controle.abort();
    // `chave` já codifica caminho + params, então params não entra nas dependências.
  }, [chave, versao]);

  const recarregar = useCallback(() => {
    if (chave) cache.delete(chave);
    setVersao((v) => v + 1);
  }, [chave]);

  const atual = estado.chave === chave;
  return {
    dados: atual ? estado.dados : undefined,
    erro: atual ? estado.erro : undefined,
    carregando: Boolean(chave) && !atual,
    recarregar,
  };
}
