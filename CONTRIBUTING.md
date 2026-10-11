# Como contribuir

Obrigado por querer ajudar! O Estou de Olho é um projeto cidadão, aberto e sem fins lucrativos.
Toda contribuição conta: código, dados novos, correção de texto, revisão de alertas, testes.

## Rodar na sua máquina (sem baixar nada das fontes)

Precisa de Python 3.10+ e Node 22+.

```bash
make instalar   # cria .venv e instala Python + front
make dev        # gera data/demo.db com dados FICTÍCIOS
make api        # terminal 1: API em http://localhost:8000 (documentação em /docs)
make web        # terminal 2: site em http://localhost:5173
```

Abra <http://localhost:5173/cidade/PE/Vila%20Exemplo>. Para usar dados reais, veja a seção
"Ordem de execução" do README (as coletas completas baixam dezenas de GB e levam horas).

## Antes de abrir um pull request

```bash
make verificar  # testes do Python + tipos e build do front (o mesmo que o CI roda)
```

- Toda regra nova de coleta ou de alerta precisa de teste em `tests/` com dados de exemplo.
- Escreva em português claro, para quem não é técnico: o público do site é o cidadão.
- Siga o estilo do código ao redor (nomes em português, dinheiro sempre em centavos inteiros).

## Regras que não mudam

1. **Só dados oficiais e públicos.** Nada de fontes privadas, redes sociais ou dados vazados.
2. **Não contornar bloqueios.** Se um portal tem proteção anti-robô (captcha, Cloudflare), não automatize:
   peça ao órgão um acesso aberto ou use outra fonte oficial.
3. **Privacidade (LGPD).** CPF nunca completo; páginas com nomes de pessoas comuns não são indexadas;
   veja `/privacidade` no site.
4. **Alerta não é acusação.** Todo sinal de alerta precisa dizer de onde veio, como foi calculado e que pode
   ter explicação legítima. Quando a ligação é só pelo nome, avise que pode ser homônimo.
5. **Direito de resposta.** Contestações chegam pelo site (`/contestar`) e são respondidas em público
   (`/correcoes`).

## Ideias de contribuição

- Adaptar um novo tribunal de contas estadual (veja `civic/tce_sp.py` como modelo).
- Melhorar ou revisar uma regra de alerta (`civic/alertas.py`), reduzindo falsos positivos.
- Acessibilidade e textos do front (`web/src`).
- Verificar alertas da sua cidade e contar o que encontrou numa issue.

## Segurança

Achou uma falha de segurança? Não abra issue pública: veja [SECURITY.md](SECURITY.md).
