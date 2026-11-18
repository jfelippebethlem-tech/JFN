# JFN — Arquitetura de Autoaprimoramento da Perícia

| | |
|---|---|
| **Documento** | Desenho, decisões, medições e riscos |
| **Versão** | 1.0 — 18/11/2026 |
| **Escopo** | Perícia de execução (`tools/lex_execucao.py`, tabela `lex_execucao`) |
| **Código** | `compliance_agent/autoaprimoramento/` · testes `tests/test_autoaprimoramento_*.py` |
| **Comando** | `python -m compliance_agent.autoaprimoramento ciclo --dry-run` |
| **Estado** | Implementado e medido; ciclo real e agendamento **desligados por padrão** |

> **Regra de ouro (herdada do Massare): IA nunca aprova a própria mudança.** Quem aprova é código determinístico,
> contra laudos conferidos na fonte primária que a proposta não viu. Nenhuma lição entra no prompt "na fé".

---

## 1. Sumário executivo

Em 18/11/2026 a conferência na fonte primária (íntegra do SEI + Ordens Bancárias do SIAFE) mostrou que quase todo
"risco alto" dado pelos modelos de volume caía, e que parte do que o Opus mantinha alto lendo só o resumo também
caía. O conserto daquele dia foi manual (regra 9 do prompt). Esta arquitetura transforma esse trabalho manual em
ciclo: toda conferência vira rótulo, o rótulo calibra a confiança de cada motor, o erro recorrente vira armadilha
catalogada, a armadilha vira proposta de mudança, e a proposta só chega à produção se um portão determinístico
medir melhora sem regressão num conjunto que ela não viu.

**Medições de 18/11/2026 (ledger real, `data/autoaprimoramento/auto.db`):**

| Medida | Valor | Estado |
|---|---|---|
| Processos conferidos na fonte primária (nível 2) | 93 | VERIFICADO (contagem no ledger) |
| Pares laudo de volume → Opus sobre o resumo | 888 | VERIFICADO |
| Risco alto de modelo de volume que seguiu alto após conferência | 9 de 517 (1,8%; IC 95% 0,9–3,1%) | VERIFICADO (treino + validação) |
| Risco alto do Opus sobre o resumo confirmado na fonte | 8 de 26 (31,5%; IC 95% 15,4–49,9%) | VERIFICADO (amostra dirigida — ver §7) |
| Risco alto de volume confirmado na fonte (estimador de duas fases) | 7,1% (IC 95% 2,4–15,3%) | ESTIMADO |
| Brier na validação: nota verbalizada → taxa calibrada | 0,4635 → 0,0354 (taxa-base: 0,0362) | VERIFICADO (219 laudos fora do ajuste) |
| Faixas certificadas para sair como risco alto sem ir à fonte | nenhuma | VERIFICADO |
| Indícios descartados na fonte, com o porquê | 132 em treino + validação; 13 armadilhas + 28 processos sem classificação | VERIFICADO |
| Laudos de fonte primária regravados por juízo mais fraco | 51 processos | VERIFICADO (achado do dia — §6.1) |
| Candidatos dos 2 primeiros ciclos | 2 reprovados no portão; 4 aguardam reexecução |
| Cruzamento entre casos (mesmo credor de risco alto confirmado) | 306 pares, 231 processos, 10 credores | VERIFICADO | VERIFICADO |

Os números são regravados a cada ciclo em `data/autoaprimoramento/relatorio.md`; os desta tabela são os do dia.

> **Leitura honesta.** A calibração não tornou os modelos de volume melhores — mostrou que a nota deles quase não
> separa risco real (o ganho sobre "dizer sempre a taxa-base" é de 0,0008 no Brier). A consequência prática é a
> regra de exibição do §5.2: risco alto sem prova primária nunca sai como VERIFICADO.

---

## 2. De onde veio cada ideia

### 2.1 Esqueleto: motor de automelhoria do Massare

