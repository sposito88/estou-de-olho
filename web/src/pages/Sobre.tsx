import { LINKS_EXTERNOS } from "../lib/config";

export function Sobre() {
  return (
    <article className="card mx-auto max-w-3xl space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold text-primary">Sobre os dados</h1>
        <p className="text-lg text-secondary">
          Tudo aqui vem de dados abertos oficiais: Câmara, Senado, Portal da Transparência, PNCP, Tesouro Nacional,
          TSE, Receita Federal, IBGE, ALEPE, TCE-PE, TCE-SP e TCE-PB. Nada é estimado: os números são somas dos registros publicados.
        </p>
      </header>

      <section className="space-y-2">
        <h2 className="text-xl font-bold text-primary">Cota parlamentar (CEAP)</h2>
        <p>
          É o dinheiro que a Câmara reembolsa a cada deputado por gastos do mandato: passagens, combustível,
          aluguel de escritório, divulgação, telefone etc. Vem da{" "}
          <a className="link" href={LINKS_EXTERNOS.dadosCamara} target="_blank" rel="noreferrer noopener">
            API de Dados Abertos da Câmara
          </a>{" "}
          e dos{" "}
          <a className="link" href={LINKS_EXTERNOS.cotaCamara} target="_blank" rel="noreferrer noopener">
            arquivos anuais da cota
          </a>
          .
        </p>
        <p>
          Todos os totais usam o <strong>valor reembolsado</strong> (valor líquido), não o valor da nota. A diferença
          é a <strong>glosa</strong>: a parte que a Câmara recusou pagar.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-bold text-primary">Emendas parlamentares</h2>
        <p>
          Parte do orçamento federal que deputados, senadores, bancadas estaduais e comissões indicam para um
          destino. Vem do{" "}
          <a className="link" href={LINKS_EXTERNOS.portalTransparencia} target="_blank" rel="noreferrer noopener">
            Portal da Transparência
          </a>
          . A página da cidade usa os <strong>pagamentos por favorecido</strong>, que dizem em qual município o
          dinheiro chegou de fato.
        </p>
        <ul className="list-disc space-y-1 pl-6">
          <li>
            <strong>Empenhado</strong>: valor reservado no orçamento. <strong>Pago</strong>: valor que saiu do
            caixa, incluindo restos a pagar de anos anteriores.
          </li>
          <li>
            O Portal não usa o mesmo código de deputado da Câmara. O vínculo é feito pelo nome parlamentar; autores
            sem correspondência aparecem como bancada, comissão, senador ou ex-deputado.
          </li>
        </ul>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-bold text-primary">Todos os municípios do Brasil</h2>
        <ul className="list-disc space-y-1 pl-6">
          <li>
            <strong>Contratos:</strong> Portal Nacional de Contratações Públicas (PNCP), onde todo órgão público é
            obrigado a publicar seus contratos desde a Lei 14.133/2021. Municípios pequenos ainda publicam pouco.
          </li>
          <li>
            <strong>Contas:</strong> declaração de contas anual (DCA) dos municípios ao Tesouro Nacional (Siconfi),
            com a despesa por área.
          </li>
          <li>
            <strong>Eleitos:</strong> candidaturas e bens declarados ao TSE. O TSE não publica mais o CPF dos
            candidatos, então cruzamentos com sócios de empresas são feitos pelo nome e podem ser homônimos.
          </li>
          <li>
            <strong>Senadores:</strong> cota para o exercício da atividade parlamentar (CEAPS), publicada pelo Senado.
          </li>
        </ul>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-bold text-primary">Deputados estaduais, prefeitura e vereadores (Pernambuco)</h2>
        <p>
          A <strong>verba indenizatória</strong> dos deputados estaduais (até R$ 60 mil por mês) vem do portal de
          transparência da Assembleia Legislativa de Pernambuco (ALEPE), nota por nota, com a empresa que recebeu.
        </p>
        <p>
          As contas da <strong>prefeitura e da câmara de vereadores</strong> vêm da API de dados abertos do Tribunal
          de Contas de Pernambuco (TCE-PE): cada empenho, com credor, valor empenhado e pago e o histórico. A lista de
          vereadores e de pessoal nomeado vem da base Sagres Pessoal do mesmo tribunal.
        </p>
        <p>
          Na <strong>Paraíba</strong>, o Tribunal de Contas do Estado (TCE-PB) publica a folha de pessoal de todos os
          municípios com o <strong>valor recebido por cada servidor em cada mês</strong>. Mostramos o valor do mês mais
          recente, o total do ano e a folha somada por tipo de vínculo, inclusive o subsídio dos vereadores.
        </p>
        <p>
          Nos <strong>municípios de São Paulo</strong> (todos, menos a capital, que presta contas ao TCM-SP) as
          despesas vêm da API de transparência do Tribunal de Contas do Estado de São Paulo (TCE-SP). Ela publica cada
          fase de cada empenho, mas sem histórico, área ou tipo de despesa; guardamos a soma por órgão e credor em cada
          ano (empenhado, liquidado, pago e quantos empenhos). A lista de pessoal não faz parte dessa base.
        </p>
        <p>
          O que cada vereador recebeu "em seu nome" (diárias, indenizações) é identificado pelo nome do credor. O{" "}
          <strong>salário individual dos vereadores não está nos dados abertos</strong>: o TCE-PE só publica o total
          da folha, e o portal da Câmara de Carpina bloqueia acesso automatizado.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-bold text-primary">Empresas e cidades</h2>
        <p>
          Os dados de cada empresa (data de abertura, situação, se é MEI, cidade da sede) vêm da{" "}
          <strong>base aberta de CNPJ da Receita Federal</strong>, atualizada todo mês. População e cidades vizinhas
          (mesma "região imediata") vêm do <strong>IBGE</strong>.
        </p>
        <p>
          A <strong>emenda Pix</strong> (transferência especial) vai direto para o caixa da prefeitura, sem projeto
          definido antes; por isso é a mais difícil de rastrear.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-bold text-primary">Sinais de alerta</h2>
        <p>
          São regras automáticas que destacam padrões incomuns: empresa aberta pouco antes de receber, fornecedor que
          vive de um só deputado, notas com numeração seguida, CNPJ baixado emitindo nota, MEI recebendo acima do
          limite anual, divulgação que dispara em ano de eleição, excesso de notas em fim de semana ou com valor
          redondo, servidor que é sócio de fornecedor do próprio órgão (nome e 6 dígitos do CPF iguais) e eleito
          com o mesmo nome de sócio de empresa contratada no município. <strong>Alerta não é prova de
          irregularidade</strong>: é um convite para olhar o documento.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-bold text-primary">Limitações conhecidas</h2>
        <ul className="list-disc space-y-1 pl-6">
          <li>O partido exibido é o atual. Gastos anteriores a uma troca de partido aparecem no partido novo.</li>
          <li>Despesas sem documento fiscal ficam sem CNPJ/CPF e sem link para a nota.</li>
          <li>
            Os dados do ano corrente mudam depois de publicados (glosas e lançamentos atrasados). Por isso esse ano é
            sempre coletado de novo.
          </li>
          <li>
            O vínculo entre autor da emenda e deputado é feito pelo nome (na legislatura atual) e depois pelo código do
            autor no Portal da Transparência. Homônimos podem ficar sem vínculo.
          </li>
          <li>
            A cidade de cada empresa é a da sede no cadastro atual da Receita; uma empresa que mudou de endereço aparece
            na cidade nova.
          </li>
          <li>Salário e verba de gabinete dos deputados federais ainda não estão aqui.</li>
          <li>
            A lista de pessoal do TCE-PE não informa desligamentos: "nomeados no mandato" pode incluir quem já saiu.
          </li>
        </ul>
      </section>
    </article>
  );
}
