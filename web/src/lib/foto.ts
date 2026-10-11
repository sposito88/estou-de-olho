import type { SyntheticEvent } from "react";

const TRANSPARENTE = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";

/** Foto externa que falhou: troca por um pixel transparente e fica só o círculo de fundo. */
export function semFoto(evento: SyntheticEvent<HTMLImageElement>): void {
  if (evento.currentTarget.src !== TRANSPARENTE) evento.currentTarget.src = TRANSPARENTE;
}
