# -*- coding: utf-8 -*-
"""Backfill + TESTE REAL do Dossiê Mestre — roda o sistema contra os processos/certames já arquivados.

Três fases (todas serial, leves — sqlite + regex sobre texto local; VM 2 vCPU):
  julgamento  varre data/sei_arquivo/*/ (arquivo compacto do SEI), monta a leitura, extrai o
              resultado da ata (coletor_ata) e PERSISTE em certame_julgamento. O nº de controle
              PNCP do certame é extraído dos próprios textos (regex; sem match → pula, honesto).
  indice      calcular_e_persistir sobre os certames com contexto (popula certame_indice —
              nunca havia sido persistido; o endpoint calculava na hora).
  acatamento  roda auditar_acatamento em cada processo e escreve um RELATÓRIO DE APRENDIZADO
              (reports/backfill_dossie_mestre.json): distribuição de vereditos, motivos de
              inabilitação por classe (trivial/substancial/ambíguo — ambíguo alto = gabarito
              a refinar), certames extremos p/ inspeção humana. Não persiste em DB.

Uso:  PYTHONPATH=. .venv/bin/python -m tools.backfill_dossie_mestre [--max-processos N]
      [--max-certames N] [--fases julgamento,indice,acatamento] [--dry-run]
"""
from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "data" / "sei_arquivo"
REPORT = RAIZ / "reports" / "backfill_dossie_mestre.json"

_RX_CERTAME = re.compile(r"\b(\d{14}-\d-\d{6}/\d{4})\b")


def _leitura_do_arquivo(pdir: Path) -> dict | None:
    """Reconstrói a `leitura` (formato sei_reader) a partir do arquivo compacto em disco."""
    man = pdir / "manifest.json"
    if not man.exists():
        return None
    j = json.loads(man.read_text())
    conteudo = []
    for d in j.get("docs") or []:
        rel = d.get("texto")
        if not rel:
            continue
        f = pdir / rel
        if not f.exists():
            continue
        try:
            # unescape: textos do arquivo SEI carregam entidades HTML (&acirc;…) que quebram
            # regex acentuado e sujam trecho citado (aprendido no teste real 2026-07-20)
            conteudo.append({"doc": d.get("titulo") or rel,
                             "conteudo": html.unescape(f.read_text(errors="replace"))})
        except OSError:
            continue
    if not conteudo:
        return None
    return {"numero": j.get("processo") or pdir.name, "texto": "", "documentos": [],
            "conteudo_documentos": conteudo}


def _certame_da_leitura(leitura: dict) -> str | None:
    """Nº de controle PNCP mais citado nos textos do processo (sem match → None, nunca inventa)."""
    hits = Counter()
    for d in leitura["conteudo_documentos"]:
        for m in _RX_CERTAME.findall(d["conteudo"]):
            hits[m] += 1
    return hits.most_common(1)[0][0] if hits else None


_RX_PROCESSO = re.compile(r"\b(?:SEI-?)?(\d{6})[./-](\d{6})/(\d{4})\b")


def mapa_processo_certame() -> dict[str, str]:
    """PONTE REVERSA (aprendida no teste real: processos SEI não citam o nº PNCP, mas ~16% dos
    EDITAIS citam o nº do processo SEI): varre edital_documento.texto uma vez e devolve
    {'uuuuuu_nnnnnn_aaaa': numero_controle_pncp}. Colisão (2 certames citam o mesmo processo) →
    descarta a chave (honesto: sem palpite)."""
    from compliance_agent.editais.db import conectar

    con = conectar()
    mapa: dict[str, str] = {}
    ambiguos: set[str] = set()
    try:
        cur = con.execute("SELECT numero_controle_pncp, texto FROM edital_documento "
                          "WHERE texto IS NOT NULL AND length(texto) > 100")
        for certame, texto in cur:
            for u, n, a in set(_RX_PROCESSO.findall(texto)):
                chave = f"{u}_{n}_{a}"
                if chave in mapa and mapa[chave] != certame:
                    ambiguos.add(chave)
                else:
                    mapa[chave] = certame
    finally:
        con.close()
    for chave in ambiguos:
        mapa.pop(chave, None)
    return mapa


