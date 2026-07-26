# Painel v14 "HOLOCRON" — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recomendado) ou `superpowers:executing-plans` para executar tarefa a tarefa. Os passos usam
> checkbox (`- [ ]`). **Leia antes:** `docs/superpowers/plans/2026-07-25-plano-mestre-v14.md` §1
> (constraints globais) — esta seção é herdada e não se repete aqui na íntegra.

**Goal:** Dar ao painel uma camada visual v14 que eleva UI, templates, botões, capas, tabelas e
as **51 abas** a um idioma ultratech coerente — holocron, sabre, nebulosa, Jarvis — com uma
assinatura própria por aba, sem regredir nenhuma correção das camadas v7–v13.

**Architecture:** Camada **aditiva** ao fim do `<style>` de `static/jfn-painel.html`, mais um
registro `ASSINATURA` de 51 entradas em JS e um seletor `body[data-aba]`. A identidade por aba
sai de **uma tabela de dados**, não de 51 blocos de CSS escritos à mão. Toda decoração nova mora
num elemento injetado `<i class="fac">` — irmão do `.hlx` do v12.3 — porque a lei da casa proíbe
decorar o `background` de quem carrega texto e porque `.card::before`/`::after` já estão ocupados
desde o v7/v8. Arte fotográfica vem do Pollinations; selos, placas e o documento de sistema de
design vêm do Adobe Express.

**Tech Stack:** HTML/CSS/JS puro self-hosted (zero CDN), OKLCH, `color-mix`, `@property`,
IBM Plex Sans/Mono, CDP na porta 9222 para auditoria, pytest para travar regressão,
MCP Adobe Express, Pollinations (`tools/express_ponte.py --gerar`).

---

## Global Constraints

Valores exatos, copiados das leis já escritas. **Os requisitos de toda tarefa incluem esta seção.**

- **Camada aditiva.** O bloco v14 vai ao **fim** do `<style>` (hoje termina na linha 1380). Nenhum
  bloco v7–v13 é reescrito. A cascata vence.
- **Nunca escrever os dois caracteres de fecha-comentário dentro de um comentário CSS.** Escrever
  "fecha-comentario" por extenso. Um órfão engole o `@media` inteiro abaixo, em silêncio.
- **Nenhuma regra em lote impõe `position`.** Já mordeu duas vezes. O v14 **não precisa** de
  nenhuma: `.card` (linha 314) e `.cover` (linha 270) já são `position:relative`, e a decoração
  nova mora num filho que se posiciona sozinho. Se alguma tarefa parecer precisar, **pare** e
  reveja — a lista de quem NÃO pode receber `position` é: `.nu-chip`, `.search .az`, `.hlx`, `.fac`.
- **Nunca decorar o `background` de quem carrega TEXTO.** Toda `background-image` nova vai no
  `<i class="fac">` ou no `<i class="hlx">`, que não têm texto.
- **`flex:0 0 auto` em strip horizontal.** Nunca `flex:1;min-width:0`.
- **Só pintura.** Animação nova só pode tocar `transform`, `opacity`, `background-position`,
  `background-size`, `box-shadow`, `filter`. **Nada** toca `left/top/width/height`.
- **Animação que já existe não se sobrescreve:** ao adicionar `animation:` a um seletor que já
  tem, componha as duas na mesma declaração (o `graveGlow` ficou desligado uma versão inteira).
- **`prefers-reduced-motion:reduce`:** a estética **fica acesa**, o movimento sai. Foi assim no v13.
- **`html.rest *`** (aba do navegador oculta) já pausa toda animação CSS — nada a declarar.
- **Contraste ≥ 4,5:1**, `tools/auditar_contraste.py` com **0 violações e 0 não medidos** nas 51 abas.
- **Alvo de toque ≥ 24px** (WCAG 2.5.8), `tools/auditar_layout.py` com 0 violações de norma.
- **Orçamento de desenho: 16,6 ms/quadro.** FPS nesta VM não mede nada (≈4 fps parado); o
  instrumento é **A/B na mesma aba** com `<style disabled>`.
- **Auditoria por CDP sempre com `Network.setCacheDisabled`** e
  `websocket.create_connection(..., suppress_origin=True)`.
- **Peso:** teto de **900 KB por arte**; JPEG q80 para fundo, SVG para vetor. Zero CDN.
- **Honestidade:** vida visual só com dado ou evento real; dado sintético proibido;
  INDISPONÍVEL ≠ 0; zero grave não é alarme.
- **Nenhum teste Python lê `static/jfn-painel.html`** exceto `tests/test_painel_css_integro.py` e
  os que este plano cria. Mudança de painel **não pode** quebrar a suíte.

---

## Conceito (papel 1 do `site-3d-premium` — Arquiteto)

**Ideia central: o painel é um HOLOCRON.** Um cristal-arquivo. A esfera é uma **face** do cristal;
cada aba é uma **faceta** dessa face, com matiz, glifo, lema e instrumento próprios. O dado não é
papel impresso: é luz presa no cristal. O **sabre** (v13) continua sendo a assinatura de energia;
o holocron acrescenta a **moldura** e a **identidade**.

**As três leis novas do v14:**

1. **Chanfro, não canto.** Todo contêiner de dado ganha canto chanfrado — idioma cyberpunk
   (`augmented-ui`), mas de mão própria, sem dependência. **Dois** cantos cortados, nunca quatro:
   quatro lê como moldura de jogo; dois lê como peça usinada.
2. **Toda aba tem nome de luz.** Matiz da faceta = matiz da esfera **± 34° no máximo**. Fora
   dessa faixa o painel vira arco-íris e a esfera perde a voz — é o "restrained" do `DESIGN.md`
   aplicado a 51 telas.
3. **A moldura se desenha.** Idioma Arwes: ao entrar na aba, o quadro é **traçado** em vez de
   aparecer pronto. Traçado por `background-size` num elemento sem texto — nunca por `width`.

**Paleta (HEX real, de `docs/referencias/express/ESPECIFICACAO.md`, gerada do próprio painel):**

| Token | HEX | Papel |
|---|---|---|
| `--ion` | `#59A3FF` | azul — console: estrutura, interação, frio |
| `--ion-hi` | `#90D7FF` | azul claro — realce de console |
| `--flame` | `#FF8804` | laranja — ENERGIA: ação, dinheiro, carga |
| `--flame-hi` | `#FFBF5C` | laranja claro — número de dinheiro |
| `--rose` | `#FF5472` | rosa — severidade crítica (nunca decorativo) |
| `--green` | `#61DA92` | verde — conforme/ok |
| `--bg` | `#010410` | fundo |
| `--card` | `#081222` | superfície |
| `--tx` | `#EAF3F8` | texto |
| `--mut` | `#90A5B2` | texto secundário |

**Matiz base por esfera** (grau OKLCH, a que a faceta soma seu delta):
`inicio 205` · `estado 245` · `prefeitura 85` · `geral 300`.

**O erro mais comum que faz interface "sci-fi" parecer amadora** — e que este plano evita por
regra, não por gosto: **glow uniforme em tudo**. Quando tudo brilha, nada brilha, e o texto perde
contraste medido. No v14 o brilho é **escasso e semântico**: núcleo do sabre, faceta ativa,
severidade alta. O segundo erro é **chanfro/cantoneira em peça pequena** — numa peça de 90×36 px
o corte come o rótulo; a lei do v12.3 ("cantoneira só onde há ÁREA") continua valendo e o v14 a
estende ao chanfro.

---

## Arsenal — geração de imagem e templates (o que entra e o que não entra)

Levantado nesta rodada, com licença e forma de uso. **Nada aqui entra por CDN**: baixa-se, mede-se
o peso, versiona-se em `static/assets/`.

| Fonte | O que dá | Chave / custo | Como usar aqui |
|---|---|---|---|
| **Pollinations** `image.pollinations.ai` | nebulosa, textura, arte de fundo (Flux) | **sem chave, sem login**; anônimo é limitado a ~1 requisição/15 s, sem SLA | `tools/express_ponte.py --gerar` já implementa. Para 4 nebulosas × 3 seeds = 12 chamadas ≈ 3 min com espaçamento |
| **Adobe Express (MCP)** | selo, placa, key art, documento de sistema de design | conta já conectada | canvas **FIXO**; ordem obrigatória de chamadas (Tarefa 11). **Recusa dashboard responsivo por contrato** — nunca peça o painel a ele |
| **`propjockey/augmented-ui`** (MIT) | idioma de canto chanfrado/recortado em CSS puro | grátis | **referência, não dependência.** Copiamos o *idioma* (chanfro por `clip-path`), não o arquivo — o painel é zero-dependência e a lib traria ~30 KB para 3 formas que escrevemos em 6 linhas |
| **`arwes/arwes`** | frames que se desenham, scanline, timing sci-fi | grátis, **projeto sem manutenção** | **referência de movimento**, não código: é React + JSS, incompatível com o painel |
| **`devdogio/sci-fi-ui`** | HUD sci-fi vetorial | aberto | banco de **formas** para desenhar selo/medidor no Express; nada é importado direto (é uGUI/Unity) |
| **`svg-sprite/svg-sprite`** (MIT) | empacotar SVG em sprite + CSS | grátis, Node | só se a folha de glifos passar de ~20 arquivos. Hoje `jfn-icones.js` (8,5 KB) já resolve — **não adotar por enquanto** |
| **Cloudflare Workers AI** | geração de imagem alternativa | **exige chave**; free tier com limite | já há chave no projeto para visão (`llm/visao.py`). **Só como reserva** se o Pollinations cair — e medindo custo antes (lei: nunca assumir free tier) |

### Imagem pronta (as "dezenas de imagens") — só com licença limpa

Arte gerada resolve o fundo abstrato; **arte real de telescópio** dá o que nenhum modelo dá — uma
nebulosa que existe. Entra no painel, mas **só com procedência declarada**, porque "fontes sempre
citadas" é regra absoluta da casa e duas destas fontes **exigem crédito visível**.

| Fonte | Licença | Crédito | Serve para |
|---|---|---|---|
| **NASA** (imagens próprias) | **domínio público** | dispensado, mas declaramos | nebulosa, campo estelar, Terra |
| **ESA/Hubble** `esahubble.org/images` | **CC BY 4.0** | **obrigatório e visível**, texto inalterado: `ESA/Hubble` | nebulosa em alta resolução |
| **ESA/Webb** `esawebb.org` | **CC BY 4.0** | **obrigatório e visível**: `ESA/Webb` | idem, no infravermelho |
| **Unsplash** | Unsplash License | não exigido | textura, superfície, granulado |
| **Pexels** | Pexels License | não exigido | idem |
| **Openverse** (WordPress) | busca sobre ~800 mi de itens, **licença varia por item** | conforme o item | achar item CC0 específico |
| **Wikimedia Commons** | varia por item | conforme o item | conferir a procedência de um arquivo achado solto |

**Duas armadilhas de licença que este plano evita por regra:**
1. **Nem toda imagem do Hubble é da NASA.** As que vêm da ESA são **CC BY 4.0**, não domínio
   público — misturar as duas e tratar tudo como domínio público é erro de licença, não de gosto.
2. **CC BY 4.0 permite uso comercial, mas proíbe sugerir endosso.** Nenhuma arte da ESA pode ser
   posta de modo que pareça a ESA endossando o painel ou um achado de fiscalização.

**Ficam de fora, com motivo:** Freepik/GraphicRiver/IconScout (licença que não permite
redistribuição no repositório), Replicate/fal.ai/HuggingFace (free é crédito inicial com chave,
não endpoint aberto), Higgsfield (o trial é só-site; já reprovado nesta casa).

---

## File Structure

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `static/jfn-painel.html` | painel inteiro (CSS + JS + HTML) | **Modificar**: bloco CSS v14 ao fim do `<style>` (após linha 1379); registro `ASSINATURA` e funções `facetar`/`instrumentar` no `<script>`; 1 linha em `ir()` |
| `tools/auditar_layout.py` | auditor de geometria | **Modificar**: linha 41 — ler as abas do próprio painel em vez da lista fixa de 9 |
| `tools/auditar_contraste.py` | auditor de contraste | **Modificar**: linha 16 — idem |
| `tools/painel_abas.py` | **Criar**: fonte única da lista de abas, lida do HTML | novo |
| `tools/auditar_assinatura.py` | **Criar**: prova que as 51 facetas existem e são distintas | novo |
| `tools/medir_quadro.py` | **Criar**: A/B de ms/quadro com `<style disabled>` | novo |
| `tests/test_painel_assinaturas.py` | **Criar**: toda aba tem assinatura; matiz dentro de ±34° | novo |
| `tests/test_painel_css_integro.py` | integridade do CSS | **Modificar**: acrescentar as regras v14 ao guarda-corpo nominal |
| `static/assets/holocron-{inicio,estado,prefeitura,geral}.svg` | placa de face, do Express | **Criar** |
| `static/assets/nebula-{inicio,estado,prefeitura,transversal}.jpg` | nebulosa por esfera (gerada) | **Substituir/criar** |
| `static/assets/portal-nebula.jpg` | nebulosa real do portal (telescópio) | **Substituir** |
| `static/assets/CREDITOS-ARTE.md` | procedência e licença de toda arte servida | **Criar** |
| `tests/test_arte_procedencia.py` | trava arte sem fonte citada e crédito CC BY ausente | **Criar** |
| `docs/referencias/express/holocron-v14.html` | fonte do documento Express (key art + sistema) | **Criar** |
| `DESIGN.md` | sistema visual | **Modificar**: seção v14 no topo |
| `docs/superpowers/specs/2026-07-2X-handoff-v14.md` | handoff | **Criar** |

