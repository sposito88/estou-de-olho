import { FileText, Search } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { useApi } from "../lib/api";
import { capitalizar, formatarBRL, formatarData, formatarDocumento, formatarInteiro, paraNumero, plural } from "../lib/format";
import type { Pagina, Reais } from "../lib/types";
import { CampoSelect } from "./Campos";
import { Carregando, ErroApi, Vazio } from "./Estado";
import { ListaBarras } from "./ListaBarras";
import { Paginacao } from "./Paginacao";
import { Secao } from "./Secao";

interface ResumoTce {
  ano: number | null;
  anos: number[];
  total: Reais;
  qtd: number;
  total_sem_disputa: Reais;
  por_tipo_processo: { nome: string; qtd: number; total: Reais }[];
  fornecedores: { nome: string; cpf_cnpj: string | null; tipo_pessoa: "PF" | "PJ" | null; total: Reais; qtd: number }[];
}

interface ContratoTce {
  id: number;
  orgao: string;
  ano: number;
  numero: string | null;
  tipo_processo: string | null;
  objeto: string | null;
  fornecedor: string | null;
  cpf_cnpj: string | null;
  tipo_pessoa: "PF" | "PJ" | null;
  valor: Reais;
  vigencia_inicio: string | null;
  vigencia_fim: string | null;
  url_documento: string | null;
}

const POR_PAGINA = 15;

/** Contratos informados ao tribunal de contas (TCE-PE/LICON), cada um com o PDF. Some se não houver. */
export function ContratosTribunal({ base, ano }: { base: string; ano: string }) {
  const resumo = useApi<ResumoTce>(`${base}/contratos-tce`, { ano });
  const [texto, setTexto] = useState("");
  const [busca, setBusca] = useState("");
  const [tipo, setTipo] = useState("");
  const [pagina, setPagina] = useState(1);
  const id = useId();
  useEffect(() => {
    const espera = setTimeout(() => {
      setBusca(texto.trim());
      setPagina(1);
    }, 400);
    return () => clearTimeout(espera);
  }, [texto]);
  const lista = useApi<Pagina<ContratoTce>>(resumo.dados ? `${base}/contratos-tce/lista` : null, {
    ano, busca, tipo_processo: tipo, limit: POR_PAGINA, offset: (pagina - 1) * POR_PAGINA,
  });

  if (resumo.erro?.status === 404 || (!resumo.dados && !resumo.erro)) return null;
  if (resumo.erro) return <ErroApi erro={resumo.erro} onTentarDeNovo={resumo.recarregar} />;
  const r = resumo.dados!;
  const pctSemDisputa = paraNumero(r.total) ? Math.round((paraNumero(r.total_sem_disputa) / paraNumero(r.total)) * 100) : 0;

  return (
    <Secao
      id="contratos-tribunal"
      titulo="Contratos informados ao tribunal de contas"
      descricao={`${formatarInteiro(r.qtd)} contratos, ${formatarBRL(r.total)}${ano ? ` em ${ano}` : " em todos os anos"}. Cada um tem o documento (PDF) enviado ao TCE-PE.`}
    >
      <div className="space-y-6">
        {pctSemDisputa > 0 && (
          <p className="rounded-lg bg-muted px-4 py-3 text-secondary">
            <strong>{pctSemDisputa}%</strong> do valor ({formatarBRL(r.total_sem_disputa)}) foi contratado por
            dispensa ou inexigibilidade, sem disputa entre empresas. É permitido em vários casos, mas merece atenção.
          </p>
        )}
        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <h3 className="mb-3 font-bold text-secondary">Maiores fornecedores</h3>
            <ListaBarras
              rotuloLista="Maiores fornecedores por contratos"
              itens={r.fornecedores.map((f) => ({
                chave: `${f.cpf_cnpj}-${f.nome}`,
                rotulo: capitalizar(f.nome),
                rotuloTexto: capitalizar(f.nome),
                detalhe: `${formatarDocumento(f.cpf_cnpj)} · ${plural(f.qtd, "contrato", "contratos")}`,
                valor: f.total,
                href: f.tipo_pessoa === "PJ" && f.cpf_cnpj ? `/fornecedores/${f.cpf_cnpj}` : undefined,
              }))}
            />
          </div>
          <div>
            <h3 className="mb-3 font-bold text-secondary">Como foram contratados</h3>
            <ListaBarras
              numerada={false}
              rotuloLista="Valor por modalidade"
              itens={r.por_tipo_processo.map((t) => ({
                chave: t.nome, rotulo: t.nome, rotuloTexto: t.nome, detalhe: plural(t.qtd, "contrato", "contratos"),
                valor: t.total,
              }))}
            />
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
          <div>
            <label htmlFor={id} className="mb-1 block text-sm font-bold text-secondary">Buscar contrato</label>
            <div className="relative">
              <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" />
              <input id={id} type="search" className="input pl-10" placeholder="Objeto, empresa ou CNPJ" autoComplete="off"
                     value={texto} onChange={(e) => setTexto(e.target.value)} />
            </div>
          </div>
          <CampoSelect rotulo="Modalidade" valor={tipo} opcoes={r.por_tipo_processo.map((t) => ({ valor: t.nome, rotulo: t.nome }))}
                       onMudar={(v) => { setTipo(v); setPagina(1); }} />
        </div>
        {lista.erro ? (
          <ErroApi erro={lista.erro} onTentarDeNovo={lista.recarregar} />
        ) : !lista.dados ? (
          <Carregando linhas={5} rotulo="Carregando contratos" />
        ) : lista.dados.total === 0 ? (
          <Vazio>Nenhum contrato com esses filtros.</Vazio>
        ) : (
          <>
            <ul className="divide-y divide-border">
              {lista.dados.itens.map((c) => (
                <li key={c.id} className="py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                    <p className="font-bold text-primary">
                      {c.tipo_pessoa === "PJ" && c.cpf_cnpj ? (
                        <Link to={`/fornecedores/${c.cpf_cnpj}`} className="link">{capitalizar(c.fornecedor)}</Link>
                      ) : capitalizar(c.fornecedor)}
                    </p>
                    <p className="numero font-bold">{formatarBRL(c.valor)}</p>
                  </div>
                  <p className="text-secondary">{capitalizar(c.objeto)}</p>
                  <p className="text-sm text-muted-foreground">
                    Contrato {c.numero}/{c.ano} · {c.tipo_processo ?? "modalidade não informada"} · {c.orgao}
                    {c.vigencia_inicio && ` · vigência ${formatarData(c.vigencia_inicio)} a ${formatarData(c.vigencia_fim)}`}
                    {" · "}{formatarDocumento(c.cpf_cnpj)}
                  </p>
                  {c.url_documento && (
                    <a href={c.url_documento} target="_blank" rel="noopener noreferrer"
                       className="link mt-1 inline-flex min-h-11 items-center gap-1 text-sm">
                      <FileText aria-hidden className="size-4" /> Ver o contrato (PDF no TCE-PE)
                    </a>
                  )}
                </li>
              ))}
            </ul>
            <Paginacao rotulo="Páginas de contratos do tribunal" pagina={pagina} porPagina={POR_PAGINA}
                       total={lista.dados.total} onMudar={setPagina} />
          </>
        )}
      </div>
    </Secao>
  );
}
