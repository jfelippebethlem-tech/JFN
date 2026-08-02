"""O painel carrega SCRIPT CLASSICO, bloqueante, nesta ordem — e isso e load-bearing.

POR QUE ESTE TESTE EXISTE. O `jfn-painel.html` traz, ha versoes, um comentario avisando que os
scripts nao levam `type=module` nem `defer` "pelo mesmo motivo do painel.js: mudar escopo/timing e
o vetor que ja matou este boot tres vezes". Comentario nao falha build. Este teste falha.

Sao quatro propriedades distintas, e cada uma quebra de um jeito diferente:

1. **Sem `type=module`** — modulo tem escopo proprio. Os ~124 handlers inline (`onclick="ir('...')"`)
   so resolvem no escopo GLOBAL; dentro de um modulo, `ir` deixa de existir para o HTML e cada
   clique vira `ReferenceError` — em UMA aba de cada vez, o que passa despercebido na revisao.
2. **Sem `defer` / `async`** — os dois adiam a execucao para depois do parse. O boot do painel roda
   `DOMContentLoaded` e disputa com View Transitions; a corrida perdida ja matou o boot uma vez.
3. **Ordem preservada** — `caps.js` declara `CAPS_MESTRAS` como `const` de script classico (nao vai
   para o `window`); se ele carregar depois do painel, o bloco de funcoes mestras do cockpit nasce
   vazio, sem erro no console.
4. **Catraca de versao viva** — toda tag de script/css do painel leva `?v=<sha256[:8]>` escrito por
   `tools/painel_bump_versao.py`. Sem o sufixo, o navegador serve o arquivo velho do cache e a
   correcao simplesmente nao chega a ninguem.

O par empirico deste teste esta em `tools/painel_boot_check.py`, que afirma
`window.__jfnBootReadyState === 'loading'` na pagina viva. Este aqui e o estatico: custa
milissegundos e nao precisa de navegador.
"""
import re
from pathlib import Path

PAINEL = Path(__file__).resolve().parents[1] / "static" / "jfn-painel.html"

# O painel.js pode virar `painel.bundle.js` quando a migracao para modulos com build acontecer.
# O que este teste protege nao e o NOME do arquivo — e o modo como ele e carregado.
_ALVO = re.compile(r'<script\s+src="/static/js/painel(?:\.bundle)?\.js\?v=([0-9a-f]{8})"\s*>'
                   r'\s*</script>')


def _html() -> str:
    return PAINEL.read_text(encoding="utf-8")


def test_o_painel_e_carregado_como_script_classico_versionado():
    html = _html()
    m = _ALVO.search(html)
    assert m, ("a tag do painel.js sumiu ou mudou de forma. Esperado exatamente\n"
               '  <script src="/static/js/painel.js?v=xxxxxxxx"></script>\n'
               "(ou painel.bundle.js, depois da migracao para modulos com build). "
               "Sem `type`, sem `defer`, sem `async`, com a catraca `?v=` de 8 hex.")


def test_nenhum_script_do_painel_e_modulo_ou_adiado():
    """`type=module`, `defer` e `async` mudam QUANDO o script roda. Os tres quebram este boot."""
    html = _html()
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert "type=" not in tag or 'type="text/javascript"' in tag, (
            f"script com `type` na tag: {tag}\n"
            "`type=module` da escopo proprio ao arquivo e os ~124 handlers inline do painel "
            "param de achar as funcoes. Se a modularizacao for o objetivo, o caminho e bundle "
            "com `--format=iife` — a saida continua sendo script classico.")
        assert not re.search(r"\b(defer|async)\b", tag), (
            f"script com defer/async: {tag}\n"
            "os dois adiam a execucao para depois do parse do HTML e reabrem a corrida com "
            "View Transitions que ja matou este boot.")


def test_a_ordem_de_carga_dos_tres_scripts_esta_preservada():
    """jfn-icones -> caps -> painel. `caps.js` declara `CAPS_MESTRAS` que o painel consome."""
    html = _html()
    pos = {}
    for nome, padrao in (("icones", r'src="/static/assets/jfn-icones\.js'),
                         ("caps", r'src="/static/js/caps\.js'),
                         ("painel", r'src="/static/js/painel(?:\.bundle)?\.js')):
        m = re.search(padrao, html)
        assert m, f"a tag de {nome} sumiu do painel"
        pos[nome] = m.start()
    assert pos["icones"] < pos["caps"] < pos["painel"], (
        f"ordem de carga trocada: {sorted(pos, key=pos.get)}. "
        "`caps.js` precisa vir ANTES do painel (CAPS_MESTRAS e `const` de script classico, "
        "nao esta no window); `jfn-icones.js` antes de ambos (JFN_ICO alimenta o svgIco).")


def test_a_primeira_instrucao_do_painel_grava_o_readystate():
    """A testemunha que o `painel_boot_check` le. Se sumir daqui, a prova viva perde o objeto."""
    js = Path(__file__).resolve().parents[1] / "static" / "js"
    fonte = js / "painel.js"
    if not fonte.exists():                                  # pos-migracao: o fonte vira src/entrada.js
        fonte = js / "src" / "entrada.js"
    assert fonte.exists(), "nao achei nem static/js/painel.js nem static/js/src/entrada.js"
    corpo = fonte.read_text(encoding="utf-8")
    # primeira linha com codigo (ignorando comentarios e linhas vazias)
    primeira = ""
    dentro_bloco = False
    for ln in corpo.splitlines():
        s = ln.strip()
        if dentro_bloco:
            if "*/" in s:
                dentro_bloco = False
                s = s.split("*/", 1)[1].strip()
            else:
                continue
        if s.startswith("/*"):
            dentro_bloco = "*/" not in s
            if dentro_bloco:
                continue
            s = s.split("*/", 1)[1].strip()
        if not s or s.startswith("//"):
            continue
        primeira = s
        break
    assert primeira.startswith("window.__jfnBootReadyState"), (
        f"a primeira instrucao executada do painel e {primeira[:80]!r}.\n"
        "Ela precisa ser `window.__jfnBootReadyState=document.readyState;` — e a unica prova "
        "empirica de que o script ainda bloqueia o parser. Qualquer coisa antes dela invalida a "
        "medicao, porque o readyState ja pode ter avancado.")
