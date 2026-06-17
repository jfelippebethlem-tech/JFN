#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sei_arvore_build — CONSOLIDA cada árvore de processo SEI num TXT que o Lex lê para avaliar.

Para cada processo SEI com ficha real (cache `data/sei_cache/*.json`), escreve um **dossiê consolidado**
em `data/sei_trees/<numero>.txt` reunindo o que o Lex precisa para avaliar direcionamento/legalidade SEM
re-ler o processo inteiro:
  • a FICHA (objeto, modalidade, fundamento legal, valores, partes, red_flags, analise, nivel_risco);
  • os DOCUMENTOS-chave (edital/contrato/parecer/ETP/…), com o ponto relevante de cada;
  • a CADEIA / árvore (processos relacionados/pai citados — execução↔contratação);
  • os PAGAMENTOS reais (OBs do `compliance.db` ligadas ao processo, via `correlacao_sei`): total, período, favorecidos.

Também grava a tabela **`sei_arvore`** (índice queryável: nº, n_membros, n_obs, total_pago, fornecedores,
nivel_risco, caminho do txt) para o Lex/relatórios localizarem a árvore certa.

ATUALIZA a cada sweep (idempotente: reescreve o txt e UPSERT na tabela). VM-safe (busy_timeout). Honesto:
processos sem ficha (bloqueados/restritos/vazios) não viram dossiê.

Uso: PYTHONPATH=. .venv/bin/python -m tools.sei_arvore_build [--limite N]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "data" / "sei_cache"
TREES = REPO / "data" / "sei_trees"
DB = REPO / "data" / "compliance.db"

_DDL = """
CREATE TABLE IF NOT EXISTS sei_arvore (
  numero_sei    TEXT PRIMARY KEY,
  objeto        TEXT,
  nivel_risco   TEXT,
  n_membros     INTEGER,
  n_docs        INTEGER,
  n_obs         INTEGER,
  total_pago    REAL,
  fornecedores  TEXT,   -- JSON [{cnpj,nome,valor}]
  lifecycle     TEXT,   -- 'encerrado_indicio' | 'ativo' | '' (CONSERVADOR — indício, não veredito)
  ultima_ob     TEXT,   -- data do último pagamento (recência)
  situacao      TEXT,   -- situação AUTORITATIVA da ficha (arquivado/concluido/em andamento/'') — read-time
  encerrado     INTEGER DEFAULT 0,  -- gate FIRME de skip (1 só com sinal autoritativo + corroboração negativa)
  txt_path      TEXT,
  atualizado_em TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_sei_arvore_risco ON sei_arvore(nivel_risco);
CREATE INDEX IF NOT EXISTS ix_sei_arvore_total ON sei_arvore(total_pago);
"""

# Marcadores de ENCERRAMENTO nas peças/objeto/resumo da ficha (sinal forte, mas indício — não veredito).
_FECHOU = ("termo de encerramento", "encerramento do processo", "arquivamento", "arquivad",
           "processo concluíd", "processo concluid", "extinção do", "baixa do processo", "rescisão", "rescindid")
# Marcadores de ATIVIDADE (mantém vivo): aditivo/prorrogação => contrato ainda corre.
_VIVO = ("aditivo", "prorrog", "termo aditivo", "repactuaç")


def _norm_situacao(s: str) -> str:
    """Normaliza a SITUAÇÃO AUTORITATIVA da ficha (capturada no read-time) p/
    {'arquivado','concluido','em andamento',''}. Honesto: o que não casa vira '' (desconhecido)."""
    t = (s or "").strip().lower()
    if not t:
        return ""
    if "arquiv" in t:
        return "arquivado"
    if "conclu" in t or "encerr" in t:
        return "concluido"
    if "andamento" in t or "tramit" in t or "vigente" in t or "ativo" in t:
        return "em andamento"
    return ""


def _filho_vigente(rec: dict) -> bool:
    """SAFEGUARD pai-com-filho-vigente: True se QUALQUER filho da cadeia (relacionados lidos) tem marcador
    de vigência (aditivo/prorrogação/repactuação) no texto/título. Um pai com filho ainda em curso NUNCA
    pode ser tratado como encerrado (pai pode ter filhos encerrados E vigentes — regra do dono 'não errar')."""
    for rel in (rec.get("cadeia") or []):
        if not isinstance(rel, dict):
            continue
        blob = (str(rel.get("texto") or "") + " " + str(rel.get("titulo_rel") or "")
                + " " + str(rel.get("titulo") or "")).lower()
        if any(m in blob for m in _VIVO):
            return True
    return False