Fonte: `vm2:~/massare/docs/BRIEF-MOTOR-AUTOMELHORIA.md`, `MOTOR-AUTOMELHORIA.md` e o pacote `massare/motor/`
(fases 1–7), lidos em 18/11/2026 (só leitura).

| Peça do Massare | Tradução no JFN | Onde |
|---|---|---|
| Dados point-in-time com proveniência e hash | Cada laudo vira versão com motor, nível de prova, data e hash; nada é regravado | `ledger.py` (`laudo_versao`) |
| Estratégias versionadas e imutáveis | Versões da rubrica (lições no prompt + filtros), identificadas pelo hash | `registro.py` (`versao`) |
| Backtest | Reexecução da versão candidata sobre a verdade de chão, em banco em memória | `reexecucao.py` |
| Diário com o porquê | Indício conferido: confirmado, descartado (armadilha + motivo) ou lacuna | `ledger.py` (`indicio_conferido`) |
| Relatório de fraquezas | Por motor, por armadilha, descartes sem explicação | `agentes.pesquisa` |
| Agentes Pesquisa → Hipótese → Código → Revisão, só em `candidatos/` | Idem; determinísticos por padrão (teto de LLM do ciclo = 0) | `agentes.py` |
| Portão de validação determinístico (9 testes) | 6 regras: amostra, mensurável, sem regressão, melhora + McNemar, estabilidade, travas | `portao.py` |
| Registry campeão × desafiante, sombra, rollback em 1 comando | `candidato → sombra → campeão`, promoção humana, `rollback` | `registro.py`, CLI |
| Monitor de deriva + kill switch | Prova primária regravada, deriva semanal, arquivo `KILL` | `monitor.py` |
| `ciclo --dry-run`; agendamento escrito e desabilitado | Idem: ensaio numa cópia; real exige `JFN_AUTOAPRIMORAMENTO=1` | `orquestrador.py` |
| Calibração do juiz por Brier/BSS | Calibração por motor e faixa, com intervalo | `calibracao.py` |
| Ledger de melhoria com antes/depois | Veredito do portão gravado na versão e em `evento_registro` | `registro.py` |
| Seleção natural de teses falsificáveis | Hipótese com critério de refutação explícito; reprovada não é repetida | `agentes.hipotese`, `agentes.propor` |

**Defeitos que o próprio Massare registrou e que este desenho corrige:**

| Defeito no Massare | Correção aqui |
|---|---|
| "Promessas que eram só docstring": lições sem critério de promoção, ledger sem produtor | O produtor é um gancho no único ponto de regravação (`lex_execucao._antes_de_regravar`); lição só existe se o campeão a contém |
| Juiz descalibrado "encolhe" pela média com a taxa-base (doc e código divergiam) | Não se encolhe a nota: publica-se a taxa medida da célula, com intervalo; sem amostra, INDISPONÍVEL |
| Amostra mínima de 5 vereditos | Mínimo de 8 por célula e 30 casos + 3 riscos altos verdadeiros no portão |
| Debate multiagente e autocorreção sem sinal externo: placebo | Nenhum laudo é "revisado pelo próprio modelo"; todo sinal vem da fonte primária |
| Goodhart só reportado, sem ação | O portão é a ação: perder um risco alto verdadeiro reprova, por mais falsos altos que derrube |

### 2.2 O que já existia no JFN e foi religado (não reinventado)

