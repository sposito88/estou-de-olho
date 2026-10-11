/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_MUNICIPIO_PADRAO_UF?: string;
  readonly VITE_MUNICIPIO_PADRAO_NOME?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
