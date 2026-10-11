import { useId, useMemo } from "react";
import { Link } from "react-router";
import { CampoSelect, opcoesSimples } from "../components/Campos";
import { Carregando, ErroApi, Vazio } from "../components/Estado";
import { useApi } from "../lib/api";
import { formatarInteiro, partidoUf } from "../lib/format";
import type { Deputado, Filtros } from "../lib/types";
import { useParametros } from "../lib/useParametros";
import { semFoto } from "../lib/foto";

const semAcento = (texto: string) =>
  texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLocaleLowerCase("pt-BR");

export function Deputados() {
  const { valores, definir } = useParametros(["uf", "partido", "nome"] as const);
  const filtros = useApi<Filtros>("/api/filtros");
  const deputados = useApi<Deputado[]>("/api/deputados", { uf: valores.uf, partido: valores.partido });
  const idBusca = useId();

  const lista = useMemo(() => {
    const termo = semAcento(valores.nome.trim());
    const todos = deputados.dados ?? [];
    return termo ? todos.filter((d) => semAcento(d.nome).includes(termo)) : todos;
  }, [deputados.dados, valores.nome]);

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold text-primary">Deputados federais</h1>
        <p className="max-w-2xl text-lg text-secondary">
          Todos os deputados que exerceram mandato na legislatura atual, inclusive suplentes. Escolha um para ver
          gastos da cota e emendas.
        </p>
      </div>

      <section aria-label="Filtros" className="card grid gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor={idBusca} className="mb-1 block text-sm font-bold text-secondary">
            Nome
          </label>
          <input
            id={idBusca}
            type="search"
            className="input"
            placeholder="Ex.: Túlio"
            autoComplete="off"
            value={valores.nome}
            onChange={(e) => definir({ nome: e.target.value })}
          />
        </div>
        <CampoSelect
          rotulo="Estado"
          valor={valores.uf}
          opcoes={opcoesSimples(filtros.dados?.ufs ?? [])}
          onMudar={(uf) => definir({ uf })}
        />
        <CampoSelect
          rotulo="Partido"
          valor={valores.partido}
          opcoes={opcoesSimples(filtros.dados?.partidos ?? [])}
          onMudar={(partido) => definir({ partido })}
        />
      </section>

      {deputados.erro ? (
        <ErroApi erro={deputados.erro} onTentarDeNovo={deputados.recarregar} />
      ) : !deputados.dados ? (
        <Carregando linhas={6} />
      ) : (
        <section aria-labelledby="titulo-lista" className="space-y-3">
          <h2 id="titulo-lista" className="font-bold text-secondary" aria-live="polite">
            {formatarInteiro(lista.length)} {lista.length === 1 ? "deputado encontrado" : "deputados encontrados"}
          </h2>
          {lista.length === 0 ? (
            <Vazio>Ninguém com esse nome nos filtros escolhidos.</Vazio>
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {lista.map((d) => (
                <li key={d.id}>
                  <Link
                    to={`/deputados/${d.id}`}
                    className="card flex items-center gap-4 p-4 transition-colors duration-150 hover:border-accent sm:p-4"
                  >
                    <img
                      onError={semFoto}
                      src={d.url_foto ?? undefined}
                      alt=""
                      loading="lazy"
                      width={56}
                      height={56}
                      className="size-14 shrink-0 rounded-full bg-muted object-cover"
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-bold text-primary">{d.nome}</span>
                      <span className="block text-sm text-muted-foreground">{partidoUf(d.sigla_partido, d.sigla_uf)}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
