# FlexVision — acesso, MFA, DOM e folha de pagamento (evolução)

**Objetivo:** coletar a FOLHA DE PAGAMENTO dos 6 órgãos (e do estado) pela **fonte ÚNICA já
autenticada** — o FlexVision (BI da SEFAZ-RJ sobre o SIAFE) — em vez de raspar 6 portais de
órgão (decisão do Jorge 2026-06-07: raspar N portais é "estúpido"; usar a fonte consolidada).

Doc-irmão: `docs/SIAFE-EVOLUCAO-TENTATIVAS.txt` (lições de SIAFE/ADF, Chrome CDP 9222).
Ferramenta: `tools/flexvision_cdp.py` (login/code/status via Chrome persistente CDP).

---

## 1. Acesso
- **URL:** https://siafe2-flexvision.fazenda.rj.gov.br/Flexvision/
- **Stack:** **Vaadin** v3.36.0 (GWT). NÃO usa `<a>/<button>` padrão — classes `v-button`,
  `v-widget`, `v-window`, `v-caption`, `v-textfield`. IDs são `gwt-uid-N` (DINÂMICOS — não
  confiar entre sessões; usar seletores estruturais).
- **Login próprio**, mas com as **MESMAS credenciais do SIAFE** (`SIAFE_USER`/`SIAFE_PASS` no .env).
- **WAF por fingerprint:** Chromium real passa (igual SIAFE/SEI). curl/httpx é dropado.

## 2. MFA (Autenticação Multifator)
- Após user+senha corretos → diálogo **"Autenticação Multifator"**: código enviado por **e-mail**
  (`jo***@al***`). **Expira em poucos minutos.** Cada novo login dispara um **código novo**
  (invalida o anterior).
- Tem checkbox **"Dispensar código neste dispositivo por 30 dias"** → marcar + salvar
  `storage_state` = **sem MFA por 30 dias**.
- Atravessar o MFA ENTRE turnos: usar o **Chrome persistente da porta 9222 (CDP)** — ele segura
  o diálogo vivo enquanto eu desconecto; no turno seguinte reconecto e digito o código.

## 3. Estrutura DOM (mapeada 2026-06-07) — PRECISA
Tela de login + diálogo MFA coexistem no DOM (o login fica ATRÁS do `.v-window`):
- **Login (fundo):**
  - Usuário: `input[type=text]` (ex. id `gwt-uid-5`), classe `v-textfield`.
  - Senha:   `input[type=password]` (ex. id `gwt-uid-7`).
  - Botão Login: `.v-button` com texto "Login".
- **Diálogo MFA (`div.v-window`):**
  - **Campo "Código" = `input[type=password]` DENTRO do `.v-window`** (ex. id `gwt-uid-15`).
    ⚠️ NÃO é `input[type=text]` — o único text é o USUÁRIO do login, atrás do diálogo.
  - Checkbox "30 dias" = `.v-window input[type=checkbox]` (ex. id `gwt-uid-13`).
  - Botões: `.v-button` "Ok" e "Cancelar" dentro do `.v-window`.

## 4. O QUE FUNCIONA ✅
- **Chrome CDP 9222** já estava vivo (da sessão SEI) → reaproveitado p/ MFA entre turnos.
- `tools/flexvision_cdp.py login` → preenche user/senha (`.type()`, limpando antes com `.fill("")`),
  clica `.v-button` "Login" → chega no MFA (dispara código).
- `tools/flexvision_cdp.py code <COD>` → digita no `.v-window input[type=password]`, marca o
  checkbox 30 dias via JS, clica "Ok" via **JS** (`.click()` no elemento) → valida.
- **Reset do diálogo:** `pg.goto(FV)` recarrega e volta ao FORM de login (mesmo que o SPA
  estivesse no MFA). Daí refazer login dispara código novo.
- Login user/senha corretos → resposta clara do servidor (MFA aberto, ou erro explícito).

## 5. O QUE FALHOU — NÃO REPETIR ❌
1. **`tools/flexvision_explore.py` (launch direto)**: loga user/senha mas TRAVA no MFA (não tem
   como atravessar sem o Chrome persistente). Serve só p/ explorar DEPOIS de logado.
