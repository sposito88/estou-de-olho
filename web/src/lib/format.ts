/** Formatação pt-BR. Os valores chegam da API como string decimal ("1234.56");
 * a conversão para número acontece só aqui, na renderização. */

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const brlCompacto = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  notation: "compact",
  maximumFractionDigits: 1,
});
const inteiro = new Intl.NumberFormat("pt-BR");

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const MESES_LONGOS = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

export const paraNumero = (valor: string | number | null | undefined): number => Number(valor ?? 0);

/** R$ 1.234,56 */
export const formatarBRL = (valor: string | number | null | undefined): string => brl.format(paraNumero(valor));

/** R$ 1,2 mi */
export const formatarBRLCompacto = (valor: string | number | null | undefined): string =>
  brlCompacto.format(paraNumero(valor));

export const formatarInteiro = (valor: number): string => inteiro.format(valor);

/** "2024-03-10" -> "10/03/2024" (sem passar por Date, para não sofrer com fuso). */
export function formatarData(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [ano, mes, dia] = iso.slice(0, 10).split("-");
  return dia && mes && ano ? `${dia}/${mes}/${ano}` : "—";
}

export function formatarDataHora(iso: string | null | undefined): string {
  if (!iso) return "—";
  const hora = iso.slice(11, 16);
  return hora ? `${formatarData(iso)} às ${hora}` : formatarData(iso);
}

export const mesCurto = (ano: number, mes: number): string => `${MESES[mes - 1]}/${String(ano).slice(2)}`;
export const mesLongo = (ano: number, mes: number): string => `${MESES_LONGOS[mes - 1]} de ${ano}`;

/** "MANUTENÇÃO DE ESCRITÓRIO" -> "Manutenção de escritório" */
export function capitalizar(texto: string | null | undefined): string {
  if (!texto) return "";
  const minusculo = texto.toLocaleLowerCase("pt-BR");
  return minusculo.charAt(0).toLocaleUpperCase("pt-BR") + minusculo.slice(1);
}

/** Tipo de despesa da Câmara para exibição: "COMBUSTÍVEIS E LUBRIFICANTES." -> "Combustíveis e lubrificantes" */
export function rotuloDespesa(tipo: string | null | undefined): string {
  return capitalizar(tipo)
    .replace(/\s+,/g, ",")
    .replace(/,(?=\S)/g, ", ")
    .replace(/\s*\.$/, "");
}

/** "CARPINA" / "POÇO REDONDO" -> "Carpina" / "Poço Redondo" */
export function nomeProprio(texto: string | null | undefined): string {
  if (!texto) return "";
  const minusculas = new Set(["de", "da", "do", "das", "dos", "e"]);
  return texto
    .toLocaleLowerCase("pt-BR")
    .split(" ")
    .map((p, i) => (i > 0 && minusculas.has(p) ? p : p.charAt(0).toLocaleUpperCase("pt-BR") + p.slice(1)))
    .join(" ");
}

/** CNPJ 12345678000195 -> 12.345.678/0001-95; CPF fica parcialmente oculto. */
export function formatarDocumento(doc: string | null | undefined): string {
  if (!doc) return "—";
  if (doc.length === 14) return doc.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");
  if (doc.length === 11) return `***.${doc.slice(3, 6)}.${doc.slice(6, 9)}-**`;
  return doc;
}

export const partidoUf = (partido: string | null, uf: string | null): string =>
  [partido, uf].filter(Boolean).join("-");

export const plural = (n: number, singular: string, pluralForma: string): string =>
  `${formatarInteiro(n)} ${n === 1 ? singular : pluralForma}`;
