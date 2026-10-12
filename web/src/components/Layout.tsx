import { Eye, Menu, X } from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { useApi } from "../lib/api";
import { MUNICIPIO_PADRAO } from "../lib/config";
import { formatarDataHora } from "../lib/format";
import { Carregando } from "./Estado";
import { RespostasPublicas } from "./Contestar";
import { FontesDaPagina } from "./FontesDaPagina";
import type { Health } from "../lib/types";

const NAVEGACAO = [
  { para: "/", rotulo: "Painel", fim: true },
  { para: `/cidade/${MUNICIPIO_PADRAO.uf}/${encodeURIComponent(MUNICIPIO_PADRAO.nome)}`, rotulo: "Minha cidade", base: "/cidade" },
  { para: "/deputados", rotulo: "Deputados" },
  { para: "/senadores", rotulo: "Senado" },
  { para: "/estaduais", rotulo: "Estaduais" },
  { para: "/alertas", rotulo: "Alertas" },
  { para: "/transparencia", rotulo: "Prefeituras" },
  { para: "/busca", rotulo: "Buscar" },
  { para: "/sobre", rotulo: "Sobre os dados" },
];

function ItensNavegacao({ onNavegar }: { onNavegar?: () => void }) {
  const { pathname } = useLocation();
  return (
    <>
      {NAVEGACAO.map((item) => (
        <li key={item.rotulo}>
          <NavLink
            to={item.para}
            end={item.fim}
            onClick={onNavegar}
            className={({ isActive }) => {
              const ativo = isActive || (item.base !== undefined && pathname.startsWith(item.base));
              return `flex min-h-11 items-center rounded-lg px-3 font-bold transition-colors duration-150 ${
                ativo ? "bg-white/15 text-white" : "text-slate-300 hover:bg-white/10 hover:text-white"
              }`;
            }}
          >
            {item.rotulo}
          </NavLink>
        </li>
      ))}
    </>
  );
}

export function Layout() {
  const [menuAberto, setMenuAberto] = useState(false);
  const { pathname } = useLocation();
  const { dados: saude } = useApi<Health>("/health");

  useEffect(() => {
    setMenuAberto(false);
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#conteudo"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-card focus:px-4 focus:py-3 focus:font-bold focus:text-primary"
      >
        Pular para o conteúdo
      </a>

      <header className="bg-primary text-on-primary">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <Link to="/" className="flex min-h-11 items-center gap-2.5 rounded-lg text-lg font-bold">
            <span aria-hidden className="grid size-9 place-items-center rounded-lg bg-white/10">
              <Eye className="size-5 text-sky-300" />
            </span>
            Estou de Olho
          </Link>

          <nav aria-label="Principal" className="hidden lg:block">
            <ul className="flex gap-1">
              <ItensNavegacao />
            </ul>
          </nav>

          <button
            type="button"
            className="grid size-11 cursor-pointer place-items-center rounded-lg hover:bg-white/10 lg:hidden"
            aria-expanded={menuAberto}
            aria-controls="menu-movel"
            onClick={() => setMenuAberto((v) => !v)}
          >
            {menuAberto ? <X aria-hidden className="size-6" /> : <Menu aria-hidden className="size-6" />}
            <span className="sr-only">{menuAberto ? "Fechar menu" : "Abrir menu"}</span>
          </button>
        </div>
        {menuAberto && (
          <nav id="menu-movel" aria-label="Principal" className="border-t border-white/10 px-4 pb-3 lg:hidden">
            <ul className="space-y-1 pt-2">
              <ItensNavegacao onNavegar={() => setMenuAberto(false)} />
            </ul>
          </nav>
        )}
      </header>

      <main id="conteudo" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 outline-none sm:px-6 sm:py-8">
        <Suspense fallback={<Carregando linhas={6} />}>
          <Outlet />
          <RespostasPublicas />
          <FontesDaPagina />
        </Suspense>
      </main>

      <footer className="border-t border-border bg-card">
        <div className="mx-auto max-w-6xl space-y-2 px-4 py-6 text-sm text-muted-foreground sm:px-6">
          <p>
            Dados públicos da Câmara dos Deputados, do Senado Federal, do Portal da Transparência, do PNCP, do Tesouro
            Nacional (Siconfi), do TSE, da Receita Federal, do IBGE, da ALEPE e dos tribunais de contas de PE, SP, RS e PB.{" "}
            <Link to="/sobre" className="link">
              Como usamos cada fonte
            </Link>
            . Projeto cidadão, sem vínculo com órgãos públicos.
          </p>
          <p>Última atualização dos dados: {saude ? formatarDataHora(saude.ultimo_sync) : "—"}</p>
          <p className="flex flex-wrap gap-x-4 gap-y-1">
            <Link to="/contestar" className="link">Contestar ou corrigir</Link>
            <Link to="/correcoes" className="link">Correções e respostas</Link>
            <Link to="/privacidade" className="link">Privacidade (LGPD)</Link>
            <Link to="/dados-abertos" className="link">Dados abertos e código</Link>
          </p>
        </div>
      </footer>
    </div>
  );
}
