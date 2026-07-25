# Handoff — estado em 25/07/2026 (rodada da manhã, v13 SABRE)

**Para retomar:** *"continue pelo docs/superpowers/specs/2026-07-25-handoff-continuidade.md"*.
Branch: `feat/painel-v8-melhorias`. Último commit: `8bf14c67`.

---

## 0 · LEIA ISTO PRIMEIRO — as armadilhas de método que custaram caro

Não são detalhes de implementação; são as coisas que fizeram trabalho ser refeito.

### 0.1 Auditoria visual sem desligar o cache não vale nada

O Chrome do CDP **reusa a folha de estilo antiga**. Rodadas inteiras "corrigindo" o mesmo
sintoma achando que a regra não pegava.

```python
cmd("Network.enable"); cmd("Network.setCacheDisabled", {"cacheDisabled": True})
cmd("Page.navigate", {"url": "http://127.0.0.1:8000/painel"})
```

Já está em **todos** os scripts de auditoria. Se criar um novo, ponha também.

### 0.2 FPS medido nesta VM não mede nada

São **~4 fps (≈250 ms/quadro) mesmo com TODOS os canvas parados** — Chrome headless com
SwiftShader por software, 2 vCPU. Um número absoluto aqui não prova nada.

**O instrumento que funciona é o A/B na MESMA aba, alternando ida e volta**, com uma folha
de estilo que desliga só o que você acabou de acrescentar (`<style disabled>`). Foi assim
que a camada v13 foi medida: **266,9 ms ligada × 254,3 ms desligada**, 3 voltas — a
diferença cabe no ruído entre voltas (a desligada chegou a dar p90 pior que a ligada).

### 0.3 Comparar suíte por CONTAGEM esconde regressão — e agora a base existe

50 antes e 50 depois pode ser 50 falhas **diferentes**. O handoff anterior prescrevia a
comparação nome a nome, mas **`base.txt` nunca tinha sido gravado**. Agora existe:

```bash
./tools/testar_na_vm2.sh > /tmp/s.log
grep '^FAILED' /tmp/s.log | sed 's/ - .*//' | sort > /tmp/agora.txt
comm -13 <(grep -v '^#' tests/BASE-FALHAS-VM2.txt) /tmp/agora.txt   # vazio = sem regressão
```

Base atual: **2.524 passando · 50 falhas de ambiente da VM-2 · 6 puladas** (dominadas por
`FileNotFoundError`). Nenhum teste lê `static/jfn-painel.html` — conferido com
`grep -rl jfn-painel tests/` (vazio). Mudança de painel **não pode** quebrar a suíte Python.

### 0.4 Nunca decore o `background` de quem carrega TEXTO

Nova, desta rodada. O scan do cabeçalho de tabela era `background-image` no próprio
`thead tr`. Mesmo sendo faixa de 1px no rodapé da linha, `auditar_contraste.py` passou a ler
"Fornecedor" a **1,02:1** contra o azul do facho. Era laudo falso — mas a cura certa **não é
ensinar o auditor a ignorar**: é tirar a decoração do fundo do texto. O efeito foi removido.

### 0.5 `position` em regra de lote já mordeu DUAS vezes

`.nu-chip{position:relative}` (v12.3) empilhou os rótulos da mesa. Agora descobriu-se que
`.btn,.chip,.search .az,…{position:relative}` (bloco do vidro líquido) **arrancou o A→Z de
dentro do campo de busca** — órfão embaixo e à esquerda, por uma versão inteira. Ao criar
regra em lote, **liste quem NÃO pode receber `position`**.

---

## 1 · O QUE FOI FEITO NESTA RODADA (commit `8bf14c67`)

### 1.1 Painel v13 "SABRE"

**A lâmina de verdade.** Sabre não é barra colorida com brilho: **núcleo branco-quente na
ESPESSURA** (`linear-gradient(180deg,…)`, branco a 38–62%) + **três camadas de halo**
(perto/médio/longe) + **zumbido de passos irregulares** (senoide limpa lê como fade de CSS).
Acende na régua da capa (`.cover::before`), no sublinhado da aba (`nav.tabs button.on::after`)
e no pé da esfera ativa (`.sph.on::after`, novo). Ignição = `sabreIgnic` + `sabreFlash`.
**`prefers-reduced-motion` mantém a lâmina ACESA** — sai o zumbido, fica a estética.

