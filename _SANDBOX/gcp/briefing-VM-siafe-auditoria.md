# BRIEFING — Claude da VM: finalizar a automação SIAFE (auditoria JFN)

> Cole isto no Claude da VM (que roda na VM GCP, com Playwright nativo). Objetivo: fechar os
> 100% da auditoria — **lista formal de TODOS os contratos** de um fornecedor + **valor PAGO** (OB),
> além dos empenhos sem contrato no histórico. Tudo decifrado abaixo; é só implementar e testar
> AO VIVO contra o SIAFE, **no ritmo humano** (pausas 3–8s; nunca em rajada; é sistema do governo).

## Contexto
- Repo já clonado na VM em `~/JFN` (branch `claude/rj-finance-agent-BYlhJ`). Faça `git pull`.
- Já existe `siafe_agent/browser/siafe_browser.py` (Playwright) — você vai ADICIONAR métodos nele.
- Credenciais no `~/.hermes/.env`: `SIAFE_USUARIO`, `SIAFE_SENHA`. (Se não tiver SIAFE_*, o Mestre
  Jorge cola: usuário 14398839712.) NUNCA imprima segredos.
- Alvo de teste: **MGS CLEAN, CNPJ 19.088.605/0001-04**, exercícios 2025 e 2026.
- Use **Chromium nativo do Playwright em aba única** (`launch()`, NÃO `connect_over_cdp`).

## LOGIN (verificado)
- URL: `https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp`
- `fill('[id="loginBox:itxUsuario::content"]', usuario)`
- `fill('[id="loginBox:itxSenhaAtual::content"]', senha)`
- `select_option('[id="loginBox:cbxCliente::content"]','0')`  (Rio de Janeiro)
- `select_option('[id="loginBox:cbxExercicio::content"], '2')`  → **2025=`2`, 2026=`1`** (2024=3,2023=4)
- `click('[id="loginBox:btnConfirmar"]')`  → sucesso = sai de login.jsp
- Fechar popup decreto: clicar botão **OK** se visível.

## NAVEGAÇÃO ADF — o que aprendi (cuidado!)
- Os anchors do topo (`pt1:pt_np4:*`) e sub-abas (`pt1:pt_np3:*`) têm **`onclick="return false"`** e às
  vezes id DUPLICADO (um oculto). **Não use `page.click(id)` direto** (pega o oculto / não navega).
- **Funciona:** clicar nas **coordenadas do elemento VISÍVEL** (pegar `getBoundingClientRect` do
  elemento visível e `page.mouse.click(x,y)`), OU navegar pela sub-aba certa após ativar o topo.
- ⚠️ Em sessão recém-logada (tela `acessoRapido`), clicar por TEXTO é traiçoeiro (cliquei "Contrato"
  e caí em Administração→Plano de Contas). **Teste e valide com screenshot a cada passo.**
- Caminho desejado: **Execução → Contratos e Convênios → Contrato**
  (sub-aba Contratos e Convênios = `pt1:pt_np3:3:pt_cni4::disclosureAnchor`; item lateral
  Contrato = `pt1:pt_np2:2:pt_cni3`). Para pagamentos: **Execução → Execução Financeira
  (`pt1:pt_np3:1`) → Ordens Bancárias (`pt1:pt_np2:8:pt_cni3`)**.
  💡 Dica: avalie usar a caixa **"Acesso Rápido"** (`pt1:iTxtCad::content`) digitando o nome da
  função — pode navegar direto e fugir do menu instável. Teste.

## FILTRO da grade (O PULO DO GATO — decifrado)
1. O texto **"Filtro"** (`...:pnlAccordionDec_afrCl0`) é **ARMADILHA** (`onclick="return false"`).
2. Quem ABRE o painel é o disclosure **`pt1:tblContrato:sdtFilter::disAcr`** (title "Mostrar este
   painel"). Para OB é `pt1:tblOrdemBancaria:sdtFilter::disAcr`. Clique nesse.
3. Filtro é "rich table filter":
   - **Propriedade**: `pt1:tblContrato:table_rtfFilter:0:cbx_col_sel_rtfFilter::content`
     → opção **`9` = Nome do Contratado** (ou `7` = Cod. Contratado/CNPJ).
   - **Operador**: `...:cbx_op_sel_rtfFilter::content` → "contém" ou "igual".
4. ⚠️ **O campo de VALOR só renderiza após o PPR do ADF** ao trocar a Propriedade. Por isso
   `select_option` do Playwright **funciona** (dispara o evento real) mas setar `.value` por JS NÃO.
   Após `select_option`, espere `wait_for_load_state('networkidle')`, então localize o input de
   texto que apareceu na linha do filtro (`[id*="table_rtfFilter:0"] input[type=text]`),
   `fill('MGS CLEAN')` e `keyboard.press('Enter')`.

## EXTRAÇÃO
- Grade Contrato — colunas: `Número Automático | Nº Licitação | Nº Original | Natureza | Objeto |
  Cód. Contratante | Nome Contratante | Cod. Contratado | Modalidade | Nome do Contratado |
  Situação | Valor do Contrato | Qtd. Aditivos | Qtd. Reajustes | Qtd. Anexos`.
- Grade OB — colunas: `Número | UG Emitente | UG Pagadora | Data Emissão | Status | Tipo |
  Tipo de OB | Favorecido | Nome do Favorecido | GD | Processo | RE | PD | Status Envio | Valor`.
- Extraia todas as linhas (paginação: avançar página com clique real até acabar). Salve em
  `data/sei_cache/` (fora do git).

## OS ~16% SEM CONTRATO NO HISTÓRICO
Para os empenhos cujo histórico não cita contrato: pegue o nº do **Empenho** (coluna da consulta
TFE / da OB) e abra em **Execução Orçamentária → Nota de Empenho** (filtro pelo nº) — o detalhe
traz o contrato e o processo vinculados.

## ENTREGÁVEIS
1. `siafe_browser.py`: métodos `buscar_contratos_por_contratado(nome_ou_cnpj)` e
   `buscar_ob_por_cnpj(cnpj, exercicio)` (pago) — testados ao vivo.
2. Atualizar o relatório `_SANDBOX/auditorias/MGS-CLEAN-2025-2026.md` com: lista FORMAL de todos os
   contratos (nº, objeto, valor, situação, aditivos) e a coluna **PAGO** por mês (vs empenhado).
3. `git add` + `commit` + `push` na branch.

## REGRAS
- Ritmo humano (pausas), só leitura, nunca imprimir segredos, backup antes de sobrescrever,
  parar e reportar se aparecer bloqueio/captcha. Validar cada passo com screenshot.
