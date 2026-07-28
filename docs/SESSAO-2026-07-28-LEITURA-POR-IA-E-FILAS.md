# Sessão 2026-07-28 — Leitura de processo por IA, filas de captura e sete inflações

> Documento de fechamento. Registra **o que passou a existir**, **o que foi medido** e — com o
> mesmo peso — **o que estava errado e foi corrigido**, inclusive erros meus. Um relatório que
> só lista acertos não serve para a próxima sessão decidir em que confiar.

---

## 1. O que passou a existir

### 1.1 Leitura de processo por IA, com o código no comando

| módulo | papel |
|---|---|
| `sei/dossie_fracionado.py` | planeja a leitura, fraciona **por documento**, consolida em seções |
| `tools/sei_dossie_md.py` | executa, com checkpoint, retomada e troca de modelo |
| `knowledge/moldura_juridica.py` | o direito administrativo brasileiro dentro do prompt |
| `sei/indicios_dossie.py` | réguas de código sobre o texto já citado |

**A divisão que se firmou:** a IA lê o documento (insubstituível), o **código** agrupa e julga
(determinístico, sem cota, sem alucinação, sem perder citação).

Medição do acervo que orienta tudo: mediana **6.295 tokens** — 97% dos processos cabem
inteiros. A cauda vai a 1,85 milhão em 291 documentos. Fracionar todo processo seria desperdício;
não fracionar a cauda seria truncamento silencioso.

### 1.2 As três filas que não existiam

| fila | comando | tamanho |
|---|---|---|
| **captura** — pago, zero linhas lidas | `--fila-captura` | 27 processos · R$ 25,9 mi |
| **recaptura** — ≥30% dos documentos cegos | `--fila-recaptura` | 129 processos · 4.568 documentos |
| **processo-pai** — contratação ausente | `--fila-pais` | 384 pais · 383 filhos · R$ 141,1 mi |

> **Processo lido pela metade é PIOR que não lido: parece analisado.** Um processo saiu da
> análise com "0 indícios" e era o primeiro da fila de recaptura, 100% cego.

### 1.3 Cobertura de detecção e responsabilização

- **Varredura por certame** — cobertura de detectores de **7% para 62%** (751 de 1.200 avaliações).
- **ID funcional** de responsável: **18% → 46%** (182 de 392 agentes).
- **Requisição formal**: 71 minutas por órgão, 77 processos sob restrição.
- **`/responsaveis <processo>`**: rota + capacidade no contrato do Yoda (2.4.0).
- **Fila de fracionamento**: 1.110 grupos, dos quais **231 priorizados** pelo discriminante.

### 1.4 Infraestrutura de IA

- **Catálogo vivo** de modelos `:free` — literal em código apodrece calado.
- **Banco de provas** (`tools/bench_modelos.py`) — 4 provas do nosso domínio, 3 delas medindo
  **honestidade**, não capacidade.
- **Diagnóstico do fallback** sob o ambiente do cron: **5 degraus vivos**.

---

## 2. Sete inflações corrigidas, e o método que as pegou

| medida | antes | depois | causa |
|---|---|---|---|
| juros e multa | R$ 3.995.001,04 | **R$ 65.681,99** | somava todo valor da linha; depois contava 2× o mesmo lançamento |
| fila de captura | R$ 2,3 bi | **R$ 25,9 mi** | os 3 maiores eram Fundo de Equalização, RIOPREV e Folha |
| processos-pai | R$ 251,6 mi | **R$ 141,1 mi** | filho que cita 2 pais contado 2× |
| P1 especificação dirigida | 106 de 150 certames | **1 crítico + 82 triagem** | homônimo, e evidência que não escalava com o palheiro |
| vícios "afirmados" pela leitura | 27 | **0** | o modelo respondia o checklist negativamente |
| detectores com teste | "23 de 31" | **6** | `"C"` casava como substring de quase todo nome |
| fila de fracionamento | 1.175 | **1.110** | entidade pública abreviada escapava do filtro |

**O método é sempre o mesmo:** o número parece medido, tem casas decimais, e está errado por
uma ordem de grandeza. Estranhar e conferir a fonte.