| Peça da casa | Papel na arquitetura |
|---|---|
| `llm/conferencia_opus.py` (fila) | Fonte dos pares laudo de volume × Opus (`resposta` × `resposta_opus`) |
| `llm/cruzamento.py` (`cruzamento_motores.db`) | Diz qual motor deu qual nota quando o texto não sobrou |
| `lex_execucao.aplicar_conferencia`, `_gravar` | Ponto único de regravação: recebe o gancho do ledger e a proteção da prova primária |
| `lex_execucao._regras_calibracao` (lições no prompt) | Passa a incluir, primeiro, as lições do campeão |
| `cruzamentos_intel._ob_paga`, `lex_execucao.mapa_obs_siafe` | Valor pago = OB contabilizada, sem a devolvida |
| `correlacao_sei.estado_do_laudo` | Ganha a nota: risco alto sem prova primária sai "A CONFERIR" |
| `tools/automelhoria_geral.py` (fila aberto/curado/REINCIDIU) | Sensor `autoaprimoramento` |
| Loop Jedi (`~/vault/aprendizados/jedi-loop-treino-ias.md`) | Mesmo protocolo (duvidar → testar → comparar → treinar → verificar), agora com registro e portão |
| `llm/ritmo_assinatura`, `claude_motor`, `contingencia` | O ciclo não chama LLM; quem injeta um gerador responde pelos tetos da casa |

`llm/auto_melhoria.py` (auto-correções escritas por LLM na memória `metodo`) fica como está: as 50 lições
`pericia:*` que ele gerou são, em boa parte, a mesma frase reescrita (OB = pagamento; presunção de regularidade) —
nenhuma passou por avaliação. Não foram apagadas; a recomendação está no §9.

### 2.3 Estado da arte — o que foi aproveitado de cada técnica

| Técnica (fonte) | Ideia | O que entrou | O que ficou de fora e por quê |
|---|---|---|---|
| Reflexion — Shinn et al., NeurIPS 2023, arXiv 2303.11366 | Reflexão verbal a partir de sinal externo | O porquê de cada descarte, escrito por quem leu a fonte | Reflexão do próprio modelo sobre o próprio erro |
| Self-Refine — Madaan et al., NeurIPS 2023, arXiv 2303.17651; crítica de Huang et al., ICLR 2024, arXiv 2310.01798 | Gerar, criticar, reescrever | Nada | Autocorreção sem feedback externo troca acerto por erro: descartada |
| ExpeL — Zhao et al., AAAI 2024, arXiv 2308.10144 | Insights extraídos de trajetórias, com votos | Armadilha com contagem de processos; mínimo de 3 para virar proposta | Insights sem validação fora da amostra |
| Voyager — Wang et al., 2023, arXiv 2305.16291 | Só entra na biblioteca o que foi verificado | Só o campeão alimenta o prompt | Recuperação por embedding (teto de 8 lições dispensa) |
| GEPA — Agrawal et al., arXiv 2507.19457 | Treino → validação → teste; portão barato antes do caro | Partição fixa 50/25/25; revisão antes do portão; teste intocado | Evolução por Pareto com LLM refletor (custo) |
| MIPROv2 — Opsahl-Ong et al., EMNLP 2024, arXiv 2406.11695; OPRO — Yang et al., arXiv 2309.03409; ProTeGi — Pryzant et al., EMNLP 2023, arXiv 2305.03495; TextGrad — Yuksekgonul et al., arXiv 2406.07496 | Otimização de prompt guiada por métrica | Métrica única (falso alto × alto verdadeiro) e comparação pareada | Busca automática de instruções: com ~200 rótulos sobreajusta; nenhum dá garantia estatística |
| PoLL — Verga et al., arXiv 2404.18796; vieses de juiz — Zheng et al., NeurIPS 2023, arXiv 2306.05685; Panickssery et al., NeurIPS 2024, arXiv 2404.13076 | Júri de famílias diferentes; autopreferência | Juiz final não é LLM: é a fonte primária | Júri de LLM como árbitro |
| Trust or Escalate — Jung et al., ICLR 2025, arXiv 2407.18370; Learn then Test — Angelopoulos et al., arXiv 2110.01052; classificação seletiva — Geifman e El-Yaniv, NeurIPS 2017, arXiv 1705.08500 | Decidir só com garantia; senão escalar | "Faixa certificada": limite inferior de confirmação ≥ 90%; hoje nenhuma ⇒ tudo escala à fonte | Garantia formal em amostra finita (exige rótulos aleatórios — §7) |
| Confiança verbalizada — Xiong et al., ICLR 2024, arXiv 2306.13063 | Nota escrita pelo modelo é superconfiante | A nota não é tratada como probabilidade (Brier 0,46 contra 0,04) | — |
| Platt × isotônica — Niculescu-Mizil e Caruana, ICML 2005; ECE — Kumar, Liang e Ma, NeurIPS 2019, arXiv 1909.10155; intervalos — Brown, Cai e DasGupta, Statistical Science 2001 | Com pouco dado: poucas faixas, intervalo de Jeffreys | 3 faixas, posterior Beta, Jeffreys; ECE só auxiliar | Isotônica e binning fino |
| Active learning — Settles, 2009 (TR 1648); Active Testing — Kossen et al., ICML 2021, arXiv 2103.05331 | Escolher o que rotular; a escolha enviesa a medida | Fila dirigida + fatia aleatória de 20% com probabilidade de inclusão gravada | Estimador ponderado completo (só quando houver rótulos aleatórios) |
| Prediction-Powered Inference — Angelopoulos et al., Science 2023, arXiv 2301.09633 | Corrigir a predição farta pelo erro medido no ouro | Estimador de duas fases (volume → Opus → fonte) | Intervalo PPI formal (mesma razão) |
| Reusable holdout — Dwork et al., Science 2015; Recht et al., arXiv 1902.10811 | Holdout consultado demais deixa de medir | Conjunto de teste com consulta registrada e teto de 4 por trimestre | Thresholdout |
| McNemar — Dietterich, Neural Computation 1998 | Comparar duas versões nos mesmos casos | McNemar exato sobre os discordantes | — |
| Model collapse — Shumailov et al., Nature 2024 | Treinar em saída de modelo apaga as caudas | Lição nasce de rótulo de nível 2, nunca do veredito do Opus sobre o resumo | — |
| Lost in the Middle — Liu et al., TACL, arXiv 2307.03172; ACE — Zhang et al., arXiv 2510.04618 | Meio do prompt é mal lido; reescrever tudo colapsa o contexto | Lições do campeão no início do bloco; itens com id; teto de 8 | — |

