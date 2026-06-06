# SIAFE-Rio 2 — Arquitetura e guia de automação (OB Orçamentária)

> Referência técnica para coletar dados do SIAFE-Rio 2 (Oracle ADF). Base: documento de exploração de UI
> (Claude/Chrome, 2026-06-06) + descobertas do coletor `compliance_agent/siafe_ob_orcamentaria.py`.
> **Para a próxima IA:** leia isto ANTES de mexer no coletor SIAFE. Os "gotchas" de ADF no fim economizam horas.

## 1. Stack e convenções
- **Oracle ADF + Apache MyFaces Trinidad.** Renderização parcial (**PPR**): campos surgem/mudam via AJAX.
  Ex.: o campo "Valor" do filtro só existe no DOM **depois** de escolher Operador e perder o foco (blur).
- **IDs ADF:** `componente:sub::tipo` (separador `:`). Prefixo do container: lista = `pt1:`, detalhe = `tplSip:`.
- **Form (lista):** `frmPrincipal` (`name=org.apache.myfaces.trinidad.faces.FORM`). **Detalhe:** `frmDocumento`.
- **ViewState:** hidden `javax.faces.ViewState` (rotaciona). **Window:** `Adf-Window-Id` (ex.: `w8`).
- **URL base:** `https://siafe2.fazenda.rj.gov.br/Siafe/`. Versão 4.167.12.

## 2. Login (resolvido em `_login`)
- Campos: usuário `loginBox:itxUsuario::content`, senha `loginBox:itxSenhaAtual::content`,
  cliente `loginBox:cbxCliente::content` (default "Rio de Janeiro"), **exercício** `loginBox:cbxExercicio::content`,
  botão **`loginBox:btnConfirmar`** (texto "Ok"). O "Sim" do diálogo de sessão é `myBtnConfirm`.
- **Submeter:** clicar `btnConfirmar` por ID (clique real). NÃO usar Enter antes (engole o submit).
- **Sessão única:** o SIAFE só permite 1 sessão/usuário e **reconecta automaticamente no exercício anterior**.
  Para TROCAR de exercício é preciso **"Sair"** (link no topo-direito) e logar de novo. O coletor faz logout-primeiro.
- **Exercício por login:** seleciona-se no dropdown (com retry — o ADF reverte o valor sozinho). Validado: 2024–2026 OK.
- **Exercício bloqueado:** se a conta não tem permissão, o servidor mostra *"O SIAFE-Rio AAAA está bloqueado.
  Somente usuários com permissão..."*. O coletor detecta e devolve `erro=exercicio_bloqueado` (ex.: 2023 — pendente
  liberação pela TI do Estado). **Não remover 2023 da lista** — só pular.

