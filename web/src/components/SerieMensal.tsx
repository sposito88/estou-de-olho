import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatarBRL, formatarBRLCompacto, mesCurto, mesLongo, paraNumero } from "../lib/format";

export interface PontoMensal {
  ano: number;
  mes: number;
  valor: string;
}

interface SerieMensalProps {
  pontos: PontoMensal[];
  titulo: string;
}

/** Colunas por mês, com resumo textual e tabela equivalente para leitores de tela. */
export function SerieMensal({ pontos, titulo }: SerieMensalProps) {
  const dados = pontos.map((p) => ({ ...p, rotulo: mesCurto(p.ano, p.mes), numero: paraNumero(p.valor) }));
  const maior = dados.reduce<(typeof dados)[number] | undefined>((m, p) => (!m || p.numero > m.numero ? p : m), undefined);
  const total = dados.reduce((s, p) => s + p.numero, 0);
  const media = dados.length ? total / dados.length : 0;

  return (
    <figure>
      <div className="h-64 w-full sm:h-72" aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={dados} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--color-border)" />
            <XAxis
              dataKey="rotulo"
              tick={{ fill: "var(--color-muted-foreground)", fontSize: 13 }}
              tickLine={false}
              axisLine={{ stroke: "var(--color-border)" }}
              interval="preserveStartEnd"
              minTickGap={12}
            />
            <YAxis
              tickFormatter={(v: number) => formatarBRLCompacto(v)}
              tick={{ fill: "var(--color-muted-foreground)", fontSize: 13 }}
              tickLine={false}
              axisLine={false}
              width={84}
            />
            <Tooltip
              cursor={{ fill: "var(--color-muted)" }}
              formatter={(v) => [formatarBRL(Number(v)), "Total"]}
              labelFormatter={(_, payload) => {
                const p = payload?.[0]?.payload as PontoMensal | undefined;
                return p ? mesLongo(p.ano, p.mes) : "";
              }}
              contentStyle={{ borderRadius: 8, borderColor: "var(--color-border)", fontFamily: "inherit" }}
            />
            <Bar dataKey="numero" fill="var(--color-accent)" radius={[4, 4, 0, 0]} maxBarSize={40} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-3 text-sm text-muted-foreground">
        {maior
          ? `${titulo}: média de ${formatarBRL(media)} por mês; o maior valor foi em ${mesLongo(maior.ano, maior.mes)} (${formatarBRL(maior.numero)}).`
          : titulo}
      </figcaption>
      <details className="mt-2">
        <summary className="inline-flex min-h-11 cursor-pointer items-center font-bold text-accent">
          Ver os valores em tabela
        </summary>
        <div className="mt-2 max-h-80 overflow-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <caption className="sr-only">{titulo}</caption>
            <thead className="sticky top-0 bg-muted text-left">
              <tr>
                <th scope="col" className="px-3 py-2">Mês</th>
                <th scope="col" className="px-3 py-2 text-right">Valor</th>
              </tr>
            </thead>
            <tbody>
              {dados.map((p) => (
                <tr key={`${p.ano}-${p.mes}`} className="border-t border-border">
                  <th scope="row" className="px-3 py-2 text-left font-normal">{mesLongo(p.ano, p.mes)}</th>
                  <td className="numero px-3 py-2 text-right">{formatarBRL(p.valor)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