Referências marcadas como não confirmadas na pesquisa (venue de TextGrad; Murphy 1973) não sustentam nenhuma decisão.

---

## 3. Desenho

```
   SEI (íntegra) + SIAFE (OB)                     modelos de volume          Opus sobre o resumo
            │ conferência na fonte                       │ laudo                     │ conferência
            ▼                                            ▼                           ▼
   ┌─────────────────────────────── LEDGER (auto.db, só acréscimo) ────────────────────────────────┐
   │ laudo_versao (nível 0 · 1 · 2)  →  conferencia (par menor→maior)  →  indicio_conferido (porquê) │
   └───────┬───────────────────────────────┬──────────────────────────────────┬────────────────────┘
           ▼                               ▼                                  ▼
     CALIBRAÇÃO                      TAXONOMIA DE ARMADILHAS            SELEÇÃO ATIVA + CRUZAMENTO
  P(confirma | motor, faixa)       sementes + candidatas novas        fila da fonte (dirigida + aleatória)
  Brier · Jeffreys · 2 fases               │                           mesmo credor de risco confirmado
           │                               ▼                                  │
           │                 AGENTES  Pesquisa → Hipótese → Código → Revisão  │
           │                        (só escrevem em candidatos/)              │
           │                               ▼                                  │
           │                 REEXECUÇÃO na validação (sombra, em memória)     │
           │                               ▼                                  │
           │                 PORTÃO DETERMINÍSTICO  R1…R6  ──reprova──► registro (não repete)
           │                               │ aprova                           │
           │                               ▼                                  │
           │                 SOMBRA (≥ 50 laudos) ──► promoção HUMANA ──► CAMPEÃO ──► campeao.json
           ▼                                                                  │            │
   estado_do_laudo: VERIFICADO só com prova primária                          ▼            ▼
   "A CONFERIR" com a taxa medida                                   conferência na fonte   prompt da perícia
                                                                    (volta ao ledger)      (rollback em 1 comando)
   MONITOR: prova primária regravada · deriva · KILL            SENSOR na automelhoria_geral
```