---

## Task 1: Instrumentos que enxergam as 51 abas

Os dois auditores olham **9 abas** (linha 41 de `auditar_layout.py`, linha 16 de
`auditar_contraste.py`). Um plano que promete assinatura em 51 abas e mede 9 é um plano que não
se verifica. Antes de qualquer pixel, os instrumentos precisam alcançar tudo — e ler a lista **do
próprio painel**, para nunca envelhecerem quando alguém acrescentar uma aba.

**Files:**
- Create: `tools/painel_abas.py`
- Modify: `tools/auditar_layout.py:41`
- Modify: `tools/auditar_contraste.py:16`
- Test: `tests/test_painel_abas.py`

**Interfaces:**
- Produces: `painel_abas.abas() -> list[str]` (ids na ordem do painel) e
  `painel_abas.abas_por_esfera() -> dict[str, list[str]]`. As Tarefas 2, 12 e 13 consomem.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/test_painel_abas.py
"""A lista de abas do painel tem UMA fonte: o proprio painel.

Os dois auditores tinham uma copia manual de 9 abas. Copia de lista diverge — foi
exatamente assim que a constante de dispensa ganhou uma terceira copia divergente
dentro de um detector. Aqui a copia envelhecia calada: o auditor dizia "9 abas
limpas" e o dono lia "o painel esta limpo".
"""
from tools import painel_abas


def test_le_todas_as_abas_do_painel():
    abas = painel_abas.abas()
    assert len(abas) == 51, f"o painel tem {len(abas)} abas, nao 51 — atualize o numero aqui de proposito"
    assert abas[0] == "i_cockpit"
    assert "g_acoes" in abas
    assert len(set(abas)) == len(abas), "id de aba repetido no painel"


def test_agrupa_por_esfera():
    por_esf = painel_abas.abas_por_esfera()
    assert set(por_esf) == {"inicio", "estado", "prefeitura", "geral"}
    assert por_esf["inicio"] == ["i_cockpit"]
    assert len(por_esf["estado"]) == 14
    assert len(por_esf["prefeitura"]) == 14
    assert len(por_esf["geral"]) == 22
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_painel_abas.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'tools.painel_abas'`

- [ ] **Step 3: Implementar a fonte única**

```python
# tools/painel_abas.py
"""Fonte unica da lista de abas do painel — lida do proprio HTML.

Os auditores mantinham uma copia manual de 9 abas; com 51 no painel, a copia nao
era um atalho, era um laudo falso. Le o bloco `const TABS={...}` de
static/jfn-painel.html e devolve os ids na ordem em que o painel os monta.
"""
from __future__ import annotations

import re
from pathlib import Path

PAINEL = Path(__file__).resolve().parents[1] / "static" / "jfn-painel.html"

_BLOCO = re.compile(r"const TABS=\{(.*?)\n\};", re.S)
_ESFERA = re.compile(r"^\s{2}(\w+):\[", re.M)
_ID = re.compile(r"id:'([a-z_]+)'")


def _corpo() -> str:
    m = _BLOCO.search(PAINEL.read_text(encoding="utf-8"))
    if not m:
        raise RuntimeError("nao achei `const TABS={...}` em static/jfn-painel.html")
    return m.group(1)


def abas_por_esfera() -> dict[str, list[str]]:
    """{esfera: [id, ...]} na ordem do painel."""
    corpo = _corpo()
    marcas = list(_ESFERA.finditer(corpo))
    fora: dict[str, list[str]] = {}
    for i, mk in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(corpo)
        fora[mk.group(1)] = _ID.findall(corpo[mk.end() : fim])
    return fora


def abas() -> list[str]:
    """Todos os ids, na ordem do painel."""
    return [a for lista in abas_por_esfera().values() for a in lista]


if __name__ == "__main__":
    for esf, lista in abas_por_esfera().items():
        print(f"{esf:12s} {len(lista):2d}  {' '.join(lista)}")
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_painel_abas.py -q`
Expected: 2 passed

- [ ] **Step 5: Ligar os dois auditores na fonte única**

Em `tools/auditar_layout.py`, trocar a linha 41-42 (a lista fixa) por:

```python
from tools.painel_abas import abas as _abas_do_painel

ABAS = _abas_do_painel()          # 51 abas, lidas do painel — nunca envelhece
```

Em `tools/auditar_contraste.py`, trocar a linha 16 pela mesma coisa. **Não mexer** no resto de
nenhum dos dois: a leitura de argumento por `sys.argv` (linhas 45-48 do layout) continua
sobrepondo a lista, que é como se audita uma aba só.

- [ ] **Step 6: Provar que os auditores enxergam mais**

```bash
.venv/bin/python -c "import tools.auditar_layout as a" 2>/dev/null; \
.venv/bin/python -c "from tools.painel_abas import abas; print(len(abas()))"
```
Expected: `51`

- [ ] **Step 7: Gravar a linha de base ANTES de qualquer mudança visual**

Sem base gravada não existe "sem regressão" — a lição de `BASE-FALHAS-VM2.txt` custou uma rodada.

```bash
systemctl --user restart jfn && sleep 25
.venv/bin/python tools/auditar_contraste.py > docs/superpowers/specs/base-contraste-v13.txt
.venv/bin/python tools/auditar_layout.py    > docs/superpowers/specs/base-layout-v13.txt
tail -5 docs/superpowers/specs/base-contraste-v13.txt
```
Expected: laudo das 51 abas gravado; anotar no commit quantas violações havia **antes**.

- [ ] **Step 8: Commit**

```bash
git add tools/painel_abas.py tools/auditar_layout.py tools/auditar_contraste.py \
        tests/test_painel_abas.py docs/superpowers/specs/base-contraste-v13.txt \
        docs/superpowers/specs/base-layout-v13.txt
git commit -m "test: auditores do painel leem as 51 abas do proprio HTML + base v13 gravada"
```

---

## Task 2: O registro ASSINATURA e o seletor `body[data-aba]`

O mecanismo que torna "assinatura por aba" possível sem 51 blocos escritos à mão: **uma linha**
em `ir()` publica a aba no `<body>`, e **uma tabela** de 51 entradas define matiz, glifo, lema e
instrumento. Tudo que vem depois lê daqui.

**Files:**
- Modify: `static/jfn-painel.html` (script: após `const TABS={...}`, linha 1641; e dentro de `ir()`, linha 1660)
- Test: `tests/test_painel_assinaturas.py`

**Interfaces:**
- Consumes: `painel_abas.abas()` (Tarefa 1).
- Produces: `window.ASSINATURA` — objeto `{[abaId]: {h:number, gl:string, lema:string, inst:string}}`;
  `body[data-aba="<id>"]`; variáveis CSS `--fac-h` (número, grau OKLCH) e `--fac-i` (índice do
  instrumento). Tarefas 3–10 consomem.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/test_painel_assinaturas.py
"""Toda aba do painel tem assinatura, e nenhuma assinatura foge da familia da esfera.

Duas coisas travadas aqui, as duas por motivo medido:
1. COBERTURA — quem acrescentar aba e esquecer a assinatura recebe uma aba sem
   identidade, que e exatamente o defeito que o v14 existe para corrigir. Pego em
   teste, nao em revisao.
2. FAMILIA — a matiz da faceta e relativa a esfera e limitada a +-34 graus. Sem
   esse teto o painel vira arco-iris e a esfera perde a voz; e a regra "restrained"
   do DESIGN.md, que nao se sustenta em 51 telas por disciplina do autor.
"""
import json
import re
from pathlib import Path

from tools.painel_abas import abas

PAINEL = Path(__file__).resolve().parents[1] / "static" / "jfn-painel.html"
LIMITE_MATIZ = 34


def _assinaturas() -> dict[str, dict]:
    fonte = PAINEL.read_text(encoding="utf-8")
    m = re.search(r"const ASSINATURA=\{(.*?)\n\};", fonte, re.S)
    assert m, "o painel perdeu o registro `const ASSINATURA={...}`"
    fora = {}
    for aba, corpo in re.findall(r"(\w+):\{([^}]*)\}", m.group(1)):
        campos = dict(re.findall(r"(\w+):\s*(-?\d+|'[^']*')", corpo))
        fora[aba] = {
            k: int(v) if re.fullmatch(r"-?\d+", v) else v.strip("'")
            for k, v in campos.items()
        }
    return fora


def test_toda_aba_tem_assinatura():
    assinaturas, esperadas = _assinaturas(), abas()
    faltando = [a for a in esperadas if a not in assinaturas]
    sobrando = [a for a in assinaturas if a not in esperadas]
    assert not faltando, "aba sem assinatura (fica sem identidade na tela): " + ", ".join(faltando)
    assert not sobrando, "assinatura de aba que nao existe mais: " + ", ".join(sobrando)


def test_campos_obrigatorios_preenchidos():
    for aba, a in _assinaturas().items():
        for campo in ("h", "gl", "lema", "inst"):
            assert campo in a, f"{aba}: falta o campo `{campo}`"
        assert a["lema"].strip(), f"{aba}: lema vazio"
        assert not a["lema"].endswith("."), f"{aba}: lema e legenda de instrumento, sem ponto final"
        assert a["inst"] in {"fila", "rede", "tempo", "moeda", "mapa", "pessoa"}, (
            f"{aba}: instrumento `{a['inst']}` nao existe"
        )


def test_matiz_fica_na_familia_da_esfera():
    fora_da_faixa = {
        aba: a["h"] for aba, a in _assinaturas().items() if abs(a["h"]) > LIMITE_MATIZ
    }
    assert not fora_da_faixa, (
        "matiz de faceta fora de +-34 graus da esfera — o painel vira arco-iris: "
        + json.dumps(fora_da_faixa, ensure_ascii=False)
    )


def test_ir_publica_a_aba_no_body():
    """Sem `data-aba` no <body> nenhuma regra por aba existe. Ja sumiu uma vez por
    regra em lote; aqui e presenca nominal, custo zero."""
    fonte = PAINEL.read_text(encoding="utf-8")
    assert "document.body.dataset.aba=id" in fonte, (
        "`ir()` parou de publicar a aba no body — todas as 51 assinaturas morrem juntas"
    )
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_painel_assinaturas.py -q`
Expected: FAIL com `AssertionError: o painel perdeu o registro const ASSINATURA={...}`

- [ ] **Step 3: Escrever o registro — as 51 facetas**

Inserir em `static/jfn-painel.html` **logo após** o fechamento de `const TABS={...};` (linha 1641):

