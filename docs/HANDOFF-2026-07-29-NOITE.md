# Handoff — 2026-07-29 (noite) · densidade, vínculos e superfície

> Continuação de `docs/HANDOFF-2026-07-29.md` (manhã). Comece por aqui.
> Branch **`feat/painel-v15-holo`** · **`main` reconciliado e em dia** (fast-forward, sem force-push).
> 24 commits nesta sessão. §4-B e §4-C cobrem as continuações (pendências atacadas após o 1º fecho).

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
  BigQuery vetado por billing. **Os 41 foram ingeridos** (ver §4-B.1): série sem buraco, 19.575 saídas
  de sócio, todas com janela de um mês.
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

## 4-B. Continuação da mesma sessão — pendências atacadas

### 4-B.1 A série societária ficou COMPLETA

**41 snapshots mensais consecutivos, 2023-03 a 2026-07, sem um buraco.** 78.774 vínculos,
**19.575 saídas de sócio**, e — porque a série não tem lacuna — *todas* com `janela_confiavel=1`,
isto é, saída fixada numa janela de um mês. Distribuição: 4.888 saídas em 2023, 5.574 em 2024,
6.137 em 2025, 2.976 em 2026.

Verificado de ponta: para um sócio que saiu entre 2023-06 e 2023-07, `vinculo_na_data` responde
**SIM** em 2023-05-10, **NÃO** em 2023-08-10 e **INDISPONÍVEL** em 2022-05-10 (antes da série).

### 4-B.2 A régua calibrada chegou ao grafo que o usuário vê

`GET /api/grafo` ligava tudo sem força. Medido: **76% das arestas de co-endereço são de PRÉDIO**
(435 de 570) e valiam 0,75 quando valem 0,05 — sobrepeso de 15×. E só **3,8%** dos vínculos de sócio
têm CPF resolvido.

Isso expôs um buraco no vocabulário fechado: a Receita mascara o CPF de todo sócio, logo **94,9% dos
vínculos são nome + seis dígitos centrais**, e nem `mesmo_socio` (0,90, que pressupõe documento) nem
`nome_igual_sem_documento` (0,10, que descarta a máscara) serviam. Entrou
`mesmo_socio_doc_parcial` (0,70), com a colisão medida (~4%) declarada no próprio tipo.
`pago_por` **não** recebe força — pagamento é fato, não inferência de proximidade.

### 4-B.3 Três correções de leitura no produto

- **Benford.** O módulo já media que em n=50 **100%** das séries benfordianas são rotuladas "NÃO
  CONFORMIDADE"; os três caminhos de relatório conferiam apenas `suficiente` (n ≥ 50), o exato limiar
  do erro. Pior: `intel_analise` escrevia "indício de fracionamento" **dentro do parecer**. O gate
  virou `mad_confiavel`; abaixo do limiar sai **NÃO AFERÍVEL**. O texto introdutório, que ensinava
  "n<50", foi trocado pela tabela medida.
- **Lift.** Os dois detectores anti-preditivos (`corrida_dezembro` 0,59 e `fornecedor_dependente`
  0,48 contra base 7,01%) seguiam com faixa **MÉDIO** no PDF. Rebaixados a **INFORMATIVO** — não
  aposentados: o padrão fático segue relevante, o que sai é a pretensão de graduar risco. Duas
  assimetrias deliberadas: lift alto **não** promove faixa, e circular (`radar_risco` 12,98) não
  promove nem rebaixa.
- **Grupo econômico.** Havia duas medições, e a que renderizava (alimenta o J1, peso 0,9, e a §1-H)
  **subestimava**: na SECID dava HHI 0,3254 por grupo e 53,27% de share, contra 0,4064 e 62,1% da
  outra. Três causas verificadas: unia por nome puro, media sobre o **espelho TFE** (contra a regra
  absoluta nº 2) e não tinha guarda de fan-out. Agora delega, com o contrato preservado campo a
  campo. O J1 sobre a SECID passou a reportar **62,12% em 9 CNPJs sob 8 raízes** — o achado
  documentado.

### 4-B.4 I.1.2 — telefone e e-mail já estavam em disco

`data/receita_estab.db` tem **6.171.766 estabelecimentos** com telefone (83,9%) e e-mail (69,0%),
indexados, sem consumidor. Isso destravou duas arestas de força 0,70 e 0,80 que o grafo nunca teve.
Todos os guardas foram medidos antes de escritos: os cinco telefones mais compartilhados do país são
`00` (129.152 empresas), `210`, `2122222222`, `2199999999`; 43 telefones ligam mais de mil empresas
cada; e os cinco e-mails campeões são de contabilidade (`maismei` 17.665, `contabilizei` 16.846) — que
viram `mesmo_contador` (0,30), não `mesmo_email` (0,80). Um falso positivo real foi corrigido: matriz
e filial da mesma raiz dividem telefone por definição.

### 4-B.5 E.0.1 — e os dois artefatos que quase viraram achado

