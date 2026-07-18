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
**Sala de comando precisa, não nave sci-fi.** Autoridade técnica, sobriedade forense, confiança. "Apple-elegante com alma Jarvis": a base é calma, precisa, arejada e tipograficamente forte; o brilho/movimento (glow teal, malha, HUD) é **acento raro e proposital** — nunca decoração constante. Premium, não espetáculo.

## Anti-references (o que NÃO ser)
- **Game UI / HUD de videogame**: glow em tudo, movimento constante, neon gratuito.
- **Glassmorphism por padrão**: blur/vidro decorativo em todo card.
- **Hero-metric SaaS**: número gigante + rótulo + gradiente, repetido.
- **Grid de cards idênticos** com ícone+título+texto ao infinito.
- **Side-stripe** (borda colorida à esquerda de card/callout).
- **Motion decorativo** que não comunica estado; sequência orquestrada de "load".
- Dashboard cinza-sobre-cinza sem hierarquia (o oposto do problema acima).

## Strategic design principles
1. **Honestidade visual** = honestidade do dado: indício ≠ acusação; INDISPONÍVEL ≠ 0. O rating (🔴🟡🟢) e a escala são sempre explícitos. A UI nunca faz um indício parecer prova.
2. **Prioridade legível em 1 relance**: o que precisa de atenção (risco alto, dinheiro em jogo) lê antes do detalhe — cor semântica, peso, posição; não um mar plano.
3. **Densidade com ar**: tabela/lista densa é bem-vinda, mas com ritmo de espaçamento e tipografia que não cansa em sessão longa.
4. **Um acento com significado**: teal = seleção/estado/ação; âmbar/rosa = severidade. Cor saturada só carrega sentido, nunca enfeite.
5. **Movimento = estado**: transição comunica mudança/feedback/reveal; o "alma Jarvis" (malha viva, glow) é um momento, não a página inteira.

## Register overrides
Nenhum. Todo o painel é product.
