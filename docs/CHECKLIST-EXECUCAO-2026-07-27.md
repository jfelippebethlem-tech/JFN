# Checklist de Execução — Refino, Responsabilização e Economia
## JFN · Lex · Yoda · Hermes

| | |
|---|---|
| **Emissão** | 27 de julho de 2026 |
| **Origem** | Instrução do titular: enxugar custo de token sem perder qualidade; extrair responsáveis (gestores, fiscais, ordenadores) dos processos SEI; refinar granularidade, precisão, análise e insight; criar funções novas nos quatro sistemas |
| **Estado** | Blocos A e B (parcial) **executados**; C a G **especificados e pendentes de autorização** |
| **Regra de ouro** | Indício ≠ acusação · LACUNA ≠ INEXISTÊNCIA · nada de número inventado · CPF mascarado |

---

## Como ler este documento

Cada item tem **estado** (✅ feito · 🟡 em curso · ⬜ pendente), **critério verificável** de conclusão
e **custo estimado**. Nenhum item pendente foi iniciado — a decisão de escopo é do titular.

---

## Bloco A — Custo de token *(o que gastava à toa)*

| # | Item | Estado | Critério de conclusão |
|---|---|---|---|
| A1 | Auditar o que entra no contexto a cada turno e medir cada fonte | ✅ | Medição por arquivo abaixo |
| A2 | Desligar as 7 skills Higgsfield do escopo JFN | ✅ | `JFN/.claude/skills/` só tem `gitnexus` e `impeccable` |
| A3 | Desligar os conectores MCP (Adobe, Higgsfield e os outros 30) | ⬜ **depende do titular** | Só se desliga na conta claude.ai — ver A3 abaixo |
| A4 | Revisar peso do `MEMORY.md` (3.952 tok/turno, o maior item local) | ⬜ | Índice ≤ 2.500 tok sem perder rastreabilidade |
| A5 | Revisar os ~45 comandos `obsidian-*` na lista de skills | ⬜ **decisão do titular** | É o segundo cérebro; não corto sem ordem |

### A1 — Medição do que é injetado por turno

| Fonte | Peso | Controlável aqui? |
|---|---:|---|
| `MEMORY.md` (índice de memória) | ~3.952 tok | Sim — item A4 |
| `JFN/CLAUDE.md` | ~1.931 tok | Sim, mas é a espinha operacional |
| **Skills Higgsfield no JFN** | **~1.701 tok** | ✅ **cortado** |
| `.claude/CLAUDE.md` global | ~1.343 tok | Sim, mas são as regras permanentes |
| Descrições das skills globais | ~2.025 tok | Parcial |
| `AGENTS.md` | ~644 tok | Sim |
| Hook `session_digest.sh` | ~674 tok | Sim |
| **Conectores MCP claude.ai** (~300 nomes de ferramenta + 3 schemas Adobe carregados de imediato + instruções do Higgsfield) | **~6.000–7.000 tok (estimativa)** | ❌ **Não** — ver A3 |

**Corte já realizado: ~1.700 tokens por turno**, sem perder nada — as skills Higgsfield eram
*symlinks*; o conteúdo continua íntegro em `JFN/.agents/skills/` e os links foram preservados em
`JFN/.claude/skills-desligadas/`. Para religar: `mv .claude/skills-desligadas/higgsfield-* .claude/skills/`.

### A3 — Por que não consigo desinstalar Adobe e Higgsfield daqui

Os MCPs que aparecem como `claude.ai Adobe for creativity`, `claude.ai higgsfield`, `claude.ai
Bigdata.com` etc. **não estão instalados nesta máquina**. `~/.claude.json` tem exatamente **um**
servidor local: `gitnexus`. Os demais são **conectores da conta claude.ai** — `claude mcp remove`
responde *"No MCP server named …"* porque não há o que remover localmente.

> **Ação necessária do titular (2 min):** claude.ai → **Settings → Connectors** → desconectar
> Adobe for creativity, higgsfield e todos os que não usa (Bigdata, Bitly, CB Insights, CoinDesk,
> Daloopa, Docusign, FMP, FactSet, G2, IBISWorld, Interactive Brokers, Kpler, MT Newswires,
> Moody's, Morningstar, Plaid, PlayMCP, Postman, Quartr, S&P Global, Similarweb, Tripadvisor,
> Vercel, Windsor.ai, iManage, tldraw…). Alternativamente, `/mcp` no CLI abre o menu de conectores.
>
> **Sugestão de o que manter:** Google Drive e Gmail se usar; **gitnexus** (local, é a inteligência
> de código do JFN). Todo o resto é peso morto para fiscalização.

