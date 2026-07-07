# -*- coding: utf-8 -*-
"""RELATÓRIO CONSOLIDADO — UM PDF, organizado em CAPÍTULOS por produtor (NOVO PADRÃO DA CASA).

Substitui os documentos separados por produtor. Em vez de N PDFs (inteligência, Lex, raciocínio),
emite **UM** PDF Kroll/Deloitte com capa + índice e três capítulos:

  • CAPÍTULO I — HERMES   → análise multi-IA / raciocínio de fraude (cadeia LLM grátis, NÃO-gemini).
  • CAPÍTULO II — JFN     → inteligência: dados, concentração, due diligence, CONTRATOS por
                            fornecedor, tabela de pagamentos (markdown já produzido por `inteligencia*`).
  • CAPÍTULO III — LEX    → parecer jurídico: red flags R1-R12, auditoria de contrato T01-T22,
                            sanções, grau 🟢🟡🔴 (markdown já produzido por `lex`).

CIRÚRGICO E REUSO: NÃO reescreve `inteligencia_orgao`/`inteligencia`/`lex` — chama `montar(retornar_ctx=True)`
(que já gera os md de JFN e Lex) e costura os markdowns num só documento. Os produtos por-produtor
seguem sendo gerados (additive). Render Kroll = CSS de `render_html` + `html_to_pdf` (Playwright).

HONESTIDADE (CLAUDE.md #6): o capítulo HERMES degrada de forma HONESTA. Gemini está DESLIGADO (billing,
ver vault gemini-desligado-billing) — a cadeia Hermes cai para Groq/Cerebras/OpenRouter:free (não-gemini).
Se NENHUMA IA estiver disponível e não houver análise Hermes em cache no DB, o capítulo é renderizado com
o aviso explícito "INDISPONÍVEL", NUNCA uma análise fabricada.

USO (CLI):
    cd ~/JFN && .venv/bin/python -m compliance_agent.reporting.consolidado orgao 166100
    cd ~/JFN && .venv/bin/python -m compliance_agent.reporting.consolidado relatorio "nome ou cnpj"
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

_REPORTS = Path(__file__).resolve().parent.parent.parent / "reports"
_DB = Path(__file__).resolve().parent.parent.parent / "data" / "compliance.db"


def _carregar_env() -> None:
    """Carrega .env (como o server.py) para que a cadeia LLM (Groq/Cerebras/OpenRouter) tenha as chaves
    quando o consolidado roda fora do processo do servidor (ex.: CLI). override=False preserva o ambiente."""
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env", override=False)
    except Exception as exc:  # noqa: BLE001
        _log.debug("dotenv não carregado (segue com ambiente atual): %s", exc)


# ───────────────────────────── CAPÍTULO I — HERMES ─────────────────────────────

_SYS_HERMES = (
    "Você é o HERMES, agente de inteligência sênior do JFN (auditoria de controle externo do Estado do "
    "Rio de Janeiro, padrão TCE-RJ/TCU). A partir EXCLUSIVAMENTE dos FATOS listados (NÃO invente "
    "dados/nomes/fontes; sem conhecimento externo), produza uma ANÁLISE DE FRAUDE multi-camada: (1) os "
    "PADRÕES que conectam os achados; (2) HIPÓTESES concretas de esquema (captura, fracionamento, "
    "direcionamento, cartel/concorrência fictícia, interposição/laranja) e COMO os sinais se REFORÇAM "
    "entre si; (3) a PRIORIDADE de apuração e exatamente O QUE verificar (contrato, certame, processo SEI). "
    "Linguagem condicional (indício, sugere, merece apuração) — NUNCA afirme irregularidade nem culpa "
    "(presunção de legitimidade). Cite os valores/percentuais/nomes dos fatos. Responda em MARKDOWN com "
    "subtítulos '### ' e bullets '- ' (NUNCA JSON/cercas). Até ~500 palavras."
)

_NOTA_GEMINI_OFF = (
    "> **INDISPONÍVEL — análise Hermes (LLM) não executada nesta geração.** A cadeia multi-IA do Hermes "
    "(Groq → Cerebras → OpenRouter :free) não respondeu e o Gemini está desligado por billing "
    "(ver vault `gemini-desligado-billing`). Nenhuma análise foi fabricada (CLAUDE.md #6: INDISPONÍVEL ≠ 0). "
    "Os capítulos II (JFN) e III (LEX) abaixo seguem íntegros — a inteligência determinística e o parecer "
    "jurídico não dependem de LLM."
)


def _hermes_cache_orgao(ug: str, top_nomes: list[str], limite: int = 6) -> str:
    """Recupera, do DB (`sei_direcionamento.llm_*`), as análises Hermes JÁ COMPUTADAS para os maiores
    fornecedores da UG — surface de cache (não chama LLM). '' se nada cacheado/DB ausente."""
    if not _DB.exists() or not top_nomes:
        return ""
    try:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            # casa por CNPJ dos fornecedores da UG que tenham llm_grau preenchido
            cnpjs = [r[0] for r in con.execute(
                "SELECT DISTINCT favorecido_cpf FROM ordens_bancarias WHERE ug_codigo=? "
                "AND favorecido_cpf IS NOT NULL AND length(favorecido_cpf)=14", (str(ug),)).fetchall()]
            if not cnpjs:
                return ""
            qs = ",".join("?" * len(cnpjs))
            rows = con.execute(
                f"SELECT fornecedor_nome, llm_grau, llm_resumo, llm_modelo, score "
                f"FROM sei_direcionamento WHERE fornecedor_cnpj IN ({qs}) "
                f"AND llm_grau IS NOT NULL AND llm_grau!='' "
                f"ORDER BY score DESC LIMIT ?", (*cnpjs, limite)).fetchall()
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        _log.warning("Cache Hermes do órgão %s indisponível: %s", ug, exc)
        return ""
    if not rows:
        return ""
    L = ["### I-B. Análises Hermes em cache (fornecedores da UG já triados pelo sweep)", "",
         "> Pareceres do Hermes JÁ COMPUTADOS e persistidos no sweep de direcionamento (`sei_direcionamento`) — "
         "recuperados do banco, sem nova chamada de LLM.", ""]
    for r in rows:
        nome = (r["fornecedor_nome"] or "—").strip()[:48]
        grau = (r["llm_grau"] or "—").strip()
        resumo = (r["llm_resumo"] or "").strip()
        modelo = (r["llm_modelo"] or "—").strip()
        L.append(f"- **{nome}** — grau Hermes **{grau}** (modelo: {modelo}): {resumo[:280]}")
    L.append("")
    return "\n".join(L)


def _hermes_fresco(fatos: str, titulo_alvo: str) -> str:
    """Síntese Hermes FRESCA via a cadeia multi-IA grátis (Groq → Cerebras → OpenRouter :free; Gemini OFF
    por billing). '' se a cadeia não responder (capítulo cai p/ INDISPONÍVEL)."""
    if not fatos.strip():
        return ""
    try:
        from compliance_agent.llm.hermes_agent import _hermes
        prompt = (f"ALVO: {titulo_alvo}\n\nFATOS APURADOS (somente estes, não invente):\n{fatos}\n\n"
                  "Produza a análise de fraude multi-camada conforme as instruções do sistema.")
        txt = asyncio.run(_hermes(_SYS_HERMES, prompt, max_tokens=1400))
        txt = (txt or "").strip()
        # remove cercas de código se a IA desobedecer
        if txt.startswith("```"):
            txt = txt.strip("`").lstrip("markdown").strip()
        return txt if len(txt) > 120 else ""
    except Exception as exc:  # noqa: BLE001
        _log.warning("Hermes fresco indisponível (%s): %s", titulo_alvo, exc)
        return ""


def _capitulo_hermes(fatos: str, titulo_alvo: str, cache_md: str = "") -> tuple[str, bool]:
    """Monta o markdown do CAPÍTULO I — HERMES. Retorna (markdown, disponivel:bool).
    disponivel=False quando não há nem síntese fresca nem cache → renderiza o aviso INDISPONÍVEL."""
    _carregar_env()
    L = ["# CAPÍTULO I — HERMES", "", "*Análise multi-IA de fraude · raciocínio sobre os fatos apurados*", ""]
    fresco = _hermes_fresco(fatos, titulo_alvo)
    disponivel = False
    if fresco:
        L += ["## I-A. Síntese raciocinada (Hermes)", "",
              "> Gerada nesta execução pela cadeia multi-IA grátis do Hermes (Groq/Cerebras/OpenRouter :free; "
              "Gemini desligado por billing). Indícios a verificar, nunca acusação.", "", fresco, ""]
        disponivel = True
    if cache_md:
        L += [cache_md]
        disponivel = True
    if not disponivel:
        L += [_NOTA_GEMINI_OFF, ""]
    return "\n".join(L), disponivel


# ───────────────────────────── markdown → HTML (Kroll) ─────────────────────────────

# CSS extraído de reporting/render_html (mesmo padrão Kroll), adaptado p/ markdown multi-capítulo:
# capa, índice, h1/h2/h3 hierárquicos, tabelas zebradas, blockquote de ressalva, quebra de página por capítulo.
_CSS = """
  @page { size: A4; margin: 16mm 14mm; }
  body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #1a1a1a; font-size: 11px; line-height: 1.55; }
  .capa { border-bottom: 3px solid #1f4e79; padding-bottom: 16px; margin-bottom: 18px; }
  .capa .classif { color:#c62828; font-weight:700; letter-spacing:1px; font-size:10px; }
  .capa h1 { font-size: 24px; color:#1f4e79; margin: 6px 0 2px; background:none; padding:0;
             page-break-before: avoid; border-radius:0; }
  .capa .sub { color:#333; font-size:13px; font-weight:600; }
  .capa .meta { color:#555; font-size:10px; margin-top:10px; }
  .grau-card { display:inline-flex; align-items:center; gap:12px; border:1px solid #ddd; border-radius:8px;
               padding:10px 16px; margin:14px 0; background:#fafafa; }
  .grau-badge { width:60px; height:60px; border-radius:50%; color:#fff; display:flex; align-items:center;
                justify-content:center; font-weight:700; font-size:13px; text-align:center; line-height:1.1; }
  .indice { border:1px solid #e0e0e0; border-radius:6px; padding:10px 16px; margin:14px 0; background:#f7f9fc; }
  .indice h3 { margin:0 0 6px; color:#1f4e79; font-size:12px; }
  .indice ul { margin:0; padding-left:18px; }
  h1 { font-size: 19px; color:#fff; background:#1f4e79; padding:8px 12px; border-radius:4px;
       margin: 26px 0 10px; page-break-before: always; }
  h2 { font-size:13.5px; color:#1f4e79; border-bottom:1px solid #d6dee8; padding-bottom:3px; margin-top:18px; }
  h3 { font-size:12px; color:#2a4a6b; margin-top:14px; }
  table { width:100%; border-collapse:collapse; font-size:9.5px; margin:8px 0; }
  th,td { text-align:left; padding:4px 6px; border-bottom:1px solid #eee; vertical-align:top; }
  th { background:#1f4e79; color:#fff; }
  td.num, th.num { text-align:right; }
  table tr:nth-child(even) td { background:#eef3fa; }
  blockquote { border-left:3px solid #1f4e79; background:#f4f7fb; margin:8px 0; padding:6px 12px;
               color:#333; font-size:10px; }
  code { background:#eef1f5; padding:1px 4px; border-radius:3px; font-size:10px; }
  ul,ol { margin:6px 0; padding-left:20px; }
  hr { border:none; border-top:1px solid #ddd; margin:12px 0; }
  footer { margin-top:24px; border-top:1px solid #ddd; padding-top:8px; font-size:8px; color:#888; }
"""

_GRAU_COR = {"BAIXO": "#2e7d32", "MODERADO": "#2e7d32", "MÉDIO": "#f9a825", "MEDIO": "#f9a825",
             "ALTO": "#ef6c00", "EXTREMO": "#c62828", "CRÍTICO": "#c62828", "CRITICO": "#c62828"}


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _inline(s: str) -> str:
    """negrito **x**, itálico *x*, código `x` → HTML. Aplicado a texto JÁ escapado."""
    import re
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+?)`", r"<code>\1</code>", s)
    s = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])", r"<em>\1</em>", s)
    return s


def _md_to_html(md: str) -> str:
    """Conversor markdown→HTML mínimo mas COMPLETO p/ o nosso markdown: h1-h4, tabelas pipe (com alinhamento
    à direita por ':---'/'---:'), blockquote, listas (- / 1.), hr, negrito/itálico/código, parágrafos.
    A lib `markdown` não está instalada; este conversor cobre exatamente o que os módulos JFN/Lex emitem."""
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    list_open = None  # 'ul' | 'ol' | None

    def _close_list():
        nonlocal list_open
        if list_open:
            out.append(f"</{list_open}>")
            list_open = None

    while i < n:
        ln = lines[i]
        raw = ln.rstrip()
        stripped = raw.strip()

        # tabela pipe: linha começa com '|' e a próxima é separador (---)
        if stripped.startswith("|") and i + 1 < n and set(lines[i + 1].strip().replace("|", "").replace(":", "").replace("-", "").replace(" ", "")) <= set():
            _close_list()
            header = [c.strip() for c in stripped.strip("|").split("|")]
            sep = [c.strip() for c in lines[i + 1].strip().strip("|").split("|")]
            # ':---:' (centro) e '---:' (direita) → alinhamento numérico à direita; senão à esquerda
            aligns = ["num" if c.endswith(":") and not c.startswith(":") else "" for c in sep]
            out.append("<table><thead><tr>")
            for h, a in zip(header, aligns + [""] * len(header)):
                cls = ' class="num"' if a == "num" else ""
                out.append(f"<th{cls}>{_inline(_esc(h))}</th>")
            out.append("</tr></thead><tbody>")
            j = i + 2
            while j < n and lines[j].strip().startswith("|"):
                cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                out.append("<tr>")
                for k, cval in enumerate(cells):
                    a = aligns[k] if k < len(aligns) else ""
                    cls = ' class="num"' if a == "num" else ""
                    out.append(f"<td{cls}>{_inline(_esc(cval))}</td>")
                out.append("</tr>")
                j += 1
            out.append("</tbody></table>")
            i = j
            continue

        if not stripped:
            _close_list()
            i += 1
            continue

        if stripped.startswith("#### "):
            _close_list(); out.append(f"<h4>{_inline(_esc(stripped[5:]))}</h4>"); i += 1; continue
        if stripped.startswith("### "):
            _close_list(); out.append(f"<h3>{_inline(_esc(stripped[4:]))}</h3>"); i += 1; continue
        if stripped.startswith("## "):
            _close_list(); out.append(f"<h2>{_inline(_esc(stripped[3:]))}</h2>"); i += 1; continue
        if stripped.startswith("# "):
            _close_list(); out.append(f"<h1>{_inline(_esc(stripped[2:]))}</h1>"); i += 1; continue
        if stripped in ("---", "***", "___"):
            _close_list(); out.append("<hr>"); i += 1; continue
        if stripped.startswith("> "):
            _close_list()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(f"<blockquote>{_inline(_esc(' '.join(buf)))}</blockquote>")
            continue
        if stripped[:2] in ("- ", "* ") or (stripped[:1].isdigit() and ". " in stripped[:4]):
            ordered = stripped[:2] not in ("- ", "* ")
            want = "ol" if ordered else "ul"
            if list_open != want:
                _close_list(); out.append(f"<{want}>"); list_open = want
            item = stripped[stripped.find(" ") + 1:] if ordered else stripped[2:]
            out.append(f"<li>{_inline(_esc(item))}</li>")
            i += 1
            continue

        _close_list()
        out.append(f"<p>{_inline(_esc(stripped))}</p>")
        i += 1

    _close_list()
    return "\n".join(out)


def _grau_norm(g: str) -> str:
    g = (g or "").upper().strip()
    for k in _GRAU_COR:
        if k in g:
            return k
    return g or "—"


def _html_consolidado(titulo: str, subtitulo: str, data: str, grau: str,
                      capitulos: list[dict], corpo_md: str) -> str:
    """Capa Kroll (título, alvo, data, grau, índice de capítulos) + corpo (markdown costurado → HTML)."""
    grau_n = _grau_norm(grau)
    cor = _GRAU_COR.get(grau_n, "#777")
    idx = "".join(f"<li><b>{_esc(c['rotulo'])}</b> — {_esc(c['desc'])}</li>" for c in capitulos)
    capa = f"""
    <div class="capa">
      <div class="classif">CONFIDENCIAL — USO INTERNO · CONTROLE EXTERNO</div>
      <h1>{_esc(titulo)}</h1>
      <div class="sub">{_esc(subtitulo)}</div>
      <div class="grau-card">
        <div class="grau-badge" style="background:{cor}">{_esc(grau_n)}</div>
        <div><b>Grau de atenção (LEX):</b> {_esc(grau_n)} — risco de ACHADO, não de punição.<br>
        Indícios a verificar; presunção de legitimidade dos atos administrativos.</div>
      </div>
      <div class="meta">Emitido em {_esc(data)} · Analista: JFN Intelligence Engine ·
        Metodologia: due diligence Nível II + red flags TCU/TCE-RJ + auditoria de contrato (T01-T22)</div>
      <div class="indice">
        <h3>Índice — relatório consolidado por capítulos</h3>
        <ul>{idx}</ul>
      </div>
    </div>"""
    corpo = _md_to_html(corpo_md)
    return (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><style>{_CSS}</style></head>"
            f"<body>{capa}{corpo}"
            f"<footer>JFN · Inteligência fiscal RJ — relatório consolidado (Hermes · JFN · Lex). "
            f"Peça de diligência: indícios, nunca acusação; presunção de legitimidade. "
            f"INDISPONÍVEL ≠ 0; nenhum dado indisponível foi fabricado.</footer></body></html>")


def _demover_titulo(md: str) -> str:
    """Demove o 1º '# Título' do markdown de um módulo p/ '## …' (evita 2 banners de H1 no mesmo capítulo,
    já que o capítulo tem seu próprio '# CAPÍTULO …'). Só o PRIMEIRO H1; os demais '# ' viram '## ' também."""
    if not md:
        return md
    out = []
    for ln in md.split("\n"):
        if ln.startswith("# "):
            out.append("## " + ln[2:])
        else:
            out.append(ln)
    return "\n".join(out)


def _ler(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8") if path else ""
    except Exception:  # noqa: BLE001
        return ""


async def _render_pdf(html: str, destino: str) -> str:
    from compliance_agent.reporting.render_html import html_to_pdf
    return await html_to_pdf(html, destino)


def _slug(s: str) -> str:
    from compliance_agent.reporting.inteligencia import _slug as _s
    return _s(s)


async def _enviar_yoda(path_pdf: str, caption: str) -> dict:
    try:
        from compliance_agent.notifications.telegram import enviar_arquivo
        return await enviar_arquivo(path_pdf, caption=caption)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:160]}


# ───────────────────────────── /orgao consolidado ─────────────────────────────

def gerar_consolidado_orgao(ug: Optional[str] = None, orgao: Optional[str] = None,
                            anos: Optional[list[int]] = None, enviar: bool = False) -> dict:
    """UM PDF consolidado por capítulos (HERMES · JFN · LEX) para um ÓRGÃO (UG). Reusa `inteligencia_orgao.
    montar(retornar_ctx=True)` (gera os md de JFN+Lex e devolve o ctx) e o capítulo Hermes (multi-IA grátis,
    cache do DB ou INDISPONÍVEL honesto). Retorna {ok, path_md, path_pdf, capitulos, enviado, grau}."""
    _carregar_env()
    from compliance_agent.reporting import inteligencia_orgao as io

    res = io.montar(orgao=orgao, ug=ug, anos=anos, salvar=True, retornar_ctx=True)
    if not res.get("ok"):
        return res  # erro ou {ambiguo,...} — repassa p/ o Yoda perguntar
    ctx = res.get("_ctx") or {}
    nome = res.get("orgao") or ctx.get("nome") or f"UG {res.get('ug')}"
    ug_cod = res.get("ug")
    data = ctx.get("data") or date.today().isoformat()
    grau = res.get("grau_lex") or "—"

    # capítulos II (JFN) e III (LEX): markdown JÁ produzido pelo montar
    jfn_md = _ler(res.get("path_md", ""))
    lex_md = _ler(res.get("path_lex_md", ""))

    # capítulo I (HERMES): fatos do órgão (mesma compilação determinística do raciocínio) + cache do DB
    fatos = io._fatos_orgao(ctx)
    top_nomes = list((ctx.get("pagamentos") or {}).get("por_favorecido_geral") or {})[:10]
    cache_md = _hermes_cache_orgao(str(ug_cod), top_nomes)
    hermes_md, hermes_ok = _capitulo_hermes(fatos, f"{nome} (UG {ug_cod})", cache_md)

    return _assemblar(
        tipo="orgao", titulo=f"RELATÓRIO CONSOLIDADO DE INTELIGÊNCIA — {nome}",
        subtitulo=f"Órgão / Unidade Gestora {ug_cod} · execução, concentração, due diligence e parecer jurídico",
        data=data, grau=grau, alvo_slug=_slug(nome) or str(ug_cod), nome=nome,
        hermes_md=hermes_md, hermes_ok=hermes_ok, jfn_md=jfn_md, lex_md=lex_md,
        enviar=enviar, extra={"ug": ug_cod, "orgao": nome})


# ───────────────────────────── /relatorio consolidado ─────────────────────────────

def gerar_consolidado_relatorio(alvo: str, enviar: bool = False) -> dict:
    """UM PDF consolidado por capítulos (HERMES · JFN · LEX) para um FORNECEDOR (/relatorio). Reusa
    `inteligencia.montar(retornar_ctx=True)`. Retorna {ok, path_md, path_pdf, capitulos, enviado, grau}."""
    _carregar_env()
    from compliance_agent.reporting import inteligencia as it

    res = asyncio.run(it.montar(cnpj=alvo, empresa=alvo, salvar=True, retornar_ctx=True))
    if not res.get("ok"):
        return res
    ctx = res.get("_ctx") or {}
    nome = res.get("empresa") or ctx.get("nome") or alvo
    cnpj_fmt = res.get("cnpj_fmt") or ctx.get("cnpj_fmt") or ""
    data = ctx.get("data") or date.today().isoformat()
    grau = res.get("grau_lex") or res.get("risco") or "—"

    jfn_md = _ler(res.get("path_md", ""))
    lex_md = _ler(res.get("path_lex_md", ""))

    # capítulo I (HERMES): fatos do fornecedor (reusa a compilação do raciocínio de fornecedor)
    fatos = _fatos_fornecedor(ctx)
    hermes_md, hermes_ok = _capitulo_hermes(fatos, f"{nome} ({cnpj_fmt})")

    return _assemblar(
        tipo="relatorio", titulo=f"RELATÓRIO CONSOLIDADO DE INTELIGÊNCIA — {nome}",
        subtitulo=f"Fornecedor · CNPJ {cnpj_fmt} · execução, due diligence e parecer jurídico",
        data=data, grau=grau, alvo_slug=_slug(nome) or res.get("cnpj", ""), nome=nome,
        hermes_md=hermes_md, hermes_ok=hermes_ok, jfn_md=jfn_md, lex_md=lex_md,
        enviar=enviar, extra={"cnpj": res.get("cnpj"), "empresa": nome})


def _fatos_fornecedor(ctx: dict) -> str:
    """Compila os FATOS de fornecedor p/ o capítulo Hermes. Reusa o compilador do módulo de fornecedor
    quando existir; senão, um resumo determinístico mínimo (sem inventar)."""
    try:
        from compliance_agent.reporting import inteligencia as it
        for fn in ("_fatos_fornecedor", "_fatos", "_fatos_para_raciocinio"):
            f = getattr(it, fn, None)
            if callable(f):
                txt = f(ctx)
                if txt and txt.strip():
                    return txt
    except Exception as exc:  # noqa: BLE001
        _log.warning("seção %s do consolidado falhou (some do relatório): %s", fn, exc)
    from compliance_agent.reporting.inteligencia import moeda
    p = ctx.get("pagamentos") or {}
    nome = ctx.get("nome", "—")
    if not p.get("tem_dados"):
        return f"- Fornecedor {nome}: sem Ordens Bancárias na base local."
    return (f"- Fornecedor: {nome} (CNPJ {ctx.get('cnpj_fmt','—')}).\n"
            f"- Execução (OB): R$ {moeda(p.get('total_geral',0))} em {p.get('n_geral',0)} ordens bancárias.\n"
            f"- Risco recalibrado JFN: {ctx.get('risco','—')} (score {ctx.get('score','—')}).")


# ───────────────────────────── montagem comum ─────────────────────────────

def _assemblar(*, tipo: str, titulo: str, subtitulo: str, data: str, grau: str, alvo_slug: str,
               nome: str, hermes_md: str, hermes_ok: bool, jfn_md: str, lex_md: str,
               enviar: bool, extra: dict) -> dict:
    """Costura os 3 capítulos num markdown, renderiza UM PDF Kroll e (opcional) envia ao Yoda."""
    capitulos = [
        {"rotulo": "CAPÍTULO I — HERMES",
         "desc": "análise multi-IA de fraude" + ("" if hermes_ok else " (INDISPONÍVEL nesta geração)")},
        {"rotulo": "CAPÍTULO II — JFN",
         "desc": "inteligência: dados, concentração, due diligence, contratos por fornecedor, tabela de pagamentos"},
        {"rotulo": "CAPÍTULO III — LEX",
         "desc": "parecer jurídico: red flags R1-R12, auditoria de contrato T01-T22, sanções, grau"},
    ]
    # capítulo II/III recebem o título de capítulo no topo; o md do módulo entra como subseções. O 1º '# '
    # do módulo (seu próprio título) é DEMOVIDO para não duplicar o banner de capítulo (collisão de H1).
    jfn_cap = ("# CAPÍTULO II — JFN\n\n*Inteligência de execução · concentração · due diligence · "
               "contratos · pagamentos*\n\n" + (_demover_titulo(jfn_md) or "> **INDISPONÍVEL** — capítulo JFN não gerado."))
    lex_cap = ("# CAPÍTULO III — LEX\n\n*Parecer jurídico · red flags R1-R12 · auditoria de contrato "
               "T01-T22 · sanções · grau*\n\n" + (_demover_titulo(lex_md) or "> **INDISPONÍVEL** — parecer LEX não gerado."))
    corpo_md = "\n\n".join([hermes_md, jfn_cap, lex_cap])

    _REPORTS.mkdir(parents=True, exist_ok=True)
    base = f"consolidado_{tipo}_{alvo_slug}_{data}"
    path_md = _REPORTS / f"{base}.md"
    full_md = f"# {titulo}\n\n*{subtitulo}*\n\n**Data:** {data}  |  **Grau (LEX):** {grau}\n\n---\n\n" + corpo_md
    path_md.write_text(full_md, encoding="utf-8")

    html = _html_consolidado(titulo, subtitulo, data, grau, capitulos, corpo_md)
    path_pdf = ""
    try:
        path_pdf = asyncio.run(_render_pdf(html, str(_REPORTS / f"{base}.pdf")))
    except Exception as exc:  # noqa: BLE001
        _log.warning("PDF consolidado falhou: %s", exc)

    enviado = False
    if enviar and path_pdf:
        cap = f"📄 Relatório consolidado — {nome} (grau {_grau_norm(grau)})"
        r = asyncio.run(_enviar_yoda(path_pdf, cap))
        enviado = bool(r.get("ok"))

    return {"ok": True, **extra, "grau": grau, "path_md": str(path_md), "path_pdf": path_pdf,
            "capitulos": capitulos, "hermes_disponivel": hermes_ok, "enviado": enviado}


# ───────────────────────────── CLI ─────────────────────────────

if __name__ == "__main__":
    import json
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "orgao":
        cod = "".join(ch for ch in args[1] if ch.isdigit())
        r = gerar_consolidado_orgao(ug=args[1] if cod else None, orgao=None if cod else args[1], enviar=False)
    elif len(args) >= 2 and args[0] == "relatorio":
        r = gerar_consolidado_relatorio(args[1], enviar=False)
    else:
        print("uso: consolidado {orgao <ug|nome> | relatorio <cnpj|nome>}")
        sys.exit(2)
    print(json.dumps({k: v for k, v in r.items() if k != "_ctx"}, ensure_ascii=False, indent=2, default=str))
