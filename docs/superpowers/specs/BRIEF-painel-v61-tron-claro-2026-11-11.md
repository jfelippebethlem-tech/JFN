# BRIEF — Painel JFN v61 «TRON CLARO» · 2026-11-11

> Executor: VM1 (jfn-core), sessão headless. Planejado pelo Claude (sessão do Jorge). **Você só executa.**
> Base: branch `ui/painel-v60-clareza` (v60 já ativa). Crie `ui/painel-v61-tron-claro` a partir dela.
> Leia antes: `HANDOFF-painel-v60-2026-11-10.md`, `HANDOFF-painel-v27-2026-07-26.md` (armadilhas reais), `_SANDBOX/v60_RELATORIO.md`.

## 0. O que o Jorge pediu (palavras dele, resumidas)

- "Tá muito dark esse site." → **tema CLARO**, todo em **azul / azul-claro**, "ultratech, nível Tron".
- "Um site todo animado, todo contínuo, com as coisas se animando em tempo real, ao vivo" → **movimento contínuo + feed ao vivo**.
- "Tudo que está funcionando, tudo que está pesquisando, todos os motores, cada agente que está por trás" → **painel AO VIVO de motores e agentes**.
- "Melhorar muito o vídeo de início, que está muito feio" e "o Arc Reactor" → **nova abertura + novo reator** (vídeos Higgsfield já entregues em `static/assets/v61/`).
- "Melhorar o cockpit e a cena do mapa do estado do RJ" → **mapa interativo, município a município, clicável**.
- "Município a município eu NÃO quero os contratos de cada prefeitura. Quero os **contratos do ESTADO por município, executados ou em execução**. E os da **Prefeitura do Rio por região / AP (área de planejamento)**. A VM1 tem que saber fazer isso também" → **motor novo `territorio`** + API + UI.
- Fontes "mais modernas", mas "a anterior [v60] estava melhor: ficou tudo mais legível, botões funcionais" → **manter TODA a legibilidade e a estrutura da v60**; trocar só a família e elevar o acabamento.

**Princípio herdado (v27): a arte dá o CORPO, o código dá a VIDA.** Vídeo é cenário; tudo o que é dado (mapa, números, status, pulsos) é código e reflete o estado real.

## Regras duras (iguais às de sempre)

- Não abrir/imprimir `.env`, `CREDENCIAIS*`, chaves, tokens. Não `git add` em `data/*`, `AGENTS.md`, `CLAUDE.md`.
- **Não reiniciar `jfn`** (static é servido do disco; mudanças em `server.py` → avisar no relatório, o Jorge/Claude reinicia). Exceção: se precisar de rota nova, crie router em arquivo novo e deixe pronto + teste com `TestClient`; o restart fica pendente no relatório.
- Um processo pesado por vez; nada de `pkill -f`; sem force-push; **sem merge na main**.
- Scripts clássicos; **INDISPONÍVEL ≠ 0**; **nenhum número inventado** (nem em arte, nem em placeholder).
- Escrever em `compliance.db` está PROIBIDO (histórico de corrupção WAL). Dados novos vão em `data/territorio.db`.
- Tudo gratuito (sem API paga).
- Patch via ssh: heredoc com aspas simples (armadilha `content:""` do v27).
- **Screenshot a cada fase** (`_SANDBOX/shot_painel.py`, mobile+desktop). Teste passando ≠ visual certo.
- Um commit por fase: `feat(painel-v61): fase N — <nome>`. Push do branch ao fim de cada fase.

## Flag

`html.v61` (classe no `<html>`), `localStorage.jfn_v61`, `?v61=0|1`. Começa **desligada**; liga por padrão só na Fase 11 se tudo passar. v60 continua sendo o fallback (`?v61=0`). Estratos CSS novos em `static/css/src/99z2-v61-*.css`, só valendo sob `html.v61`.

---

## Fase 1 — Tema «GELO» (claro, azul, Tron)

Tokens (sob `html.v61`):

