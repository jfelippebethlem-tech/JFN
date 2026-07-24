# Plano — Interpretação SEI além de direcionamento (#4)

> ## STATUS DE EXECUÇÃO — 2026-07-24 (sessão seguinte)
>
> | Item | Situação | Onde |
> |---|---|---|
> | 1.4 OB ≠ empenho (§2) | ✅ feito | `execucao_sinais.estagio_despesa` + teto amarelo sem OB (`dfb30e47`) |
> | 1.1 Atesto faz-sentido (LLM) | ✅ feito | `execucao_cerebro.avaliar_coerencia_atesto` (`60828ce4`) |
> | 1.5 Fusão + snapshot execução | ✅ feito | `execucao_cerebro.avaliar_execucao` / `guardar_snapshot_execucao` |
> | 1.3 NF-e | ✅ offline completo · live PENDENTE DE DECISÃO | `nfe_verifica` (chave/DV/tpEmis); `situacao()` injetável |
> | 2.1 Aditivo · 2.2 Antecipado · 2.3 Fracionamento | ⚠️ **replanejado — a regra JÁ EXISTIA** | X1 / X3 / P4 já cobrem; entregue a PONTE `execucao_fatos.py` (`a35bc95e`) |
> | 1.2 VLM foto | ⛔ não iniciado — depende de decisão de custo do dono | — |
> | **PGE: cumprimento de condicionantes** (fora do plano, pedido do dono) | ✅ feito | `parecer_cumprimento.py` (`ee2add3b`), calibrado em 296 processos reais |
>
> **Decisões DECIDIDAS pelo dono (2026-07-24, mesma noite) — nenhuma pendência aberta:**
>
> | Questão | Decisão | Resultado |
> |---|---|---|
> | Consulta live à SEFAZ | **nada pago** — certificado A1 e agregador fora | portal público + `ddddocr` local (já roda no sweep SEI-PCRJ da VM-2); contingência continua saindo da chave, offline |
> | VLM do relatório fotográfico | **gratuito**, e não Mapillary | `foto_medicao.py`: reciclagem por dHash (offline, sem IA) + VLM local injetado (moondream2 / SmolVLM em llama.cpp na VM-2) |
> | Fracionamento sobre o SIAFE | **seguir** | `fracionamento_siafe.py` — triagem por UG+credor+exercício com data e OB paga; grau sempre `a_verificar` (a fonte não tem objeto nem modalidade) |
>
> **1.2 e 2.3-SIAFE entregues** (`95f9bbab`). O que o dado real corrigiu, em ambos, está nos docstrings —
> página em branco, folha de ponto, OB excluída, órgão público, concessionária e parcelas do mesmo processo
> eram falsos positivos que só apareceram ao rodar sobre 5.525 fotos e 60 mil Ordens Bancárias.


**Data:** 2026-07-24 · **Autor:** Claude (sessão fusão/obtenção/storage) · **Status:** plano para NOVA SESSÃO
**Contexto-pai:** esta sessão entregou o direcionamento completo (fusão det×LLM, veredito resolvido, ponte de
obtenção, storage versionado B2/R2) + o **primeiro** detector de execução (`compliance_agent/execucao_sinais.py`,
determinístico, 9 testes). Este documento é o roteiro **detalhado** do que falta, para retomar sem perda.

> **Princípios herdados (não renegociar):** determinístico **+** subjetivo combinados via `fundir_graus`;
> veredito **sempre resolvido** (nunca `indeterminado`/`indisponivel`); **honestidade** (INDISPONÍVEL ≠
> irregular; indício ≠ acusação; cada achado com trecho literal); **§2: Empenho ≠ Liquidação ≠ OB — só a
> Ordem Bancária é "pago"**; cada análise vira **snapshot versionado** (`analise_remotes`); TDD offline.

---

## 0. O que JÁ foi feito (base para o resto)