## 3. Navegação
Menu **Execução → Execução Financeira → OB Orçamentária** (anchors `a.xyo` por texto; "Execução Financeira" via
`pt1:pt_np3:1:pt_cni4::disclosureAnchor`). Cuidado: clicar **exatamente** "OB Orçamentária" (não "Execução
Orçamentária", que também casa "orçamentária"). URLs: lista `.../financeira/ordemBancariaOrcamentariaCad.jsp`,
detalhe `...Edit.jsp`. A grade demora a carregar — usar o detector `tabela_pronta` (linhas + sem glasspane + contagem estável).

## 4. A tabela (virtualizada) e o limite
- Container: `pt1:tblOBOrcamentaria:tabViewerDec`. Corpo (linhas no DOM): **`::db`**. **Scroller virtual: `::scroller`**
  (~40000px ≈ 1000 linhas). **Rolar o `::db` NÃO carrega mais** — é o **`::scroller`** que dispara o fetch. O coletor
  rola o `::scroller` incrementalmente e colhe o `::db` a cada passo (linhas têm `class="xzy"`, sem id próprio).
- **Limite de 1000 registros** por consulta (`pt1:tblOBOrcamentaria:txt_maxResults`). Para o ano inteiro: **filtrar**.

### 4.1 Colunas (23) — OB Orçamentária
`Número · UG Emitente · UG Pagadora · Data Emissão · Status · Tipo · Finalidade · Tipo de OB · NL · Credor ·
Nome do Credor · UG Liquidante · Valor · Competência · Status de Envio · GD · Processo · RE · PD ·
Tipo de Regularização · Qtd. Impressões · Assinatura Digital · Vinculação de Pagamento`.
> **Riqueza vs TFE:** o SIAFE traz **NL (liquidação), PD, Processo, Credor, Competência, Vinculação** — que a base
> TFE (`ordens_bancarias`) não tem. Por isso o SIAFE **prepondera** na compatibilização.

## 5. Filtro rico (a chave para passar de 1000)
O filtro real é uma **tabela de condições** `pt1:tblOBOrcamentaria:table_rtfFilter` (abrir o accordion
"Filtro" via `pt1:tblOBOrcamentaria:sdtFilter::disAcr`). Cada linha `:N:`:
- **Propriedade:** `...:N:cbx_col_sel_rtfFilter::content` (select). Valores: 0 Número, **1 UG Emitente**, 2 UG Pagadora,
  **3 Data Emissão**, 4 Status, 8 NL, 9 Credor, 12 Valor, **16 Processo**, 18 PD, ...
- **Operador:** `...:N:cbx_op_sel_rtfFilter::content`. Valores: 0 igual, 1 maior que, 2 ≥, 3 menor que, 4 ≤,
  5 diferente, 6 é nulo, 7 contém, 8 começa com, 9 termina com, 10 pertence (`;`).
- **Valor:** `...:N:in_value_rtfFilter::content` — **só aparece via PPR** após escolher Operador + blur.
- **Aplicar:** digitar o Valor + **Enter** (ou blur) → recarrega a tabela. Linha em branco nova é adicionada (AND).

**Estratégia de varredura completa (por ano liberado):** filtrar **Propriedade=UG Emitente, Operador=igual,
Valor=<código UG>** para cada UG (lista no §6); se a UG-ano passar de 1000, **sub-particionar por Data Emissão**
(Propriedade=3, Operadores ≥/≤ por mês). Cada OB tem 1 UG Emitente → iterar todas as UGs cobre tudo sem duplicar.

## 6. UGs (dropdown `pt1:selUg`, value→código) — 206 unidades
A lista completa (código/nome/value) é **lida em runtime** das 206 `options` do `pt1:selUg::content`
(mais robusto que hardcode). Exemplos: 1=010100 ALERJ,
3=020100 TCE-RJ, 5=030100 TJ, 23=100100 MP, 26=110100 DPGE, 31=123400 RIOPREVIDEN, 50=133100 ITERJ,
160=404300 UERJ, 167=404500 UENF, 169=404700 UEZO, 204=999900 TESOURO ESTADUAL. (0 = TODAS.)
> Obs.: o dropdown `pt1:selUg` do topo é um seletor global; para FILTRAR a grade use a **tabela de filtro rico** (§5).

## 7. Drill-down por OB (detalhe — futuro)
Para abrir uma OB: **selecionar a linha** (clique) e clicar **`pt1:tblOBOrcamentaria:btnView`** (Visualizar).
`dblclick` via JS NÃO funciona. Tela de detalhe: form `frmDocumento`, prefixo `tplSip:` (ex.: `tplSip:itxNumero::content`,
`tplSip:itxDataEmissao::content`, `tplSip:lovUgEmitente:itxLovDec::content`). Abas: Detalhamento, etc.

## 8b. INTELIGÊNCIA-CHAVE — por que o filtro rico resiste ao Playwright (medido)
**Fato medido (captura de rede):** selecionar Propriedade e Operador do filtro via `select_option`
(ou `dispatchEvent('change')`, ou clique real de blur em outro campo) dispara **ZERO requisições HTTP**.
Os `<select>` do filtro **não têm `onchange` inline** (atributos só `id/name/class=x2h/title`); o ADF registra
o listener via JS (peer `AdfDhtmlSelectOneChoicePeer`; `AdfPage` existe como função global). Logo, o PPR que
**cria o campo Valor** (`in_value_rtfFilter`) **nunca é acionado** por eventos sintéticos.
**Implicação:** para dirigir esses componentes ADF é preciso **emulação humana genuína** (mouse/teclado reais
no nível do SO), como faz o Claude/Chrome. Opções profissionais: **Anthropic Computer Use** (modelo + screenshot +
`xdotool` num Chrome headed sob Xvfb) ou invocar a API interna do ADF (`AdfPage.PAGE.findComponent(...)` +
value-change/autosubmit — frágil entre versões). **O que JÁ funciona** (login + navegação + colheita de ~1000/consulta
+ ingestão) NÃO depende disso; só a **varredura completa por filtro** depende. Replay HTTP do PPR também é viável se
capturarmos (DevTools→Network) a requisição exata que o filtro dispara num navegador real.

## 8. GOTCHAS de automação (o que custou horas)
- **Headless vs ADF:** o pipeline de eventos/PPR do ADF pode não disparar 100% em Chromium headless. Rodar
  **headed em Xvfb** (`xvfb-run`) aproxima do comportamento real (como o Claude/Chrome "enxerga"). Ver `_HEADED` no coletor.
- **`select_option`/`dispatchEvent` sintéticos** podem não acionar o autoSubmit/PPR do ADF (selectOneChoice).
  Preferir interação **trusted** (Playwright `.click()`/`.press()`/`.fill()` reais; e modo headed).
- **Clique de botão ADF:** usar `.click()` real (ou `el.click()` por ID); o `.click()` do Playwright auto-espera 30s
  e TRAVA se o elemento não está acionável — clicar via JS por ID quando for diálogo/popup.
- **Sessão única:** logar pela VM derruba o navegador do Mestre Jorge (e vice-versa). Coordenação via Telegram
  (`/siafelivre`, `/siafeocupado`) + checkpoint para retomar.
