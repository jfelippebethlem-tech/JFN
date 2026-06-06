# SIAFE-RIO 2 — Guia Técnico de Automação por IA (Execução Financeira)

> **Fonte:** mapeamento manual do Mestre Jorge após login (06/06/2026). Versão SIAFE 4.167.12, build
> 202605281616, exercício 2026. **Inteligência operacional** para o coletor `siafe_ob_orcamentaria.py`
> e correlatos. Complementa `docs/SIAFE-ARQUITETURA.md` e `docs/PESQUISA-SIAFE-ADF-PPR.md`.
>
> ⚠️ A mensagem-fonte foi **truncada** na seção 7.6 (Guia de Recolhimento, lista de botões). As seções
> 1–7.5 estão completas; 7.6+ a completar quando o Mestre enviar o restante.

- **URL base:** `https://siafe2.fazenda.rj.gov.br/Siafe/`
- **IP servidor:** 10.8.180.234 (rede interna — WAF gov barra IP não-governamental, ver CLAUDE.md §6)

---

## 1. Arquitetura técnica

- **Framework:** Oracle ADF (Application Development Framework) + Apache MyFaces Trinidad.
- **Padrão de IDs:** `prefixo:componente:subcomponente::tipo`. O **prefixo varia por tela**:
  - Lista/tabela principal: `pt1:`
  - Acompanhamento PD: `tpl:`
  - Fechamento do Dia: `ptPrincipal:`
  - Tipo de Conciliação: `tpl:`
- **Forms:** lista = `id="frmPrincipal"`; detalhe = `id="frmDocumento"`.
- **Hidden fields (sessão):**
  - `oracle.adf.view.faces.RICH_UPDATE` (hidden, value="dirty")
  - `org.apache.myfaces.trinidad.faces.FORM` (hidden)
  - `Adf-Window-Id` (hidden, ex.: "w8")
  - `javax.faces.ViewState` (hidden, **token de sessão**)
- **Push iframe (ADF polling):** `id="afr::PushIframe"`.
- **PPR (Partial Page Rendering):** o ADF atualiza partes da página via AJAX sem recarregar. **Crítico:**
  o campo "Valor" do filtro só aparece no DOM **após** o servidor fazer PPR em resposta ao blur/change
  do campo "Operador".

---

## 2. Login

- **URL:** `.../Siafe/faces/login.jsp`
- **Campos:**
  - `loginBox:itxUsuario::content` (text, name=`loginBox:itxUsuario`)
  - `loginBox:itxSenhaAtual::content` (password, name=`loginBox:itxSenhaAtual`)
  - `loginBox:cbxCliente::content` (select) — `value="0"` = Rio de Janeiro
  - `loginBox:cbxExercicio::content` (select) — options: Selecione, **2027(0), 2026(1), 2025(2), 2024(3), 2023(4)**
  - `loginBox:btnConfirmar` (submit) — botão "Ok"
- **Popup "USUÁRIO LOGADO" (sessão duplicada):**
  - `myBtnOk` (text="Sim") — confirma e encerra a outra sessão
  - `myBtnCancel` (text="Não") — cancela
- ⚠️ **Gotcha:** usar `el.click()` via JS num link do menu enquanto o popup `myModal` está ativo **encerra
  a sessão**. Solução: clicar visualmente, ou checar se `myModal` está visível antes.
