# -*- coding: utf-8 -*-
"""Migração das FILAS LEGADAS de E5–E7 para `fluxo.jobs` / `fluxo.eventos`, com REPLAY sobre o estado congelado da
parada (item O3.4: "0 perda em replay de 30 dias"). Só lê as filas antigas; escreve só no esquema de fluxo pedido.

Filas e registros legados (inventário: ~/vault/refatoracao/inventario-jobs-20261124.md, linhas E5/E6/E7):
  E5  data/sei_ocr_gpu_fila.txt            fila da GPU (`integra_<tag>/NNN.pdf`), sem data: o estado na parada
      data/sei_ocr_reserva_estado.json     reserva da CPU: reservado | entregue | falha (com `em`)
      data/sei_ocr_gpu_aplicado.jsonl      o que o integrador APLICOU (com `acao`); `descartado_sem_texto` é VAZIO
                                           — pela lição ocr-gpu-vazio-marcado-feito, vazio não é feito: volta ao E5
  E6  data/sei_ocr_reserva_conferir.txt    fila de conferência da reserva
      data/sei_ocr_ia_conferencia.jsonl    número a número (a última decisão por número vale)
      data/sei_ocr_confirmacao.jsonl       documento a documento (a última linha por (tag, i) vale)
  E7  data/sei_arquivo_frio.jsonl          pastas movidas (rc 0 = foi); pasta que nunca teve rc 0 ficou na VM-1
      data/hd_migracao/indice_<src>.jsonl  o que está no HD do it-campo (conferido? pendente de OCR?)
      listagem_pastas.json                 PDFs das pastas do frio que nunca saíram (gerada na VM-1 por `listar`)

Para cada item: PENDENTE ⇒ um job (`ocr:` / `confirmar_ocr:` / `arquivar:`) com `payload.rel` e `payload.legado`
(a fila de origem) e `payload.estagio` (o supervisor só reserva depois da liberação do estágio na O9.0 — migrar não
religa nada); FEITO ⇒ um evento `legado/<fila>` já processado (história, não aciona ninguém). Identidade pela função
única: `processos.tag` → processo e `documentos.posicao` → doc_id no PG; tag sem processo no PG vira o processo da
própria pasta e `pos:<i>` (o mesmo `id_base` do domínio), declarado `sem_identidade`.

REPLAY (`replay`): aplica o plano num esquema de fluxo TEMPORÁRIO, aplica de novo (idempotência: 0 job novo) e
reconta item a item — cada pendente tem o seu job em `fila`, cada feito tem o seu evento. Perda = item legado sem
contraparte; o relatório exige 0.

CLI:
    python -m compliance_agent.aplicacao.estagios.texto_ocr_legado listar --dados DIR       # VM-1: só lista PDFs
    python -m compliance_agent.aplicacao.estagios.texto_ocr_legado replay --dados DIR --desde 2026-10-25 \\
        [--esquema-pg public] [--saida rel.json]                                              # VM-2: esquema tmp
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

from compliance_agent.aplicacao.estagios import arquivar as E7
from compliance_agent.aplicacao.estagios import arvore as A
from compliance_agent.aplicacao.estagios import confirmar_ocr as E6
from compliance_agent.aplicacao.estagios import ocr as E5
from compliance_agent.dominio import processo_id as PI

ARQUIVOS = {"fila_gpu": "sei_ocr_gpu_fila.txt", "reserva": "sei_ocr_reserva_estado.json",
            "aplicado": "sei_ocr_gpu_aplicado.jsonl", "conferir": "sei_ocr_reserva_conferir.txt",
            "ia_conferencia": "sei_ocr_ia_conferencia.jsonl", "confirmacao": "sei_ocr_confirmacao.jsonl",
            "frio": "sei_arquivo_frio.jsonl", "listagem": "listagem_pastas.json"}
INDICES_HD = ("sei_cache", "sei_pdfs")
APLICADO_VAZIO = {"descartado_sem_texto"}                  # vazio não é feito
ESTAGIOS = {"ocr": ("E5", E5.ESTAGIO, E5.NOS), "confirmar_ocr": ("E6", E6.ESTAGIO, ["vm2"]),
            "arquivar": ("E7", E7.ESTAGIO, ["vm2"])}


# ── leitura das filas ──────────────────────────────────────────────────────────────────────────────────────────
def _md5(p: Path) -> str | None:
    return hashlib.md5(p.read_bytes()).hexdigest() if p.is_file() else None


def _jsonl(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            out.append(json.loads(ln))
    return out


def _linhas(p: Path) -> list[str]:
    return [x.strip() for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


def ler(dados: Path) -> dict:
    f = {k: dados / v for k, v in ARQUIVOS.items()}
    hd = {s: _jsonl(dados / "hd_migracao" / f"indice_{s}.jsonl") for s in INDICES_HD}
    return {"fila_gpu": _linhas(f["fila_gpu"]),
            "reserva": json.loads(f["reserva"].read_text(encoding="utf-8")) if f["reserva"].is_file() else {},
            "aplicado": _jsonl(f["aplicado"]), "conferir": _linhas(f["conferir"]),
            "ia_conferencia": _jsonl(f["ia_conferencia"]), "confirmacao": _jsonl(f["confirmacao"]),
            "frio": _jsonl(f["frio"]), "hd": hd,
            "listagem": json.loads(f["listagem"].read_text(encoding="utf-8")) if f["listagem"].is_file() else {},
            "md5": {k: _md5(p) for k, p in f.items()} | {f"hd_{s}": _md5(dados / "hd_migracao" / f"indice_{s}.jsonl")
                                                          for s in INDICES_HD}}


def rel_de(tag: str, i) -> str:
    return f"integra_{tag}/{int(i):03d}.pdf"


def tag_i(rel: str) -> tuple[str, int] | None:
    p = Path(rel)
    if not p.parent.name.startswith("integra_") or not p.stem.isdigit():
        return None
    return p.parent.name[len("integra_"):], int(p.stem)


# ── identidade (PG, só leitura) ────────────────────────────────────────────────────────────────────────────────
def identidade(con, tags: set[str]) -> tuple[dict, dict]:
    proc = {t: p for p, t in con.execute("SELECT processo, tag FROM processos WHERE tag = ANY(%s)", (sorted(tags),))}
    docs = {}
    if proc:
        for p, pos, d in con.execute("SELECT processo, posicao, doc_id FROM documentos WHERE processo = ANY(%s) AND "
                                     "posicao IS NOT NULL", (sorted(set(proc.values())),)):
            docs.setdefault((p, int(pos)), d)
    return proc, docs


def alvo(rel: str, proc: dict, docs: dict) -> dict | None:
    ti = tag_i(rel)
    if ti is None:
        return None
    tag, i = ti
    p = proc.get(tag) or PI.chave_processo(tag.replace("_", "/"))
    if not p:
        return None
    d = docs.get((p, i))
    return {"processo": p, "doc_id": d or f"pos:{i}", "rel": rel, "sem_identidade": d is None}


# ── plano ──────────────────────────────────────────────────────────────────────────────────────────────────────
def planejar(f: dict, proc: dict, docs: dict, desde: str) -> dict:
    """{jobs: {chave: job}, feitos: {chave_evento: evento}, itens: [(fila, rel, destino, chave)], sem_rel: [...]}"""
    jobs, feitos, itens, sem_rel = {}, {}, [], []

    def job(tipo: str, rel: str, fila: str, extra: dict | None = None, sufixo: str = "legado") -> str | None:
        a = alvo(rel, proc, docs)
        if a is None:
            sem_rel.append((fila, rel))
            return None
        est, contrato, nos = ESTAGIOS[tipo]
        chave = f"{tipo}:{a['processo']}|{a['doc_id']}|{sufixo}"
        j = jobs.setdefault(chave, {"tipo": tipo, "chave": chave, "prioridade": contrato.prioridade,
                                    "recursos": contrato.recursos, "volta": contrato.volta,
                                    "payload": {**a, "estagio": est, "nos": nos, "legado": []}})
        if fila not in j["payload"]["legado"]:
            j["payload"]["legado"].append(fila)
        j["payload"].update(extra or {})
        itens.append((fila, rel, "job", chave))
        return chave

    def feito(fila: str, rel: str, detalhe: dict) -> None:
        k = f"legado/{fila}|{rel}"
        feitos.setdefault(k, {"fonte": "legado", "tipo": fila, "chave": rel, "detalhe": detalhe})
        itens.append((fila, rel, "evento", k))

    # E5 ─ aplicado (por (tag, i): a última ação vale)
    ultima_ap: dict[str, dict] = {}
    for e in f["aplicado"]:
        if str(e.get("em") or "") >= desde:
            ultima_ap[rel_de(e["tag"], e["i"])] = e
    for rel, e in ultima_ap.items():
        if e.get("acao") in APLICADO_VAZIO:
            job("ocr", rel, "aplicado_vazio")
        else:
            feito("aplicado", rel, {"acao": e.get("acao"), "motor": e.get("motor"), "em": e.get("em")})
    aplicados = {r for r, e in ultima_ap.items() if e.get("acao") not in APLICADO_VAZIO}
    for rel in f["fila_gpu"]:
        (feito("fila_gpu_ja_aplicado", rel, {}) if rel in aplicados else job("ocr", rel, "fila_gpu"))
    for rel, v in f["reserva"].items():
        if str(v.get("em") or "") < desde:
            continue
        if v.get("estado") == "entregue" and rel in aplicados:
            feito("reserva_entregue", rel, {"no": v.get("no"), "em": v.get("em")})
        else:                                     # reservado, falha, ou entregue que nunca foi aplicado
            job("ocr", rel, f"reserva_{v.get('estado')}")
    # E6 ─ conferência (doc pendente se algum número está a conferir na ÚLTIMA decisão)
    for rel in f["conferir"]:
        job("confirmar_ocr", rel, "reserva_conferir")
    ult_num: dict[tuple, dict] = {}
    for e in f["ia_conferencia"]:
        if str(e.get("em") or "") >= desde:
            ult_num[(e["tag"], int(e["i"]), e.get("tipo"), e.get("norma"))] = e
    por_doc: dict[str, list[str]] = {}
    for (t, i, _, _), e in ult_num.items():
        por_doc.setdefault(rel_de(t, i), []).append(e.get("estado"))
    for rel, est in por_doc.items():
        if all(x == "confirmado" for x in est):
            feito("ia_conferencia", rel, {"numeros": len(est)})
        else:
            job("confirmar_ocr", rel, "ia_conferencia")
    ult_doc: dict[str, dict] = {}
    for e in f["confirmacao"]:
        if str(e.get("em") or "") >= desde:
            ult_doc[rel_de(e["tag"], e["i"])] = e
    for rel, e in ult_doc.items():
        (feito("confirmacao", rel, {"motor": e.get("motor")}) if e.get("estado") == "confirmado"
         else job("confirmar_ocr", rel, f"confirmacao_{e.get('estado')}"))
    # E7 ─ HD (conferido e fora do OCR = já saiu; o resto é trabalho do E7) e pastas do frio que nunca saíram
    for src, linhas in f["hd"].items():
        for e in linhas:
            if str(e.get("em") or "") < desde:
                continue
            rel = e["origem_rel"]
            if e.get("sai_da_vm2"):
                feito(f"hd_{src}", rel, {"md5": e.get("md5"), "caminho_hd": e.get("caminho_hd")})
            else:
                job("arquivar", rel, f"hd_{src}_" + ("pendente_ocr" if e.get("pendente_ocr") else "nao_conferido"),
                    {"md5_legado": e.get("md5"), "raiz_legado": src}, sufixo=f"legado:{src}")
    ok_frio = {e["pasta"] for e in f["frio"] if e.get("rc") == 0}
    for e in f["frio"]:
        if str(e.get("em") or "") < desde:
            continue
        if e.get("rc") == 0:
            feito("frio", e["pasta"] + "/", {"destino": e.get("destino"), "em": e.get("em")})
        elif e["pasta"] not in ok_frio:
            pdfs = f["listagem"].get(e["pasta"])
            if pdfs is None:
                sem_rel.append(("frio_sem_listagem", e["pasta"]))
                continue
            if not pdfs:                          # só texto ficou (o nativo já depurado): nada a mover
                feito("frio_sem_pdf", e["pasta"] + "/", {"rc": e.get("rc"), "em": e.get("em")})
            for nome in pdfs:
                job("arquivar", f"{e['pasta']}/{nome}", "frio_nunca_saiu", sufixo="legado:sei_cache_vm1")
    return {"jobs": jobs, "feitos": feitos, "itens": itens, "sem_rel": sem_rel}


# ── aplicar e reconferir ───────────────────────────────────────────────────────────────────────────────────────
def aplicar(con, plano: dict) -> dict:
    """Jobs na fila (idempotente pela chave) e eventos de história já processados (idempotente pela chave)."""
    from compliance_agent.fluxo import fila
    novos = 0
    for j in plano["jobs"].values():
        if fila.enfileirar(con, j["tipo"], j["chave"], j["payload"], j["prioridade"], j["recursos"], j["volta"],
                           no_preferido=j["payload"]["nos"][0]) is not None:
            novos += 1
    existentes = {r[0] for r in con.execute("SELECT detalhe->>'_chave' FROM eventos WHERE fonte = 'legado'")}
    ev_novos = 0
    for k, e in plano["feitos"].items():
        if k in existentes:
            continue
        eid = fila.emitir(con, e["fonte"], e["tipo"], e["chave"], {**e["detalhe"], "_chave": k})
        con.execute("UPDATE eventos SET processado_em = now() WHERE id = %s", (eid,))
        ev_novos += 1
    return {"jobs_novos": novos, "eventos_novos": ev_novos}


def reconferir(con, plano: dict) -> dict:
    jobs = {r[0]: r[1] for r in con.execute("SELECT chave, estado FROM jobs")}
    evs = {r[0] for r in con.execute("SELECT detalhe->>'_chave' FROM eventos WHERE fonte = 'legado' AND "
                                     "processado_em IS NOT NULL")}
    por_fila: dict[str, dict] = {}
    perdidos = []
    for fila_, rel, destino, chave in plano["itens"]:
        q = por_fila.setdefault(fila_, {"itens": 0, "job": 0, "evento": 0, "perdidos": 0})
        q["itens"] += 1
        ok = jobs.get(chave) == "fila" if destino == "job" else chave in evs
        q[destino] += ok
        if not ok:
            q["perdidos"] += 1
            perdidos.append([fila_, rel, chave])
    for fila_, rel in plano["sem_rel"]:
        q = por_fila.setdefault(fila_, {"itens": 0, "job": 0, "evento": 0, "perdidos": 0})
        q["itens"] += 1
        q["perdidos"] += 1
        perdidos.append([fila_, rel, None])
    return {"por_fila": por_fila, "perdidos": len(perdidos), "amostra_perdidos": perdidos[:20],
            "jobs_por_tipo": dict(con.execute("SELECT tipo, count(*) FROM jobs GROUP BY 1").fetchall()),
            "jobs_sem_identidade": con.execute("SELECT count(*) FROM jobs WHERE (payload->>'sem_identidade')::boolean"
                                               ).fetchone()[0]}


def replay(dados: Path, desde: str, esquema_pg: str | None = None, dsn: str | None = None) -> dict:
    import psycopg

    from compliance_agent import evidencias as EV
    from compliance_agent.fluxo import fila, schema
    dsn = dsn or EV.dsn_vigente()
    t0 = time.monotonic()
    f = ler(dados)
    tags = {ti[0] for rel in (f["fila_gpu"] + list(f["reserva"]) + f["conferir"]) if (ti := tag_i(rel))}
    tags |= {e["tag"] for k in ("aplicado", "ia_conferencia", "confirmacao") for e in f[k]}
    tags |= {ti[0] for ls in f["hd"].values() for e in ls if (ti := tag_i(e["origem_rel"]))}
    tags |= {e["pasta"][len("integra_"):] for e in f["frio"]}
    pg = A.conectar(dsn, esquema_pg)
    try:
        proc, docs = identidade(pg, tags)
    finally:
        pg.close()
    plano = planejar(f, proc, docs, desde)
    nome = f"tmp_o34_replay_{uuid.uuid4().hex[:8]}"
    adm = psycopg.connect(dsn, autocommit=True)
    try:
        schema.aplicar(adm, nome)
        con = fila.conectar(dsn, nome)
        try:
            a1 = aplicar(con, plano)
            a2 = aplicar(con, plano)                   # idempotência: a 2ª aplicação não cria nada
            rec = reconferir(con, plano)
        finally:
            con.close()
    finally:
        adm.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')
        adm.close()
    return {"desde": desde, "md5_das_filas": f["md5"], "tags": len(tags), "tags_com_processo_no_pg": len(proc),
            "itens": len(plano["itens"]) + len(plano["sem_rel"]), "jobs": len(plano["jobs"]),
            "eventos": len(plano["feitos"]), "aplicacao_1": a1, "aplicacao_2": a2, **rec,
            "esquema_temporario": nome, "segundos": round(time.monotonic() - t0, 1)}


def listar(dados: Path, raiz_cache: Path) -> dict:
    """VM-1 (leve): os PDFs das pastas do frio que nunca saíram com rc 0 — vai para `listagem_pastas.json`."""
    f = _jsonl(dados / ARQUIVOS["frio"])
    ok = {e["pasta"] for e in f if e.get("rc") == 0}
    out = {}
    for p in sorted({e["pasta"] for e in f} - ok):
        d = raiz_cache / p
        if d.is_dir():
            out[p] = sorted(x.name for x in d.glob("*.pdf"))
    (dados / ARQUIVOS["listagem"]).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return {"pastas": len(out), "pdfs": sum(len(v) for v in out.values())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="migração/replay das filas legadas de E5–E7 (O3.4)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    li = sub.add_parser("listar")
    li.add_argument("--dados", required=True)
    li.add_argument("--cache", default=str(A.RAIZ / "data" / "sei_cache"))
    r = sub.add_parser("replay")
    r.add_argument("--dados", required=True)
    r.add_argument("--desde", required=True)
    r.add_argument("--esquema-pg")
    r.add_argument("--saida")
    a = ap.parse_args(argv)
    if a.cmd == "listar":
        print(json.dumps(listar(Path(a.dados), Path(a.cache)), ensure_ascii=False))
        return 0
    out = replay(Path(a.dados), a.desde, a.esquema_pg)
    if a.saida:
        Path(a.saida).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "amostra_perdidos"}, ensure_ascii=False))
    return 0 if out["perdidos"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