```
--bg:#F3F8FE; --bg-2:#E8F1FC; --bg-3:#DCEAFB;
--surface:rgba(255,255,255,.74); --surface-solid:#FFFFFF; --surface-2:rgba(240,247,255,.82);
--line:rgba(30,110,220,.16); --line-strong:rgba(30,110,220,.32);
--ink:#0B1B33; --ink-2:#34496A; --ink-3:#6A7E9B;
--ion:#1E7BF0; --ion-text:#0A63D1; --cyan:#22B5F5; --glow:rgba(34,181,245,.42);
--ok:#0E9E74; --warn:#C98400; --crit:#D93A40; --money:#0B7A64;
--radius:14px; --blur:saturate(150%) blur(18px);
```

- Texto de acento usa `--ion-text` (contraste AA sobre branco). Verificar AA de **todos** os pares ink/bg com script (salvar resultado no relatório).
- Fundo da página (camada fixa única, `z-index:-1`):
  1. vídeo/pôster da esfera ativa (Fase 2) a ~0.55 de opacidade,
  2. véu `linear-gradient(180deg, rgba(243,248,254,.55), rgba(243,248,254,.92) 60%)`,
  3. **grade Tron em perspectiva** só no terço inferior: `repeating-linear-gradient` de linhas `--line` com `transform: perspective(600px) rotateX(62deg)`, deslizando (`background-position`) em 40s linear infinito,
  4. **3 rastros de luz** (`--cyan`, 1px, gradiente com cauda) correndo pela grade em 7s/11s/17s com atrasos diferentes. Só CSS, `will-change: transform`.
- Cartões = vidro branco: `background:var(--surface); backdrop-filter:var(--blur); border:1px solid var(--line); box-shadow:0 1px 0 #fff inset, 0 8px 24px rgba(20,70,140,.08)`. Mantém colchetes de canto (técnica v15) em `--ion` a 50%.
- Cabeçalho, chips, nav inferior, folha "⋯": mesmos componentes da v60, recoloridos. Chip ativo = fundo `--ion`, texto branco, brilho `0 0 0 3px var(--glow)`.
- Cores de risco continuam semânticas (só onde há risco/dinheiro, regra v60).
- Opção **"Tema escuro"** dentro da folha "⋯" (liga a v60 escura via `localStorage.jfn_tema=escuro`). Padrão: claro.

## Fase 2 — Fontes modernas (legibilidade v60 intacta)

- **Geist** (texto/UI, 400/500/600) + **Geist Mono** (todos os números, `font-variant-numeric: tabular-nums`) + **Oxanium 600/700** só para display.
- Origem gratuita e offline: `npm i geist @fontsource/oxanium` → copiar woff2 (latin + latin-ext; pt-BR precisa `ãõçáéíóúâêô`) para `static/assets/fonts/v61/`. Máx. 6 arquivos, `font-display:swap`, `preload` só de Geist 400 e 600.
- **Oxanium só em classe folha** (lição v22): título da aba (capa), nome das esferas, rótulos do HUD da abertura, título do mapa. Nunca em container, corpo, tabela ou botão.
- Escala igual à v60 (não aumentar densidade). Remover referências a IBM Plex sob `html.v61`.

## Fase 3 — Assets Higgsfield (já entregues pelo Claude)

**JÁ PRONTOS** em `static/assets/v61/` (o Claude gerou no Higgsfield, emendou os loops com crossfade de 0,8 s e comprimiu). Para cada nome: `<n>.webm` + `<n>.mp4` (1280×720), `<n>-m.webm` + `<n>-m.mp4` (854×480, celular), e, exceto abertura, pôster `<n>.webp` (1600w) + `<n>-sm.webp` (800w). Total ≈ 17 MB; maior loop 1,4 MB. Sem áudio. **Não recodificar**; só conferir (`ffprobe`) e versionar. Ignore abaixo o passo de ffmpeg, já foi feito.

