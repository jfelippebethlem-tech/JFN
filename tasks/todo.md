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
- [ ] **M1** Benford (MD) · **M2** anomalias · **M3** decisões TCE · **M4** receita×despesa (órgão) ·
      **M5** conflito de endereços · **M6** co-ocorrência de sócios · **M7** OpenSanctions detalhado ·
      **M8** gazetas estruturado · **M9** tipo de processo SEI · **M10** consórcio. (cada um: dado+leitura+conclusão)
- [ ] **Checkpoint F3** + revisão final (agent-skills:review) + medição PDF completa.

## Em curso / feito
- [x] Sweep de benefícios sócios/admin (detached) + fix BF anoMesReferencia — commitado (cont.20).