```javascript
/* ═══════════ v14 "HOLOCRON" — a assinatura de cada faceta ═══════════
   51 abas, 51 identidades, UMA tabela. Cada entrada define:
     h    = deslocamento de MATIZ da faceta, em graus, relativo à matiz da esfera.
            Teto de ±34° de propósito: fora disso o painel vira arco-íris e a
            esfera perde a voz. tests/test_painel_assinaturas.py trava o teto.
     gl   = glifo do jfn-icones.js que a capa da aba estampa no selo.
     lema = o que a capa diz sob o título. Uma linha, sem ponto final: é legenda
            de instrumento, não slogan. Nunca adjetiva o achado (indício ≠ acusação).
     inst = a leitura principal da aba, que decide o desenho da capa e do medidor:
            'fila' (ordem por gravidade) · 'rede' (quem se liga a quem) ·
            'tempo' (o quando é o achado) · 'moeda' (o quanto) ·
            'mapa' (território/órgão) · 'pessoa' (vínculo humano).
   Quem acrescentar aba e esquecer a assinatura é pego pelo teste, não na revisão. */
const ASSINATURA={
  /* ── INÍCIO ── */
  i_cockpit:{h:0,gl:'◎',lema:'a vigília inteira em uma tela',inst:'mapa'},
  /* ── ESTADO (matiz base 245) ── */
  e_panorama:{h:0,gl:'📊',lema:'o retrato do gasto estadual no período',inst:'moeda'},
  e_pericias:{h:-14,gl:'⚖️',lema:'perícias abertas e o que cada uma apura',inst:'fila'},
  e_sanc:{h:22,gl:'🚫',lema:'fornecedor com sanção vigente à época do pagamento',inst:'fila'},
  e_frac:{h:-24,gl:'✂️',lema:'compra fatiada colada no teto da dispensa',inst:'moeda'},
  e_sobre:{h:28,gl:'📈',lema:'preço acima do comparável no mesmo item',inst:'moeda'},
  e_escal:{h:31,gl:'📈',lema:'preço que sobe sem o item mudar',inst:'tempo'},
  e_comp:{h:12,gl:'💰',lema:'o mesmo item, órgão a órgão',inst:'moeda'},
  e_adit:{h:-8,gl:'📑',lema:'aditivo que refaz o contrato depois de assinado',inst:'tempo'},
  e_certames:{h:-30,gl:'🧮',lema:'como o certame foi julgado e por quem',inst:'rede'},
  e_cartel:{h:18,gl:'🔗',lema:'concorrentes que se repetem em bloco',inst:'rede'},
  e_conluio:{h:25,gl:'🕸️',lema:'quadro societário que cruza entre concorrentes',inst:'rede'},
  e_poder:{h:-19,gl:'🏛️',lema:'quem foi nomeado e por qual ato',inst:'pessoa'},
  e_alertas:{h:34,gl:'🚨',lema:'o que o motor levantou e ainda não foi lido',inst:'fila'},
  e_siafe:{h:6,gl:'💰',lema:'ordem bancária como o SIAFE a emitiu',inst:'moeda'},
  /* ── PREFEITURA (matiz base 85) ── */
  p_panorama:{h:0,gl:'📊',lema:'o retrato do gasto municipal no período',inst:'moeda'},
  p_gastos:{h:-22,gl:'✂️',lema:'despesa municipal por natureza e por órgão',inst:'moeda'},
  p_sanc:{h:24,gl:'🚫',lema:'sanção vigente contra quem a Prefeitura pagou',inst:'fila'},
  p_sobre:{h:30,gl:'📈',lema:'preço municipal acima do comparável',inst:'moeda'},
  p_escal:{h:33,gl:'📈',lema:'preço municipal que sobe sem o item mudar',inst:'tempo'},
  p_comp:{h:11,gl:'💰',lema:'o mesmo item, entre Estado e Município',inst:'moeda'},
  p_adit:{h:-9,gl:'📑',lema:'aditivo municipal e o que ele mudou',inst:'tempo'},
  p_cartel:{h:17,gl:'🔗',lema:'concentração de contratos em poucos fornecedores',inst:'rede'},
  p_comis:{h:-28,gl:'🎖️',lema:'cargo comissionado por órgão e por vínculo',inst:'pessoa'},
  p_benef:{h:-14,gl:'🍞',lema:'benefício pago e a natureza do vínculo',inst:'pessoa'},
  p_fant:{h:20,gl:'👻',lema:'empresa sem fachada, sem quadro, sem porta',inst:'rede'},
  p_ppp:{h:-33,gl:'🏗️',lema:'parceria público-privada e o que ela contratou',inst:'moeda'},
  p_conluio:{h:26,gl:'🕸️',lema:'quadro societário cruzado no município',inst:'rede'},
  p_contr:{h:-5,gl:'📄',lema:'contrato municipal e sua vigência',inst:'tempo'},
  /* ── TRANSVERSAL (matiz base 300) ── */
  g_buscar:{h:0,gl:'🔎',lema:'procure por nome, CNPJ, órgão ou processo',inst:'mapa'},
  g_radar:{h:29,gl:'🎯',lema:'a fila por gravidade, do pior para o resto',inst:'fila'},
  g_prioridade:{h:32,gl:'⚡',lema:'o que apurar primeiro, e por qual razão',inst:'fila'},
  g_conluioq:{h:24,gl:'🤝',lema:'sócios em comum entre quem disputou junto',inst:'rede'},
  g_comun:{h:21,gl:'🧩',lema:'agrupamentos que o grafo societário revela',inst:'rede'},
  g_retro:{h:-16,gl:'🔮',lema:'o que o motor teria dito no passado',inst:'tempo'},
  g_riscos:{h:34,gl:'👻',lema:'perfil de risco por fornecedor',inst:'fila'},
  g_dep:{h:-11,gl:'🔗',lema:'fornecedor que vive de um pagador só',inst:'rede'},
  g_capital:{h:-25,gl:'🫧',lema:'capital social irrisório diante do contrato',inst:'moeda'},
  g_dez:{h:-30,gl:'📅',lema:'a corrida de dezembro no fim do exercício',inst:'tempo'},
  g_ocult:{h:18,gl:'🕸️',lema:'controle que não aparece no quadro declarado',inst:'rede'},
  g_nep:{h:-20,gl:'👪',lema:'parentesco entre nomeado e nomeante',inst:'pessoa'},
  g_nepx:{h:-23,gl:'🔀',lema:'parentesco cruzado entre órgãos',inst:'pessoa'},
  g_fenix:{h:27,gl:'🦅',lema:'empresa que recebeu depois da baixa',inst:'tempo'},
  g_porta:{h:-8,gl:'🚪',lema:'servidor que passou para o outro lado do balcão',inst:'pessoa'},
  g_laranjas:{h:22,gl:'🎭',lema:'sócio de perfil incompatível com o contrato',inst:'pessoa'},
  g_socserv:{h:-13,gl:'🕴️',lema:'servidor que é sócio de quem contrata',inst:'pessoa'},
  g_poder:{h:-18,gl:'🏛️',lema:'nomeações e o ato que as sustenta',inst:'pessoa'},
  g_conluio:{h:25,gl:'🕸️',lema:'quadro societário cruzado, nas duas esferas',inst:'rede'},
  g_validar:{h:-3,gl:'🏢',lema:'confirme ou descarte o que o motor levantou',inst:'fila'},
  g_sweeps:{h:8,gl:'🛰️',lema:'o que está sendo coletado agora',inst:'tempo'},
  g_acoes:{h:14,gl:'⚡',lema:'disparar coleta, relatório ou dossiê',inst:'mapa'},
};
/* matiz base de cada face do cristal, em graus OKLCH — a faceta soma o seu delta */
const _ESF_MATIZ={inicio:205,estado:245,prefeitura:85,geral:300};
```

- [ ] **Step 4: Publicar a faceta no `<body>` — a única linha em `ir()`**

Em `ir()`, **logo após** a linha 1660 (`document.body.setAttribute('data-esf',esfera);`), inserir:

```javascript
  /* v14: a faceta ativa vira estado do documento. É daqui que saem as 51 identidades —
     uma linha aqui, uma tabela ali, zero bloco de CSS escrito à mão por aba. */
  document.body.dataset.aba=id;
  {const s=ASSINATURA[id]||{h:0,inst:'mapa'};
   document.body.style.setProperty('--fac-h',(_ESF_MATIZ[esfera]+(s.h||0)));
   document.body.dataset.inst=s.inst||'mapa';}
```

- [ ] **Step 5: Rodar o teste e ver passar**

Run: `.venv/bin/python -m pytest tests/test_painel_assinaturas.py tests/test_painel_css_integro.py -q`
Expected: 5 passed

- [ ] **Step 6: Confirmar no navegador vivo, não no arquivo**

```bash
systemctl --user restart jfn && sleep 25
.venv/bin/python - <<'PY'
import json, websocket, requests
ws=websocket.create_connection(json.loads(requests.get("http://127.0.0.1:9222/json").text)[0]["webSocketDebuggerUrl"],suppress_origin=True)
i=[0]
def cmd(m,p=None):
    i[0]+=1; ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
    while True:
        r=json.loads(ws.recv())
        if r.get("id")==i[0]: return r
cmd("Network.enable"); cmd("Network.setCacheDisabled",{"cacheDisabled":True})
cmd("Page.navigate",{"url":"http://127.0.0.1:8000/painel"})
import time; time.sleep(6)
def js(e): return cmd("Runtime.evaluate",{"expression":e,"returnByValue":True})["result"]["result"].get("value")
js("ir('g_fenix')"); time.sleep(2)
print("data-aba :",js("document.body.dataset.aba"))
print("--fac-h  :",js("getComputedStyle(document.body).getPropertyValue('--fac-h')"))
print("data-inst:",js("document.body.dataset.inst"))
PY
```
Expected: `data-aba : g_fenix` · `--fac-h : 327` (300 + 27) · `data-inst: tempo`

- [ ] **Step 7: Commit**

```bash
git add static/jfn-painel.html tests/test_painel_assinaturas.py
git commit -m "feat(painel): v14 registro ASSINATURA das 51 facetas + body[data-aba]"
```

---

## Task 3: Tokens do cristal e o elemento `.fac`

A camada onde toda decoração nova vai morar. `.card::before` (luz especular, v7) e `.card::after`
(border-beam, v8) estão ocupados; a lei da casa proíbe decorar o `background` de quem tem texto.
A saída já foi inventada no v12.3 e funcionou: **injetar um elemento real**. O v14 injeta o seu.

**Files:**
- Modify: `static/jfn-painel.html` (CSS ao fim do `<style>`, após linha 1379; JS após `holografar`, linha 1704)

**Interfaces:**
- Consumes: `--fac-h`, `body[data-aba]`, `body[data-inst]` (Tarefa 2).
- Produces: variáveis `--fac`, `--fac-d`, `--fac-soft`, `--chanfro`, `--kyber`; elemento
  `<i class="fac">` em `.card,.cover,.sheet,.leitura`; função `facetar(root)`. Tarefas 4–10 consomem.

- [ ] **Step 1: Escrever os tokens e a base do `.fac`**

Ao **fim** do `<style>`, antes de `</style>` (linha 1380):

```css
  /* ══ v14 "HOLOCRON" ═══════════════════════════════════════════════════════
     O painel é um cristal-arquivo: a esfera é uma FACE, a aba é uma FACETA.
     Três leis, todas verificáveis:
     1. chanfro em DOIS cantos, nunca quatro (quatro lê como moldura de jogo);
     2. matiz da faceta = matiz da esfera ± 34° no máximo (teste trava o teto);
     3. a moldura se DESENHA — por background-size num elemento sem texto, nunca
        por width (a lei do "só pintura" vale para tudo que entrou aqui).
     Por que um elemento injetado e não um pseudo: .card::before é a luz especular
     do v7 e .card::after é a border-beam do v8. E decorar o background de quem
     carrega TEXTO já produziu laudo falso de contraste (1,02:1 em "Fornecedor").
     O <i class="fac"> não tem texto — pode ser decorado à vontade.
     NENHUMA regra deste bloco impõe `position` em lote: .card e .cover já são
     relative desde o v7, e o .fac se posiciona sozinho. Quem NUNCA pode receber
     `position` de fora: .nu-chip, .search .az, .hlx, .fac.                      */
  :root{
    --chanfro:13px;                       /* profundidade do corte usinado */
    --fac-h:205;                          /* matiz da faceta — ir() reescreve por aba */
    --fac:oklch(0.80 0.135 var(--fac-h));         /* a cor da faceta ativa */
    --fac-d:oklch(0.62 0.115 var(--fac-h));       /* a mesma, rebaixada: traço e régua */
    --fac-soft:oklch(0.80 0.135 var(--fac-h)/.14);/* véu — nunca atrás de texto */
    --kyber:oklch(0.985 0.012 var(--fac-h));      /* núcleo branco-quente do sabre */
  }
  /* a camada da faceta: decoração pura, sem texto, sem clique, sem leitor de tela */
  .fac{position:absolute;inset:0;border-radius:inherit;pointer-events:none;
    z-index:0;overflow:hidden}
  .card>.fac,.cover>.fac,.leitura>.fac{opacity:.9}
  /* o CHANFRO pintado: duas diagonais de 1px nos cantos opostos. Custo zero de
     camada — nem clip-path nem filter, que se multiplicariam por 40 cards na tela. */
  .card>.fac::before{content:"";position:absolute;inset:0;
    background:
      linear-gradient(135deg,var(--fac-d) 0 1.5px,transparent 1.5px) top left/var(--chanfro) var(--chanfro) no-repeat,
      linear-gradient(315deg,var(--fac-d) 0 1.5px,transparent 1.5px) bottom right/var(--chanfro) var(--chanfro) no-repeat;
    opacity:.55;transition:opacity .22s cubic-bezier(.2,.7,.2,1)}
  .card:hover>.fac::before{opacity:1}
  /* o corte de verdade só onde há ÁREA para ele ler como usinagem (lei do v12.3,
     estendida do cantoneira ao chanfro). Numa peça de 90×36 o corte come o rótulo. */
  .cover,.sheet,#holofeed,.card.hl{
    clip-path:polygon(var(--chanfro) 0,100% 0,100% calc(100% - var(--chanfro)),
                      calc(100% - var(--chanfro)) 100%,0 100%,0 var(--chanfro))}
  /* clip-path corta box-shadow: quem é cortado troca a elevação por drop-shadow,
     que segue o recorte. Só nestas quatro peças — não se multiplica. */
  .cover,.sheet,#holofeed,.card.hl{filter:drop-shadow(0 10px 26px oklch(0 0 0/.5))}
  /* MOLDURA QUE SE DESENHA (idioma Arwes): quatro traços em L crescem do canto.
     background-size é pintura; nada aqui toca width/height. */
  .card>.fac::after,.cover>.fac::after{content:"";position:absolute;inset:0;
    background:
      linear-gradient(90deg,var(--fac),transparent) top left/0 1px no-repeat,
      linear-gradient(0deg,var(--fac),transparent) top left/1px 0 no-repeat,
      linear-gradient(270deg,var(--fac),transparent) bottom right/0 1px no-repeat,
      linear-gradient(180deg,var(--fac),transparent) bottom right/1px 0 no-repeat;
    opacity:.75;animation:facTracar .5s cubic-bezier(.2,.7,.2,1) both;
    animation-delay:calc(var(--d,0ms) + 90ms)}
  @keyframes facTracar{
    from{background-size:0 1px,1px 0,0 1px,1px 0}
    to{background-size:34% 1px,1px 34%,34% 1px,1px 34%}}
  /* menos movimento: o traço já nasce desenhado — a estética fica, o gesto sai */
  @media (prefers-reduced-motion:reduce){
    .card>.fac::after,.cover>.fac::after{animation:none;
      background-size:34% 1px,1px 34%,34% 1px,1px 34%}}
```

- [ ] **Step 2: Injetar o `.fac` — o gêmeo de `holografar`**

No `<script>`, logo após a função `holografar` (linha 1704):

