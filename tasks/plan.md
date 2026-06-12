# Plano — Relatórios JFN 100% completos (todos os campos/funções/resultados)

> Meta do dono: surfar TODOS os sinais que já existem no código mas não aparecem (ou aparecem resumidos)
> nos relatórios de **fornecedor** (`compliance_agent/reporting/inteligencia.py`), **órgão**
> (`.../inteligencia_orgao.py`) e no parecer **Lex** (`compliance_agent/lex.py`). "Completo, não resumido."
> Cada item é uma **fatia vertical** (dado → seção → teste → medição no PDF real → commit). TDD obrigatório,
> honestidade (indício≠acusação, INDISPONÍVEL≠0, CPF mascarado/LGPD), VM-safe, LLM nos produtos só async/bounded.

## Arquitetura real (âncoras verificadas)
- **Fornecedor** `inteligencia.py`: `montar()` (l.473, async) monta o `ctx`; `render_md(ctx)` (l.841) emite as
  seções 1, 1-B, 2, 3, 4, 4-B, 5..11. Perfil/QSA em **§1 (l.879)**; Contratos em **§4 (l.976)**. Novos dados →
  buscar em `montar()` (ou helper bounded) e renderizar em `render_md`. PDF: `render_pdf_html` (já traz TSE/OSINT).
- **Órgão** `inteligencia_orgao.py`: `montar()` (l.246) seta `ctx["dd_orgao"]`/`ctx["endereco_real"]`;
  `render_md` (l.692) emite 1, 1-B, 1-C, **1-D** (`_secao_dd_md`), **1-E** (`_secao_endereco_md`), 2..5.
  Nova seção de benefícios = **1-F** (`_secao_beneficios_md`) + `ctx["beneficios_socios"]` em `montar()`.
- **Lex** `lex.py`: II-E já apresenta a investigação DD por-pessoa (H-BENEFICIO/H-PEP existem). Falta o AGREGADO.

## Princípio de honestidade (vale p/ TODAS as seções)
Toda seção nova distingue 3 estados: **achado/indício** (com evidência+fonte+base legal), **AFASTADO**
(verificado, negativo) e **INDISPONÍVEL** (não deu p/ verificar — nunca tratar como 0/limpo). CPF de sócio
sempre mascarado no produto. Indício, nunca acusação.

## Grafo de dependências
- **Fundação F1** (helper agregador de `socio_beneficio` por CNPJ) → destrava P1.T2 (órgão) e P1.T3 (fornecedor).
- Demais itens ALTA/MÉDIA são independentes entre si (cada um lê sua própria fonte) → paralelizáveis, mas
  entregues em série (1 commit/unidade) p/ medir o PDF a cada passo.

## Fases (ordem por valor × prontidão do dado)

### FASE 1 — Benefícios dos sócios/administradores (laranja) — o sweep recém-criado
Dado JÁ existe (`socio_beneficio`, populando via supervisor). Maior valor novo.
- **F1.T1** Helper `beneficios_view.agregar_por_cnpjs(cnpjs)` + `por_fornecedor(cnpj)` (lê `socio_beneficio`
  ⋈ `socios_fornecedor`): retorna {n_socios, n_resolvidos, n_com_beneficio, n_indisponivel, itens[]} honesto.
- **F1.T2** Órgão §1-F "Benefícios sociais dos sócios/administradores" (agregado da UG).
- **F1.T3** Fornecedor: bloco por-CNPJ (quais sócios/admin resolvidos recebem benefício; mascarado).
- **F1.T4** Lex: linha agregada na II-E ("N de M sócios verificados recebem benefício de subsistência").

### FASE 2 — Gaps ALTA com dado pronto
- **A8** Capital social × recebido (incompatibilidade de porte) — §1 fornecedor (H-CAPITAL já existe).
- **A7** QSA detalhe (participação %, qualificação, entrada/saída) — §1 fornecedor.
- **A1** Aditivos contratuais (se colunas populadas) — §4 fornecedor.
- **A3** Doações eleitorais TSE no **MD** (já está no PDF) — nova seção fornecedor.
- **A4** Rodízio/cartel no fornecedor (`rodizio_temporal`) — §5 fornecedor.
- **A2** Cadeia Empenho→Liquidação→OB (se colunas populadas) — §2.
- **A5** Regularidade fiscal/previdenciária (`registry_providers`, async/bounded) — §1.
- **A6** Terceirizados (conflito de pessoal) — nova seção.

### FASE 3 — Gaps MÉDIA
M1 Benford · M2 anomalias · M3 decisões TCE · M4 receita×despesa (órgão) · M5 conflito de endereços ·
M6 co-ocorrência de sócios · M7 OpenSanctions detalhado · M8 gazetas estruturado · M9 tipo de processo SEI · M10 consórcio.

## Critério de aceite (por tarefa)
1. **Verificar o dado primeiro** (a fonte existe e está populada? senão a seção sai INDISPONÍVEL honesto).
2. **Teste** novo (unit, sem rede/SQL pesado via injeção) — verde, e regressão dos módulos tocados verde.
3. **Render do PRODUTO REAL**: gerar o MD/PDF de um alvo conhecido e conferir que a seção aparece correta
   (Fundo 036100 / TJRJ 030100 p/ órgão; um fornecedor real p/ fornecedor).
4. **Ruff** limpo. **Commit** por unidade (msg semântica + Co-Authored-By).
5. Honestidade conferida (INDISPONÍVEL≠0; CPF mascarado).

## Checkpoints entre fases
- Fim de cada fase: suíte dos módulos tocados verde + 1 PDF real renderizado e inspecionado + `§10` do
  REFERENCIA-PROJETO.md atualizado (1 linha) + estado de CPU/RAM avaliado (VM-safe).

## Fora de escopo agora
god-file split (oportunístico); itens BAIXA (whois/CNAE secundário/grafo de poder) — pós-completude.