Esse é, de longe, o maior gasto à toa — e é o único que não está na minha mão.

---

## Bloco B — Quem responde por cada processo *(o pedido central)*

| # | Item | Estado | Critério |
|---|---|---|---|
| B1 | Módulo de extração de agentes públicos do texto SEI | ✅ | `compliance_agent/sei/agentes_publicos.py` · 29 testes |
| B2 | Validação contra o acervo real (não contra a doc) | ✅ | Varredura de 120 processos / 1.796 documentos |
| B3 | Verificação "fiscal não designado" (art. 117, Lei 14.133) | ✅ | `montar_ficha().lacunas` |
| B4 | Verificação "segregação de funções" (art. 5º, Lei 14.133) | ✅ | `montar_ficha().alertas` |
| B5 | Persistir agentes em tabela e varrer os 2.055 processos | ⬜ | Tabela `sei_agente` + sweep off-hours |
| B6 | Elevar a cobertura de 8% para ≥30% dos processos | ⬜ | Ver B6 abaixo |
| B7 | Cruzar agente × fornecedor × achado (rede de responsabilidade) | ⬜ | Ver Bloco D |

### O que B1 entrega

Papéis reconhecidos: ordenador de despesas (e substituto), gestor do contrato, fiscal do contrato /
técnico / administrativo / substituto, pregoeiro, agente de contratação, membro de comissão de
licitação e de fiscalização, autoridade homologadora, parecerista jurídico.

Três formas de identificação, todas colhidas do acervo real:

1. **Bloco de assinatura** — `NOME` / cargo / papel, uma linha cada. É o padrão dominante em ato de
   homologação, despacho e publicação no D.O.
2. **Rótulo inline** — `Fiscal: André Luiz Gama Filho`, `Fiscal Técnico: …`, `Gestor do Contrato-…`.
3. **Designação formal** — `Designar o servidor Rodolfo da Rocha Varize, Chefe de Serviço, ID
   funcional nº 5143197-1`. O **ID funcional** é a identificação forte e vence na deduplicação;
   nome se repete, matrícula não.

### B2 — O que a validação no acervo real mostrou

Varredura de 120 processos sorteados (semente fixa), 1.796 documentos:

| Métrica | Valor |
|---|---:|
| Agentes extraídos | 18 |
| Processos com ao menos um agente | 8% |
| Falsos positivos após correção | **0** na inspeção manual dos 18 |

**Precisão veio de erros medidos, não de suposição.** A primeira passada extraiu 22 agentes, dos
quais **3 eram lixo**: `Aquisição de Motos Aquáticas\nAnexos` e `Substituto\nResolução SEGOV`
(a regex de nome usava `\s+` e **atravessava a quebra de linha**, colando pedaços de duas frases)
e `Maj PM De` (posto militar no lugar do nome). Corrigido: separador `[ \t]+`, exigência de duas
palavras com 3+ letras e vocabulário de exclusão. Os três casos viraram teste de regressão.

Armadilhas do acervo já barradas, todas reais: `Fiscal - NF 313028` e `Nota Fiscal` (documento
fiscal), `Fiscal - IBS/CBS` (reforma tributária), `FISCAL - Relator: Conselheiro …` (é do TCE-RJ,
não do órgão), `Fiscal – Empresa DIAGNÓSTICA …` (o fiscalizado, não o fiscal).

### B6 — Por que a cobertura é 8% e como subir

Honestidade sobre o número: **8% é cobertura, não precisão**. O que já se sabe da causa:

- boa parte dos textos veio de **OCR de PDF escaneado** e o bloco de assinatura chega desmontado
  (letras isoladas, linhas quebradas no meio da palavra);
- muitos processos capturados **não contêm** o ato de designação — o documento existe no SEI e não
  foi trazido, ou vive no processo-pai;
- publicações do D.O. usam `DESIGNO para compor a Comissão …` **sem listar nomes no mesmo trecho**.

Plano: (a) casar o extrator com o classificador de fase — em documento `fiscal_designacao` vale
gastar OCR melhor; (b) buscar o ato de designação no processo-pai; (c) reconstruir o bloco de
assinatura tolerando OCR sujo. Cada uma é medida antes e depois, na mesma amostra de 120.

---

## Bloco C — Granularidade e precisão do dado *(pendente)*

