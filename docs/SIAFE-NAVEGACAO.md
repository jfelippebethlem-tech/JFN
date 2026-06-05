# SIAFE-Rio 2 — Mapa de Navegação e Funções (ADF)

Documento vivo: caminhos, telas e seletores do SIAFE-Rio 2 descobertos pela coleta automatizada.
Atualizar sempre que aprender um caminho novo. (Oracle ADF — `siafe2.fazenda.rj.gov.br/Siafe/faces/...`)

## Acesso
- **URL login:** `/Siafe/faces/login.jsp` — campos `loginBox:itxUsuario::content` (CPF),
  `loginBox:itxSenhaAtual::content` (senha), `<select>` Exercício, botão "Ok".
- **MFA:** por email, **por login** (muda a cada tentativa). Campo `loginBox:frmTokenMfa:itxTokenMfa::content`;
  checkbox **`loginBox:frmTokenMfa:ckTrustDevice::content`** = "dispensar 30 dias" → marcar e salvar
  `storage_state` (siafe_state.json) evita MFA por ~30 dias. (Ver `compliance_agent/siafe_session.py`.)
- **A VM GCP acessa o SIAFE direto** (WAF não bloqueia este IP).

## Pós-login
- Cai em **`/administracao/seguranca/acessoRapido.jsp`** (página "Acesso Rápido").
  Tem `pt1:iTxtCad::content` (NÃO é busca de transação — não traz sugestões) e `pt1:selUg::content`
  (dropdown de UG — lista todas as UGs, ex.: `0:TODAS`, `7:030100 - TJ`, `21:070200 - CEDAE`, ...).
- **Sessão expira em ~60 min** de inatividade ("Sua sessão expira em: 59:34").
- Breadcrumb no topo, ex.: "Administração > Segurança > Acesso Rápido".

## Menu principal (barra de topo, `a.xyo`)
Itens: **Execução** · Planejamento · Projetos · Apoio · Administração · Relatórios · Segurança ·
Configuração · Estrutura Classificatória · Migração de Dados · Monitoramento · Agendamento ·
Assinatura Eletrônica · Redistribuição · Regras de Descentralização.

### Execução (clicar `a.xyo` com texto exato "Execução") → submenu:
- Execução Orçamentária
- **Execução Financeira**  ← Ordens Bancárias ficam aqui dentro
- Contabilidade
- Contratos e Convênios
- Folha de Pagamento
- Mensagens · Acompanhamento Execução

### Execução > Execução Financeira  ✅ CAMINHO MAPEADO
**Sequência que funciona (driver `coletar_obs_sessao.py`):**
1. Clicar `a.xyo` com texto exato **"Execução"** (abre o submenu).
2. Clicar o id **`pt1:pt_np3:1:pt_cni4::disclosureAnchor`** = "Execução Financeira" (disclosureAnchor, expande).
3. Clicar `<a>` com texto exato **"Ordens Bancárias"** (id observado `pt1:pt_np2:8:pt_cni3` — o sufixo numérico
   pode variar entre sessões; preferir clicar pelo TEXTO). → vai para `/execucao/financeira/execucaoFinanceiraMain.jsf`.

**Itens do submenu Execução Financeira:** Acompanhamento de Execução de PD · Bloqueio Judicial ·
Código de Barras · Fechamento do Dia · Guia de Devolução · Guia de Recolhimento ·
**Lista de Favorecido para OB** · Nota de Aplicação e Resgate · **Ordens Bancárias** · OB Orçamentária ·
OB de Dedução · OB de Retenção · OB de Transferência · OB Extra-orçamentária ·
Programações de Desembolso (PD Orçamentária/Retenção/Transferência/Extra) · Tipo de Conciliação Bancária.

### ✅✅ LEITURA DA GRADE — FUNCIONANDO (coleta provada com OBs reais)
A grade de dados das OBs é **`pt1:tblOrdemBancaria:tabViewerDec::db`** (NÃO `tblOrdemBancaria::db`,
que é o filtro). Cabeçalho em `:tabViewerDec::ch`. **16 colunas, nesta ordem:**
`Número, UG Emitente, UG Pagadora, Data Emissão, Status, Tipo, Tipo de OB, Favorecido,
Nome do Favorecido, GD, Processo (nº SEI), RE, PD, Status de Envio, Valor, Assinatura Digital`.
- Reader: ler `tr`→`td` de `tabViewerDec::db`. Validado: 50 OBs reais lidas (ex.: `2026OB04836` Tesouro
  R$221.324.029,50; `2026OB05568` proc `0001.0034022.2026-03` R$35.998,28). Driver: `coletar_obs_sessao.py`.
