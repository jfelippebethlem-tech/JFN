# Decision log — untangle de `compliance_agent/reporting/` (20/11/2026)

| | |
|---|---|
| **Escopo** | `compliance_agent/reporting/` (37 arquivos, 13,8 mil linhas): relatório de fornecedor (`inteligencia` + `intel_*`), de órgão (`inteligencia_orgao`), consolidado, render HTML/PDF, gate de citações, neutralidade, perícia rica, dossiê mestre, 360, TAC, Receita, coberturas |
| **Base** | `origin/ui/painel-v61-tron-claro` (`3947271c`) — worktree `agent-af69dad4a724369f6` |
| **Opções do dono** | Comentários = SIM (saem só os que repetem o código; ficam medição datada, decisão do dono, norma, porquê de workaround) · Testes = NÃO (nenhum teste removido/reescrito; nenhuma asserção precisou mudar) |
| **Levantamento** | 3 subagentes só-leitura (~230 itens com `arquivo:linha`) + leitura própria; revisão independente dos commits no fim (imports pela AST em todo o repo, ciclos, SQL) |
| **Validação empírica** | ctx REAL congelado (fornecedor `13417794000135` + órgão UG `133100` ITERJ; base viva; LLM desligado; Google/GDELT/CEIS congelados) renderizado com o código de antes e o de depois → md, html do PDF de fornecedor e xlsx comparados byte a byte (render determinístico conferido 2×). Para a etapa de dados (lote 4) o ctx foi recapturado com cada código. Comparação final com cwd de produção (`~/JFN`). |

Legenda: **FEITO** (commit) · **PENDENTE** (decisão do dono ou redesenho de detector/fonte) · **FORA** (outro escopo, só anotado).

---

## 1. Consertos, com os problemas que cada um resolve

### 1.1 Formatador em fonte única: `intel_base` — FEITO (`a8cfb252`, sobras em `8c1a9208`)

`intel_base` (folha, só stdlib) ganhou `reais`, `esc`, `inteiro`, `fmt_doc`; `so_digitos` passou a aceitar não-str.
Cada módulo mantém só o rótulo do valor inválido que é dele ("—", "não informado", texto escapado, `str(v)`).

- Sete cópias de R$ BR: `detector_tac._moeda`, `relatorio_direcionamento._moeda`, `pericia_fisc_rico._moeda`,
  `requisicao._moeda`, `penalidades_tce_view._moeda`, `export_relatorios._fmt_currency`, `_brl` local em
  `intel_md._render_execucao` e em `inteligencia_orgao._secao_sei_risco_md`.
- Cinco `_esc` (`ficha7`, `relatorio_direcionamento`, `pericia_fisc_rico`, `capitulos_dossie`; `consolidado`
  reimplementava `html.escape(quote=False)` à mão) e um `html.escape` local em `intel_md._fachada_b2_html`.
- Sete "só dígitos" (`detector_tac._digitos`, `capitulos_dossie._dig`, `requisicao._orgao`,
  `anomalia_receita._norm_ug`, `pericia_fisc_rico._fmt`, CLI do consolidado, três `isdigit` em
  `inteligencia_orgao`) e dois "milhar inteiro" (`cabecalho_frescor`, `listar_ugs`).
- `pericia_fisc_rico._fmt('doc')` reimplementava `fmt_cnpj` e a máscara de CPF → `fmt_doc` (máscara de
  `qualidade.verificadores.mascarar_cpf`, a da regra PAD-04 — idêntica à antiga).
- `render_html._REPORTS` e o de `consolidado` eram cópias do caminho de `intel_base._REPORTS`.
- Prova: 19 entradas × 16 funções, antes × depois — saída idêntica em toda entrada que antes funcionava; só
  mudam as que antes levantavam exceção (ex.: `penalidades._moeda(None)`: `TypeError` → `0,00`).
  `export_relatorios._fmt_currency` passou de `except Exception` a `(TypeError, ValueError)`.

### 1.2 Fachada `inteligencia.py` só com o que é usado — FEITO (`4e736c70`)