- **URL de erro de sessão:** `.../Siafe/faces/session-error.jsp` ("Sua sessão foi encerrada devido a uma
  conexão em outro dispositivo" + link "Retornar à tela de Login").

---

## 3. Estrutura de navegação

**Menu principal (abas nível 1):** `pt1:pt_np4:N:pt_cni6::disclosureAnchor`
`0=Planejamento · 1=Execução · 2=Projetos · 3=Apoio · 4=Administração · 5=Relatórios`

**Subabas de Execução (nível 2):** `pt1:pt_np3:N:pt_cni4::disclosureAnchor`
`0=Execução Orçamentária · 1=Execução Financeira · 2=Contabilidade · 3=Contratos e Convênios ·
4=Folha de Pagamento · 5=Mensagens · 6=Acompanhamento Execução`

**Menu lateral — Execução Financeira (20 itens):** `PREFIXO:pt_np2:N:pt_cni3` (PREFIXO varia por tela)

| Índice | Label | URL JSP |
|---|---|---|
| 0 | Acompanhamento de Execução de PD | `acompanhamentoExecucaoPDCad.jsp` |
| 1 | Bloqueio Judicial | `bloqueioJudicialCad.jsp` |
| 2 | Código de Barras | `codigoBarrasCad.jsp` (estimado) |
| 3 | Fechamento do Dia | `pagamentoCad.jsp` |
| 4 | Guia de Devolução | `guiaDevolucaoCad.jsp` |
| 5 | Guia de Recolhimento | `guiaRecolhimentoCad.jsp` |
| 6 | Lista de Favorecido para OB | `listaFavorecidoOBCad.jsp` |
| 7 | Nota de Aplicação e Resgate | `notaAplicacaoResgateCad.jsp` |
| 8 | Ordens Bancárias | `ordemBancariaCad.jsp` |
| 9 | OB Orçamentária | `ordemBancariaOrcamentariaCad.jsp` |
| 10 | OB de Dedução | `ordemBancariaDeducaoCad.jsp` |
| 11 | OB de Retenção | `ordemBancariaRetencaoCad.jsp` |
| 12 | OB de Transferência | `ordemBancariaTransferenciaCad.jsp` |
| 13 | OB Extra-orçamentária | `ordemBancariaExtraOrcamentariaCad.jsp` |
| 14 | Programações de Desembolso | `programacaoDesembolsoCad.jsp` |
| 15 | PD Orçamentária | `programacaoDesembolsoOrcamentariaCad.jsp` |
| 16 | PD de Retenção | `programacaoDesembolsoRetencaoCad.jsp` |
| 17 | PD de Transferência | `programacaoDesembolsoTransferenciaCad.jsp` |
| 18 | PD Extra-orçamentária | `programacaoDesembolsoExtraOrcamentariaCad.jsp` |
| 19 | Tipo de Conciliação Bancária | `tipoConciliacaoBancariaCad.jsp` |

**Navegar sem encerrar sessão:** (1) clicar por coordenada visual (não `el.click()` via JS); (2) aguardar
2–3s; (3) confirmar pela URL/título.

---

## 4. Seletor de UG (em todas as telas)

- **ID:** `PREFIXO:selUg::content` (name=`PREFIXO:selUg`), `SELECT` (select-one). Padrão `value="0"` = TODAS.
- ⚠️ O `value_option` é o **índice da option no exercício 2026** — pode mudar entre exercícios (em 2026
  surgem UGs como 016200/026200 que deslocam índices). Casar por **código da UG**, não pelo índice.

Mapa completo extraído em `data/siafe_ug_map_2026.json` (gerado deste guia). Referência (código | nome | value):

```
0=TODAS(0)
010100 ALERJ(1) · 016100 FUNDO ALERJ(2) · 016200 FUNPGALERJ(2026) · 020100 TCE-RJ(3) · 026100 FEM/TCE-RJ(4)
026200 FUNPGT(2026) · 030100 TJ(5) · 036100 FETJ(6) · 036200 FEEMERJ(7) · 036300 FUNARPEN(8)
040100 SEPLANIG-Extinta(9) · 043400 AGETRANSP(10) · 043500 AGENERSA(11) · 044100 DER-RJ(12) · 045200 EMOP(13)
046500 FRSCPER(14) · 050100 SEDC-Extinta(15) · 053100 IPEM(16) · 060100 GSI(17) · 070100 SEINFRA-Extinta(18)
070200 CEDAE ACOES DESC.(19) · 080100 VICE-GOV(20) · 090100 PGE(21) · 096100 FUNPERJ(22) · 100100 MP(23)
100200 CEJ(24) · 106100 FEMP(25) · 110100 DPGE(26) · 116100 FUNDPERJ(27) · 120100 Antiga SEPLAG(28)
120200 SEFAZ LOGISTICA(29) · 123100 IPERJ-Extinto(30) · 123400 RIOPREVIDEN(31) · 123401 RIOPREVI-ALERJ(32)
123402 RIOPREVI-TCE(33) · 123403 RIOPREVI-TJUSTICA(34) · 123404 RIOPREVI-EXECUTIVO(35) · 123410 RIOPREVI-MP(36)
123411 RIOFUNDOPREVI-ALERJ(37) · 123412 RIOFUNDOPREVI-TCE(38) · 123413 RIOFUNDOPREVI-TJ(39)
123414 RIOFUNDOPREVI-EXEC.(40) · 123420 RIOFUNDOPREVI-MP(41) · 123422 RIOPREV-SPSM(42) · 123425 RIOPREV-TXADM(43)
123499 RIOFUNDOPREVI(44) · 124100 CEPERJ(45) · 124200 RJPREV(46) · 130100 SEAPPA(47) · 130200 FUNDEAGRO-RJ(48)
130900 PROJ. RIO RURAL/GEF(49) · 133100 ITERJ(50) · 134100 FIPERJ(51) · 135300 EMATER-RIO(52) · 135400 PESAGRO-RIO(53)
136200 FUNDEAGRO(54) · 137100 CASERJ(55) · 137200 CEASA(56) · 140100 SECC(57) · 144100 FENORTE(58) · 146400 FEFOSP(59)
150100 SECEC(60) · 154100 FUNARJ(61) · 154300 FTMRJ(62) · 154400 FMIS(63) · 156100 FEC-RJ(64) · 160100 SEDEC(65)
166100 FUNESBOM(66) · 170100 SEEL(67) · 173100 SUDERJ(68) · 176100 FUNJOVEM(69) · 180100 SEEDUC(70) · 180300 CEE(71)
190100 SEHAB(72) · 196100 FUNTERJ(73) · 196200 FEHIS(74) · 197100 CEHAB(75) · 200100 SEFAZ(76) · 203100 LOTERJ(77)
206100 FAF(78) · 207100 CFSEC(79) · 210100 SEPLAG(80) · 210110 SUBGERAL(81) · 210600 SSMGSI(82) · 210700 DEGASE(83)
210900 SUBGAP(84) · 213200 RIOMETROPOLE(85) · 213600 PROCON(86) · 215300 SERVE(87) · 216100 FUNDEP(88)
216400 FUSPRJ(89) · 216500 FDRM(90) · 217100 METRO(91) · 217200 CTCRJ(92) · 217300 FLUMITRENS(93) · 220100 SEDEICS(94)
220200 FUNDES(95) · 223200 JUCERJA(96) · 226100 FREMF(97) · 226200 FEMPO(98) · 226300 FSERJ(99) · 227100 CODIN(100)
230100 SEDHSP-GS-Extinta(101) · 240100 SEA(102) · 240200 SEA-PSAM(103) · 240400 FECAM(104) · 243100 IEEA(105)
243200 INEA(106) · 244100 FEEMA(107) · 244200 IEF(108) · 244300 SERLA(109) · 246300 FUNDRHI(110) · 250100 SEAP(111)
254100 FSCABRINI(112) · 256100 FUESP(113) · 260100 SESEG(114) · 260200 SESP(115) · 260400 SEPOL(116) · 261100 SEPM(117)
263100 DETRAN-RJ(118) · 263200 ISP(119) · 266100 ACADEPOL(120) · 266200 SECSP-FUNESPOL(121) · 266400 FUNESSP(122)
266500 FUNNESPOLMILI(123) · 266600 FISED(124) · 280100 SEJDC-Extinta(125) · 290100 SES(126) · 293100 IASERJ(127)
294200 FS(128) · 296100 FES(129) · 297100 IVB(130) · 300100 SETRAB(131) · 300200 FUNRIO(132) · 306100 FEFEPS(133)
306200 FTRJ(134) · 310100 SETRAM(135) · 313300 DETRO-RJ(136) · 316100 FUND.EST.TRANSPORTE(137) · 317100 CODERTE(138)
317200 CENTRAL(139) · 317300 RIOTRILHOS(140) · 320100 SEASDH(141) · 320200 SUBSEC.JUST/DIR.HUM(142) · 324200 F.L.XIII(143)
326100 FEAS(144) · 326400 FUPDE(145) · 350100 SEINPE-Extinta(146) · 353100 DRM(147) · 370100 EGES-SEPLAG(148)
370200 EGE-SEFAZ(149) · 370300 EGE-PREC.JUDICIAIS(150) · 370301 EGE-RPV(151) · 370400 EGE-EMPRESAS EXTINTAS(152)
370500 EGE-DIVIDA PUBLICA(153) · 390100 SUBCOM(154) · 390200 SUBCOM-DESCENTRAL.(155) · 400100 SECTI(156)
400200 GIEDUC(157) · 403200 PRODERJ(158) · 404100 FAPERJ(159) · 404300 UERJ(160) · 404310 A.C(161) · 404320 CEPUERJ(162)
404330 NUSEG(163) · 404340 HUPE(164) · 404350 UERJ-ZO(165) · 404400 FAETEC(166) · 404500 UENF(167) · 404600 CECIERJ(168)
404700 UEZO(169) · 406100 FATEC(170) · 406200 FUNCIERJ(171) · 410100 SEDEB-Extinta(172) · 420100 SEIJ-Extinta(173)
424100 FIA(174) · 426100 FUNDO FIA(175) · 430100 SETUR(176) · 437100 TURISRIO(177) · 444100 FUNDACAO CIDE(178)
450100 SEDRAP(179) · 460100 SEC. ENV. QUAL.VIDA(180) · 470100 SEPROCON(181) · 476100 FEPROCON(182) · 480100 SEPREVDEPQ(183)
486100 FESPREN(184) · 490100 SEDSODH(185) · 496420 FUNDEPI(186) · 500100 CGE(187) · 506100 FACI(188) · 530100 SEIOP(189)
540100 SERGB(190) · 550100 SEVAPD(191) · 570100 SEGOV(192) · 580100 SETD(193) · 590100 SEM(194) · 596100 FEDM(195)
600100 SEIJES(196) · 610100 SEGG(197) · 620200 SEDCON(198) · 630100 SEACJ(199) · 636100 FUNJOVEM(200) · 640100 SEENEMAR(201)
650100 SEHIS(202) · 660100 SECID(203) · 999900 TESOURO ESTADUAL(204) · 999901 SUTES(205) · 999902 SUCOMF(206)
```

---

## 5. Filtro genérico (padrão ADF — quase todas as telas) — **destrava o limite de 1000**

Substituir `PREFIX` pelo prefixo da tela e `TABELA` pelo ID da tabela.

**Estrutura:**
- `PREFIX:TABELA:sdtFilter::head` (cabeçalho "Filtro") · `::disAcr` (expandir/colapsar) · `::btn` · `::body` · `sdtFilter` (container)
- `PREFIX:TABELA:btnClearFilter` (LIMPAR / borrachinha) · `::icon`

**Campos por linha de filtro** (N = índice 0,1,2…):
- `PREFIX:TABELA:table_rtfFilter:N:cbx_col_sel_rtfFilter::content` — SELECT "Propriedade" (campo a filtrar)
- `PREFIX:TABELA:table_rtfFilter:N:chk_neg_rtfFilter::content` — checkbox "Negar"
- `PREFIX:TABELA:table_rtfFilter:N:cbx_op_sel_rtfFilter::content` — SELECT "Operador"
- `PREFIX:TABELA:table_rtfFilter:N:in_value_rtfFilter::content` — INPUT "Valor" (**gerado via PPR** — só
  aparece após selecionar Operador)

**Operadores (value):** `""=Selecione · 0=igual · 1=maior que · 2=maior ou igual · 3=menor que ·
4=menor ou igual · 5=diferente · 6=é nulo · 7=contém · 8=começa com · 9=termina com · 10=pertence (sep. por ;)`

**Sequência correta:** (1) selecionar Propriedade; (2) selecionar Operador; (3) ADF faz PPR e cria o campo
Valor; (4) digitar o Valor; (5) **sem Enter** — a tabela atualiza ao vivo (PPR no blur/change); (6) nova
linha `:1:` aparece sozinha para o próximo filtro (AND implícito entre linhas).

**Limpar:** clicar "Limpar" (visual) ou `document.getElementById('PREFIX:TABELA:btnClearFilter').click()`.

**Limite de registros (o gargalo §8b):**
- Padrão **1000 registros**; aviso em `PREFIX:TABELA:txt_maxResults` ("Limite de 1000 registros.").
- ✅ **Checkbox para remover o limite:** `PREFIX:TABELA:chkRemoveLimit::content` (checkbox). Marcado →
  carrega **todos** os registros (presente p.ex. em Acompanhamento de PD, Código de Barras, Guia de Devolução).
- **Estratégia >1000 sem o checkbox:** (a) filtrar por UG Emitente; (b) por período (Data Emissão ≥ e ≤);
  (c) por Status; (d) por Número "começa com" prefixo; (e) "pertence (;)" para múltiplos valores;
  combinar linhas (AND); iterar em blocos (ex.: 2026OB00001→01000, 01001→02000…).

---

## 6. Toolbar padrão

`PREFIX:TABELA:tbrBotoes` (container) · `btnInsert` · `btnEdit` · `btnView` (Visualizar = double-click) ·
`btnCopiar` · `btnExcluir` · `btnImprimir`.

**Abrir detalhe:** (1) clicar UMA vez na linha (fica azul); (2) clicar `btnView`. O double-click via JS
(`dispatchEvent dblclick`) **não funciona** — precisa ser interação visual.

**Popups padrão:** `popConfirmacaoExclusao · popExclusao · popActivate · popDeactivate · popRestauracao`.

---

## 7. Telas do módulo Execução Financeira

### 7.1 Acompanhamento de Execução de PD — `acompanhamentoExecucaoPDCad.jsp` · prefixo `tpl:` · tabela `tpl:tblAcompanhamento`
Colunas (`tabViewerDec_col_0..8`): Id · Responsável · UG · Descrição · Agendamento · Início · Término · Status · Valor.
Botões: `btnView` · `btnPrint` · `idExecutarNovamente` (Disponibilizar p/ Nova Execução) · `grpButtons`.
Limite: `tpl:tblAcompanhamento:chkRemoveLimit::content` (remove limite). Filtro colapsado.

### 7.2 Bloqueio Judicial — `bloqueioJudicialCad.jsp` · prefixo `pagTemplate:` · tabela `pagTemplate:tblEntidadeDec`
Colunas: Código · Código Credor · Nome Credor · Valor Bloqueado · Data Bloqueio · Data Desbloqueio · Autos do Bloqueio · Status.
Status: Bloqueado, Desbloqueado. Botões (padrão ADF). ⚠️ Usa prefixos `af_` nos ícones — comportamento visual pode diferir.

### 7.3 Código de Barras — `codigoBarrasCad.jsp` (estimado) · prefixo `pt1:` · tabela `pt1:tblEntidadeDec`
Colunas (`col_0..11`): Tipo · Unidade Gestora · Cód. Beneficiário · Beneficiário · Código de Barras · Valor ·
Desconto/Abatimento · Juros/Multa · Ordem bancária · Programação de Desembolso · Observação · Status.
Botões: `btnInsert · btnView · btnImprimir` + link "Importar Código de Barras". Tipo: "Fatura". Status: Pago, Desativado.
Limite: `pt1:tblEntidadeDec:chkRemoveLimit::content`.

### 7.4 Fechamento do Dia — `pagamentoCad.jsp` · prefixo `ptPrincipal:` · tabela `ptPrincipal:tblProcessamentostable`
Colunas (`tblProcessamentostable_col_0..5`): Código · Processo · Data de Início · Data de Término · Usuário · Status.
Botões: `tblProcessamentosviewButton` (Visualizar) · `btnProcessar` (Gerar Prévia) · `btnExecutar` · `btnExcluir` ·
`btnAtualizar` · `tblProcessamentostoolbar`. Popup: `popExclusao`.

### 7.5 Guia de Devolução — `guiaDevolucaoCad.jsp` · prefixo `pt1:` · tabela `pt1:tblGuiaDevolucao`
Colunas (`tabViewerDec_col_0..7`): Número · UG Emitente · Data Emissão · Tipo de Baixa · Status · Cód. UG Liquidante · OB · Valor.
Botões: `btnInsert · btnEdit · btnView · btnCopiar · btnExcluir · btnImprimir`.
Accordion: `pnlAccordionDec_afrCl0` (Filtro) · `pnlAccordionDec_afrCl1` (Conteúdo). Limite: `pt1:tblGuiaDevolucao:chkRemoveLimit::content`.

### 7.6 Guia de Recolhimento — `guiaRecolhimentoCad.jsp` · prefixo `pt1:` · tabela `pt1:tblGuiaRecolhimento`
Colunas (`tabViewerDec_col_0..11`): Número · UG Emitente · UG Orçamentária · UG 2 · Nome UG 2 · Data Emissão · Tipo ·
Status · Estorno · Doc. Alterado · Automática · Valor.
Botões: `btnInsert · btnEdit · btnView · ...` **[mensagem-fonte truncada aqui — completar 7.6+ depois]**

---

## Como o JFN usa isto (operacionalização)
- **`siafe_ob_orcamentaria.py`** (tela 7 / OB Orçamentária `ordemBancariaOrcamentariaCad.jsp`): aplicar a
  sequência da §5 e, sobretudo, marcar `chkRemoveLimit` **ou** iterar por UG (mapa §4) + período p/ romper o
  limite de 1000 (resolve o §8b de `SIAFE-ARQUITETURA.md`).
- **`compliance_agent/ugs.py`**: cruzar o mapa de UGs (§4) com o canônico TFE (lembrar: numeração SIAFE-Rio 2
  ≠ numeração TFE; ITERJ = 133100 nas duas, mas índices diferem).
- **Gotchas que evitam derrubar a sessão:** §2 (popup `myModal`) e §6 (interação visual, não `el.click()`/dblclick JS).