- **Paginação:** botão "próxima" do ADF ainda a afinar (a 1ª tentativa leu só a página 1 = 50 linhas).
- **Filtro por favorecido:** ainda o problema do PPR do rtfFilter (abaixo) — alternativa atual: filtrar por
  `Nome do Favorecido` em Python (`--nome`), mas só sobre as páginas lidas. Para MGS, ou afinar o filtro ADF
  ou ler todas as páginas. Coluna **Processo** dá o nº SEI → liga OB ao processo (objetivo do Mestre Jorge).

### Tela de Ordens Bancárias  ✅ IDs MAPEADOS
URL: `/Siafe/faces/execucao/financeira/execucaoFinanceiraMain.jsf` (carrega a grade async — esperar ~10s).
Abas: **"Filtro"** e **"Lista de Favorecido para OB"**.
- **Grade:** `pt1:tblOrdemBancaria` (usada por `_filtrar_por_cnpj`/`_ler_tabela`).
- **Filtro (accordion):** `pt1:tblOrdemBancaria:sdtFilter::disAcr` (cabeça `::head`, corpo `::body`, botão `::btn`).
- **Tabela (accordion):** `pt1:tblOrdemBancaria:sdtTabela::disAcr`.
- **Máx. resultados:** `pt1:tblOrdemBancaria:txt_maxResults`.
- **Botões:** `:btnEdit` (editar), `:btnView` (visualizar), `:btnImprimir` (imprimir/exportar), `:tbrBotoes` (barra).
- **Filtrar por CNPJ do favorecido:** usar a aba **"Lista de Favorecido para OB"** ou o accordion Filtro.

> ✅ FEITO: `coletar_obs_sessao.py::_navegar_ob` faz Execução → `pt1:pt_np3:1:pt_cni4::disclosureAnchor`
> (Execução Financeira) → clique em "Ordens Bancárias". Chega na grade `tblOrdemBancaria` (confirmado).

### ÚLTIMO TRECHO PENDENTE — filtrar por favorecido e ler a grade
A grade **vem vazia**: o SIAFE só popula após aplicar um filtro. Na tela de OB há duas abas:
**"Filtro"** e **"Lista de Favorecido para OB"**; a de favorecido tem botões **"Inserir"** e **"Filtro"**.
O campo de favorecido/CNPJ fica **atrás do botão "Filtro"** (LOV do ADF "Favorecido" / "Nome do Favorecido").
- Pendência: clicar o botão "Filtro" da aba favorecido de forma robusta (o match por texto exato é instável),
  abrir o LOV "Favorecido", preencher o CNPJ, "Pesquisar", e então `_ler_tabela` (`pt1:tblOrdemBancaria`).
- `_filtrar_por_cnpj` (antigo) não acha o campo (`_JS_APLICAR_FILTRO_CNPJ` não casa o LOV) — adaptar para
  o campo "Favorecido" desta build. Screenshots de apoio: `data/sei_cache/siafe_*.png`.
- Alternativa: aba "Filtro" (accordion `pt1:tblOrdemBancaria:sdtFilter::disAcr`) com campos por UG/data/número.

### ✅ Filtro avançado (rtfFilter) — MAPEADO; falta só o PPR do valor
O accordion **Filtro** (`pt1:tblOrdemBancaria:sdtFilter::head` para abrir) tem um **filtro dinâmico por linha**
(`pt1:tblOrdemBancaria:table_rtfFilter:0:`):
- **Propriedade** (`cbx_col_sel_rtfFilter::content`, `<select>`): opções = Número, UG Emitente, UG Pagadora,
  Data Emissão, Status, Tipo, Tipo de OB, **Favorecido**, **Nome do Favorecido**, GD, **Processo** (nº SEI!),
  RE, PD, Status de Envio, Valor, Assinatura Digital.
- **Operador** (`cbx_op_sel_rtfFilter::content`): igual, contém, começa com, termina com, maior/menor que, é nulo,
  diferente de, pertence (separado por ;).
- **Negação** (`chk_neg_rtfFilter::content`, checkbox).
- Botões: **"Filtro"** (aplica) e **"Limpar"**.