| # | Item | Critério | Custo |
|---|---|---|---|
| C1 | Ligar agente ↔ contrato ↔ OB ↔ achado num só grafo | Consulta "quem autorizou esta OB" responde em 1 salto | Médio |
| C2 | Datar cada papel (designação, substituição, exoneração) | Achado atribuído a **quem estava no cargo na data do ato**, não ao atual | Médio |
| C3 | Desambiguar homônimos por ID funcional | Duas pessoas de mesmo nome não viram uma | Baixo |
| C4 | Registrar a **cadeia decisória** por processo: quem pediu → quem autorizou → quem homologou → quem fiscalizou → quem liquidou | Linha do tempo de responsabilidade no dossiê | Médio |
| C5 | Marcar a confiança de cada extração (assinatura > designação > rótulo) | Todo agente sai com grau de certeza explícito | Baixo |

> **C2 é o item que mais muda a qualidade da peça.** Imputar a um ordenador ato praticado antes de
> sua posse é o erro que derruba uma representação inteira. Hoje não temos data de vigência de papel.

---

## Bloco D — Análise e insight *(pendente)*

| # | Função nova | O que revela |
|---|---|---|
| D1 | `concentracao_por_ordenador` | Ordenador que concentra dispensas/inexigibilidades acima da mediana do órgão |
| D2 | `fiscal_recorrente_por_fornecedor` | Mesmo fiscal atestando execução do mesmo fornecedor em N contratos — não é ilícito, é **onde olhar** |
| D3 | `rede_agente_fornecedor` | Grafo agente × fornecedor; componente denso = núcleo a auditar |
| D4 | `ausencia_de_designacao` (em lote) | Contratos com execução e sem fiscal designado, ranqueados por valor pago |
| D5 | `rodizio_de_fiscal_em_medicao_flagueada` | Troca de fiscal imediatamente antes de medição com red flag |
| D6 | `agente_x_sancao` | Cruzar nome/CPF de agente com CEIS/CNEP/CEAF/CNCIAI e com o QSA dos fornecedores do próprio órgão |
| D7 | `cadeia_completa_em_1_pagina` | Da requisição à OB, com nome e papel em cada elo |

> **D6 é o de maior peso e o de maior risco.** Cruzar agente público com quadro societário de
> fornecedor toca dado pessoal e exige rigor: só CPF validado, sempre mascarado no relatório,
> sempre como indício a confirmar. Não implemento sem ordem expressa.

---

## Bloco E — Lex *(pendente)*

| # | Item | Estado | Critério |
|---|---|---|---|
| E1 | **Gate de citação** ligado em `lex_render.parecer_md` | ✅ | `reporting/gate_citacoes` · 13 testes |
| E2 | Trocar as citações defeituosas da base curada | ✅ | `verificar_citacao` sobre `jurisprudencia.py`: **0** impossíveis, **0** colegiado errado |

### E1 — como o gate ficou

Ponto único: `lex_render.parecer_md`, por onde passa markdown **e** PDF. Comportamento por estado:

| Estado | Ação | Razão |
|---|---|---|
| `numero_impossivel` | citação **suprimida** do texto | não existe |
| `colegiado_diverge` | colegiado **corrigido** | o acórdão existe; conserta-se, não se descarta |
| `nao_confirmado` | mantida + **declarada** na nota ao pé | dúvida legítima; lacuna ≠ inexistência |
| `fora_do_escopo` | intocada | TCE-RJ/TCM não são cobertos por este índice |
| `indice_ausente` | nada é alterado e a peça **declara que não conferiu** | nunca fingir conferência |

Não levanta exceção (ao contrário de `garantir_neutro`): derrubar a geração de um parecer no
meio de um sweep noturno por causa de uma *dúvida* seria pior que o problema. Existe o modo
`estrito=True` para quem quiser falhar alto. Toda supressão vai para o log com o teto medido.

Ao pé de cada peça passa a constar quantas citações foram conferidas contra o acervo oficial,
quantas foram suprimidas e quais precisam de conferência na fonte.

### E2 — o que foi trocado

Cada substituto foi **buscado no acervo oficial** e sua ementa foi reescrita para dizer o que o
acórdão real decidiu — não se herda a tese de uma citação inventada.

