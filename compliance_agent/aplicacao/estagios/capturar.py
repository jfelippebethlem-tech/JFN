# -*- coding: utf-8 -*-
"""E3 `capturar` — só os documentos NOVOS do processo, com versão sha256 e conferência com 0 omitido (plano mestre v2
§3.2 E3, §7 "delta"; item O3.3). Absorve `sei_integra_completa` (como motor, não reescrito), `sei_integra_fila`,
`sei_integra_vm2`, `run_integras_bombeiros` e `bombeiros_integra_supervisor`.

Entrada: `capturar:<processo>` (o evento `arvore/documento_novo` do E2). O que o estágio faz é um INVÓLUCRO com contrato:
  1. GUARDADOS do PG (documentos com alguma versão: texto do legado O3.1 ou binário de um E3 anterior) no formato de
     `captura_delta.exportar_guardados` — o delta por id_documento já existente (`captura_delta.plano_de_captura`);
  2. captura pelo navegador injetável: o real roda tools/sei_integra_completa.py com o delta da chave `JFN_E3_DELTA`
     (padrão desligado = sombra; `=1` só baixa o que não está guardado — O3.5, ligado na O9.0), "Gerar PDF" em
     lotes de 40 com CONFERÊNCIA POR MARCADOR (`cortar_lote`: pedido × marcador presente; o omitido calado vai ao
     laço doc a doc) e o laço até o fim da árvore (processo completo, nunca "os 40 primeiros"); a retomada é pelo id
     (`donos.json`), então a tentativa seguinte só busca o que faltou;
  3. APURAÇÃO (`apurar`, pura): do `manifest.json` da captura, cada documento com arquivo e dono conferido
     (`donos.json`: o id_documento do arquivo = o do nó) vira uma VERSÃO `hash_de='binario'` (sha256 do arquivo);
     o texto é do E4. OMITIDO = documento da árvore viva sem versão depois da captura e que não é restrito.
Grava no PG (ADR-001): `versoes` (+ `documentos` do que a árvore trouxe de novo) e uma `aquisicao` por execução
(`fonte='sei:e3'`, nó, ferramenta, commit, início/fim, e no `detalhe`: tree_hash, capturados, omitidos, restritos,
marcador). Idempotente: a mesma versão não duplica (PK processo, doc_id, sha256); a execução repetida da mesma posse
reaproveita a mesma aquisição.

Efeito conferido (outro processo): a aquisição desta posse existe; as versões dela no PG = as declaradas; cada arquivo
declarado existe e o sha256 RECALCULADO = o gravado; e as faltas recontadas (árvore do manifesto − versões − restritos)
são ZERO. Omitido > 0 ⇒ efeito falha ⇒ o job volta e a próxima tentativa só busca o que faltou.

CLI (teste real mínimo, um processo — navegador real):
    python -m compliance_agent.aplicacao.estagios.capturar um --processo 270006/000236/2026 [--raiz DIR] [--esquema X]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.aplicacao.estagios import arvore as A
from compliance_agent.dominio import documento_id as DI
from compliance_agent.dominio import processo_id as PI
from compliance_agent.fluxo.fila import Resultado

VERSAO = "e3-1"
FONTE = "sei:e3"
ORIGEM = "sei:e3"
FERRAMENTA = "compliance_agent.aplicacao.estagios.capturar"
RAIZ_PADRAO = A.RAIZ / "data" / "sei_cache"          # o mesmo lugar do sei_integra_completa (o arquivador lê dali)
_BLOCO = 1 << 20


def sha256_arquivo(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(_BLOCO), b""):
            h.update(b)
    return h.hexdigest()


def guardados_do_pg(con, processo: str) -> dict:
    """O que o PG já tem do processo, no formato de `captura_delta.exportar_guardados` (chars > 0 = tem versão).
    Título e id_documento: os de `documentos` (o E2 os regrava com a árvore VIVA) só se alguma versão foi capturada
    com essa identidade (captura_002); senão, os CAPTURADOS — e o `retificado` do plano dispara. Legado sem
    identidade capturada: os de `documentos`."""
    linhas = con.execute(
        "SELECT d.doc_id, COALESCE(d.titulo, ''), COALESCE(max(v.chars), 0), count(v.sha256), "
        "COALESCE(d.id_documento, '') FROM documentos d JOIN versoes v ON v.processo = d.processo AND "
        f"v.doc_id = d.doc_id AND NOT COALESCE(({A._INVALIDA}), false) WHERE d.processo = %s "
        "GROUP BY d.doc_id, d.titulo, d.id_documento ORDER BY d.doc_id", (processo,)).fetchall()
    cap = A.identidade_capturada(con, processo)
    docs = []
    for k, t, c, n, idd in linhas:
        if k in cap and not A.casa_identidade(idd, t, cap[k]):
            idd, t = sorted(cap[k])[0]          # nenhuma versão com a identidade viva: o plano vê "retificado"
        docs.append([k, t, max(int(c or 0), 1 if n else 0), idd])
    return {"tag": PI.pasta(processo), "processo": processo, "docs": docs}


def restritos_da_arvore(con, processo: str) -> set[str]:
    """id_documento marcados restritos na leitura vigente do E2 (restrito não é omitido: o SEI não o serve)."""
    r = con.execute("SELECT docs FROM arvore_leitura WHERE processo = %s ORDER BY id DESC LIMIT 1",
                    (processo,)).fetchone()
    return {d["id_documento"] for d in (r[0] if r else []) if d.get("restrito") and d.get("id_documento")}


def _ler_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def apurar(outdir: Path, ja_tinha: set[str], restritos: set[str]) -> dict:
    """Do manifesto da captura: versões novas (doc_id, i, arquivo, sha256, id_documento, título), omitidos e o resumo
    da conferência por marcador. `ja_tinha` = doc_id com versão ANTES desta captura (o delta os pulou de propósito)."""
    man = _ler_json(outdir / "manifest.json")
    entradas = [e for e in (man.get("docs") or []) if isinstance(e, dict)]
    if not entradas:
        raise RuntimeError(f"captura sem manifesto/documentos em {outdir}")
    ids = DI.ids_documentos([{"titulo": e.get("titulo", ""), "i": e.get("i")} for e in entradas])
    donos = _ler_json(outdir / "donos.json")
    versoes, omitidos, restr, sem_dono = [], [], [], []
    for k, e in zip(ids, entradas):
        idd = str(e.get("id_documento") or "")
        fp = outdir / str(e.get("arquivo") or "")
        tem_arquivo = bool(e.get("ok")) and fp.is_file() and fp.stat().st_size > 0
        if tem_arquivo and donos.get(fp.name) not in (None, idd):
            sem_dono.append(k)                  # arquivo de OUTRO documento no lugar: não vira versão deste
            tem_arquivo = False
        if tem_arquivo:
            versoes.append({"doc_id": k, "i": e.get("i"), "arquivo": fp.name, "sha256": sha256_arquivo(fp),
                            "id_documento": idd, "titulo": e.get("titulo", ""), "via": e.get("via")})
        elif k in ja_tinha:
            continue
        elif idd and idd in restritos:
            restr.append(k)
        else:
            omitidos.append({"doc_id": k, "i": e.get("i"), "titulo": e.get("titulo", ""), "via": e.get("via")})
    lotes = man.get("pdf_lotes") or {}
    marcador = {"via_pdf": lotes.get("via_pdf", 0), "lotes_ok": lotes.get("lotes_ok", 0),
                "lotes_pedidos": lotes.get("lotes_pedidos", 0),
                "omitidos_pelo_pdf": len(lotes.get("omitidos") or []),
                "recusados_pelo_sei": len(lotes.get("recusados") or []),
                "pendentes_janela": lotes.get("pendentes_janela", 0)}
    pdf_omit = {o.get("i") for o in (lotes.get("omitidos") or [])}
    marcador["omitidos_pdf_recuperados_pelo_laco"] = sum(1 for v in versoes if v["i"] in pdf_omit)
    return {"versoes": versoes, "omitidos": omitidos, "restritos": restr, "sem_dono": sem_dono,
            "n_arvore": len(ids), "completo_declarado": bool(man.get("completo")), "marcador": marcador,
            "delta": {k: (man.get("delta") or {}).get(k) for k in ("modo", "baixados", "mantidos", "removidos",
                                                                   "arvore_igual", "hash")}}


def _commit() -> str | None:
    try:
        p = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=A.RAIZ, capture_output=True, text=True,
                           timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() or None


def aquisicao_id(ctx: Contexto) -> str:
    return "e3:" + hashlib.sha256(f"{ctx.chave}|{ctx.ficha}".encode()).hexdigest()[:24]


# a identidade capturada (captura_002) vai na versão; os mesmos bytes sob identidade nova (título retificado sem mudar
# o PDF) atualizam a identidade — senão o E2 veria o documento "retificado" para sempre
_INS_VER = ("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, ocr, vista_em, hash_de, aquisicao_id, "
            "id_documento, titulo) VALUES (%s,%s,%s,0,%s,NULL,%s,'binario',%s,%s,%s) "
            "ON CONFLICT (processo, doc_id, sha256) DO UPDATE SET id_documento = excluded.id_documento, "
            "titulo = excluded.titulo, vista_em = excluded.vista_em WHERE (versoes.id_documento, versoes.titulo) "
            "IS DISTINCT FROM (excluded.id_documento, excluded.titulo)")
_INS_DOC = ("INSERT INTO documentos(processo, doc_id, posicao, titulo, visto_em, id_documento) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (processo, doc_id) DO NOTHING")


def gravar(con, processo: str, ap: dict, ctx: Contexto, outdir: Path, inicio: str, lente: list[str]) -> dict:
    aid = aquisicao_id(ctx)
    em = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        rel = str(outdir.resolve().relative_to(A.RAIZ))
    except ValueError:
        rel = str(outdir)
    detalhe = {"processo": processo, "outdir": rel, "capturados": len(ap["versoes"]), "omitidos": ap["omitidos"],
               "restritos": ap["restritos"], "sem_dono": ap["sem_dono"], "marcador": ap["marcador"],
               "delta": ap["delta"], "n_arvore": ap["n_arvore"], "lente": lente, "versao": VERSAO}
    with con.transaction():
        con.execute("INSERT INTO aquisicao(id, fonte, no, ferramenta, versao_codigo, iniciada_em, concluida_em, "
                    "detalhe) VALUES (%s,%s,%s,%s,%s,%s,now(),%s) ON CONFLICT (id) DO UPDATE SET "
                    "concluida_em = now(), detalhe = excluded.detalhe",
                    (aid, FONTE, ctx.no, FERRAMENTA, _commit(), inicio, json.dumps(detalhe, ensure_ascii=False)))
        cur = con.cursor()
        cur.executemany(_INS_DOC, [(processo, v["doc_id"], v["i"], v["titulo"], em, v["id_documento"] or None)
                                   for v in ap["versoes"]])
        cur.executemany(_INS_VER, [(processo, v["doc_id"], v["sha256"], ORIGEM, em, aid, v["id_documento"] or None,
                                    v["titulo"] or None) for v in ap["versoes"]])
    novas = con.execute("SELECT count(*) FROM versoes WHERE aquisicao_id = %s", (aid,)).fetchone()[0]
    return {"processo": processo, "aquisicao_id": aid, "outdir": str(outdir),
            "versoes": [[v["doc_id"], v["sha256"], v["arquivo"]] for v in ap["versoes"]],
            "versoes_desta_aquisicao": novas, "omitidos": len(ap["omitidos"]), "restritos": len(ap["restritos"]),
            "sem_dono": len(ap["sem_dono"]), "marcador": ap["marcador"], "n_arvore": ap["n_arvore"],
            "lente": lente, "versao": VERSAO}


def conferir(con, efeito: dict) -> dict:
    """Recontagem independente: aquisição, versões dela, sha256 recalculado de cada arquivo e faltas = 0."""
    aid, proc, outdir = efeito.get("aquisicao_id"), efeito.get("processo"), Path(str(efeito.get("outdir") or ""))
    r = con.execute("SELECT detalhe FROM aquisicao WHERE id = %s AND fonte = %s", (aid, FONTE)).fetchone()
    if r is None:
        return {"ok": False, "motivo": "aquisição desta posse não está no PG"}
    # a versão declarada pode ser de uma aquisição anterior (retomada pelo id: mesmo arquivo, mesmo sha) — vale a do
    # processo, não só a desta aquisição
    no_pg = {(k, s) for k, s in con.execute("SELECT doc_id, sha256 FROM versoes WHERE processo = %s", (proc,))}
    declaradas = {(k, s) for k, s, _ in efeito.get("versoes") or []}
    divergentes = [k for k, s, arq in efeito.get("versoes") or []
                   if not (outdir / arq).is_file() or sha256_arquivo(outdir / arq) != s]
    man = _ler_json(outdir / "manifest.json")
    entradas = [e for e in (man.get("docs") or []) if isinstance(e, dict)]
    ids = DI.ids_documentos([{"titulo": e.get("titulo", ""), "i": e.get("i")} for e in entradas])
    tem = A.capturados(con, proc)
    restr = restritos_da_arvore(con, proc)
    ret = set(A.retificados(ids, entradas, A.identidade_capturada(con, proc)))   # versão de outra identidade
    falta = [k for k, e in zip(ids, entradas) if (k not in tem or k in ret)
             and str(e.get("id_documento") or "") not in restr]
    # a árvore VIGENTE do E2 também conta (revisão de falhas caladas S2): um manifesto que lista menos que a árvore
    # (captura parcial, só o baixado) não esconde o que nunca veio
    vig = con.execute("SELECT docs FROM arvore_leitura WHERE processo = %s ORDER BY id DESC LIMIT 1",
                      (proc,)).fetchone()
    if vig:
        no_man = set(ids)
        vd = [d for d in vig[0] if d["doc_id"] not in no_man and not d.get("restrito")]
        rv = set(A.retificados([d["doc_id"] for d in vd], vd, A.identidade_capturada(con, proc)))
        falta += [d["doc_id"] for d in vd if d["doc_id"] not in tem or d["doc_id"] in rv]
    novas = con.execute("SELECT count(*) FROM versoes WHERE processo = %s AND aquisicao_id = %s",
                        (proc, aid)).fetchone()[0]
    c = {"versoes_no_pg": declaradas <= no_pg, "sha256_recalculado": not divergentes, "faltas_recontadas": len(falta),
         "arvore_nao_vazia": bool(ids), "divergentes": divergentes[:20], "novas_nesta_posse": int(novas)}
    c["ok"] = c["versoes_no_pg"] and c["sha256_recalculado"] and not falta and c["arvore_nao_vazia"]
    c["continua"] = continua(c)
    return c


def continua(c: dict) -> bool:
    """Incompleto MAS com progresso nesta posse e sem defeito (sha, PG, árvore): a captura é por janela (lotes de 40,
    30 min) e o processo grande leva várias voltas — o motor reabre sem gastar tentativa (26/11/2026). Sem nada novo
    nesta posse é falha de verdade: volta com backoff e esgota, como sempre."""
    return (not c.get("ok") and c.get("faltas_recontadas", 0) > 0 and c.get("novas_nesta_posse", 0) > 0
            and bool(c.get("versoes_no_pg")) and bool(c.get("sha256_recalculado")) and bool(c.get("arvore_nao_vazia")))


def afastar_invalidos(con, processo: str, outdir: Path) -> list[str]:
    """O binário que o E4 declarou inválido (WAF/menu) sai do caminho da RETOMADA PELO ID (`NNN.pdf` do mesmo dono ou
    `_retomada/<id>.pdf`) para `_invalidos/` — preservado, nunca apagado; senão a captura seguinte o "retomaria" e o
    documento nunca seria baixado de novo (revisão 1.8). Só move arquivo cujo sha256 RECALCULADO = o inválido."""
    inval = A.versoes_invalidas(con, processo)
    if not inval or not outdir.is_dir():
        return []
    shas = {sh for _, sh, _ in inval}
    donos = _ler_json(outdir / "donos.json")
    alvo_ids = {i for _, _, i in inval if i}
    cands = [outdir / n for n, idd in donos.items() if idd in alvo_ids]
    cands += [outdir / "_retomada" / f"{i}.pdf" for i in alvo_ids]
    movidos = []
    for fp in cands:
        if fp.is_file() and sha256_arquivo(fp) in shas:
            dest = outdir / "_invalidos" / f"{fp.stem}.{sha256_arquivo(fp)[:12]}{fp.suffix}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            fp.replace(dest)
            movidos.append(fp.name)
            donos.pop(fp.name, None)            # o dono era do arquivo que saiu: a retomada não o procura mais
    if movidos:
        tmp = outdir / "donos.json.tmp"
        tmp.write_text(json.dumps(donos, ensure_ascii=False), encoding="utf-8")
        tmp.replace(outdir / "donos.json")
    return movidos


NO_DO_ESPELHO = "vm2"                                    # onde a captura tem de morar (§3.5: o original fica na VM-2)


def espelhar(outdir: Path, no: str | None) -> dict | None:
    """Captura feita FORA da VM-2 (it-campo) é espelhada nela e conferida do outro lado — o E4 roda na VM-2 e lê dali
    (26/11/2026: o E3 do it-campo gravava só no disco dele e todo job de texto falhava em < 1 s, «manifest.json
    ausente»). Destino em JFN_E3_ESPELHO ("host:caminho/da/sei_cache"). Na VM-2, ou sem destino, nada a fazer (None).
    Não conferiu (rsync falhou, md5 do manifesto ou nº de arquivos diferentes) ⇒ RuntimeError: a captura não conta."""
    destino = os.environ.get("JFN_E3_ESPELHO")
    if not destino or no == NO_DO_ESPELHO:
        return None
    host, _, base = destino.partition(":")
    alvo = f"{base.rstrip('/')}/{outdir.name}"
    r = subprocess.run(["rsync", "-a", "--checksum", "--timeout=120", f"{outdir}/", f"{host}:{alvo}/"],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"espelho da captura em {host} falhou (rsync rc={r.returncode}): {r.stderr[-300:]}")
    md5 = hashlib.md5((outdir / "manifest.json").read_bytes()).hexdigest()
    n = sum(1 for _ in outdir.iterdir())
    v = subprocess.run(["ssh", "-o", "BatchMode=yes", host,
                        f"cd {alvo} && md5sum manifest.json | cut -d' ' -f1 && ls -1A | wc -l"],
                       capture_output=True, text=True, timeout=120)
    lado = (v.stdout or "").split()
    if v.returncode != 0 or lado[:2] != [md5, str(n)]:
        raise RuntimeError(f"espelho da captura em {host} não conferiu: local md5={md5} n={n}, "
                           f"lá {lado[:2]} (rc={v.returncode})")
    return {"ok": True, "destino": f"{host}:{alvo}", "manifest_md5": md5, "arquivos": n}


def capturar(con, nav, processo: str, ctx: Contexto, raiz: Path, lente: list[str]) -> dict:
    inicio = time.strftime("%Y-%m-%d %H:%M:%S%z")
    ja = A.capturados(con, processo)
    vig = con.execute("SELECT docs FROM arvore_leitura WHERE processo = %s ORDER BY id DESC LIMIT 1",
                      (processo,)).fetchone()
    if vig:                                     # retificado não "já tinha": se não vier agora, é omitido
        ja -= set(A.retificados([d["doc_id"] for d in vig[0]], vig[0], A.identidade_capturada(con, processo)))
    afastar_invalidos(con, processo, Path(raiz) / f"integra_{PI.pasta(processo)}")
    outdir = nav.capturar(processo, guardados_do_pg(con, processo), raiz)
    ap = apurar(outdir, ja, restritos_da_arvore(con, processo))
    esp = espelhar(outdir, ctx.no)              # antes de gravar: versão no PG só com o arquivo onde o E4 lê
    ef = gravar(con, processo, ap, ctx, outdir, inicio, lente)
    if esp:
        ef["espelho"] = esp
    return ef


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    processo = A.processo_do(payload, ctx)
    raiz = Path(payload.get("raiz") or RAIZ_PADRAO)
    con = A.conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        ef = capturar(con, A.obter_navegador(), processo, ctx, raiz, A._lente(payload))
    finally:
        con.close()
    ev = [{"fonte": "capturar", "tipo": "versao_nova", "chave": processo,
           "detalhe": {"aquisicao_id": ef["aquisicao_id"], "n": len(ef["versoes"])}}] if ef["versoes"] else []
    return Resultado(efeito=ef, eventos=ev)


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    con = A.conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        c = conferir(con, resultado.efeito)
    finally:
        con.close()
    resultado.efeito["conferencia"] = c
    return bool(c["ok"])


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["navegador"], prioridade=45, volta={"nos": ["vm2"]})


def pendentes(con, limite: int = 50) -> dict:
    """Processos cuja leitura VIGENTE do E2 tem documento (não restrito) sem versão — o que o E3 ainda deve. Só lê."""
    linhas = con.execute(
        "WITH vig AS (SELECT DISTINCT ON (processo) processo, docs FROM arvore_leitura ORDER BY processo, id DESC) "
        "SELECT vig.processo, count(*) FROM vig, jsonb_array_elements(vig.docs) d WHERE NOT "
        "COALESCE((d->>'restrito')::boolean, false) AND NOT EXISTS (SELECT 1 FROM versoes v WHERE v.processo = "
        "vig.processo AND v.doc_id = d->>'doc_id') GROUP BY 1 ORDER BY 2 DESC").fetchall()
    return {"processos": len(linhas), "documentos": sum(n for _, n in linhas),
            "topo": [{"processo": p, "faltam": n} for p, n in linhas[:limite]]}


# ── CLI: teste real mínimo (E2 + E3 de um processo, fora do motor, com posse sintética) ─────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E3 capturar (O3.3) — teste real de um processo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("um")
    u.add_argument("--processo", required=True)
    u.add_argument("--raiz", default=str(RAIZ_PADRAO))
    u.add_argument("--esquema")
    u.add_argument("--no", default="manual")
    pe = sub.add_parser("pendentes")
    pe.add_argument("--esquema")
    pe.add_argument("--limite", type=int, default=50)
    a = ap.parse_args(argv)
    if a.cmd == "pendentes":
        con = A.conectar(esquema=a.esquema)
        try:
            print(json.dumps(pendentes(con, a.limite), ensure_ascii=False))
        finally:
            con.close()
        return 0
    proc = PI.chave_processo(a.processo)
    if not proc:
        raise ErroPermanente(f"processo inválido: {a.processo!r}")
    ficha = int(time.time())
    t0 = time.monotonic()
    e2 = A._handler({"processo": proc, "esquema": a.esquema}, Contexto(a.no, "arvore", f"arvore:{proc}", ficha, 1))
    ok2 = A._efeito({"esquema": a.esquema}, Contexto(a.no, "arvore", f"arvore:{proc}", ficha, 1), e2)
    t2 = time.monotonic() - t0
    out = {"processo": proc, "e2": {k: e2.efeito.get(k) for k in ("estado", "n_docs", "faltantes", "restritos",
                                                                    "paginas", "via", "tree_hash")},
           "e2_efeito": ok2, "e2_s": round(t2, 1)}
    if e2.efeito.get("estado") == A.DOC_NOVO:
        ctx3 = Contexto(a.no, "capturar", f"capturar:{proc}", ficha, 1)
        e3 = _handler({"processo": proc, "raiz": a.raiz, "esquema": a.esquema}, ctx3)
        ok3 = _efeito({"esquema": a.esquema}, ctx3, e3)
        out.update({"e3": {k: e3.efeito.get(k) for k in ("omitidos", "restritos", "sem_dono", "marcador", "n_arvore",
                                                         "versoes_desta_aquisicao")},
                    "e3_conferencia": e3.efeito.get("conferencia"), "e3_efeito": ok3,
                    "e3_s": round(time.monotonic() - t0 - t2, 1)})
    out["total_s"] = round(time.monotonic() - t0, 1)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
