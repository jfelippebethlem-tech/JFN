#!/usr/bin/env python3
"""Pista APROFUNDADA (segunda opinião forte) — SÓ nos contratos PRIORITÁRIOS do FUNESBOM.

deepseek-v4-pro (NVIDIA NIM) reanalisa a execução com a MESMA perícia calibrada do lex_execucao
(reusa _SYS/_SCHEMA/_flags/_regras_calibracao), gravando em tabela SEPARADA `lex_aprofundado` para
comparar Lex-fraco × deepseek-forte SEM destruir o baseline.

Custo (§4.1): NVIDIA NIM, guardado pelo cap mensal de `nvidia` (_cap_ok/_cap_inc). ~50s/caso → por isso
é ON-DEMAND (NÃO entra no auto-loop do supervisor) e com --top pequeno.

Uso: cd ~/JFN && PYTHONPATH=. .venv/bin/python -m tools.lex_bombeiros_aprofundado [--top N]
"""
import os, sqlite3, json, time, argparse, httpx
from pathlib import Path
import tools.lex_execucao as L  # reusa _SYS, _SCHEMA, _flags, _parse_json, _regras_calibracao, _agora
from compliance_agent.llm.free_llm import _cap_ok, _cap_inc, _envk

DB = "/home/ubuntu/JFN/data/compliance.db"
FILA = "/home/ubuntu/JFN/data/bombeiros_sei_fila.json"
MODEL = os.environ.get("DEEPSEEK_LANE_MODEL", "deepseek-ai/deepseek-v4-pro")
NIM = "https://integrate.api.nvidia.com/v1/chat/completions"


def _load_env() -> None:
    """Carrega .env p/ os.environ (idempotente) — o tool roda standalone, sem o wrapper dos serviços."""
    try:
        for ln in Path("/home/ubuntu/JFN/.env").read_text(encoding="utf-8", errors="ignore").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass


