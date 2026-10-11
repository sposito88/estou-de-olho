import type { ReactNode } from "react";
import { Link } from "react-router";
import { formatarBRL, paraNumero } from "../lib/format";
import { semFoto } from "../lib/foto";

export interface ItemBarra {
  chave: string | number;
  rotulo: ReactNode;
  /** Texto do rótulo para leitores de tela quando `rotulo` não é texto puro. */
  rotuloTexto: string;
  detalhe?: ReactNode;
  valor: string | number;
  /** Base do comprimento da barra, quando não for o próprio valor (ex.: índice relativo). */
  medida?: number;
  href?: string;
  imagem?: string | null;
}

interface ListaBarrasProps {
  itens: ItemBarra[];
  rotuloLista: string;
  numerada?: boolean;
  /** Formato do valor escrito (padrão: reais). */
  formatarValor?: (valor: string | number) => string;
}

/** Ranking em barras horizontais feito em HTML: legível no celular, com valor escrito
 * ao lado de cada barra (não depende de cor) e navegável por teclado. */
export function ListaBarras({ itens, rotuloLista, numerada = true, formatarValor = formatarBRL }: ListaBarrasProps) {
  const medida = (i: ItemBarra) => Math.abs(i.medida ?? paraNumero(i.valor));
  const maximo = Math.max(...itens.map(medida), Number.EPSILON);
  const Lista = numerada ? "ol" : "ul";

  return (
    <Lista aria-label={rotuloLista} className="space-y-3">
      {itens.map((item, indice) => {
        const largura = Math.max((medida(item) / maximo) * 100, 0.5);
        const conteudo = (
          <>
            <div className="flex items-baseline justify-between gap-3">
              <span className="flex min-w-0 items-center gap-2">
                {numerada && (
                  <span aria-hidden className="numero w-6 shrink-0 text-right text-sm font-bold text-muted-foreground">
                    {indice + 1}
                  </span>
                )}
                {item.imagem !== undefined && (
                  <img
                    onError={semFoto}
                    src={item.imagem ?? undefined}
                    alt=""
                    loading="lazy"
                    width={32}
                    height={32}
                    className="size-8 shrink-0 rounded-full bg-muted object-cover"
                  />
                )}
                <span className="min-w-0">
                  <span className="block break-words font-bold">{item.rotulo}</span>
                  {item.detalhe && <span className="block break-words text-sm text-muted-foreground">{item.detalhe}</span>}
                </span>
              </span>
              <span className="numero shrink-0 font-bold">{formatarValor(item.valor)}</span>
            </div>
            <div aria-hidden className={`mt-1.5 h-2.5 rounded-full bg-muted ${numerada ? "ml-8" : ""}`}>
              <div className="h-full rounded-full bg-accent" style={{ width: `${largura}%` }} />
            </div>
          </>
        );

        return (
          <li key={item.chave}>
            {item.href ? (
              <Link
                to={item.href}
                aria-label={`${item.rotuloTexto}: ${formatarValor(item.valor)}`}
                className="-mx-2 block rounded-lg px-2 py-1.5 transition-colors duration-150 hover:bg-background"
              >
                {conteudo}
              </Link>
            ) : (
              <div className="py-1.5">{conteudo}</div>
            )}
          </li>
        );
      })}
    </Lista>
  );
}