### 3.1 Níveis de prova

| Nível | Quem | O que leu |
|---:|---|---|
| 0 | Modelo de volume (Gemini, cascata, Haiku pela API, Sonnet co-motor) | Ficha do sweep + recorte de texto |
| 1 | Opus pela assinatura (fila de conferência, lote de 18/11, sessão que releu só a entrada) | O mesmo resumo |
| 2 | Agente ou sessão Claude Code com a peça lida declarada | Íntegra do SEI + OB do SIAFE |

O nível sai do campo `modelo` de `lex_execucao` (`ledger.motor_e_nivel`). Um par de conferência liga sempre um
nível menor a um maior do mesmo processo; laudo de volume posterior à conferência não forma par (julgou outra
captura).

### 3.2 Partição fixa

Cada processo cai, pelo hash do número, em treino (50%), validação (25%) ou teste (25%). O teste só é lido por
`ledger.consultar_teste`, que grava quem consultou e por quê e recusa a 5ª consulta em 90 dias. Em 18/11/2026 o
teste **não foi consultado** (as contagens agregadas por conjunto foram vistas uma vez, na conferência da
importação; nenhuma decisão de desenho usou o teste).

---

## 4. Componentes

| Módulo | Função | Estado que mantém |
|---|---|---|
| `config.py` | Caminhos, chaves (`JFN_AUTOAPRIMORAMENTO`, `…_KILL`, `…_DIR`), tetos do ciclo e do portão | — |
| `ledger.py` | Versões de laudo, pares, indícios conferidos, partição, orçamento do teste, gancho de regravação | `laudo_versao`, `conferencia`, `indicio_conferido`, `consulta_teste` |
| `armadilhas.py` | 15 armadilhas-semente (regex do porquê, regex do indício fraco, lição); candidatas novas; roteiro da fonte | código versionado |
| `importar.py` | Reconstrói a verdade de chão das fontes da casa (idempotente, só leitura) | — |
| `calibracao.py` | Tabela motor × faixa, Jeffreys, Brier/BSS/ECE, duas fases, faixas certificadas, `confianca()` | `calibracao.json` |
| `registro.py` | Versões imutáveis, transições, promoção humana, rollback, `campeao.json` | `versao`, `evento_registro`, `laudo_sombra` |
| `reexecucao.py` | Backtest por filtros (sem LLM) e por prompt (gerador injetado, banco em memória) | — |
| `portao.py` | R1–R6 + McNemar exato | — |
| `agentes.py` | Pesquisa, hipótese, código, revisão; propostas de armadilha nova | `candidatos/`, `relatorio_fraquezas.json` |
| `selecao.py` | Fila da fonte, cruzamento entre casos, roteiro | `fila_fonte`, `cruzamento_caso`, `fila_fonte.json` |
| `monitor.py` | Prova primária regravada, deriva, `matar()` | arquivo `KILL` |
| `orquestrador.py`, `__main__.py` | Ciclo, relatório, CLI | `ultimo_ciclo.json`, `relatorio.md` |

Tudo em `data/autoaprimoramento/` (fora do git).

---

## 5. Decisões

### 5.1 O portão

| Regra | Exigência | Por quê |
|---|---|---|
| R1 amostra | ≥ 30 casos | Abaixo disso o McNemar não tem poder |
| R2 mensurável | ≥ 3 riscos altos verdadeiros no conjunto | Sem eles "não perdeu nenhum" não mede nada |
| R3 sem regressão | 0 risco alto verdadeiro perdido | Falso negativo é o erro que a casa não aceita |
| R4 melhora | Falsos altos −5% **e** McNemar exato p ≤ 0,05 | Melhora pequena e não significativa é ruído |
| R5 estabilidade | Melhora sem perda nas duas metades | Não vale ganhar num subgrupo só |
| R6 travas | KILL desligado | — |