| arquivo | uso |
|---|---|
| `abertura.mp4` | filme de abertura: reator acende → câmera recua → sala de comando clara com a mesa holográfica |
| `reator.mp4` + `reator.png` | loop do arc reactor (frontal, centrado) |
| `sala.mp4` + `sala.png` | loop da sala/mesa holográfica (fundo do cockpit e do Início) |
| `fluxo.mp4` + `fluxo.png` | loop de rio de luz (login e Transversal secundário) |
| `estado.mp4` + `estado.png` | loop da esfera Estado (treliça de vidro hexagonal) |
| `prefeitura.mp4` + `prefeitura.png` | loop da esfera Prefeitura (cidade de vidro) |
| `transversal.mp4` + `transversal.png` | loop da esfera Transversal (esfera de fios / grafo) |

Tarefa: `tools/v61_midia.sh` (ffmpeg, `nice -n 10`):
- Para cada vídeo: `webm` VP9 (`-crf 36 -b:v 0 -row-mt 1 -deadline good -cpu-used 4`) e `mp4` H.264 (`-crf 26 -preset veryfast -movflags +faststart -pix_fmt yuv420p`), 1280×720, sem áudio. E versão **mobile** 854×480 (`-m.webm`/`-m.mp4`). Alvos: loops ≤ 1,8 MB (720p) / ≤ 0,9 MB (480p); abertura ≤ 3,5 MB.
- Loops: os vídeos foram gerados com quadro inicial = final. Conferir a emenda (extrair último e primeiro quadro, diferença média). Se houver salto visível, aplicar crossfade de 0,6 s do fim sobre o início (`xfade`) e cortar para emendar.
- Pôsteres: do PNG, gerar `webp` 1600w (q 80) e 800w (q 78).
- Saída final em `static/assets/v61/` (os brutos em `src/` ficam fora do git: adicionar a `.gitignore`).

## Fase 4 — Abertura nova (substitui a atual: portal/kyber)

- Tela cheia: `<video muted playsinline autoplay>` com `abertura` (mobile → `-m`). Pôster = `reator` webp.
- **HUD por cima, em código**, sincronizado ao tempo do vídeo:
  - 0,0–2,5s: centro, Oxanium, letra a letra: `JFN` e abaixo `INTELIGÊNCIA FISCAL · RJ`.
  - 1,0–7,0s: canto inferior esquerdo, **checklist de boot REAL** vindo de `/api/ao-vivo/estado` (Fase 7): uma linha por motor, `● SEI noturno — rodando`, `● TFE/OBs — falhou há 2h` (vermelho, honesto). Se a API falhar: `motores: INDISPONÍVEL`. Nunca linhas fixas fingindo status.
  - 7,5–10s: HUD some, o vídeo termina na sala, e **crossfade de 600 ms para o cockpit** (o loop `sala` está no fundo do cockpit, então a passagem fica contínua).
- Botão **Pular** (canto superior direito, 44px de alvo).
- Frequência: completa só na **primeira abertura do dia** (`localStorage.jfn_abertura_dia`). Nas demais, versão de 1,2 s (pôster do reator + flash + fade).
- `prefers-reduced-motion` ou `Save-Data`: só pôster + fade de 300 ms.
- Login: fundo com loop `fluxo` + véu claro; cartão de login em vidro branco.

## Fase 5 — Cockpit: reator vivo + mesa holográfica + mapa interativo

Layout desktop: fundo = loop `sala` (véu claro). Centro-esquerda = **mapa** (Fase 6). Direita = coluna com reator (topo) e cartões de status. Mobile: reator compacto (120px) no topo, mapa a largura toda, cartões abaixo.

