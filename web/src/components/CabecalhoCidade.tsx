import { MapPin } from "lucide-react";
import { NavLink } from "react-router";
import { useApi } from "../lib/api";
import { CampoBusca } from "./CampoBusca";
import { tribunal } from "../lib/tribunal";
import type { Prefeitura } from "../lib/types";
import { nomeProprio } from "../lib/format";

interface CabecalhoCidadeProps {
  uf: string;
  municipio: string;
  /** Nome já formatado, quando a página o conhece melhor que a URL. */
  nome?: string;
}

/** Título da cidade e abas: emendas federais, câmara de vereadores e prefeitura. */
export function CabecalhoCidade({ uf, municipio, nome }: CabecalhoCidadeProps) {
  const base = `/cidade/${uf.toUpperCase()}/${encodeURIComponent(municipio)}`;
  // Câmara e Prefeitura só existem para municípios coletados de um tribunal de contas (TCE-PE, TCE-SP).
  const tce = useApi<Prefeitura>(`/api/municipios/${encodeURIComponent(uf)}/${encodeURIComponent(municipio)}/prefeitura`);
  const abas = [
    { para: base, rotulo: "Emendas federais", fim: true },
    { para: `${base}/emenda-pix`, rotulo: "Emenda Pix" },
    { para: `${base}/contratos`, rotulo: "Contratos" },
    { para: `${base}/contas`, rotulo: "Contas" },
    { para: `${base}/eleitos`, rotulo: "Eleitos" },
    ...(tce.dados
      ? [
          { para: `${base}/camara`, rotulo: "Câmara de vereadores" },
          { para: `${base}/prefeitura`, rotulo: "Prefeitura" },
          ...(tribunal(tce.dados.por_orgao[0]?.orgao.fonte).pessoal ? [{ para: `${base}/pessoal`, rotulo: "Pessoal" }] : []),
        ]
      : []),
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-2">
          <p className="flex items-center gap-1.5 font-bold text-accent">
            <MapPin aria-hidden className="size-5" /> Minha cidade
          </p>
          <h1 className="text-3xl font-bold text-primary sm:text-4xl">
            {nome ?? nomeProprio(municipio)} <span className="text-muted-foreground">– {uf.toUpperCase()}</span>
          </h1>
        </div>
        <div className="w-full text-primary lg:w-[28rem]">
          <CampoBusca
            key={`${uf}-${municipio}`}
            destino={`${base}/busca`}
            rotulo={`Buscar pessoa ou empresa em ${nome ?? nomeProprio(municipio)}`}
            placeholder="Servidor, vereador, empresa, credor ou CNPJ"
          />
        </div>
      </div>
      <nav aria-label="Seções da cidade" className="-mx-4 overflow-x-auto px-4">
        <ul className="flex min-w-max gap-1 border-b border-border">
          {abas.map((aba) => (
            <li key={aba.para}>
              <NavLink
                to={aba.para}
                end={aba.fim}
                className={({ isActive }) =>
                  `-mb-px flex min-h-11 items-center border-b-4 px-4 font-bold transition-colors duration-150 ${
                    isActive
                      ? "border-accent text-primary"
                      : "border-transparent text-muted-foreground hover:border-border hover:text-primary"
                  }`
                }
              >
                {aba.rotulo}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}

/** Aviso para municípios cujas contas ainda não são coletadas de nenhum tribunal de contas. */
export function SemDadosMunicipais({ nome }: { nome: string }) {
  return (
    <p className="rounded-lg bg-muted px-4 py-3 text-secondary">
      Ainda não coletamos as contas da prefeitura e da câmara de {nome}. Por enquanto aparecem aqui os municípios de
      São Paulo (TCE-SP, exceto a capital) e os de Pernambuco configurados no sistema (TCE-PE). Os contratos (aba
      Contratos) e as contas anuais (aba Contas) valem para todo o Brasil.
    </p>
  );
}