O coletor de licitantes municipais do TCE-RJ existia, era testado com `buscar` injetado e **nunca
havia rodado contra a API** — a tabela não existia em nenhum banco, apesar de o handoff da manhã
registrar "E.0 ✅ 630 certames". Rodado: **13.021 certames, 34.659 perdedores nominados, 17.037 nomes**.

Dois artefatos apareceram na ponte para o detector, ambos de ler ausência como fato:

1. **Nominação parcial lida como afunilamento.** O J4 confirmou "forte" em Teresópolis 2244/2025 com
   "129 inscritos ⇒ 1 classificado". Os nominados eram **um**: o vencedor. Os outros 128 não foram
   desclassificados — não foram nominados.
2. **`PERDEDOR` lido como INABILITADO.** A API não distingue inabilitação de derrota no preço. O J4
   mede seletividade na habilitação; mapear um no outro faria toda licitação normal (71 licitantes, 1
   vencedor) parecer afunilamento.

Conclusão medida: a fonte **não** alimenta o funil do J4 nem o QSA do E.3.2 (que exige CNPJ; a API traz
só o nome). Sobre 400 certames o J4 sai `nao_avaliavel` em 400, e é a resposta certa. O que ela
sustenta é `licitantes_inscritos` declarado — e com ele **3.782 certames (29,0%) de licitante único
apurável**, que antes era inferido da ausência de registro.

### 4-B.6 O teto da fonte para atas, medido