**Reator**: o vídeo `reator` recortado em círculo (`mask-image: radial-gradient(circle, #000 62%, transparent 70%)`) + **canvas por cima** com 3 anéis procedurais que respondem ao estado REAL:
- velocidade de rotação ∝ nº de motores rodando agora,
- brilho do núcleo ∝ eventos/min do feed (Fase 7, média móvel 5 min),
- **flash + onda** quando chega um evento de tipo `achado`,
- **agentes em órbita**: um nó por motor ativo, nome em Geist 11px, órbita mais rápida quanto mais eventos. Toque no nó → cartão do motor.
- Um único `requestAnimationFrame` compartilhado (reaproveitar `ritmo.js`); pausar com `visibilitychange`; ≤ 30 fps no mobile.

## Fase 6 — Mapa interativo do RJ (o coração do pedido)

**Geometria**:
- Municípios RJ (UF 33, 92 municípios): malha do IBGE (API de malhas `servicodados.ibge.gov.br/api/v3/malhas/estados/33?intrarregiao=municipio&formato=application/vnd.geo+json&qualidade=intermediaria`), simplificar com `mapshaper` (npx, keep-shapes, alvo ≤ 150 KB TopoJSON) → `static/assets/geo/rj-municipios.topo.json` com `cod_ibge` e `nome`.
- Cidade do Rio: **Áreas de Planejamento (AP1…AP5)** e **Regiões Administrativas** do Data.Rio/IPP (camadas "Limite Áreas de Planejamento", "Limite Regiões Administrativas" e "Limite de Bairros", GeoJSON via ArcGIS Hub/`pgeo3.rio.rj.gov.br`). Reprojetar para WGS84 se preciso, simplificar → `rio-aps.topo.json` (AP + RA + bairro com `ap`, `ra`, `bairro`).
- Se algum download falhar (rede da VM), registrar no relatório e seguir com o que houver. **Não desenhar mapa à mão.**

**Render**: SVG com `d3-geo` + `topojson-client` (npm, empacotados pelo esbuild existente). `geoMercator().fitSize`. Visual de mesa holográfica clara:
- Placa base: sombra suave azul + borda `--line-strong`; leve inclinação 3D no desktop (`transform: perspective(1200px) rotateX(18deg)`, alinhar ao hover).
- Preenchimento coroplético da métrica escolhida em escala sequencial azul (`#EAF4FF` → `#1E7BF0` → `#0A3E8C`, quantis), divisas brancas 0,8px; municípios **sem dado = hachura clara + legenda "sem dado"** (não pintar como zero).
- Hover/toque: o município "sobe" (translate −3px + glow `--glow`) e abre tooltip de vidro: nome, valor, nº contratos, % executado.
- Clique: **Ficha do município** (painel lateral no desktop; bottom sheet no mobile, arrastável).
- **Pulsos ao vivo**: quando o feed (Fase 7) traz evento ligado a um município/AP, onda circular sai do centróide (1,2 s).
- Varredura de radar suave girando sobre o mapa (30s/volta, 6% de opacidade).

**Controles no topo do mapa** (chips v60):
- Escopo: `Estado · por município` | `Prefeitura do Rio · por AP`. Trocar faz zoom animado (900 ms) para a cidade do Rio e mostra as 5 APs (RAs em linha fina). Clique na AP → **Ficha da AP** (e lista de RAs da AP).
- Métrica: `Valor contratado` · `Em execução` · `Pago` · `Nº de contratos` · `Alertas`.
- Período: `Vigentes hoje` · `2023–hoje` · `Tudo`.
- Rodapé do mapa: `Fonte: … · atualizado em dd/mm hh:mm · N contratos sem município identificado (R$ X)`. Esse balde fica sempre visível (transparência).

**Ficha do município / AP** (mobile-first):
- KPIs: contratos estaduais **em execução**, **executados**, valor contratado, **pago** (de OB; sem vínculo → INDISPONÍVEL), % executado.
- Top órgãos estaduais (SEEDUC, SES, SEOP, DER, CEDAE, PMERJ…) com barra.
- Top fornecedores (link para a ficha do fornecedor que já existe).
- Lista de contratos: objeto (2 linhas), órgão, fornecedor, valor, vigência, status `Em execução`/`Executado`/`Rescindido`, % pago, **selo do método de atribuição** (`campo`, `orçamento`, `unidade`, `endereço`, `texto`) e confiança (alta/média/baixa). Toque → dossiê do contrato existente.
- Alertas/achados ligados àquele território.