**🔴 BLOQUEIO TÉCNICO (último 5%):** ao setar a Propriedade via `page.select_option` (Playwright), o **campo
de VALOR não é criado** — o ADF só renderiza o input de valor após o **PPR (partial page refresh) disparado
pelo evento de mudança do WIDGET ADF**, não do `<select>` nativo. `select_option` muda o `<select>` oculto mas
não aciona o `AdfRichUIPeer`/autosubmit.
**Próximo passo (fix):** interagir com o widget visual do ADF — clicar o dropdown (`...cbx_col_sel_rtfFilter`),
clicar a opção pelo texto, deixar o ADF fazer o PPR; idem operador; então o input de valor aparece → preencher
"MGS CLEAN" (ou CNPJ na propriedade "Favorecido") → clicar "Filtro" → `_ler_tabela` (`pt1:tblOrdemBancaria`).
Alternativa: disparar o autosubmit do ADF via JS (`AdfPage.PAGE.... ` / evento `_adfsu`) após setar o select.

> **Dedup SIAFE×TFE:** ao gravar OBs coletadas, usar UPSERT por `numero_ob` (idempotente) e manter SEPARADO do
> agregado TFE (granularidades diferentes: TFE = execução agregada por classificação; OB = pagamento nominal).

### ⚠️ LIMITE TÉCNICO do ADF (filtro/paginação) — honesto
A grade entrega **as 50 OBs mais recentes** (fetch size do ADF) e isso JÁ é ingerido no painel
(`coletar_obs_sessao --ingest` → `ordens_bancarias` → painel mostra valor total). PORÉM, para
**filtrar por favorecido** ou **paginar além das 50**, o ADF rich-client **não responde a interação
programática**: `select_option`/`fill`/`dispatchEvent` não disparam o PPR (o campo de valor do filtro
não renderiza; `txt_maxResults` e scroll não recarregam). Cliques em **âncoras de menu** funcionam
(é como `_navegar_ob` navega), mas inputs/selects com autosubmit exigem eventos "trusted" que o ADF
headless ignora. **Caminhos viáveis para coleta completa/MGS (futuro):**
1. **Interceptar as respostas PPR** (XHR/XML) do ADF e ler os dados crus da resposta do servidor.
2. **Export nativo** do ADF (botão `pt1:tblOrdemBancaria:btnImprimir` / `menuImprimir` → Excel/CSV) — exporta tudo.
3. **GitHub Actions** com o `_SANDBOX/coletar_obs_agora.py` (mesma sessão, mas o filtro lá idem precisa do fix).
> Não é falha de credencial/navegação (essas funcionam 100%) — é a barreira de automação do Oracle ADF.

### Tentativas EXAUSTIVAS de coleta completa (>50 OBs) — todas bloqueadas em HEADLESS
A grade exibe "**Limite de 1000 registros**" (o dado existe), mas o DOM (`tabViewerDec::db`) só contém
~50 linhas (scroll virtual). Testado e FALHOU em headless:
1. `select_option`/`fill` no filtro e em `txt_maxResults` → ADF não dispara o PPR (campo de valor não renderiza).
2. Scroll JS (`scrollTop`) e **scroll real (`mouse.wheel`)** sobre a grade → DOM permanece 50 (sem lazy-load).
3. Nenhum container com `overflow:auto/scroll` dentro da grade (ADF gerencia o scroll por JS próprio).
4. Interceptar requests PPR → as 50 linhas chegam EMBUTIDAS na resposta do clique de menu, não num fetch
   de range replicável.
5. Export/Imprimir (`btnImprimir` → "Imprimir") → não gera download nem nova página em headless (usa window.print).

**CAMINHO REALISTA p/ a base completa (próxima sessão dedicada):**
- **Rodar o navegador em modo HEADED com display virtual (xvfb)** — em headless o ADF rich-client
  suprime scroll-fetch/export; com display real, `mouse.wheel`/export tendem a funcionar como num browser
  de verdade. (Setup: `xvfb-run` + `headless=False`.) É a aposta mais promissora.
- Alternativa: reverter o protocolo de partial-submit do ADF (replicar o XML de evento de scroll da tabela).
- A coleta das **50 OBs recentes funciona** e já alimenta o painel/relatório — é a base mínima confiável.

## Coleta de OBs (objetivo)
- Filtrar por CNPJ do favorecido. Funções prontas em `_SANDBOX/coletar_obs_agora.py`:
  `_ir_obs`, `_ir_lista_favorecido`, `_filtrar_por_cnpj`, `_ler_tabela`.
- Driver que reusa a sessão (sem MFA): `compliance_agent/coletar_obs_sessao.py`.
- Cadeia para avaliar processo na íntegra: **OB → Nota de Liquidação → Nota de Empenho → processo (SEI)**.

## Exercícios (valor do `<select>`)
`{2027: "0", 2026: "1", 2025: "2", 2024: "3", 2023: "4"}`