O coletor de atas devolvia `atas_gravadas: 0` sem motivo (dois `continue` sem contador).
Instrumentado, o diagnóstico saiu numa execução: dois de três descartes estavam **certos** ("ATA DE
REGISTRO DE PREÇOS" e "MINUTA DE ATA" não são ata de sessão), e o gargalo é a montante — sobre 150
certames, **8,7% têm documento com título de ata**, e a maioria é minuta. A distribuição real:
168 Edital, 47 Outros Documentos, 8 Termo de Referência, 5 ETP, 4 Minuta de Ata, 2 Minuta de
Contrato, 1 DFD. **Não existe tipo "Ata de Sessão" na taxonomia do PNCP.** É limite de fonte.

---

## 4-C. Segunda continuação — o que destravou os eixos que devolviam zero

### 4-C.1 Resolução nome → CNPJ: era CATÁLOGO, não técnica

Os perdedores do TCE-RJ vêm por **nome**, e sem CNPJ não há QSA. A primeira medição, contra os
catálogos que a casa já tinha (75.891 nomes), deu **13,9%** de acerto com **0,3%** de ambiguidade — e
esse par de números diz tudo: quando o nome está no catálogo, ele resolve limpo; o problema é que 86%
dos licitantes municipais nunca venderam ao Estado. Não era caso de biblioteca de record linkage: era
caso de catálogo maior. O dump `Empresas*.zip` (1,3 GB, o país inteiro) estava em disco desde sempre.
Uma passada por streaming: **60,3%** (12.738 resolvidos, 2.215 ambíguos com CNPJ **NULO** declarado).

### 4-C.2 E.3.2 destravado — 42 pares com sócio em comum

    coleta TCE-RJ ................ 15.436 certames · 82.941 perdedores
    resolução nome → CNPJ ........  60,3%
    vencedor E perdedora resolvidos  5.220 certames
    com QSA nos dois lados ........  4.074   ← universo real
    pares com sócio em comum ......     42, em 31 certames (0,76%)

**0,76% é a marca de um sinal que discrimina.** Três ressalvas viajam com o achado, e a principal veio
de olhar um certame real (Angra dos Reis, 45 participantes): em **pregão multi-item a MESMA empresa é
vencedora de um item e perdedora de outro**, e a fonte não publica o item — o veredito é
`indicio_a_confirmar_no_item`, nunca fechado.

### 4-C.3 SpiderFoot ganhou caller — e a recusa que o torna utilizável

Estava parado porque recebe domínio e a casa não tinha o campo; passou a ter com o I.1.2. Medido
sobre os **4.258.994 e-mails do dump inteiro**: **87,3% são de provedor livre**, só 12,7% têm domínio
próprio. Logo, **não ter domínio próprio não é sinal de fachada** — é a norma de sete em cada oito
empresas. Sem domínio o resultado é INDISPONÍVEL com `score=None`; footprint vazio de verdade
(domínio existe, scan não achou nada) segue valendo 1,0.

Detalhe de método: a primeira medição, por `LIMIT 400000`, deu 83,2%; a de `LIMIT 100000` deu 59,8%.
`LIMIT` sem ordenação pega fatia contígua por rowid. **Denominador errado é pior que ausente** —
`cobertura_dominio` passou a contar.

### 4-C.4 Interposição e patrimônio saíram do CLI

E com eles um defeito latente: `_socios_da_empresa` fazia `dict(row)` assumindo `sqlite3.Row`
configurado pelo chamador — nunca atingido porque nunca teve chamador. A primeira correção setava
`con.row_factory`, o que é **efeito colateral na conexão do chamador** e mudou o parecer do Lex.
Trocada por montar o dict pelas colunas nomeadas.

### 4-C.5 O snapshot do Lex dizia OFFLINE e dependia da rede

`investigacao_dd` consultava o provider de cadastro pela internet quando `cadastral is None` — o
único caminho do módulo que saía para fora, e sem como desligar. O golden tinha sido gravado **com**
rede. Entrou `JFN_SEM_REDE`, e o golden foi regravado no estado offline de verdade. Golden que depende
de conectividade é moeda, não teste.

### 4-C.6 Os três cérebros aprenderam o sistema

- **Vault**: `aprendizados/CATALOGO-DE-FALHAS.md` — as **11 famílias** de falha já reportadas, cada
  uma com a **assinatura** que a denuncia e a regra que a impede. E `COMO-O-SISTEMA-FUNCIONA.md` —
  manual único: peças, invariantes, onde vive cada dado, régua de força, o que rodar antes de dizer
  "pronto". Ligados em `00-INDEX`, `MOC-Aprendizados` e `log.md`.
- **GitNexus**: reindexado — **39.299 símbolos · 61.688 relações · 1.233 clusters**
  (era 38.500/60.335/1.189).
- **graphify**: as notas estão no vault e linkadas dos hubs, mas o **grafo não foi reconstruído** — o
  CLI só faz `path`/`explain`/`diagnose`; o build é por subagentes via skill. Fica como próxima ação.

---

## 5. PENDENTE

### 5.1 Herdado e ainda aberto (ordem de valor por esforço)

| # | O quê | Estado |
|---|---|---|
| 1 | **E.0.1 — ampliar coleta de propostas** | ⚠️ PARCIAL (ver §4-B.5). 13.021 certames municipais e 34.659 perdedores coletados; 3.782 com licitante único apurável. Mas o E.3.2 segue bloqueado: a fonte traz NOME, não CNPJ. Falta resolução de entidade |
| 2 | **D.3.1/D.3.2 — `contrato_item` + extrator de planilha** | intocado. Sem elas a curva ABC (pronta) e o X5 não têm o que ler |
| 3 | **Recaptura dos 282 manifests sem `contexto`** | intocado. Não são "limpos", são **não observados** |
| 4 | **G.5 — extrator de ordenador/gestor/fiscal (~8%)** | intocado. Sem responsável, a dosimetria não passa de determinação |

### 5.2 Nascido nesta sessão

- ✅ **Série societária COMPLETA** — 41 snapshots, 2023-03 a 2026-07, sem buraco (§4-B.1).
- ✅ **Benford** — o gate virou `mad_confiavel` nos três caminhos; abaixo do limiar sai NÃO AFERÍVEL
  (§4-B.3). O `min_n` do módulo segue em 50 de propósito: mexer nele mudaria em silêncio cinco
  caminhos, e o defeito era de LEITURA, não de corte.
- ✅ **Dois anti-preditivos** — rebaixados a INFORMATIVO, com o lift medido impresso no documento.
- ✅ **`grafo_poder`** — migrado para a régua calibrada (§4-B.2).
- ✅ **Dedupe de grupo econômico** — `grafo_cartel` delega; o J1 sobre a SECID passou de 53,27% para
  62,12% de share (§4-B.3).
- ✅ **I.1.2** — telefone e e-mail consumidos, com os guardas medidos (§4-B.4).

Segue aberto:

- ✅ **Resolução nome → CNPJ** — 60,3% pelo catálogo nacional (§4-C.1). **Não** foi preciso Splink.
  Segue aberto o outro lado: resolver **CPF de sócio** (mascarado, colisão ~4%) continua em 3,8%, e
  aí sim record linkage probabilístico é o caminho.
- 🔴 **Os 6.188 nomes não encontrados** (29,3%) — grafia divergente do registro. Aqui, sim, casamento
  por semelhança tem o que fazer; com o cuidado de que 2.215 já são ambíguos no casamento EXATO.
- 🔴 **Ata de sessão** — a única fonte do funil de habilitação (o TCE-RJ não distingue inabilitação de
  derrota no preço; o PNCP publica ata em 8,7% dos certames, quase toda minuta). Caminhos restantes:
  SEI (arquivo já em disco), DOERJ, portais municipais.
- ✅ **SpiderFoot** — caller feito (§4-C.3), com a recusa que impede acusar 87,3% do país.
- ✅ **`osint/interposicao` e `osint/patrimonio`** — rota e tela (§4-C.4). `osint/timeline` segue só
  em CLI: precisa de uma linha de eventos montada, e o caller natural é o dossiê.
- 🔴 **graphify do vault não reconstruído** — as notas novas estão lá e linkadas dos hubs, mas o grafo
  não as tem. O CLI só consulta; o build é por subagentes via skill.
- ✅ **Coleta TCE-RJ** — 2024, 2025 e 2026 dentro (**15.436 certames**). 2023 devolve vazio na API.

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