def fase_julgamento(max_processos: int, dry: bool) -> dict:
    from compliance_agent.detectores.coletor_ata import persistir_julgamento
    from compliance_agent.editais.db import conectar, init_schema

    con = conectar()
    init_schema(con)
    stats = Counter()
    exemplos = []
    mapa = mapa_processo_certame()
    stats["mapa_reverso_chaves"] = len(mapa)
    dirs = sorted(p for p in ARQUIVO.iterdir() if p.is_dir())[:max_processos]
    for pdir in dirs:
        leitura = _leitura_do_arquivo(pdir)
        if not leitura:
            stats["sem_leitura"] += 1
            continue
        certame = _certame_da_leitura(leitura) or mapa.get(pdir.name)
        if not certame:
            stats["sem_certame_pncp"] += 1
            continue
        try:
            agg = None if dry else persistir_julgamento(leitura, certame, con,
                                                        processo_sei=leitura["numero"])
        except Exception as exc:  # noqa: BLE001 — 1 processo ruim não derruba o backfill
            stats["erro"] += 1
            exemplos.append({"processo": leitura["numero"], "erro": str(exc)[:160]})
            continue
        if agg is None and not dry:
            stats["sem_resultado_de_ata"] += 1
        else:
            stats["persistidos"] += 1
            if agg and (agg.get("violacoes_saneamento") or agg.get("ambiguos")):
                exemplos.append({"processo": leitura["numero"], "certame": certame, "trivialidade": agg})
    con.close()
    return {"stats": dict(stats), "exemplos": exemplos[:25], "n_dirs": len(dirs)}


def fase_indice(max_certames: int) -> dict:
    from compliance_agent.editais.indice_certame import _certames_com_contexto, calcular_e_persistir

    certames = _certames_com_contexto()[:max_certames]
    faixas, extremos = Counter(), []
    for c in certames:
        try:
            r = calcular_e_persistir(c)
        except Exception:  # noqa: BLE001
            faixas["erro"] += 1
            continue
        faixas[r["faixa"]] += 1
        if r["faixa"] == "EXTREMO":
            extremos.append({"certame": c, "score": r["score"], "confianca": r["confianca"],
                            "drivers": [d["flag"] for d in r["drivers"]]})
    extremos.sort(key=lambda e: -e["score"])
    return {"n": len(certames), "faixas": dict(faixas), "extremos": extremos[:20]}


def fase_acatamento(max_processos: int) -> dict:
    from compliance_agent.sei_recomendacoes import auditar_acatamento

    vereditos, casos = Counter(), []
    dirs = sorted(p for p in ARQUIVO.iterdir() if p.is_dir())[:max_processos]
    for pdir in dirs:
        leitura = _leitura_do_arquivo(pdir)
        if not leitura:
            continue
        docs = [{"ref": d["doc"], "tipo": d["doc"], "texto": d["conteudo"]}
                for d in leitura["conteudo_documentos"]]
        r = auditar_acatamento(docs)
        vereditos[r["veredito"]] += 1
        if r["veredito"] in ("IGNORADO_INDICIO", "CONTRARIADO_COM_MOTIVACAO"):
            casos.append({"processo": leitura["numero"], "veredito": r["veredito"],
                          "leitura": r["leitura"][:200]})
    return {"n": sum(vereditos.values()), "vereditos": dict(vereditos), "casos_de_interesse": casos[:25]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backfill + teste real do Dossiê Mestre")
    ap.add_argument("--max-processos", type=int, default=400)
    ap.add_argument("--max-certames", type=int, default=500)
    ap.add_argument("--fases", default="julgamento,indice,acatamento")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    out: dict = {}
    fases = [f.strip() for f in args.fases.split(",") if f.strip()]
    if "julgamento" in fases:
        out["julgamento"] = fase_julgamento(args.max_processos, args.dry_run)
        print("julgamento:", json.dumps(out["julgamento"]["stats"], ensure_ascii=False))
    if "indice" in fases and not args.dry_run:
        out["indice"] = fase_indice(args.max_certames)
        print("indice:", json.dumps(out["indice"]["faixas"], ensure_ascii=False))
    if "acatamento" in fases:
        out["acatamento"] = fase_acatamento(args.max_processos)
        print("acatamento:", json.dumps(out["acatamento"]["vereditos"], ensure_ascii=False))

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"relatório: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
