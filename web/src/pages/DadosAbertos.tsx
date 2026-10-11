import { Code2, Database, Download, FileJson } from "lucide-react";
import { Carregando, Vazio } from "../components/Estado";
import { useApi } from "../lib/api";
import { formatarData, formatarInteiro } from "../lib/format";

const REPOSITORIO = "https://github.com/sposito88/estou-de-olho";

interface IndiceDados {
  gerado_em: string;
  observacoes: string[];
  conjuntos: { arquivo: string; descricao: string; colunas: string[]; linhas: number; bytes: number }[];
}

function tamanho(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

export function DadosAbertos() {
  const indice = useApi<IndiceDados>("/dados/indice.json");
  return (
    <div className="space-y-6">
      <div className="max-w-3xl space-y-2">
        <h1 className="text-3xl font-bold text-primary sm:text-4xl">Dados abertos e código</h1>
        <p className="text-lg text-secondary">
          Tudo o que o Estou de Olho reúne pode ser baixado, reusado e verificado. O código também é aberto: qualquer
          pessoa pode estudar, melhorar ou colocar outra cópia no ar.
        </p>
      </div>

      <section className="grid gap-4 md:grid-cols-3">
        <a href={REPOSITORIO} className="card flex items-start gap-3 hover:border-accent" rel="noopener">
          <Code2 aria-hidden className="mt-0.5 size-6 shrink-0 text-accent" />
          <span>
            <span className="block font-bold text-primary">Código no GitHub</span>
            <span className="block text-sm text-secondary">Licença AGPL-3.0. Veja como contribuir no repositório.</span>
          </span>
        </a>
        <a href="/docs" className="card flex items-start gap-3 hover:border-accent">
          <FileJson aria-hidden className="mt-0.5 size-6 shrink-0 text-accent" />
          <span>
            <span className="block font-bold text-primary">API pública</span>
            <span className="block text-sm text-secondary">
              Documentação interativa. Limite de 240 consultas por minuto; para volume, use os arquivos abaixo.
            </span>
          </span>
        </a>
        <a href="/dados/" className="card flex items-start gap-3 hover:border-accent">
          <Database aria-hidden className="mt-0.5 size-6 shrink-0 text-accent" />
          <span>
            <span className="block font-bold text-primary">Arquivos (CSV)</span>
            <span className="block text-sm text-secondary">Atualizados toda semana, compactados (gzip), em UTF-8.</span>
          </span>
        </a>
      </section>

      {indice.erro ? (
        <Vazio>Os arquivos ainda estão sendo gerados. Volte em algumas horas.</Vazio>
      ) : !indice.dados ? (
        <Carregando linhas={5} rotulo="Carregando a lista de arquivos" />
      ) : (
        <section aria-labelledby="arquivos-titulo" className="space-y-3">
          <h2 id="arquivos-titulo" className="text-xl font-bold text-primary">
            Conjuntos de dados <span className="text-base font-normal text-muted-foreground">(gerados em {formatarData(indice.dados.gerado_em)})</span>
          </h2>
          <ul className="list-disc space-y-1 pl-6 text-sm text-secondary">
            {indice.dados.observacoes.map((o) => <li key={o}>{o}</li>)}
          </ul>
          <ul className="space-y-3">
            {indice.dados.conjuntos.map((c) => (
              <li key={c.arquivo} className="card space-y-2">
                <div className="flex flex-wrap items-baseline justify-between gap-3">
                  <h3 className="font-bold text-primary">{c.arquivo}</h3>
                  <a href={`/dados/${c.arquivo}`} className="btn-secondary min-h-10 text-sm" download>
                    <Download aria-hidden className="size-4" /> Baixar ({tamanho(c.bytes)})
                  </a>
                </div>
                <p className="text-secondary">{c.descricao}</p>
                <p className="numero text-sm text-muted-foreground">{formatarInteiro(c.linhas)} linhas</p>
                <details className="text-sm">
                  <summary className="cursor-pointer font-bold text-secondary">Colunas</summary>
                  <p className="mt-1 break-words font-mono text-xs">{c.colunas.join(", ")}</p>
                </details>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
