# CLAUDE.md — Navegação de Sites Difíceis (WAF · JS/SPA · Oracle ADF · WebRTC)
> Regras operacionais para scraping/sweep (avaliado/adotado 2026-06-07; origem: outra IA).
> Princípio-mestre: **não simule o navegador quando puder falar HTTP direto.**
> Hierarquia de esforço: **HTTP replay > DOM-driven (Playwright) > vision (Computer Use)**.

## 0. Decisão inicial (SEMPRE antes de codar)
- Dado em dados abertos/API/CSV? → use isso, não scrapeie.
- Dá pra capturar o request e replicar em HTTP puro? → caminho 1 (HTTP replay).
- SPA/ADF que exige render/PPR? → caminho 2 (Playwright CLI).
- DOM inacessível (canvas/anti-bot)? → caminho 3 (Computer Use, último recurso ~78%).

## 1. Ferramentas (ordem): har2requests/mitmproxy/httpx (replay) > Playwright CLI (sweep, YAML em disco, ~4x menos token) > Playwright MCP (debug) > Stagehand > Computer Use.

## 2. WAF: validar IP por alvo (SEI-RJ prefere IP residencial BR, não Actions); logar 1x no browser e REAPROVEITAR cookies no replay; replicar UA/Accept/Accept-Language/Referer/Origin EXATOS; jitter 1–4s; se bloquear httpx mas browser passa = TLS/JA3 → curl_cffi (impersonate chrome) ou ficar no Playwright. Nunca versionar cookies/credenciais.

## 3. SPA/JS: HTML inicial é casca vazia (curl sem dados = esperado). Esperar ESTADO real (wait_for_selector/networkidle/condição JS), nunca sleep fixo. Capturar o XHR/fetch JSON por trás e replicar. Infinite scroll → replicar request paginado.

## 4. Oracle ADF Faces (SIAFE-Rio 2)
### 4.1 Sincronização (regra mais importante): trocar todo sleep por
`AdfPage.PAGE.isSynchronizedWithServer()===true` após cada interação. `setAnimationEnabled(false)` 1x/página. Helper: adf_sync.py / compliance_agent/siafe_adf.py.
### 4.2 Filtros (PPR só com evento REAL): fill()/dispatchEvent NÃO disparam PPR. Campo Valor: keyboard.type(delay=80)+Enter. Propriedade/Operador = <select> nativos → select_option(). Disclosure do filtro: clique de MOUSE REAL (locator.click()), nunca el.click() JS (label "Filtro" tem onclick=return false).
### 4.3 Login (ordem importa): exercício PRIMEIRO → networkidle → SÓ ENTÃO credenciais.
### 4.4 Paginação: ADF PPR HTTP via oracle.adf.view.rich.DELTAS, avançar scrollTopRowKey/clientKey em fetchSize=50, contentDelivery=immediate. Teto ~1000/consulta → FURAR POR FILTRO (faixa de Data Emissão por quinzena, OU número OB começa-com prefixo, OU operador "pertence (;)" p/ agrupar UGs).
### 4.5 HTTP replay ADF: POST precisa de javax.faces.partial.ajax=true E header Faces-Request: partial/ajax (ambos). javax.faces.ViewState ROTACIONA a cada resposta → extrair do <![CDATA[...]]> e reenviar. Gerar esqueleto com har2requests a partir de HAR de ação manual.

## 5. WebRTC: negocia via signaling (WS/HTTP) + P2P (SRTP/DataChannel); requests não vê. Inspecionar via chrome://webrtc-internals; capturar WS de signaling (page.on("websocket")); hook em RTCPeerConnection.prototype.createDataChannel via evaluate p/ logar mensagens.

## 6. Anti-padrões: sleep fixo em SPA/ADF; fill() em filtro ADF; despejar snapshot a11y inteiro no contexto; puxar grade ignorando teto; Computer Use como 1ª opção; reraspar o que já existe; commitar cookies/.env.

## 7. Checklist: dado já existe? capturei HAR antes de codar? dá replay HTTP? se browser, CLI não MCP? toda espera por condição? cookies/headers reais reaproveitados? jitter + filtro por faixa? ViewState re-extraído a cada POST?
