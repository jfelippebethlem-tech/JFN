# -*- coding: utf-8 -*-
"""E4 `texto` — texto NATIVO por página + perfil da página e do documento + `transformacao` (plano mestre v2 §3.2 E4;
item O3.4). Absorve a EXTRAÇÃO do `tools/sei_arquivar` (o critério, não o arquivo de saída).

Entrada: `texto:<processo>|<doc_id>|<sha16>` (uma versão BINÁRIA nova do E3; `jobs_da_aquisicao` expande o evento
`capturar/versao_nova`). Payload `{processo, doc_id, sha256, arquivo?}`; sem `arquivo`, o PDF é achado pela aquisição
da versão (`aquisicao.detalhe.outdir` + `manifest.json` do E3) e o sha256 RECALCULADO tem de ser o da versão.

Perfil POR PÁGINA (o mesmo critério do motor da casa, `sei/ocr_docs.paginas_escaneadas` e
`tools/sei_arquivar._pagina_com_imagem_grande` — nada inventado aqui):
  · `escaneada` — camada de texto < `ocr_docs.MIN_CHARS_POR_PAGINA` (40) E imagem cobrindo ≥ 35% da página: é a
    ÚNICA que vai ao E5 (OCR só onde está vazio);
  · `branca`    — sem texto nenhum e sem imagem grande (nada a ler; declarado, não é falha);
  · `nativa`    — o resto (texto do próprio PDF: é a verdade, nunca vai ao OCR).
Perfil do DOCUMENTO: nativa | escaneada | branca | mista (páginas de perfis diferentes) | `invalida` — o texto é
tela de WAF ou menu do SEI (marcadores de `lex_sei_leitura`, regra 67 do mapa: "perfil de texto inválido no E4"):
não vira versão de texto (não é conteúdo) e o evento `texto/invalido` pede recaptura.

Saída (ADR-001, PG): `transformacao` (tipo `texto_nativo`, entrada = sha256 do binário, saída = sha256 do texto
composto, motor `pymupdf` + versão, perfil por página e o sha256 do arquivo lateral em `parametros`) e `versoes`
(hash_de `texto`, origem `sei:e4`) quando há texto. Arquivo LATERAL (o texto por página, que não cabe no PG):
`data/sei_texto/<pasta>/<doc>.<sha16>.e4.json` (`JFN_TEXTO_RAIZ`). Páginas compostas separadas por `\\f` (o E8 conta a
página por `\\f`: `fatos.pagina_de`). Idempotente: a mesma entrada com o mesmo motor não duplica (UNIQUE da
transformacao; PK da versão).

Efeito conferido (outro processo): a linha de `transformacao` existe; o lateral existe e o sha256 dele é o gravado;
o PDF RELIDO dá o mesmo perfil por página e o mesmo sha256 de texto; o sha256 do binário é a entrada; a versão de
texto existe quando há texto.

CLI:
    python -m compliance_agent.aplicacao.estagios.texto schema aplicar|verificar [--esquema X]
    python -m compliance_agent.aplicacao.estagios.texto perfil --arquivo x.pdf        # só lê, não grava
    python -m compliance_agent.aplicacao.estagios.texto pendentes --estagio E4|E5|E6|E7  # só lê o PG
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.aplicacao.estagios import arvore as A
from compliance_agent.dominio import documento_id as DI
from compliance_agent.dominio import processo_id as PI
from compliance_agent.fluxo.fila import Resultado
from compliance_agent.sei import ocr_docs

VERSAO = "e4-1"
ORIGEM = "sei:e4"
TIPO_TRANSFORMACAO = "texto_nativo"
MOTOR = "pymupdf"
MIN_CHARS = ocr_docs.MIN_CHARS_POR_PAGINA                   # 40: abaixo disso a página não tem camada de texto
FRACAO_IMAGEM = ocr_docs._FRACAO_IMAGEM_PAGINA              # 0,35: imagem grande = página escaneada
NATIVA, ESCANEADA, BRANCA, MISTA, INVALIDA = "nativa", "escaneada", "branca", "mista", "invalida"
RAIZ_TEXTO_PADRAO = A.RAIZ / "data" / "sei_texto"
ENV_RAIZ_TEXTO = "JFN_TEXTO_RAIZ"
SQL_TEXTO_OCR = A.RAIZ / "deploy" / "vm2" / "postgres" / "texto_ocr_001.sql"
SQL_TEXTO_OCR_002 = A.RAIZ / "deploy" / "vm2" / "postgres" / "texto_ocr_002.sql"   # versão do estágio na chave
QUEBRA = "\f"
_RX_SEGURO = re.compile(r"[^0-9A-Za-z_.#-]+")


# ══ 1. PostgreSQL (o mesmo esquema do E2/E3) ════════════════════════════════════════════════════════════════════
def conectar(dsn: str | None = None, esquema: str | None = None):
    return A.conectar(dsn, esquema)


def aplicar_schema(dsn: str, esquema: str | None = None) -> None:
    """E2/E3 (evidências + aquisição + captura) e depois texto_ocr_001/002 — idempotente, só acrescenta."""
    import psycopg

    from compliance_agent.fluxo.schema import renderizar
    A.aplicar_schema(dsn, esquema)
    with psycopg.connect(dsn, autocommit=True) as c:
        for arq in (SQL_TEXTO_OCR, SQL_TEXTO_OCR_002):
            c.execute(renderizar(arq.read_text(encoding="utf-8"), A.esquema_vigente(esquema)))


def verificar_schema(con) -> list[str]:
    falta = [t for t in ("transformacao", "ocr_numero", "ocr_conferencia", "arquivamento")
             if con.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0] is None]
    return falta


# ══ 2. hashes e arquivo lateral ═════════════════════════════════════════════════════════════════════════════════
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_texto(t: str) -> str:
    return sha256_bytes(t.encode("utf-8"))


def sha256_arquivo(p: Path) -> str:
    from compliance_agent.aplicacao.estagios.capturar import sha256_arquivo as _s
    return _s(p)


def raiz_texto() -> Path:
    return Path(os.environ.get(ENV_RAIZ_TEXTO) or RAIZ_TEXTO_PADRAO)


def caminho_lateral(processo: str, doc_id: str, sha_binario: str, etapa: str, raiz: Path | None = None) -> Path:
    """`<raiz>/<pasta>/<doc>.<sha16>.<etapa>.json` — chaveado pela VERSÃO binária, não pelo lugar do PDF (o E7 tira o
    PDF da VM; o texto fica)."""
    return (raiz or raiz_texto()) / (PI.pasta(processo) or _RX_SEGURO.sub("_", processo)) / \
        f"{_RX_SEGURO.sub('_', doc_id)}.{sha_binario[:16]}.{etapa}.json"


def gravar_lateral(p: Path, dados: dict) -> str:
    """Grava atômico (tmp + rename) e devolve o sha256 do que ficou no disco."""
    p.parent.mkdir(parents=True, exist_ok=True)
    corpo = json.dumps(dados, ensure_ascii=False, sort_keys=True).encode("utf-8")
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_bytes(corpo)
    os.replace(tmp, p)
    return sha256_bytes(corpo)


def ler_lateral(p: Path) -> tuple[dict, str] | None:
    try:
        corpo = p.read_bytes()
    except OSError:
        return None
    try:
        return json.loads(corpo.decode("utf-8")), sha256_bytes(corpo)
    except ValueError:
        return None


# ══ 3. extração e perfil (puro) ═════════════════════════════════════════════════════════════════════════════════
def _fracao_imagem(pg) -> float:
    import fitz
    area = abs(pg.rect) or 1.0
    return max((abs(fitz.Rect(im["bbox"])) / area for im in pg.get_image_info()), default=0.0)


def perfil_pagina(texto: str, fracao_imagem: float) -> str:
    chars = len((texto or "").strip())
    if chars < MIN_CHARS and fracao_imagem >= FRACAO_IMAGEM:
        return ESCANEADA
    if chars == 0:
        return BRANCA
    return NATIVA


def invalido(texto: str) -> str:
    """Motivo se o texto é tela de WAF ou menu do SEI (não é conteúdo de documento); '' se não."""
    from compliance_agent import lex_sei_leitura as L
    amostra = {"texto": (texto or "")[:20000]}
    return L._bloqueio_rede(amostra) or L._eh_interface_sei(amostra)


def perfil_documento(paginas: list[dict], motivo_invalido: str = "") -> str:
    if motivo_invalido:
        return INVALIDA
    tipos = {p["perfil"] for p in paginas}
    if not tipos:
        return BRANCA
    return tipos.pop() if len(tipos) == 1 else MISTA


def extrair(pdf: Path) -> dict:
    """Texto nativo e perfil de CADA página (1-based). PDF que não abre ⇒ ErroPermanente (o binário é o que é)."""
    import fitz
    try:
        doc = fitz.open(pdf)
    except (RuntimeError, ValueError) as e:
        raise ErroPermanente(f"{pdf.name}: não abre como documento ({type(e).__name__}: {str(e)[:120]})") from e
    paginas = []
    with doc:
        for i in range(doc.page_count):
            pg = doc.load_page(i)
            t = pg.get_text("text") or ""
            fr = _fracao_imagem(pg)
            paginas.append({"pagina": i + 1, "perfil": perfil_pagina(t, fr), "chars": len(t.strip()),
                            "imagem": round(fr, 4), "texto": t})
    composto = QUEBRA.join(p["texto"] for p in paginas)
    motivo = invalido(composto)
    return {"paginas": paginas, "perfil": perfil_documento(paginas, motivo), "invalido": motivo,
            "texto_sha": sha256_texto(composto), "chars": len(composto.strip()),
            "escaneadas": [p["pagina"] for p in paginas if p["perfil"] == ESCANEADA]}


def texto_composto(lateral: dict) -> str:
    return QUEBRA.join(p.get("texto") or "" for p in lateral.get("paginas") or [])


def versao_motor() -> str:
    import fitz
    return f"PyMuPDF {fitz.VersionBind}"


# ══ 4. onde está o binário ══════════════════════════════════════════════════════════════════════════════════════
def trazer_captura(outdir: Path) -> bool:
    """A pasta da captura não está neste nó: traz da cópia canônica na VM-2 (JFN_E3_ESPELHO, a mesma do E3) —
    26/11/2026: o E4 tem a VM-1 de volta e o E5 prefere o it-campo, mas a captura mora na VM-2 (§3.5). Sem destino
    configurado ou rsync falhou ⇒ False (o chamador segue com o erro de antes). O sha256 da versão é conferido depois."""
    destino = os.environ.get("JFN_E3_ESPELHO")
    if not destino:
        return False
    host, _, base = destino.partition(":")
    outdir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["rsync", "-a", "--checksum", "--timeout=120", f"{host}:{base.rstrip('/')}/{outdir.name}/",
                        f"{outdir}/"], capture_output=True, text=True, timeout=900)
    return r.returncode == 0 and (outdir / "manifest.json").is_file()


def localizar_binario(con, processo: str, doc_id: str, sha: str, arquivo: str | None = None) -> Path:
    """O PDF da versão: o `arquivo` do payload ou, sem ele, o do manifesto da aquisição do E3 que gravou a versão.
    Em qualquer caso o sha256 recalculado TEM de ser o da versão (senão é outro arquivo no lugar)."""
    candidatos: list[Path] = []
    if arquivo:
        p = Path(arquivo)
        candidatos.append(p if p.is_absolute() else A.RAIZ / p)
    else:
        r = con.execute("SELECT a.detalhe->>'outdir' FROM versoes v JOIN aquisicao a ON a.id = v.aquisicao_id "
                        "WHERE v.processo = %s AND v.doc_id = %s AND v.sha256 = %s AND v.hash_de = 'binario'",
                        (processo, doc_id, sha)).fetchone()
        if r is None or not r[0]:
            raise ErroPermanente(f"{processo} {doc_id}: versão binária {sha[:12]} sem aquisição no PG")
        outdir = Path(r[0]) if Path(r[0]).is_absolute() else A.RAIZ / r[0]
        if not (outdir / "manifest.json").is_file():
            trazer_captura(outdir)
        try:
            man = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise RuntimeError(f"{processo}: manifesto da captura ilegível em {outdir} ({e})") from e
        ent = [e for e in (man.get("docs") or []) if isinstance(e, dict)]
        ids = DI.ids_documentos([{"titulo": e.get("titulo", ""), "i": e.get("i")} for e in ent])
        candidatos += [outdir / str(e.get("arquivo") or "") for k, e in zip(ids, ent) if k == doc_id]
    for p in candidatos:
        if p.is_file():
            if sha256_arquivo(p) != sha:
                raise ErroPermanente(f"{processo} {doc_id}: {p.name} não é a versão {sha[:12]} (sha256 diferente)")
            return p
    raise RuntimeError(f"{processo} {doc_id}: binário {sha[:12]} não está no disco (procurei {len(candidatos)})")


# ══ 5. registro no PG ═══════════════════════════════════════════════════════════════════════════════════════════
_INS_TR = ("INSERT INTO transformacao(processo, doc_id, tipo, entrada_sha, saida_sha, motor, versao_motor, parametros) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT ON CONSTRAINT transformacao_unica DO NOTHING")
# o E4 grava a versão do ESTÁGIO na chave (texto_ocr_002): reprocessar com lógica nova grava linha nova (histórico)
_INS_TR_VERSAO = ("INSERT INTO transformacao(processo, doc_id, tipo, entrada_sha, saida_sha, motor, versao_motor, "
                  "parametros, versao_estagio) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                  "ON CONFLICT ON CONSTRAINT transformacao_unica DO NOTHING")
_INS_VER = ("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, ocr, vista_em, hash_de) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'texto') ON CONFLICT DO NOTHING")


def transformacao_de(con, processo: str, doc_id: str, tipo: str, entrada_sha: str,
                     versao_estagio: str | None = None) -> dict | None:
    """A transformação mais recente desta entrada; com `versao_estagio`, só a gravada por ESSA versão do estágio (a
    conferência do efeito compara com a linha da mesma versão)."""
    sql = ("SELECT saida_sha, motor, versao_motor, parametros FROM transformacao WHERE processo = %s AND "
           "doc_id = %s AND tipo = %s AND entrada_sha = %s")
    par: list = [processo, doc_id, tipo, entrada_sha]
    if versao_estagio is not None:
        sql += " AND versao_estagio = %s"
        par.append(versao_estagio)
    r = con.execute(sql + " ORDER BY id DESC LIMIT 1", par).fetchone()
    return None if r is None else {"saida_sha": r[0], "motor": r[1], "versao_motor": r[2], "parametros": r[3]}


_CHAVES_EX = ("paginas", "perfil", "invalido", "texto_sha", "chars", "escaneadas")


def extracao_feita(con, sha: str) -> dict | None:
    """A extração JÁ FEITA destes bytes (mesmo sha256 binário) pelo MESMO motor@versão e lógica do E4, em qualquer
    documento — o lateral dela conferido pelo sha gravado. O8.5 (leitura única): o ensaio de 25/11 mediu o MESMO PDF
    anexado duas vezes no processo 330002/028372/2026 (sei:142288890 e sei:142290226) aberto e extraído por dois jobs.
    Extrair é determinístico sobre os bytes: a 2ª vez reusa o resultado. Sem extração anterior conferível, None."""
    for rel, lat_sha in con.execute(
            "SELECT parametros->>'lateral', parametros->>'lateral_sha' FROM transformacao WHERE tipo = %s AND "
            "entrada_sha = %s AND motor = %s AND versao_motor = %s AND parametros->>'versao' = %s ORDER BY id",
            (TIPO_TRANSFORMACAO, sha, MOTOR, versao_motor(), VERSAO)):
        if not rel:
            continue
        lat = ler_lateral(Path(rel) if Path(rel).is_absolute() else A.RAIZ / rel)
        if lat is not None and lat[1] == lat_sha and lat[0].get("entrada_sha") == sha \
                and all(k in lat[0] for k in _CHAVES_EX):
            return {k: lat[0][k] for k in _CHAVES_EX}
    return None


def registrar(con, processo: str, doc_id: str, sha: str, ex: dict, lateral: Path, lateral_sha: str,
              ctx: Contexto) -> dict:
    vm = versao_motor()
    try:
        rel = str(lateral.resolve().relative_to(A.RAIZ))
    except ValueError:
        rel = str(lateral)
    params = {"perfil": ex["perfil"], "paginas": [[p["pagina"], p["perfil"], p["chars"]] for p in ex["paginas"]],
              "lateral": rel, "lateral_sha": lateral_sha, "min_chars": MIN_CHARS, "fracao_imagem": FRACAO_IMAGEM,
              "invalido": ex["invalido"] or None, "versao": VERSAO, "job": ctx.chave, "ficha": ctx.ficha}
    com_texto = ex["chars"] > 0 and ex["perfil"] != INVALIDA
    with con.transaction():
        con.execute(_INS_TR_VERSAO, (processo, doc_id, TIPO_TRANSFORMACAO, sha, ex["texto_sha"], MOTOR, vm,
                                     json.dumps(params, ensure_ascii=False), VERSAO))
        if com_texto:
            con.execute(_INS_VER, (processo, doc_id, ex["texto_sha"], ex["chars"], ORIGEM, None,
                                   time.strftime("%Y-%m-%d %H:%M:%S")))
    return {"processo": processo, "doc_id": doc_id, "entrada_sha": sha, "texto_sha": ex["texto_sha"],
            "perfil": ex["perfil"], "escaneadas": ex["escaneadas"], "chars": ex["chars"],
            "paginas": len(ex["paginas"]), "lateral": str(lateral), "versao_texto": com_texto,
            "invalido": ex["invalido"] or None, "motor": f"{MOTOR}@{vm}", "versao": VERSAO}


# ══ 6. contrato do estágio ══════════════════════════════════════════════════════════════════════════════════════
def alvo_do(payload: dict, ctx: Contexto) -> tuple[str, str, str]:
    """(processo, doc_id, sha256 binário) do payload; a chave `tipo:<processo>|<doc_id>|<sha16>` só completa. Item da
    fila LEGADA (`payload.rel`, migrado por `texto_ocr_legado`) pode vir sem sha256: '' — o handler o calcula do
    arquivo achado (a versão é o arquivo que existe; não há binário do E3 para comparar)."""
    partes = (ctx.chave.split(":", 1)[1] if ":" in ctx.chave else "").split("|")
    processo = A.processo_do({"processo": payload.get("processo") or partes[0]}, ctx)
    doc_id = str(payload.get("doc_id") or (partes[1] if len(partes) > 1 else "")).strip()
    sha = str(payload.get("sha256") or "").strip().lower()
    if payload.get("rel") and not sha:
        if not doc_id:
            raise ErroPermanente("item legado sem doc_id")
        return processo, doc_id, ""
    if not doc_id or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ErroPermanente(f"payload sem doc_id/sha256 válidos: {doc_id!r} {sha[:16]!r}")
    return processo, doc_id, sha


def chave_job(tipo: str, processo: str, doc_id: str, sha: str) -> str:
    return f"{tipo}:{processo}|{doc_id}|{sha[:16]}"


def eventos_de(ef: dict) -> list[dict]:
    k = f"{ef['processo']}|{ef['doc_id']}"
    det = {"sha256": ef["entrada_sha"], "texto_sha": ef["texto_sha"]}
    if ef["perfil"] == INVALIDA:
        return [{"fonte": "texto", "tipo": "invalido", "chave": k, "detalhe": {**det, "motivo": ef["invalido"]}}]
    ev = []
    if ef["versao_texto"]:
        ev.append({"fonte": "texto", "tipo": "texto_novo", "chave": k, "detalhe": det})               # → E8
    if ef["escaneadas"]:
        ev.append({"fonte": "texto", "tipo": "pagina_escaneada", "chave": k,                          # → E5
                   "detalhe": {**det, "paginas": ef["escaneadas"]}})
    else:
        ev.append({"fonte": "texto", "tipo": "sem_ocr", "chave": k, "detalhe": det})                  # → E7
    return ev


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    processo, doc_id, sha = alvo_do(payload, ctx)
    con = conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        pdf = localizar_binario(con, processo, doc_id, sha, payload.get("arquivo"))
        ex = extracao_feita(con, sha) or extrair(pdf)        # O8.5: os mesmos bytes não são lidos duas vezes
        lat = caminho_lateral(processo, doc_id, sha, "e4", Path(payload["raiz_texto"]) if payload.get("raiz_texto")
                              else None)
        lat_sha = gravar_lateral(lat, {"versao": VERSAO, "processo": processo, "doc_id": doc_id, "entrada_sha": sha,
                                       "arquivo": str(pdf), **ex})
        ef = registrar(con, processo, doc_id, sha, ex, lat, lat_sha, ctx)
    finally:
        con.close()
    ef["arquivo"] = str(pdf)
    return Resultado(efeito=ef, eventos=eventos_de(ef))


def conferir(con, ef: dict) -> dict:
    t = transformacao_de(con, ef["processo"], ef["doc_id"], TIPO_TRANSFORMACAO, ef["entrada_sha"],
                         ef.get("versao") or VERSAO)
    if t is None:
        return {"ok": False, "motivo": "transformacao texto_nativo desta versão do estágio não está no PG"}
    lat = ler_lateral(Path(ef["lateral"]))
    c = {"lateral_existe": lat is not None,
         "lateral_sha": lat is not None and lat[1] == (t["parametros"] or {}).get("lateral_sha"),
         "saida_sha": t["saida_sha"] == ef["texto_sha"]}
    pdf = Path(ef.get("arquivo") or "")
    if pdf.is_file():
        c["binario_sha"] = sha256_arquivo(pdf) == ef["entrada_sha"]
        re_ex = extrair(pdf)
        c["perfil_relido"] = [p["perfil"] for p in re_ex["paginas"]] == [p[1] for p in t["parametros"]["paginas"]]
        c["texto_relido"] = re_ex["texto_sha"] == t["saida_sha"]
    else:
        c["binario_sha"] = c["perfil_relido"] = c["texto_relido"] = False
    if lat is not None:
        c["texto_do_lateral"] = sha256_texto(texto_composto(lat[0])) == t["saida_sha"]
    tem_ver = con.execute("SELECT 1 FROM versoes WHERE processo = %s AND doc_id = %s AND sha256 = %s AND "
                          "hash_de = 'texto'", (ef["processo"], ef["doc_id"], ef["texto_sha"])).fetchone() is not None
    c["versao_texto"] = tem_ver == bool(ef["versao_texto"])
    c["ok"] = all(c.values())
    return c


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    con = conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        c = conferir(con, resultado.efeito)
    finally:
        con.close()
    resultado.efeito["conferencia"] = c
    return bool(c["ok"])


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["cpu_leve"], prioridade=60,
                  volta={"nos": ["vm1"], "nota": "CPU leve: VM-2 e VM-1"})


def jobs_da_aquisicao(con, aquisicao_id: str) -> list[dict]:
    """O evento `capturar/versao_nova` (uma aquisição do E3) → um job `texto:` por versão binária dela."""
    linhas = con.execute("SELECT processo, doc_id, sha256 FROM versoes WHERE aquisicao_id = %s AND hash_de = "
                         "'binario' ORDER BY processo, doc_id", (aquisicao_id,)).fetchall()
    return [{"tipo": "texto", "chave": chave_job("texto", p, d, s), "payload": {"processo": p, "doc_id": d,
                                                                                "sha256": s, "estagio": "E4"}}
            for p, d, s in linhas]


_PENDENTES = {
    "E4": "SELECT count(*) FROM versoes v WHERE v.hash_de = 'binario' AND NOT EXISTS (SELECT 1 FROM transformacao t "
          "WHERE t.processo = v.processo AND t.doc_id = v.doc_id AND t.tipo = 'texto_nativo' AND t.entrada_sha = v.sha256)",
    "E5": "SELECT count(*) FROM transformacao t WHERE t.tipo = 'texto_nativo' AND t.parametros->>'perfil' IN "
          "('escaneada', 'mista') AND NOT EXISTS (SELECT 1 FROM transformacao o WHERE o.processo = t.processo AND "
          "o.doc_id = t.doc_id AND o.tipo = 'ocr' AND o.entrada_sha = t.entrada_sha)",
    "E6": "SELECT count(*) FROM transformacao o WHERE o.tipo = 'ocr' AND NOT EXISTS (SELECT 1 FROM ocr_conferencia c "
          "WHERE c.processo = o.processo AND c.doc_id = o.doc_id AND c.texto_sha = o.saida_sha)",
    "E7": "SELECT count(*) FROM versoes v WHERE v.hash_de = 'binario' AND NOT EXISTS (SELECT 1 FROM arquivamento a "
          "WHERE a.processo = v.processo AND a.doc_id = v.doc_id AND a.sha256 = v.sha256)",
}


def pendentes(con, estagio: str) -> dict:
    """Quanto o estágio ainda deve, contado no PG (só lê). E6 conta também o OCR sem número (o handler decide)."""
    return {"estagio": estagio, "pendentes": con.execute(_PENDENTES[estagio]).fetchone()[0]}


# ══ 7. CLI ══════════════════════════════════════════════════════════════════════════════════════════════════════
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E4 texto (O3.4)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("schema")
    s.add_argument("acao", choices=["aplicar", "verificar"])
    s.add_argument("--esquema")
    p = sub.add_parser("perfil")
    p.add_argument("--arquivo", required=True)
    pe = sub.add_parser("pendentes")
    pe.add_argument("--estagio", choices=sorted(_PENDENTES), required=True)
    pe.add_argument("--esquema")
    a = ap.parse_args(argv)
    if a.cmd == "pendentes":
        con = conectar(esquema=a.esquema)
        try:
            print(json.dumps(pendentes(con, a.estagio), ensure_ascii=False))
        finally:
            con.close()
        return 0
    if a.cmd == "perfil":
        ex = extrair(Path(a.arquivo))
        print(json.dumps({k: v for k, v in ex.items() if k != "paginas"} |
                         {"paginas": [[x["pagina"], x["perfil"], x["chars"]] for x in ex["paginas"]]},
                         ensure_ascii=False))
        return 0
    from compliance_agent import evidencias as EV
    if a.acao == "aplicar":
        aplicar_schema(EV.dsn_vigente(), a.esquema)
    con = conectar(esquema=a.esquema)
    try:
        falta = verificar_schema(con)
    finally:
        con.close()
    print(json.dumps({"esquema": A.esquema_vigente(a.esquema), "falta": falta}, ensure_ascii=False))
    return 1 if falta else 0


if __name__ == "__main__":
    sys.exit(main())
