import { Link } from "react-router";

export function Privacidade() {
  return (
    <article className="prose-texto max-w-3xl space-y-5">
      <h1 className="text-3xl font-bold text-primary sm:text-4xl">Privacidade e dados pessoais</h1>
      <p className="text-lg text-secondary">
        O Estou de Olho é um projeto cidadão, aberto e sem fins lucrativos, para acompanhar o uso do dinheiro público.
        Aqui está como tratamos dados pessoais, seguindo a Lei Geral de Proteção de Dados (Lei 13.709/2018).
      </p>

      <section className="space-y-2">
        <h2 className="text-xl font-bold text-primary">Que dados pessoais aparecem aqui</h2>
        <ul className="list-disc space-y-1 pl-6">
          <li>Agentes públicos: parlamentares, prefeitos, vereadores e servidores (nome, cargo, vínculo, órgão).</li>
          <li>Fornecedores pessoa física pagos com dinheiro público (nome e valores).</li>
          <li>Sócios de empresas que receberam dinheiro público (nome e qualificação, como publicado pela Receita).</li>
          <li>Candidatos e doadores de campanha (como publicado pelo TSE).</li>
        </ul>
        <p>
          Todos já são publicados pelas fontes oficiais (Câmara, Senado, Receita Federal, TSE, tribunais de contas,
          Portal da Transparência, PNCP). Não coletamos nada de fontes privadas nem de redes sociais.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-bold text-primary">Para quê e com que base</h2>
        <p>
          A finalidade é o controle social dos gastos públicos, de interesse público. Usamos dados pessoais de acesso
          público, respeitando a finalidade e o interesse público que justificaram a sua divulgação (art. 7º, §§ 3º e
          4º, da LGPD), e a Lei de Acesso à Informação (Lei 12.527/2011).
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-bold text-primary">O que fazemos para proteger as pessoas</h2>
        <ul className="list-disc space-y-1 pl-6">
          <li>
            <strong>CPF nunca aparece completo.</strong> Mostramos só os dígitos que as próprias fontes divulgam
            (ex.: ***.123.456-**) e não guardamos o CPF completo de doadores nem de fornecedores.
          </li>
          <li>
            <strong>Páginas de busca e de pessoal não são indexadas</strong> pelo Google e outros buscadores, para que
            o nome de uma pessoa comum não vire resultado de pesquisa por causa deste site.
          </li>
          <li>
            <strong>Alerta não é acusação.</strong> Os sinais de alerta são padrões calculados automaticamente; muitos
            têm explicação legítima. Quando a ligação entre dois registros é só pelo nome, avisamos que pode ser homônimo.
          </li>
          <li>
            <strong>Sem rastreamento.</strong> O site não usa cookies, nem ferramentas de publicidade ou de análise de
            visitantes. No formulário de contestação, o IP não é guardado (só um resumo que muda todo dia, para evitar
            abuso).
          </li>
        </ul>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-bold text-primary">Seus direitos</h2>
        <p>
          Você pode pedir confirmação, correção, explicação sobre o tratamento dos seus dados ou revisão de um alerta
          (art. 18 da LGPD), e pessoas e empresas citadas podem publicar sua resposta. Use o{" "}
          <Link to="/contestar?url=/privacidade" className="link">formulário de contestação</Link>, escolhendo “Pedido
          sobre meus dados pessoais”. Seu nome e contato nunca são publicados. As decisões ficam registradas em{" "}
          <Link to="/correcoes" className="link">Correções</Link>.
        </p>
        <p>
          Dados que estão errados na fonte oficial (por exemplo, no tribunal de contas ou na Receita) precisam ser
          corrigidos lá também; ajudamos indicando onde.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-bold text-primary">Código e dados abertos</h2>
        <p>
          O código do projeto é aberto, e os dados consolidados podem ser baixados em{" "}
          <Link to="/dados-abertos" className="link">Dados abertos</Link>, sempre com o CPF mascarado.
        </p>
      </section>
    </article>
  );
}