| Peça | Arquivo | Reuso pelo resto |
|---|---|---|
| Fusão det×LLM (nunca silencia alarme + divergência) | `direcionamento_cerebro.fundir_graus/_com_fusao` | **toda** família nova usa |
| Storage versionado por hash da captura | `compliance_agent/analise_remotes.py` | snapshot de qualquer análise |
| Ponte de obtenção (busca doc que falta) | `direcionamento_cerebro.obter_edital_ata` | modelo p/ buscar NF/medição |
| Classificador de doc | `compliance_agent/sei/classificador_doc.py` | rotear peças do processo |
| **Execução sem comprovação (determinístico)** | `compliance_agent/execucao_sinais.py` | ampliar (itens 1–3 abaixo) |

---

## 1. Aprofundar `execucao_sinais` — o que o dono pediu (2026-07-24)

O detector atual já sinaliza (determinístico, texto): falta de medição/NF/atesto, **atesto sem relatório
fotográfico**, e menção a **NF cancelada / em contingência**. Falta a camada que **verifica de verdade**:

### 1.1 Atesto "FAZ SENTIDO?" (coerência) — camada SUBJETIVA/LLM
- **Problema:** um atesto pode existir e ser meramente formal (carimbo). Precisa bater com a medição e o objeto.
- **Método:** prompt ao LLM (padrão do `direcionamento_cerebro`) com {texto do atesto, boletim de medição,
  objeto do contrato} → pergunta: o atesto é coerente com a medição (quantidades/datas/itens) e com o objeto?
  Sinais de incoerência: atesto genérico, data anterior à medição, quantidade divergente, "de acordo" sem detalhe.
- **Saída:** `coerente: bool`, `incoerencias: [trecho]`, grau. **Fundir** com o determinístico (`fundir_graus`).
- **Honesto:** sem os 3 documentos → `pendente_captura`/`obter` (buscar a medição, como a ponte de edital/ata).

### 1.2 Relatório fotográfico CORRESPONDE ao objeto? — camada VLM (visão)
- **Problema:** foto pode ser genérica/reciclada/não corresponder ao objeto medido.
- **Método:** as fotos de medição já são baixadas em `data/sei_arquivo/<proc>/fotos/`. Rodar VLM (o mesmo do
  `fachada`/Street View já existe no projeto) para descrever a foto e comparar com o objeto. Sinal: foto não
  bate com objeto, foto duplicada entre processos (hash perceptual), EXIF ausente/inconsistente.
- **Cautela §4.1:** VLM pago → estimar custo; preferir modelo local/gratuito. Rodar só nos casos amarelo/vermelho.

### 1.3 NF-e: cancelada? em contingência? — VERIFICAÇÃO LIVE na SEFAZ ("dá pra saber?" → SIM)
- **Chave:** extrair a **chave de acesso NF-e (44 dígitos)** do texto/PDF do processo (regex `\d{44}` + validação
  do DV mod 11). A chave carrega UF, AAMM, CNPJ emitente, modelo, série, número, tpEmis (1=normal, 4/9=contingência).
- **Status:** consultar a situação na SEFAZ:
  - **tpEmis** (posição 35 da chave) já revela **contingência** sem rede (4=SCAN/SVC, 9=EPEC, etc.).
  - Situação **autorizada/cancelada/denegada/inutilizada**: consulta ao webservice `NfeConsultaProtocolo`
    (exige certificado A1) OU ao portal público `nfe.fazenda.gov.br`/portais estaduais via chave (sem cert,
    com captcha) OU serviços agregadores. **Decisão de custo/credencial pendente do dono** (§4.1).
  - Sinal **vermelho forte:** NF **cancelada/denegada** lastreando OB paga (§2: OB = pagou de verdade).
- **Entregável:** `compliance_agent/nfe_verifica.py` — `extrair_chaves(texto)`, `tp_emissao(chave)` (offline),
  `situacao(chave)` (live, injetável p/ teste). Fundir no veredito de execução.
- **Honesto:** sem chave → registrar `a_verificar` (não afirmar); sem rede/cert → reportar "não verificado", nunca inventar.

