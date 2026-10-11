import { CheckCircle2 } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router";
import { ApiError } from "../lib/api";
import { postar } from "../lib/postar";
import { useParametros } from "../lib/useParametros";

const TIPOS = [
  { valor: "erro", rotulo: "Há um erro nos dados", ajuda: "Diga o que está errado e, se puder, onde está a informação certa." },
  {
    valor: "resposta",
    rotulo: "Sou a pessoa ou empresa citada e quero responder",
    ajuda: "Sua resposta pode ser publicada ao lado do que foi mostrado (direito de resposta).",
  },
  {
    valor: "privacidade",
    rotulo: "Pedido sobre meus dados pessoais (LGPD)",
    ajuda: "Correção, explicação ou revisão de como seus dados aparecem aqui.",
  },
] as const;

export function Contestar() {
  const { valores } = useParametros(["url", "alvo"] as const);
  const url = valores.url.startsWith("/") ? valores.url : "/";
  const [tipo, setTipo] = useState<(typeof TIPOS)[number]["valor"]>("erro");
  const [mensagem, setMensagem] = useState("");
  const [nome, setNome] = useState("");
  const [contato, setContato] = useState("");
  const [site, setSite] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [protocolo, setProtocolo] = useState<string | null>(null);
  const ids = { mensagem: useId(), nome: useId(), contato: useId(), site: useId() };

  if (protocolo) {
    return (
      <div className="max-w-2xl space-y-4">
        <h1 className="flex items-center gap-2 text-3xl font-bold text-primary">
          <CheckCircle2 aria-hidden className="size-8 text-accent" /> Recebido
        </h1>
        <p className="text-lg">
          Seu protocolo é <strong className="numero">{protocolo}</strong>. Vamos analisar e, quando houver correção ou
          resposta publicada, ela aparece na página contestada e em <Link to="/correcoes" className="link">Correções</Link>.
        </p>
        <Link to={url} className="btn-secondary">Voltar para a página</Link>
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold text-primary">Contestar ou corrigir</h1>
        <p className="text-secondary">
          Os números vêm de fontes oficiais, mas podem ter erro na origem ou no cruzamento que fazemos. Se algo está
          errado, ou se você foi citado e quer responder, conte aqui.
        </p>
        <p className="text-sm text-muted-foreground">
          Página: <Link to={url} className="link">{url}</Link>
          {valores.alvo && <> · Sobre: {valores.alvo}</>}
        </p>
      </div>

      <form
        className="card space-y-5"
        onSubmit={async (e) => {
          e.preventDefault();
          setErro(null);
          setEnviando(true);
          try {
            const r = await postar<{ protocolo: string }>("/api/contestacoes", {
              tipo, url, alvo: valores.alvo || null, mensagem, nome: nome || null, contato: contato || null, site,
            });
            setProtocolo(r.protocolo);
          } catch (err) {
            setErro(err instanceof ApiError ? err.message : "Não foi possível enviar.");
          } finally {
            setEnviando(false);
          }
        }}
      >
        <fieldset className="space-y-2">
          <legend className="mb-1 font-bold text-secondary">O que você quer fazer?</legend>
          {TIPOS.map((t) => (
            <label key={t.valor} className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3 has-[:checked]:border-accent">
              <input type="radio" name="tipo" value={t.valor} checked={tipo === t.valor} onChange={() => setTipo(t.valor)}
                     className="mt-1 size-4 accent-[var(--color-accent)]" />
              <span>
                <span className="block font-bold">{t.rotulo}</span>
                <span className="block text-sm text-muted-foreground">{t.ajuda}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <div>
          <label htmlFor={ids.mensagem} className="mb-1 block font-bold text-secondary">Sua mensagem</label>
          <textarea id={ids.mensagem} required minLength={20} maxLength={4000} rows={7} value={mensagem}
                    onChange={(e) => setMensagem(e.target.value)} className="input min-h-40 py-2" />
          <p className="mt-1 text-sm text-muted-foreground">Mínimo de 20 caracteres. Links para documentos ajudam.</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor={ids.nome} className="mb-1 block font-bold text-secondary">Nome (opcional)</label>
            <input id={ids.nome} className="input" maxLength={200} value={nome} onChange={(e) => setNome(e.target.value)}
                   autoComplete="name" />
          </div>
          <div>
            <label htmlFor={ids.contato} className="mb-1 block font-bold text-secondary">E-mail ou telefone (opcional)</label>
            <input id={ids.contato} className="input" maxLength={200} value={contato}
                   onChange={(e) => setContato(e.target.value)} autoComplete="email" />
          </div>
        </div>
        {/* Campo invisível para robôs. */}
        <div aria-hidden className="absolute -left-[9999px]">
          <label htmlFor={ids.site}>Não preencha</label>
          <input id={ids.site} tabIndex={-1} autoComplete="off" value={site} onChange={(e) => setSite(e.target.value)} />
        </div>

        <p className="text-sm text-muted-foreground">
          Seu nome e contato nunca são publicados; servem só para falarmos com você. Veja a{" "}
          <Link to="/privacidade" className="link">política de privacidade</Link>.
        </p>
        {erro && <p role="alert" className="rounded-lg bg-destructive-soft px-4 py-3 text-destructive">{erro}</p>}
        <button type="submit" className="btn-primary" disabled={enviando}>
          {enviando ? "Enviando…" : "Enviar"}
        </button>
      </form>
    </div>
  );
}