def _lifecycle(ficha: dict, obs: list[dict], rec: dict | None = None) -> tuple[str, str, str, bool]:
    """CONSERVADOR (regra do dono 'não pode errar'). Retorna (lifecycle, ultima_ob, situacao, encerrado):
      • `situacao`: sinal AUTORITATIVO da ficha (read-time) normalizado — '' se não declarado.
      • `lifecycle`: indício informacional — 'ativo' (OB recente/aditivo/situação em andamento),
        'encerrado_indicio' (marcador de fecho no texto) ou '' (desconhecido).
      • `encerrado`: flag FIRME p/ decidir skip — SÓ True com situação autoritativa arquivado/concluído E
        sem OB recente (≤18m) E sem aditivo próprio E sem filho vigente na cadeia. Tudo o mais é False."""
    import datetime as _dt
    blob = " ".join(str(ficha.get(k) or "") for k in ("objeto", "resumo", "analise")).lower()
    for d in (ficha.get("documentos") or []):
        if isinstance(d, dict):
            blob += " " + str(d.get("tipo", "")).lower() + " " + str(d.get("ponto", "")).lower()
    datas_ob = [str(o.get("data_pagamento") or "")[:10] for o in obs if o.get("data_pagamento")]
    ultima = max(datas_ob) if datas_ob else ""
    recente = False
    if ultima:
        try:
            recente = (_dt.date.today() - _dt.date.fromisoformat(ultima)).days <= 548  # ~18 meses
        except ValueError:
            recente = False
    tem_aditivo = any(m in blob for m in _VIVO)
    fechou = any(m in blob for m in _FECHOU)
    situacao = _norm_situacao(ficha.get("situacao") or "")
    filho_vivo = _filho_vigente(rec or {})
    # lifecycle (indício): situação autoritativa em andamento, OB recente ou aditivo => ativo
    if situacao == "em andamento" or recente or tem_aditivo or filho_vivo:
        lifecycle = "ativo"
    elif situacao in ("arquivado", "concluido") or fechou:
        lifecycle = "encerrado_indicio"
    else:
        lifecycle = ""
    # encerrado FIRME (gate de skip): exige o sinal AUTORITATIVO + corroboração negativa total.
    encerrado = bool(
        situacao in ("arquivado", "concluido")
        and not recente and not tem_aditivo and not filho_vivo)
    return lifecycle, ultima, situacao, encerrado


def _safe(numero: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]", "_", numero) or "sem_numero"