---

## 3. Falhas silenciosas que a sessão desenterrou

### 3.1 HTTP 200 com corpo de erro
`raise_for_status()` não protege. O `KeyError` escapava do laço de retry (não é `HTTPError` nem
`RuntimeError`), **zero retentativas**, e derrubava o provedor inteiro em cooldown por um erro
**transitório** de capacidade. Sete sítios repetiam o mesmo parse cru.

### 3.2 Lote truncado apresentado como leitura completa
6 de 7 lotes terminavam no meio de uma frase; um trazia 98 caracteres para 37 documentos. O
`finish_reason == "length"` estava disponível e era ignorado. Depois do conserto, o mesmo dossiê
foi de 230 para **385 citações**.

### 3.3 Checkpoint que misturava planos
Indexado só pelo número do lote. Trocar de modelo refaz o plano — e a retomada colou extrações
de ~57 documentos num dossiê que declarava cobrir 291. O log dizia `retomando: 16 de 4 lote(s)`.

### 3.4 SLO que vigiava o log, não o dado
A coleta SIAFE ficou **10 dos últimos 30 dias sem produzir uma linha**, com o SLO verde: ele
olhava o mtime do log, e o runner escreve o log mesmo quando não traz nada. O sintoma apareceu
antes no vault — dois pares de dias com o mesmo número **ao centavo**.

### 3.5 `INSERT OR REPLACE` só acrescenta
Melhorar o filtro não limpava a fila: 65 linhas obsoletas permaneciam. A retirada agora é
escopada por exercício e geração — nunca o `DELETE` global que truncou `ob_redflag`.

---

## 4. Erros meus, registrados

**O invariante do ITERJ.** Concluí que a UG 133100 "mudou de órgão" e cheguei a editar o
`CLAUDE.md`. Estava errado: as Ordens Bancárias rotulam a UG com o **órgão superior**, e o
`ugs.py` já registrava isso desde junho. Revertido. O que restou foi um módulo que mede o que de
fato varia — a **subordinação** — e cujo aviso diz que a série **é** somável.

**O medidor que rebaixava por cota.** A 1ª versão do banco de provas somava 0 para prova que
estourou por 429 — o `INDISPONÍVEL ≠ 0` cometido dentro da ferramenta feita para medir. Três
modelos com 0,0 viraram 100,0 depois do conserto.

**O alarme falso do captcha.** `arvore_carregou` e `captcha_resolvido` nascem `False` e o
caminho de leitura `cracked` nunca os toca. 200 de 200 amostrados eram leituras bem-sucedidas.

**Dois falsos alarmes de pente fino.** As notas de OSINT no vault existiam (procurei na pasta
errada), e a chave `"litro"` duplicada em `medida_item` não escondia bug nenhum.

---

## 5. O que continua aberto

- **Análise em série**: 6 de 2.055 processos. Código pronto e retomável; falta tempo de execução.
- **Migração para a VM-2**: proposta escrita, execução pendente do dono.
- **Banco de provas não mede documento longo** — as provas são curtas. O piso de parâmetros do
  perfil `documento` é salvaguarda por tamanho declarado, não por desempenho medido.
- **16% das pesquisas OSINT** terminam com resposta não-parseável do LLM (degradação honesta,
  mas melhorável).

## 6. O que NÃO está aberto, ao contrário do que eu vinha dizendo

**"As IAs pesquisarem na internet e aprenderem" já existe e roda no cron.**
`tools/lex_pesquisa_internet.py` extrai as dúvidas do sweep, pesquisa (web_research + Querido
Diário + mídia adversa), julga via LLM se a evidência resolve ou agrava, e grava o aprendizado no
banco **e** no vault (13 notas em `~/vault/aprendizados/pesquisa-internet/`). Eu vinha listando
como pendente por não ter verificado.

---

**Verificação:** 833 testes verdes. `docs/PLAYBOOK-SEI.md` atualizado com as três seções novas e
quatro proibições. Grafo do segundo cérebro em 2.091 nós.
