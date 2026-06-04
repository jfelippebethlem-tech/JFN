# ROTINA DE AUDITORIA SIAFE — passo a passo mecânico (para IA fraca seguir)

> Objetivo: dado um **CNPJ**, descobrir **todos os pagamentos (Ordens Bancárias),
> por mês, em cada exercício (ano)**, com o **número do processo (SEI)** de cada um,
> e os **contratos** relacionados. Tudo VERIFICADO ao vivo em 2026-06-04 (login OK,
> navegação OK, colunas confirmadas).
>
> Caso de teste: **MGS CLEAN SOLUCOES E SERVICOS LTDA — CNPJ 19.088.605/0001-04**, anos 2025 e 2026.

## REGRAS DE OURO (não quebrar)
- **Ritmo humano**: 3–8 s entre ações; nunca disparar cliques em rajada (o SIAFE é sistema do governo — agir como humano evita bloqueio).
- **Só LEITURA/consulta.** Nunca emitir, alterar, assinar ou excluir nada.
- Credenciais só no `~/.hermes/.env` (`SIAFE_USUARIO`, `SIAFE_SENHA`). Nunca no git/chat/log.
- Se aparecer erro/sessão expirada → relogar com calma; se bloquear → PARAR e avisar.

## FERRAMENTA CERTA
SIAFE é **Oracle ADF** (JavaScript pesado). Clique JS simples (`el.click()`) **NÃO funciona**
nos menus/itens. Use **clique de mouse REAL** (Playwright `page.click()`, ou CDP
`Input.dispatchMouseEvent` mousePressed+mouseReleased nas coordenadas do elemento).
Rodar pelo módulo `siafe_agent/browser/siafe_browser.py` (Playwright) na VM.

URLs:
- Login: `https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp`
- Base:  `https://siafe2.fazenda.rj.gov.br/Siafe`

---

## PASSO 1 — LOGIN (verificado)
Campos do formulário (IDs exatos):
- usuário (CPF): `loginBox:itxUsuario::content`  → valor `SIAFE_USUARIO` (ex.: 14398839712)
- senha:         `loginBox:itxSenhaAtual::content` → valor `SIAFE_SENHA`
- cliente:       `loginBox:cbxCliente::content` → `0` (Rio de Janeiro)
- exercício:     `loginBox:cbxExercicio::content` → **2025 = `2`** ; **2026 = `1`** (2027=0, 2024=3, 2023=4)
- botão entrar:  `loginBox:btnConfirmar` (texto "Ok")

Receita: preencher cada campo com value + disparar eventos `input`/`change`/`blur`;
clicar `btnConfirmar`. Sucesso = a URL sai de `login.jsp` (vai para `.../acessoRapido.jsp`).
**Sem captcha.**

## PASSO 2 — FECHAR O POP-UP DE DECRETO
Ao entrar costuma abrir um modal "DECRETO DE ENCERRAMENTO DO EXERCÍCIO". Clique no botão
**OK** (texto "OK") para fechar, senão ele bloqueia toda a navegação.

## PASSO 3 — IR ATÉ AS ORDENS BANCÁRIAS (pagamentos)
1. Menu topo: **Execução** (anchor `pt1:pt_np4:1:pt_cni6::disclosureAnchor`).
2. Sub-aba: **Execução Financeira** (`pt1:pt_np3:1:pt_cni4::disclosureAnchor`) — clique REAL.
3. Menu lateral esquerdo: **Ordens Bancárias** (`pt1:pt_np2:8:pt_cni3`) — clique REAL.
   (Aguardar ~4 s o ADF carregar a grade.)

Resultado: tabela com as colunas (confirmadas):
`Número | UG Emitente | UG Pagadora | Data Emissão | Status | Tipo | Tipo de OB |
Favorecido(CNPJ) | Nome do Favorecido | GD | Processo | RE | PD | Status de Envio | Valor | Assinatura Digital`

## PASSO 4 — FILTRAR PELO CNPJ
1. Clicar no acordeão **"Filtro"** (`pt1:tblOrdemBancaria:pnlAccordionDec_afrCl0`) — clique REAL.
2. No campo **Favorecido/CNPJ** do filtro, digitar o CNPJ. Tentar nas duas formas:
   `19.088.605/0001-04` e, se não achar, `19088605000104`.
3. Acionar **Pesquisar/Filtrar**. (Se houver filtro por Data Emissão, deixar o ano todo.)
   Dica: também existe o item lateral **"Lista de Favorecido para OB"** — caminho alternativo
   que já lista por favorecido; usar se o filtro da grade não cooperar.

## PASSO 5 — EXTRAIR AS LINHAS (todas as páginas)
Para cada linha visível, capturar: **Número, Data Emissão, Valor, Processo, Nome do Favorecido, Status**.
A grade é paginada (rolar/avançar página com clique REAL até acabar). Guardar tudo em lista.
Salvar bruto em `data/sei_cache/siafe_<cnpj>_<ano>.json` (cache, fora do git).