Controle positivo e negativo do portão estão em `tests/test_autoaprimoramento_ciclo.py` (derrubar 30 de 60 falsos
passa; perder um verdadeiro, não mudar nada, melhorar 2 em 60, conjunto pequeno, conjunto sem verdadeiros e ruído
aleatório reprovam).

### 5.2 Exibição — risco alto só é VERIFICADO com prova primária

`correlacao_sei.estado_do_laudo(modelo, nota)`:

| Laudo | Antes | Agora |
|---|---|---|
| Nota ≥ 7, conferido na fonte primária | VERIFICADO | VERIFICADO — "conferido na fonte primária" |
| Nota ≥ 7, Opus sobre o resumo | VERIFICADO | **A CONFERIR** — "de 26 laudos altos do Opus sobre o resumo conferidos na fonte, 8 seguiram altos (31%)" |
| Nota ≥ 7, modelo de volume | PENDENTE | PENDENTE, com a taxa medida do motor |
| Nota < 7 | como era | como era |

Sem tabela de calibração o texto diz INDISPONÍVEL; nunca um número inventado.

### 5.3 Prova primária não é regravada por juízo mais fraco

`lex_execucao._antes_de_regravar` roda em toda regravação (`_gravar_uma_vez` e `aplicar_conferencia`): arquiva a
linha vigente no ledger e, se ela é de nível 2 e o laudo que chega não é, **recusa a regravação** — o laudo
recusado também é arquivado. Nível 2 substitui nível 2 (nova leitura dos autos).

### 5.4 O ciclo não chama LLM e não promove

Teto de LLM do ciclo = 0. Candidato que só muda filtro é julgado na hora; candidato que muda lição fica
`candidato` até alguém rodar a reexecução com um gerador (`reexecucao.por_prompt`, até 40 casos, em memória, sem
`item` — o laudo de sombra não entra na fila do Opus). Aprovado no portão entra em **sombra**; virar campeão exige
50 laudos em sombra e o comando `promover CHAVE --quem NOME`. `rollback --quem --motivo` devolve o posto ao
anterior. O `KILL` zera as lições do campeão na produção imediatamente.

### 5.5 Seleção ativa

Pontuação dirigida = valor pago (OB contabilizada) × (taxa de confirmação da célula + metade da largura do
intervalo) × (1 + fração de indícios em armadilha conhecida) × 2 se o credor já teve risco alto confirmado na
fonte. 20% das vagas são sorteio uniforme entre todos os laudos pagos sem prova primária, de qualquer nota, com a
probabilidade de inclusão gravada — é o que permitirá medir a calibração sem viés e o falso negativo. Cada item
sai com o **roteiro da fonte** (18 passos aprendidos nos casos confirmados de 18/11: aditivo vigente como base,
processo de continuação, início retroativo, status da OB, ISS retido, relatório-modelo de fiscalização etc.).

---

## 6. Achados do primeiro ciclo

### 6.1 Prova primária regravada — 51 processos

> **Alerta.** De 72 laudos escritos por agentes na fonte primária em 18/11, 58 puderam ser ligados a um processo
> sem adivinhar (arquivo `.ns`, resumo idêntico, ou OB + NL que o SIAFE liga a um único processo); 14 ficaram sem
> processo e não foram usados. Dos ligados, **51 têm hoje em `lex_execucao` um laudo de nível menor** — o lote do
> Opus sobre o resumo gravou por cima, ou o laudo do agente nunca foi aplicado. Os 51 laudos de fonte estão
> preservados no ledger (`laudo_versao`, `nivel_prova = 2`, origem `agente:*`). A lista está em
> `data/autoaprimoramento/relatorio.md` §6 e no sensor `autoaprimoramento:fonte_perdida`.