2. **Digitar o código MFA no `input[type=text]`**: ERRADO — esse é o campo USUÁRIO do login
   (ficou com o CPF `14398839712`). O código vai no `input[type=password]` do `.v-window`.
3. **Clicar botão (Login/Ok) com `pg.click()` quando há overlay de erro**: o `div aria-live`
   (mensagem "código inválido") **intercepta pointer events** → 57+ retries e timeout.
   → Solução: clicar via **JS** (`el.click()`), que ignora o overlay; OU recarregar a página antes.
4. **Clique-JS no botão Vaadin "Login" numa página recém-carregada**: às vezes NÃO avança
   (Vaadin precisa do evento nativo). → Para Login use `pg.click(xpath .v-button 'Login')`
   quando NÃO há overlay; JS-click só p/ Ok/Cancelar dentro do diálogo.
5. **Digitar user/senha SEM limpar o campo antes** (dois scripts em sequência): concatena
   (`1439883971214398839712`) → "Usuário e/ou senha incorretos". → SEMPRE `.fill("")` antes de `.type()`.
6. **Código expirado**: demorar entre disparar e digitar → "O código informado é inválido".
   → Pedir o código e digitar IMEDIATO; se demorar, disparar um novo (reset + login).
7. **Playwright em background (nohup/run_in_background)**: trava o chromium (contexto detached) —
   lição geral do SIAFE, vale aqui. Usar FOREGROUND + redirect p/ arquivo.

## 5.1 Correção definitiva do overlay/pile-up (2026-06-07)
Tentativas falhas EMPILHAM janelas Vaadin de erro ("Usuário e/ou senha incorretos") cujo
`div aria-live` intercepta TODOS os cliques (Login/Ok) → loop de retries. Pior: o
`querySelector('.v-window')` pegava a janela de ERRO (sem campo de código), não a do MFA.
**Solução adotada (fluxo remoto, igual SIAFE):**
- `cmd_login` agora **fecha as abas FV antigas e abre uma ABA NOVA limpa** (zero resíduo de
  janelas/overlay), loga limpando os campos, e ao chegar no MFA **marca o checkbox "30 dias"**
  e **avisa o Jorge no Telegram** (`siafe_coord.notificar`).
- `cmd_code` localiza a **janela do MFA pelo texto** (`/multifator|código|dispensar/`), fecha
  janelas de erro antes, digita no `input[type=password]` DELA, e clica "Ok" via **JS** dentro
  dela. Robusto a IDs `gwt-uid-N` dinâmicos.
Fluxo: `login` (abre+avisa) → Jorge manda o código → `code <COD>` (digita+Ok+salva sessão).

## 5.2 RUNBOOK MFA p/ IA FRACA / cron (auto-sinalizante) — 2026-06-07
**Como ler o código do Jorge:** NÃO usar `getUpdates` (conflita com o long-poll do Yoda). O
Hermes PERSISTE toda mensagem em `~/.hermes/logs/gateway.log` no formato:
`inbound message: ... chat=45338178 msg='<CÓDIGO>'`. Basta ler a última linha que casa.
(Eu já leio o que o Yoda recebe por aqui — é o canal certo.)

**Comando único (faz tudo sozinho):**
```
PYTHONPATH=. .venv/bin/python -m tools.flexvision_cdp auto
```
Ele: detecta se já está logado (idempotente) → senão loga em aba limpa → marca "30 dias" →
avisa o Jorge no Telegram → **lê o código no gateway.log** → digita → Ok → salva sessão.

**SINAIS** (impressos como `SINAL=...` E gravados em `data/sei_cache/flexvision_sinal.json`)
— uma IA fraca decide pelo sinal:
- `LOGADO` → ok, pode coletar.
- `MFA_PENDENTE` → pediu código ao Jorge; rodar `auto` de novo (ou esperar — `auto` já faz poll 240s).
- `PRECISA_LOGIN` → rodar `auto` (vai logar).
- `MFA_FALHOU` → nenhum código válido a tempo; pedir ao Jorge e rodar `auto` de novo.
- `ERRO` → ver detalhe.

Comandos manuais (se precisar): `status` (só sinaliza), `login` (abre+avisa), `code <COD>` (digita+Ok).
A sessão salva (`data/sei_cache/flexvision_state.json`, "30 dias" marcado) dispensa MFA por ~30 dias.

