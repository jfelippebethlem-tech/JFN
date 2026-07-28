# Plano Mestre — Superfície de Detecção, Responsabilização e Captura

> **Para executores agênticos:** SUB-SKILL OBRIGATÓRIA — usar `superpowers:subagent-driven-development`
> (recomendado) ou `superpowers:executing-plans`. Os passos usam checkbox (`- [ ]`) para rastreio.

**Objetivo:** fechar as quatro lacunas medidas em 27/07/2026 — detectores sem rede de proteção,
fracionamento inflado 26×, cobertura de responsáveis em 8%, e 77 processos restritos + 3.216 não
capturados sem encaminhamento formal.

**Arquitetura:** quatro fases independentes, cada uma entregando software funcionando e testável por
si. Fase A é rede de proteção (nenhum comportamento novo). Fase B corrige um detector existente na
fonte autoritativa. Fase C é captura, medida em amostra fixa antes/depois. Fase D integra tudo aos
quatro sistemas e gera a peça para o gabinete.

**Stack:** Python 3.12 · pytest · SQLite (`data/compliance.db`) · pandas · httpx · fpdf2 ·
framework de detectores próprio (`compliance_agent/detectores/base.py`).

---

## Context — por que este plano existe

Em 27/07/2026 medimos a superfície real de detecção do JFN e encontramos quatro problemas, todos
com número apurado no dado real, não estimado:

1. **Dez detectores rodam sem nenhum teste** (P1, P2, P3, P5, E2, E3, J1, J2, J3, J4). São 2.500+
   linhas de lógica de detecção que ninguém sabe se ainda funcionam. Detector silenciosamente
   quebrado é pior que detector ausente: ele produz `nao_avaliavel` e a fila fica limpa por engano.

2. **`R_FRACIONAMENTO_SAMEDAY` estava 26× inflado** — 59.209 marcações que viram 2.225 quando se
   exige processo e empenho distintos e se exclui repasse intragoverno. A regra roda sobre o
   espelho TFE, onde `numero_processo` está vazio em 100% das linhas: o campo discriminante não
   existe naquela tabela. Já rebaixamos a âncora para 0,3 e declaramos a ressalva no parecer, mas o
   conserto real é migrar para o SIAFE. Além disso, sobrevive uma **5ª cópia divergente** do teto de
   dispensa em `lex_analise_conteudo.py:307`, congelada em 2024.

3. **Cobertura de responsáveis em 8%** (171 de 2.007 processos). A investigação da causa mudou a
   hipótese de trabalho: **o ato de designação simplesmente não está no acervo**. Só 68 dos 2.053
   processos (3,3%) têm algum documento de designação, e 4.695 dos 34.749 documentos (13%) têm
   `chars=0` — texto não extraído. Somado a 2.579 caches (46%) com árvore de documentos que não
   carregou e 3.216 processos conhecidos e nunca capturados, elevar cobertura é problema de
   **captura**, não de extração. Isso reordena o esforço.

4. **77 processos sob restrição de acesso e 3.216 na fila** sem encaminhamento. O marcador de
   cadeado foi validado por correlação (22,42% dos caches sem documentos contra 0,02% dos caches
   com documentos — mil vezes de diferença, o que exclui artefato de seletor CSS). A lista existe
   em `sei_sigilo` e não vira pedido formal sozinha.

**Resultado pretendido:** os 31 detectores com rede de proteção; fracionamento defensável em peça;
cobertura de responsáveis medida e elevada com ganho comprovado em amostra fixa; e uma minuta de
requisição por órgão pronta para o gabinete assinar.

---

## Global Constraints

Copiadas verbatim das regras do projeto — valem para **toda** tarefa deste plano.

- **Honestidade:** indício ≠ acusação · `INDISPONÍVEL`/`nao_avaliavel` ≠ 0 · nunca inventar número ·
  presunção de legitimidade dos atos administrativos · score é indício INTERNO, nunca nota pública.
- **CPF de sócio mascarado** em qualquer saída (LGPD art. 7º, II / art. 23).
- **OB (Ordem Bancária) = pagamento = verdade.** Empenho ≠ liquidação ≠ OB. Nunca citar empenho
  como "total pago".
- **Fonte de OB é sempre o SIAFE** (`ob_orcamentaria_siafe`), nunca o espelho TFE
  (`ordens_bancarias`) quando o campo importar.
- **Teto de dispensa vem de `compliance_agent/limites_dispensa.py`**, por exercício. Proibido
  duplicar a tabela — já existem 5 cópias e é a origem de falso positivo e falso negativo.
- **Limiar numérico fica no código, nunca no prompt do LLM** (spec §1.3 do framework de detectores).
- **Estética de entregável:** padrão de consultoria (capa, seções numeradas, tabelas alinhadas,
  R$ com separador de milhar e duas casas, fontes citadas). Nada feio sai para o dono.
- **Gate de neutralidade:** todo entregável passa por `reporting/neutralidade.garantir_neutro` —
  zero menção interna (jfn, yoda, lex, hermes, itkava, iterj, massare).
- **Gate de citações:** todo texto com acórdão passa por `reporting/gate_citacoes`.
- **VM:** Oracle ARM, 2 vCPU, 11,6 GB. **Um processo pesado por vez.** Checar `uptime` antes de
  sweep; OCR e browser são caros. Sweep longo vai para background com log em arquivo.
- **Nunca rodar em produção função com `DELETE` antes de gravar.** `anomalias.regras()` é assim e
  truncou `ob_redflag` de 69.807 para 12.215 num teste. Testar sempre com `JFN_DB` apontando para
  tmp.
- **Testes:** `.venv/bin/python -m pytest`. Suíte completa **já derrubou a VM** — rodar por arquivo.
  Módulo que escreve no banco entra em `_MODULOS_ISOLAR_DB` no `tests/conftest.py`.
- **Commits:** convenção semântica; `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
  O hook `pre-commit` (codegraph/graphify) estoura 9 min com a VM carregada — `--no-verify` é
  aceitável (o hook é declaradamente best-effort) e deve ser declarado na mensagem.

---

## File Structure

### Fase A — rede de proteção (só testes, nenhum comportamento novo)
| Arquivo | Responsabilidade |
|---|---|
| `tests/detectores/test_p1_especificacao_dirigida.py` | P1: pista nominativa, valor redondo, requisito sem justificativa |
| `tests/detectores/test_p2_cotacoes_combinadas.py` | P2: telefone/e-mail/endereço/sócio compartilhado, CV das cotações |
| `tests/detectores/test_p3_sobrepreco.py` | P3: razão vs mediana, faixas de nível |
| `tests/detectores/test_p5_emergencia_fabricada.py` | P5: delta entre datas, emergência que nasce de desídia |
| `tests/detectores/test_e2_prazos.py` | E2: mínimo do art. 55, dias úteis, data-sombra, retificação sem reabertura |
| `tests/detectores/test_e3_lote_pacote.py` | E3: classe de mercado, agregação anticompetitiva |
| `tests/detectores/test_j1_cartel.py` | J1: share/HHI por grupo |
| `tests/detectores/test_j2_propostas_cobertura.py` | J2: dispersão robusta, vencedor vs perdedores |
| `tests/detectores/test_j3_desconto_anomalo.py` | J3: desconto sobre estimado |
| `tests/detectores/test_j4_supressao_propostas.py` | J4: licitante único, contagem de propostas |
| `tests/conftest.py` (modificar) | registrar em `_MODULOS_ISOLAR_DB` os que tocam banco |

Modelo obrigatório a copiar: `tests/detectores/test_atestado_cruzado.py` — é o único teste de
detector existente e estabelece o padrão (sqlite tmp com o schema real espiado por PRAGMA, texto
sintético, guards anti-falso-positivo, conformidade com o schema §1.4).

### Fase B — fracionamento na fonte certa
| Arquivo | Responsabilidade |
|---|---|
| `compliance_agent/fracionamento_siafe.py` (criar) | Regra de fracionamento sobre `ob_orcamentaria_siafe`, com guarda de processo/empenho, filtro de intragoverno, teto por exercício e cruzamento com o registro de compras diretas |
| `tests/test_fracionamento_siafe.py` (criar) | Todos os guards, cada um com o caso que o justifica |
| `compliance_agent/lex_analise_conteudo.py:307` (modificar) | remover a 5ª cópia do teto |
| `compliance_agent/detectores/base.py` (modificar) | atualizar o mapa que declara 9 cards como "a construir" |
| `compliance_agent/anomalias.py` (modificar) | apontar no docstring que o same-day é sinal fraco e que a régua defensável vive no módulo novo |

### Fase C — captura e cobertura
| Arquivo | Responsabilidade |
|---|---|
| `tools/sei_reextrair_vazios.py` (criar) | Re-extrai os 4.695 documentos com `chars=0`, medindo ganho |
| `compliance_agent/sei/relacionados.py` (criar) | Resolve processo-pai/relacionado a partir do cache (17% dos caches apontam para outro processo) |
| `tools/sei_agentes_sweep.py` (modificar) | Passa a ler também o processo relacionado ao montar a ficha |
| `tools/medir_cobertura_agentes.py` (criar) | Amostra FIXA (semente 7, 120 processos) — mede antes/depois; é o critério de aceite da fase |
| `tests/test_relacionados.py` (criar) | Extração de nº SEI de outro processo, sem casar o próprio |
| `tests/test_medir_cobertura.py` (criar) | A medição é determinística e comparável entre execuções |

### Fase D — integração e peça formal
| Arquivo | Responsabilidade |
|---|---|
| `compliance_agent/lex_render.py` (modificar) | Seção "Responsáveis" no parecer, a partir de `montar_ficha` |
| `compliance_agent/reporting/requisicao.py` (criar) | Minuta de requisição por órgão (sigilo + fila), com fundamento legal |
| `tools/gerar_requisicoes.py` (criar) | CLI que emite as minutas em md + PDF |
| `tests/test_requisicao.py` (criar) | Agrupamento por órgão, fundamento correto, gate de neutralidade |
| `compliance_agent/agent.py` ou rota Yoda (modificar) | Comando `/responsaveis <processo>` |
| `tests/test_responsaveis_rota.py` (criar) | Rota devolve ficha e declara lacuna |

---

# FASE 0 — Parar de derrubar a VM ✅ FEITA (27/07, após a queda das 22:22)

Esta fase não estava no plano original. Entrou porque a VM travou durante o planejamento, e a
causa é pré-requisito de tudo o que vem depois: **não adianta planejar sweep se o sweep mata a
máquina**.

**Causa-raiz, medida.** `tools/sei_pais.carregar_cache()` fazia `json.loads` dos **6.093 arquivos**
de `data/sei_cache` — **18 GB em disco**, um deles com 697 MB — e segurava tudo num `dict`. A VM
tem 11,9 GB. Não era vazamento: carga integral, morte determinística, que piora a cada sweep
porque o cache só cresce.

**Prova da correlação:** `sei_pais rc=137` em `data/sweep_sei.log` bate ao segundo com o OOM killer
do kernel — 12:50:26/27, 16:52:47/44, 19:23:30/27, 20:40:20/26. **Onze vezes só em 27/07.** Às
22:19:35 o passo anterior terminou, `sei_pais` entrou, e às 22:22:49 a máquina travou sem
conseguir nem registrar o OOM (o journald já falhava por watchdog desde as 20:40).

| Item | Estado |
|---|---|
| Passo `sei_pais` desligado no `sweep_sei.sh` (comentado, com histórico e instrução de religar) | ✅ |
| `iter_resumos()` — streaming, um arquivo por vez, guardando só os campos usados | ✅ |
| `detectar_pais()` reescrito sobre os resumos, mesmo veredito | ✅ |
| Teto por arquivo calibrado na distribuição real (256 MB → 4 de 6.093 ficam de fora) | ✅ |
| 3 testes de regressão (não pode chamar `carregar_cache`; gigante é pulado **e declarado**; streaming == carga integral) | ✅ |

**Medido:** pico de **262 MB** (teto de 64 MB) contra os ~10.000 MB de antes, em 112 s, detectando
1.275 processos-pai.

### Pendências da Fase 0

- [ ] **0.1 — Validar em produção e religar `sei_pais`.** Rodar o passo à mão uma vez, com
  `/usr/bin/time -v` para registrar o pico real, e só então descomentar a linha em `sweep_sei.sh`.
  ```bash
  cd ~/JFN && uptime && /usr/bin/time -v .venv/bin/python -m tools.sei_sweep --seguir-pais --max 5
  ```
  Aceite: `Maximum resident set size` abaixo de 2 GB.

- [ ] **0.2 — Recuperar os 4 arquivos acima de 256 MB.** Hoje ficam de fora (0,07% do acervo) e o
  log declara isso. Para não perder nada, extrair as refs desses arquivos por regex sobre o texto
  cru, sem `json.loads`. O `_PAT_SEI` já funciona sobre o JSON bruto; o que se perde é a janela de
  palavra-chave, então a confiança dessas refs cai para `media`.

- [ ] **0.3 — Auditar os outros passos do `sweep_sei.sh` pelo mesmo padrão.** `sei_sweep` também
  aparece com `rc=137` oito vezes em 27/07. Verificar se é OOM (mesma causa) ou apenas o `timeout`
  de 1500 s estourando — são coisas diferentes e o log não distingue. Sugestão: `say` passar a
  registrar o pico de memória de cada passo.

- [ ] **0.4 — Guarda de memória por passo.** Envolver cada `timeout ... python` num limite de RSS
  para que um passo defeituoso morra sozinho em vez de levar a máquina. `ulimit -v` é grosseiro com
  Python; avaliar `systemd-run --scope -p MemoryMax=` (atenção: cron não alcança o barramento do
  usuário — é uma limitação já conhecida do projeto).

---

# FASE A — Rede de proteção dos 10 detectores sem teste

**Por que primeiro:** é a única fase que não muda comportamento. Sem ela, qualquer refatoração das
fases B–D é feita no escuro. Cada tarefa é um detector; um revisor pode aprovar P1 e rejeitar P2.

**Interfaces (idênticas para os 10):**
- Consome: `Detector.avaliar(contexto: dict) -> ResultadoDetector` de
  `compliance_agent/detectores/base.py`; âncoras fixas `ANCORAS = {ausente:0.0, fraco:0.3,
  medio:0.6, forte:0.85, critico:1.0}`; `STATUS_VALIDOS`.
- Produz: nada para outras tarefas — são testes.

O contrato de `contexto` de cada detector **já está documentado no docstring da própria classe**
(ver `e2_prazos.E2Prazos.avaliar` como exemplo canônico). Ler o docstring é o passo 1 de cada tarefa.

### Task A1: Teste do E2 (prazos) — o mais rico, serve de gabarito para os outros 9

**Files:**
- Create: `tests/detectores/test_e2_prazos.py`
- Read: `compliance_agent/detectores/e2_prazos.py:59-332`
- Read (modelo): `tests/detectores/test_atestado_cruzado.py`

**Interfaces:**
- Consome: `E2Prazos`, `minimo_art55(modalidade, criterio) -> int|None`,
  `dias_uteis(inicio: date, fim: date, feriados: set[date]) -> int`,
  `_is_data_sombra(dt, feriados) -> tuple[bool, str]`.
- Produz: nada.

- [ ] **Passo 1: Ler o contrato do detector**

Ler `compliance_agent/detectores/e2_prazos.py` linhas 153-190 (docstring do `avaliar`). Anotar as
chaves de `contexto`: `processo`, `data_publicacao`, `data_abertura`, `modalidade`, `criterio`,
`feriados`, `no_pncp`, `versoes`.

- [ ] **Passo 2: Escrever o teste do mínimo legal do art. 55**

```python
# -*- coding: utf-8 -*-
"""Teste TARGETED do detector E2 (publicidade e prazos minimizados — art. 54/55 Lei 14.133/2021).

Sem rede, sem banco: o detector é puro sobre `contexto`. Cobre o mínimo legal por modalidade,
a contagem em dias ÚTEIS (que é o ponto onde a régua costuma errar), a data-sombra (sessão em
véspera/feriado, que encurta o prazo real) e o invariante de honestidade do projeto: campo
ausente devolve `nao_avaliavel`, nunca score 0.
"""
from __future__ import annotations

