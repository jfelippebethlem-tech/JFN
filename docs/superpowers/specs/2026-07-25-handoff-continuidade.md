# Handoff — continuidade da sessão de 24/07 → 25/07/2026

**Para retomar:** *"continue pelo docs/superpowers/specs/2026-07-25-handoff-continuidade.md"*.
Branch: `feat/painel-v8-melhorias` (tudo commitado e no remoto).

---

## 1. O QUE FICOU PARA A PRÓXIMA SESSÃO (prioridade do dono)

### 1.1 PAINEL — refazer o visual (o dono não gostou do que foi entregue)

**Briefing literal (25/07):** *"queremos o painel nas cores **azul e laranja**, **ultrafuturista**,
**Jarvis**, **sci-fi**, **cyber**, **holográfico**, **3D super foda** e **Star Wars**."*

**Referência visual:** o dono enviou uma foto ao **Yoda (Telegram)**. Ela **não chegou ao disco da VM**
— o cache de imagens do Hermes (`~/.hermes/cache/images/`) só tem `img_0d3122f04234.jpg`, de 09/07.
**Peça a foto de novo, anexada no chat da sessão** (aí é vista direto) ou salva em
`~/JFN/docs/referencias/`. Sem ela, qualquer tentativa é chute — foi o que aconteceu nesta sessão.

**O que já existe (não recomeçar do zero):**
- `static/jfn-painel.html` (~3.440 linhas, arquivo único). Paleta OKLCH com dois polos já definidos:
  `--ion` (azul) e `--flame` (laranja) — **as cores pedidas já são a base do tema**.
- Portal com **shader WebGL de passe único** (0 KB de dependência; escolha deliberada: a VM tem 2 vCPU).
- Núcleo orbital em canvas com a malha real do RJ (IBGE) ao fundo.
- Camada holográfica **v11 "PRISMA"** acrescentada nesta sessão (varredura, aresta cônica animada,
  franja cromática no hover, grade de perspectiva) — commit `7c563b4c`.
- Anti-colisão dos rótulos orbitais (o "NINHOS" sumia sob "COMUNIDADES").

**Veredito honesto do que foi feito:** a camada v11 é **sutil demais** para o que o dono pediu. Ele quer
uma mudança de *impressão*, não de detalhe. O caminho provável é reformular a **primeira dobra** (hero +
núcleo) com profundidade real, não decorar o que já existe.

**Como auditar sem chutar** (foi o que funcionou):
```bash
# screenshot + erros de console pelo Chrome que já roda na VM (CDP 9222)
.venv/bin/python /tmp/shot_painel.py      # recriar a partir deste doc se /tmp foi limpo
```
O script usa `websocket.create_connection(..., suppress_origin=True)` — sem isso o Chrome recusa com
403. Para página inteira: `Page.getLayoutMetrics` → `setDeviceMetricsOverride` → `captureScreenshot`
com `captureBeyondViewport: True`.

**Regras que não podem ser violadas na reforma:**
- `prefers-reduced-motion` desliga o movimento (a estética fica);
- nada de CDN (0 dependência externa) e nada que dispute CPU com o servidor do JFN;
- **quem já brilha (grave/ouro/alerta) não pode ser dessaturado**;
- é um painel de trabalho: número tem de ficar legível em repouso.

### 1.2 ADOBE EXPRESS — o que dá e o que não dá (o dono tem assinatura)

Apurado na documentação oficial (25/07/2026):

| Caminho | Serve para automação daqui? | Observação |
|---|---|---|
| **Adobe Express API (beta)** — REST | **Talvez** | Modifica elementos marcados de um documento e gera variações/exportações. Exige app registrado no Adobe Developer Console, `X-API-KEY` + token com escopos `openid`, `AdobeID`, **`ee.express_api`**. A doc **não diz** se assinatura individual habilita. |
| **Firefly Services** (Firefly/Photoshop/Lightroom APIs) | Sim, mas **é pago** | Plataforma empresarial. O dono já vetou qualquer coisa paga (24/07). |
| **Add-on SDK** | Não | O add-on roda **dentro** do Express (JS no navegador), não no servidor. |
| **Embed SDK** | Parcial | Embute o editor numa página; ainda exige API key do Developer Console. |

**Teste definitivo (5 min, faça primeiro):** entrar em `developer.adobe.com/console` com a conta da
assinatura → *Create new project* → *Add API* → procurar **Adobe Express API**. Se o escopo
`ee.express_api` aparecer para a conta, dá para automatizar daqui; se não aparecer, é plano empresarial.

**O caminho que funciona hoje, sem depender disso:** fluxo assistido — a sessão gera especificação de
design (tokens, paleta OKLCH, SVG, hero em HTML), o dono ajusta no Express e exporta **SVG/PNG** para
`~/JFN/docs/referencias/`, e a sessão integra o asset no painel. Nenhuma credencial, nenhum custo.