## Fase 7 — Motor `territorio` (dados) — a VM1 tem que saber fazer

### A. Contratos do ESTADO por município de execução
Escopo: Poder Executivo estadual (adm. direta e indireta). **Fora: contratos das prefeituras.**
Primeiro faça o inventário do que JÁ existe na VM (registrar no relatório): backfill `contratos_estado` (17.467 contratos, 10 entes), OBs SIAFE/TFE, `pncp_resultado` filtrado por esfera estadual (`pcrj_orgao_esfera`/`pncp_ente`), `contratos_tcerj` só jurisdicionados estaduais, extratos do DOERJ.

Atribuição de município, por ordem de força (guardar **todos** os métodos que acertarem, decidir pelo mais forte):
1. **campo** — local de execução explícito na fonte. ATENÇÃO: município do órgão/UG **não** é local de execução (a sede de quase todo órgão é a capital). Só vale se a UG for regional (ex.: "Hospital Estadual X – Campos").
2. **orçamento** — regionalização SIAFE do empenho ligado ao contrato (localizador/subtítulo com município ou região).
3. **unidade** — objeto cita unidade estadual com endereço conhecido: escolas estaduais (Censo Escolar/INEP), hospitais/UPAs estaduais (CNES), batalhões PMERJ, delegacias PCERJ, unidades DEGASE/SEAP, estações CEDAE. Montar `data/territorio_unidades.csv` com nome normalizado → `cod_ibge`, fonte.
4. **endereço** — CEP/endereço no objeto ou extrato → município (base CEP: `receita_estab.db` já tem CEP→município).
5. **texto** — dicionário dos 92 municípios no objeto/extrato (normalizado, sem acento) com variantes e armadilhas:
   - "Rio" sozinho é ambíguo: só conta "Município do Rio de Janeiro", "Capital", ou bairro carioca reconhecido.
   - "Caxias" → Duque de Caxias (mas não "Duque" sozinho); "Campos" → Campos dos Goytacazes; "Búzios" → Armação dos Búzios; "Parati" → Paraty; "Trajano de Morais/Moraes"; "Varre-Sai"; "São João de Meriti" vs "São João da Barra"; "Rio das Ostras", "Rio Bonito", "Rio Claro" ≠ Rio de Janeiro.
   - Região ("Região Serrana", "Baixada", "Norte Fluminense") → **não** espalhar valor; marcar `regiao` e listar.
- Contrato com **vários municípios**: guardar a lista, `multi=1`. **Não dividir valor** (seria número inventado). No mapa: valor vai para o balde "Vários municípios" e cada município mostra "participa de N contratos multimunicipais".
- Sem município → balde "Sem município identificado" (aparece no rodapé do mapa).
- **Status**: `em_execucao` = vigência final ≥ hoje (considerando aditivos de prazo) e não rescindido; `executado` = encerrado; `rescindido`. **Pago** = soma de OBs ligadas (contrato/processo/empenho); sem vínculo → NULL (UI: INDISPONÍVEL).

Tabelas em `data/territorio.db`:
```
territorio_contrato_estado(contrato_id PK, fonte, orgao, fornecedor_cnpj, objeto, valor, vig_ini, vig_fim, status, pago NULL, cod_ibge NULL, multi, municipios_json, regiao, metodo, confianca, evidencia, atualizado_em)
territorio_mun_agg(cod_ibge PK, nome, n_em_execucao, n_executados, valor_contratado, valor_em_execucao, pago NULL, n_alertas, atualizado_em)
territorio_baldes(balde PK, n, valor, atualizado_em)  -- 'sem_municipio', 'multimunicipio', 'regiao'
```

