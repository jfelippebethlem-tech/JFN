# Handoff — 2026-07-29 (noite) · densidade, vínculos e superfície

> Continuação de `docs/HANDOFF-2026-07-29.md` (manhã). Comece por aqui.
> Branch **`feat/painel-v15-holo`** · **`main` reconciliado e em dia** (fast-forward, sem force-push).
> 8 commits nesta sessão.

---

## 1. Em uma frase

O gargalo saiu do raciocínio e foi para a **entrega**: o motor pensava bem e o documento chegava
cortado, o OSINT estava construído e desligado, e 43% da API não tinha por onde ser alcançada.

---

## 2. O que foi FEITO

### 2.1 O entregável parou de mentir por omissão

| Defeito | Como estava | Como está |
|---|---|---|
| §1-L do PDF de órgão | **não era renderizada** — ~1.000 linhas do MD (45 fornecedores nominados, com objeto e valor) sumiam sem aviso | consulta única `dados_contratos_fornecedor`, consumida pelo MD **e** pelo PDF |
| Cortes de lista | ~30 fatias silenciosas em cartel, laranja, rede societária; a pior era `LIMIT 50` **na origem** (o relatório não sabia quantos ficaram de fora) | `reporting/completude.py` — `tudo()` não corta, `top_declarado()` corta e diz |
| Teto de OBs | 40 no MD e 12 no PDF **ao mesmo tempo**, com o comentário afirmando "sem limite, tudo no PDF" | `TOP_OB_ANO = None`, constante única de módulo |
| Numeração de página | `pág. X de Y` só no pipeline Chromium (o PDF de órgão nunca teve) | removida — contar página convida a cortar para caber |
| §1-G execução | existia **só no Markdown**; o PDF, que é o que circula, saía sem "pagou-se, há prova de entrega?" | §9-C no PDF, mesma fonte de dados do MD |
| Gate de neutralidade | bloqueava **`iterj`** — órgão público real, UG 133100, alvo declarado no CLAUDE.md | removido da lista; e "JFN" saía impresso em 3 lugares, agora travado por catraca de fonte |

**Medido no produto real:** órgão ITERJ **19 → 92 páginas**, MD 225 KB → 846 KB. MGS CLEAN: 40
páginas, zero numeração, zero nome interno.

### 2.2 O `osint/` saiu do papel — e o tempo passou a existir

- **G.3 fechado.** `osint/fonte_grafo.py` é o caller que faltava: alimenta o `GrafoVinculos` com
  `socios_receita` e sobe a cadeia PJ→PJ (**2.449 elos encadeáveis** na base). Rodou sobre dado real.
- **Dois defeitos no motor, que só o dado real revelou** — mesma raiz: `beneficiario_final` ignorava
  a **direção** da aresta. (a) A subida seguia a mesma aresta de volta e relatava *participação
  cruzada circular* em toda cadeia de dois degraus — e o módulo trata ciclo como ACHADO, então era
  detector disparando no normal. (b) Ao chegar numa holding, descia para as empresas **irmãs** e
  devolvia os sócios delas como beneficiários da empresa de origem.
- **A SÉRIE HISTÓRICA — o achado mais valioso da sessão.** Os caminhos oficiais da Receita estão 404
  desde janeiro/2026, mas o espelho público `dados-abertos-rf-cnpj.casadosdados.com.br` guarda **41
  snapshots mensais de 2023-03 a 2026-07, sem chave e sem cobrança**. Substitui com vantagem o
  BigQuery vetado por billing. **Ingeridos 19 meses (2025-01 a 2026-07) → 9.113 saídas de sócio
  identificadas**, informação que não existia na casa.
- **`vinculo_na_data`** responde SIM, NÃO ou **INDISPONÍVEL** — e INDISPONÍVEL não é NÃO: fora da
  janela observada vem o pedido de diligência à JUCERJA. Era a pergunta que fechava caso de
  direcionamento e não tinha resposta possível.
- **Persistência**: `pessoas` e `relacionamentos` (desenhadas no schema, **vazias desde sempre**)
  agora recebem o grafo. `data_fim` grava NULO **de propósito** — a fonte não observa saída, e nulo
  aqui é afirmação, não esquecimento. Rótulo FollowTheMoney derivado na exportação.

### 2.3 Parentesco: hipótese medida, nunca conclusão

Não existe base aberta brasileira de parentesco — conferido na fonte: Registro Civil só serve
agregado por UF, TSE não tem campo de parentesco, **nome da mãe não é público em nenhuma base
federal** (a coluna `pessoas.nome_mae` existe aqui e continua vazia; é o certo). O banco de vínculos
do TCU que cita pai/mãe/irmão é alimentado por Receita e CNIS — cita-se o **método**, não se finge
ter o insumo.

