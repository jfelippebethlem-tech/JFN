# TODO — Relatórios JFN 100% completos + inteligentes

> **Princípio transversal (dono):** cada seção nova = (a) **dado COMPLETO** (todos os campos, não resumido) +
> (b) **leitura inteligente em prosa** (o que significa, indício/AFASTADO/INDISPONÍVEL, base legal) +
> (c) **alimenta a CONCLUSÃO** (o sinal entra no `_fatos_para_raciocinio`/`_fatos_orgao` da análise raciocinada
> e, quando for indício, no grau/score final). Não é tabela solta: é tabela + raciocínio + conclusão.
> TDD, honestidade, CPF mascarado, VM-safe, medir o PDF real, 1 commit/unidade.

## FASE 1 — Benefícios dos sócios/administradores (laranja) [dado pronto: socio_beneficio]
- [ ] **F1.T1** `reporting/beneficios_view.py`: `agregar_por_cnpjs(cnpjs, db)` + `por_fornecedor(cnpj, db)` ⋈
      `socio_beneficio`×`socios_fornecedor`. Retorna {n_socios,n_resolvidos,n_com_beneficio,n_indisponivel,
      cobertura, itens[{nome_mascarado,papel,fonte,recebe,tipos}]}. **Teste** com DB temp. **Aceite:** verde + honesto.
- [ ] **F1.T2** Órgão §1-F `_secao_beneficios_md` + `ctx["beneficios_socios"]` em `montar()`: agregado da UG
      ("N de M sócios/administradores verificados recebem benefício de subsistência — indício de laranja") +
      **prosa de conclusão** + INDISPONÍVEL honesto. Entra no `_fatos_orgao` (raciocínio). PDF idem. Render real 036100.
- [ ] **F1.T3** Fornecedor: bloco por-CNPJ em §1-B/§9 (quais sócios/admin resolvidos recebem; mascarado) +
      leitura. Entra no `_fatos_para_raciocinio` + (se indício) no grau. Render real de 1 fornecedor.
- [ ] **F1.T4** Lex II-E: linha agregada ("N de M sócios verificados recebem benefício") acima das hipóteses.
- [ ] **Checkpoint F1:** testes verdes + 1 PDF órgão + 1 PDF fornecedor inspecionados + §10 doc + CPU ok.

## FASE 2 — Gaps ALTA com dado pronto (cada um: dado + leitura + conclusão)
- [ ] **A8** Capital social × recebido (H-CAPITAL) — §1 fornecedor + leitura "porte incompatível?" + grau.
- [ ] **A7** QSA detalhe (participação %, qualificação, entrada/saída) — §1 + leitura estrutura societária.
- [ ] **A1** Aditivos contratuais [VERIFICAR colunas populadas] — §4 + leitura limite 25%/50% (Lei 8.666 art.65).
- [ ] **A3** Doações eleitorais TSE no MD (portar do PDF) — nova seção + leitura conflito doador↔contrato.
- [ ] **A4** Rodízio/cartel no fornecedor (`rodizio_temporal`) — §5 + leitura bid rotation.
- [ ] **A2** Empenho→Liquidação→OB [VERIFICAR colunas] — §2 + leitura execução incompleta.
- [ ] **A5** Regularidade fiscal/previdenciária (`registry_providers`, async/bounded) — §1 + leitura.
- [ ] **A6** Terceirizados (conflito de pessoal) — nova seção + leitura incompatibilidade.
- [ ] **Checkpoint F2.**

## FASE 3 — Gaps MÉDIA
- [ ] **M1** Benford (MD) · **M2** anomalias · **M3** decisões TCE · **M4** receita×despesa (órgão) ·
      **M5** conflito de endereços · **M6** co-ocorrência de sócios · **M7** OpenSanctions detalhado ·
      **M8** gazetas estruturado · **M9** tipo de processo SEI · **M10** consórcio. (cada um: dado+leitura+conclusão)
- [ ] **Checkpoint F3** + revisão final (agent-skills:review) + medição PDF completa.

## Em curso / feito
- [x] Sweep de benefícios sócios/admin (detached) + fix BF anoMesReferencia — commitado (cont.20).