### 1.4 Calibração: chave no OB, não no empenho (§2)
- Hoje `_PAGAMENTO` inclui empenho/liquidação/OB. **Refinar:** OB presente = pagamento EFETIVO (peso alto);
  empenho-só = compromisso (pode ser cancelado) → fragilidade mais fraca. Adicionar `tem_ob` distinto de `tem_empenho`.

### 1.5 Fusão + snapshot da execução (fechar o ciclo, igual ao direcionamento)
- `avaliar_execucao(texto, gerar=...)`: roda `execucao_sinais` (det) + LLM (coerência 1.1) → `fundir_graus`.
- Persistir + `analise_remotes.guardar_analise` (snapshot versionado). Wiring espelha `sei_direcionamento_llm.avaliar_top`.

---

## 2. Outras famílias de irregularidade (mesma receita: det → resolvido → fusão → snapshot)

### 2.1 Aditivo além do limite legal
- **Regra:** acréscimo/supressão cumulativa > **25%** (obras/serviços/compras) ou **50%** (reforma de edifício/equip.) — art. 125 Lei 14.133/2021.
- **Determinístico:** regex `aditivo` + percentual (`acr[ée]scimo de (\d+)%`, "valor aditado", somar aditivos do processo). Flag quando soma > limite.
- **Cautela FP:** distinguir reajuste/repactuação (índice, permitido) de aditivo quantitativo; "prorrogação de prazo" ≠ acréscimo de valor.
- **Entregável:** `aditivo_sinais.py` + fusão + snapshot.

### 2.2 Pagamento antecipado
- **Regra:** vedação de pagamento antes da entrega/execução, salvo exceções com garantia (art. 145 Lei 14.133).
- **Determinístico:** "pagamento antecipado", "antecipação de pagamento", "adiantamento", data de OB **anterior** à medição/entrega.
- **Cautela FP:** "sinal"/"entrada" contratual legítimo com garantia; empenho ≠ pagamento (§2).

### 2.3 Fracionamento de despesa
- **Regra:** múltiplas dispensas/compras do MESMO objeto e fornecedor no exercício para escapar da modalidade (art. 75 §1º).
- **NÃO é de texto único:** exige **cruzar vários processos/OBs** (mesmo objeto+fornecedor+ano, somatório > limite de dispensa).
  Reusar `compliance.db` (`ob_orcamentaria_siafe`) + `limites_dispensa.py`. Determinístico agregado, não por-texto.
- **Entregável:** query + `fracionamento_sinais.py`; snapshot por fornecedor+objeto+ano.

---

## 3. Ordem sugerida na nova sessão

1. **1.4** (OB vs empenho — refino barato, alto valor §2) → **1.1** (atesto faz-sentido, LLM) → **1.5** (fusão+snapshot execução). Fecha a execução ponta a ponta.
2. **1.3** NF-e (offline tpEmis primeiro; live SEFAZ após decisão de custo/cert do dono).
3. **2.1 Aditivo** (determinístico limpo) → **2.2 Antecipado**.
4. **1.2** VLM foto (custo — confirmar com o dono) e **2.3 Fracionamento** (agregado, mais pesado).

## 4. Definição de pronto (cada item)
- TDD offline (injeção p/ rede/LLM/VLM), veredito resolvido, honesto, trecho literal, snapshot versionado.
- `detect_changes` antes do commit; catracas de except verdes; sem regressão na suíte.
- Segunda-cérebro: nota em `memory/` + `~/vault` ao fechar cada família.

## 5. Riscos / decisões pendentes do dono
- **NF-e live:** certificado A1 (custo/segurança) vs portal público com captcha vs agregador pago (§4.1). **Decidir.**
- **VLM foto:** custo por imagem; preferir local. **Decidir** antes de ligar em volume.
- **Fracionamento:** definir limite/critério de "mesmo objeto" (similaridade textual) — calibrar com o dono.