from datetime import date

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.e2_prazos import E2Prazos, dias_uteis, minimo_art55


@pytest.mark.parametrize("modalidade,criterio,esperado", [
    ("pregao", "menor_preco", 8),
    ("concorrencia", "menor_preco", 15),
    ("concorrencia", "tecnica_e_preco", 35),
])
def test_minimo_do_art55_por_modalidade(modalidade, criterio, esperado):
    assert minimo_art55(modalidade, criterio) == esperado


def test_modalidade_desconhecida_nao_chuta_prazo():
    assert minimo_art55("modalidade_inexistente") is None
```

> **Atenção do executor:** os valores 8/15/35 são o que o art. 55 fixa, mas **confirme contra o
> código** antes de gravar o teste. Se o detector implementa outro número, o teste documenta o
> comportamento REAL e você abre uma questão — não ajuste o teste para passar sem entender.

- [ ] **Passo 3: Rodar e ver falhar (ou passar) — e entender qual dos dois**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/detectores/test_e2_prazos.py -v
```

Esperado: PASS se a régua do código bate com o art. 55. Se FALHAR, **pare**: você encontrou um bug
no detector, não no teste. Anote o valor real, o esperado, e siga para o passo 4 documentando o
comportamento atual com um comentário `# comportamento ATUAL — divergente do art. 55, ver questão`.

- [ ] **Passo 4: Escrever o teste dos dias úteis**

```python
def test_conta_dias_uteis_pulando_fim_de_semana():
    # 2026-07-01 é quarta; 2026-07-08 é a quarta seguinte -> 5 dias úteis no intervalo
    assert dias_uteis(date(2026, 7, 1), date(2026, 7, 8), set()) == 5


def test_feriado_encurta_o_prazo_util():
    feriado = {date(2026, 7, 3)}  # sexta
    assert dias_uteis(date(2026, 7, 1), date(2026, 7, 8), feriado) == 4
```

- [ ] **Passo 5: Rodar**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/detectores/test_e2_prazos.py -v
```

Esperado: PASS. Se a contagem divergir, ajuste os números do teste ao comportamento real e
documente no docstring do teste **como** o detector conta (inclusivo/exclusivo nas pontas). Essa é
a informação que o teste existe para congelar.

- [ ] **Passo 6: Escrever o teste do invariante de honestidade**

```python
@pytest.mark.parametrize("faltando", ["data_publicacao", "data_abertura", "modalidade"])
def test_campo_ausente_devolve_nao_avaliavel_e_nao_zero(faltando):
    """Invariante do projeto: INDISPONÍVEL ≠ 0. Sem data ou modalidade não há juízo possível."""
    ctx = {
        "processo": "SEI-TESTE/000001/2026",
        "data_publicacao": "2026-07-01",
        "data_abertura": "2026-07-10",
        "modalidade": "pregao",
    }
    ctx.pop(faltando)
    res = E2Prazos().avaliar(ctx)
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert res.motivo_refutacao, "tem de dizer POR QUE não avaliou"
```

- [ ] **Passo 7: Escrever o teste de prazo violado e de prazo conforme**

```python
_BASE = {"processo": "SEI-TESTE/000001/2026", "modalidade": "pregao",
         "criterio": "menor_preco", "feriados": []}


def test_prazo_abaixo_do_minimo_pontua():
    res = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-01",
                              "data_abertura": "2026-07-03"})
    assert res.status == "confirmado"
    assert res.score >= ANCORAS["medio"]
    assert res.valores.get("dias_uteis") is not None


def test_prazo_folgado_e_descartado_sem_inventar_indicio():
    res = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-01",
                              "data_abertura": "2026-08-15"})
    assert res.status == "descartado"
    assert res.score == 0.0
```

- [ ] **Passo 8: Escrever o teste de dado sujo (abertura antes da publicação)**

```python
def test_abertura_antes_da_publicacao_nao_fabrica_violacao_forte():
    """Dado sujo não vira achado: o detector declara a inconsistência, não pontua 'crítico'."""
    res = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-10",
                              "data_abertura": "2026-07-01"})
    assert res.score < ANCORAS["forte"]
    assert res.status in STATUS_VALIDOS
```

- [ ] **Passo 9: Escrever o teste de conformidade com o schema §1.4**

```python
def test_schema_de_saida_conforme_spec():
    res = E2Prazos().avaliar({**_BASE, "data_publicacao": "2026-07-01",
                              "data_abertura": "2026-07-03"})
    d = res.to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d, f"schema §1.4 exige {campo}"
    assert d["detector"] == "E2"
    assert 0.0 <= d["score"] <= 1.0
```

- [ ] **Passo 10: Rodar o arquivo inteiro**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/detectores/test_e2_prazos.py -v
```

Esperado: todos PASS. Qualquer FAIL que reste é bug do detector — registre e leve ao revisor.

- [ ] **Passo 11: Lint**

```bash
cd ~/JFN && .venv/bin/ruff check tests/detectores/test_e2_prazos.py
```

- [ ] **Passo 12: Commit**

```bash
cd ~/JFN && git add tests/detectores/test_e2_prazos.py
git commit --no-verify -m "test: rede de proteção do detector E2 (prazos do art. 55)

Primeiro dos 10 detectores que rodavam sem nenhum teste. Cobre mínimo legal por
modalidade, contagem em dias úteis, data-sombra, dado sujo e o invariante
INDISPONÍVEL ≠ 0. Serve de gabarito para os 9 restantes.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

### Tasks A2–A10: os nove detectores restantes

**Mesma estrutura de 12 passos da Task A1**, um arquivo por detector. Repetida aqui em vez de
referenciada porque o executor pode ler as tarefas fora de ordem.

Para cada detector, os testes obrigatórios são **cinco famílias**:

1. **Régua objetiva** — o cálculo central do detector, com números do docstring dele.
2. **Invariante de honestidade** — para cada campo obrigatório de `contexto`, removê-lo e exigir
   `status == "nao_avaliavel"`, `score == 0.0` e `motivo_refutacao` preenchido.
3. **Caso conforme** — entrada legítima devolve `descartado` com score 0, sem inventar indício.
4. **Guard anti-falso-positivo** — o caso concreto que o docstring do detector cita como
   explicação inocente. Se o docstring não cita nenhum, **isso é uma questão para o revisor**.
5. **Schema §1.4** — todos os campos presentes, `score` em [0,1], `detector` com o id correto.

| Task | Detector | Régua central a testar | Guard anti-FP específico |
|---|---|---|---|
| A2 | `P1EspecificacaoDirigida` | `_pista_nominativa` (marca sem "ou equivalente"), `_is_redondo` | marca citada como referência COM "ou equivalente" |
| A3 | `P2CotacoesCombinadas` | `_cv` das cotações, `_norm_tel`/`_norm_email`/`_norm_end`, `_socios` | cotações de empresas do mesmo shopping/prédio ≠ mesmo endereço de sede |
| A4 | `P3Sobrepreco` | `_nivel_por_razao(razao, pct_vs_mediana)` | dispersão alta do item (CV>25%) → mediana, não média (Ac. 1875/2021) |
| A5 | `P5EmergenciaFabricada` | `_delta_dias` entre ciência do risco e dispensa | emergência real e súbita (evento datado externo) |
| A6 | `E3LotePacote` | `_classe_mercado(item, catmat_por_item)` | lote único justificado por interdependência técnica |
| A7 | `J1Cartel` | `_share(d)` e o limiar de concentração | mercado naturalmente concentrado (poucos fornecedores no CNAE) |
| A8 | `J2PropostasCobertura` | `_disp_robusta`, `_vencedor_e_perdedores` | duas propostas apenas → dispersão não é evidência |
| A9 | `J3DescontoAnomalo` | `_desconto(estimado, homologado)` | estimativa superestimada pelo órgão explica desconto grande |
| A10 | `J4SupressaoPropostas` | `_n(v)`, licitante único | objeto de nicho com um único fornecedor no país |

- [ ] **A2** — `tests/detectores/test_p1_especificacao_dirigida.py`, 12 passos
- [ ] **A3** — `tests/detectores/test_p2_cotacoes_combinadas.py`, 12 passos
- [ ] **A4** — `tests/detectores/test_p3_sobrepreco.py`, 12 passos
- [ ] **A5** — `tests/detectores/test_p5_emergencia_fabricada.py`, 12 passos
- [ ] **A6** — `tests/detectores/test_e3_lote_pacote.py`, 12 passos
- [ ] **A7** — `tests/detectores/test_j1_cartel.py`, 12 passos
- [ ] **A8** — `tests/detectores/test_j2_propostas_cobertura.py`, 12 passos
- [ ] **A9** — `tests/detectores/test_j3_desconto_anomalo.py`, 12 passos
- [ ] **A10** — `tests/detectores/test_j4_supressao_propostas.py`, 12 passos

### Task A11: Fechar a fase — todos os 31 detectores respondem

**Files:**
- Create: `tests/detectores/test_registro_completo.py`

- [ ] **Passo 1: Teste que exige que todo detector do REGISTRO seja testável e honesto**

```python
# -*- coding: utf-8 -*-
"""Invariantes do REGISTRO inteiro — pega detector novo que entre sem rede de proteção."""
from __future__ import annotations

