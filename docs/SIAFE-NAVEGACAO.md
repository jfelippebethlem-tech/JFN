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

## Coleta de OBs (objetivo)
- Filtrar por CNPJ do favorecido. Funções prontas em `_SANDBOX/coletar_obs_agora.py`:
  `_ir_obs`, `_ir_lista_favorecido`, `_filtrar_por_cnpj`, `_ler_tabela`.
- Driver que reusa a sessão (sem MFA): `compliance_agent/coletar_obs_sessao.py`.
- Cadeia para avaliar processo na íntegra: **OB → Nota de Liquidação → Nota de Empenho → processo (SEI)**.

## Exercícios (valor do `<select>`)
`{2027: "0", 2026: "1", 2025: "2", 2024: "3", 2023: "4"}`