```javascript
/* ═══ FACETA — a camada v14 de todo contêiner de dado ═══════════════════════════
   Mesmo padrão provado do `holografar` do v12.3, e pelas mesmas três razões:
   elemento REAL (os pseudos do .card estão ocupados desde o v7/v8), `aria-hidden`
   + `pointer-events:none` (é decoração: não fala com leitor de tela nem rouba
   clique) e marca própria para nunca duplicar. O `--d` herda a cascata de entrada
   que o `vivo()` já escreve, então a moldura se desenha DEPOIS do card subir. */
const FAC_SEL='.card,.cover,.sheet,.leitura';
function facetar(root){
  const alvo=root||document; let els;
  try{els=alvo.querySelectorAll(FAC_SEL);}catch(_){return;}
  els.forEach(el=>{
    if(el.dataset.fac)return;
    el.dataset.fac='1';
    const i=document.createElement('i');
    i.className='fac';i.setAttribute('aria-hidden','true');
    el.insertBefore(i,el.firstChild);
  });
}
```

E acrescentar a chamada dentro de `holografar`, no fim do corpo da função (depois do
`els.forEach(...)`), para que o `MutationObserver` que já existe cubra as duas camadas:

```javascript
  facetar(root);
```

- [ ] **Step 3: Provar que o `.fac` existe e não fala com leitor de tela**

```bash
systemctl --user restart jfn && sleep 25
.venv/bin/python tools/auditar_layout.py g_radar 1440 | tail -20
```
Expected: 0 violações — o `.fac` é `inset:0` sobre o pai, então não pode sobrepor irmão nem
vazar do pai. Se o auditor acusar vazamento, **o `.fac` não é o culpado: pare e leia quem corta**
(o auditor da 1ª geração gritou lobo exatamente aqui).

- [ ] **Step 4: Perguntar ao elemento, não a si mesmo**

```bash
.venv/bin/python - <<'PY'
import json, time, websocket, requests
ws=websocket.create_connection(json.loads(requests.get("http://127.0.0.1:9222/json").text)[0]["webSocketDebuggerUrl"],suppress_origin=True)
i=[0]
def cmd(m,p=None):
    i[0]+=1; ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
    while True:
        r=json.loads(ws.recv())
        if r.get("id")==i[0]: return r
cmd("Network.enable"); cmd("Network.setCacheDisabled",{"cacheDisabled":True})
cmd("Page.navigate",{"url":"http://127.0.0.1:8000/painel"}); time.sleep(7)
def js(e): return cmd("Runtime.evaluate",{"expression":e,"returnByValue":True})["result"]["result"].get("value")
js("ir('g_radar')"); time.sleep(2)
print("cards com .fac :",js("document.querySelectorAll('.card>.fac').length"))
print("duplicados     :",js("[...document.querySelectorAll('.card')].filter(c=>c.querySelectorAll(':scope>.fac').length>1).length"))
print("position do fac:",js("getComputedStyle(document.querySelector('.card>.fac')).position"))
print("--fac resolvido:",js("getComputedStyle(document.querySelector('.card')).getPropertyValue('--fac')"))
PY
```
Expected: contagem > 0 · duplicados `0` · position `absolute` · `--fac` resolvendo para um
`oklch(...)` com a matiz da aba. **Se `--fac` vier vazio, o problema é de PARSE, não de valor** —
procure fecha-comentário órfão antes de mexer em qualquer número.

- [ ] **Step 5: Travar as regras novas contra sumiço**

Acrescentar ao dicionário `obrigatorias` de `tests/test_painel_css_integro.py:80`:

```python
        # v14: a camada da faceta é onde toda decoração nova mora; se o seletor
        # sumir, as 51 assinaturas somem juntas e nada avisa
        "camada .fac declarada": ".fac{position:absolute;inset:0" in css,
        "chanfro pintado no card": ".card>.fac::before{" in css,
        "moldura que se desenha": "@keyframes facTracar{" in css,
```

- [ ] **Step 6: Rodar os testes**

Run: `.venv/bin/python -m pytest tests/test_painel_css_integro.py tests/test_painel_assinaturas.py -q`
Expected: 8 passed

- [ ] **Step 7: Commit**

```bash
git add static/jfn-painel.html tests/test_painel_css_integro.py
git commit -m "feat(painel): v14 tokens do cristal, chanfro pintado e moldura que se desenha"
```

---

## Task 4: Botões e controles — ignição, íon, fantasma

Hoje `.btn` é laranja para todo mundo (linha 649) e `.chip` é uma pílula de borda (linha 498). O
v14 dá aos três papéis um corpo diferente: **ignição** dispara ação, **íon** navega, **fantasma**
é reversível. A diferença não é decorativa — é a leitura de "isto muda o mundo" versus "isto só
me leva a outro lugar".

**Files:**
- Modify: `static/jfn-painel.html` (CSS ao fim do bloco v14)

**Interfaces:**
- Consumes: `--fac`, `--kyber` (Tarefa 3); `.hlx` (v12.3, já existente).
- Produces: classes `.btn.ign`, `.btn.ion`, `.btn.ghost` (esta já existe e ganha corpo novo).

- [ ] **Step 1: Escrever as três vozes**

```css
  /* ── v14: três vozes de botão. Não é decoração — é a diferença entre "isto muda
     o mundo" (ignição), "isto me leva a outro lugar" (íon) e "isto é reversível"
     (fantasma). O corpo do sabre entra na ESPESSURA, como no v13: núcleo branco
     entre 38% e 62%, nunca uma barra colorida com brilho por fora.              */
  .btn.ign,.btn:not(.ghost):not(.ion){
    background:linear-gradient(180deg,
      color-mix(in oklch,var(--flame) 88%,white 12%) 0 36%,
      color-mix(in oklch,var(--kyber) 60%,var(--flame) 40%) 44% 56%,
      color-mix(in oklch,var(--flame-d) 92%,black 8%) 64% 100%);
    color:oklch(0.16 0.04 60);text-shadow:none}
  .btn.ion{
    background:linear-gradient(180deg,
      color-mix(in oklch,var(--fac) 82%,white 18%) 0 36%,
      color-mix(in oklch,var(--kyber) 55%,var(--fac) 45%) 44% 56%,
      color-mix(in oklch,var(--fac-d) 92%,black 8%) 64% 100%);
    color:oklch(0.16 0.04 var(--fac-h))}
  .btn.ghost{background:transparent;color:var(--tx2);
    box-shadow:inset 0 0 0 1px color-mix(in oklch,var(--fac) 34%,transparent)}
  .btn.ghost:hover{color:var(--tx);
    box-shadow:inset 0 0 0 1px var(--fac),0 0 18px -6px var(--fac)}
  /* a CARGA na base: o botão acumula energia enquanto o cursor está nele e a
     descarrega no clique. background-position é pintura — nada de width. */
  .btn>.hlx::after{content:"";position:absolute;left:8%;right:8%;bottom:2px;height:1.5px;
    border-radius:2px;background:linear-gradient(90deg,transparent,var(--kyber),transparent);
    background-size:0% 100%;background-repeat:no-repeat;background-position:50% 0;
    transition:background-size .34s cubic-bezier(.2,.7,.2,1)}
  .btn:hover>.hlx::after{background-size:100% 100%}
  .btn:active{transform:scale(.975)}   /* ease-out-quart; bounce é banido desde o v10 */
  /* chip ativo ganha o pé de sabre da faceta, no mesmo idioma da esfera ativa (v13) */
  .chip.on{color:var(--tx);border-color:color-mix(in oklch,var(--fac) 55%,transparent)}
  .chip.on>.hlx::before{content:"";position:absolute;left:22%;right:22%;bottom:-1px;height:2px;
    border-radius:2px;background:linear-gradient(180deg,var(--kyber) 38% 62%,var(--fac));
    box-shadow:0 0 6px var(--fac),0 0 14px color-mix(in oklch,var(--fac) 60%,transparent)}
  @media (prefers-reduced-motion:reduce){
    .btn>.hlx::after{transition:none;background-size:100% 100%;opacity:.5}}
```

- [ ] **Step 2: Não deixar o botão primário virar laranja sem sentido**

`btnPdf` (linha 1480) já usa `.ghost`. Trocar apenas os disparos de ação real para `.ign` e as
navegações para `.ion`. Localizar e ajustar em `renderAcoes` e `sweep`:

```bash
grep -n "class=\"btn" static/jfn-painel.html | head -30
```

Regra de decisão, para não virar gosto: **`.ign`** = chamada que escreve (`/api/sweeps/*`,
`/api/acoes/*`, gerar dossiê); **`.ion`** = `ir(...)`, abrir dossiê, trocar recorte;
**`.ghost`** = tudo que é reversível ou secundário (PDF, filtro, voltar).

- [ ] **Step 3: Medir contraste, que é onde botão colorido costuma quebrar**

```bash
systemctl --user restart jfn && sleep 25
.venv/bin/python tools/auditar_contraste.py g_acoes 2>/dev/null || .venv/bin/python tools/auditar_contraste.py
```
Expected: 0 violações e 0 não medidos. Se a tinta do `.ion` ficar abaixo de 4,5:1 sobre a faceta
clara (matiz 85, Prefeitura, é a arriscada), **escurecer a tinta, não clarear o fundo** — clarear
o fundo apaga a diferença entre as três vozes.

- [ ] **Step 4: Medir alvo de toque a 390px**

```bash
.venv/bin/python tools/auditar_layout.py g_acoes 390 | tail -20
```
Expected: 0 `alvo_viola_norma`.

- [ ] **Step 5: Commit**

```bash
git add static/jfn-painel.html
git commit -m "feat(painel): v14 tres vozes de botao (ignicao/ion/fantasma) com carga na base"
```

---

## Task 5: A capa da aba — selo, lema, régua-sabre e cena

`cover()` (linha 1477) hoje entrega eyebrow + título + leitura. A capa é o primeiro contato com a
aba e é onde a assinatura tem que aparecer. Ela passa a estampar o **glifo da faceta**, o **lema**
e uma **cena procedural** — SVG desenhado a partir de `inst`, custo zero de byte.

**Files:**
- Modify: `static/jfn-painel.html` (helper `cover`, linha 1477; CSS ao fim do bloco v14)

**Interfaces:**
- Consumes: `ASSINATURA` (Tarefa 2), `--fac`/`.fac` (Tarefa 3).
- Produces: `cover(sph,t,s,ic)` com a mesma assinatura de hoje — **nenhuma das 51 funções de
  render muda**; a capa se enriquece sozinha lendo `ASSINATURA[aba]`.

- [ ] **Step 1: Enriquecer o helper sem mudar sua assinatura**

Substituir a linha 1477 por:

```javascript
/* v14: a capa passa a carregar a assinatura da faceta — glifo, lema e cena.
   A assinatura da FUNÇÃO não muda: as 51 funções de render continuam chamando
   cover(sph,t,s,ic) sem saber de nada. É por isso que o v14 alcança tudo sem 51
   edições — a identidade vem da tabela, não do chamador. */
const _cena=inst=>({
  fila:'<path d="M2 6h44M2 13h34M2 20h22M2 27h12"/>',
  rede:'<circle cx="10" cy="8" r="2.6"/><circle cx="34" cy="6" r="2.6"/><circle cx="22" cy="20" r="2.6"/><circle cx="44" cy="22" r="2.6"/><path d="M10 8 22 20M34 6 22 20M22 20 44 22"/>',
  tempo:'<path d="M2 26h46"/><path d="M8 26V14M18 26V8M28 26V18M38 26V5"/>',
  moeda:'<path d="M2 28 12 20 22 24 32 10 46 4"/><path d="M2 28h44"/>',
  mapa:'<path d="M4 6 16 10 30 4 46 9v18L30 22 16 28 4 24z"/><path d="M16 10v18M30 4v18"/>',
  pessoa:'<circle cx="12" cy="9" r="4"/><path d="M4 26c0-5 4-8 8-8s8 3 8 8"/><circle cx="34" cy="9" r="4"/><path d="M26 26c0-5 4-8 8-8s8 3 8 8"/>',
}[inst]||'');
const cover=(sph,t,s,ic)=>{const a=ASSINATURA[aba]||{};
  const g=svgIco(a.gl||ic||''),cn=_cena(a.inst||'mapa');
  return `<div class="cover ${sph}"><div class="cover-row">${g?`<span class="cover-seal" aria-hidden="true">${g}</span>`:''}<div class="cover-tx"><div class="t">${t}</div><div class="s">${s}</div>${a.lema?`<div class="lema">${esc(a.lema)}</div>`:''}</div>${cn?`<svg class="cover-cena" viewBox="0 0 48 32" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" aria-hidden="true">${cn}</svg>`:''}</div></div>`;};
```

- [ ] **Step 2: Vestir a capa**

```css
  /* ── v14: a capa da aba anuncia a faceta ─────────────────────────────────── */
  .cover .lema{color:var(--fac);font-family:var(--mono);font-size:11px;letter-spacing:.4px;
    margin-top:7px;opacity:.92}
  .cover-cena{margin-left:auto;width:96px;height:64px;flex:0 0 auto;color:var(--fac);
    opacity:.34;align-self:center}
  .cover-row{display:flex;align-items:flex-start;gap:12px}
  /* a régua da capa já é lâmina desde o v13 (.cover::before) — aqui ela só passa a
     falar a matiz da FACETA em vez da esfera. Uma variável, não uma regra nova. */
  .cover::before{background:linear-gradient(180deg,
    color-mix(in oklch,var(--fac) 55%,transparent) 0 30%,
    var(--kyber) 38% 62%,
    color-mix(in oklch,var(--fac) 55%,transparent) 70% 100%)}
  /* o selo do glifo pulsa na matiz da faceta — SÓ o selo, que é onde o olho pousa.
     Glow em tudo = glow em nada; é o erro nº 1 do gênero. */
  .cover-seal{color:var(--fac);
    box-shadow:0 0 0 1px color-mix(in oklch,var(--fac) 40%,transparent),
               0 0 22px -8px var(--fac)}
  @media (max-width:600px){.cover-cena{display:none}}   /* rouba largura do título */
```