## PASSO 6 — AGRUPAR POR MÊS
Da Data Emissão (DD/MM/AAAA), somar **Valor** por mês (01..12). Gerar tabela:
| Mês | Qtde OBs | Total R$ |  e o **total do ano**.

## PASSO 7 — REPETIR PARA O OUTRO ANO
Sair (ou relogar) escolhendo **exercício 2026 (`1`)** e refazer PASSOS 3–6.
(O exercício é escolhido no LOGIN; para trocar de ano, deslogar e logar de novo no outro exercício.)

## PASSO 8 — CONTRATOS (caminho VERIFICADO ao vivo)
Menu **Execução → Contratos e Convênios** (`pt1:pt_np3:3:pt_cni4::disclosureAnchor`) →
menu lateral **Contrato** (`pt1:pt_np2:2:pt_cni3`) — clique de MOUSE REAL.
Grade carrega com as colunas (confirmadas):
`Número Automático | Número da Licitação | Número Original | Natureza | Objeto |
Cód. Contratante | Nome Contratante | Cod. Contratado | Modalidade | Nome do Contratado |
Situação | Valor do Contrato | Qtd. Aditivos | Qtd. Reajustes | Qtd. Anexos`.
Filtrar por **Cod. Contratado (CNPJ)** ou **Nome do Contratado** → lista AUTORITATIVA de todos
os contratos do fornecedor (com valor, objeto, aditivos).

### 🔑 SEGREDO DO FILTRO ADF (descoberto ao vivo — economiza horas)
1. O texto **"Filtro"** (`...pnlAccordionDec_afrCl0`) tem **`onclick="return false"`** — clicar nele NÃO faz nada (armadilha!).
2. Quem expande o painel é o disclosure **`pt1:tblContrato:sdtFilter::disAcr`** (title "Mostrar este painel"). Clique REAL nesse.
3. Aberto, o filtro é um "rich table filter": **Propriedade** (`...table_rtfFilter:0:cbx_col_sel_rtfFilter::content`) → escolher **`9` = Nome do Contratado** (ou `7` = Cod. Contratado); **Operador** (`...cbx_op_sel_rtfFilter::content`) → "contém"/"igual".
4. ⚠️ O **campo de VALOR só aparece depois que o ADF faz o refresh parcial (PPR)** ao trocar a Propriedade — e isso o **JS/CDP cru NÃO dispara** (setar `.value`+`change` não aciona o autosubmit do ADF). 
   **Solução (Playwright NATIVO na VM):** `page.select_option(prop, '9')` dispara o evento real → o campo de valor renderiza → `page.fill(valor, 'MGS CLEAN')` → aplicar. Em Chrome de **aba única na VM** (não `connect_over_cdp` num Chrome local lotado, que dá timeout).

Esse é exatamente o "aprimorar o módulo de auditoria": implementar `buscar_contratos_por_contratado(nome_ou_cnpj)` no `siafe_browser.py`, rodando na VM. Caminho 100% mapeado acima.

> ✅ **RESOLVIDO (2026-06-04)** — `_SANDBOX/siafe_contratos.py` já faz: abre filtro (`sdtFilter::disAcr`),
> Propriedade `7` (Cod. Contratado) + Operador `0` (igual), e **DIGITA o CNPJ** com `keyboard.type`
> (o `fill` NÃO aplica; só keystrokes reais disparam a query ADF) + Enter. Resultado validado:
> **41 contratos da MGS CLEAN, R$ 146,7 mi**. `connect_over_cdp` funciona com poucas abas abertas.

## PASSO 8b — EMPENHOS SEM CONTRATO NO HISTÓRICO
Os ~16–20% do empenhado cujo histórico não cita contrato: abrir cada **Nota de Empenho**
(Execução Orçamentária → Nota de Empenho, filtro pelo nº do empenho da coluna "Empenho" do TFE)
— o detalhe do empenho traz o contrato e o processo vinculados.

## PASSO 9 — CRUZAR COM O SEI
Para cada **Processo** achado nas OBs/contratos, rodar `python _SANDBOX/sei_auditor.py <numero>`
(ferramenta já pronta) e conferir: o processo existe? o objeto bate? as datas batem?
Marcar divergências como **red flag**.

## PASSO 10 — RELATÓRIO
Gerar `.md`/`.xlsx`/`.pdf` com:
- Identificação (CNPJ, razão social).
- Tabela **pagamentos por mês** (2025 e 2026) + totais.
- Lista de **contratos** (nº, objeto, valor, vigência, processo).
- Lista de **processos SEI** vinculados.
- **Red flags** (valores fora de contrato, datas estranhas, processo inexistente, etc.).
- Fonte e data da coleta.

---

## ESTADO ATUAL (2026-06-04)
- ✅ PASSOS 1–3 e a grade do PASSO 5 **verificados ao vivo** (login, navegação, colunas).
- ✅ Método ADF (clique de mouse real) confirmado.
- ⏳ Falta executar PASSOS 4–10 pelo módulo Playwright na VM (ritmo humano) → entrega os números da MGS CLEAN.
- Próximo: implementar `buscar_ob_por_cnpj(cnpj, exercicio)` no `siafe_browser.py` seguindo esta rotina.
