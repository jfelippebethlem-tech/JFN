# Design — Municipalizar o JFN (Prefeitura do Rio) · Lex + Detectores + Entrega

**Data:** 2026-07-19 · **Branch:** `feat/fiscalizacao-emendas-pcrj` · **Autor:** Claude Fable 5 (autônomo, meta `/goal`)

## 1. Problema

O JFN nasceu para o **Estado do RJ** (TCE-RJ, SIAFE). A camada municipal (Prefeitura do Rio)
cresceu em silo — o pacote `compliance_agent/pcrj/` tem 43 módulos, 12M linhas de folha, 7,3M
benefícios, D.O. do Município, PPPs — mas três lacunas estruturais impedem que o investigador
municipal use a plataforma no mesmo nível do estadual:

1. **Lex é cego para a esfera municipal.** Nenhum `lex*.py` importa `pcrj/esfera.py`. Um parecer
   sobre contrato da Prefeitura roteia destinatários para **TCE-RJ** e cita **Lei RJ 5.427/2009**
   (processo administrativo *estadual*) — quando a competência é do **TCM-RJ** e a norma é
   municipal. Isso é um **defeito de correção**: o parecer sai juridicamente errado.
2. **Corpus do D.O. RIO (`pcrj_doe_materia.texto`) está cru.** 262 matérias com atas de registro
   de preços item-a-item, CNPJ vencedor, preço unitário, empenho e — sinal municipal marcante —
   compras hospitalares conduzidas por **e-mail @gmail.com pessoal**. Nada disso é estruturado
   nem vira detector.
3. **Alcance de entrega.** Os 16 detectores "Transversais" mais fortes (fênix, porta giratória,
   nepotismo, capital irrisório, corrida de dezembro, sócio-servidor) **não têm filtro por esfera**
   no painel; o investigador do Rio enxerga só 8 abas municipais. Não existe comando `/pcrj`.

## 2. Objetivo

Elevar Lex, os detectores e a entrega ao mesmo patamar municipal do estadual, **sem cortes
destrutivos** (esfera é dimensão de consulta, não filtro que joga dado fora — princípio já firmado
em `pcrj/esfera.py`) e **sem reinventar** o que o pacote `pcrj/` já faz.

## 3. Escopo — 3 pilares

### Pilar A — Lex ganha jurisdição municipal (correção) · **build nesta sessão**
Gate de esfera em Lex: quando o órgão/contrato é `municipal-rio` (via `pcrj.esfera.classificar_esfera`),
o roteamento de destinatários, a base sancionatória e os rótulos de jurisdição passam a **TCM-RJ /
PGM-Rio / MP-RJ (promotorias de tutela do patrimônio público)** e citam a norma municipal
(Lei Rio 5.026/2019 para OS; regulamento municipal da 14.133). Função pura, testável, cirúrgica.
Honestidade: esfera `indefinido` → mantém o comportamento atual (não chuta jurisdição).

### Pilar B — Detectores municipais novos (descoberta) · **build nesta sessão**
Somente onde o dado **já existe** e o risco de falso-positivo é controlável, com a ressalva da casa
(indício ≠ acusação; empenho ≠ pago; INDISPONÍVEL ≠ 0):

- **B1 · Minerador do D.O. RIO** (`pcrj_doe_materia.texto` → eventos estruturados): ata nº, item,
  CNPJ vencedor, preço unitário/total, empenho (`NNNNNE...`, rotulado **empenho**, nunca "pago"),
  processo. Alimenta:
  - **B1a Sobrepreço municipal item-a-item** (mediana robusta por item entre atas — mesma régua do
    `sobrepreco` estadual, mas na fonte municipal).
  - **B1b Concentração de vencedor** por órgão gestor da ata.
  - **B1c Canal informal `@gmail.com`** — hospital/órgão municipal conduzindo "pesquisa de mercado"
    e retirada de empenho por e-mail pessoal (baixa transparência, vetor de direcionamento).
- **B2 · Aditivo-salame** (sequência de aditivos, cada `<25%`, soma `>25%/50%` — art. 125/126
  da 14.133): fecha o buraco do `aditivos_estouro` (que só olha o total vg−vi).
- **B3 · Duplicidade de documento fiscal** — mesmo doc fiscal (`re`/`nl`) em 2+ OBs ao mesmo credor
  (complementa `duplicidade_competencia`, que deixa "mesma NF" de fora de propósito).
- **B4 · Sancionadas contratadas — Município** — análogo do `sancionadas_contratadas` (hoje só
  SIAFE-Estado) repontado a `pcrj_contratos`/`pcrj_despesa`, com teste "à época" + `sancao_abrangencia`.

Cada detector: função em `cruzamentos_intel.py` (ou módulo dedicado) retornando `{ok, n, achados,
ressalva}`, materializada em `data/cache/*.json`, exposta em `/api/intel/*`, com teste.

### Pilar C — Alcance de entrega (uso) · **roadmap, parcial nesta sessão**
- **C1** parâmetro `?esfera=prefeitura` nos endpoints `/api/intel/*` Transversais (backend; baixo risco).
- **C2** comando/digest `/pcrj` agregando `/api/pcrj/*` + os novos detectores.
- **C3** abas/filtros no painel (`static/jfn-painel.html`) — maior superfície, fase seguinte.

## 4. Não-objetivos (YAGNI)
- Não abrir novas coletas de rede pesadas nesta sessão (SEI.RIO/reCAPTCHA, D.O. full-text,
  Nota Carioca, obras) — são fases de coleta próprias; ficam registradas como lacunas de dado.
- Não mexer no `compliance.db` (hub live) além de leitura; materializar em `pcrj.db`/cache.
- Não refatorar o painel de 202KB neste passo.

## 5. Verificação
- `pytest` novo por detector (fixture com DB sintético pequeno) + guardas anti-FP explícitas.
- `gitnexus_impact` antes de editar símbolo existente (Lex); `gitnexus_detect_changes` antes de commit.
- Commit por unidade, msg semântica, `Co-Authored-By: Claude Fable 5`.
- Regenerar golden de rotas se novos endpoints entrarem no lote testado.

## 6. Lacunas de dado registradas (para fases de coleta futuras)
SEI.RIO/SIGA (processo=0, reCAPTCHA) · D.O. RIO full-text (só 262 termos de saúde) · despesa/OB
2024+ (ContasRio para em 2023) · Nota Carioca/ISS · OSC/contratos de gestão (só 13 PDFs) · obras
(SISOBRAS) · filiação partidária pós-2018 · base TSE candidatos completa.