| Antes (inexistente) | Depois (conferido) | Observação |
|---|---|---|
| 4.021/2022-Plenário | **645/2007-Plenário** | Emergência nascida de falta de planejamento não autoriza dispensa |
| 5.782/2023-Plenário | **585/2023-Plenário** | Eficácia condicionada ao PNCP é **lei** (art. 94), não jurisprudência — corrigido no texto |
| 6.100/2022-Plenário | **888/2011-Plenário** | A lista de indícios de fachada é metodologia nossa; o TCU decidiu a admissibilidade da prova indiciária |
| 7.002/2023-Plenário | **2.470/2008-Plenário** | Valores de teto são lei e vivem em `catalogo_vicios`, não em ementa |
| 1.273/2020-Plenário | **1.936/2011-Plenário** | Não era erro de colegiado: o 1273/2020 existe e trata de **tempo de serviço religioso** — citação inteiramente trocada |

Achados adicionais no bloco injetado nos prompts (`contexto_jurisprudencial_para_prompt`):

- **2.622/2015 não existe** — o clássico do BDI é **2.622/2013**. Era erro de ano, e o número
  errado ia para o prompt de toda análise de superfaturamento.
- **1.793/2011** existe, mas decide sobre adesão a ata de registro de preços vencida — estava
  rotulado como precedente de *fracionamento*. Trocado por 2.470/2008.
- **3.654/2020** (conflito de interesse) não se confirmou: o número saiu e a regra passou a citar
  a base legal (Lei 14.133, arts. 9º, III e 14). Não se cita o que não se conferiu.

**Restam 9 citações `nao_confirmado`** — números dentro da faixa plausível, ausentes do recorte
selecionado. Não são erro presumido; entram na nota ao pé como pendência de conferência na fonte.
| E3 | Fundamentar por acervo real (`fundamentar()`) em vez de memória do modelo | Todo achado com acórdão conferível |
| E4 | Seção "Responsáveis" no parecer, vinda de `montar_ficha` | Parecer individualiza quem responde |
| E5 | `judicializacao_de_documento` no fluxo: matéria já sub judice muda a recomendação | Representação × subsídio ao MP decidido por dado |

## Bloco F — Yoda e Hermes *(pendente)*

| # | Item | Critério |
|---|---|---|
| F1 | Yoda: comando `/responsaveis <processo>` devolvendo a ficha | Resposta no Telegram com tabela e lacunas |
| F2 | Yoda: alerta quando surge achado em processo cujo ordenador já é reincidente | Notificação com histórico |
| F3 | Hermes: gravar a ficha de responsabilidade no vault por caso | Nota por processo, com `[[links]]` para pessoas |
| F4 | Hermes: nota de pessoa para cada agente recorrente | Ficha viva por agente público |
| F5 | Aplicar o gate de citação (E1) também às saídas de Yoda e Hermes | Nenhum canal escapa da verificação |

## Bloco G — Fontes ainda não integradas *(pendente)*

| # | Item | Referência |
|---|---|---|
| G1 | Indexar `resposta-consulta.csv` e `boletim-jurisprudencia.csv` do TCU | `docs/FONTES-JURIDICAS-NACIONAIS-2026-07-27.md` #45, #47 |
| G2 | Rodar `extrair_numeros_cnj` sobre todo o acervo SEI | Mapa do que já está judicializado |
| G3 | Pedir credencial da API do CNCIAI (condenações por improbidade) | Achado de peso máximo; via gabinete |
| G4 | Decidir o destino do `lexml_fetcher.py` (bloqueado por WAF) | Proxy, mirror ou aposentadoria declarada |

---

## Ordem sugerida de execução

1. **A3** — desconectar os MCPs na conta *(2 min do titular; maior economia isolada)*
2. **E1 + E2** — gate de citação e conserto das 5 referências *(risco jurídico ativo hoje)*
3. **B5 + B6** — persistir e varrer o acervo, subindo a cobertura
4. **C2 + C4** — datar papéis e montar a cadeia decisória
5. **D1–D5** — análises sobre a base de agentes já consolidada
6. **E4/E5, F1–F5** — levar tudo aos quatro sistemas
7. **A4/A5, G1–G4** — enxugar contexto e fechar as fontes pendentes

---

## Verificação do que foi entregue hoje

| Item | Evidência |
|---|---|
| `sei/agentes_publicos.py` | 29 testes passando · validado em 1.796 documentos reais |
| `knowledge/tcu_juris_index.py` | 17 testes · índice de 17.510 acórdãos e 292 súmulas |
| `collectors/datajud.py` | 13 testes · consulta real ao TJRJ |
| `collectors/querido_diario.py` | 6 testes · coletor morto há meses, de volta |
| **Total** | **65 testes novos, 0 falhas** |
| Economia de contexto | ~1.700 tok/turno, reversível |
| **Não verificado** | Suíte completa do projeto **não** rodada (regra de não derrubar a VM) |
