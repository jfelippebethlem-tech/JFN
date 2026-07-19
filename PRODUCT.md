# PRODUCT.md — JFN

## Register
**product** — o design SERVE a tarefa. É uma central de inteligência/fiscalização de gasto público (dashboard denso, tabelas, listas de indícios, dossiês). Não é marketing; a ferramenta deve desaparecer na tarefa.

## Platform
web (SPA estática servida por FastAPI; entry `static/jfn-painel.html`, rota `/painel`).

## Target users
Equipe de **controle externo** de um Deputado Estadual do RJ (assessoria técnica de fiscalização) e o próprio parlamentar. Usuários fluentes em dado público (SIAFE, PNCP, CEIS/CNEP), lendo indícios de fraude/sobrepreço/conluio para priorizar apuração. Uso frequente, sessões longas, muitas vezes noturnas.

## Purpose
Transformar dado bruto de contratação/pagamento em **fila priorizada de apuração**: quem olhar primeiro, por quê, e com quanto dinheiro em risco. Cada tela é um recorte de risco (radar, conluio, capital irrisório, prioridade por valor, perícias, comparador de preços).

## Positioning
A régua é **Linear / Raycast / Stripe**: um usuário fluente nas melhores ferramentas de dado deve sentar e **confiar** na interface na hora — nada de componente sutilmente errado, nada de "game UI". Densidade quando o usuário precisa; calma e precisão sempre.

## Brand personality
**Organismo vivo: Jarvis × lightsaber × Apple Glass** (brief do dono, 2026-07-19 — SUPERSEDE "sala de comando sóbria").
A interface é um organismo de energia: informação REAL fluindo visivelmente (lâmina SSE, malha de luz, plexus),
vidro líquido (visionOS: highlight especular + sombra + iluminação), cores vivas com significado, e CADA elemento
interativo vivo — respondendo ao cursor, mudando de cor, com estado luminoso. Elegância premium continua obrigatória:
vivo ≠ poluído; o dado sempre lê primeiro, a luz o serve.

## Anti-references (o que NÃO ser)
- **Dado sintético**: nenhuma animação de número/gráfico inventado (Math.random em série "de dados" é proibido). Vida = evento/dado REAL.
- **Ruído que esconde o dado**: glow/partícula nunca por cima de texto denso; camadas ambientes ficam ATRÁS e discretas.
- **Motion que trava**: canvas com cap de partículas, RAF pausado em document.hidden, transform/opacity only.
- **Ignorar acessibilidade**: prefers-reduced-motion desliga TUDO que se move; contraste de texto ≥4.5:1 sempre.
- Dashboard cinza-sobre-cinza sem alma (o v6 "Lâmina" — regressão declarada pelo dono).

## Strategic design principles
1. **Honestidade visual** = honestidade do dado: indício ≠ acusação; INDISPONÍVEL ≠ 0. O rating (🔴🟡🟢) e a escala são sempre explícitos. A UI nunca faz um indício parecer prova.
2. **Prioridade legível em 1 relance**: o que precisa de atenção (risco alto, dinheiro em jogo) lê antes do detalhe — cor semântica, peso, posição; não um mar plano.
3. **Densidade com ar**: tabela/lista densa é bem-vinda, mas com ritmo de espaçamento e tipografia que não cansa em sessão longa.
4. **Um acento com significado**: teal = seleção/estado/ação; âmbar/rosa = severidade. Cor saturada só carrega sentido, nunca enfeite.
5. **Movimento = estado**: transição comunica mudança/feedback/reveal; o "alma Jarvis" (malha viva, glow) é um momento, não a página inteira.

## Register overrides
Nenhum. Todo o painel é product.