### B. Prefeitura do Rio por AP (e RA)
Fontes PCRJ já na VM (`pcrj_contratos`, `contasrio_contrato`, `contrato_integra`, DOE-Rio). Atribuição:
1. **órgão regional**: CRE (1ª–11ª Coordenadoria Regional de Educação) → AP; CAP x.y (Saúde) → AP x.y; Subprefeituras → AP; gerências regionais (Conservação, RioÁguas, Comlurb) → AP. Montar `data/territorio_pcrj_orgao_ap.csv` com fonte oficial de cada linha (decreto/página).
2. **unidade**: escolas municipais (INEP), clínicas da família/CMS (CNES) → bairro → RA → AP.
3. **endereço/CEP** → bairro → RA → AP.
4. **texto**: bairros cariocas (lista oficial de 160+ bairros) no objeto → RA → AP. Cuidado com nomes iguais a municípios ("Paciência" ok; "Santa Cruz"… mas há "Santa Cruz" em outros contextos; "Penha" etc.).
- Sem AP → balde "Cidade inteira / sem AP". Mesmos campos `metodo/confianca/evidencia`.
Tabelas: `territorio_contrato_pcrj(...)`, `territorio_ap_agg(ap PK, ra_json, ...)`.

### Execução, API e testes
- `compliance_agent/territorio/` (pacote): `geo.py`, `dicionario.py`, `atribui_estado.py`, `atribui_pcrj.py`, `agrega.py`, `cli.py` (`python -m compliance_agent.territorio.cli --full|--incremental`).
- `systemd --user`: `jfn-territorio.service` + `.timer` (a cada 6h, `Nice=10`, `IOSchedulingClass=idle`, `flock data/territorio.lock`). Rodar o `--full` UMA vez nesta sessão, quando nenhum outro pesado estiver rodando.
- API (router novo `compliance_agent/territorio/api.py`, incluir no app; restart pendente): `GET /api/territorio/estado?metrica=&periodo=`, `GET /api/territorio/estado/{cod_ibge}`, `GET /api/territorio/pcrj`, `GET /api/territorio/pcrj/{ap}`, `GET /api/territorio/baldes`. JSON com `fonte` e `atualizado_em`. `ETag` + `Cache-Control: max-age=600`. Mesma autenticação do painel.
- `pytest tests/test_territorio.py`: ≥ 25 casos reais de objeto → município/AP esperado, incluindo todas as armadilhas acima.
- **Auditoria de precisão**: amostra aleatória de 60 atribuições (40 Estado, 20 PCRJ), revisar uma a uma e registrar no relatório: acertos, erros, % por método. Se a precisão do método `texto` ficar < 85%, rebaixar a confiança dele para `baixa` e mostrar isso na UI.

## Fase 8 — AO VIVO: motores e agentes

**Backend** (router `compliance_agent/aovivo/api.py`, só leitura, sem botão de ligar/desligar):
- `GET /api/ao-vivo/estado` → snapshot; `GET /api/ao-vivo/stream` → SSE (`text/event-stream`, heartbeat 15s, reconexão com `Last-Event-ID`).
- Fontes: `systemctl --user show` das unidades `jfn-*`, `chrome-jfn`, `painel-tunnel`, `hermes-gateway` (ActiveState, SubState, desde quando, último código de saída) e seus `.timer` (próxima execução); locks em uso (`/tmp/*.lock`, `data/*.lock`) = o que está rodando agora; últimas linhas dos logs conhecidos convertidas em evento humano por **regex de lista branca por motor** (ex.: `[contratos-estado] aditivos 4200/4233` → progresso 99%); delta de linhas nas tabelas-chave por minuto; status do Massare/VM2 se o endpoint de túnel responder.
- **Saneamento obrigatório** antes de enviar qualquer texto: remover tokens, e-mails, CPFs, URLs com query; limitar a 140 caracteres. Nunca transmitir linha bruta de log.
- Catálogo `compliance_agent/aovivo/motores.yaml`: id, nome humano ("SEI noturno", "TFE · OBs", "Bombeiros · perícia", "Inteligência · cache", "Território", "DOERJ", "PNCP", "Massare (VM2)", …), unidade systemd, log, regex de eventos, tabela-contador.
- Estados: `rodando` / `ocioso` / `agendado (próx. 03:00)` / `falhou (desde …)`. Hoje `jfn-intel-cache` e `jfn-tfe-ob` estão **failed** e têm que aparecer assim, em vermelho.