A reaplicação **não foi feita**: são laudos de outra sessão, e reaplicar exige conferir que a captura do processo
não mudou depois. É a primeira ação recomendada (§9).

### 6.2 Calibração

- A nota verbalizada não é probabilidade: Brier 0,4635 na validação (219 laudos, 8 riscos altos verdadeiros).
- Nenhum motor de volume passa de 7,5% de confirmação na faixa alta; a célula conjunta é 1,8%.
- O Opus sobre o resumo, na faixa alta, confirma 31,5% (8 de 26) — e, do que ele baixou, a fonte achou alto em 2
  de 42. A amostra de nível 2 foi escolhida a dedo (maiores valores, mantidos altos): o intervalo é largo e o
  número vale como ordem de grandeza.

### 6.3 Armadilhas (132 descartes em treino + validação)

| Armadilha | Processos |
|---|---:|
| Sem classificação (alimenta as candidatas novas) | 28 |
| "Ausência" de documento que está nos autos | 17 |
| "Ausência de OB" com OB contabilizada no SIAFE | 15 |
| Ausência no recorte capturado tratada como fato | 12 |
| Retenção de tributo lida como diferença de valor | 8 |
| NF cancelada com substituta regular | 6 |
| Cobrar atesto/OB de processo que não é de pagamento | 5 |
| Data de 2025/2026 lida como futura; nº SEI/NE lido como NF | 3 cada |
| Empenho estimativo; dígito de OCR | 2 cada |
| Pesquisa de preços alheia; objeto da ficha; OB devolvida e reemitida | 1 cada |

### 6.4 Portão

`filtros: ob_existe_no_siafe` e `filtros: ausencia_no_recorte` — **reprovados**: 71 casos, 4 riscos altos
verdadeiros, 0 perdido, falsos altos 46 → 46. Os laudos de volume recentes raramente trazem só "ausências" (as
regras 5 e 8 do prompt já tinham tirado isso); o filtro, que só derruba laudo cujos indícios são todos armadilha,
não tem o que derrubar. É o portão funcionando: uma ideia plausível, medida, não pagou — e não será tentada de novo.
As lições `documento_existe_nos_autos`, `ob_existe_no_siafe`, `ausencia_no_recorte` e `retencao_tributaria`
aguardam reexecução por prompt.

Descartes sem classificação que já se repetem (propostas em `candidatos/armadilhas_novas/`): nota de empenho ou
item patrimonial do SIAFE lido como irregularidade (5 processos); atesto por carimbo na própria NF não reconhecido
como atesto (5 processos).

---

## 7. Riscos e limites

| Risco | Como aparece aqui | Mitigação | Resíduo |
|---|---|---|---|
| Sobreajuste ao conjunto de avaliação | Regex e limiares ajustados olhando os mesmos casos | Partição fixa; teste com orçamento de consultas; desenho feito só com treino | Validação reutilizada a cada ciclo — por isso o McNemar e a sombra |
| Viés de seleção dos rótulos | Toda conferência de 18/11 foi de nota ≥ 7 e maior valor | Fatia aleatória de 20% com probabilidade gravada; duas fases | Calibração das faixas baixa e média de nível 2: INDISPONÍVEL até a fatia aleatória render |
| Reward hacking / Goodhart | Derrubar tudo zera falsos altos | R2 + R3: perder um verdadeiro reprova; filtro só derruba laudo cujos indícios são TODOS armadilha | Poucos verdadeiros (8 na validação): a R3 tem pouco poder |
| Colapso de diversidade | Lições nascidas do veredito do Opus | Lição exige ≥ 3 processos de nível 2 | — |
| Deriva de prompt | Lições acumulando | Teto de 8; versão imutável; rollback | — |
| Rótulo de nível 2 errado | Quem conferiu também erra | Nível 2 substitui nível 2; o anterior fica no ledger | Sem segunda leitura independente da fonte |
| Classificador de nível pelo texto de `modelo` | Proveniência escrita à mão | Testes com as grafias reais do dia | Grafia nova cai em nível 0 ou 1 (erro para o lado seguro) |
| Loop que se reaciona | — | O ciclo não se agenda, não chama LLM, não promove | — |
| Deriva semanal | Semanas antes do gancho têm base parcial | Fica no relatório, fora do sensor | Vale a partir de dezembro |

