/** Configuração do front, lida das variáveis VITE_* (arquivo web/.env). */

/** Vazio = mesma origem do site (deploy com proxy reverso, ver deploy/Caddyfile). */
export const API_URL = (import.meta.env.VITE_API_URL || window.location.origin).replace(/\/+$/, "");

export const MUNICIPIO_PADRAO = {
  uf: (import.meta.env.VITE_MUNICIPIO_PADRAO_UF ?? "PE").toUpperCase(),
  nome: import.meta.env.VITE_MUNICIPIO_PADRAO_NOME ?? "Carpina",
};

export const CACHE_TTL_MS = 10 * 60 * 1000;

export const LINKS_EXTERNOS = {
  perfilDeputado: (id: number) => `https://www.camara.leg.br/deputados/${id}`,
  dadosCamara: "https://dadosabertos.camara.leg.br",
  cotaCamara: "https://www.camara.leg.br/transparencia/gastos-parlamentares",
  portalTransparencia: "https://portaldatransparencia.gov.br/emendas",
};
