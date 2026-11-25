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
  · `siafe_ob` / `siafe_ne` — OB e NE do SIAFE no MESMO processo (valor, credor), lidas do snapshot só-leitura;
  · `barras` — código de barras / QR DECODIFICADO da imagem da página (chave de acesso de 44 dígitos com DV e
    estrutura válidos — `nfe_verifica.chave_valida` — dá o CNPJ do emitente e o nº da NF). Sem decodificador
    instalado (`zxingcpp` ou `pyzbar`) a fonte é declarada INDISPONÍVEL (não confirma, não vira zero).
O "outro documento do mesmo processo" do legado (nível B) NÃO entra: não confirma aqui.
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
from compliance_agent.aplicacao.estagios import texto as T
from compliance_agent.fluxo.fila import Resultado
from compliance_agent.sei import ocr_ia_prova as P

VERSAO = "e6-1"
NIVEL_A = "A"
FONTES_A = ("leitura:", "siafe_ob", "siafe_ne", "barras")
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
def leitura_independente(pdf: Path, paginas: list[int], motores: set[str]) -> dict[str, str]:
    """Outra família que a do motor que leu: Tesseract/nativo da casa (`ocr_ia_prova.ler_pdf`) para o OCR por IA;
    RapidOCR para o Tesseract."""
    if paginas and all(m.startswith("tesseract") for m in motores):
        lidas = O.ExecutorCPU().ler(pdf, paginas)
        return {f"leitura:{O.ExecutorCPU().motor()}": "\n".join(le.texto for le in lidas.values())}
    r = P.ler_pdf(pdf, paginas, max_paginas=max(len(paginas), 1))
    return {f"leitura:{k}": t for k, t in (r.get("leituras") or {}).items() if t.strip()}


def _decodificador():
    from importlib.util import find_spec
    if find_spec("zxingcpp") is not None:
        import zxingcpp
        return lambda img: [r.text for r in zxingcpp.read_barcodes(img)]
    if find_spec("pyzbar") is not None:
        from pyzbar import pyzbar
        return lambda img: [r.data.decode("ascii", "ignore") for r in pyzbar.decode(img)]
    return None


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
    dec = _decodificador()
    if dec is None:
        return {"disponivel": False, "motivo": "sem zxingcpp/pyzbar neste nó", "textos": [], "chaves": []}
    textos = []
    for _, img, _, _ in O._imagens(pdf, paginas):
        textos += dec(img)
    return {"disponivel": True, "textos": textos, "chaves": sorted(chaves_de_barras(textos))}


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


def obter_fontes() -> Fontes:
    return Fontes()


# ── decisão (pura) ─────────────────────────────────────────────────────────────────────────────────────────────
def decidir(numeros: list[dict], leituras: dict[str, str], externos: dict[str, set]) -> list[dict]:
    """`confirmar_numeros` do legado SÓ com fontes de nível A (sem `outros_docs`) + a página de cada número."""
    pagina = {}
    for x in numeros:
        pagina.setdefault((x["tipo"], x["norma"]), x["pagina"])
    dec = P.confirmar_numeros(numeros, leituras, externos, None) if numeros else []
    for d in dec:
        d["pagina"] = pagina.get((d["tipo"], d["norma"]))
        if d["estado"] == CONFIRMADO and not nivel_a(d.get("fonte")):
            d["estado"] = A_CONFERIR                       # defesa: fonte fora do nível A nunca confirma
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
            "paginas_a_conferir": sorted({d["pagina"] for d in pend if d.get("pagina")}), "versao": VERSAO}


def _contar(xs) -> dict:
    out: dict[str, int] = {}
    for x in xs:
        k = "leitura" if str(x).startswith("leitura:") else str(x)
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
    motores = {x["motor"] for x in numeros}
    fx = obter_fontes()
    con = T.conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        leituras, bar, sia = {}, {"disponivel": False, "motivo": "sem número", "chaves": []}, \
            {"disponivel": False, "motivo": "sem número", "chaves": {}}
        if numeros:
            pdf = O.localizar_pdf(con, processo, doc_id, sha, payload)
            leituras = fx.leitura(pdf, paginas, motores)
            bar = fx.barras(pdf, paginas)
            sia = fx.siafe(processo)
        externos = {k: {tuple(x) for x in v} for k, v in (sia.get("chaves") or {}).items()}
        if bar.get("chaves"):
            externos["barras"] = {tuple(x) for x in bar["chaves"]}
        dec = decidir(numeros, leituras, externos)
        e6 = T.caminho_lateral(processo, doc_id, sha, "e6", raiz)
        e6_sha = T.gravar_lateral(e6, {"versao": VERSAO, "texto_sha": e5["texto_sha"], "leituras": leituras,
                                       "barras": bar, "siafe": sia})
        fontes = {"leitura": sorted(leituras), "barras": {k: bar[k] for k in ("disponivel", "motivo") if k in bar},
                  "siafe": {k: sia[k] for k in ("disponivel", "motivo", "fonte") if k in sia},
                  "lateral": str(e6), "lateral_sha": e6_sha}
        ef = gravar(con, processo, doc_id, e5["texto_sha"], dec, fontes, ctx)
    finally:
        con.close()
    ef.update(lateral_e5=str(T.caminho_lateral(processo, doc_id, sha, "e5", raiz)), lateral_e6=str(e6))
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

    def na_fonte(tipo, norma, fonte) -> bool:
        if fonte.startswith("leitura:"):
            return (tipo, norma) in leituras.get(fonte, set())
        if fonte == "barras":
            return (tipo, norma) in barras_k
        return (tipo, norma) in siafe_k.get(fonte, set())

    conf = [r for r in rows if r[2] == CONFIRMADO]
    c = {"recontados": len(rows) == ef["numeros"] == doc[1],
         "nenhum_pulado": {(r[0], r[1]) for r in rows} == reextraidos,
         "confirmado_nivel_a": all(r[4] == NIVEL_A and nivel_a(r[3]) for r in conf),
         "confirmado_na_fonte": all(na_fonte(r[0], r[1], r[3]) for r in conf),
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


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["cpu_leve"], prioridade=60, volta={"nos": ["vm1"]})