## 5.3 INVENTÁRIO DE CUBOS (logado 2026-06-07) — ACHADO CRÍTICO
A tela **Cubos** tem campo "Digite para filtrar". Filtrei por `folha / pessoal / remunera /
salar / vencimento / servidor` → **ZERO resultados**. `despesa` → só "Naturezas da Despesa".
**Listei os 68 cubos (todos orçamentário/contábil) — NÃO existe cubo de FOLHA por servidor.**
Cubos relevantes a despesa/pagamento: **Documento - OB** (Ordens Bancárias), Documento - NE
(empenho), NL (liquidação), NP (pagamento), **Naturezas da Despesa**, Lista de Favorecidos,
Credores, Saldos Contábeis. (Demais: Contratos, Convênios, Conciliação, Conformidade, Receitas,
Dívida, Security, Logs.)

**CONCLUSÃO (não repetir busca de cubo de folha aqui):** a folha NOMINAL por servidor
(CPF/nome/cargo/bruto/líquido) **NÃO está nesta FlexVision** — é domínio RH/SEPLAG, não SIAFE.
O que ESTA instância permite é **despesa de PESSOAL por órgão/UG/competência** (cubo Documento-OB
ou Naturezas da Despesa filtrando o grupo 1 — Pessoal e Encargos / naturezas 3.1.90.11 etc.) =
folha AGREGADA por órgão, sem nominal. Decisão de rumo levada ao Jorge.

## 5.4 SESSÃO ÚNICA (achado 2026-06-07) — coordenar c/ o Jorge
FlexVision/SIAFE = **1 sessão por usuário**. Ao recarregar, apareceu:
*"Sua sessão expirou. O usuário '14398839712' já está logado a partir do IP 179.82.47.3."*
→ Quando o Jorge loga (do IP dele), DERRUBA a sessão da VM, e vice-versa. Mesmo problema do
SIAFE (coordenação `siafe_coord` por Telegram). Detector trata como estado **`ocupada`** →
sinal `SESSAO_OCUPADA`. Re-login na VM ASSUME a sessão (derruba o Jorge). Com o "30 dias"
salvo, o re-login NÃO pede MFA. ⚠️ Combinar com o Jorge antes de assumir (ele pode estar usando).
Caveat: o timeout de sessão do FV é curto — coletar em bloco, não deixar ocioso.

## 5.5 EXPORT (Exportação/Importação) — RECEITA QUE FUNCIONA ✅ (2026-06-07)
Caminho do Jorge: **Exportação/Importação > filtro > tick no checkbox do item > Exportar > .xml**.
Passos validados (tudo via Chrome CDP 9222, logado):
1. **Abrir/fechar o drawer lateral:** clicar o hambúrguer "Menu" (~28,18). ⚠️ Com o drawer ABERTO
   ele COBRE a coluna de checkboxes da grade → FECHAR o drawer antes de marcar o checkbox.
2. **Navegar p/ Export:** abrir drawer → clicar o item "Exportação/Importação" (bbox x>0; o item fica
   em x negativo quando o drawer está recolhido). Hash vira `#!exportação/importação`. (JS `location.hash`
   NÃO funciona — Vaadin ignora; tem que clicar o item.)
3. **Filtrar:** campo `input.filter-textfield` ("Digite para filtrar") — só DIGITAR o termo (ex. "folha"),
   a lista atualiza sozinha, SEM Enter (confirmado pelo Jorge).
4. **Marcar o checkbox:** clicar com **mouse REAL** na 1ª célula da linha (`row.querySelectorAll('td,.v-grid-cell')[0]`,
   ~x=52). JS `.click()` no input NÃO marca. Marcar habilita o botão Exportar.
5. **Glyphs da barra (topo-dir):** `ee69a`=Limpar filtro · **`ee746`=EXPORTAR** · `ee703`=Importar.
   ⚠️ o glyph vem como 'e'+codePoint = **"ee746"** (não "e746"). O Exportar fica `v-disabled` até ter
   item marcado. Clicar `ee746` (~706,93) quando habilitado.
6. **Capturar o download:** `expect_download` do Playwright retorna 0 byte sobre CDP. O que FUNCIONA:
   `cdp.send("Browser.setDownloadBehavior",{behavior:"allow",downloadPath:"/tmp/fvdl",eventsEnabled:true})`
   e depois POLL a pasta (o arquivo real aparece, ex. 9856 bytes). Ferramenta: `/tmp/fv_go.py` (consolidar em tools).