---

## 8. Operação

```bash
# ensaio (não muda nada que a produção lê)
python -m compliance_agent.autoaprimoramento ciclo --dry-run [--agentes PASTA ...]
# ciclo real
JFN_AUTOAPRIMORAMENTO=1 python -m compliance_agent.autoaprimoramento ciclo
python -m compliance_agent.autoaprimoramento status
python -m compliance_agent.autoaprimoramento promover CHAVE --quem NOME
python -m compliance_agent.autoaprimoramento rollback --quem NOME --motivo "..."
python -m compliance_agent.autoaprimoramento matar "motivo"        # religar: apagar data/autoaprimoramento/KILL
python -m compliance_agent.autoaprimoramento teste --quem NOME --motivo "..."   # gasta 1 das 4 consultas do trimestre
```

**Agendamento (escrito, NÃO instalado):**

```cron
# 20 7 * * * cd /home/ubuntu/JFN && JFN_AUTOAPRIMORAMENTO=1 PYTHONPATH=. nice -n 10 timeout 900 .venv/bin/python -m compliance_agent.autoaprimoramento ciclo >> data/autoaprimoramento_ciclo.log 2>&1
```

O ciclo leva cerca de 30 s e não chama LLM. Instalar é decisão do dono.

---

## 9. O que ficou para depois

| Item | Por quê não agora |
|---|---|
| Reaplicar os 51 laudos de fonte primária regravados | São de outra sessão; exige conferir a captura de cada processo |
| Reexecução por prompt das lições candidatas (até 40 casos por candidato) | Chama a cascata de volume; o dono decide o teto antes (regra de custo) |
| Laudos em sombra em produção (`laudo_sombra`) | Só faz sentido com um desafiante aprovado; a tabela e a trava de 50 existem |
| Detector de documento reaproveitado (hash do corpo entre processos do mesmo credor) e "ISS da NF × OB" | Detectores novos, com controle positivo e negativo próprios; o primeiro encosta na frente de similaridade por GPU aberta no quadro |
| Estender o ledger à perícia integral e à triagem de alertas | Mesmo esqueleto; cada tarefa precisa do seu aplicador |
| Faxina das 50 lições `pericia:*` da memória `metodo` | Redundantes e nunca avaliadas; tirar exige medir antes (é uma mudança de prompt como outra) |
| Aba no painel | `static/` pertence a outra frente; o sensor e o relatório cobrem por ora |

---

## 10. Fontes

**Dados:** `data/compliance.db` (`lex_execucao`, `sei_ficha`, `ob_orcamentaria_siafe`), `data/conferencia_opus.db`,
`data/cruzamento_motores.db`, `data/conferir_85.log`, laudos de agentes de 18/11/2026.
**Casa:** `docs/REGRAS-DE-QUALIDADE.md`, `config/propagacao.yaml`, `~/vault/aprendizados/CATALOGO-DE-FALHAS.md`,
`~/vault/aprendizados/jedi-loop-treino-ias.md`, notas de caso em `~/vault/casos/`.
**Massare:** `vm2:~/massare/docs/{BRIEF-MOTOR-AUTOMELHORIA,MOTOR-AUTOMELHORIA,LOOP-MELHORIA,INTELIGENCIA-PROGRESSIVA-2026-07,ENXAMES-JUIZ-SUPERVISOR-2026-06}.md`, `massare/motor/`.
**Literatura:** as referências do §2.3 (arXiv/venue indicados em cada linha).