**Prevalência medida hoje, sobre 31.132 raízes com QSA:**

| Eixo | Prevalência | Veredito |
|---|---:|---|
| co-ocorrência societária (mesmas 2 pessoas em 2+ empresas) | **4,76%** | sinal — pode acender sozinho |
| coabitação (endereço idêntico entre empresas distintas) | **3,86%** | sinal — pode acender sozinho |
| sobrenome de família repetido no MESMO QSA | **16,88%** | **não é sinal** |
| sobrenome raro compartilhado ENTRE empresas | **25,90%** | **não é sinal** |

Empresa familiar é a norma no Brasil, e o corte por raridade quase não move o número (16,9% → 10,6%
exigindo sobrenome com ≤3 ocorrências). Daí a regra dura: **eixo de sobrenome nunca acende sozinho.**
Sem ela, estaríamos acusando um quinto do acervo. `prevalencia()` recalcula na base de hoje e o teste
falha se um eixo dobrar — é assim que a calibração deixa de envelhecer em silêncio.

### 2.4 Três listas paralelas divergiam

1. **Sete detectores existiam e o catálogo não os conhecia** (C8 e X7–X12). O catálogo
   **subestimava a própria cobertura**, e `lacunas()` mandava construir o que já existia.
   42 → **48 vícios**, 45 cobertos, zero detector órfão. Checagem inversa acrescentada a `validar()`.
2. **Quatro detectores sem peso** caíam no default 0,6. `C7` (sancionada contratada) e `P6`
   (contratação direta indevida) são `violacao_legal`, peso **1,0**: o score subestimava **os dois
   sinais mais graves do sistema**. Pesos agora derivam do REGISTRO por família.
3. **Cinco detectores fora de todo runner** (P4, P6, C7, C8, J8) — existiam e nunca rodavam para
   quem chamava `rodar_*`. Ligados.

### 2.5 Painel e Yoda: 57 rotas órfãs → 0

Oito abas novas na esfera Transversal (**60 abas** no total): **Vínculos**, **Peças** (dossiê
completo, dossiê mestre, minuta .docx, PPP, acatamento, conjunto), **Fontes externas** (os 6
providers), **Hub físico**, **Acurácia** (`/api/eval/*` junto do produto, com lift anti-preditivo e
circularidade marcados), **Detectores** (12 leituras órfãs), **Instrumentação**, **Missões** (a fila
paralela do Hermes, que só existia no backend).

`tests/test_rotas_sem_orfa.py` é a catraca — **teto 0**. `tools/painel_boot_check.py` é o detector
certo para o boot: `pageerror`, não a aparência da tela. **60 abas percorridas sem um erro.**

`capabilities.yaml` ganhou 6 capacidades de vínculo e o grupo "🕸️ Vínculos" no menu do Telegram —
fonte única, então `/api/lista`, `/api/skills` e o teclado já as mostram.

---

## 3. Coisas que eu supunha e o dado desmentiu

- **`/api/lista` e `/api/skills` NÃO divergem.** São dois renders da mesma skilltree — `render_menu`
  curado e `render` completo. Não há o que unificar.
- **Os sub-ids `C1`/`C2`/`C3-5`/`C4` em `PESOS_DETECTOR` não são fantasmas.** `CFachada.avaliar_todos`
  os emite como `ResultadoDetector.detector`; sem peso próprio, o achado de fachada mais específico
  pesaria menos que a família-mãe.
- **Os botões de pausar/retomar sweep existiam.** Minha catraca acusou falso positivo porque
  `sweep()` compõe `'/api/sweeps/'+a` em runtime. Catraca que mente é catraca que se aprende a
  ignorar — corrigida antes de fechar.
- **A divergência com `main` era 4 atrás / 396 à frente, não 121/1.729.** Eu havia comparado com um
  `main` **local defasado** (06/07); o `origin/main` estava em 18/07.

---

## 4. Erro operacional que custou tempo — não repetir

`git checkout main 2>&1 | tail -2 && git reset --hard origin/main` — **o pipe faz o exit code ser o
do `tail`**, sempre 0. O `checkout` falhou (árvore com mudanças de outra sessão), a corrente
continuou, e o `reset --hard` rodou na **branch de trabalho**, movendo-a para `origin/main`. Os 397
commits foram recuperados pelo reflog em segundos, e o push anterior já os tinha salvo no remoto.

**Regra:** nunca encadear `&&` depois de um comando git com pipe. Verificar `git branch
--show-current` entre o `checkout` e qualquer `reset`.

