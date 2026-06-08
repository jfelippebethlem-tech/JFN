# Direcionamento de licitação — pesquisa + spec do "cérebro" (LLM)

> **Pedido do dono (2026-06-08):** conluio entre licitantes é, na prática, **inviável** (faltam as propostas
> dos perdedores em dado estruturado público). O sinal de fato detectável é o **DIRECIONAMENTO** — no edital
> (exigências restritivas) e na **cascata de desclassificações/inabilitações** do julgamento. Não é parâmetro
> numérico simples: **precisa de "cérebro"** (LLM que lê o edital + a ata e raciocina). Esta é a pesquisa
> fundamentada + o design do cérebro. **Honesto:** indício a verificar, NUNCA acusação (presunção de
> legitimidade dos atos administrativos).

## 1. O sinal-mestre (insight do dono, confirmado por jurisprudência)
**Vencedor mal classificado em preço que vence após uma CASCATA de desclassificações/inabilitações por uma
exigência específica** (ex.: atestado de capacidade técnica muito particular). Ex.: a proposta vencedora era a
10ª mais barata e ganhou após 9 quedas por uma exigência de atestado. = forte indício de direcionamento.

## 2. Red flags de direcionamento (TCU/TCESP/TCDF + ACFE) — o que o cérebro procura
**No EDITAL (restritividade):**
- **Atestado de capacidade técnica restritivo** — idêntico ao objeto, com prazo/local específicos, parcela
  insignificante, ou **vedação de somatório de atestados** sem justificativa técnica (Súmula TCU 263).
- Exigência de **marca/modelo** ou de certificações/normas **sem comprovação de essencialidade**.
- Quantitativos mínimos desproporcionais; prazos exíguos; amostra/visita técnica restritiva.
- Falta de **estudo técnico** que justifique cada exigência (ETP/TR genérico).
**Na ATA DE JULGAMENTO (cascata):**
- **Alta taxa de desclassificação/inabilitação** + concentração dos motivos numa MESMA exigência.
- **Anomalia de ranking:** o vencedor estava longe do menor preço e subiu por quedas dos mais baratos.
- Quedas por **tecnicalidade** (atestado/formato) e não por preço/inexequibilidade.
- Recursos negados em bloco; reabertura/anulação seletiva.

## 3. Via de DADOS — PROVADA ao vivo (2026-06-08)
- **A ata de julgamento está no PNCP** (não só no SIGA): `collectors/pncp.baixar_documentos(id_pncp)` traz o
  **texto** dos documentos. Confirmado num caso RJ real (id `37115383000153-1-000028/2026`): a ata tinha
  **39.214 chars** com `desclassificação`×5, `inabilitação`×5, **`atestado`×4**, `vencedor`×12,
  `classificado`×14, `recurso`×7 — ou seja, **a cascata está no documento**.
- O **edital** também vem por `baixar_documentos` (já usado por `sei_direcionamento.varrer_direcionamento`).
- Alternativa/cadeia: o processo no **SEI-RJ** (login itkava) tem o extrato da licitação — mas o escopo de
  acesso limita (ver `docs/exemplos-sei/README.md`). **PNCP é a fonte primária** (público, sem browser).

## 4. O que JÁ EXISTE no JFN (não reconstruir)
- `compliance_agent/sei_direcionamento.py` — varre editais (PNCP+SEI) e roda os red flags do Lex
  (`lex.analisar_texto_edital`, R3/R5/R7/R9/R12) sobre o **texto do edital**. Cobre parte da restritividade.
- **GAP:** ninguém lê a **ATA DE JULGAMENTO** para a **cascata** (o sinal-mestre §1). E `analisar_texto_edital`
  é majoritariamente por **regra/keyword** — falta o "cérebro" (raciocínio) que o dono pede.

## 5. Design do CÉREBRO (a construir) — `compliance_agent/direcionamento_cerebro.py`
Função `avaliar_direcionamento(edital_txt, ata_txt, contexto) -> dict` que faz UMA chamada LLM (free LLM já
configurado: Groq/OpenRouter) com um prompt de auditor de controle externo e **saída por schema** (forçada),
para não alucinar. Camadas:
1. **Extrai da ata (cérebro):** lista de licitantes com {ordem_preço, valor, situação: classificado/
   desclassificado/inabilitado, motivo, dispositivo citado}. + o vencedor e sua ordem de preço original.
2. **Avalia o edital (cérebro):** exigências potencialmente restritivas, cada uma com o trecho + por que
   reduz competição + o paralelo de jurisprudência (Súmula TCU 263 etc.).
3. **Sintetiza o indício:** `grau` (🟢/🟡/🔴) + narrativa + **os trechos que sustentam** (proveniência) +
   ressalva de legitimidade. Calcula sinais objetivos auxiliares: `taxa_desclassificacao`,
   `motivo_dominante`, `anomalia_ranking_vencedor` (ordem de preço do vencedor / nº de quedas acima dele).

**Schema de saída (esboço):**
```json
{ "grau": "verde|amarelo|vermelho",
  "taxa_desclassificacao": 0.0, "motivo_dominante": "atestado X",
  "vencedor": {"nome": "", "ordem_preco_original": 10, "subiu_por_quedas": 9},
  "exigencias_restritivas": [{"trecho": "", "por_que": "", "jurisprudencia": "Súmula TCU 263"}],
  "cascata": [{"licitante": "", "ordem_preco": 1, "situacao": "desclassificado", "motivo": "", "trecho": ""}],
  "parecer": "indício a verificar — narrativa", "ressalva": "presunção de legitimidade; não é acusação" }
```
**Guardrails (cláusula de honestidade do JFN):** o prompt PROÍBE afirmar irregularidade; exige citar o
**trecho** de cada achado; se a ata não trouxer ranking/motivos, retorna `grau=verde` + "dados insuficientes"
(nunca inventa). Integra como nova regra do Lex (ex.: **R-DIR**) e alimenta o parecer.

## 6. Próximos passos sugeridos (a confirmar com o dono)
1. Construir `direcionamento_cerebro.py` (§5) + teste com a ata real (mock do LLM no teste).
2. Ligar em `sei_direcionamento.varrer_direcionamento` (quando há ata, roda o cérebro) e no parecer do Lex.
3. **Calibrar com casos reais:** rodar sobre N atas RJ e revisar os 🔴 manualmente (o "ver casos reais com
   documentos" que o dono pediu) antes de expor no /relatorio.
4. Rota `/api/direcionamento?id_pncp=` + capability (auto-entra no /lista).

## Fontes (jurisprudência)
- TCU — Habilitação Técnica / Súmula 263 (vedação de somatório de atestados): licitacoesecontratos.tcu.gov.br
- TCU — exigência de normas/certificações sem essencialidade é irregular.
- TCDF Pesquisa 22/2021 — restrição indevida no edital (ofensa à competitividade).
- ACFE Report to the Nations — alta taxa de desclassificação como red flag de procurement fraud.