- [ ] **Step 3: Ver com olho humano, em quatro facetas de esferas diferentes**

```bash
systemctl --user restart jfn && sleep 25
for a in i_cockpit e_fenix p_fant g_radar; do
  .venv/bin/python tools/auditar_layout.py $a 1440 | tail -3
done
```
Expected: 0 violações em cada. **`e_fenix` não existe** — é `g_fenix`; se o auditor reclamar de
aba desconhecida, é o comportamento certo (a lista vem do painel).

- [ ] **Step 4: Confirmar que o lema não trunca a 390px**

```bash
.venv/bin/python tools/auditar_layout.py g_capital 390 | grep -i trunc
```
Expected: nenhuma linha. `g_capital` tem o lema mais longo do registro — é o pior caso de propósito.

- [ ] **Step 5: Contraste do lema (11px sobre superfície é onde some)**

```bash
.venv/bin/python tools/auditar_contraste.py | tail -10
```
Expected: 0 violações. Rótulo ≤11px exige `--dim-sm`; se o lema em matiz 85 (Prefeitura) cair
abaixo de 4,5:1, subir a luminosidade do `--fac` **só para o lema**, não para a faceta inteira.

- [ ] **Step 6: Commit**

```bash
git add static/jfn-painel.html
git commit -m "feat(painel): v14 capa da aba com selo, lema e cena procedural por faceta"
```

---

## Task 6: O KPI vira instrumento

`kpi()` (linha 1472) é um card com rótulo e número. Vira **leitura de instrumento**: régua de
escala na base, glifo de severidade que já existe, e o número no núcleo branco-quente quando é
dinheiro. Nada de dado inventado — a régua é escala, não valor.

**Files:**
- Modify: `static/jfn-painel.html` (CSS ao fim do bloco v14)

**Interfaces:**
- Consumes: `.fac` (Tarefa 3), `_kpiIco` (linha 1467, existente).
- Produces: nenhuma API nova — `kpi(v,l,cor,gl,dest)` continua idêntico.

- [ ] **Step 1: Vestir o KPI**

```css
  /* ── v14: o KPI deixa de ser um número num quadro e vira leitura de instrumento.
     A régua da base é ESCALA, não valor — não afirma nada sobre o dado, e por isso
     pode existir mesmo quando o número é INDISPONÍVEL.                          */
  .kpi>.fac::after{background:none}          /* o KPI não recebe a moldura traçada:
     é peça pequena e o traço competiria com o número. A lei do v12.3 outra vez. */
  .kpi>.fac{background:
    repeating-linear-gradient(90deg,
      color-mix(in oklch,var(--fac) 42%,transparent) 0 1px,
      transparent 1px 11px) bottom left/100% 5px no-repeat;
    opacity:.5;transition:opacity .25s}
  .kpi:hover>.fac{opacity:.95}
  /* número de DINHEIRO ganha o núcleo do sabre — dinheiro é a moeda do painel */
  .kpi .v{text-shadow:0 0 18px color-mix(in oklch,currentColor 28%,transparent)}
  .kpi .kpi-ico{opacity:.55;transition:opacity .2s,transform .25s cubic-bezier(.2,.7,.2,1)}
  .kpi:hover .kpi-ico{opacity:1;transform:translateY(-1px) scale(1.06)}
  /* o KPI clicável (kpi-go) anuncia o destino com um chanfro aceso, não com sublinhado */
  .kpi-go>.fac::before{opacity:.95}
  .kpi-go:hover{cursor:pointer}
  @media (prefers-reduced-motion:reduce){
    .kpi>.fac{transition:none}.kpi .kpi-ico{transition:none}}
```

- [ ] **Step 2: Provar que a régua não passa por trás de texto**

Esta é a armadilha exata que produziu o laudo de 1,02:1. A régua vive no `.fac`, que está **atrás**
do conteúdo — mas o auditor mede a pilha de fundo computada. Confirmar:

```bash
systemctl --user restart jfn && sleep 25
.venv/bin/python tools/auditar_contraste.py | grep -iE "violac|nao medid" | tail -5
```
Expected: `0 violações` e `0 não medidos`. **Se aparecer violação num `.kpi .l` ou `.kpi .v`, a
cura não é ensinar o auditor a ignorar — é baixar a régua para fora da caixa do texto** (a régua
tem 5px; o `.v` começa 7px abaixo do `.l`; há espaço).

- [ ] **Step 3: Medir o custo — 4+4 KPIs por aba, é onde o desenho se multiplica**

```bash
.venv/bin/python tools/medir_quadro.py e_panorama    # criado na Tarefa 13
```
Se `tools/medir_quadro.py` ainda não existir nesta ordem de execução, adiar este passo para a
Tarefa 13 e **anotar no commit** que a medição ficou pendente — não afirmar que está barato.

- [ ] **Step 4: Commit**

```bash
git add static/jfn-painel.html
git commit -m "feat(painel): v14 KPI como leitura de instrumento (regua de escala + nucleo)"
```

---

## Task 7: Tabela e lista viram leitura de sensor

A cascata de entrada (`--li`), a varredura no cursor e o medidor grave já chegaram no v13. O que
falta é a **coluna se identificar**: cada `<th>` ganha um glifo mudo de tipo (texto, dinheiro,
data, score), injetado por JS — porque os 51 renders escrevem `<th>` cru e não vale editar 51.

**Files:**
- Modify: `static/jfn-painel.html` (JS: nova função `instrumentar`, chamada em `vivo()`, linha 1743; CSS ao fim do bloco v14)

**Interfaces:**
- Consumes: `vivo()` (linha 1743).
- Produces: `instrumentar(root)` — idempotente, marca `data-inst` no `<th>`.

- [ ] **Step 1: Escrever a instrumentação**

Logo antes de `function _countUp` (linha 1763):

```javascript
/* ═══ INSTRUMENTAR — cada coluna diz que TIPO de coisa ela mede ═══════════════════
   Os 51 renders escrevem `<th>` cru; editar 51 para pôr um ícone seria 51 chances de
   errar. Aqui o tipo é DEDUZIDO do rótulo, uma vez por render, e vira um glifo mudo.
   Deduzir do rótulo é frágil de propósito: quando não reconhece, não põe nada — a
   coluna fica como está hoje. Falha para o lado de não afirmar. */
const _TIPO_COL=[
  [/valor|R\$|pago|total|montante|preço|preco/i,'moeda'],
  [/data|período|periodo|emissão|emissao|vigência|vigencia|ano|mês|mes/i,'tempo'],
  [/score|risco|grau|nota|indício|indicio/i,'grau'],
  [/cnpj|cpf|processo|nº|numero|número/i,'chave'],
];
function instrumentar(root){
  (root||document).querySelectorAll('thead th:not([data-inst])').forEach(th=>{
    const rot=(th.textContent||'').trim();
    const achou=_TIPO_COL.find(([re])=>re.test(rot));
    th.dataset.inst=achou?achou[1]:'';
  });
}
```

E dentro de `vivo()`, logo após a linha `const top=[...]` (linha 1746), acrescentar:

```javascript
  instrumentar(v);   // v14: a coluna se identifica antes da cascata começar
```

- [ ] **Step 2: Vestir a coluna**

```css
  /* ── v14: a coluna diz o que mede. Glifo em ::before do TH — o th carrega texto,
     então isto é `content`, não `background-image`: a lei proíbe decorar o FUNDO
     de quem tem texto, não pôr um caractere antes dele.                          */
  thead th[data-inst]::before{margin-right:5px;opacity:.6;font-weight:400}
  thead th[data-inst="moeda"]::before{content:"◈"}
  thead th[data-inst="tempo"]::before{content:"◷"}
  thead th[data-inst="grau"]::before{content:"⌁"}
  thead th[data-inst="chave"]::before{content:"⌗"}
  thead th[data-inst=""]::before{content:none}
  /* a linha sob o cabeçalho passa a falar a matiz da faceta (a regra já existe
     desde o v10.1 — aqui só troca a fonte da cor, sem regra nova) */
  thead::after{background:linear-gradient(90deg,transparent,var(--fac),transparent)}
  /* lista paginada: o botão "carregar mais" ganha a voz fantasma da Tarefa 4 e a
     contagem do que FALTA — silêncio sobre o resto era o que fazia parecer cap fixo */
  .pag-mais{color:var(--fac)}
```

- [ ] **Step 3: Verificar que o glifo não estragou o alinhamento numérico**

`thead th` é `text-align:right` exceto a primeira (linha 438-439). O `::before` entra **antes** do
texto, então numa coluna à direita ele fica colado no rótulo, não na borda — correto.

```bash
systemctl --user restart jfn && sleep 25
.venv/bin/python tools/auditar_layout.py g_radar 1440 | tail -5
.venv/bin/python tools/auditar_layout.py g_radar 390  | tail -5
```
Expected: 0 violações nas duas larguras. A 390px a tabela rola na horizontal e o SCORE fica
grudado à direita (v13) — confirmar que continua grudado.

- [ ] **Step 4: Confirmar no DOM vivo que a dedução acertou**

```bash
.venv/bin/python - <<'PY'
import json, time, websocket, requests
ws=websocket.create_connection(json.loads(requests.get("http://127.0.0.1:9222/json").text)[0]["webSocketDebuggerUrl"],suppress_origin=True)
i=[0]
def cmd(m,p=None):
    i[0]+=1; ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
    while True:
        r=json.loads(ws.recv())
        if r.get("id")==i[0]: return r
cmd("Network.enable"); cmd("Network.setCacheDisabled",{"cacheDisabled":True})
cmd("Page.navigate",{"url":"http://127.0.0.1:8000/painel"}); time.sleep(7)
def js(e): return cmd("Runtime.evaluate",{"expression":e,"returnByValue":True})["result"]["result"].get("value")
js("ir('g_radar')"); time.sleep(2)
print(js("[...document.querySelectorAll('thead th')].map(t=>t.textContent.trim()+' -> '+(t.dataset.inst||'(nenhum)')).join('\\n')"))
PY
```
Expected: colunas de valor marcadas `moeda`, score marcado `grau`, o resto vazio. **Coluna
marcada errado é pior que não marcada** — se acontecer, apertar a expressão regular, não afrouxar.

- [ ] **Step 5: Commit**

```bash
git add static/jfn-painel.html
git commit -m "feat(painel): v14 coluna de tabela se identifica por tipo, deduzido do rotulo"
```

---

## Task 8: Abas e esferas como facetas do cristal

A barra inferior tem 51 botões em quatro grupos. Ela já é um deck 3D com sublinhado-sabre (v13). O
v14 dá a cada botão a **matiz da sua própria faceta** quando ativo, e à faixa uma leitura de
cristal — sem tocar em `left/top/width`, que é o que a barra não perdoa.

**Files:**
- Modify: `static/jfn-painel.html` (`montarTabs`, linha 1648; CSS ao fim do bloco v14)

**Interfaces:**
- Consumes: `ASSINATURA`, `_ESF_MATIZ` (Tarefa 2).
- Produces: atributo `style="--tab-h:<grau>"` em cada `<button>` da nav.

- [ ] **Step 1: Cada botão de aba carrega a própria matiz**

Substituir a linha 1650 (dentro de `montarTabs`):

```javascript
  $('tabs').innerHTML=TABS[esfera].map(t=>{
    /* v14: o botão carrega a matiz da SUA faceta — assim a barra inteira lê como
       um cristal com 14 lados, e não como 14 cópias da cor da esfera. */
    const h=(_ESF_MATIZ[esfera]||205)+((ASSINATURA[t.id]||{}).h||0);
    return `<button class="${t.id===aba?'on':''}" style="--tab-h:${h}" onclick="ir('${t.id}')" title="${t.tl}"><span class="ti">${svgIco(t.ic)}</span><span class="tl">${t.tl}</span></button>`;
  }).join('');
```

- [ ] **Step 2: Vestir a barra**

```css
  /* ── v14: a barra de abas é a borda do cristal — cada botão uma faceta ────── */
  nav.tabs button{--tf:oklch(0.80 0.135 var(--tab-h,205))}
  nav.tabs button:hover .ti .jico{filter:drop-shadow(0 0 6px color-mix(in oklch,var(--tf) 60%,transparent))}
  nav.tabs button.on .ti .jico{filter:drop-shadow(0 0 8px var(--tf))}
  /* o sublinhado-sabre do v13 passa a acender na matiz da faceta. A regra do v13
     continua intacta; aqui só se troca a fonte da cor — nenhuma animação é
     redeclarada (redeclarar `animation:` apaga a de baixo em silêncio). */
  nav.tabs button.on::after{background:linear-gradient(180deg,
    color-mix(in oklch,var(--tf) 50%,transparent) 0 30%,
    var(--kyber) 38% 62%,
    color-mix(in oklch,var(--tf) 50%,transparent) 70% 100%);
    box-shadow:0 0 7px var(--tf),0 0 16px color-mix(in oklch,var(--tf) 55%,transparent)}
  /* a esfera ativa: o pé de sabre do v13 passa a somar a matiz da faceta corrente,
     de modo que trocar de aba move a luz DENTRO da face — é o gesto do holocron */
  .sph.on::after{transition:background .45s cubic-bezier(.2,.7,.2,1)}
  @media (prefers-reduced-motion:reduce){.sph.on::after{transition:none}}
```

