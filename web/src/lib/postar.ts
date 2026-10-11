import { ApiError } from "./api";
import { API_URL } from "./config";

/** POST de JSON; devolve o corpo da resposta ou lança ApiError com a mensagem da API. */
export async function postar<T>(caminho: string, corpo: unknown): Promise<T> {
  let resposta: Response;
  try {
    resposta = await fetch(`${API_URL}${caminho}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(corpo),
    });
  } catch {
    throw new ApiError("Não foi possível falar com o servidor. Tente de novo.", null);
  }
  const dados = (await resposta.json().catch(() => ({}))) as { detail?: unknown };
  if (!resposta.ok) {
    const detalhe = typeof dados.detail === "string" ? dados.detail : "Confira os campos e tente de novo.";
    throw new ApiError(detalhe, resposta.status);
  }
  return dados as T;
}