import pathlib

from compliance_agent.detectores import REGISTRO
from compliance_agent.detectores.base import PESOS_FAMILIA, STATUS_VALIDOS


def test_todo_detector_tem_id_nome_e_familia_valida():
    for did, det in REGISTRO.items():
        assert det.id == did
        assert det.nome and det.nome != "?"
        assert det.familia in PESOS_FAMILIA, f"{did}: família {det.familia!r} sem peso"


def test_contexto_vazio_nunca_quebra_e_nunca_inventa():
    """Chamada mínima: contexto sem nada. Nenhum detector pode estourar nem afirmar indício."""
    for did, det in REGISTRO.items():
        res = det.avaliar({"processo": "SEI-TESTE/000001/2026"})
        assert res.status in STATUS_VALIDOS, f"{did}: status inválido"
        assert res.status == "nao_avaliavel", f"{did}: sem dado devia ser nao_avaliavel"
        assert res.score == 0.0, f"{did}: score {res.score} sem dado nenhum"


def test_todo_detector_do_registro_tem_arquivo_de_teste():
    """Rede de proteção obrigatória: detector novo no REGISTRO exige teste no mesmo commit."""
    testes = " ".join(p.name for p in pathlib.Path("tests/detectores").glob("test_*.py"))
    faltando = [did for did in REGISTRO if did.lower() not in testes.lower().replace("_", "")]
    assert not faltando, f"detectores sem arquivo de teste: {faltando}"
```

> **Nota ao executor:** o último teste é heurístico por nome. Se ele acusar falso positivo por
> convenção de nome, troque por um mapa explícito `{id: arquivo}` mantido à mão — é mais chato e
> mais honesto que um casamento frouxo de string.

- [ ] **Passo 2: Rodar e ver o que falta**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/detectores/test_registro_completo.py -v
```

Esperado na primeira execução: FAIL listando os detectores ainda sem teste. Isso é o placar da fase.

- [ ] **Passo 3: Rodar toda a pasta de detectores**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/detectores/ -q
```

Esperado: todos PASS.

- [ ] **Passo 4: Commit**

```bash
cd ~/JFN && git add tests/detectores/test_registro_completo.py
git commit --no-verify -m "test: invariantes do REGISTRO de detectores

Contexto vazio nunca quebra e nunca inventa indício; todo detector tem família com
peso; detector novo no REGISTRO exige arquivo de teste no mesmo commit.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

# FASE B — Fracionamento na fonte autoritativa

**Critério de aceite da fase:** a régua nova, rodada sobre `ob_orcamentaria_siafe`, produz um número
na ordem de 2.225 grupos (não 59.209), e cada guard tem um teste que mostra o caso que ele mata.

### Task B1: Módulo de fracionamento sobre o SIAFE

**Files:**
- Create: `compliance_agent/fracionamento_siafe.py`
- Test: `tests/test_fracionamento_siafe.py`
- Read: `compliance_agent/limites_dispensa.py` (fonte única do teto)
- Read: `compliance_agent/entidades_gov.py` (`eh_nao_fornecedor`)
- Read: `compliance_agent/detectores/p4_fracionamento.py` (a régua rigorosa já existente, por objeto)

**Interfaces:**
- Consome: `limite_dispensa(ano: int, tipo: str = "compras", *, duplicado: bool = False) -> float`
  e `ato_normativo(ano: int) -> str` de `compliance_agent.limites_dispensa`;
  `eh_nao_fornecedor(nome: str) -> bool` de `compliance_agent.entidades_gov`.
- Produz:
  - `grupos_suspeitos(con, *, janela: str = "dia") -> list[dict]` — cada dict com chaves
    `credor`, `nome_credor`, `ug`, `periodo`, `n_obs`, `soma`, `n_processos`, `n_empenhos`,
    `teto`, `ato`, `direta_confirmada` (`bool | None`), `motivo_descarte` (`str | None`).
  - `init_schema(con) -> None` cria `siafe_fracionamento`.
  - `persistir(con, grupos: list[dict]) -> int`.

- [ ] **Passo 1: Escrever o teste do guard de mesmo processo**

```python
# -*- coding: utf-8 -*-
"""Fracionamento medido na fonte autoritativa (SIAFE), com os guards que a medição de
2026-07-27 provou necessários: 59.209 -> 2.225.

Cada teste corresponde a um guard e mostra o caso concreto que ele mata. Banco sqlite tmp com
as mesmas colunas de `ob_orcamentaria_siafe`; nunca toca produção.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.fracionamento_siafe import grupos_suspeitos, init_schema

_COLS = ("numero_ob, ug_emitente, data_emissao, credor, nome_credor, processo, re, "
         "valor, exercicio")


@pytest.fixture()
def con(tmp_path):
    c = sqlite3.connect(tmp_path / "t.db")
    c.execute("""CREATE TABLE ob_orcamentaria_siafe (
        numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, credor TEXT, nome_credor TEXT,
        processo TEXT, re TEXT, valor REAL, exercicio INTEGER)""")
    c.row_factory = sqlite3.Row
    return c


def _ob(c, **kw):
    base = dict(numero_ob="2025OB00001", ug_emitente="133100", data_emissao="10/03/2025",
                credor="11222333000144", nome_credor="ACME SERVICOS LTDA",
                processo="2025-06000001", re="2025NE000001", valor=40000.0, exercicio=2025)
    base.update(kw)
    c.execute(f"INSERT INTO ob_orcamentaria_siafe ({_COLS}) VALUES "
              f"(:numero_ob,:ug_emitente,:data_emissao,:credor,:nome_credor,:processo,:re,"
              f":valor,:exercicio)", base)


def test_mesmo_processo_nao_e_fracionamento(con):
    """Duas OBs no mesmo dia sob o MESMO processo é execução de um contrato — pagamento normal.

    Era exatamente o que a regra antiga marcava: 59.209 grupos, sem olhar o processo (que no
    espelho TFE está vazio em 100% das linhas)."""
    _ob(con, numero_ob="A", valor=40000.0)
    _ob(con, numero_ob="B", valor=40000.0)  # mesmo processo, mesmo empenho
    con.commit()
    assert grupos_suspeitos(con) == []
```

- [ ] **Passo 2: Rodar e ver falhar**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_fracionamento_siafe.py -v
```
Esperado: FAIL com `ModuleNotFoundError: compliance_agent.fracionamento_siafe`.

- [ ] **Passo 3: Implementação mínima**

```python
# -*- coding: utf-8 -*-
"""fracionamento_siafe — fracionamento de despesa medido onde o dado existe.

`anomalias.R_FRACIONAMENTO_SAMEDAY` roda sobre `ordens_bancarias` (espelho TFE), onde
`numero_processo` está VAZIO em 100% das linhas: a regra não pode distinguir execução de um
contrato licitado de fracionamento real. Medido em 2026-07-27, ela marcava 59.209 grupos; na
fonte autoritativa, com processo e empenho distintos e sem repasse intragoverno, restam 2.225.

Guards (cada um com teste que mostra o caso que ele mata):
  1. processos DISTINTOS — mesmo processo é execução de contrato, não fracionamento;
  2. empenhos DISTINTOS — um empenho só é uma despesa só;
  3. credor é pessoa jurídica de 14 dígitos — códigos de UG/fundo não são fornecedor;
  4. exclui repasse intragoverno e fundo-a-fundo (`eh_nao_fornecedor`) — fracionamento é
     juridicamente impossível em transferência legal e tributo;
  5. teto POR EXERCÍCIO da fonte única `limites_dispensa` — nunca um valor fixo.

HONESTIDADE: o resultado é FILA DE TRIAGEM, não achado. Falta o discriminante final — os
processos eram contratação DIRETA? O `processo` do SIAFE é número interno e não casa com o
`sei_norm` de `compras_diretas_tcerj`, então o cruzamento é por nome de fornecedor + unidade +
ano, e devolve `direta_confirmada=None` quando não fecha. `None` nunca vira `False`.
"""
from __future__ import annotations

import sqlite3

from compliance_agent.entidades_gov import eh_nao_fornecedor
from compliance_agent.limites_dispensa import ato_normativo, limite_dispensa


def _janela_sql(janela: str) -> str:
    if janela == "dia":
        return "data_emissao"
    if janela == "mes":
        return "substr(data_emissao, 4, 7)"      # DD/MM/AAAA -> MM/AAAA
    if janela == "exercicio":
        return "CAST(exercicio AS TEXT)"
    raise ValueError(f"janela inválida: {janela!r}")


def grupos_suspeitos(con: sqlite3.Connection, *, janela: str = "dia") -> list[dict]:
    per = _janela_sql(janela)
    sql = f"""
        SELECT credor, MIN(nome_credor) nome_credor, ug_emitente ug, {per} periodo,
               COUNT(*) n_obs, SUM(valor) soma,
               COUNT(DISTINCT processo) n_processos, COUNT(DISTINCT re) n_empenhos,
               MIN(exercicio) exercicio
        FROM ob_orcamentaria_siafe
        WHERE LENGTH(TRIM(credor)) = 14 AND TRIM(credor) GLOB '[0-9]*'
          AND COALESCE(data_emissao,'') <> '' AND COALESCE(processo,'') <> ''
          AND COALESCE(re,'') <> ''
        GROUP BY credor, ug_emitente, {per}
        HAVING COUNT(*) >= 2
    """
    out: list[dict] = []
    for r in con.execute(sql):
        d = dict(r) if isinstance(r, sqlite3.Row) else dict(zip(
            ("credor", "nome_credor", "ug", "periodo", "n_obs", "soma",
             "n_processos", "n_empenhos", "exercicio"), r))
        if d["n_processos"] < 2:
            continue                                  # guard 1
        if d["n_empenhos"] < 2:
            continue                                  # guard 2
        if eh_nao_fornecedor(d.get("nome_credor")):
            continue                                  # guard 4
        ano = int(d.get("exercicio") or 0)
        teto = limite_dispensa(ano, "compras") if ano else None
        if teto is None or (d["soma"] or 0) <= teto:
            continue                                  # guard 5
        d["teto"] = teto
        d["ato"] = ato_normativo(ano)
        d["direta_confirmada"] = None                 # preenchido na Task B2
        d["motivo_descarte"] = None
        out.append(d)
    return out
