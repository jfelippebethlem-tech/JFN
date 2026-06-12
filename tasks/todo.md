# TODO — Relatórios JFN 100% completos + inteligentes

> **Princípio transversal (dono):** cada seção nova = (a) **dado COMPLETO** (todos os campos, não resumido) +
> (b) **leitura inteligente em prosa** (o que significa, indício/AFASTADO/INDISPONÍVEL, base legal) +
> (c) **alimenta a CONCLUSÃO** (o sinal entra no `_fatos_para_raciocinio`/`_fatos_orgao` da análise raciocinada
> e, quando for indício, no grau/score final). Não é tabela solta: é tabela + raciocínio + conclusão.
> TDD, honestidade, CPF mascarado, VM-safe, medir o PDF real, 1 commit/unidade.

## FASE 1 — Benefícios dos sócios/administradores (laranja) [dado pronto: socio_beneficio] ✅
- [x] **F1.T1** `reporting/beneficios_view.py`: agregar_por_cnpjs/por_fornecedor/leitura ⋈ socio_beneficio×
      socios_fornecedor (indício/AFASTADO/INDISPONÍVEL). +5 testes. Commit 406abed.
- [x] **F1.T2** Órgão §1-F (MD+PDF) + `ctx["beneficios_socios"]` + `_fatos_orgao`. Medido real (036100). Commit f014165.
- [x] **F1.T3** Fornecedor §1-C (MD) + `_fatos_para_raciocinio`. Medido real (13210413000142). Commit 8edffd0.
- [x] **F1.T4** Lex II-E: agregado do sweep acima das hipóteses. Commit 0f5ef6a.
- [~] **Checkpoint F1:** testes verdes (rodando) + PDF órgão inspecionado ✅ + §10 doc. **Pendente p/ paridade:**
      fornecedor **PDF** (render_pdf_html) ainda sem a 1-C — fazer na próxima passada (MD já completo).

## FASE 2 — Gaps ALTA com dado pronto (cada um: dado + leitura + conclusão)
- [x] **A3** Doações eleitorais TSE no MD (conflito doador↔contrato) — §1-D fornecedor. Commit 6e50b15.
- [x] **A8** Capital social × recebido (H-CAPITAL) — §1 + leitura subcapitalização + raciocínio. Commit (a seguir).
- [~] **A7** QSA detalhe — qualificação + entrada JÁ em §1 (MD/PDF). Participação %/data-saída **NÃO coletados**
      (não há na base) → exigiria coletor novo; fora do escopo de *surfar*. Marcado como coberto no possível.
- [⛔] **A1** Aditivos contratuais — **SEM DADO** (tabela `contratos` não tem colunas de aditivo). Vira "coletar
      aditivos" (coletor novo), fora do escopo de *surfar campos existentes*.
- [⛔] **A2** Empenho→Liquidação→OB — **SEM DADO** (`ordens_bancarias` não tem empenho/liquidação). Idem A1.
- [x] **A4** Rodízio/cartel no fornecedor (`rodizio_temporal`) — §1-E (bounded top-3 UGs). Commit d2e023b.
- [⛔] **A5** Regularidade fiscal/previdenciária — **SEM DADO de débito** (`registry_providers` só traz cadastral;
      situação cadastral já em §1). INSS/ICMS/PGFN/CND = coletor novo (gated). Fora do escopo de *surfar*.
- [x] **A6** Conflito de pessoal (sócio na folha do Estado) — §1-F, `conflito_pessoal_view`. Commit b62fe6b.
- [x] **Checkpoint F2:** 106 passed/0 failed. Fornecedor render real com 1-B…1-F + capital. §10 atualizado.
      **Achado honesto:** A1/A2/A5 do inventário NÃO têm dado na base (colunas/feeds inexistentes) → viram
      "coletar primeiro", não "surfar". O surfar de campos existentes na Fase 2 está completo.

## FASE 3 — Gaps MÉDIA
- [x] **M1** Benford no MD (§8-B fornecedor) — paridade com PDF. Commit c1c0bff.
- [x] **M2** Anomalias do modelo (§8-C fornecedor, `ob_anomaly` 1M ⋈ OBs). Commit c3a810b.
- [⛔] **M3** decisões TCE — `decisoes_tce`=0 linhas (live/async). MAS `penalidades_tcerj` (910, sanções a
      ÓRGÃOS) é surfável no relatório de ÓRGÃO por match de nome (pendente).
- [⛔] **M3** penalidades_tcerj — dado existe (910) mas SEM chave de join confiável (nomes abreviados ≠ UG);
      match fuzzy arriscaria atribuição errada → **honestidade veta**. Precisa de mapa órgão→UG curado.
- [~] **M6** co-ocorrência de sócios — JÁ surfada no §1-B (empresas com sócio em comum). **M8** gazetas — JÁ no
      §1-B/raciocínio (Querido Diário). **M9** tipo de processo SEI — JÁ no Lex II-B. (duplicados; não re-surfar)