- O split de 06/07 deixou ~110 linhas em branco e 8 blocos de comentário órfãos (descreviam `_ENRIQUECE_*`,
  `_SEDE_ONDEMAND_DIAS`, `favorecido_resumo`, `_RCLONE_BIN`, `_BOILERPLATE`, `_NOTA_CARDINALIDADE`, retenção)
  — foram para junto das constantes em `intel_dados`/`intel_md`/`intel_analise`/`intel_base`.
- A fachada re-exportava 85 nomes; ficam os 38 usados pelo orquestrador ou importados de fora (lex, lex_render,
  server, `tools/refresh_favorecido_resumo.sh`, testes). Inventário por grep/AST de `inteligencia import` e de
  `<alias>.<attr>` em todo o repo; a revisão independente confirmou que todos resolvem.
- `inteligencia_orgao` importava 13 nomes (10 privados) atravessando a fachada; agora do módulo dono.
- `consolidado`: repasses `_slug`/`_render_pdf`; cópia do caminho de `_DB`/`_REPORTS` (ignorava
  `JFN_DATA_DIR`); laço `getattr` sobre `_fatos_fornecedor`/`_fatos`, que não existem (e `fn` podia ficar
  indefinido no `except`).
- `intel_dados.resolver_empresa`: sem chamador.

### 1.3 Defeitos visíveis provados — FEITO (`e7be5bbc`, complemento em `8c1a9208`)

| Defeito | Antes | Depois |
|---|---|---|
| `/orgao` PDF: motor de achados quebrado | "GRAU DE ATENÇÃO: VERDE — sem indícios relevantes · Score N/100" | "INDISPONÍVEL" (cinza), score "INDISPONÍVEL", erro no log |
| `render_html`: faixa `MEDIO` sem acento (dossiê mestre, avaliação 360) | selo cinza `#777` | cor de MÉDIO `#f9a825` (texto igual) |
| `processo_360_ctx`: subtítulo do PDF | "… que importam · JFN" (termo interno; o caller não passa pelo gate) | sem "· JFN" |
| `/orgao` §1-F (benefícios) e §1-G (sanções TCE-RJ) | imprime todos (`tudo()`) e depois diz "(+N … detalhe na planilha/base)" | nota falsa removida |
| PDF fornecedor, coluna Órgão (UG) da rede TSE | mostra 10 UGs e diz "+(n−3) UG" | "+(n−10) UG" |
| `/orgao` PDF (fpdf): sumário executivo e matriz P×I | "… no Parecer Lex anexo" — o gate `termos_proibidos` acusa `['Lex']` no PDF de 96 páginas (achado no PDF de validação) | "no parecer anexo" / "no Parecer jurídico anexo"; gate limpo |
| consolidado: cerca do LLM | `.lstrip("markdown")` comia letras ("```dados apurados" → "s apurados") | `intel_analise.sem_cercas`, a mesma do `_normaliza_raciocinio` |

`sem_cercas` só trata como etiqueta a palavra seguida de quebra de linha ou de JSON; 9 casos no
`_normaliza_raciocinio`, antes × depois: 8 iguais, muda só o do defeito. (A mensagem do commit `e7be5bbc` cita
"§1-B.2/§1-H" por engano; o certo são §1-F e §1-G — registrado em `8c1a9208`.)

### 1.4 Uma definição de "favorecido PJ" — FEITO (`ff38e477`, alias `ob.` em `8c1a9208`)

`intel_base.SQL_FAVORECIDO_PJ = "length(favorecido_cpf)=14 AND favorecido_cpf NOT LIKE '%*%'"`.

- Treze cópias de `length(favorecido_cpf)=14` em `reporting/` (intel_base, inteligencia_orgao ×3, consolidado,
  detector_tac, anomalia_receita ×7). O espelho TFE grava CPF já mascarado como `999.***.***-99` — também 14
  caracteres. Medido hoje: 286.869 das 1.202.093 OB "de 14 caracteres" são de PF; no ITERJ, 104 dos 203
  "fornecedores PJ".
- Efeito no relatório real (mesma base, código antes × depois):
  - cabeçalho de cobertura (fornecedor e órgão): "100% com CNPJ (PJ)" → "76%";
  - `/orgao` ITERJ §1-L: 200 → 98 fornecedores PJ (130 → 28 "sem contrato no TCE-RJ" — saem nomes de PF);
  - §1-E sedes: "98 de 203 verificados (48%)" → "98 de 99 (99%)";
  - §1-K dump Receita: "189 fornecedores PJ, 92 (49%)" → "97, 92 (95%)".
  Nada mais mudou no md/html/xlsx. As consultas com JOIN por `cnpj_basico` já descartavam o CPF mascarado
  (saída igual); só mudam as contagens e listas sem JOIN.