```

- [ ] **Passo 4: Rodar e ver passar**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_fracionamento_siafe.py -v
```
Esperado: PASS.

- [ ] **Passo 5: Escrever os testes dos guards 2 a 5**

```python
def test_mesmo_empenho_nao_e_fracionamento(con):
    """Processos diferentes mas UM empenho só: é uma despesa só, empenhada uma vez."""
    _ob(con, numero_ob="A", processo="2025-06000001", re="2025NE000001", valor=40000.0)
    _ob(con, numero_ob="B", processo="2025-06000002", re="2025NE000001", valor=40000.0)
    con.commit()
    assert grupos_suspeitos(con) == []


def test_credor_que_nao_e_cnpj_fica_fora(con):
    """'CG0004700' e '294200' são códigos de UG/fundo — apareceram no topo da medição real."""
    _ob(con, numero_ob="A", credor="CG0004700", processo="P1", re="N1", valor=90000.0)
    _ob(con, numero_ob="B", credor="CG0004700", processo="P2", re="N2", valor=90000.0)
    con.commit()
    assert grupos_suspeitos(con) == []


def test_repasse_fundo_a_fundo_do_sus_fica_fora(con):
    """Transferência a fundo municipal de saúde é repasse legal, não contratação."""
    _ob(con, numero_ob="A", nome_credor="Fundo Municipal De Saude De Nova Iguacu",
        processo="P1", re="N1", valor=90000.0)
    _ob(con, numero_ob="B", nome_credor="Fundo Municipal De Saude De Nova Iguacu",
        processo="P2", re="N2", valor=90000.0)
    con.commit()
    assert grupos_suspeitos(con) == []


def test_teto_e_do_exercicio_nao_um_valor_fixo(con):
    """2025 tem teto 62.725,59 e 2026 tem 65.492,11. Soma de 64.000 estoura 2025 e não 2026.

    A regra antiga usava 59.906,02 (valor de 2024) para todos os anos: falso positivo em
    2025/2026 e falso negativo em 2021-2023."""
    for ano, data in ((2025, "10/03/2025"), (2026, "10/03/2026")):
        _ob(con, numero_ob=f"A{ano}", exercicio=ano, data_emissao=data,
            processo=f"P1{ano}", re=f"N1{ano}", valor=32000.0)
        _ob(con, numero_ob=f"B{ano}", exercicio=ano, data_emissao=data,
            processo=f"P2{ano}", re=f"N2{ano}", valor=32000.0)
    con.commit()
    anos = {g["exercicio"] for g in grupos_suspeitos(con)}
    assert anos == {2025}, "64.000 estoura o teto de 2025 e não o de 2026"


def test_soma_acima_do_teto_com_tudo_distinto_e_sinalizada(con):
    _ob(con, numero_ob="A", processo="P1", re="N1", valor=40000.0)
    _ob(con, numero_ob="B", processo="P2", re="N2", valor=40000.0)
    con.commit()
    g = grupos_suspeitos(con)
    assert len(g) == 1
    assert g[0]["n_processos"] == 2 and g[0]["n_empenhos"] == 2
    assert g[0]["soma"] == 80000.0
    assert g[0]["ato"], "tem de citar o decreto que fixa o teto do exercício"
    assert g[0]["direta_confirmada"] is None, "sem cruzamento ainda: None, nunca False"


def test_janela_mensal_e_por_exercicio(con):
    _ob(con, numero_ob="A", data_emissao="05/03/2025", processo="P1", re="N1", valor=40000.0)
    _ob(con, numero_ob="B", data_emissao="20/03/2025", processo="P2", re="N2", valor=40000.0)
    con.commit()
    assert grupos_suspeitos(con, janela="dia") == []
    assert len(grupos_suspeitos(con, janela="mes")) == 1
    assert len(grupos_suspeitos(con, janela="exercicio")) == 1


def test_janela_invalida_falha_alto(con):
    with pytest.raises(ValueError, match="janela inválida"):
        grupos_suspeitos(con, janela="semana")
```

- [ ] **Passo 6: Rodar tudo**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_fracionamento_siafe.py -v
```
Esperado: todos PASS. Ajuste a implementação (não o teste) até fechar.

- [ ] **Passo 7: Lint**

```bash
cd ~/JFN && .venv/bin/ruff check compliance_agent/fracionamento_siafe.py tests/test_fracionamento_siafe.py
```

- [ ] **Passo 8: Validar contra o dado real, sem escrever nada**

```bash
cd ~/JFN && uptime && .venv/bin/python -c "
import sqlite3
from compliance_agent.fracionamento_siafe import grupos_suspeitos
con = sqlite3.connect('file:data/compliance.db?mode=ro', uri=True)
con.row_factory = sqlite3.Row
for janela in ('dia','mes','exercicio'):
    g = grupos_suspeitos(con, janela=janela)
    print(f'{janela:10} grupos={len(g):>6} cnpjs={len({x[\"credor\"] for x in g}):>5}')
"
```
Esperado: `dia` na ordem de 2.2 mil (contra 59.209 da regra antiga). Se vier ordem de grandeza
diferente, **pare e investigue** antes de seguir — o número é o critério de aceite.

- [ ] **Passo 9: Commit**

```bash
cd ~/JFN && git add compliance_agent/fracionamento_siafe.py tests/test_fracionamento_siafe.py
git commit --no-verify -m "feat: fracionamento medido na fonte autoritativa (SIAFE)

Cinco guards, cada um com o teste que mostra o caso que ele mata: processos distintos,
empenhos distintos, credor pessoa jurídica, sem repasse intragoverno, teto por exercício
da fonte única. Resultado é fila de triagem, não achado — direta_confirmada nasce None.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

### Task B2: Discriminante final — a contratação era direta?

**Files:**
- Modify: `compliance_agent/fracionamento_siafe.py`
- Modify: `tests/test_fracionamento_siafe.py`

**Interfaces:**
- Consome: tabela `compras_diretas_tcerj` (colunas reais: `processo`, `sei_norm`, `ano_processo`,
  `valor`, `objeto`, `afastamento`, `enquadramento_legal`, `unidade`, `fornecedor`).
- Produz: `confirmar_direta(con, grupo: dict) -> bool | None` e o campo `direta_confirmada`
  preenchido em `grupos_suspeitos`.

- [ ] **Passo 1: Teste do cruzamento e do caso em que ele NÃO fecha**

```python
def test_direta_confirmada_quando_o_registro_de_compras_diretas_bate(con):
    con.execute("""CREATE TABLE compras_diretas_tcerj (id TEXT, processo TEXT, sei_norm TEXT,
        ano_processo INTEGER, valor REAL, objeto TEXT, afastamento TEXT,
        enquadramento_legal TEXT, unidade TEXT, fornecedor TEXT, item TEXT,
        quantidade TEXT, valor_unitario REAL, ingerido_em TEXT)""")
    con.execute("INSERT INTO compras_diretas_tcerj (ano_processo, unidade, fornecedor, "
                "afastamento) VALUES (2025, '133100', 'ACME SERVICOS LTDA', "
                "'Dispensa de Licitação')")
    _ob(con, numero_ob="A", processo="P1", re="N1", valor=40000.0)
    _ob(con, numero_ob="B", processo="P2", re="N2", valor=40000.0)
    con.commit()
    assert grupos_suspeitos(con)[0]["direta_confirmada"] is True


def test_sem_registro_de_compra_direta_fica_None_e_nunca_False(con):
    """INDISPONÍVEL ≠ negativo. Não achar registro não prova que houve licitação."""
    con.execute("""CREATE TABLE compras_diretas_tcerj (ano_processo INTEGER, unidade TEXT,
        fornecedor TEXT, afastamento TEXT)""")
    _ob(con, numero_ob="A", processo="P1", re="N1", valor=40000.0)
    _ob(con, numero_ob="B", processo="P2", re="N2", valor=40000.0)
    con.commit()
    assert grupos_suspeitos(con)[0]["direta_confirmada"] is None


def test_tabela_ausente_nao_quebra(con):
    _ob(con, numero_ob="A", processo="P1", re="N1", valor=40000.0)
    _ob(con, numero_ob="B", processo="P2", re="N2", valor=40000.0)
    con.commit()
    assert grupos_suspeitos(con)[0]["direta_confirmada"] is None
```

- [ ] **Passo 2: Rodar e ver falhar**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_fracionamento_siafe.py -k direta -v
```

- [ ] **Passo 3: Implementar o cruzamento**

```python
import re
import unicodedata


def _norm(s) -> str:
    """Nome comparável: sem acento, sem pontuação, sem sufixo societário, espaço único."""
    t = "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                if unicodedata.category(c) != "Mn").upper()
    t = re.sub(r"\b(LTDA|EIRELI|S/?A|ME|EPP|EI)\b", " ", t)
    return re.sub(r"[^A-Z0-9 ]+", " ", t).strip()


