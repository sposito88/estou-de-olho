import { BellRing, ExternalLink, Send } from "lucide-react";
import { TELEGRAM_CANAL } from "../lib/config";

const ITENS = [
  "Os sinais de alerta mais fortes, assim que aparecem nos dados oficiais",
  "Aviso quando chega dinheiro de emenda nas cidades acompanhadas",
  "Poucas mensagens: um resumo por dia, só quando há novidade",
];

/** Chamada para o canal público do Telegram (some se não houver canal configurado). */
export function ChamadaTelegram() {
  if (!TELEGRAM_CANAL) return null;
  const endereco = TELEGRAM_CANAL.replace(/^https?:\/\//, "");
  return (
    <aside aria-labelledby="telegram-titulo" className="rounded-2xl bg-primary p-6 text-on-primary shadow-lg sm:p-7">
      <p className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-sky-300">
        <Send aria-hidden className="size-4" /> Canal no Telegram
      </p>
      <h2 id="telegram-titulo" className="mt-3 text-2xl font-bold leading-tight">
        Os alertas chegam até você
      </h2>
      <ul className="mt-4 space-y-3">
        {ITENS.map((item) => (
          <li key={item} className="flex gap-3 text-slate-200">
            <BellRing aria-hidden className="mt-0.5 size-5 shrink-0 text-sky-300" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
      <a
        href={TELEGRAM_CANAL}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-6 inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-lg bg-white px-5 text-lg font-bold text-primary transition-colors duration-150 hover:bg-sky-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
      >
        Entrar no canal <ExternalLink aria-hidden className="size-5" />
      </a>
      <p className="mt-3 text-center text-sm text-slate-300">
        {endereco} · grátis, sem cadastro
      </p>
    </aside>
  );
}