---

## 5. PENDENTE

### 5.1 Herdado e ainda aberto (ordem de valor por esforço)

| # | O quê | Estado |
|---|---|---|
| 1 | **E.0.1 — ampliar coleta de propostas** | intocado. Só 0,66% dos certames (114 de 17.242) têm classificado além do 1º lugar. É isto, e não falta de vínculo, que faz o E.3.2 dar zero |
| 2 | **D.3.1/D.3.2 — `contrato_item` + extrator de planilha** | intocado. Sem elas a curva ABC (pronta) e o X5 não têm o que ler |
| 3 | **Recaptura dos 282 manifests sem `contexto`** | intocado. Não são "limpos", são **não observados** |
| 4 | **G.5 — extrator de ordenador/gestor/fiscal (~8%)** | intocado. Sem responsável, a dosimetria não passa de determinação |

### 5.2 Nascido nesta sessão

- **Completar a série societária**: faltam **22 snapshots** (2023-03 a 2024-12) dos 41 do espelho.
  `PYTHONPATH=. .venv/bin/python -m tools.socios_serie_historica --listar` mostra o que falta;
  ingerir **off-hours** (cada mês são ~600 MB baixados, filtrados por streaming e descartados).
- **Benford `min_n`**: o default 50 rotula 100% das séries benfordianas como não conformes
  (n=100→95%, n=200→64%, n=400→20%, n=800→2%). Catalogado como vício `quantitativos_manipulados`
  com `status="parcial"`, mas **o default não foi alterado** — precisa teste de potência.
- **Dois detectores anti-preditivos** (`corrida_dezembro` lift 0,59 · `fornecedor_dependente` 0,48
  contra base 7,01%) seguem sem decisão: recalibrar, rebaixar a informativo, ou aposentar.
- **Splink** (resolução de entidade) não foi feito. A resolução de CPF segue em **3,8%**, e o CPF
  mascarado da Receita colide ~4%.
- **SpiderFoot** segue instalado, implementado, testado e **sem caller** — o guard
  `elegivel(radar_score >= 50)` está pronto. Ressalva medida: os módulos brasileiros são fracos;
  usar para infra/domínio/e-mail, não para societário.
- **`grafo_poder` ainda liga sócios por nome normalizado** (força 0,10 pela régua do `vinculos.py`).
  O beneficiário final já usa a régua honesta; o grafo do painel não. Migrar.
- **`osint/interposicao`, `osint/timeline`, `osint/patrimonio`** seguem só em CLI.
- **Dedupe de grupo econômico**: `osint/grupo_economico` (nova, com delta de HHI) × `grafo_cartel`
  (antiga, é a que renderiza). Ainda duas implementações.

### 5.3 Dívida que NÃO absorvi

`test_divida_except_pass`: **157 contra teto 153**. Medi no commit de partida (`ace03b90`) e **a
dívida já era 157** — é de outra sessão. Eu introduzi 2 e curei os 2; saldo zero. Absorver teto
alheio em silêncio é como ele cresce.

Também não commitei: `AGENTS.md`, `_SANDBOX/walker_humano.py`, `siafe_agent/llm/groq_explorer.py` —
modificados por outra sessão e deixados intactos.

---

## 6. Como verificar

```bash
# suíte em 4 lotes (a monolítica não fecha em 2 vCPU) — 1.375 + 1.170 + 2.374 passed, 7 skipped
ls tests/*.py tests/*/*.py | sort > /tmp/arqs.txt
.venv/bin/python -m pytest $(sed -n '1,110p'   /tmp/arqs.txt | tr '\n' ' ') -q -p no:randomly
.venv/bin/python -m pytest $(sed -n '111,240p' /tmp/arqs.txt | tr '\n' ' ') -q -p no:randomly
.venv/bin/python -m pytest $(sed -n '241,430p' /tmp/arqs.txt | tr '\n' ' ') -q -p no:randomly

# boot do painel (pageerror é o detector; a aparência da tela não é)
PYTHONPATH=. .venv/bin/python -m tools.painel_boot_check --todas

# eixo de vínculos, sobre dado real
curl -s "http://127.0.0.1:8000/api/osint/serie_societaria"        # 19 meses, 9.113 saídas
curl -s "http://127.0.0.1:8000/api/osint/beneficiario_final?cnpj=12035062000100"
curl -s "http://127.0.0.1:8000/api/osint/parentesco/prevalencia"  # calibração contra a base de hoje
```

---

## 7. Nota de modelo

A sessão inteira correu em **Opus 5**. A diretriz permanente do dono é **Fable 5**
(`/model` → `claude-fable-5`).