- [ ] **M4** receita×despesa (estado, `tfe_receita` CSV) — contexto orçamentário; mais esforço, valor médio. ·
      **M7** OpenSanctions (API externa) · **M10** consórcio (não coletado).
- [x] **jfn.service REINICIADO** → seções novas (Fases 1/2/3) VIVAS; API servindo; fornecedor end-to-end OK.

## CONCLUSÃO HONESTA (cont.20)
**O surfar de TODO sinal com DADO REAL + JOIN CONFIÁVEL está COMPLETO** (Fases 1, 2 e Fase 3 M1/M2).
O que falta para "100%" exige trabalho FORA do escopo de *surfar campos existentes*:
- **Coletores novos** (A1 aditivos, A2 empenho→liquidação→OB, A5 débito fiscal, M10 consórcio) — não há o dado.
- **Mapa de join curado** (M3 órgão→UG) — sem chave confiável, fuzzy é desonesto.
- **APIs externas** (M7 OpenSanctions).
- **Subir cobertura de CPF** (~4,7%) via parsing de SEI/procurações (traz procuradores).
- **Yoda:** poller externo (ação do dono — §9).

## RESOLUÇÃO DE CPF — arquitetura completa (cont.20) + CONCLUSÃO HONESTA
- [x] **Engine de CPF legal/sem-leak:** bridge favorecidos+TSE (~5%) + **SEI CPF sweep** (`compliance_agent/sei/
      extrair_cpf` DV-validado + `tools/sei_cpf_sweep` + leitor SEI prioriza contrato social/procuração, lê 12 docs)
      + `resolucao_cpf.carregar_indice_sei`/`sei_idx` (3ª fonte, conf 0.9; **provado: resolve sócios**) +
      `ingerir_cpf_oficial` (qualquer lista nome,cpf → valida DV + `confirmar_cpf` anti-homônimo contra a máscara) +
      `gerar_cpfs_da_mascara` (1000 candidatos válidos — calculadora, não método) + `cadastro_pf_providers` (genérico).
- [x] **SEI CPF sweep integrado ao supervisor** (cada lote extrai CPF); cresce diário (cron 07:00, leitor novo).
- ⚠️ **CONCLUSÃO (testado ao vivo):** toda fonte GRÁTIS mascara CPF de PF (cnpj.ws, Portal API, Querido Diário,
      PNCP = 0/mascarado). Nome→CPF completo em massa só vem de **bureau pago** (dono vetou) ou **leak** (não construo
      harvester). Teto grátis ~5% + SEI (cresce). **Para 100%: dono passa CSV `nome,cpf` → `ingerir_cpf_oficial`.**
- [⛔] **Yoda 100%:** poller externo em OUTRA máquina (provado: gateway parado → 409 + 0 conexões locais). Ação do
      dono: BotFather `/revoke` → novo token no `~/.hermes/.env` → restart gateway. (Agente/relatórios/envio OK.)

## SUÍTE DE TESTES (cont.20): 8 → 2 falhas
- [x] Corrigidos 6 testes STALE: verificacao_endereco ×2 (pré-Mapillary), skilltree (menu 16→24), hermes ×3 (Qwen
      virou 1º na cascata, não mockavam). Commits b716d42, 8a32322, 42c5c86.
- [ ] **2 restantes = ambientais/perf** (não-lógica): `test_goal_agent_ciclo_autonomo` trava (full-scan na DB
      1,2GB → precisa fixture/temp-DB; `DB_PATH` é hardcoded, `trabalhar()` usa a DB direto) · `test_sei_cdp_sem_
      chrome` depende do estado do Chrome 9222. Baixa prioridade (não são bugs de produto).

## Em curso / feito
- [x] Sweep de benefícios sócios/admin (detached) + fix BF anoMesReferencia — commitado (cont.20).

## AUDITORIA + BUGS REAIS CORRIGIDOS (cont.20, foco em FUNCIONALIDADE)
- [x] **🐛 A6 conflito de pessoal** cruzava CPF completo×mascarado → nunca casava. FIX: nome+5díg (posições 4-8).
      Acha **7 conflitos reais** (sócios = Defensor Público/cargo em comissão). Índice folha cacheado. Commit 85944bd.
- [x] **🐛 §1-E endereço do órgão (PRÉ-EXISTENTE)** usava `MAX(favorecido)` (coluna inexistente) → seção SUMIA
      quando tinha indícios. FIX: `favorecido_nome`. Restaura 7 indícios no Fundo 036100. Commit ecc4c93.
- [x] +4 fixes (cobertura>100%, mode=ro, dedup, parsing) + hardening (logging nas seções, commit 84f59af).
- [x] **Auditoria adversarial sistemática** (3 agentes) de TODO o pipeline de relatório → **zero** outros bugs de
      coluna/query. Código de relatório confirmado SÓLIDO. (Diminishing returns no hunt.)
- [x] **PDF=MD** (paridade total fornecedor) + Fases 1/2/3 VIVAS (jfn.service reiniciado).