**Cockpit: o conteúdo das abas deixou de ser papel** (fecha o §2.1 do handoff anterior — a
`g_radar` tinha ~100 linhas completamente estáticas). Cascata de entrada por `--li` em
`nth-child` até a 15ª linha (**sem JS**), varredura no cursor por `background-position`, e
medidor grave com o mesmo núcleo branco-quente. Vale para `tbody tr` **e** `.barw .row`.
Regra de custo respeitada: **só pintura** — nada toca `left/top/width/height`.

### 1.2 Defeitos fechados (achados olhando a tela como humano)

| Defeito | Causa-raiz medida |
|---|---|
| As 4 esferas se **sobrepunham no celular** | `flex:1;min-width:0` a 390px encolhe o botão abaixo do próprio texto; sem clipping o rótulo vaza sobre o vizinho. Cura: `flex:0 0 auto` |
| **A→Z fora do campo de busca** | `position:relative` em regra de lote (§0.5). Botão em x=127,y=512; campo em x=133,y=467,h=40 |
| **"PREFEITURA …"** no valor grande | Cortado 2× (25 chars no JS + reticências do CSS a 26px). A caixa é do NÚMERO → `R$ 13,4 mi`, órgão inteiro embaixo |
| **Zero crítico em vermelho com ⚠** | Cor e ícone fixos no sítio da chamada, no radar e nas comunidades. Agora seguem o número contra o limiar |
| Colunas de tabela **encostadas** | `tbody td{padding:8px 0}` sem respiro lateral → `td+td{padding-left:14px}` |
| Grade de KPI **esfarrapada 5+3** | `minmax(216px,…)` cabia 5 colunas em 1160px → `minmax(260px,…)` dá 4+4 |
| Abas inferiores cortando **no meio da palavra** | Faltava máscara de esmaecimento (mesmo idioma do ticker), em px |
| Subtítulo do cabeçalho truncado no celular | `max-width:38vw` datava de quando as ações dividiam a linha → 78vw |

**Contraste depois de tudo: 0 violações e 0 não medidos nas 9 abas.**

### 1.3 Adobe Express — exercitado fim a fim

Documento Express real de 2 folhas, gerado do nosso HTML:
`docs/referencias/express/cockpit-keyart.html` → folha 1 = key art do cockpit (reator,
sabre, 4 instrumentos com número real e data de apuração); folha 2 = sistema de design
(paleta HEX, tipografia, anatomia do sabre, leis da casa).

**Editor:** <https://new.express.adobe.com/id/urn:aaid:sc:US:4e38c1f8-3bb0-45cb-bbc2-e85a34d3a124>

O que a prática ensinou (detalhe em `~/.claude/.../memory/adobe-express-so-empresarial.md`):

- o fluxo **tem ordem obrigatória**: `adobe_mandatory_init` → `create_visual_design_express_skill`
  → fontes → **`html_export_readiness_skill` antes de CADA export** → `export_html_to_express`;
- **IBM Plex está no Adobe Fonts**, mas só alguns cortes pelo nome PostScript
  (`IBMPlexSans-SemiBold/-Bold`, `IBMPlexMono-Medium/-SemiBold`; os `-Regular` dão `not_found`);
- **geração de imagem por IA NÃO existe neste conector** (só `image_generative_expand`, que é
  outpainting). Arte fotográfica continua pelo Pollinations (`tools/express_ponte.py --gerar`);
- **`animate_design` existe**, mas por **presets** (Bloom/Popping/Glide/Sunrise) escolhidos na
  UI — não é animação arbitrária por prompt;
- **o importador não é navegador**: perde gradiente repetido de fundo e pseudo-elementos
  `::before`. **Desenhe em SVG inline sem filtro** — camadas empilhadas com gradiente
  importam idênticas (foi assim que o sabre e o reator sobreviveram);
- **não peça painel/dashboard responsivo ao Express** — ele recusa por contrato. Express é
  canvas FIXO: key art e sistema de design, nunca o painel vivo.

---

## 2 · PENDENTE

1. **Escolher o preset de animação** do documento Express (a UI ofereceu Bloom / Popping /
   Glide / Sunrise). Depende do dono; nenhum foi aplicado.
2. **Leitura e análise de processos SEI** — nem começou. A fila por dinheiro tem
   **18.843 processos nunca tocados, R$ 2,11 bi** (`tools/sei_fila_por_dinheiro.py`).
