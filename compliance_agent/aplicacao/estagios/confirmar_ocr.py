# -*- coding: utf-8 -*-
"""E6 `confirmar_ocr` — número lido por OCR só vira CONFIRMADO com fonte de NÍVEL A (plano mestre v2 §3.2 E6, §7
"valor, CNPJ, data e quantidade exigem nível A"; item O3.4). Absorve `tools/sei_ocr_ia_conferir` e
`sei/ocr_confirmacao` — a REGRA deles é reusada, não reescrita: a extração e a forma canônica dos números
(`ocr_ia_prova.extrair`/`normalizar`), a decisão número a número (`ocr_ia_prova.confirmar_numeros`: concordância
LITERAL do número normalizado; DV válido não confirma), a segunda leitura independente (`ocr_ia_prova.ler_pdf`:
Tesseract da casa ou texto nativo da página, nunca a GPU) e o SIAFE do mesmo processo (`ocr_ia_prova.fontes_externas`).

Entrada: `confirmar_ocr:<processo>|<doc_id>|<sha16>` — o evento `ocr/numero_ia` do E5. Lê o lateral do E5 e só os
números das PÁGINAS LIDAS POR OCR (o texto nativo não é OCR: não entra).

NÍVEL A (as únicas fontes aceitas; nada abaixo confirma):
  · `leitura:<motor>` — leitura INDEPENDENTE das mesmas páginas por motor de OUTRA família (Surya/RapidOCR ⇒
    Tesseract da casa; Tesseract ⇒ RapidOCR);
  · `recorte:<motor>` — o número re-lido NO RECORTE da bbox da linha (E5) por motor de outra família
    (`ocr_recorte`, O3.6): valor, CNPJ, data e nº de processo;
  · `siafe_ob` / `siafe_ne` — OB e NE do SIAFE no MESMO processo (valor, credor), lidas do snapshot só-leitura;
  · `barras` — código de barras / QR DECODIFICADO da imagem da página (chave de acesso de 44 dígitos com DV e
    estrutura válidos — `nfe_verifica.chave_valida` — dá o CNPJ do emitente e o nº da NF). Sem decodificador
    instalado (`zxingcpp` ou `pyzbar`) a fonte é declarada INDISPONÍVEL (não confirma, não vira zero).
O "outro documento do mesmo processo" do legado (nível B) NÃO entra: não confirma aqui.
ORDEM (O3.6): o código de barras é decodificado ANTES de tudo (a chave da NF-e vale mais que qualquer leitura da
imagem). Cada número guarda TODAS as fontes de nível A que o têm (`concordantes`, no lateral do E6); a `fonte`
gravada é a mais forte pela `PRECEDENCIA` (barras > SIAFE > recorte > leitura). Era a causa do "SIAFE 0/1.288"
(1ª rodada do legado, 23/11): o legado creditava só a PRIMEIRA fonte que tinha o número, e testava as leituras antes
do SIAFE — os 4 números do processo 030001/087722/2024 que o SIAFE tem (CNPJ do credor e 3 valores de OB) foram
todos creditados ao texto nativo/Tesseract. O SIAFE concordava e não aparecia.
Documento: `confirmado` só com TODO número em nível A; senão `a_conferir` (com os números e as páginas). Divergente
(a 2ª leitura trouxe um número parecido e diferente) é `a_conferir` com a leitura 2 guardada.

Saída (PG): `ocr_numero` (um por número) e `ocr_conferencia` (o documento), substituídos inteiros por (processo,
doc_id, texto_sha) — reexecução não duplica. As leituras usadas vão no lateral `…e6.json` (sha256 em `fontes`).
Efeito conferido: linhas recontadas = declaradas; os números REEXTRAÍDOS do lateral do E5 = os gravados (nenhum
pulado); cada `confirmado` tem nível A e o número está de fato na fonte guardada (leitura/barras relidas do lateral
do E6; SIAFE pelo conjunto gravado); o estado do documento é coerente.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.aplicacao.estagios import ocr as O
from compliance_agent.aplicacao.estagios import ocr_recorte as R
from compliance_agent.aplicacao.estagios import texto as T
from compliance_agent.fluxo.fila import Resultado
from compliance_agent.sei import ocr_ia_prova as P

VERSAO = "e6-2"                              # e6-2 (O3.6): recorte, concordantes, precedência, barras primeiro
NIVEL_A = "A"
FONTES_A = ("leitura:", "siafe_ob", "siafe_ne", "barras", "recorte:")
PRECEDENCIA = ("barras", "siafe_ob", "siafe_ne", "recorte:", "leitura:")      # a fonte gravada = a 1ª que concorda
FONTE_PARADA = Path.home() / "snapshot-20261124" / "compliance.db"
ENV_FONTE = "JFN_OCR_SIAFE_FONTE"
CONFIRMADO, A_CONFERIR = "confirmado", "a_conferir"


def nivel_a(fonte: str | None) -> bool:
    return bool(fonte) and any(fonte == f or (f.endswith(":") and fonte.startswith(f)) for f in FONTES_A)


# ── números do OCR (só das páginas lidas por OCR) ──────────────────────────────────────────────────────────────
def numeros_do_ocr(e5: dict) -> list[dict]:
    out = []
    for n, v in sorted((e5.get("paginas") or {}).items(), key=lambda x: int(x[0])):
        if v.get("estado") != O.TEXTO:
            continue
        for x in P.extrair(v.get("texto") or ""):
            out.append({**x, "pagina": int(n), "motor": v.get("motor") or ""})
    return out


def e5_legado(rel: str) -> dict:
    """Item da fila legada: o texto do OCR é a ENTREGA CRUA do motor legado ao lado do PDF (`NNN.ocr_gpu.txt` do
    Surya, `NNN.ocr_reserva.txt` da reserva; marcadores `[página N]`), no formato do lateral do E5."""
    for raiz in O.raizes_legado():
        for suf, motor in ((".ocr_gpu.txt", "surya@legado"), (".ocr_reserva.txt", "reserva:rapidocr@legado")):
            p = (raiz / rel).with_suffix(suf)
            if p.is_file():
                bruto = p.read_text(encoding="utf-8", errors="replace")
                pags = P.paginas_da_ia(bruto)
                return {"legado": str(p), "texto_sha": T.sha256_texto(bruto), "paginas": {
                    str(n): {"estado": O.TEXTO if O.util(t) else O.VAZIA_PENDENTE, "motor": motor, "texto": t}
                    for n, t in pags.items()}}
    raise RuntimeError(f"{rel}: entrega crua do OCR legado não achada em nenhuma raiz")


# ── fontes de nível A (injetáveis) ─────────────────────────────────────────────────────────────────────────────
def leitura_independente(pdf: Path, paginas: list[int], motores) -> dict[str, str]:
    """Outra família que a do motor que leu CADA página: Tesseract/nativo da casa (`ocr_ia_prova.ler_pdf`) para a
    página do OCR por IA ou do RapidOCR; RapidOCR para a página que o Tesseract leu (o 2º motor da volta CPU).
    `motores` = {página: motor} (O3.6) ou, no formato antigo, o conjunto dos motores. O formato antigo relia TODAS as
    páginas com o Tesseract quando havia mistura — a página lida pelo Tesseract era "confirmada" por ele mesmo."""
    if not isinstance(motores, dict):
        motores = {n: next(iter(motores)) if len(motores) == 1 else "" for n in paginas}
    tess = [n for n in paginas if str(motores.get(n, "")).startswith("tesseract")]
    outras = [n for n in paginas if n not in tess]
    out: dict[str, str] = {}
    if tess:
        ex = O.ExecutorCPU()
        out[f"leitura:{ex.motor()}"] = "\n".join(le.texto for le in ex.ler(pdf, tess).values())
    if outras:
        r = P.ler_pdf(pdf, outras, max_paginas=max(len(outras), 1), raster=O.raster_atual())
        out.update({f"leitura:{k}": t for k, t in (r.get("leituras") or {}).items() if t.strip()})
    return out


DPI_BARRAS = 300            # medido em 2.000 NF (O3.6): a 200 dpi o zxing-cpp acha a chave em 5,6% e o pyzbar em 17,5%;
#                            a 300 dpi, 16,8% e 18,1%; os dois juntos, 18,2% (o QR sai melhor no zxing). Cinza, 0,7 s/doc.


def _decodificadores() -> list:
    """TODOS os decodificadores instalados (a união acha mais que qualquer um sozinho); [] = fonte indisponível."""
    from importlib.util import find_spec
    out = []
    if find_spec("zxingcpp") is not None:
        import zxingcpp
        out.append(("zxing-cpp", lambda img: [r.text for r in zxingcpp.read_barcodes(img)]))
    if find_spec("pyzbar") is not None:
        from pyzbar import pyzbar
        out.append(("pyzbar", lambda img: [r.data.decode("ascii", "ignore") for r in pyzbar.decode(img)]))
    return out


def _paginas_cinza(pdf: Path, paginas: list[int]):
    r = O.raster_atual()
    if r is not None:                                  # leitura única no job (O8.5): o PDF já aberto pelo job
        total = r.paginas(pdf)
        for n in paginas:
            if 1 <= n <= min(total, O.MAX_PAGINAS):
                yield n, r.imagem(pdf, n, dpi=DPI_BARRAS, cinza=True)
        return
    import fitz
    import numpy as np
    with fitz.open(pdf) as doc:
        for n in paginas:
            if 1 <= n <= min(doc.page_count, O.MAX_PAGINAS):
                pix = doc.load_page(n - 1).get_pixmap(dpi=DPI_BARRAS, colorspace=fitz.csGRAY)
                yield n, np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)


def chaves_de_barras(textos: list[str]) -> set[tuple[str, str]]:
    """Do conteúdo DECODIFICADO (não do OCR): chave de 44 dígitos válida ⇒ CNPJ do emitente e nº da NF."""
    from compliance_agent import nfe_verifica as NF
    out = set()
    for t in textos:
        for m in re.finditer(r"\d{44}", re.sub(r"[\s.-]", "", t or "")):
            c = m.group(0)
            if NF.chave_valida(c):
                cn = P.normalizar("cnpj", c[6:20])
                if cn:
                    out.add(("cnpj", cn))
                nf = P.normalizar("nf", c[25:34])
                if nf:
                    out.add(("nf", nf))
    return out


def barras(pdf: Path, paginas: list[int]) -> dict:
    """{disponivel, textos, chaves}. Sem decodificador: indisponível declarado (a fonte não confirma)."""
    decs = _decodificadores()
    if not decs:
        return {"disponivel": False, "motivo": "sem zxingcpp/pyzbar neste nó", "textos": [], "chaves": []}
    textos: list[str] = []
    for _, img in _paginas_cinza(pdf, paginas):
        for _, dec in decs:
            textos += [t for t in dec(img) if t not in textos]
    return {"disponivel": True, "textos": textos, "chaves": sorted(chaves_de_barras(textos)),
            "decodificadores": [n for n, _ in decs], "dpi": DPI_BARRAS}


def siafe(processo: str, caminho: Path | None = None) -> dict:
    """{disponivel, chaves: {fonte: [(tipo, norma)]}} do SIAFE do mesmo processo, no snapshot só-leitura imutável."""
    p = Path(caminho or os.environ.get(ENV_FONTE) or FONTE_PARADA)
    if not p.is_file():
        return {"disponivel": False, "motivo": f"fonte SIAFE ausente: {p}", "chaves": {}}
    con = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True, timeout=60)
    try:
        ext = P.fontes_externas(processo, con)
    finally:
        con.close()
    return {"disponivel": True, "fonte": str(p), "chaves": {k: sorted(v) for k, v in ext.items()}}


class Fontes:
    """As três fontes de nível A — o real lê o PDF e o SIAFE; os testes trocam por fakes."""

    def leitura(self, pdf: Path, paginas: list[int], motores: set[str]) -> dict[str, str]:
        return leitura_independente(pdf, paginas, motores)

    def barras(self, pdf: Path, paginas: list[int]) -> dict:
        return barras(pdf, paginas)

    def siafe(self, processo: str) -> dict:
        return siafe(processo)

    def recorte(self, pdf: Path, e5: dict, numeros: list[dict]) -> list[dict]:
        return R.conferir(pdf, e5, numeros, R.leitores_do_no())


def obter_fontes() -> Fontes:
    return Fontes()


# ── decisão (pura) ─────────────────────────────────────────────────────────────────────────────────────────────
def _rank(fonte: str) -> int:
    return next((i for i, f in enumerate(PRECEDENCIA) if fonte == f or (f.endswith(":") and fonte.startswith(f))),
                len(PRECEDENCIA))


def decidir(numeros: list[dict], leituras: dict[str, str], externos: dict[str, set]) -> list[dict]:
    """`confirmar_numeros` do legado SÓ com fontes de nível A (sem `outros_docs`) + a página de cada número + TODAS as
    fontes que concordam (`concordantes`); a `fonte` do confirmado é a mais forte delas (`PRECEDENCIA`)."""
    pagina = {}
    for x in numeros:
        pagina.setdefault((x["tipo"], x["norma"]), x["pagina"])
    dec = P.confirmar_numeros(numeros, leituras, externos, None) if numeros else []
    lidos = {f: {(x["tipo"], x["norma"]) for x in P.extrair(t, tolerante=True)} for f, t in leituras.items()}
    todas = {**lidos, **externos}
    for d in dec:
        d["pagina"] = pagina.get((d["tipo"], d["norma"]))
        k = (d["tipo"], d["norma"])
        conc = sorted((f for f, ks in todas.items() if k in ks and nivel_a(f)), key=lambda f: (_rank(f), f))
        d["concordantes"] = conc
        if d["estado"] == CONFIRMADO:
            if conc:
                d["fonte"] = conc[0]
            elif not nivel_a(d.get("fonte")):
                d["estado"] = A_CONFERIR                   # defesa: fonte fora do nível A nunca confirma
    return dec


# ── PG ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def gravar(con, processo: str, doc_id: str, texto_sha: str, dec: list[dict], fontes: dict, ctx: Contexto) -> dict:
    pend = [d for d in dec if d["estado"] != CONFIRMADO]
    estado = CONFIRMADO if not pend else A_CONFERIR
    with con.transaction():
        con.execute("DELETE FROM ocr_numero WHERE processo = %s AND doc_id = %s AND texto_sha = %s",
                    (processo, doc_id, texto_sha))
        cur = con.cursor()
        cur.executemany(
            "INSERT INTO ocr_numero(processo, doc_id, texto_sha, tipo, norma, literal, pagina, estado, fonte, nivel, "
            "leitura_2, job_chave, ficha) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(processo, doc_id, texto_sha, d["tipo"], d["norma"], d.get("literal"), d.get("pagina"), d["estado"],
              d.get("fonte") if d["estado"] == CONFIRMADO or d["estado"] == "divergente" else None,
              NIVEL_A if d["estado"] == CONFIRMADO else None, d.get("leitura_2"), ctx.chave, ctx.ficha)
             for d in dec])
        con.execute("INSERT INTO ocr_conferencia(processo, doc_id, texto_sha, estado, numeros, a_conferir, fontes, "
                    "job_chave, ficha) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT ON CONSTRAINT "
                    "ocr_conferencia_pk DO UPDATE SET estado = excluded.estado, numeros = excluded.numeros, "
                    "a_conferir = excluded.a_conferir, fontes = excluded.fontes, job_chave = excluded.job_chave, "
                    "ficha = excluded.ficha, em = now()",
                    (processo, doc_id, texto_sha, estado, len(dec), len(pend), json.dumps(fontes, ensure_ascii=False),
                     ctx.chave, ctx.ficha))
    return {"processo": processo, "doc_id": doc_id, "texto_sha": texto_sha, "estado": estado, "numeros": len(dec),
            "confirmados": len(dec) - len(pend), "a_conferir": len(pend),
            "por_fonte": _contar([d.get("fonte") for d in dec if d["estado"] == CONFIRMADO]),
            "por_fonte_concordante": _contar([f for d in dec if d["estado"] == CONFIRMADO
                                              for f in {_familia_fonte(x) for x in d.get("concordantes") or []}]),
            "paginas_a_conferir": sorted({d["pagina"] for d in pend if d.get("pagina")}), "versao": VERSAO}


def _familia_fonte(f: str) -> str:
    return str(f).split(":", 1)[0] if str(f).startswith(("leitura:", "recorte:")) else str(f)


def _contar(xs) -> dict:
    out: dict[str, int] = {}
    for x in xs:
        k = _familia_fonte(x)
        out[k] = out.get(k, 0) + 1
    return out


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    processo, doc_id, sha = T.alvo_do(payload, ctx)
    raiz = Path(payload["raiz_texto"]) if payload.get("raiz_texto") else None
    con = T.conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        pdf_legado = O.localizar_pdf(con, processo, doc_id, sha, payload) if not sha else None
    finally:
        con.close()
    sha = sha or T.sha256_arquivo(pdf_legado)
    lat = T.ler_lateral(T.caminho_lateral(processo, doc_id, sha, "e5", raiz))
    if lat is None and payload.get("rel"):
        lat = (e5_legado(str(payload["rel"])), "")
        T.gravar_lateral(T.caminho_lateral(processo, doc_id, sha, "e5", raiz), lat[0])
    if lat is None:
        raise ErroPermanente(f"{processo} {doc_id}: sem lateral do E5 (o E6 nasce do ocr/numero_ia)")
    e5 = lat[0]
    numeros = numeros_do_ocr(e5)
    paginas = sorted({x["pagina"] for x in numeros})
    motores = {x["pagina"]: x["motor"] for x in numeros}                 # a família de CADA página
    fx = obter_fontes()
    con = T.conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        leituras, bar, sia, rec = {}, {"disponivel": False, "motivo": "sem número", "chaves": []}, \
            {"disponivel": False, "motivo": "sem número", "chaves": {}}, []
        rasterizacao = {}
        if numeros:
            pdf = O.localizar_pdf(con, processo, doc_id, sha, payload)
            # uma abertura do PDF e uma rasterização por (página, dpi) no job: a leitura independente e o recorte
            # usam a MESMA imagem a 200 dpi (antes, cada um renderizava e abria o PDF de novo)
            with O.rasterizacao_unica() as ras:
                bar = fx.barras(pdf, paginas)              # o código de barras ANTES da leitura da NF
                leituras = fx.leitura(pdf, paginas, motores)
                rec = fx.recorte(pdf, e5, numeros)
            rasterizacao = ras.resumo()
            sia = fx.siafe(processo)
        externos = {k: {tuple(x) for x in v} for k, v in (sia.get("chaves") or {}).items()}
        if bar.get("chaves"):
            externos["barras"] = {tuple(x) for x in bar["chaves"]}
        externos.update(R.chaves_confirmadas(rec))
        dec = decidir(numeros, leituras, externos)
        e6 = T.caminho_lateral(processo, doc_id, sha, "e6", raiz)
        e6_sha = T.gravar_lateral(e6, {"versao": VERSAO, "texto_sha": e5["texto_sha"], "leituras": leituras,
                                       "barras": bar, "siafe": sia, "recortes": rec,
                                       "concordantes": {f"{d['tipo']}|{d['norma']}": d.get("concordantes") or []
                                                        for d in dec}})
        fontes = {"leitura": sorted(leituras), "barras": {k: bar[k] for k in ("disponivel", "motivo") if k in bar},
                  "recorte": _contar(r["estado"] for r in rec),
                  "siafe": {k: sia[k] for k in ("disponivel", "motivo", "fonte") if k in sia},
                  "lateral": str(e6), "lateral_sha": e6_sha}
        ef = gravar(con, processo, doc_id, e5["texto_sha"], dec, fontes, ctx)
    finally:
        con.close()
    ef.update(lateral_e5=str(T.caminho_lateral(processo, doc_id, sha, "e5", raiz)), lateral_e6=str(e6), **rasterizacao)
    return Resultado(efeito=ef, eventos=[{"fonte": "confirmar_ocr", "tipo": ef["estado"],
                                          "chave": f"{processo}|{doc_id}",
                                          "detalhe": {"texto_sha": ef["texto_sha"], "a_conferir": ef["a_conferir"]}}])


def conferir(con, ef: dict) -> dict:
    rows = con.execute("SELECT tipo, norma, estado, fonte, nivel FROM ocr_numero WHERE processo = %s AND doc_id = %s "
                       "AND texto_sha = %s", (ef["processo"], ef["doc_id"], ef["texto_sha"])).fetchall()
    doc = con.execute("SELECT estado, numeros, a_conferir, fontes FROM ocr_conferencia WHERE processo = %s AND "
                      "doc_id = %s AND texto_sha = %s", (ef["processo"], ef["doc_id"], ef["texto_sha"])).fetchone()
    e5 = T.ler_lateral(Path(ef["lateral_e5"]))
    e6 = T.ler_lateral(Path(ef["lateral_e6"]))
    if doc is None or e5 is None or e6 is None:
        return {"ok": False, "motivo": "conferência do documento ou laterais ausentes"}
    reextraidos = {(x["tipo"], x["norma"]) for x in numeros_do_ocr(e5[0])}
    leituras = {f: {(x["tipo"], x["norma"]) for x in P.extrair(t, tolerante=True)}
                for f, t in (e6[0].get("leituras") or {}).items()}
    barras_k = {tuple(x) for x in (e6[0].get("barras") or {}).get("chaves") or []}
    siafe_k = {k: {tuple(x) for x in v} for k, v in ((e6[0].get("siafe") or {}).get("chaves") or {}).items()}
    recorte_k = R.chaves_confirmadas(e6[0].get("recortes") or [])
    conc = e6[0].get("concordantes") or {}

    def na_fonte(tipo, norma, fonte) -> bool:
        if fonte.startswith("leitura:"):
            return (tipo, norma) in leituras.get(fonte, set())
        if fonte.startswith("recorte:"):
            return (tipo, norma) in recorte_k.get(fonte, set())
        if fonte == "barras":
            return (tipo, norma) in barras_k
        return (tipo, norma) in siafe_k.get(fonte, set())

    conf = [r for r in rows if r[2] == CONFIRMADO]
    c = {"recontados": len(rows) == ef["numeros"] == doc[1],
         "nenhum_pulado": {(r[0], r[1]) for r in rows} == reextraidos,
         "confirmado_nivel_a": all(r[4] == NIVEL_A and nivel_a(r[3]) for r in conf),
         "confirmado_na_fonte": all(na_fonte(r[0], r[1], r[3]) for r in conf),
         "fonte_e_a_mais_forte": all(r[3] == (conc.get(f"{r[0]}|{r[1]}") or [r[3]])[0] for r in conf),
         "concordantes_na_fonte": all(na_fonte(*k.split("|", 1), f) for k, fs in conc.items() for f in fs),
         "lateral_e6_sha": e6[1] == (doc[3] or {}).get("lateral_sha"),
         "estado_coerente": doc[0] == (CONFIRMADO if len(conf) == len(rows) else A_CONFERIR) == ef["estado"]}
    c["ok"] = all(c.values())
    return c


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    con = T.conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        c = conferir(con, resultado.efeito)
    finally:
        con.close()
    resultado.efeito["conferencia"] = c
    return bool(c["ok"])


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["cpu_leve"], prioridade=55, volta={"nos": ["vm1"]})  # 26/11: à frente do E4 (60) — o de baixo drena primeiro