### 1.3 YODA — o 413 com foto (CORRIGIDO, mas verificar na prática)

**Sintoma relatado pelo dono (25/07):** ao enviar a foto de referência no Telegram, o Yoda respondeu
`Request payload too large (413). Cannot compress further.` — *"isso não pode acontecer nunca"*.

**Causa-raiz encontrada:** a imagem ia **inteira** ao provedor. Em
`~/hermes-agent/gateway/platforms/base.py` havia apenas um teto de 20 MB que **descartava** a imagem;
não havia redimensionamento. Uma foto de 12 MP vira 5-8 MB em base64 e estoura o limite de corpo de
vários provedores. O segundo efeito é pior que o primeiro: ao receber o 413, o compressor de contexto
(`agent/turn_context.py`) tenta encolher **texto** — a imagem continua igual, nada muda, ele conclui
"não houve progresso" e desiste. O usuário fica sem resposta.

**Correção aplicada** (commit `6f222a1a2` no repo `hermes-agent`): em `cache_image_from_bytes` — ponto
único por onde toda imagem recebida passa, em qualquer plataforma — a versão enviada cai para **1568 px**
no maior lado (JPEG 85), e o **original em tamanho pleno é preservado** como `img_<id>.orig.jpg`.
Medido: 4000×3000 de 956 KB → **96 KB** ao provedor. Degrada honesto (sem Pillow ou arquivo corrompido,
envia o original). Pillow 12.2.0 confirmado no venv do Hermes.

**Sobre qualidade:** para o modelo não há perda — Gemini, GPT e Claude reduzem internamente para
~1568 px de qualquer forma. Para detalhe fino (ler texto pequeno numa foto), o caminho é **recortar a
região do `.orig`** e mandar o recorte, não mandar a foto inteira maior.

**A verificar na próxima sessão:** o dono reenviar uma foto pesada ao Yoda e confirmar que responde.
Atenção ao **auto-update do Hermes (04:00)**: se o merge com o upstream reverter este patch, reaplicar
(ver [[hermes-update-git-merge-seguro]]).

---

## 2. O QUE FOI FEITO NESTA SESSÃO (para não refazer)

### 2.1 Motor de análise de processos (o grosso do trabalho)

| Módulo | O que responde |
|---|---|
| `execucao_sinais` | pagou e comprovou? (§2: só a **OB** é pagamento; empenho não) |
| `execucao_cerebro` | o **atesto faz sentido** com a medição e o objeto? (LLM injetado) |
| `nfe_verifica` | NF **cancelada / em contingência**? (contingência sai da própria chave, offline) |
| `parecer_cumprimento` | as **condicionantes da PGE** foram cumpridas, item a item? |
| `foto_medicao` | **foto reciclada** entre processos? (dHash, sem IA) |
| `execucao_fatos` | ponte texto → fatos que alimentam os detectores X1/X3 já existentes |
| `fracionamento_siafe` | fila de candidatos a fracionamento pela ótica do **pagamento** |
| `objeto_similaridade` | "mesmo objeto" por TF-IDF + **ramo de atividade** (art. 75, §1º, II) |
| `cadeia_processo` | os atos estão na **ORDEM** que a lei exige? (art. 53; Lei 4.320) |
| `coerencia_valores` | o pago cabe no **teto contratual**? o favorecido é a **contratada**? |

Todos ligados ao **dossiê completo** pelo capítulo *"Execução contratual e cumprimento do controle
prévio"* (`reporting/capitulos_dossie.secao_execucao_controle_previo`) — **nenhum ficou órfão**.

### 2.2 A lição que mais vale para as próximas sessões

**Todo achado bruto do motor era falso.** Auditando um a um:

- 30 processos "com OB paga e sem prova de entrega" (R$ 138,8 mi) → **0**. Eram transferências fundo a
  fundo (que não têm nota fiscal — a comprovação é prestação de contas: RDQA/RAG), documentos cujo
  **título** provava a peça ("Anexo NF 16787") sem texto extraído, e tributo a órgão público;
- 9 processos com "condicionante da PGE descumprida" → **0**. Era **transcrição de norma** repetida
  igual em vários pareceres, e aula de doutrina casando o gatilho "desde que";
- 107 inversões de cadeia → **30**. "Parecer Técnico de Medição" lido como parecer jurídico, e
  diferenças de ID que eram **minutos** (o ID do SEI anda ~113 mil/dia — medido no acervo);
- 5 divergências de valor → **0**. Teto zero por contrato sem valor legível, e multa diária virando
  teto contratual;
- 99 grupos de "foto reciclada" → **0**. Eram páginas em branco e **folhas de ponto** digitalizadas
  (29 de 40 arquivos do diretório `fotos/` são página de documento, não fotografia).