3. **VLM local para fotos de medição** — `foto_medicao.avaliar_fotos(descrever=…)` pronto e
   injetável; falta subir **moondream2** ou **SmolVLM** em llama.cpp na VM-2.
4. **Consulta à SEFAZ por chave de NF-e** — `nfe_verifica.situacao(consultar=…)` pronto; o
   caminho gratuito é o portal público com captcha pelo **ddddocr local** (já na VM-2).
5. **I.D.E.A.S** — R$ 3,56 bi pelo Fundo Estadual de Saúde (UG 296100), 124 processos SEI,
   743 OBs. Com o motor calibrado, vale o dossiê dedicado.
6. **Fracionamento pelo SIAFE** — 4 casos com prioridade ≥ 0,7 em 2024; o primeiro
   (4ID MÉDICOS, UG 294200) tem 12 pagamentos, 12 processos distintos, todos ≥ 80% do teto.
7. **Duas perdas decorativas no import do Express** (malha do console e marcadores das
   regras). Se incomodarem, redesenhar as duas como SVG inline.

### Dívida consciente (medida, não corrigida de propósito)

`reporting.intel_base.moeda(None)` devolve **`0,00`** — afirma que o valor é zero, contra
`INDISPONÍVEL ≠ 0`. **Não foi mexido**: a função tem **178 chamadas** e mudar a semântica
derrubaria os goldens em massa. Nos 152 sítios corrigidos o risco é nulo.

---

## 3 · O QUE JÁ ESTAVA PRONTO ANTES (v12 e anteriores)

Núcleo **HOLOMESA** (mesa de holograma: território do RJ como chão em perspectiva, domínios
em três altitudes, projetor no centro, laje com espessura girada ~16°, aro), **arc reactor**
billboard com brasa laranja por dentro, **nós com relógio próprio** (fase determinística por
índice), **orçamento de vida** (`IntersectionObserver` para a mesa parar fora da viewport),
**holograma universal** em todo acionável (`.hlx`, elemento real e não pseudo),
**R$ no padrão brasileiro** em 152 sítios com teste que trava a volta, e o
**`/api/intel/hub_compartilhado`** que passou de 90 s sem resposta para 3,4 s ao ler o cache
que já existia em disco.

---

## 4 · COMANDOS

```bash
# suíte (na VM-2, deixa a VM-1 livre) — comparar nome a nome, §0.3
./tools/testar_na_vm2.sh > /tmp/s.log
grep '^FAILED' /tmp/s.log | sed 's/ - .*//' | sort > /tmp/agora.txt
comm -13 <(grep -v '^#' tests/BASE-FALHAS-VM2.txt) /tmp/agora.txt

# contraste no navegador que já roda na VM (CDP 9222)
.venv/bin/python tools/auditar_contraste.py

# ponte do Express (independe do MCP)
.venv/bin/python -m tools.express_ponte --spec       # paleta OKLCH→HEX, fontes, medidas
.venv/bin/python -m tools.express_ponte --gerar portal --seeds 3   # arte pelo Pollinations
.venv/bin/python -m tools.express_ponte --importar

# painel (o serviço leva ~20 s para responder: faz login SIAFE no boot)
systemctl --user restart jfn && sleep 25 && \
  curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/painel
```

**Auditar o painel sem chutar:** CDP na 9222 com
`websocket.create_connection(..., suppress_origin=True)` (sem isso o Chrome recusa com 403)
**e `Network.setCacheDisabled`** (§0.1). **As variantes é que revelam o defeito** que a tela
normal esconde: `setDeviceMetricsOverride` a 390px achou as esferas sobrepostas, e
`Emulation.setEmulatedMedia` com `prefers-reduced-motion:reduce` já achou a mesa em branco.

**Transforme "está bonito" em critério verificável.** O transbordamento das folhas do
key-art só apareceu porque um probe percorreu `.bloco` comparando `scrollHeight` com
`clientHeight` e o `getBoundingClientRect()` de cada filho com o do pai — três blocos
vazavam e o olho tinha deixado passar dois.

**Ganchos de auditoria no painel** (existem para isto, não são código morto):
`window.__holoCam` (estado da câmera) e `window.__nuEstado()` (visibilidade + rAF do laço).

**Regras da casa que valeram em cada passo:** OB é pagamento (empenho não); INDISPONÍVEL ≠
irregular; indício ≠ acusação; **zero grave não é alarme**; nunca dessaturar o que já brilha;
e **a VM tem 2 vCPU** — um pesado por vez.