### 1.5 Caminho do banco nas views; código morto — FEITO (`95275060`)

- `beneficios_view`, `conflito_pessoal_view`, `penalidades_tce_view`: `Path("data")/"compliance.db"` (e
  `ug_canonico.json`) relativo ao diretório corrente → `intel_base._DB/_DATA`. A validação mostrou o defeito ao
  vivo: com cwd fora da raiz, as seções 2-B e 2-E do fornecedor saíam "INDISPONÍVEL" caladas; com o código novo
  leem a base. Em produção (`WorkingDirectory=~/JFN`, `JFN_DATA_DIR=~/JFN/data`) a saída é a mesma — conferido
  renderizando o mesmo ctx com cwd de produção, antes × depois.
- `reporting/pericia_fisc.py` apagado (nenhum importador em .py/.sh/.yaml; só citado em planos de julho em
  `docs/superpowers/`; o caminho vivo é `pericia_fisc_rico`).
- `inteligencia_orgao`: `gerar()` repasse usado só pelo `__main__`; `_nota_ob` sem uso; imports locais
  redundantes (`sqlite3`, `json as _json`, `logging` ×2 → `_log`).

### 1.6 Comentários que só repetiam o código — FEITO (`0cc6bd90`)

38 comentários (intel_md 17, inteligencia_orgao 21) que repetiam o `add("## …")`/`_secao_*`/`_render_*` ou a
variável da linha seguinte. Em intel_md, onze mentiam a numeração ("# 2. Perfil cadastral" sobre
`## 1. PERFIL CADASTRAL`). Ficaram os de requisito do dono ("TABELA POR ANO"), paridade MD×PDF, caso Con-tato,
medição de 09/08 sobre o espelho, normas. O comentário de `_RX_TAC` voltou para cima da regex (estava sobre o
logger); o banner órfão "moeda (formatação local)" de detector_tac saiu.

---

## 2. PENDENTE — decisão do dono ou redesenho (não é refatoração)

1. **Pagamento pela régua `cruzamentos_intel._ob_paga`.** Todo total dos relatórios de fornecedor e órgão (e
   TAC, Receita, cobertura de captura, `_sede_total_pago`) é `SUM(ordens_bancarias.valor)` do espelho TFE, sem
   status; `_ob_paga` só existe sobre `ob_orcamentaria_siafe`. Trocar é troca de fonte. O MD declara o viés
   (9,7% não Contabilizado); o PDF de fornecedor diz "OB = pagamento definitivo, REAL" sem a ressalva.
   `cobertura_captura.py` usa `status='Contabilizado'` literal (não pega Erro no Pagamento/Complementar/reemitida).
2. **Chave de fornecedor = `so_digitos(favorecido_cpf)`** em `consultar_orgao`/recorrentes: CPF mascarado vira 5
   dígitos ("01912") e funde pessoas; `n_fornecedores` conta PF. Concentração/HHI chaveados por NOME (mesmo CNPJ
   com duas grafias divide a fatia). Mexe em `n_fornecedores`, HHI, score e parecer. `detector_tac`
   (`LIKE raiz%` em medir_tac/emergencial) também soma CPF com o mesmo prefixo.
3. **MD × PDF divergem** (seções computadas duas vezes): sanções (PDF consulta CEIS ao vivo, MD usa o enriq), P×I
   com dois métodos, Benford ×3, `_anomalias_fornecedor`/`beneficios`/`conflito` refeitos no PDF, cortes
   silenciosos no PDF (`[:80]`, `[:60]`, `[:40]`…) que o MD não tem (e `intel_pdf` fora de `_RENDER_SANEADOS`),
   §1-D.1/§1-N só no MD do órgão, ordem das seções, tetos diferentes (30×80 processos, 5×4 líderes), `n_eventos`
   com fallback diferente. Unificar muda o PDF.