def _gerar_deepseek(prompt: str, system: str, timeout: float = 150.0) -> str:
    key = _envk("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY")
    if not key:
        raise RuntimeError("NVIDIA key ausente")
    r = httpx.post(NIM, headers={"Authorization": f"Bearer {key}"},
                   json={"model": MODEL, "temperature": 0.1, "max_tokens": 1500,
                         "messages": [{"role": "system", "content": system},
                                      {"role": "user", "content": prompt}]}, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    msg = j["choices"][0]["message"]
    tok = (j.get("usage") or {}).get("total_tokens")
    return (msg.get("content") or msg.get("reasoning_content") or ""), tok


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("""CREATE TABLE IF NOT EXISTS lex_aprofundado (
        numero_sei TEXT PRIMARY KEY, objeto TEXT, execucao_comprovada TEXT, coerencia TEXT,
        nota_risco INTEGER, indicios TEXT, duvidas TEXT, resumo TEXT, modelo TEXT, em TEXT,
        lat_s REAL, tokens INTEGER)""")
    return con


def _alvos(con: sqlite3.Connection, top: int, reavaliar: bool) -> list:
    """Prioritários = bombeiros com docs, NÃO monopólio_legítimo, ordem de score da fila; pula já-feitos."""
    fila = {x["sei"]: x for x in json.load(open(FILA))}
    ja = set() if reavaliar else {r[0] for r in con.execute("SELECT numero_sei FROM lex_aprofundado")}
    rows = con.execute("SELECT numero_sei,objeto,valores,documentos,red_flags FROM sei_ficha "
                       "WHERE n_docs>0 AND numero_sei LIKE 'SEI-2700%'").fetchall()
    cand = []
    for ns, obj, val, docs, rf in rows:
        if ns in ja:
            continue
        meta = fila.get(ns)
        if not meta or "monopolio_legitimo" in (meta.get("flags") or []):
            continue
        try:
            score = int(float(meta.get("score") or 0))
        except Exception:
            score = 0
        cand.append((score, ns, obj, val, docs, rf))
    cand.sort(key=lambda x: -x[0])
    return cand[:top]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--reavaliar", action="store_true")
    a = ap.parse_args()
    _load_env()
    if not _cap_ok("nvidia"):
        print("[aprofundado] cap mensal NVIDIA atingido (§4.1) — abortando (nada gasto).")
        return
    con = _con()
    try:
        regras = L._regras_calibracao()
        alvos = _alvos(con, a.top, a.reavaliar)
        print(f"[aprofundado] {len(alvos)} prioritários · modelo {MODEL} (~50s/caso · cap §4.1)")
        feitos = 0
        for score, ns, obj, val, docs, rf in alvos:
            if not _cap_ok("nvidia"):
                print("  cap NVIDIA atingido — parando."); break
            try:
                dl = json.loads(docs or "[]")
            except Exception:
                dl = []
            try:
                rfl = json.loads(rf or "[]")
            except Exception:
                rfl = []
            dl = dl if isinstance(dl, list) else []
            fl = L._flags(dl)
            docs_txt = "\n".join(f"- [{d.get('tipo','?')}] {d.get('ponto','')}" for d in dl[:40] if isinstance(d, dict))
            prompt = (f"OBJETO CONTRATADO: {obj or '(n/d)'}\nVALORES: {val or '(n/d)'}\n"
                      f"RED FLAGS já anotadas: {rfl or '[]'}\nPRESENÇA DETECTADA (1=sim): {fl}\n\n"
                      f"DOCUMENTOS DO PROCESSO ({len(dl)}):\n{docs_txt or '(nenhum)'}\n\n"
                      f"LIÇÕES DE CALIBRAÇÃO DA PERÍCIA (aplique antes de pontuar):\n{regras}\n\n"
                      f"Avalie se a execução está comprovada e coerente com o objeto/quantidade. Árvore rasa "
                      f"(poucos docs, só empenho/envio-TCE/despacho) → 'indeterminado' e nota ≤4. "
                      f"Responda SOMENTE o JSON: {L._SCHEMA}")
            t = time.time()
            try:
                txt, tok = _gerar_deepseek(prompt, L._SYS)
            except Exception as e:
                print(f"  {ns}: erro {str(e)[:70]}"); continue
            dt = time.time() - t
            _cap_inc("nvidia")
            r = L._parse_json(txt) or {}
            nota = r.get("nota_risco_execucao")
            try:
                nota = int(nota)
            except Exception:
                nota = None
            con.execute("""INSERT INTO lex_aprofundado
                (numero_sei,objeto,execucao_comprovada,coerencia,nota_risco,indicios,duvidas,resumo,modelo,em,lat_s,tokens)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(numero_sei) DO UPDATE SET objeto=excluded.objeto,
                execucao_comprovada=excluded.execucao_comprovada, coerencia=excluded.coerencia,
                nota_risco=excluded.nota_risco, indicios=excluded.indicios, duvidas=excluded.duvidas,
                resumo=excluded.resumo, modelo=excluded.modelo, em=excluded.em, lat_s=excluded.lat_s, tokens=excluded.tokens""",
                (ns, obj, r.get("execucao_comprovada"), r.get("coerencia_objeto_evidencia"), nota,
                 json.dumps(r.get("indicios") or [], ensure_ascii=False),
                 json.dumps(r.get("duvidas") or [], ensure_ascii=False),
                 r.get("resumo"), MODEL, L._agora(), round(dt, 1), tok))
            con.commit()
            w = con.execute("SELECT nota_risco FROM lex_execucao WHERE numero_sei=?", (ns,)).fetchone()
            wn = w[0] if w else None
            div = "  <DIVERGE>" if (wn is not None and nota is not None and abs(float(wn) - nota) >= 3) else ""
            print(f"  {ns} [{dt:4.0f}s {tok}tok] lex-fraco={wn} → deepseek={nota} ({r.get('execucao_comprovada')}){div}")
            feitos += 1
        print(f"[aprofundado] concluídos: {feitos}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