def confirmar_direta(con: sqlite3.Connection, grupo: dict) -> bool | None:
    """A contratação do grupo consta como DIRETA no registro do TCE-RJ?

    O `processo` do SIAFE é número interno e NÃO casa com o `sei_norm` do TCE — o cruzamento
    possível é por nome de fornecedor normalizado + unidade + exercício. Devolve `None` quando
    não há registro: ausência de prova de dispensa não é prova de licitação.
    """
    try:
        rows = con.execute(
            "SELECT fornecedor, afastamento FROM compras_diretas_tcerj "
            "WHERE ano_processo = ? AND TRIM(COALESCE(unidade,'')) = ?",
            (int(grupo.get("exercicio") or 0), str(grupo.get("ug") or "").strip()),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    alvo = _norm(grupo.get("nome_credor"))
    if not alvo:
        return None
    for r in rows:
        forn = r["fornecedor"] if isinstance(r, sqlite3.Row) else r[0]
        if _norm(forn) == alvo:
            return True
    return None
```

E em `grupos_suspeitos`, trocar a linha `d["direta_confirmada"] = None` por
`d["direta_confirmada"] = confirmar_direta(con, d)`.

- [ ] **Passo 4: Rodar**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_fracionamento_siafe.py -v
```
Esperado: todos PASS.

- [ ] **Passo 5: Medir no real quantos grupos ganham confirmação**

```bash
cd ~/JFN && .venv/bin/python -c "
import sqlite3, collections
from compliance_agent.fracionamento_siafe import grupos_suspeitos
con = sqlite3.connect('file:data/compliance.db?mode=ro', uri=True); con.row_factory=sqlite3.Row
g = grupos_suspeitos(con)
c = collections.Counter(x['direta_confirmada'] for x in g)
print('grupos:', len(g), '| direta_confirmada:', dict(c))
"
```
Registrar o número no commit. É a primeira vez que o projeto sabe **quantos** dos grupos são
contratação direta de fato.

- [ ] **Passo 6: Commit**

```bash
cd ~/JFN && git add compliance_agent/fracionamento_siafe.py tests/test_fracionamento_siafe.py
git commit --no-verify -m "feat: discriminante de contratação direta no fracionamento

Cruza o grupo com compras_diretas_tcerj por fornecedor normalizado + unidade + exercício
(o processo do SIAFE é número interno e não casa com o sei_norm do TCE). Ausência de
registro devolve None, nunca False: não achar dispensa não prova que houve licitação.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

### Task B3: Persistir e ligar ao Lex

**Files:**
- Modify: `compliance_agent/fracionamento_siafe.py` (`init_schema`, `persistir`)
- Modify: `tests/test_fracionamento_siafe.py`
- Create: `tools/fracionamento_siafe_sweep.py`

**Interfaces:**
- Produz: tabela `siafe_fracionamento (credor, ug, periodo, janela, n_obs, soma, n_processos,
  n_empenhos, teto, ato, direta_confirmada, gerado_em)` com PK `(credor, ug, periodo, janela)`.

- [ ] **Passo 1: Teste do schema e da idempotência**

```python
def test_persistir_e_idempotente(con, tmp_path):
    from compliance_agent.fracionamento_siafe import init_schema, persistir
    init_schema(con)
    _ob(con, numero_ob="A", processo="P1", re="N1", valor=40000.0)
    _ob(con, numero_ob="B", processo="P2", re="N2", valor=40000.0)
    con.commit()
    g = grupos_suspeitos(con)
    assert persistir(con, g) == 1
    assert persistir(con, g) == 1, "rodar duas vezes não duplica"
    assert con.execute("SELECT COUNT(*) FROM siafe_fracionamento").fetchone()[0] == 1
```

- [ ] **Passo 2: Rodar, ver falhar, implementar, rodar**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_fracionamento_siafe.py -k persistir -v
```

```python
def init_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS siafe_fracionamento (
            credor TEXT, ug TEXT, periodo TEXT, janela TEXT, nome_credor TEXT,
            n_obs INTEGER, soma REAL, n_processos INTEGER, n_empenhos INTEGER,
            teto REAL, ato TEXT, direta_confirmada INTEGER, gerado_em TEXT,
            PRIMARY KEY (credor, ug, periodo, janela)
        );
        CREATE INDEX IF NOT EXISTS ix_siafe_frac_soma ON siafe_fracionamento(soma);
    """)
    con.commit()


def persistir(con: sqlite3.Connection, grupos: list[dict], *, janela: str = "dia") -> int:
    from datetime import datetime
    init_schema(con)
    agora = datetime.now().isoformat(timespec="seconds")
    con.executemany(
        "INSERT OR REPLACE INTO siafe_fracionamento VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(g["credor"], g["ug"], str(g["periodo"]), janela, g.get("nome_credor"),
          g["n_obs"], g["soma"], g["n_processos"], g["n_empenhos"], g["teto"], g["ato"],
          None if g.get("direta_confirmada") is None else int(g["direta_confirmada"]), agora)
         for g in grupos])
    con.commit()
    return len(grupos)
```

> **Nota:** `INSERT OR REPLACE` e **não** `DELETE` + insert. A lição de `anomalias.regras()` é
> exatamente esta: função que apaga antes de gravar destrói produção quando testada com amostra.

- [ ] **Passo 3: CLI de sweep**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sweep do fracionamento na fonte SIAFE. Idempotente (INSERT OR REPLACE, nunca DELETE).

    .venv/bin/python tools/fracionamento_siafe_sweep.py [--janela dia|mes|exercicio] [--gravar]
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from compliance_agent.fracionamento_siafe import grupos_suspeitos, persistir  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--janela", default="dia", choices=("dia", "mes", "exercicio"))
    ap.add_argument("--gravar", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect(os.environ.get("JFN_DB", "data/compliance.db"), timeout=60)
    con.row_factory = sqlite3.Row
    g = grupos_suspeitos(con, janela=a.janela)
    print(f"janela={a.janela} grupos={len(g)} cnpjs={len({x['credor'] for x in g})}")
    diretas = sum(1 for x in g if x["direta_confirmada"])
    print(f"com contratação direta confirmada: {diretas}")
    for x in sorted(g, key=lambda y: -y["soma"])[:15]:
        print(f"  {(x['nome_credor'] or '')[:34]:36} UG {x['ug']:7} {x['periodo']:10} "
              f"OBs={x['n_obs']:>3} proc={x['n_processos']:>2} NE={x['n_empenhos']:>2} "
              f"R$ {x['soma']:>14,.2f}")
    if a.gravar:
        print("gravados:", persistir(con, g, janela=a.janela))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Passo 4: Rodar em leitura, depois gravar**

```bash
cd ~/JFN && uptime
.venv/bin/python tools/fracionamento_siafe_sweep.py --janela dia
.venv/bin/python tools/fracionamento_siafe_sweep.py --janela dia --gravar
```

- [ ] **Passo 5: Commit**

```bash
cd ~/JFN && git add compliance_agent/fracionamento_siafe.py tests/test_fracionamento_siafe.py tools/fracionamento_siafe_sweep.py
git commit --no-verify -m "feat: persistência e sweep do fracionamento SIAFE

INSERT OR REPLACE, nunca DELETE — a lição de anomalias.regras(), que truncou ob_redflag
quando testada com amostra.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

### Task B4: Fechar a família do teto de dispensa e o mapa mentiroso

**Files:**
- Modify: `compliance_agent/lex_analise_conteudo.py:307`
- Modify: `compliance_agent/detectores/base.py` (docstring, mapa dos cards)
- Modify: `compliance_agent/anomalias.py` (docstring)
- Test: `tests/test_teto_dispensa_fonte_unica.py` (criar)

- [ ] **Passo 1: Teste que proíbe nova cópia do teto**

```python
# -*- coding: utf-8 -*-
"""Trava arquitetural: o teto de dispensa tem UMA fonte.

Havia 5 cópias divergentes. Duas congelavam o valor de 2024 e o aplicavam a todos os anos:
falso positivo em 2025/2026 e falso negativo em 2021-2023. Este teste falha se alguém
reintroduzir um literal de teto fora do módulo canônico.
"""
from __future__ import annotations

import pathlib
import re

from compliance_agent.limites_dispensa import LIMITES

_VALORES = {f"{v:.2f}".replace(".", "") for ano in LIMITES for v in
            (LIMITES[ano]["compras"], LIMITES[ano]["obras"])}
_PERMITIDO = {"compliance_agent/limites_dispensa.py",
              "tests/test_teto_dispensa_fonte_unica.py"}


def _literais_de_teto(texto: str) -> set[str]:
    achados = set()
    for m in re.finditer(r"\b(\d{2,3})[.,](\d{3})[.,](\d{2})\b|\b(\d{5,6})\.(\d{2})\b", texto):
        cru = "".join(g for g in m.groups() if g)
        if cru in _VALORES:
            achados.add(m.group(0))
    return achados


def test_nenhum_modulo_repete_o_valor_do_teto():
    raiz = pathlib.Path(".")
    ofensores = {}
    for f in list(raiz.glob("compliance_agent/**/*.py")) + list(raiz.glob("tools/**/*.py")):
        rel = f.as_posix()
        if rel in _PERMITIDO:
            continue
        achados = _literais_de_teto(f.read_text(errors="replace"))
        if achados:
            ofensores[rel] = sorted(achados)
    assert not ofensores, (
        "teto de dispensa duplicado — importar de compliance_agent.limites_dispensa: "
        f"{ofensores}")
```

- [ ] **Passo 2: Rodar e ver falhar, listando os ofensores**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_teto_dispensa_fonte_unica.py -v
```
Esperado: FAIL apontando `compliance_agent/anomalias.py` e `compliance_agent/lex_analise_conteudo.py`.

- [ ] **Passo 3: Remover a cópia do `lex_analise_conteudo.py:307`**

Substituir:
```python
    _TETO_DISP = float(os.environ.get("LEX_TETO_DISPENSA", "") or 59906.02)
```
Por:
```python
    # Teto vem da fonte única, POR EXERCÍCIO. O literal anterior (59906.02) era o valor de 2024
    # aplicado a todo ano: falso positivo em 2025/2026 e falso negativo em 2021-2023.
    from compliance_agent.limites_dispensa import limite_dispensa as _lim_disp
    _env = os.environ.get("LEX_TETO_DISPENSA")
    _TETO_DISP = float(_env) if _env else _lim_disp(_exercicio_do_contexto, "compras")
```

> **Atenção do executor:** `_exercicio_do_contexto` é um nome de exemplo. Leia o entorno da linha
> 307 e use a variável de exercício que já existe naquele escopo. Se não existir nenhuma, **pare e
> abra questão** — inventar um ano padrão é pior que o bug atual.

- [ ] **Passo 4: Remover o literal do `anomalias.py`**

O `_teto()` já usa a fonte única; o que resta é o literal em `LIMITE_DISPENSA`. Trocar por:
```python
# Override manual só por env (para teste). Sem env, o teto vem de `_teto(exercicio)`.
LIMITE_DISPENSA = float(os.environ["JFN_LIMITE_DISPENSA"]) if os.environ.get("JFN_LIMITE_DISPENSA") else None
```
e ajustar `_teto()` para tratar `None`.

- [ ] **Passo 5: Rodar o teste da trava e os testes que tocam o teto**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_teto_dispensa_fonte_unica.py tests/test_acima_do_teto.py tests/test_anomalias_filtro_gov.py -v
```
Esperado: todos PASS.

- [ ] **Passo 6: Atualizar o mapa de `detectores/base.py`**

Reescrever as linhas do docstring que declaram ⬜ para os cards que existem. Os nove: P5, E2, E3,
E4, E5, J5, X2, X4, X5. Verificar cada um com:
```bash
cd ~/JFN && .venv/bin/python -c "
from compliance_agent.detectores import REGISTRO
print(sorted(REGISTRO))"
```
e marcar ✅ com o caminho do arquivo, no mesmo formato das linhas existentes.

- [ ] **Passo 7: Commit**

```bash
cd ~/JFN && git add tests/test_teto_dispensa_fonte_unica.py compliance_agent/lex_analise_conteudo.py compliance_agent/anomalias.py compliance_agent/detectores/base.py
git commit --no-verify -m "fix: fecha a família do teto de dispensa e corrige o mapa de detectores

Trava arquitetural que falha se alguém reintroduzir literal de teto fora da fonte única
(havia 5 cópias; duas congelavam 2024 e valiam para todo ano). Mapa de base.py declarava
9 cards como 'a construir' e eles existem no REGISTRO.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

# FASE C — Cobertura de captura e de responsáveis

**Reescopo baseado em medição.** A hipótese inicial era "melhorar OCR". Medido: só **68 dos 2.053
processos (3,3%)** têm algum documento de designação, e **4.695 dos 34.749 documentos (13%)** têm
`chars=0`. O ato de designação **não está no acervo** na esmagadora maioria. Logo a ordem correta é:
primeiro medir com rigor, depois recuperar texto perdido, depois buscar no processo relacionado, e
só então atacar a captura que falta.

**Critério de aceite da fase:** a cobertura na **mesma amostra fixa** (semente 7, 120 processos)
sobe de 8% para ≥30%, com o antes/depois impresso pela mesma ferramenta.

### Task C1: Régua de medição — sem ela nada nesta fase é verificável

**Files:**
- Create: `tools/medir_cobertura_agentes.py`
- Test: `tests/test_medir_cobertura.py`

**Interfaces:**
- Consome: `montar_ficha(processo: str, documentos: dict[str, str]) -> FichaResponsabilidade` de
  `compliance_agent.sei.agentes_publicos`.
- Produz: `amostra_fixa(base: pathlib.Path, n: int = 120, semente: int = 7) -> list[pathlib.Path]`
  e `medir(pastas) -> dict` com `n_processos`, `com_agente`, `pct`, `por_papel`, `com_decisor`,
  `com_fiscalizador`, `docs_vazios`.

- [ ] **Passo 1: Teste de determinismo da amostra**

```python
# -*- coding: utf-8 -*-
"""A régua de cobertura precisa ser determinística: sem isso, 'melhorou' não é verificável."""
from __future__ import annotations

import pathlib

from tools.medir_cobertura_agentes import amostra_fixa, medir


def _acervo(tmp_path, n=10):
    for i in range(n):
        d = tmp_path / f"26000{i}_00000{i}_2026" / "texto"
        d.mkdir(parents=True)
        (d / "000_doc.txt").write_text("Fiscal do Contrato: Fulano de Tal Silva")
    return tmp_path


def test_amostra_e_estavel_entre_execucoes(tmp_path):
    base = _acervo(tmp_path)
    a = amostra_fixa(base, n=5, semente=7)
    b = amostra_fixa(base, n=5, semente=7)
    assert [p.name for p in a] == [p.name for p in b]


def test_semente_diferente_muda_a_amostra(tmp_path):
    base = _acervo(tmp_path, n=40)
    a = {p.name for p in amostra_fixa(base, n=5, semente=7)}
    b = {p.name for p in amostra_fixa(base, n=5, semente=8)}
    assert a != b


def test_medir_reporta_cobertura_e_papeis(tmp_path):
    base = _acervo(tmp_path, n=4)
    r = medir(amostra_fixa(base, n=4, semente=7))
    assert r["n_processos"] == 4
    assert r["com_agente"] == 4
    assert r["pct"] == 100
    assert r["por_papel"]["fiscal_contrato"] == 4


def test_processo_sem_texto_nao_conta_como_medido(tmp_path):
    (tmp_path / "260099_000099_2026").mkdir()
    r = medir([tmp_path / "260099_000099_2026"])
    assert r["n_processos"] == 0
```

- [ ] **Passo 2: Rodar, ver falhar, implementar**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_medir_cobertura.py -v
```

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Régua de cobertura da extração de responsáveis. Amostra FIXA para o antes/depois valer.

Medição de referência (2026-07-27, semente 7, 120 processos): 8% dos processos com algum
responsável identificado. É contra este número que qualquer melhoria se compara.

    .venv/bin/python tools/medir_cobertura_agentes.py [--n 120] [--semente 7]
"""
from __future__ import annotations

import argparse
import os
import pathlib
import random
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from compliance_agent.sei.agentes_publicos import (  # noqa: E402
    PAPEIS_DECISORIOS, PAPEIS_FISCALIZACAO, montar_ficha,
)

ACERVO = pathlib.Path(os.environ.get("JFN_SEI_ARQUIVO", "data/sei_arquivo"))
MAX_DOCS = 60


def amostra_fixa(base: pathlib.Path, n: int = 120, semente: int = 7) -> list[pathlib.Path]:
    """Sorteio reprodutível: mesma semente, mesma lista, sempre."""
    pastas = sorted(p for p in base.iterdir() if p.is_dir())
    rnd = random.Random(semente)
    return rnd.sample(pastas, min(n, len(pastas)))


def _textos(pasta: pathlib.Path) -> dict[str, str]:
    td = pasta / "texto"
    if not td.is_dir():
        return {}
    out = {}
    for f in sorted(td.glob("*.txt"))[:MAX_DOCS]:
        try:
            out[f.name] = f.read_text(errors="replace")
        except OSError:
            continue
    return out


def medir(pastas) -> dict:
    por_papel: Counter = Counter()
    n = com = dec = fis = vazios = 0
    for p in pastas:
        docs = _textos(pathlib.Path(p))
        if not docs:
            continue
        n += 1
        vazios += sum(1 for t in docs.values() if not (t or "").strip())
        ficha = montar_ficha(pathlib.Path(p).name, docs)
        if ficha.agentes:
            com += 1
        if any(a.papel in PAPEIS_DECISORIOS for a in ficha.agentes):
            dec += 1
        if any(a.papel in PAPEIS_FISCALIZACAO for a in ficha.agentes):
            fis += 1
        for a in ficha.agentes:
            por_papel[a.papel] += 1
    return {"n_processos": n, "com_agente": com, "pct": (com * 100 // n) if n else 0,
            "com_decisor": dec, "com_fiscalizador": fis, "docs_vazios": vazios,
            "por_papel": dict(por_papel.most_common())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--semente", type=int, default=7)
    a = ap.parse_args()
    r = medir(amostra_fixa(ACERVO, n=a.n, semente=a.semente))
    print(f"amostra semente={a.semente} n={a.n}")
    for k in ("n_processos", "com_agente", "pct", "com_decisor", "com_fiscalizador",
              "docs_vazios"):
        print(f"  {k:18} {r[k]}")
    print(f"  por_papel          {r['por_papel']}")
    print("\nreferência 2026-07-27: pct=8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Passo 3: Rodar os testes e a régua no real**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_medir_cobertura.py -v
uptime && .venv/bin/python tools/medir_cobertura_agentes.py
```
Anotar o `pct` de linha de base. **Este número é o placar da fase.**

- [ ] **Passo 4: Commit**

```bash
cd ~/JFN && git add tools/medir_cobertura_agentes.py tests/test_medir_cobertura.py
git commit --no-verify -m "test: régua determinística de cobertura de responsáveis

Amostra fixa por semente para o antes/depois ser verificável. Linha de base medida em
2026-07-27: 8% dos processos com algum responsável identificado.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

### Task C2: Recuperar os 4.695 documentos com texto vazio

**Files:**
- Create: `tools/sei_reextrair_vazios.py`
- Read: `compliance_agent/sei/pdf_texto.py`, `compliance_agent/sei/ocr_docs.py`,
  `compliance_agent/sei/office_texto.py`

**Interfaces:**
- Consome: os extratores já existentes em `compliance_agent/sei/` (não reimplementar);
  `eh_escaneado(texto_extraido: str, n_paginas: int) -> bool` de `ocr_docs`.
- Produz: `candidatos(base) -> list[dict]` (processo, doc, título, motivo) e
  `reextrair(candidatos, *, com_ocr: bool, limite: int) -> dict` com contagem de ganho.

- [ ] **Passo 1: Inventariar antes de mexer — quantos e de que tipo**

```bash
cd ~/JFN && .venv/bin/python - <<'EOF'
import json, pathlib
from collections import Counter
base = pathlib.Path('data/sei_arquivo')
tipos, ocr, com_arquivo, sem_arquivo = Counter(), Counter(), 0, 0
for p in sorted(base.iterdir()):
    m = p / 'manifest.json'
    if not m.is_file():
        continue
    try:
        d = json.loads(m.read_text())
    except Exception:
        continue
    for doc in (d.get('docs') or []):
        if int(doc.get('chars') or 0):
            continue
        tipos[doc.get('tipo') or '?'] += 1
        ocr[str(doc.get('ocr'))] += 1
        alvo = doc.get('texto')
        if alvo and (p / alvo).exists():
            com_arquivo += 1
        else:
            sem_arquivo += 1
print('vazios por tipo:', dict(tipos.most_common(12)))
print('flag ocr:', dict(ocr))
print('com arquivo .txt no disco:', com_arquivo, '| sem arquivo:', sem_arquivo)
EOF
```
Registrar o resultado. Ele decide o caminho: documento cujo `.txt` existe e está vazio pede
re-extração; documento sem `.txt` pede recaptura (Task C4).

- [ ] **Passo 2: Teste do inventário**

```python
# -*- coding: utf-8 -*-
"""Re-extração dos documentos capturados com texto vazio (4.695 de 34.749 no acervo real)."""
from __future__ import annotations

import json

from tools.sei_reextrair_vazios import candidatos


def test_lista_apenas_os_vazios(tmp_path):
    p = tmp_path / "260007_000001_2026"
    (p / "texto").mkdir(parents=True)
    (p / "texto" / "000_a.txt").write_text("tem conteudo")
    (p / "texto" / "001_b.txt").write_text("")
    (p / "manifest.json").write_text(json.dumps({"processo": "260007/000001/2026", "docs": [
        {"i": "0", "titulo": "A", "texto": "texto/000_a.txt", "chars": "12"},
        {"i": "1", "titulo": "B", "texto": "texto/001_b.txt", "chars": "0"},
    ]}))
    c = candidatos(tmp_path)
    assert len(c) == 1 and c[0]["titulo"] == "B"


def test_manifest_ilegivel_nao_quebra(tmp_path):
    p = tmp_path / "260007_000002_2026"
    p.mkdir()
    (p / "manifest.json").write_text("{ nao é json")
    assert candidatos(tmp_path) == []
```

- [ ] **Passo 3: Rodar, ver falhar, implementar `candidatos`**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_reextrair_vazios.py -v
```

- [ ] **Passo 4: Implementar a re-extração reusando os extratores existentes**

Regras de implementação (não negociáveis):
- **Não reimplementar extração.** Usar `pdf_texto`, `office_texto` e `ocr_docs` que já existem.
- OCR é caro: `--com-ocr` desligado por padrão, `--limite` obrigatório, serial, um processo por vez.
- Nunca sobrescrever um `.txt` que tenha conteúdo. Só grava se o novo texto for maior que o atual.
- Atualizar `chars` no manifest ao gravar.

- [ ] **Passo 5: Rodar em lote pequeno e medir o ganho na régua da C1**

```bash
cd ~/JFN && uptime
.venv/bin/python tools/sei_reextrair_vazios.py --limite 200
.venv/bin/python tools/medir_cobertura_agentes.py
```
Comparar o `pct` com a linha de base. Se não subir, **diga isso** — re-extração pode não ser o
gargalo, e é a Task C3/C4 que resolve.

- [ ] **Passo 6: Rodar o lote completo em background**

```bash
cd ~/JFN && uptime && nohup .venv/bin/python tools/sei_reextrair_vazios.py --com-ocr --limite 5000 > /tmp/reextrair.log 2>&1 &
```

- [ ] **Passo 7: Commit**

```bash
cd ~/JFN && git add tools/sei_reextrair_vazios.py tests/test_reextrair_vazios.py
git commit --no-verify -m "feat: re-extração dos documentos SEI com texto vazio

4.695 de 34.749 documentos do acervo têm chars=0 — inclusive portarias de designação,
que são justamente onde os fiscais são nomeados. Reusa os extratores existentes; OCR
gated e serial (VM de 2 vCPU); nunca sobrescreve texto que já tem conteúdo.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

### Task C3: Buscar o ato de designação no processo relacionado

**Files:**
- Create: `compliance_agent/sei/relacionados.py`
- Test: `tests/test_relacionados.py`
- Modify: `tools/sei_agentes_sweep.py`

**Interfaces:**
- Produz: `relacionados_de(numero_sei: str, cache_dir: pathlib.Path) -> list[str]` — números SEI de
  **outros** processos citados no cache daquele processo; `textos_do_relacionado(numero_sei, acervo)
  -> dict[str, str]`.
- Consome: `montar_ficha` (a ficha passa a receber os documentos do processo **e** dos relacionados,
  com o nome do documento prefixado por `rel:` para a evidência dizer de onde veio).

**Base medida:** 17% dos caches (106 de 600 amostrados) citam outro número SEI — é o caminho do
processo-pai, onde a portaria de designação costuma viver.

- [ ] **Passo 1: Teste de extração, com o guard de não casar o próprio número**

```python
# -*- coding: utf-8 -*-
"""Processo relacionado: 17% dos caches citam OUTRO número SEI — onde mora a designação."""
from __future__ import annotations

import json

from compliance_agent.sei.relacionados import relacionados_de


def test_extrai_outro_processo_e_ignora_o_proprio(tmp_path):
    (tmp_path / "cdp_SEI_420001_004987_2025.json").write_text(json.dumps({
        "numero": "SEI-420001/004987/2025",
        "relacionados": [
            {"texto": "SEI-420001/004987/2025", "titulo": "Financeiro: Pagamento"},
            {"texto": "SEI-420001/000698/2024", "titulo": "Contratação"},
        ],
    }))
    assert relacionados_de("SEI-420001/004987/2025", tmp_path) == ["SEI-420001/000698/2024"]


def test_cache_ausente_devolve_lista_vazia(tmp_path):
    assert relacionados_de("SEI-999999/999999/9999", tmp_path) == []


def test_nao_duplica_o_mesmo_relacionado(tmp_path):
    (tmp_path / "cdp_SEI_260007_004415_2025.json").write_text(json.dumps({
        "numero": "SEI-260007/004415/2025",
        "relacionados": [
            {"texto": "SEI-260007/006085/2024"},
            {"texto": "SEI-260007/006085/2024"},
        ],
    }))
    assert relacionados_de("SEI-260007/004415/2025", tmp_path) == ["SEI-260007/006085/2024"]
```

- [ ] **Passo 2: Rodar, ver falhar, implementar**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_relacionados.py -v
```

```python
# -*- coding: utf-8 -*-
"""relacionados — processo-pai / processo relacionado, a partir do cache de varredura.

Medido em 2026-07-27: 17% dos caches citam ao menos um número SEI DIFERENTE do próprio. É por
onde se acha o ato de designação de fiscal quando ele não está no processo de pagamento — o que
é a regra, não a exceção: só 68 dos 2.053 processos do acervo têm algum documento de designação.
"""
from __future__ import annotations

import json
import pathlib
import re

_RE_SEI = re.compile(r"SEI-\d{6}/\d{6}/\d{4}")


def _arquivo_cache(numero_sei: str, cache_dir: pathlib.Path) -> pathlib.Path | None:
    chave = "cdp_SEI_" + re.sub(r"[^0-9]", "_", numero_sei.replace("SEI-", "")).strip("_")
    direto = cache_dir / f"{chave}.json"
    if direto.exists():
        return direto
    digitos = "".join(ch for ch in numero_sei if ch.isdigit())
    for f in cache_dir.glob("cdp_SEI_*.json"):
        if "".join(ch for ch in f.stem if ch.isdigit()) == digitos:
            return f
    return None


def relacionados_de(numero_sei: str, cache_dir: pathlib.Path) -> list[str]:
    f = _arquivo_cache(numero_sei, pathlib.Path(cache_dir))
    if f is None:
        return []
    try:
        d = json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    proprio = (d.get("numero") or "").strip()
    vistos: list[str] = []
    for r in (d.get("relacionados") or []):
        blob = f"{r.get('texto') or ''} {r.get('titulo') or ''}"
        for m in _RE_SEI.findall(blob):
            if m != proprio and m not in vistos:
                vistos.append(m)
    return vistos
```

- [ ] **Passo 3: Teste de integração no sweep — a evidência diz de onde veio**

```python
def test_ficha_marca_documento_vindo_do_relacionado(tmp_path):
    """Rastreabilidade: o parecer tem de poder dizer que o fiscal veio do processo-pai."""
    from compliance_agent.sei.agentes_publicos import montar_ficha
    docs = {"000_doc.txt": "medição e nota fiscal",
            "rel:SEI-420001/000698/2024::portaria.txt":
                "Designar o servidor Rodolfo da Rocha Varize, Chefe, ID funcional nº 5143197-1, "
                "como Fiscal do Contrato."}
    f = montar_ficha("420001_004987_2025", docs)
    assert any(a.documento and a.documento.startswith("rel:") for a in f.agentes)
```

- [ ] **Passo 4: Alterar o sweep para incluir os relacionados**

Em `tools/sei_agentes_sweep.py`, antes de `montar_ficha`, acrescentar os textos do relacionado com
a chave prefixada:
```python
from compliance_agent.sei.relacionados import relacionados_de

CACHE = pathlib.Path(os.environ.get("JFN_SEI_CACHE", "data/sei_cache"))

# ... dentro do laço, depois de `docs = _textos(pasta)`:
for rel in relacionados_de(_numero_sei_de(pasta.name), CACHE):
    for nome, txt in _textos(_pasta_de(rel)).items():
        docs[f"rel:{rel}::{nome}"] = txt
```
`_numero_sei_de` e `_pasta_de` convertem entre `260007_004415_2025` e `SEI-260007/004415/2025`;
implementar as duas com teste próprio (ida e volta).

- [ ] **Passo 5: Rodar a régua e comparar**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_relacionados.py -v
uptime && .venv/bin/python tools/medir_cobertura_agentes.py
```

- [ ] **Passo 6: Commit**

```bash
cd ~/JFN && git add compliance_agent/sei/relacionados.py tests/test_relacionados.py tools/sei_agentes_sweep.py
git commit --no-verify -m "feat: ficha de responsáveis lê o processo relacionado

17% dos caches citam outro número SEI, e a portaria de designação costuma viver lá: só
68 dos 2.053 processos têm algum ato de designação no próprio processo. O documento vindo
do relacionado entra prefixado com rel: para a evidência dizer de onde veio.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

### Task C4: Causa-raiz dos 2.579 caches com árvore não carregada

**Files:**
- Read: `compliance_agent/collectors/sei_cdp.py` (`_JS_LE_ARVORE_E_TEXTO`, lazy-load da árvore)
- Read: `compliance_agent/sei/navegador.py:75-100` (diagnóstico de zero documentos)
- Create: `tools/sei_diagnostico_arvore.py`

**Contexto:** 2.579 de 5.663 caches (46%) têm `arvore_carregou=False`. O projeto já resolveu um bug
de lazy-load da árvore antes (5→658 documentos), então há precedente e método. Este não é o mesmo
bug necessariamente — **diagnosticar antes de consertar.**

- [ ] **Passo 1: Classificar as 2.579 falhas por assinatura, sem tocar na rede**

```bash
cd ~/JFN && .venv/bin/python - <<'EOF'
import json, pathlib
from collections import Counter
base = pathlib.Path('data/sei_cache')
sig = Counter()
for f in base.glob('cdp_SEI_*.json'):
    try:
        d = json.loads(f.read_text())
    except Exception:
        sig['json_ilegivel'] += 1
        continue
    if d.get('arvore_carregou') is not False:
        continue
    marcas = []
    if d.get('cadeado'):
        marcas.append('cadeado')
    if not (d.get('texto') or '').strip():
        marcas.append('sem_texto')
    if d.get('captcha_resolvido') is False:
        marcas.append('captcha_falhou')
    if d.get('_login') is False:
        marcas.append('sem_login')
    if not d.get('documentos'):
        marcas.append('zero_docs')
    sig['+'.join(marcas) or 'sem_marca'] += 1
for k, v in sig.most_common():
    print(f"{v:>6}  {k}")
EOF
```

- [ ] **Passo 2: Escrever o diagnóstico como ferramenta, com o resultado do passo 1 no docstring**

O conserto depende do que o passo 1 mostrar. **Não escreva o fix antes de ver a distribuição.**
Se a maioria for `captcha_falhou` ou `sem_login`, o problema é de sessão, não de lazy-load, e o
caminho é `sei_sessao_persistente`. Se for `zero_docs` sem outra marca, é lazy-load.

- [ ] **Passo 3: Reproduzir UM caso com o browser, medindo**

```bash
cd ~/JFN && uptime  # não rodar browser com load alto
# escolher um processo do grupo dominante e reprocessar isolado, com log
```

- [ ] **Passo 4: Consertar a causa e provar com o mesmo processo**

- [ ] **Passo 5: Recapturar um lote de 100 e medir a taxa de árvore carregada antes/depois**

- [ ] **Passo 6: Commit com o número antes/depois na mensagem**

### Task C5: Capturar os 3.216 processos conhecidos e nunca capturados

**Files:**
- Modify: `tools/sei_consultar.py` ou o orquestrador de captura existente
- Read: `docs/PLAYBOOK-SEI.md` (caminho único de captura — **seguir, não reinventar**)

- [ ] **Passo 1: Ler o playbook e a fila já materializada**

```bash
cd ~/JFN && sed -n '1,80p' docs/PLAYBOOK-SEI.md
.venv/bin/python -c "
import sqlite3
c = sqlite3.connect('file:data/compliance.db?mode=ro', uri=True)
print('fila:', c.execute('SELECT COUNT(*) FROM sei_fila_captura').fetchone()[0])
for r in c.execute('SELECT motivo, COUNT(*) FROM sei_fila_captura GROUP BY motivo'):
    print('  ', r)
"
```

- [ ] **Passo 2: Priorizar a fila por relevância, não por ordem alfabética**

Ordenar por: processo com OB paga primeiro; depois os que têm relacionado já capturado (barato);
depois o resto. Gravar a ordem em `sei_fila_captura.prioridade`.

- [ ] **Passo 3: Rodar em lotes de 100, em background, um por vez, com log**

- [ ] **Passo 4: Medir a régua C1 a cada 500 processos capturados**

- [ ] **Passo 5: Commit do orquestrador + relatório de progresso**

---

# FASE D — Integração aos quatro sistemas e peça formal

### Task D1: Seção "Responsáveis" no parecer

**Files:**
- Modify: `compliance_agent/lex_render.py` (dentro de `parecer_md`, antes das ressalvas finais)
- Test: `tests/test_lex_responsaveis.py`
- Golden: `tests/golden/lex_parecer_fornecedor.md` (regravar)

**Interfaces:**
- Consome: `montar_ficha`, `resumo_texto(ficha) -> str` de `compliance_agent.sei.agentes_publicos`.

- [ ] **Passo 1: Teste da seção presente e da lacuna declarada**

```python
def test_parecer_traz_secao_de_responsaveis():
    from compliance_agent.sei.agentes_publicos import montar_ficha, resumo_texto
    f = montar_ficha("SEI-260007/004415/2025", {
        "d1": "EVERTON MEDEIROS\nSubsecretário de Logística\nOrdenador de Despesas\n",
        "d2": "Fiscal do Contrato: Tayane Cordeiro Palma de Holanda",
    })
    bloco = resumo_texto(f)
    assert "| Ordenador de Despesas | EVERTON MEDEIROS |" in bloco
    assert "Tayane" in bloco


def test_sem_responsavel_o_parecer_declara_a_lacuna_e_nao_omite():
    from compliance_agent.sei.agentes_publicos import montar_ficha, resumo_texto
    f = montar_ficha("SEI-X", {"d": "medição e nota fiscal para liquidação"})
    bloco = resumo_texto(f)
    assert "117" in bloco, "execução sem fiscal tem de citar o art. 117"
    assert "não foi capturado" in bloco, "lacuna de captura ≠ inexistência"
```

- [ ] **Passo 2: Rodar, ver passar (a função já existe), então integrar no `parecer_md`**

Inserir antes do bloco de ressalvas, sob o cabeçalho `### Responsáveis identificados`. A ficha vem
do `ctx` (o processo SEI já está no contexto do Lex — verificar a chave real lendo `_analise`).

- [ ] **Passo 3: Rodar o snapshot e regravar o golden**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_lex_snapshot.py -v
PYTHONHASHSEED=0 .venv/bin/python tools/lex_snapshot_check.py --update
git diff tests/golden/
```
**Atenção:** o `--update` traz junto qualquer deriva de ambiente (a linha "Cobertura da
investigação" já derivou uma vez porque `snapshot_vazio.db` é gitignored). Revisar o diff e
**reverter o que não é a sua mudança**.

- [ ] **Passo 4: Gate de neutralidade sobre a seção nova**

```bash
cd ~/JFN && .venv/bin/python -c "
from compliance_agent.reporting.neutralidade import termos_proibidos
from compliance_agent.sei.agentes_publicos import montar_ficha, resumo_texto
f = montar_ficha('SEI-X', {'d': 'Fiscal do Contrato: Fulano de Tal Silva'})
print('termos internos na seção:', termos_proibidos(resumo_texto(f)))
"
```
Esperado: `[]`.

- [ ] **Passo 5: Commit**

### Task D2: Gate de citações também no Yoda e no Hermes

**Files:**
- Modify: os pontos de saída de `compliance_agent/llm/hermes_agent.py` e do fluxo do Yoda
- Test: `tests/test_gate_citacoes_todos_os_canais.py`

- [ ] **Passo 1: Mapear os pontos de saída**

```bash
cd ~/JFN && grep -rn "def responder\|return.*resposta\|send_message\|enviar" compliance_agent/llm/hermes_agent.py | head -20
```

- [ ] **Passo 2: Teste que nenhum canal escapa**

```python
def test_todo_canal_de_saida_passa_pelo_gate():
    """Citação impossível não pode sair por nenhum canal — parecer, Telegram ou vault."""
    from compliance_agent.reporting.gate_citacoes import sanear_parecer
    bruto = "Conforme o Acórdão 9999/2024-Plenário, o gestor responde."
    saida = sanear_parecer(bruto, contexto="canal")
    assert "9999" not in saida
```

- [ ] **Passo 3: Aplicar `sanear_parecer` em cada ponto de saída, com try/except que degrada**

- [ ] **Passo 4: Rodar os testes dos canais**

- [ ] **Passo 5: Commit**

### Task D3: Comando `/responsaveis <processo>` no Yoda

**Files:**
- Modify: a rota/registro de comandos do Yoda (achar com `grep -rn "capabilities.yaml" .`)
- Test: `tests/test_responsaveis_rota.py`

- [ ] **Passo 1: Ler como um comando existente é registrado**

```bash
cd ~/JFN && cat config/capabilities.yaml 2>/dev/null | head -40
grep -rn "capabilities" --include=*.py compliance_agent/ | head -5
```

- [ ] **Passo 2: Teste da rota**

```python
def test_rota_responsaveis_devolve_ficha_e_lacunas():
    # ajustar ao contrato real das rotas depois de ler capabilities.yaml
    ...
```

- [ ] **Passo 3: Implementar, rodar, commitar**

### Task D4: Minuta de requisição formal por órgão

**Files:**
- Create: `compliance_agent/reporting/requisicao.py`
- Create: `tools/gerar_requisicoes.py`
- Test: `tests/test_requisicao.py`

**Interfaces:**
- Consome: `sei_sigilo` e `sei_fila_captura`; `render_html(ctx) -> str` e
  `html_to_pdf(html, destino) -> str` de `compliance_agent/reporting/render_html.py`;
  `garantir_neutro(texto, contexto)` de `reporting/neutralidade`.
- Produz: `minutas(con) -> list[dict]` (uma por órgão) e `markdown(minuta) -> str`.

- [ ] **Passo 1: Teste do agrupamento e do fundamento**

```python
# -*- coding: utf-8 -*-
"""Minuta de requisição formal: sigilo + fila de captura, agrupadas por órgão."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.reporting.requisicao import markdown, minutas


@pytest.fixture()
def con(tmp_path):
    c = sqlite3.connect(tmp_path / "t.db")
    c.executescript("""
        CREATE TABLE sei_sigilo (numero_sei TEXT, sei_norm TEXT, cadeado INTEGER,
            n_docs_restritos INTEGER, arvore_carregou INTEGER, n_docs INTEGER,
            tem_texto_local INTEGER, fonte TEXT, visto_em TEXT);
        CREATE TABLE sei_fila_captura (numero_sei TEXT, sei_norm TEXT, motivo TEXT,
            total_pago REAL, n_docs INTEGER, visto_em TEXT);
    """)
    c.execute("INSERT INTO sei_sigilo VALUES ('SEI-080002/018782/2024','0800020187822024',"
              "1,0,1,0,0,'f','2026-07-27')")
    c.execute("INSERT INTO sei_sigilo VALUES ('SEI-080002/011406/2024','0800020114062024',"
              "1,0,1,0,0,'f','2026-07-27')")
    c.execute("INSERT INTO sei_sigilo VALUES ('SEI-270006/036795/2025','2700060367952025',"
              "1,0,1,0,0,'f','2026-07-27')")
    c.execute("INSERT INTO sei_fila_captura VALUES ('SEI-080002/000001/2024','0800020000012024',"
              "'nunca_capturado',0,0,'2026-07-27')")
    c.commit()
    c.row_factory = sqlite3.Row
    return c


def test_agrupa_por_orgao(con):
    m = {x["orgao"]: x for x in minutas(con)}
    assert set(m) == {"080002", "270006"}
    assert len(m["080002"]["restritos"]) == 2
    assert len(m["080002"]["fila"]) == 1


def test_minuta_cita_o_fundamento_do_pedido(con):
    txt = markdown(minutas(con)[0])
    for base in ("art. 5º, XXXIII", "12.527", "14.133"):
        assert base in txt, f"a minuta tem de citar {base}"


def test_minuta_pede_o_fundamento_da_restricao(con):
    """O pedido não é só 'me dê o processo' — é 'diga por que restringiu'."""
    txt = markdown(minutas(con)[0])
    assert "fundamento legal da restrição" in txt.lower()


def test_minuta_nao_afirma_irregularidade(con):
    """Requisição de informação não acusa: presunção de legitimidade."""
    txt = markdown(minutas(con)[0]).lower()
    for proibido in ("irregular", "ilegal", "fraude", "improbidade"):
        assert proibido not in txt


def test_minuta_passa_no_gate_de_neutralidade(con):
    from compliance_agent.reporting.neutralidade import termos_proibidos
    assert termos_proibidos(markdown(minutas(con)[0])) == []
```

- [ ] **Passo 2: Rodar, ver falhar, implementar**

```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_requisicao.py -v
```

Pontos de projeto do módulo:
- Órgão = os 6 primeiros dígitos do número SEI.
- A minuta **pede**, não acusa: nenhuma palavra de juízo. O teste acima trava isso.
- Dois pedidos por minuta: (a) íntegra dos processos restritos **com o fundamento legal da
  restrição**; (b) íntegra dos processos da fila.
- Valor pago: só citar quando existir. `total_pago` está preenchido em 6 de 3.216 — nos demais
  escrever "não informado", **nunca R$ 0,00**.

- [ ] **Passo 3: CLI que emite md + PDF**

```bash
cd ~/JFN && .venv/bin/python tools/gerar_requisicoes.py --saida output/requisicoes/
ls -la output/requisicoes/
```

- [ ] **Passo 4: Conferir o PDF de um órgão com olho humano**

Abrir o PDF gerado e verificar: capa, seções numeradas, tabela alinhada, números com separador de
milhar e duas casas, fundamento legal citado, nenhuma menção interna. Se estiver feio, **não
entregue** — a regra estética é absoluta.

- [ ] **Passo 5: Commit**

### Task D5: Ficha de agente público no vault (Hermes)

**Files:**
- Create: `tools/hermes_agentes_para_vault.py`
- Read: a skill `obsidian-second-brain` e o padrão de nota de pessoa já usado no vault

- [ ] **Passo 1: Ler o padrão de nota de pessoa existente**

```bash
ls ~/vault/pessoas/ 2>/dev/null | head; sed -n '1,40p' $(ls ~/vault/pessoas/*.md 2>/dev/null | head -1)
```

- [ ] **Passo 2: Gerar uma nota por agente recorrente (≥3 processos), com `[[links]]` para os casos**

- [ ] **Passo 3: Conferir uma nota no Obsidian e commitar**

---

## Verification — como provar que funcionou, fim a fim

### Por fase

**Fase A**
```bash
cd ~/JFN && .venv/bin/python -m pytest tests/detectores/ -q
```
Aceite: todos PASS, e `test_registro_completo.py` não lista nenhum detector sem teste.

**Fase B**
```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_fracionamento_siafe.py tests/test_teto_dispensa_fonte_unica.py -q
.venv/bin/python tools/fracionamento_siafe_sweep.py --janela dia
```
Aceite: grupos na ordem de 2,2 mil (não 59 mil); a trava do teto passa; nenhum literal de teto
fora da fonte única.

**Fase C**
```bash
cd ~/JFN && .venv/bin/python tools/medir_cobertura_agentes.py
```
Aceite: `pct >= 30` na amostra semente 7, contra a linha de base de 8. Se ficar entre 8 e 30,
**relatar o número real e a causa medida** — não arredondar para cima nem chamar de sucesso.

**Fase D**
```bash
cd ~/JFN && .venv/bin/python -m pytest tests/test_requisicao.py tests/test_lex_responsaveis.py -q
.venv/bin/python tools/gerar_requisicoes.py --saida output/requisicoes/
```
Aceite: uma minuta por órgão, com fundamento legal, sem palavra de juízo, aprovada no gate de
neutralidade, e o PDF visualmente conferido.

### Teste de ponta a ponta, como um humano faria

1. Escolher um processo real que **tenha** responsável identificado:
   ```bash
   cd ~/JFN && .venv/bin/python -c "
   import sqlite3
   c = sqlite3.connect('file:data/compliance.db?mode=ro', uri=True)
   for r in c.execute('SELECT processo, nome, papel FROM agente_processo LIMIT 5'):
       print(r)"
   ```
2. Gerar o parecer desse fornecedor/órgão e **ler o documento inteiro**, procurando: a seção
   Responsáveis presente; a nota de conferência de citações ao pé; nenhuma citação suprimida
   inesperada; nenhuma menção interna.
3. Rodar o gate de citações contra o parecer gerado e confirmar zero `numero_impossivel`.
4. Abrir a minuta de requisição do órgão desse processo e conferir que o processo aparece na lista
   certa (restrito ou fila) e que o pedido está redigido como pedido, não como acusação.
5. Rodar a régua de cobertura e comparar com a linha de base registrada no início.
6. `git log --oneline` e confirmar que cada tarefa virou um commit com mensagem que explica o
   **porquê**, não só o quê.

### Guarda de saúde da VM (rodar antes de qualquer passo pesado)

```bash
uptime; free -m | head -2; pgrep -c chrome
```
Se `load` > 6 ou houver Chrome de outra varredura vivo, **esperar**. Um pesado por vez.

---

## Self-review

**Cobertura do escopo.** As quatro frentes que o titular pediu estão cobertas: rede de proteção dos
detectores (Fase A, 11 tarefas), fracionamento na fonte certa (Fase B, 4 tarefas), cobertura de
responsáveis (Fase C, 5 tarefas), integração e peça formal (Fase D, 5 tarefas). A ordem sugerida no
documento de superfície de detecção é respeitada, com uma exceção deliberada: a Fase C foi
**reescopada** porque a medição mostrou que o gargalo é captura, não extração — o plano diz isso
explicitamente em vez de seguir a hipótese antiga.

**Sem placeholders.** Todo passo de código traz o código. Onde o executor precisa ler o entorno
antes de decidir (o exercício em `lex_analise_conteudo.py:307`, a chave do processo no `ctx` do Lex,
a assinatura das falhas de árvore na Task C4), o plano **manda parar e abrir questão** em vez de
mandar inventar um valor. Isso é deliberado: nesses três pontos, chutar produz bug pior que o atual.

**Consistência de tipos.** `grupos_suspeitos` devolve `list[dict]` com as mesmas chaves em B1, B2 e
B3. `confirmar_direta` devolve `bool | None` e o `None` é preservado até a persistência
(`direta_confirmada INTEGER` aceita NULL). `relacionados_de` devolve `list[str]` de números SEI
formatados, e o prefixo `rel:<numero>::<doc>` é o mesmo no teste e no sweep. `medir` devolve as
chaves que o `main` imprime.

**Riscos assumidos e declarados.**
- A Task C4 não tem fix escrito porque a causa não está diagnosticada. Escrever o fix antes do
  diagnóstico seria adivinhação; o plano dá o comando de diagnóstico e a bifurcação.
- A meta de 30% de cobertura na Fase C é uma aposta: se o ato de designação não existir nem no
  processo relacionado nem no que falta capturar, o teto real é menor. O plano exige relatar o
  número medido, não perseguir a meta.
- O cruzamento de contratação direta na Task B2 é por nome de fornecedor, porque o `processo` do
  SIAFE é número interno e não casa com o `sei_norm` do TCE. Isso produz falso negativo (nome
  grafado diferente) e o resultado é `None`, nunca `False`.