- [ ] **Step 3: A armadilha que já mordeu duas vezes — conferir a 390px**

As quatro esferas se sobrepunham no celular com `flex:1;min-width:0`; a cura foi `flex:0 0 auto`
(travada em teste). **Nada nesta tarefa toca `flex`.** Confirmar mesmo assim:

```bash
systemctl --user restart jfn && sleep 25
.venv/bin/python tools/auditar_layout.py i_cockpit 390 | grep -iE "sobrep|vaz" | head
.venv/bin/python -m pytest tests/test_painel_css_integro.py -q
```
Expected: nenhuma sobreposição · 3 passed (o teste de presença nominal cobre `flex:0 0 auto`).

- [ ] **Step 4: Ver a barra inteira, não uma aba**

```bash
.venv/bin/python - <<'PY'
import json, time, websocket, requests
ws=websocket.create_connection(json.loads(requests.get("http://127.0.0.1:9222/json").text)[0]["webSocketDebuggerUrl"],suppress_origin=True)
i=[0]
def cmd(m,p=None):
    i[0]+=1; ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
    while True:
        r=json.loads(ws.recv())
        if r.get("id")==i[0]: return r
cmd("Network.enable"); cmd("Network.setCacheDisabled",{"cacheDisabled":True})
cmd("Page.navigate",{"url":"http://127.0.0.1:8000/painel"}); time.sleep(7)
def js(e): return cmd("Runtime.evaluate",{"expression":e,"returnByValue":True})["result"]["result"].get("value")
js("trocarEsfera('geral')"); time.sleep(3)
print("matizes distintas na barra:",js("new Set([...document.querySelectorAll('nav.tabs button')].map(b=>b.style.getPropertyValue('--tab-h'))).size"))
print("botoes na barra          :",js("document.querySelectorAll('nav.tabs button').length"))
PY
```
Expected: 22 botões e ao menos 18 matizes distintas (algumas assinaturas compartilham delta de
propósito — `e_conluio`/`g_conluio` são a mesma leitura).

- [ ] **Step 5: Commit**

```bash
git add static/jfn-painel.html
git commit -m "feat(painel): v14 barra de abas com a matiz de cada faceta"
```

---

## Task 9: A ignição da faceta — o painel fica vivo ao trocar de aba

Hoje trocar de aba faz um crossfade (`.fade`) e a cascata do `vivo()`. O v14 acrescenta o gesto
que dá nome ao conceito: ao entrar, a faceta **acende do centro para fora** e o conteúdo assenta.
Duração curta, `ease-out-quart`, e **só pintura**.

**Files:**
- Modify: `static/jfn-painel.html` (CSS ao fim do bloco v14; `ir()` linha 1664)

**Interfaces:**
- Consumes: `body[data-aba]`, `--fac` (Tarefas 2–3).
- Produces: classe `.ignicao` em `#view` por 620 ms.

- [ ] **Step 1: Disparar a ignição em `ir()`**

Substituir a linha 1664 (`try{const html=await t.render(); ...}`) por:

```javascript
  try{const html=await t.render();if(meu!==_nav)return;
    v.innerHTML=`<div class="fade">${html}</div>`;
    /* v14: a faceta acende. Classe efêmera para a animação poder repetir a cada
       troca — sem isto o navegador reusa o estado final e o gesto só acontece
       uma vez por carregamento. */
    v.classList.remove('ignicao');void v.offsetWidth;v.classList.add('ignicao');
    setTimeout(()=>v.classList.remove('ignicao'),620);}
```

- [ ] **Step 2: Desenhar a ignição**

```css
  /* ── v14: IGNIÇÃO DA FACETA. Uma frente de luz atravessa o conteúdo de cima a
     baixo quando a aba entra. É `background-position` num elemento que a própria
     regra cria — pintura pura, nada de layout, e ela se apaga sozinha em 620ms.  */
  #view{position:relative}
  #view.ignicao::before{content:"";position:absolute;inset:-8px 0 0;pointer-events:none;
    z-index:3;background:linear-gradient(180deg,
      transparent 0 42%,
      color-mix(in oklch,var(--kyber) 70%,transparent) 47% 53%,
      color-mix(in oklch,var(--fac) 45%,transparent) 55% 60%,
      transparent 62% 100%);
    background-size:100% 260%;background-repeat:no-repeat;
    animation:facIgnicao .62s cubic-bezier(.2,.7,.2,1) both;
    mix-blend-mode:screen;opacity:.5}
  @keyframes facIgnicao{
    from{background-position:0 -140%;opacity:.62}
    to{background-position:0 240%;opacity:0}}
  /* quem pediu menos movimento não recebe a frente de luz — mas a faceta continua
     acesa em tudo que é estático. A estética fica; o gesto sai. É a lei do v13. */
  @media (prefers-reduced-motion:reduce){#view.ignicao::before{display:none}}
```

- [ ] **Step 3: Provar que a ignição não fica presa na tela**

O risco real: `mix-blend-mode:screen` com `opacity` residual cobrindo o conteúdo. Perguntar ao
elemento:

```bash
systemctl --user restart jfn && sleep 25
.venv/bin/python - <<'PY'
import json, time, websocket, requests
ws=websocket.create_connection(json.loads(requests.get("http://127.0.0.1:9222/json").text)[0]["webSocketDebuggerUrl"],suppress_origin=True)
i=[0]
def cmd(m,p=None):
    i[0]+=1; ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
    while True:
        r=json.loads(ws.recv())
        if r.get("id")==i[0]: return r
cmd("Network.enable"); cmd("Network.setCacheDisabled",{"cacheDisabled":True})
cmd("Page.navigate",{"url":"http://127.0.0.1:8000/painel"}); time.sleep(7)
def js(e): return cmd("Runtime.evaluate",{"expression":e,"returnByValue":True})["result"]["result"].get("value")
js("ir('g_radar')"); time.sleep(1.5)
print("durante  :",js("$('view').classList.contains('ignicao')"))
time.sleep(1.5)
print("depois   :",js("$('view').classList.contains('ignicao')"))
PY
```
Expected: `durante: True` (ou já False se a captura demorou) e **`depois: False`**. Se ficar
`True`, o `setTimeout` não rodou — a classe presa cobre o conteúdo com uma película e é
exatamente o tipo de defeito que "está bonito" não pega.

- [ ] **Step 4: Confirmar que reduced-motion não deixa a tela em branco**

`prefers-reduced-motion` já deixou a mesa **em branco** uma vez — é o teste que mais vale aqui.

```bash
.venv/bin/python tools/auditar_contraste.py 2>&1 | tail -4
```
E a variante:

```bash
.venv/bin/python - <<'PY'
import json, time, websocket, requests
ws=websocket.create_connection(json.loads(requests.get("http://127.0.0.1:9222/json").text)[0]["webSocketDebuggerUrl"],suppress_origin=True)
i=[0]
def cmd(m,p=None):
    i[0]+=1; ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
    while True:
        r=json.loads(ws.recv())
        if r.get("id")==i[0]: return r
cmd("Network.enable"); cmd("Network.setCacheDisabled",{"cacheDisabled":True})
cmd("Emulation.setEmulatedMedia",{"features":[{"name":"prefers-reduced-motion","value":"reduce"}]})
cmd("Page.navigate",{"url":"http://127.0.0.1:8000/painel"}); time.sleep(7)
def js(e): return cmd("Runtime.evaluate",{"expression":e,"returnByValue":True})["result"]["result"].get("value")
js("ir('e_panorama')"); time.sleep(2)
print("cards visiveis:",js("[...document.querySelectorAll('#view .card')].filter(c=>c.getBoundingClientRect().height>0).length"))
print("opacidade 1o  :",js("getComputedStyle(document.querySelector('#view .card')).opacity"))
PY
```
Expected: cards visíveis > 0 e opacidade `1`. **Zero card visível = a tela ficou em branco para
quem pediu menos movimento** — regressão grave, corrigir antes de seguir.

- [ ] **Step 5: Commit**

```bash
git add static/jfn-painel.html
git commit -m "feat(painel): v14 ignicao da faceta na troca de aba (pintura pura, 620ms)"
```

---

## Task 10: Estados honestos no idioma do holocron

Vazio, INDISPONÍVEL, erro e carregando são onde um painel bonito costuma mentir. `spin()` (linha
1476) é um esqueleto e `erroHumano()` já existe. O v14 dá aos quatro o mesmo idioma — e mantém a
distinção que a casa exige: **INDISPONÍVEL ≠ 0**, **silêncio ≠ INDISPONÍVEL**, **zero grave não é alarme**.

**Files:**
- Modify: `static/jfn-painel.html` (CSS ao fim do bloco v14)

**Interfaces:**
- Consumes: `.skel`, `.warn`, `.sp` (existentes).
- Produces: nenhuma API nova.

- [ ] **Step 1: Vestir os quatro estados**

```css
  /* ── v14: os quatro estados honestos falam o mesmo idioma ────────────────────
     Vazio ensina a tela · INDISPONÍVEL é estado, não zero · erro é humano, nunca
     um TypeError cru · carregando é o esqueleto do layout, nunca um giro no meio
     do conteúdo. A cor de cada um é semântica e não decorativa: INDISPONÍVEL usa
     a matiz da faceta (é ausência de dado, não gravidade); erro usa rosa.        */
  .skel{color:var(--mut)}
  .skel .sp{border-top-color:var(--fac)}
  .skel::after{content:"";display:block;height:1px;margin-top:10px;
    background:linear-gradient(90deg,transparent,var(--fac),transparent);
    background-size:38% 100%;background-repeat:no-repeat;
    animation:facVarrer 1.5s linear infinite}
  @keyframes facVarrer{from{background-position:-40% 0}to{background-position:140% 0}}
  .warn{border-left:2px solid var(--rose);
    box-shadow:inset 0 0 0 1px color-mix(in oklch,var(--rose) 22%,transparent)}
  /* INDISPONÍVEL nunca veste a cor de gravidade — não é achado, é ausência */
  .indisp,[data-estado="indisponivel"]{color:var(--fac);font-family:var(--mono);
    letter-spacing:.4px;opacity:.85}
  @media (prefers-reduced-motion:reduce){.skel::after{animation:none;background-size:100% 100%;opacity:.35}}
```

- [ ] **Step 2: Provar que o esqueleto não some para reduced-motion**

Sem a animação, `background-size:38%` deixaria uma barra parada de 38% — parece defeito. A regra
acima resolve; confirmar:

```bash
systemctl --user restart jfn && sleep 25
.venv/bin/python tools/auditar_contraste.py | tail -4
```
Expected: 0 violações e 0 não medidos.

- [ ] **Step 3: Ver um erro de verdade, não um simulado**

```bash
.venv/bin/python - <<'PY'
import json, time, websocket, requests
ws=websocket.create_connection(json.loads(requests.get("http://127.0.0.1:9222/json").text)[0]["webSocketDebuggerUrl"],suppress_origin=True)
i=[0]
def cmd(m,p=None):
    i[0]+=1; ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
    while True:
        r=json.loads(ws.recv())
        if r.get("id")==i[0]: return r
cmd("Network.enable"); cmd("Network.setCacheDisabled",{"cacheDisabled":True})
cmd("Page.navigate",{"url":"http://127.0.0.1:8000/painel"}); time.sleep(7)
def js(e): return cmd("Runtime.evaluate",{"expression":e,"returnByValue":True})["result"]["result"].get("value")
# rota que nao existe: o erro tem que virar frase humana, nunca TypeError
print(js("J('/api/rota_que_nao_existe').then(r=>JSON.stringify(r))"))
PY
```
Expected: um objeto com `erro` em português. **Se aparecer `TypeError` cru, é regressão do v10** —
`erroHumano()` deixou de ser chamado.

- [ ] **Step 4: Commit**

```bash
git add static/jfn-painel.html
git commit -m "feat(painel): v14 estados honestos (vazio/INDISPONIVEL/erro/carregando)"
```

---

## Task 11: Adobe Express — placas de face, key art e sistema de design

O Express é canvas **FIXO** e **recusa dashboard responsivo por contrato**. O que ele entrega bem:
selo, placa, key art e o documento de sistema de design. Esta tarefa produz os quatro selos de
face que o painel consome e o documento de referência do v14.

**Files:**
- Create: `docs/referencias/express/holocron-v14.html`
- Create: `static/assets/holocron-{inicio,estado,prefeitura,geral}.svg`
- Modify: `static/jfn-painel.html` (CSS: a placa entra no `.cover-seal` de cada esfera)

**Interfaces:**
- Consumes: paleta de `docs/referencias/express/ESPECIFICACAO.md`.
- Produces: quatro SVG em `static/assets/`, cada um ≤ 40 KB.

- [ ] **Step 1: Atualizar a especificação, que é o que o Express lê**

```bash
.venv/bin/python -m tools.express_ponte --spec
head -30 docs/referencias/express/ESPECIFICACAO.md
```
Expected: paleta com os HEX atuais (`--ion #59A3FF`, `--flame #FF8804`, …).

- [ ] **Step 2: Escrever a fonte HTML das duas folhas**

Criar `docs/referencias/express/holocron-v14.html` com **duas** `.slide` de 1920×1080:

- **Folha 1 — key art v14:** o holocron ao centro (quatro faces em SVG inline, cada uma na matiz
  da sua esfera), o sabre na base, e **quatro números reais** com data de apuração, lidos do
  `compliance.db` no momento de gerar. Nunca número inventado, nunca empenho apresentado como pago.