def _moeda(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _digest_txt(numero: str, ficha: dict, rec: dict, obs: list[dict]) -> tuple[str, dict]:
    """Monta o TXT do dossiê + um resumo (métricas p/ a tabela)."""
    def _lst(k):
        v = ficha.get(k) or []
        return v if isinstance(v, list) else [v]
    L = [f"DOSSIÊ DE PROCESSO SEI — {numero}", "=" * 70, ""]
    L.append(f"OBJETO: {ficha.get('objeto') or '—'}")
    if ficha.get("modalidade"):
        L.append(f"MODALIDADE: {ficha['modalidade']}")
    if ficha.get("fundamento_legal"):
        L.append(f"FUNDAMENTO LEGAL: {ficha['fundamento_legal']}")
    if ficha.get("nivel_risco"):
        L.append(f"NÍVEL DE RISCO (interno, indício≠acusação): {ficha['nivel_risco']}")
    if ficha.get("analise"):
        L.append(f"\nANÁLISE (auditoria): {ficha['analise']}")
    if ficha.get("resumo"):
        L.append(f"RESUMO: {ficha['resumo']}")
    valores = _lst("valores")
    if valores:
        L.append(f"\nVALORES citados: {', '.join(str(v) for v in valores)}")
    partes = _lst("partes")
    if partes:
        L.append(f"PARTES: {', '.join(str(p) for p in partes)}")
    rf = _lst("red_flags")
    if rf:
        L.append("\nRED FLAGS (verificar):")
        L += [f"  - {x}" for x in rf]
    docs = ficha.get("documentos") or []
    if docs:
        L.append(f"\nDOCUMENTOS-CHAVE ({len(docs)}):")
        for d in docs:
            if isinstance(d, dict):
                L.append(f"  - [{d.get('tipo','?')}] {d.get('ponto','')}")
    # cadeia / árvore (processos relacionados)
    cadeia = rec.get("cadeia") or []
    rel = rec.get("relacionados") or []
    if cadeia or rel:
        membros = cadeia or rel
        L.append(f"\nÁRVORE / RELACIONADOS ({len(membros)}):")
        _re_sei = re.compile(r"SEI[-\s]?\d{6}[/-]\d{6}[/-]\d{4}")
        for m in membros:
            if not isinstance(m, dict):
                continue
            _tit_raw = (m.get("titulo_rel") or m.get("titulo") or "").strip()
            tit = _tit_raw.splitlines()[0][:80] if _tit_raw else ""  # "".splitlines()==[] → guarda contra IndexError
            bruto = m.get("texto") or m.get("id_procedimento") or ""
            achou = _re_sei.search(bruto or "")           # evita despejar o menu lateral do SEI
            ref = achou.group(0) if achou else (m.get("id_procedimento") or "ref?")
            L.append(f"  - {ref}{(' · ' + tit) if tit else ''}".rstrip())
    # pagamentos reais (OB = verdade)
    total = sum(float(o.get("valor") or 0) for o in obs)
    fornec: dict[str, dict] = {}
    if obs:
        anos = sorted({str(o.get("exercicio") or "") for o in obs if o.get("exercicio")})
        L.append(f"\nPAGAMENTOS (OB — verdade de pagamento): {len(obs)} OB · {_moeda(total)}"
                 + (f" · exercícios {', '.join(anos)}" if anos else ""))
        for o in obs:
            cpf = (o.get("favorecido_cpf") or "").strip()
            nome = (o.get("favorecido_nome") or "").strip()
            e = fornec.setdefault(cpf, {"cnpj": cpf, "nome": nome, "valor": 0.0})
            e["valor"] += float(o.get("valor") or 0)
        for e in sorted(fornec.values(), key=lambda x: -x["valor"])[:12]:
            L.append(f"  - {e['nome']} ({e['cnpj']}): {_moeda(e['valor'])}")
    else:
        L.append("\nPAGAMENTOS: nenhuma OB vinculada a este processo (INDISPONÍVEL ≠ 0).")
    lifecycle, ultima_ob, situacao, encerrado = _lifecycle(ficha, obs, rec)
    if lifecycle or situacao:
        rotulo = {"encerrado_indicio": "INDÍCIO DE ENCERRADO (verificar — não sweepar à toa)",
                  "ativo": "ATIVO (OB recente, aditivo, filho vigente ou situação em andamento)"}.get(lifecycle, lifecycle or "—")
        extra = (f" · situação autoritativa: {situacao}" if situacao else "")
        if encerrado:
            extra += " · ENCERRADO (gate de skip: autoritativo + sem OB recente/aditivo/filho vigente)"
        L.insert(2, f"LIFECYCLE: {rotulo}{extra}" + (f" · última OB {ultima_ob}" if ultima_ob else ""))
    L.append(f"\n— fonte: ficha nous {rec.get('_ficha_modelo','')} · lido {rec.get('_cached_at','')} —")
    resumo = {"objeto": ficha.get("objeto") or "", "nivel_risco": ficha.get("nivel_risco") or "",
              "n_membros": len(cadeia or rel), "n_docs": len(docs), "n_obs": len(obs),
              "total_pago": total, "fornecedores": list(fornec.values()),
              "lifecycle": lifecycle, "ultima_ob": ultima_ob,
              "situacao": situacao, "encerrado": 1 if encerrado else 0}
    return "\n".join(L) + "\n", resumo


def construir(limite: int = 0) -> dict:
    from compliance_agent import correlacao_sei
    TREES.mkdir(exist_ok=True)
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(_DDL)
    # migração aditiva: garante colunas novas em tabelas já existentes (idempotente)
    cols = {r[1] for r in con.execute("PRAGMA table_info(sei_arvore)")}
    for c in ("lifecycle TEXT", "ultima_ob TEXT", "situacao TEXT", "encerrado INTEGER DEFAULT 0"):
        if c.split()[0] not in cols:
            con.execute(f"ALTER TABLE sei_arvore ADD COLUMN {c}")
    con.execute("CREATE INDEX IF NOT EXISTS ix_sei_arvore_life ON sei_arvore(lifecycle)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_sei_arvore_enc ON sei_arvore(encerrado)")
    cur = con.cursor()
    arquivos = [p for p in CACHE.glob("*.json")
                if "checkpoint" not in p.name and "progress" not in p.name]
    feitos = pulados = 0
    for p in arquivos:
        if limite and feitos >= limite:
            break
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        ficha = rec.get("ficha") if isinstance(rec, dict) else None
        if not isinstance(ficha, dict) or ficha.get("_erro"):
            pulados += 1
            continue
        numero = (rec.get("numero") or ficha.get("numero") or "").strip()
        if not numero:
            pulados += 1
            continue
        try:
            obs = correlacao_sei.obs_por_processo(numero)
        except Exception:  # noqa: BLE001
            obs = []
        txt, r = _digest_txt(numero, ficha, rec, obs)
        path = TREES / f"{_safe(numero)}.txt"
        path.write_text(txt, encoding="utf-8")
        cur.execute(
            """INSERT INTO sei_arvore
               (numero_sei,objeto,nivel_risco,n_membros,n_docs,n_obs,total_pago,fornecedores,lifecycle,ultima_ob,situacao,encerrado,txt_path,atualizado_em)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(numero_sei) DO UPDATE SET objeto=excluded.objeto,nivel_risco=excluded.nivel_risco,
                 n_membros=excluded.n_membros,n_docs=excluded.n_docs,n_obs=excluded.n_obs,
                 total_pago=excluded.total_pago,fornecedores=excluded.fornecedores,lifecycle=excluded.lifecycle,
                 ultima_ob=excluded.ultima_ob,situacao=excluded.situacao,encerrado=excluded.encerrado,
                 txt_path=excluded.txt_path,atualizado_em=datetime('now')""",
            (numero, r["objeto"], r["nivel_risco"], r["n_membros"], r["n_docs"], r["n_obs"],
             r["total_pago"], json.dumps(r["fornecedores"], ensure_ascii=False),
             r["lifecycle"], r["ultima_ob"], r["situacao"], r["encerrado"], str(path)))
        feitos += 1
    con.commit()
    total_db = cur.execute("SELECT COUNT(*) FROM sei_arvore").fetchone()[0]
    com_ob = cur.execute("SELECT COUNT(*) FROM sei_arvore WHERE n_obs>0").fetchone()[0]
    encerr = cur.execute("SELECT COUNT(*) FROM sei_arvore WHERE encerrado=1").fetchone()[0]
    con.close()
    return {"arquivos": len(arquivos), "dossies": feitos, "pulados": pulados,
            "no_db": total_db, "com_pagamento": com_ob, "encerrados": encerr}


def arvores_encerradas(db_path: Path | str | None = None) -> set[str]:
    """Conjunto dos nº SEI com `encerrado=1` na tabela `sei_arvore` — o GATE FIRME de skip do sweep diário.
    São processos com situação AUTORITATIVA arquivado/concluído, sem OB recente, sem aditivo e sem filho
    vigente (a corroboração já foi exigida no build). Vale só na fase 'update diário', NUNCA no drain inicial.
    Honesto: se a tabela não existe (base nova), retorna conjunto VAZIO (não pula nada)."""
    dbp = Path(db_path) if db_path else DB
    if not dbp.exists():
        return set()
    con = sqlite3.connect(str(dbp), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sei_arvore'").fetchone():
            return set()
        cols = {r[1] for r in con.execute("PRAGMA table_info(sei_arvore)")}
        if "encerrado" not in cols:
            return set()
        return {r[0] for r in con.execute(
            "SELECT numero_sei FROM sei_arvore WHERE encerrado=1 AND numero_sei IS NOT NULL")}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=0, help="máx dossiês (0=todos)")
    a = ap.parse_args()
    r = construir(limite=a.limite)
    print(f"[sei_arvore] arquivos={r['arquivos']} · dossiês={r['dossies']} · pulados={r['pulados']} · "
          f"no_db={r['no_db']} · com_pagamento_OB={r['com_pagamento']} · encerrados(gate skip)={r['encerrados']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
