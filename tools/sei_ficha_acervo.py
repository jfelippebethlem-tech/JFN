# -*- coding: utf-8 -*-
"""sei_ficha_acervo — FICHA SEI a partir do ACERVO (`data/sei_arquivo`), em LOTE pela API (Haiku, Batch, 50%).

POR QUE EXISTE. A ficha (`sei_ficha`) só nascia do cache de varredura do browser (`sei_cache/cdp_SEI_*.json` →
`sei_refichar` → `sei_depurar_db`). Desde que a captura passou a vir das ÍNTEGRAS dos nós (VM-2, it-campo — 14/11/2026),
o processo entra no acervo SEM cache, e ninguém o fichava: medido em 14/11/2026, 3.730 dos 6.418 processos do acervo
sem ficha, e por consequência sem `lex_execucao` (que lê a ficha). O ritmo do caminho antigo era ~60 fichas/dia.

O QUE FAZ, e onde mora cada garantia (diretriz do dono, 13/11/2026: "não pode ter margem pra erro em nada"):
  1. FILA pelo VALOR PAGO (OB `Contabilizado` no SIAFE, `lex_execucao.mapa_obs_siafe`), depois pelo tamanho do texto.
  2. TEXTO por VALOR FISCALIZATÓRIO (`classificador_doc.ordenar_para_leitura`, nunca os N primeiros da árvore), sem a
     etiqueta da casa (`acervo_texto.ler`), cada peça com o cabeçalho `=== DOCUMENTO: <título> ===` que a ficha cita.
     Teto DECLARADO (`TETO_TOTAL`/`TETO_DOC`); o que ficou de fora vai contado em `verificacao`.
  3. EXTRAÇÃO pelo prompt canônico da ficha (`tools/sei_ficha`: mesmo schema, mesmo exemplo) — Haiku 5.5 pela Batch
     API, balde `extracao_sei` do `claude_api` (teto em dólar, reserva antes de enviar). Nunca Opus pela API.
  4. CONFERÊNCIA POR CÓDIGO contra o texto (`llm/verificacao`): documento só entra com o trecho LITERAL achado na
     fonte; red flag só com a citação `[Doc: … — "trecho"]` achada; valor/CNPJ/data/parte só se aparecem no texto.
     O resto é DESCARTADO, nunca corrigido — e contado.
  4b. NÍVEL DE RISCO NÃO É GRAVADO: o piloto (14/11/2026) deu 51 "alto" e 54 "médio" em 111 fichas — conta de luz
     da concessionária por inexigibilidade saiu "alto". A citação confere, a INFERÊNCIA não. O palpite do modelo
     fica em `verificacao.nivel_risco_modelo`; a coluna `nivel_risco` fica "" (não avaliado) — quem gradua é a
     camada de juízo (perícia de execução, Processo 360), nunca o modelo barato.
  5. A ficha continua sendo ÍNDICE DE TRIAGEM (ver o cabeçalho de `tools/sei_ficha`): nada daqui vira 🔴/🟡 sem a
     camada de juízo por cima. `fonte_modelo` = `claude-haiku-5-5@api-lote#acervo-v1`.

    PYTHONPATH=. .venv/bin/python -m tools.sei_ficha_acervo --estado
    PYTHONPATH=. .venv/bin/python -m tools.sei_ficha_acervo --ciclo --lote 400     # colhe o que terminou e envia
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from compliance_agent.llm import verificacao as V
from compliance_agent.sei import acervo_texto
from compliance_agent.sei.classificador_doc import ordenar_para_leitura

REPO = Path(__file__).resolve().parents[1]
ACERVO = REPO / "data" / "sei_arquivo"
DB = REPO / "data" / "compliance.db"
ESTADO = REPO / "data" / "sei_ficha_acervo_estado.json"
TAREFA = "extracao_sei"
VERSAO = "acervo-v1"
TETO_TOTAL = 60_000        # caracteres por processo (~17k tokens): cabe no preço curto do Haiku (≤100k tokens)
TETO_DOC = 8_000           # por peça: uma peça gigante não come a janela das outras
MIN_TEXTO = 400            # abaixo disto não há o que fichar (capa/recibo) — fica fora da fila, contado
MAX_TENTATIVAS = 2         # resposta inválida 2× = sai da fila automática e aparece em --estado
# Piloto de 14/11/2026 (200 processos): com 8.000, 87 respostas cortaram no teto (raciocínio + JSON da ficha passam
# de 6.000 tokens em quase todas) — custo pago e nada aproveitado. 16.000 cabe; o custo é o que a resposta usa.
MAX_TOKENS = 16_000


def _dig(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def numero_da_pasta(nome: str) -> str:
    p = nome.split("_")
    return f"SEI-{p[0]}/{p[1]}/{p[2]}" if len(p) >= 3 else nome


# ── texto ─────────────────────────────────────────────────────────────────────────────────────────────
def texto_para_ficha(pasta: Path) -> tuple[str, dict]:
    """(texto rotulado por documento, cobertura). Ordem = valor fiscalizatório; árvore preservada na faixa."""
    try:
        man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        man = {}
    docs = [d for d in (man.get("docs") or []) if isinstance(d, dict) and d.get("texto")]
    if not docs:   # acervo antigo sem manifesto: os arquivos na ordem do nome, o título é o nome do arquivo
        docs = [{"titulo": f.stem, "texto": f"texto/{f.name}"} for f in sorted((pasta / "texto").glob("*.txt"))]
    partes, total, lidos, cortados = [], 0, 0, 0
    for d in ordenar_para_leitura(docs):
        t = acervo_texto.ler(pasta, d).strip()
        if len(t) < 40:
            continue
        if total >= TETO_TOTAL:
            cortados += 1
            continue
        t = t[: min(TETO_DOC, TETO_TOTAL - total)]
        partes.append(f"=== DOCUMENTO: {str(d.get('titulo') or '').strip() or '(sem título)'} ===\n{t}")
        total += len(t)
        lidos += 1
    return "\n\n".join(partes), {"docs_com_texto": len(docs), "docs_lidos": lidos, "docs_fora_do_teto": cortados,
                                 "chars": total}


# ── fila ──────────────────────────────────────────────────────────────────────────────────────────────
def _ler_estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"lotes": {}, "tentativas": {}, "pequenos": []}


def _gravar_estado(e: dict) -> None:
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ESTADO)


def _bytes_texto(pasta: Path) -> int:
    t = pasta / "texto"
    return sum(f.stat().st_size for f in t.glob("*.txt")) if t.is_dir() else 0


def fila(con: sqlite3.Connection, estado: dict) -> list[dict]:
    """Pastas do acervo sem ficha, com texto, fora de lote em curso — por valor pago (SIAFE) e depois tamanho."""
    from tools.lex_execucao import _chave_processo, mapa_obs_siafe
    com_ficha = {_dig(r[0]) for r in con.execute("SELECT numero_sei FROM sei_ficha")}
    em_lote = {cid for ids in estado.get("lotes", {}).values() for cid in ids}
    esgotados = {k for k, n in estado.get("tentativas", {}).items() if n >= MAX_TENTATIVAS}
    cands = []
    for p in ACERVO.iterdir() if ACERVO.is_dir() else ():
        if not p.is_dir() or _dig(p.name) in com_ficha or p.name in em_lote or p.name in esgotados:
            continue
        tam = _bytes_texto(p)
        if tam < MIN_TEXTO:
            continue
        cands.append({"pasta": p.name, "numero": numero_da_pasta(p.name), "bytes": tam})
    obs = mapa_obs_siafe(con, [c["numero"] for c in cands]) if cands else {}
    for c in cands:
        c["pago"] = round((obs.get(_chave_processo(c["numero"])) or {}).get("total", 0.0), 2)
    cands.sort(key=lambda c: (-c["pago"], -c["bytes"]))
    return cands


# ── prompt (o canônico da ficha, sem o corte de 4.500 caracteres do modelo grátis) ────────────────────────
def sistema_e_prompt(texto: str) -> tuple[str, str]:
    from tools import sei_ficha as F
    sistema = (F._SIST + F._aprendizados_pericia()
               + f"\n\nFormato da FICHA (JSON):\n{F._CAMPOS}\n\n=== EXEMPLO ===\nTEXTO:\n{F._EXEMPLO_TXT}\n"
                 f"FICHA:\n{F._EXEMPLO_FICHA}")
    return sistema, f"=== AGORA (mesmo formato) ===\nTEXTO:\n{texto}\nFICHA:"


# ── conferência por código ────────────────────────────────────────────────────────────────────────────
_FLAG = re.compile(r"^\s*\[\s*Doc:\s*(?P<ref>.*?)\s*[—–-]+\s*[\"“”'](?P<trecho>.+?)[\"“”']\s*\]", re.S)
_RETICENCIAS = re.compile(r"\.\.\.|…|\[\s*\.\.\.\s*\]")
_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}\s*/?\s*\d{4}\s*-?\s*\d{2}")
_MOEDA = re.compile(r"(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+,\d{2}|\d+)")
_DATA = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_SEM_PARENTESE = re.compile(r"\([^)]*\)")


def _nucleo_data(d) -> str:
    m = _DATA.search(str(d or ""))
    n = V._normal(m.group(0) if m else _SEM_PARENTESE.sub("", str(d or "")))
    return n if len(n) >= 6 else ""


def trecho_confere(trecho: str, fonte_normal: str) -> bool:
    """Toda parte do trecho (separada por reticências) com ≥ 8 caracteres está LITERALMENTE na fonte."""
    pedacos = [V._normal(x) for x in _RETICENCIAS.split(str(trecho or ""))]
    pedacos = [x for x in pedacos if len(x) >= 8]
    return bool(pedacos) and all(x in fonte_normal for x in pedacos)


def _cnpjs_do_texto(texto: str) -> set[str]:
    return {_dig(m) for m in re.findall(r"\d{2}\.?\d{3}\.?\d{3}\s*/?\s*\d{4}\s*-?\s*\d{2}", texto or "")}


def conferir(ficha: dict, fonte: str) -> tuple[dict, dict]:
    """(ficha só com o que se confirmou no texto, contagem do que foi descartado). Nunca corrige: descarta."""
    fn = V._normal(fonte)
    rel: dict = {}
    out = dict(ficha)

    docs_ok = [d for d in (ficha.get("documentos") or [])
               if isinstance(d, dict) and trecho_confere(d.get("trecho", ""), fn)]
    rel["documentos"] = [len(docs_ok), len(ficha.get("documentos") or [])]
    out["documentos"] = docs_ok

    flags_ok = []
    for f in ficha.get("red_flags") or []:
        m = _FLAG.match(str(f or ""))
        if m and trecho_confere(m.group("trecho"), fn):
            flags_ok.append(f)
    rel["red_flags"] = [len(flags_ok), len(ficha.get("red_flags") or [])]
    out["red_flags"] = flags_ok

    # O modelo ANOTA os itens ("R$ 988.734,64 (NL 2025NL00384)", "03/06/2025 (NF)", "B&B MED (contratada)") — o
    # piloto perdeu assim 299 de 614 valores verdadeiros. Confere-se o NÚCLEO do item (o valor, a data, o nome sem o
    # parêntese); o item segue gravado como o modelo escreveu, anotação incluída.
    cnpjs_txt = _cnpjs_do_texto(fonte)
    out["cnpjs"] = [c for c in (ficha.get("cnpjs") or []) if (m := _CNPJ.search(str(c)))
                    and _dig(m.group(0)) in cnpjs_txt]
    out["valores"] = [v for v in (ficha.get("valores") or []) if (m := _MOEDA.search(str(v)))
                      and V.numero_no_trecho(m.group(1), fonte)]
    out["datas"] = [d for d in (ficha.get("datas") or []) if (n := _nucleo_data(d)) and n in fn]
    out["partes"] = [p for p in (ficha.get("partes") or []) if len(n := V._normal(_SEM_PARENTESE.sub("", str(p)))) >= 3
                     and n in fn]
    for k in ("cnpjs", "valores", "datas", "partes"):
        rel[k] = [len(out[k]), len(ficha.get(k) or [])]

    from tools.sei_depurar_db import nivel_risco_norm
    rel["nivel_risco_modelo"] = nivel_risco_norm(ficha.get("nivel_risco"))   # palpite do modelo: registro, não nota
    out["nivel_risco"] = ""
    return out, rel


# ── gravação ──────────────────────────────────────────────────────────────────────────────────────────
def _garantir_coluna(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(sei_ficha)")}
    if "verificacao" not in cols:
        con.execute("ALTER TABLE sei_ficha ADD COLUMN verificacao TEXT")


def _escalar(v) -> str:
    if isinstance(v, list):
        return "; ".join(str(x) for x in v if x not in (None, ""))
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return "" if v is None else str(v)


def gravar(con: sqlite3.Connection, numero: str, ficha: dict, verif: dict, modelo: str) -> None:
    """INSERT só se não existir ficha (a do cache, se chegou antes, não é sobrescrita aqui)."""
    js = lambda k: json.dumps(ficha.get(k) or [], ensure_ascii=False)  # noqa: E731
    per = lambda k: json.dumps(ficha[k], ensure_ascii=False) if isinstance(ficha.get(k), dict) else ""  # noqa: E731
    con.execute(
        """INSERT OR IGNORE INTO sei_ficha
           (numero_sei,objeto,modalidade,fundamento_legal,resumo,analise,nivel_risco,situacao,relevante,
            valores,cnpjs,partes,datas,red_flags,documentos,pericia_contabil,pericia_juridica,
            n_docs,fonte_modelo,cached_at,atualizado_em,verificacao)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?)""",
        (numero, *(_escalar(ficha.get(c)) for c in ("objeto", "modalidade", "fundamento_legal", "resumo", "analise")),
         ficha.get("nivel_risco") or "", _escalar(ficha.get("situacao")), 1 if ficha.get("relevante") else 0,
         js("valores"), js("cnpjs"), js("partes"), js("datas"), js("red_flags"), js("documentos"),
         per("pericia_contabil"), per("pericia_juridica"), len(ficha.get("documentos") or []), modelo,
         datetime.now().isoformat(timespec="seconds"), json.dumps(verif, ensure_ascii=False)))


# ── ciclo: colher o que terminou, enviar o próximo lote ───────────────────────────────────────────────
def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    return con


def regravar_lote(lote_id: str) -> dict:
    """Refaz a CONFERÊNCIA de um lote já colhido (resultado guardado em data/claude_api_lotes/, sem nova chamada nem
    custo) — para quando a régua de conferência muda. Só substitui ficha que É do acervo; a do cache fica."""
    from compliance_agent.llm.json_resposta import parse_json_llm
    saida = json.loads((REPO / "data" / "claude_api_lotes" / f"{lote_id}.json").read_text(encoding="utf-8"))
    from compliance_agent.llm import claude_api as C
    modelo = f"{C.MODELO_BARATO}@api-lote#{VERSAO}"
    tot = {"regravadas": 0, "invalidas": 0}
    con = _con()
    try:
        _garantir_coluna(con)
        for pasta, bruto in saida.items():
            ficha = parse_json_llm(bruto) if bruto else None
            if not isinstance(ficha, dict) or ficha.get("_truncado"):
                tot["invalidas"] += 1
                continue
            numero = numero_da_pasta(pasta)
            con.execute("DELETE FROM sei_ficha WHERE numero_sei=? AND fonte_modelo LIKE '%#acervo-%'", (numero,))
            texto, cob = texto_para_ficha(ACERVO / pasta)
            ficha_ok, rel = conferir(ficha, texto)
            gravar(con, numero, ficha_ok, {"versao": VERSAO, "cobertura": cob, "conferido": rel, "lote": lote_id},
                   modelo)
            tot["regravadas"] += 1
        con.commit()
    finally:
        con.close()
    return tot


def colher(estado: dict) -> dict:
    from compliance_agent.llm import claude_api as C
    from compliance_agent.llm.json_resposta import parse_json_llm
    modelo = f"{C.MODELO_BARATO}@api-lote#{VERSAO}"
    tot = {"lotes": 0, "gravadas": 0, "invalidas": 0}
    for lote_id, ids in list(estado.get("lotes", {}).items()):
        res = C.colher_lote(lote_id)
        if res is None:
            continue                                     # em curso
        con = _con()
        try:
            _garantir_coluna(con)
            for pasta in ids:
                bruto = res.get(pasta)
                ficha = parse_json_llm(bruto) if bruto else None
                if not isinstance(ficha, dict) or ficha.get("_truncado"):
                    estado["tentativas"][pasta] = estado.get("tentativas", {}).get(pasta, 0) + 1
                    tot["invalidas"] += 1
                    continue
                texto, cob = texto_para_ficha(ACERVO / pasta)
                ficha_ok, rel = conferir(ficha, texto)
                gravar(con, numero_da_pasta(pasta), ficha_ok, {"versao": VERSAO, "cobertura": cob, "conferido": rel,
                                                               "lote": lote_id}, modelo)
                tot["gravadas"] += 1
            con.commit()
        finally:
            con.close()
        estado["lotes"].pop(lote_id, None)
        tot["lotes"] += 1
        _gravar_estado(estado)
    return tot


def enviar(estado: dict, n: int) -> dict:
    from compliance_agent.llm import claude_api as C
    con = _con()
    try:
        cands = fila(con, estado)
    finally:
        con.close()
    C.registrar_restantes(TAREFA, len(cands))
    itens, sistema = [], ""
    for c in cands[:n]:
        texto, _ = texto_para_ficha(ACERVO / c["pasta"])
        if len(texto) < MIN_TEXTO:
            continue
        sistema, prompt = sistema_e_prompt(texto)
        itens.append((c["pasta"], prompt))
    if not itens:
        return {"enviados": 0, "fila": len(cands)}
    lote = C.enviar_lote(TAREFA, itens, sistema=sistema, max_tokens=MAX_TOKENS, effort="low")
    if not lote:
        return {"enviados": 0, "fila": len(cands), "motivo": C.ultimo_motivo}
    estado.setdefault("lotes", {})[lote] = [cid for cid, _ in itens]
    _gravar_estado(estado)
    return {"enviados": len(itens), "fila": len(cands), "lote": lote,
            "pago_no_lote": round(sum(c["pago"] for c in cands[:n]), 2)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Ficha SEI a partir do acervo, em lote pela API (Haiku)")
    ap.add_argument("--ciclo", action="store_true", help="colhe lotes terminados e envia o próximo")
    ap.add_argument("--lote", type=int, default=400, help="processos por lote")
    ap.add_argument("--max-em-curso", type=int, default=2, help="lotes simultâneos no máximo")
    ap.add_argument("--estado", action="store_true")
    ap.add_argument("--regravar", metavar="LOTE_ID", help="refaz a conferência de um lote já colhido (sem custo)")
    a = ap.parse_args()
    if a.regravar:
        print(json.dumps(regravar_lote(a.regravar), ensure_ascii=False))
        return 0
    estado = _ler_estado()
    estado.setdefault("lotes", {})
    estado.setdefault("tentativas", {})
    if a.estado or not a.ciclo:
        con = _con()
        try:
            n = len(fila(con, estado))
        finally:
            con.close()
        print(json.dumps({"fila": n, "lotes_em_curso": {k: len(v) for k, v in estado["lotes"].items()},
                          "esgotados": sorted(k for k, v in estado["tentativas"].items() if v >= MAX_TENTATIVAS)},
                         ensure_ascii=False))
        return 0
    t0 = time.monotonic()
    r = {"colheita": colher(estado)}
    if len(estado["lotes"]) < a.max_em_curso:
        r["envio"] = enviar(estado, a.lote)
    r["s"] = round(time.monotonic() - t0, 1)
    print(f"[{datetime.now():%F %T}] sei_ficha_acervo {json.dumps(r, ensure_ascii=False)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