4. **Ordem de chamada escondida:** `ctx["rodizio_forn"]` só é preenchido dentro de `render_md`, depois do
   `parecer_raciocinado` — o ramo de rodízio dos fatos do LLM nunca roda em produção; `render_md` precisa rodar
   antes do `render_pdf_html` (muta o ctx). §4-B do MD consulta o TCE-RJ de novo em vez de `ctx["tcerj_itens"]`.
5. **Faixas/limiares copiados:** P×I (lex_render, lex_orgao, inteligencia_orgao, intel_md com 9/39/79); faixas
   de score 90/70/50 (×3) vs 75/50/25 (dossiê mestre); TAC 🔴 ≥25% no MD vs 30/50 em `detector_tac._severidade`;
   concentração 60/40, pago/contratado 1,5/1,2, anomalia ≥0,70, "≥4× acima de R$ 50 mil" escritos em prosa.
6. **Construído, nunca rodado:** `matriz_achados`, `qualificacao_juridica`, `quesitos_diligencia` só têm chamador
   em teste. `requisicao.PALAVRAS_VEDADAS` e a lista de `quesitos_diligencia` já divergiram.
7. **Cópias entre `ficha7` e `relatorio_direcionamento`** (`_bloco_colegiado`, `_matriz_risco`,
   `_bloco_fundamentacao`, `_ficha_html`, lentes) — o texto já difere em detalhes; unificar muda HTML.
8. **Glifos do fpdf** (`_t`): três cópias com listas diferentes (intel_pdf, inteligencia_orgao, lex_render).
9. **`processo_360_ctx.ordem_grav`** aceita "alto/medio" mas `_GRAV_EMOJI` só tem "alta/media".
10. **Privados atravessando módulos:** `inteligencia_orgao` usa `lex._achados_orgao`, `lex._grau`, `lex._RF`,
    `detector_tac._FAIXA_MIN`; `lex_orgao`/`consolidado` usam `inteligencia_orgao._recorrentes_identicos` e
    `_fatos_orgao`; `relatorio_direcionamento` usa `indice_certame._matriz_sv` e `peer_diff._SUBTIPO_PARA_TIPO_E7`.
    Tornar públicos exige mexer em lex/editais.
11. **"Art. 90 Lei 8.666"** citado 6× no /orgao — dispositivo revogado (crime migrou para o CP 337-F pela
    14.133). Conteúdo jurídico: decisão do dono.
12. `conflito_pessoal_view._FOLHA_IDX_CACHE` nunca invalida no serviço de longa vida (a folha muda todo dia).
13. Rótulo "CNPJ 01912" para CPF mascarado na pergunta de ambiguidade do /relatorio (ligado ao item 2). Não é
    vazamento: medido, `favorecido_resumo` não tem CPF cru de 11 dígitos (39.769 linhas, todas de 14 caracteres,
    24.568 mascaradas). `fmt_doc` já existe para quando houver.
14. Caminho fixo `repo/data/compliance.db` em `cobertura_captura`, `cobertura_siafe`, `cobertura_pericia`,
    `ob_retiradas`, `processo_360_ctx` (ignoram `JFN_DATA_DIR`; `detector_tac._resolver_db` lê o env a cada
    chamada e não deve ser trocado pelo valor congelado de `intel_base`). Igual em produção; não mexido.

## 3. FORA do escopo (anotado, não mexido)

- Mais onze arquivos fora de `reporting/` com `length(favorecido_cpf)=14` (relacoes, cruzamento,
  rede_societaria, ninho_sala, cruzamentos_intel, rede_fachada, tools/*) — o mesmo defeito do 1.4.
- `pericia_contabil.mascarar_doc` mascara CPF como `123.***.***-00` (3 primeiros + 2 últimos), diferente da
  máscara PAD-04 (`***.456.789-**`) que o resto da casa usa.
- Alguma suíte de teste cria `data/compliance.db` vazio na raiz do checkout (visto três vezes no worktree);
  módulo que abre esse caminho fixo sem `JFN_DATA_DIR` passa a ler a base vazia ("no such table" no DD do órgão).
- `lex_render.py` importa `_mc`/`_registrar_fonte`/`_render_parecer_pdf` privados pela fachada.
- `tools/processo_360.py:129` chama `gerar_pdf` sem `garantir_neutro` (o subtítulo foi corrigido aqui; o portão
  continua faltando no caller).
