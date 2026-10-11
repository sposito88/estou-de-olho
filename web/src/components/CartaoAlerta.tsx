import { AlertTriangle, Building2, Eye, Landmark } from "lucide-react";
import { Link } from "react-router";
import { useApi } from "../lib/api";
import { formatarBRL, paraNumero, partidoUf } from "../lib/format";
import type { Alerta, Esfera } from "../lib/types";
import { semFoto } from "../lib/foto";
import { BotaoContestar } from "./Contestar";

export const ROTULO_ESFERA: Record<Esfera, string> = {
  federal: "Deputado federal",
  senado: "Senador",
  estadual: "Deputado estadual",
  municipal: "Prefeitura/Câmara",
};

/** Nomes dos tipos de alerta vindos da API (fonte única dos rótulos). */
export function useTiposAlerta(): Record<string, string> {
  return useApi<Record<string, string>>("/api/alertas/tipos").dados ?? {};
}

export function SeloGravidade({ gravidade }: { gravidade: Alerta["gravidade"] }) {
  const alta = gravidade === "alta";
  const Icone = alta ? AlertTriangle : Eye;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-sm font-bold ${
        alta ? "bg-destructive-soft text-destructive" : "bg-warning-soft text-warning"
      }`}
    >
      <Icone aria-hidden className="size-4" />
      {alta ? "Atenção" : "Vale olhar"}
    </span>
  );
}

interface CartaoAlertaProps {
  alerta: Alerta;
  tipos: Record<string, string>;
  mostrarDeputado?: boolean;
  mostrarFornecedor?: boolean;
}

export function CartaoAlerta({ alerta, tipos, mostrarDeputado = true, mostrarFornecedor = true }: CartaoAlertaProps) {
  const alta = alerta.gravidade === "alta";
  return (
    <article
      className={`rounded-xl border border-border border-l-4 bg-card p-4 sm:p-5 ${
        alta ? "border-l-destructive" : "border-l-amber-500"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <SeloGravidade gravidade={alerta.gravidade} />
        <span className="font-bold text-secondary">{tipos[alerta.tipo] ?? alerta.tipo}</span>
        <span className="text-muted-foreground">· {ROTULO_ESFERA[alerta.esfera]}</span>
        {alerta.ano && <span className="text-muted-foreground">· {alerta.ano}</span>}
        {alerta.prioridade !== undefined && (
          <span
            className="numero ml-auto rounded-full bg-muted px-2 py-0.5 text-xs font-bold text-secondary"
            title="Prioridade de 0 a 100: tipo do alerta, gravidade, valor e outras evidências sobre o mesmo CNPJ"
          >
            prioridade {alerta.prioridade}
          </span>
        )}
      </div>
      <h3 className="mt-2 text-lg font-bold leading-snug text-primary">{alerta.titulo}</h3>
      <p className="mt-1 text-secondary">{alerta.descricao}</p>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        {mostrarDeputado && alerta.deputado && (
          <Link to={`/deputados/${alerta.deputado.id}`} className="link inline-flex min-h-11 items-center gap-2">
            <img
              onError={semFoto}
              src={alerta.deputado.url_foto ?? undefined}
              alt=""
              width={24}
              height={24}
              loading="lazy"
              className="size-6 rounded-full bg-muted object-cover"
            />
            {alerta.deputado.nome}
            <span className="font-normal text-muted-foreground no-underline">
              ({partidoUf(alerta.deputado.sigla_partido, alerta.deputado.sigla_uf)})
            </span>
          </Link>
        )}
        {mostrarDeputado && alerta.deputado_estadual && (
          <Link to={`/estaduais/${alerta.deputado_estadual.id}`} className="link inline-flex min-h-11 items-center gap-2">
            {alerta.deputado_estadual.url_foto && (
              <img
                onError={semFoto}
                src={alerta.deputado_estadual.url_foto}
                alt=""
                width={24}
                height={24}
                loading="lazy"
                className="size-6 rounded-full bg-muted object-cover"
              />
            )}
            {alerta.deputado_estadual.nome}
            {alerta.deputado_estadual.sigla_partido && (
              <span className="font-normal text-muted-foreground no-underline">
                ({alerta.deputado_estadual.sigla_partido}-PE)
              </span>
            )}
          </Link>
        )}
        {mostrarDeputado && alerta.senador && (
          <Link to={`/senadores/${alerta.senador.id}`} className="link inline-flex min-h-11 items-center gap-2">
            {alerta.senador.url_foto && (
              <img
                onError={semFoto}
                src={alerta.senador.url_foto}
                alt=""
                width={24}
                height={24}
                loading="lazy"
                className="size-6 rounded-full bg-muted object-cover"
              />
            )}
            {alerta.senador.nome}
            <span className="font-normal text-muted-foreground no-underline">
              ({[alerta.senador.sigla_partido, alerta.senador.sigla_uf].filter(Boolean).join("-")})
            </span>
          </Link>
        )}
        {mostrarDeputado && alerta.orgao_contratante && (
          <Link
            to={
              alerta.municipio
                ? `/cidade/${alerta.municipio.sigla_uf}/${encodeURIComponent(alerta.municipio.nome)}/contratos`
                : "#"
            }
            className="link inline-flex min-h-11 items-center gap-1"
          >
            <Landmark aria-hidden className="size-4" /> {alerta.orgao_contratante.nome}
            {alerta.municipio && (
              <span className="font-normal text-muted-foreground no-underline">
                ({alerta.municipio.nome}-{alerta.municipio.sigla_uf})
              </span>
            )}
          </Link>
        )}
        {mostrarDeputado && alerta.orgao && (
          <Link
            to={`/cidade/${alerta.orgao.sigla_uf}/${encodeURIComponent(alerta.orgao.municipio)}/${
              (alerta.orgao.natureza ?? "").startsWith("Câmara") ? "camara" : "prefeitura"
            }`}
            className="link inline-flex min-h-11 items-center gap-1"
          >
            <Landmark aria-hidden className="size-4" /> {alerta.orgao.nome}
          </Link>
        )}
        {mostrarFornecedor && alerta.cnpj && (
          <Link to={`/fornecedores/${alerta.cnpj}`} className="link inline-flex min-h-11 items-center gap-1">
            <Building2 aria-hidden className="size-4" /> Ver fornecedor
          </Link>
        )}
        {paraNumero(alerta.valor) > 0 && (
          <span className="numero font-bold text-primary">{formatarBRL(alerta.valor)}</span>
        )}
        <span className="ml-auto">
          <BotaoContestar alvo={`Alerta: ${alerta.titulo}`} url={alerta.cnpj ? `/fornecedores/${alerta.cnpj}` : undefined} />
        </span>
      </div>
    </article>
  );
}

export function AvisoAlertas() {
  return (
    <p className="rounded-lg bg-warning-soft px-4 py-3 text-sm text-warning">
      <strong>Alerta não é acusação.</strong> São padrões calculados automaticamente a partir dos dados oficiais
      que merecem uma olhada no documento (nota fiscal ou empenho). Muitos têm explicação legítima.
    </p>
  );
}