- **Folha 2 — sistema de design v14:** paleta HEX, matiz base por esfera, anatomia do chanfro
  (os dois cantos, com medida), anatomia da moldura que se desenha, as três vozes de botão, e as
  leis da casa em uma coluna.

**Restrições do importador, medidas na rodada anterior — respeitar ou a arte chega quebrada:**
- **desenhar em SVG inline, sem filtro** — camadas empilhadas com gradiente importam idênticas;
- o importador **perde gradiente repetido de fundo e pseudo-elementos `::before`**;
- IBM Plex está no Adobe Fonts, mas só alguns cortes pelo nome PostScript: use
  `IBMPlexSans-SemiBold`, `IBMPlexSans-Bold`, `IBMPlexMono-Medium`, `IBMPlexMono-SemiBold`.
  Os `-Regular` retornam `not_found`;
- **geração de imagem por IA não existe neste conector** (só `image_generative_expand`, que é
  outpainting) — arte fotográfica é da Tarefa 12.

- [ ] **Step 3: Provar que as folhas não transbordam ANTES de exportar**

O transbordamento do key-art anterior só apareceu porque um probe mediu; o olho tinha deixado
passar dois blocos.

```bash
.venv/bin/python - <<'PY'
import json, time, websocket, requests
ws=websocket.create_connection(json.loads(requests.get("http://127.0.0.1:9222/json").text)[0]["webSocketDebuggerUrl"],suppress_origin=True)
i=[0]
def cmd(m,p=None):
    i[0]+=1; ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
    while True:
        r=json.loads(ws.recv())
        if r.get("id")==i[0]: return r
cmd("Network.enable"); cmd("Network.setCacheDisabled",{"cacheDisabled":True})
cmd("Page.navigate",{"url":"file:///home/ubuntu/JFN/docs/referencias/express/holocron-v14.html"}); time.sleep(4)
def js(e): return cmd("Runtime.evaluate",{"expression":e,"returnByValue":True})["result"]["result"].get("value")
print(js("""[...document.querySelectorAll('.bloco')].map((b,i)=>{
  const vaza=[...b.children].some(c=>{const r=c.getBoundingClientRect(),p=b.getBoundingClientRect();
    return r.right>p.right+1||r.bottom>p.bottom+1||r.left<p.left-1;});
  return i+': rola='+(b.scrollHeight>b.clientHeight+1)+' vaza='+vaza;}).join('\\n')"""))
PY
```
Expected: `rola=false vaza=false` em **todos** os blocos. Qualquer `true` se corrige antes de
exportar — o importador não conserta layout.

- [ ] **Step 4: Exportar, na ordem obrigatória**

O fluxo tem ordem e não perdoa pular etapa:

1. `adobe_mandatory_init`
2. `create_visual_design_express_skill` — ler o playbook devolvido e seguir
3. `find_fonts` / `font_recommend` — confirmar os cortes PostScript da IBM Plex
4. `html_export_readiness_skill` — **antes de CADA export**, inclusive re-exports
5. `export_html_to_express` com `docName:"JFN — Holocron v14"`

Ao voltar, **inspecionar o `slides[].html` normalizado** que a resposta traz: é a representação
interna do Express, não o HTML enviado. Confirmar que texto, fontes e o sabre sobreviveram antes
de dar por pronto.

- [ ] **Step 5: Trazer os quatro selos de volta**

Exportar do editor Express cada placa de face como **SVG** (vetor escala sem peso e aceita cor por
CSS), salvar em `docs/referencias/express/entrada/` e rodar:

```bash
.venv/bin/python -m tools.express_ponte --importar
ls -la static/assets/holocron-*.svg
du -ch static/assets/holocron-*.svg | tail -1
```
Expected: quatro arquivos, soma **≤ 160 KB**. Acima disso, simplificar o traçado — não aceitar.

- [ ] **Step 6: Ligar a placa ao selo da capa**

```css
  /* ── v14: a placa de face do Express entra atrás do glifo da capa, na esfera ── */
  body[data-esf="inicio"]     .cover-seal{--placa:url(/static/assets/holocron-inicio.svg)}
  body[data-esf="estado"]     .cover-seal{--placa:url(/static/assets/holocron-estado.svg)}
  body[data-esf="prefeitura"] .cover-seal{--placa:url(/static/assets/holocron-prefeitura.svg)}
  body[data-esf="geral"]      .cover-seal{--placa:url(/static/assets/holocron-geral.svg)}
  /* a placa é fundo de um selo SEM texto — o glifo é um <svg> irmão, não texto.
     A lei de "não decorar o fundo de quem carrega texto" continua respeitada. */
  .cover-seal{background-image:var(--placa);background-size:contain;
    background-position:center;background-repeat:no-repeat}
```

- [ ] **Step 7: Confirmar que o selo continua legível e medido**

```bash
systemctl --user restart jfn && sleep 25
.venv/bin/python tools/auditar_contraste.py | tail -4
```
Expected: 0 violações e 0 não medidos. Se cair, **tirar a placa de trás do glifo** e pô-la ao
lado — a cura certa não é ensinar o auditor a ignorar.

- [ ] **Step 8: Commit**

```bash
git add docs/referencias/express/holocron-v14.html static/assets/holocron-*.svg \
        docs/referencias/express/ESPECIFICACAO.md static/jfn-painel.html
git commit -m "feat(painel): v14 placas de face e sistema de design pelo Adobe Express"
```

---

## Task 12: As imagens — nebulosa gerada, arte real de telescópio e procedência

Duas origens, dois papéis. **Gerada** (Pollinations) para o fundo abstrato de cada esfera —
controlamos a matiz e ela não afirma nada. **Real** (NASA / ESA-Hubble / ESA-Webb) para o portal
de ignição, onde uma nebulosa que **existe** vale mais que qualquer *prompt*. E, porque duas das
fontes exigem crédito visível, esta tarefa também entrega o **manifesto de procedência** — sem
ele o painel viola a regra da casa de citar fonte e a própria licença CC BY 4.0.

**Files:**
- Create/replace: `static/assets/nebula-{inicio,estado,prefeitura,transversal}.jpg`
- Create: `static/assets/portal-nebula.jpg` (substitui a atual, por arte real)
- Create: `static/assets/CREDITOS-ARTE.md`
- Create: `tests/test_arte_procedencia.py`
- Modify: `static/jfn-painel.html` (regra `#esfnebula`; crédito dentro de `glossario()`)

**Interfaces:**
- Consumes: `tools/express_ponte.py --gerar` (existente).
- Produces: quatro JPEG 1536×384 ≤ 900 KB cada; `CREDITOS-ARTE.md` com uma linha por arte.

- [ ] **Step 1: Gerar com espaçamento — a API anônima limita ~1 requisição/15 s**

Quatro alvos × 3 sementes = 12 chamadas ≈ 3 min. Rodar em background para não segurar a sessão:

```bash
for alvo in inicio estado prefeitura transversal; do
  .venv/bin/python -m tools.express_ponte --gerar $alvo --seeds 3
  sleep 20
done
ls -la docs/referencias/express/entrada/
```
Expected: 12 arquivos. Se algum vier com 0 byte, é limite de taxa — repetir **só aquele**, com
mais espera. Não paralelizar: a VM tem 2 vCPU e a API limita por origem.

- [ ] **Step 2: Escolher com o olho e medir com a régua**

```bash
du -h docs/referencias/express/entrada/*.jpg | sort -h | tail -12
```
Escolher uma semente por esfera. **Teto de 900 KB por arte.** Critério de escolha, nesta ordem:
(1) não competir com o texto na primeira dobra; (2) matiz coerente com a face
(inicio 205 · estado 245 · prefeitura 85 · geral/transversal 300); (3) sem forma que pareça
rosto, mapa falso ou gráfico — o painel não pode sugerir dado que não existe.

- [ ] **Step 3: Instalar e conferir peso total**

```bash
cp docs/referencias/express/entrada/<escolhida-inicio>.jpg static/assets/nebula-inicio.jpg
cp docs/referencias/express/entrada/<escolhida-estado>.jpg static/assets/nebula-estado.jpg
cp docs/referencias/express/entrada/<escolhida-pref>.jpg   static/assets/nebula-prefeitura.jpg
cp docs/referencias/express/entrada/<escolhida-transv>.jpg static/assets/nebula-transversal.jpg
du -ch static/assets/nebula-*.jpg | tail -1
```
Expected: soma **≤ 900 KB** (o teto é por arte, mas quatro artes na primeira dobra é o que pesa).

- [ ] **Step 4: Ligar a nebulosa de `inicio`**

```css
  /* v14: a face de Início ganha céu próprio — antes herdava o do Transversal */
  body[data-esf="inicio"] #esfnebula{background-image:url(/static/assets/nebula-inicio.jpg)}
```

- [ ] **Step 5: Medir a primeira dobra**

```bash
systemctl --user restart jfn && sleep 25
curl -s -o /dev/null -w "painel: %{http_code} · %{size_download} bytes · %{time_total}s\n" \
  http://127.0.0.1:8000/painel
```
Expected: `200`. O HTML sozinho deve continuar abaixo de 420 KB; as artes são requisições à parte
e entram depois da primeira pintura.

- [ ] **Step 6: Colher a arte real para o portal**

O portal de ignição é a única superfície que aparece **uma vez por sessão** e cobre o
carregamento — é o lugar certo para uma nebulosa que existe de verdade. Escolher **uma** imagem
em `https://esahubble.org/images/` ou `https://esawebb.org/images/` (filtrar por *Fullsize*
`≥ 2400px` de largura) e baixar:

```bash
cd /tmp && curl -L -o portal-bruta.jpg "<URL_DA_IMAGEM_ESCOLHIDA>"
identify /tmp/portal-bruta.jpg 2>/dev/null || file /tmp/portal-bruta.jpg
```
Expected: JPEG com largura ≥ 2400px. **Anotar agora, antes de esquecer:** URL da página da
imagem, título, e o crédito exatamente como a fonte o escreve (`ESA/Hubble` ou `ESA/Webb`, texto
inalterado — a licença exige).

- [ ] **Step 7: Recortar para a medida do portal e caber no teto de peso**

A medida do portal é 1175×501 (está em `docs/referencias/express/ESPECIFICACAO.md` §3).

```bash
.venv/bin/python - <<'PY'
from PIL import Image
im = Image.open("/tmp/portal-bruta.jpg").convert("RGB")
alvo_w, alvo_h = 1175, 501
# recorte central mantendo proporcao — nunca esticar: nebulosa esticada le como erro
r = max(alvo_w / im.width, alvo_h / im.height)
im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
esq = (im.width - alvo_w) // 2
topo = (im.height - alvo_h) // 2
im.crop((esq, topo, esq + alvo_w, topo + alvo_h)).save(
    "static/assets/portal-nebula.jpg", quality=80, optimize=True, progressive=True)
PY
du -h static/assets/portal-nebula.jpg
```
Expected: 1175×501 e **≤ 900 KB**. Acima do teto, baixar a qualidade para 74 — nunca reduzir a
dimensão, que o portal cobre a tela inteira e pixel visível lê como amadorismo.

- [ ] **Step 8: Escrever o manifesto de procedência**

Criar `static/assets/CREDITOS-ARTE.md`:

```markdown
# Procedência das artes do painel

Uma linha por arquivo. **Regra da casa:** fonte sempre citada. **Regra de licença:** as artes
CC BY 4.0 exigem crédito visível no produto, com o texto do crédito **inalterado**, e não podem
ser usadas de modo que sugiram endosso da fonte a este painel ou a qualquer achado de fiscalização.

| Arquivo | Origem | Licença | Crédito exigido | Obtido em |
|---|---|---|---|---|
| `portal-nebula.jpg` | <URL da página da imagem> | CC BY 4.0 | `ESA/Hubble` | 2026-07-2X |
| `nebula-inicio.jpg` | Pollinations (Flux), semente <n> | gerada — sem titular | — | 2026-07-2X |
| `nebula-estado.jpg` | Pollinations (Flux), semente <n> | gerada — sem titular | — | 2026-07-2X |
| `nebula-prefeitura.jpg` | Pollinations (Flux), semente <n> | gerada — sem titular | — | 2026-07-2X |
| `nebula-transversal.jpg` | Pollinations (Flux), semente <n> | gerada — sem titular | — | 2026-07-2X |
| `holocron-*.svg` | Adobe Express, desenho próprio | obra da casa | — | 2026-07-2X |
```

E tornar o crédito **visível no produto**, dentro de `glossario()` (linha 1820) — é o painel de
Termos que já existe e é o lugar honesto para ele:

```javascript
  /* v14: crédito de arte. CC BY 4.0 exige crédito VISÍVEL e com o texto inalterado;
     esconder num arquivo do repositório não cumpre a licença. */
  h+=`<h3>Arte</h3><p class="mono" style="font-size:11px;color:var(--mut)">
      Nebulosa do portal: <b>ESA/Hubble</b> — CC BY 4.0. Fundos de esfera gerados por
      Pollinations (Flux). Selos e placas: desenho próprio.</p>`;
```

- [ ] **Step 9: Travar a procedência em teste**

