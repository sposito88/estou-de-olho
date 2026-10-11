import { Download, Share2 } from "lucide-react";
import { useState } from "react";

export interface DadosCartao {
  /** Linha pequena acima do título (ex.: "Emendas em 2025"). */
  chamada: string;
  titulo: string;
  destaque: string;
  legendaDestaque: string;
  linhas: { rotulo: string; valor: string }[];
  /** Nome do arquivo sem extensão. */
  arquivo: string;
}

const LARGURA = 1080;
const ALTURA = 1350;

function cor(token: string, padrao: string): string {
  const valor = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  return valor || padrao;
}

/** Quebra o texto em linhas que caibam em `largura`. */
function quebrar(ctx: CanvasRenderingContext2D, texto: string, largura: number): string[] {
  const linhas: string[] = [];
  let atual = "";
  for (const palavra of texto.split(" ")) {
    const teste = atual ? `${atual} ${palavra}` : palavra;
    if (ctx.measureText(teste).width > largura && atual) {
      linhas.push(atual);
      atual = palavra;
    } else {
      atual = teste;
    }
  }
  if (atual) linhas.push(atual);
  return linhas;
}

function truncar(ctx: CanvasRenderingContext2D, texto: string, largura: number): string {
  if (ctx.measureText(texto).width <= largura) return texto;
  let t = texto;
  while (t.length > 1 && ctx.measureText(`${t}…`).width > largura) t = t.slice(0, -1);
  return `${t}…`;
}

/** Desenha o cartão 1080×1350 (formato de post) e devolve o PNG. */
async function desenhar(dados: DadosCartao, url: string): Promise<Blob> {
  const fonte = "Atkinson Hyperlegible, system-ui, sans-serif";
  await Promise.all([document.fonts.load(`700 40px ${fonte}`), document.fonts.load(`400 40px ${fonte}`)]).catch(() => []);

  const canvas = document.createElement("canvas");
  canvas.width = LARGURA;
  canvas.height = ALTURA;
  const ctx = canvas.getContext("2d")!;
  const primaria = cor("--color-primary", "#0f172a");
  const destaque = "#38bdf8";
  const suave = "#cbd5e1";
  const m = 88;

  ctx.fillStyle = primaria;
  ctx.fillRect(0, 0, LARGURA, ALTURA);

  ctx.fillStyle = destaque;
  ctx.font = `700 36px ${fonte}`;
  ctx.fillText("ESTOU DE OLHO", m, 130);

  ctx.fillStyle = suave;
  ctx.font = `400 40px ${fonte}`;
  ctx.fillText(dados.chamada, m, 230);

  ctx.fillStyle = "#ffffff";
  ctx.font = `700 76px ${fonte}`;
  let y = 330;
  for (const linha of quebrar(ctx, dados.titulo, LARGURA - 2 * m).slice(0, 2)) {
    ctx.fillText(linha, m, y);
    y += 90;
  }

  y += 60;
  ctx.fillStyle = destaque;
  ctx.font = `700 104px ${fonte}`;
  ctx.fillText(truncar(ctx, dados.destaque, LARGURA - 2 * m), m, y);
  ctx.fillStyle = suave;
  ctx.font = `400 40px ${fonte}`;
  ctx.fillText(dados.legendaDestaque, m, y + 64);

  y += 170;
  ctx.strokeStyle = "rgba(255,255,255,0.15)";
  ctx.lineWidth = 2;
  for (const { rotulo, valor } of dados.linhas.slice(0, 4)) {
    ctx.beginPath();
    ctx.moveTo(m, y - 54);
    ctx.lineTo(LARGURA - m, y - 54);
    ctx.stroke();
    ctx.font = `700 44px ${fonte}`;
    ctx.fillStyle = "#ffffff";
    const larguraValor = ctx.measureText(valor).width;
    ctx.fillText(valor, LARGURA - m - larguraValor, y);
    ctx.font = `400 40px ${fonte}`;
    ctx.fillStyle = suave;
    ctx.fillText(truncar(ctx, rotulo, LARGURA - 2 * m - larguraValor - 32), m, y);
    y += 104;
  }

  ctx.fillStyle = suave;
  ctx.font = `400 32px ${fonte}`;
  ctx.fillText("Dados oficiais: Câmara dos Deputados, Portal da Transparência e IBGE", m, ALTURA - 150);
  ctx.fillStyle = "#ffffff";
  ctx.font = `700 34px ${fonte}`;
  ctx.fillText(truncar(ctx, url.replace(/^https?:\/\//, ""), LARGURA - 2 * m), m, ALTURA - 96);

  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Falha ao gerar imagem"))), "image/png"),
  );
}

/** Botão que gera um cartão para redes sociais. No celular abre o compartilhamento do sistema;
 * no computador baixa a imagem e oferece o link do WhatsApp. */
export function Compartilhar({ dados, texto }: { dados: DadosCartao; texto: string }) {
  const [status, setStatus] = useState<string>("");
  const [gerando, setGerando] = useState(false);
  const url = window.location.href;
  const whatsapp = `https://wa.me/?text=${encodeURIComponent(`${texto}\n${url}`)}`;

  async function compartilhar() {
    setGerando(true);
    setStatus("");
    try {
      const blob = await desenhar(dados, url);
      const arquivo = new File([blob], `${dados.arquivo}.png`, { type: "image/png" });
      if (navigator.canShare?.({ files: [arquivo] })) {
        await navigator.share({ files: [arquivo], text: `${texto}\n${url}` });
        setStatus("Pronto para compartilhar.");
      } else {
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = arquivo.name;
        link.click();
        URL.revokeObjectURL(link.href);
        setStatus("Imagem baixada. Agora é só anexar no WhatsApp ou na rede social.");
      }
    } catch (erro) {
      if (!(erro instanceof DOMException && erro.name === "AbortError")) {
        setStatus("Não foi possível gerar a imagem neste navegador.");
      }
    } finally {
      setGerando(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="btn-primary" onClick={compartilhar} disabled={gerando}>
        {gerando ? <Download aria-hidden className="size-5" /> : <Share2 aria-hidden className="size-5" />}
        {gerando ? "Gerando imagem…" : "Compartilhar"}
      </button>
      <a href={whatsapp} target="_blank" rel="noreferrer noopener" className="btn-secondary">
        Enviar no WhatsApp
        <span className="sr-only">(abre em nova aba)</span>
      </a>
      <p className="w-full text-sm text-muted-foreground" aria-live="polite">
        {status}
      </p>
    </div>
  );
}
