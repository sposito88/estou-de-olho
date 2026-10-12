import { Check, Copy, ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { Carregando, ErroApi } from "../components/Estado";
import { useApi } from "../lib/api";
import { formatarBRL, formatarDocumento } from "../lib/format";
import type { Alerta } from "../lib/types";

const PERGUNTAS: Record<string, string> = {
  empresa_nova:
    "Como a empresa foi escolhida e se houve verificação de capacidade técnica e econômica, considerando que ela foi aberta pouco antes de receber",
  fornecedor_inativo: "Por que houve pagamento a CNPJ que consta como inativo (baixado, inapto ou suspenso) na Receita Federal",
  mei_acima_limite: "Como foi verificada a regularidade de um MEI que recebeu acima do limite anual de faturamento do MEI",
  concentracao: "Como o fornecedor foi escolhido e quais serviços ou produtos foram efetivamente entregues",
  notas_sequenciais: "Quais serviços ou produtos foram efetivamente entregues em cada nota fiscal",
  padrao_atipico: "Quais serviços ou produtos foram efetivamente entregues, com as datas de cada um",
  divulgacao_eleitoral: "Quais materiais de divulgação foram produzidos, com cópia ou foto de cada um e a data de distribuição",
  servidor_socio:
    "Se houve declaração de inexistência de conflito de interesses e como o servidor sócio da empresa se afastou da contratação",
  eleito_socio: "Se houve declaração de inexistência de conflito de interesses e qual foi o procedimento de contratação",
  doador_socio: "Qual foi o procedimento de contratação e se houve declaração de inexistência de conflito de interesses",
  contrato_capital: "Quais requisitos de capacidade técnica e econômico-financeira foram exigidos e como a empresa os comprovou",
  pix_parado:
    "Onde está o dinheiro recebido por transferência especial (extratos da conta específica desde o recebimento) e qual o cronograma de execução",
  pix_custeio:
    "Por que a transferência especial foi usada em despesa corrente, e quais empenhos e notas fiscais foram pagos com ela",
  pix_gasto_maior: "Quais despesas foram pagas com recursos de transferência especial e qual a origem de cada recurso usado",
};

function destino(a: Alerta): { orgao: string; onde: string; url: string } {
  if (a.esfera === "federal")
    return { orgao: "Câmara dos Deputados", onde: "Serviço de Informação ao Cidadão da Câmara",
             url: "https://www.camara.leg.br/transparencia/lei-de-acesso-a-informacao" };
  if (a.esfera === "senado")
    return { orgao: "Senado Federal", onde: "Serviço de Informação ao Cidadão do Senado",
             url: "https://www12.senado.leg.br/transparencia/sic" };
  if (a.esfera === "estadual")
    return { orgao: "Assembleia Legislativa de Pernambuco", onde: "SIC da ALEPE",
             url: "https://www.alepe.pe.gov.br/transparencia/" };
  const orgao = a.orgao?.nome ?? a.orgao_contratante?.nome ?? `Prefeitura de ${a.municipio?.nome ?? "seu município"}`;
  const cidade = a.orgao?.municipio ?? a.municipio?.nome ?? "";
  return {
    orgao,
    onde: `e-SIC (Serviço de Informação ao Cidadão) de ${cidade || "do município"}, no portal de transparência, ou a plataforma Fala.BR, se o município aderiu`,
    url: `https://www.google.com/search?q=${encodeURIComponent(`e-SIC ${orgao}`)}`,
  };
}

export function textoPedido(a: Alerta): string {
  const d = destino(a);
  const quem = a.deputado ? `do(a) deputado(a) federal ${a.deputado.nome}`
    : a.senador ? `do(a) senador(a) ${a.senador.nome}`
    : a.deputado_estadual ? `do(a) deputado(a) estadual ${a.deputado_estadual.nome}`
    : `do(a) ${d.orgao}`;
  const fornecedor = a.cnpj ? ` à pessoa jurídica de CNPJ ${formatarDocumento(a.cnpj)}` : "";
  const pix = a.tipo.startsWith("pix_");
  const documentos = pix
    ? "o plano de trabalho, os extratos da conta específica da transferência especial, os empenhos, as notas fiscais e os comprovantes de pagamento"
    : "as notas de empenho, de liquidação e as ordens de pagamento, as notas fiscais, o contrato e o processo de contratação (licitação, dispensa ou inexigibilidade), além dos comprovantes de entrega dos produtos ou serviços";
  return [
    `Ao(À) ${d.orgao}`,
    "",
    "Assunto: pedido de acesso à informação (Lei nº 12.527/2011)",
    "",
    `Com base na Lei de Acesso à Informação, solicito cópia de ${documentos} referentes às despesas ${quem}${fornecedor}${a.ano ? ` no exercício de ${a.ano}` : ""}${Number(a.valor) > 0 ? `, que somam ${formatarBRL(a.valor)}` : ""}.`,
    "",
    `Solicito também que seja informado: ${PERGUNTAS[a.tipo] ?? "a finalidade e a comprovação da execução dessas despesas"}.`,
    "",
    `Contexto: a partir de dados públicos oficiais, o projeto Estou de Olho registrou o seguinte padrão, que pode ter explicação legítima: "${a.titulo}". ${a.descricao}`,
    "",
    "Peço que a resposta seja enviada em formato eletrônico, no prazo do art. 11 da Lei nº 12.527/2011 (até 20 dias, prorrogáveis por mais 10, mediante justificativa).",
    "",
    "Atenciosamente,",
    "[seu nome]",
  ].join("\n");
}

export function PedirExplicacao() {
  const { id = "" } = useParams();
  const alerta = useApi<Alerta>(`/api/alertas/${encodeURIComponent(id)}`);
  const [copiado, setCopiado] = useState(false);

  if (alerta.erro) return <ErroApi erro={alerta.erro} onTentarDeNovo={alerta.recarregar} />;
  if (!alerta.dados) return <Carregando linhas={6} rotulo="Montando o pedido" />;
  const a = alerta.dados;
  const d = destino(a);
  const texto = textoPedido(a);

  return (
    <div className="max-w-3xl space-y-6">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold text-primary sm:text-4xl">Pedir explicação</h1>
        <p className="text-lg text-secondary">
          Todo cidadão pode pedir documentos e explicações a qualquer órgão público, sem precisar dizer por quê. Abaixo
          está um pedido pronto pela Lei de Acesso à Informação sobre o alerta “{a.titulo}”. Revise, coloque seu nome e
          envie.
        </p>
      </div>

      <section className="card space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold text-primary">O pedido</h2>
          <button
            type="button"
            className="btn-secondary"
            onClick={async () => {
              await navigator.clipboard.writeText(texto);
              setCopiado(true);
              setTimeout(() => setCopiado(false), 2500);
            }}
          >
            {copiado ? <Check aria-hidden className="size-5" /> : <Copy aria-hidden className="size-5" />}
            {copiado ? "Copiado" : "Copiar texto"}
          </button>
        </div>
        <textarea readOnly value={texto} rows={18} className="input min-h-96 py-2 font-mono text-sm" aria-label="Texto do pedido" />
      </section>

      <section className="card space-y-2">
        <h2 className="text-xl font-bold text-primary">Para onde mandar</h2>
        <p>
          <strong>{d.orgao}</strong>, pelo {d.onde}.
        </p>
        <a href={d.url} target="_blank" rel="noopener noreferrer" className="link inline-flex min-h-11 items-center gap-1">
          Abrir o canal de pedidos <ExternalLink aria-hidden className="size-4" />
        </a>
        <ul className="list-disc space-y-1 pl-6 text-sm text-secondary">
          <li>Guarde o número do protocolo. O prazo é de 20 dias, prorrogáveis por mais 10.</li>
          <li>Sem resposta, ou com resposta incompleta, você pode recorrer à autoridade superior em até 10 dias.</li>
          <li>Se a resposta mostrar algo errado aqui no site, conte para nós em <Link to="/contestar" className="link">Contestar ou corrigir</Link>.</li>
        </ul>
      </section>
    </div>
  );
}