```python
# tests/test_arte_procedencia.py
"""Toda arte servida pelo painel tem procedencia declarada.

Nao e burocracia: duas das fontes usadas (ESA/Hubble e ESA/Webb) sao CC BY 4.0 e
exigem credito visivel com o texto inalterado. Arte que entra no repositorio sem
linha no manifesto e, na melhor hipotese, fonte nao citada — o que a casa proibe
por regra — e na pior, violacao de licenca num produto que vai para fora.
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ASSETS = RAIZ / "static" / "assets"
MANIFESTO = ASSETS / "CREDITOS-ARTE.md"
EXTENSOES = {".jpg", ".jpeg", ".png", ".webp", ".svg"}


def test_toda_arte_tem_linha_no_manifesto():
    assert MANIFESTO.exists(), "static/assets/CREDITOS-ARTE.md nao existe"
    texto = MANIFESTO.read_text(encoding="utf-8")
    artes = sorted(p.name for p in ASSETS.iterdir() if p.suffix.lower() in EXTENSOES)
    sem_linha = [a for a in artes if a not in texto and not _coberta_por_curinga(a, texto)]
    assert not sem_linha, (
        "arte sem procedencia declarada em CREDITOS-ARTE.md: " + ", ".join(sem_linha)
    )


def _coberta_por_curinga(nome: str, texto: str) -> bool:
    """`holocron-*.svg` cobre holocron-estado.svg e os irmaos."""
    for linha in texto.splitlines():
        if "*" in linha and "|" in linha:
            padrao = linha.split("|")[1].strip().strip("`")
            if "*" in padrao:
                pre, _, suf = padrao.partition("*")
                if nome.startswith(pre) and nome.endswith(suf):
                    return True
    return False


def test_credito_cc_by_aparece_no_painel():
    """Credito escondido no repositorio nao cumpre CC BY 4.0 — tem que estar no produto."""
    painel = (RAIZ / "static" / "jfn-painel.html").read_text(encoding="utf-8")
    manifesto = MANIFESTO.read_text(encoding="utf-8")
    if "CC BY 4.0" not in manifesto:
        return  # nenhuma arte CC BY em uso — nada a exigir
    assert "ESA/Hubble" in painel or "ESA/Webb" in painel, (
        "ha arte CC BY 4.0 no manifesto, mas o credito nao aparece no painel"
    )
```

- [ ] **Step 10: Rodar**

Run: `.venv/bin/python -m pytest tests/test_arte_procedencia.py -q`
Expected: 2 passed

- [ ] **Step 11: Commit**

```bash
git add static/assets/nebula-*.jpg static/assets/portal-nebula.jpg \
        static/assets/CREDITOS-ARTE.md tests/test_arte_procedencia.py static/jfn-painel.html
git commit -m "data(painel): v14 nebulosas geradas + portal com arte real de telescopio, com procedencia"
```

---

## Task 13: Auditoria final — o papel 8 do `site-3d-premium`

O plano fecha provando, não afirmando. Três instrumentos: contraste, geometria e **custo de
desenho**. Este último ainda não existe e é o que separa "ficou bonito" de "cabe no orçamento".

**Files:**
- Create: `tools/medir_quadro.py`
- Modify: `DESIGN.md`
- Create: `docs/superpowers/specs/2026-07-2X-handoff-v14.md`

**Interfaces:**
- Consumes: tudo acima.
- Produces: laudo comparável com a base da Tarefa 1.

- [ ] **Step 1: Escrever o medidor de ms/quadro**

```python
# tools/medir_quadro.py
"""A/B de ms/quadro na MESMA aba, alternando ida e volta.

FPS nesta VM nao mede nada: sao ~4 fps (250 ms/quadro) com TODOS os canvas
parados — Chrome headless com SwiftShader por software, 2 vCPU. Um numero
absoluto aqui nao prova coisa nenhuma. O que prova e a DIFERENCA entre a camada
ligada e desligada, medida de ida e volta, na mesma aba, varias voltas.

Uso:  .venv/bin/python tools/medir_quadro.py g_radar [voltas]
"""
from __future__ import annotations

import json
import statistics
import sys
import time

import requests
import websocket

ABA = sys.argv[1] if len(sys.argv) > 1 else "g_radar"
VOLTAS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
MARCA = "v14 “HOLOCRON”"          # texto que identifica o bloco a desligar

_id = [0]


def _cmd(ws, metodo, params=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": metodo, "params": params or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == _id[0]:
            return r


def _js(ws, expr):
    r = _cmd(ws, "Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    return r["result"]["result"].get("value")


AMOSTRA = """
new Promise(res=>{const t=[];let ant=performance.now(),n=0;
  (function q(ts){const d=ts-ant;ant=ts;if(n++>2)t.push(d);
    if(n<70)requestAnimationFrame(q);else res(t);})(performance.now());});
"""

# desliga SO o bloco v14: acha a folha inline e reescreve sem ele.
DESLIGA = """
(()=>{const s=document.querySelector('style');
  if(!window.__v14){const i=s.textContent.indexOf(%s);
    window.__v14={todo:s.textContent,corte:i};}
  const c=window.__v14.corte;
  s.textContent=c>0?window.__v14.todo.slice(0,c):window.__v14.todo;return c>0;})();
""" % json.dumps(MARCA)

LIGA = "(()=>{if(window.__v14)document.querySelector('style').textContent=window.__v14.todo;return true;})();"


def main() -> int:
    alvo = json.loads(requests.get("http://127.0.0.1:9222/json").text)[0]["webSocketDebuggerUrl"]
    ws = websocket.create_connection(alvo, suppress_origin=True)
    _cmd(ws, "Network.enable")
    _cmd(ws, "Network.setCacheDisabled", {"cacheDisabled": True})   # sem isto a medicao nao vale
    _cmd(ws, "Page.navigate", {"url": "http://127.0.0.1:8000/painel"})
    time.sleep(8)
    _js(ws, f"ir('{ABA}')")
    time.sleep(3)

    if not _js(ws, DESLIGA):
        print(f"nao achei o bloco {MARCA} na folha — nada a medir")
        return 1
    _js(ws, LIGA)

    ligado: list[float] = []
    desligado: list[float] = []
    for volta in range(VOLTAS):
        _js(ws, LIGA)
        time.sleep(1.2)
        ligado += _js(ws, AMOSTRA) or []
        _js(ws, DESLIGA)
        time.sleep(1.2)
        desligado += _js(ws, AMOSTRA) or []
        print(f"volta {volta + 1}/{VOLTAS} medida")
    _js(ws, LIGA)

    def laudo(nome, xs):
        xs = sorted(xs)
        p90 = xs[int(len(xs) * 0.9)] if xs else 0.0
        print(f"{nome:10s} n={len(xs):3d}  mediana={statistics.median(xs):7.1f} ms  p90={p90:7.1f} ms")

    print(f"\naba {ABA} — {VOLTAS} voltas")
    laudo("ligado", ligado)
    laudo("desligado", desligado)
    d = statistics.median(ligado) - statistics.median(desligado)
    print(f"\ndiferenca da camada v14: {d:+.1f} ms/quadro")
    print("veredito:", "cabe no orcamento" if d < 2.0 else "CARO — investigar antes de fechar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Medir três abas de densidades diferentes**

```bash
systemctl --user restart jfn && sleep 25
.venv/bin/python tools/medir_quadro.py i_cockpit 3
.venv/bin/python tools/medir_quadro.py g_radar 3
.venv/bin/python tools/medir_quadro.py e_panorama 3
```
Expected: diferença < 2,0 ms/quadro em cada. A holomesa custa 0,9 ms (p90 1,1) num orçamento de
16,6 ms — a camada v14 é pintura e deve custar menos que ela. **Se der acima de 2 ms**, o suspeito
número um é o `filter:drop-shadow` das quatro peças com `clip-path` (Tarefa 3): medir com ele
comentado antes de acusar qualquer outra coisa.

- [ ] **Step 3: Contraste e geometria nas 51 abas, comparado com a base**

```bash
.venv/bin/python tools/auditar_contraste.py > /tmp/contraste-v14.txt
.venv/bin/python tools/auditar_layout.py    > /tmp/layout-v14.txt
diff <(grep -E "^(VIOLA|NAO_MEDIDO)" docs/superpowers/specs/base-contraste-v13.txt | sort) \
     <(grep -E "^(VIOLA|NAO_MEDIDO)" /tmp/contraste-v14.txt | sort)
tail -6 /tmp/contraste-v14.txt; tail -6 /tmp/layout-v14.txt
```
Expected: `diff` **vazio ou só com remoções** (violação que sumiu é ganho; violação nova é
regressão e o plano não fecha). Laudo final: 0 violações e 0 não medidos nas 51 abas; 0 violações
de norma a 390px.

- [ ] **Step 4: As duas variantes que revelam o que a tela normal esconde**

```bash
.venv/bin/python tools/auditar_layout.py g_radar 390
.venv/bin/python tools/auditar_layout.py p_benef 390
.venv/bin/python tools/auditar_layout.py e_certames 390
```
Expected: 0 violações de norma. E a variante de movimento reduzido, pelo script do passo 4 da
Tarefa 9 — **cards visíveis > 0** em ao menos quatro abas, uma por esfera.

- [ ] **Step 5: A suíte inteira, nome a nome**

Contagem esconde regressão: 50 antes e 50 depois pode ser 50 falhas **diferentes**.

```bash
./tools/testar_na_vm2.sh > /tmp/s.log
grep '^FAILED' /tmp/s.log | sed 's/ - .*//' | sort > /tmp/agora.txt
comm -13 <(grep -v '^#' tests/BASE-FALHAS-VM2.txt) /tmp/agora.txt
```
Expected: **saída vazia**. Qualquer linha é falha nova e o plano não fecha.

- [ ] **Step 6: Olhar como humano — o que o auditor não mede**

Os auditores não medem hierarquia, ritmo nem intenção. Abrir quatro abas (uma por esfera) e
responder por escrito, no handoff:

1. O olho sabe **em 3 segundos** o que a aba mede? (o lema falha se precisa ser lido duas vezes)
2. Algum brilho aparece **sem significado**? (glow uniforme é o erro nº 1 do gênero)
3. O espaçamento é irregular em algum lugar? (escala 4/8/12/16/24/32 — não inventar valor)
4. Alguma animação **atrapalha a leitura**?
5. Alguma peça pequena ganhou chanfro e ficou apertada? (a lei do v12.3)

As **três melhorias de maior impacto** que saírem daqui se aplicam **nesta tarefa**, não na próxima.

- [ ] **Step 7: Escrever o estado REAL, não o pretendido**

Atualizar `DESIGN.md` com uma seção v14 no topo (o formato das seções v9/v10 já existente) e criar
`docs/superpowers/specs/2026-07-2X-handoff-v14.md` com: o que ficou pronto, os números medidos
(ms/quadro, contraste, layout), as armadilhas novas que aparecerem e o que ficou **pendente**.
Handoff que descreve o pretendido em vez do medido já custou um número errado carregado adiante.

- [ ] **Step 8: Commit final**

```bash
git add tools/medir_quadro.py DESIGN.md docs/superpowers/specs/2026-07-2X-handoff-v14.md
git commit -m "docs(painel): v14 HOLOCRON auditado — ms/quadro, contraste e layout nas 51 abas"
```

---

## Auto-revisão do plano (feita, registrada)

**1 · Cobertura do pedido**

| Pedido do dono | Onde |
|---|---|
| UI mais ultratech | Tarefas 3, 4, 6, 7, 8 |
| templates | Tarefas 5 (capa), 6 (KPI), 7 (tabela/lista), 10 (estados) |
| botões | Tarefa 4 |
| **em todas as abas** | Tarefas 1 (auditor vê 51), 2 (registro de 51), 8 (barra) |
| painel mais vivo e animado | Tarefas 5, 9, 10 |
| bem detalhado e desenhado | Tarefas 3 (chanfro, moldura), 5 (cena), 11 (placas) |
| Adobe Express | Tarefa 11 |
| Jarvis / Star Wars / holocron / cyberpunk | Conceito + Tarefas 3, 4, 9 |
| gits de referência e geração de imagem | seção **Arsenal** + Tarefas 11, 12 |
| **"dezenas de imagens"** | **Arsenal → Imagem pronta** + Tarefa 12 (colheita, recorte, procedência, crédito visível) |
| sem regredir | Constraints + Tarefas 1 (base), 13 (comparação nome a nome) |

**2 · Varredura de espaço reservado:** nenhum "TBD", nenhum "similar à Tarefa N", nenhum passo de
código sem bloco de código. O único ponto declarado como condicional é o Passo 3 da Tarefa 6
(medição que depende de `tools/medir_quadro.py`), e ele diz explicitamente o que fazer se a
ordem de execução o alcançar antes — **e proíbe afirmar que está barato sem medir**.

**3 · Consistência de tipos e nomes:** `ASSINATURA` (Tarefa 2) é lida com os mesmos quatro campos
(`h`, `gl`, `lema`, `inst`) nas Tarefas 5 e 8 e no teste; `_ESF_MATIZ` idem; `facetar`/`FAC_SEL`
(Tarefa 3) casam com o teste de presença nominal; `painel_abas.abas()` (Tarefa 1) é o mesmo nome
consumido pelos dois auditores e por `tests/test_painel_assinaturas.py`; `--fac`, `--fac-d`,
`--fac-h`, `--kyber`, `--chanfro` são declarados uma vez (Tarefa 3) e só consumidos depois.

**Uma pendência declarada, não escondida:** o registro `ASSINATURA` traz 51 lemas escritos aqui.
Eles são legenda de instrumento e afirmam o que a aba **mede** — nunca o que ela **prova**. Se
alguma aba, ao ser aberta, mostrar que o lema promete mais do que o dado sustenta, **o lema muda**;
indício não vira acusação por causa de uma frase de capa.