**BATCH (todas de uma vez):** marcar o **checkbox do CABEÇALHO** (1ª célula do `.v-grid-header`,
~x=52,y=134) = "selecionar todos os filtrados" → Exportar gera UM .xml com TODAS (root `<queries>`).
Ex.: filtro "folha" → 16 selecionadas → 1 xml de ~1,9 MB. Salvo em `data/flexvision_export/`.

**APRENDIZADO CRÍTICO — o .xml é a DEFINIÇÃO da consulta, NÃO os dados.** Arquivo `query-export_*.xml`
contém: `cube-name`, eixos (x/y), formatos e o **filtro parametrizado**. Ex. da consulta 034411
("...FOLHA DE PAGAMENTO PROCESSO SEI"): cubo **"Saldos Contábeis (Histórico)"**, filtro
`[Exercício].[Ano]=?Ano? E [Mês].[Número]<=?Mês? E [Unidade Gestora].[Código] começa com ?UG? E
[Nota de Liquidação].[Código do documento] começa com ?NL?`. Parâmetros: **Ano, Mês, UG, NL**.
→ Pra DADOS: RODAR a consulta (área Consultas) preenchendo os parâmetros (Ano/Mês/UG) e exportar o
RESULTADO; OU replicar via HTTP (doc SCRAPING §4.5). O export aqui serve p/ MAPEAR a estrutura
(cubo+dimensões+filtro) de cada consulta de folha já pronta pelos técnicos da SEFAZ.

## 5.6 NAVEGAÇÃO entre telas — o que funciona (2026-06-07)
- ⚠️ Clicar item do menu lateral (Valo `.valo-menu-item`) **NÃO navega de forma confiável** (testado:
  mouse-click no bbox, locator.click, dispatch de mouse events — nada muda o hash). "Consultas"/"Cubos"
  da sidebar são em parte `.valo-menu-subtitle` (cabeçalho, não clicável).
- ✅ **O QUE FUNCIONA: `pg.goto("…/Flexvision/#!consultas")`** (ou `#!exportação/importação`, `#!cubos`).
  goto pro hash roteia dentro da sessão SEM deslogar (≠ goto pra raiz `/Flexvision/` que dá "sessão expirou").
- Menu responsivo Valo COLAPSA em hambúrguer com viewport estreita → `pg.set_viewport_size({width:1920,height:1080})`
  deixa o menu expandido (itens em x≈144). Mesmo expandido, navegar é por goto.
- Hashes conhecidos: `#!paineis #!cubos #!dimensões #!parâmetros #!agregações #!exportação/importação
  #!monitoramento #!consultas #!visibilidades`.

## 5.7 RODAR consulta p/ DADOS — em mapeamento (PENDENTE recipe do Jorge)
Área `#!consultas`: grid Código/Título/Categoria/Cubo/Estado/Proprietário + árvore
(Consultas > [meu usuário] > "Consultas de outros usuários"). As consultas de folha são de OUTROS
usuários (Alessandro/Ana Paula/etc.) — não aparecem no filtro do meu nó direto; provável precisar
expandir o nó "outros usuários". Abrir/rodar (duplo-clique?) → prompt de parâmetros (Ano/Mês/UG/NL) →
executar → exportar RESULTADO. Recipe exata a confirmar com o Jorge (alt.: importar a def. .xml p/ meu
nó via Importar e rodar dali).

## 6. PENDENTE (após logar)
- Salvar `data/sei_cache/flexvision_state.json` (com "30 dias" marcado).
- **Mapear o DOM logado COM CALMA antes de coletar** (pedido do Jorge): sidebar (Paineis, Cubos,
  Dimensões, Consultas, Parâmetros, Agregações, Exportação/Importação, Monitoramento, Segurança).
- Achar a folha: provável **Cubo** ("Folha"/"Pessoal"/"Despesa de Pessoal") ou **Consulta** salva.
- Descobrir o **export** (menu Exportação/Importação) → baixar por UG/competência 2023→2026 →
  ingerir em `registros_folha` (idempotente por fonte+competencia+cpf+nome).