**Regra:** rodar no acervo real **antes** de considerar pronto, e transformar cada caso real em teste de
regressão. Sem isso, o sistema produziria um relatório de controle externo imputando R$ 138 milhões
inexistentes contra fundos municipais de saúde e fornecedores cujas notas estão nos autos.

### 2.3 Acervo e infraestrutura

- **Acervo SEI: 356 → 2.005 processos analisáveis** (`tools/sei_arquivar_do_cache.py`), arquivando o
  texto que o sweep já tinha lido. **Integridade conferida antes**: parte do cache guarda só ~400
  caracteres por documento (amostra) — a ferramenta **recusa** esses; 0 amostras entraram.
- `tools/sei_reparar_vazios.py` — recuperou 290.903 caracteres (3 pareceres, um de 101 mil chars) de
  documentos cujo PDF estava em disco e o texto, zerado.
- `tools/sei_fila_por_dinheiro.py` — dos 22.587 processos com OB, **18.843 nunca foram tocados**,
  somando **R$ 2,11 bilhões**. A captura noturna (03:30) agora regenera essa fila e drena o caso ativo
  (bombeiros) primeiro, depois o dinheiro.
- **Túnel vm1↔vm2**: Tailscale + **porta 2222** (a 22 é interceptada pelo Tailscale SSH na vm1), rotas
  `vm1-ts`/`vm2-ts`, auto-reparo a cada 30 min, apt blindado com `--force-confold`.
- **Alerta de crash/reboot** nas duas VMs (distingue reboot limpo de queda) + heartbeat mútuo.
- **VM-2**: `apt upgrade` órfãou 4 venvs (Python 3.10→3.12) — sweep SEI-PCRJ e Massare recriados.
- `tools/testar_na_vm2.sh` — suíte pesada roda na VM-2 (**3 min** contra 13 na VM-1).

**Suíte: 2.500 passando.** As 50 falhas da VM-2 são de ambiente (falta `data/` lá) — confirmado rodando
as mesmas na VM-1.

---

## 3. PENDÊNCIAS ABERTAS

1. **Painel** (item 1.1) — a foto de referência e a reforma da primeira dobra.
2. **Adobe Express** (item 1.2) — o teste do Developer Console decide o caminho.
3. **VLM local para as fotos de medição** — `foto_medicao.avaliar_fotos(descrever=...)` está pronto e
   injetável; falta subir **moondream2** ou **SmolVLM** em llama.cpp na VM-2 (ambos gratuitos, CPU/ARM).
4. **Consulta à SEFAZ por chave de NF-e** — `nfe_verifica.situacao(consultar=...)` está pronto; o
   caminho gratuito é o portal público com captcha resolvido pelo **ddddocr local** (já roda no
   sweep SEI-PCRJ da VM-2).
5. **I.D.E.A.S** — R$ 3,56 bilhões pelo Fundo Estadual de Saúde (UG 296100), 124 processos SEI, 743 OBs.
   Já é caso vermelho no vault. Com o motor calibrado, vale o dossiê completo dedicado.
6. **Fracionamento pelo SIAFE** — a fila de 2024 tem 4 casos com prioridade ≥ 0,7; o primeiro
   (4ID MÉDICOS, UG 294200) tem **12 pagamentos, 12 processos distintos, todos ≥ 80% do teto**.
7. **Confirmar o fix do 413** no Yoda com uma foto pesada (item 1.3) e vigiar o auto-update do Hermes.
8. **Varredura de formatação de moeda** — corrigido em `coerencia_valores` e `scheduler` (o alerta
   chegava como "R$ 57,208", que no Brasil se lê como cinquenta e sete reais). Vale varrer o resto:
   `grep -rn ':,\.2f' --include=*.py compliance_agent/ tools/` — cada `f"{v:,.2f}"` sem `_brl()` é um
   número em padrão americano num documento brasileiro.

---

## 4. COMANDOS ÚTEIS

```bash
# suíte completa (na VM-2, deixando a VM-1 livre)
./tools/testar_na_vm2.sh

# reavaliar o acervo com o motor (scripts em /tmp são descartáveis — refaça se sumirem)
.venv/bin/python -m tools.sei_fila_por_dinheiro            # gap de captura por dinheiro
.venv/bin/python -m tools.sei_arquivar_do_cache            # o que dá para arquivar sem browser
.venv/bin/python -m tools.sei_reparar_vazios               # documentos sem texto com PDF em disco

# painel
systemctl --user restart jfn && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/painel
```

**Regras da casa que valeram em cada passo:** OB é pagamento (empenho não); INDISPONÍVEL ≠ irregular;
indício ≠ acusação; nunca dessaturar o que já brilha; e **a VM tem 2 vCPU** — um pesado por vez.