**UI**:
1. **Ticker ao vivo** (faixa de 28px sob o cabeçalho, todas as abas): eventos entrando pela direita, ponto pulsante "AO VIVO"; toque pausa e abre o histórico.
2. **"Motores"** no Início (seção nova, chip próprio): grade de cartões, um por motor, com ponto de status pulsando quando `rodando`, barra de progresso quando houver, sparkline de atividade dos últimos 60 min (canvas pequeno), último evento, próxima execução.
3. **Agentes em órbita** no reator (Fase 5) e **pulsos no mapa** (Fase 6).
4. Sem conexão: badge cinza "ao vivo pausado · reconectando" (não esconder).

## Fase 9 — Movimento contínuo (sistema)

- Tokens: `--dur-1:120ms; --dur-2:240ms; --dur-3:480ms; --ease:cubic-bezier(.2,.8,.2,1)`.
- Troca de aba: View Transitions API (`document.startViewTransition`, fade + 12px), fallback CSS. **Resolver o engasgo da v60**: renderização preguiçosa das abas pesadas, `content-visibility:auto` em seções fora da tela, medir antes/depois (salvar no relatório).
- Números contam de 0 ao valor na 1ª aparição (só valores reais; INDISPONÍVEL fica texto). Atualização ao vivo de um número = flip curto + lâmina de luz na borda superior do cartão.
- Entrada das listas em cascata (teto 480 ms, regra v16).
- Vídeos de fundo: só na aba visível; `pause()` em `visibilitychange`; mobile usa `-m`; `Save-Data`/reduced-motion → pôster.
- Orçamento: LCP < 2,5 s em 4G (celular médio), nada de long task > 200 ms ao trocar de aba, um único loop rAF.

## Fase 10 — Capas das abas

- Capa de cada aba (estrutura v60) ganha como fundo o **pôster/loop da sua esfera** (Estado/Prefeitura/Transversal; Início = `sala`), com recorte e véu claro para o título ficar em `--ink`. Selo da aba = ícone vetorial (glifos de linha; raster em ícone foi REPROVADO no v27).
- Ícones emprestados (5 abas + 3 botões do cabeçalho, pendência v60): desenhar glifos de linha próprios no mesmo traço.
- O pacote de artes antigo (prompts escuros, fase 10 da v60) fica **suspenso**: o estilo mudou para claro.

## Fase 11 — Verificação, liga por padrão, entrega

- Screenshots finais mobile+desktop: login, abertura (t=1s, 5s, 9s), cockpit, mapa estado, ficha de 3 municípios (Rio, Campos dos Goytacazes, Paraty), mapa PCRJ por AP, ficha AP3, Motores, 4 abas quaisquer. → `screenshots/holo/v61_final_*`.
- Suíte guardiã + `test_territorio.py` + contraste AA + Lighthouse mobile (perf ≥ 70, a11y ≥ 90) + tamanhos dos vídeos.
- Se tudo passar: ligar `html.v61` por padrão (`?v61=0` volta para v60).
- `_SANDBOX/v61_RELATORIO.md`: o que foi feito por fase, inventário de fontes de dados, precisão da atribuição (amostra de 60), baldes (sem município / multi / região) com números reais, o que ficou INDISPONÍVEL e por quê, rotas que precisam do restart do `jfn`, pendências.
- `docs/superpowers/specs/HANDOFF-painel-v61-2026-11-11.md` + atualizar `DESIGN.md` (tema Gelo, fontes, motion, mapa).
- Push do branch. **Não** fazer merge.
