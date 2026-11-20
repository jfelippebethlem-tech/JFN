# -*- coding: utf-8 -*-
"""Despesa realizada sem prévio empenho (Lei 4.320/64, art. 60: "É vedada a realização de despesa sem prévio empenho").

ORIGEM (perícias integrais 18/11/2026): INEA × Cobrape (SEI-070002/004386/2024 e 004385/2024) — "JUSTIFICATIVA DE
DESPESAS SEM PREVIO EMPENHO ... está sendo efetuado sem seu prévio empenho"; INEA × Lytoranea (006459/2024) e RJL2
(023359/2024: "pois no período não existia o prévio empenho"); SEEDUC × Cesgranrio (030001/047970/2026: NE original
2026NE08145 de 14/05/2026 × NF de 04/05/2026); SEEDUC × Estudo Play e Casa Civil × MRC (NE de reforço após a NF).

DOIS SINAIS:
  (a) CONFISSÃO nos autos (forte): a própria administração escreve que a despesa foi/está sendo feita sem prévio
      empenho ("justificativa de despesa(s) sem prévio empenho", "efetuad[ao]/realizad[ao]/executad[ao] sem (seu)
      prévio empenho", "não existia/havia o prévio empenho"). EXCLUÍDO o texto NORMATIVO — "é vedada a realização de
      despesa sem prévio empenho", "o art. 60 veda…" (parecer e CI citando a lei), medido 18/11/2026 como a maior parte
      das ocorrências literais no acervo.
  (b) NE ORIGINAL posterior à NF (medio): nota de empenho ORIGINAL juntada no processo emitida depois da emissão da
      nota fiscal do mesmo exercício. Reforço posterior à NF NÃO acende sozinho (o original pode cobrir a despesa) —
      só se o original citado estiver nos autos e também for posterior.
EXPLICAÇÕES INOCENTES: NE global/estimativa emitida em outro processo (contrato) — por isso (b) exige a NE original
juntada e nunca usa a ausência de NE como prova; reconhecimento de dívida de exercício anterior (art. 37 da L4.320)
é rito próprio — registrado se o texto o cita.
"""
from __future__ import annotations

import re
from pathlib import Path

from compliance_agent.padroes import _aditivos_comum as C
from compliance_agent.sei.acervo_texto import sem_etiqueta

ID = "despesa_sem_previo_empenho"
_PRE = re.compile(rb"pr[\xc3][\xa9a]vio\s+empenho|previo\s+empenho|PR[\xc3][\x89E]VIO\s+EMPENHO|PREVIO\s+EMPENHO", re.I)
_RE_CONFISSAO = re.compile(
    r"justificativa\s+(?:de\s+|para\s+(?:a\s+)?)?(?:realiza[çc][ãa]o\s+de\s+)?despesas?\s+sem\s+(?:o\s+)?pr[ée]vio\s+empenho|"
    r"(?:efetuad|realizad|executad|prestad|feit)[oa]s?\s+sem\s+(?:o\s+|seu\s+|a\s+emiss[ãa]o\s+d[eo]\s+)?pr[ée]vio\s+empenho|"
    r"n[ãa]o\s+(?:existia|havia|houve)\s+(?:o\s+)?pr[ée]vio\s+empenho", re.I)
_RE_NORMATIVO = re.compile(r"vedad|\bveda\b|proib|n[ãa]o\s+(?:ser[áa]|poder[áa]|se\s+admite)|art(?:igo)?\.?\s*60|"
                           r"4\.?320", re.I)
_RE_TIT_NF = re.compile(r"nota\s+fiscal|\bNF|DANFE|NFS-?e", re.I)
_RE_TIT_NE = re.compile(r"nota\s+de\s+empenho|\bNE\b", re.I)
_RE_NF_DATA = re.compile(r"(?:data\s+(?:e\s+hora\s+)?d[ae]\s+emiss[ãa]o|emiss[ãa]o)\s*:?\s*(\d{2}/\d{2}/\d{4})", re.I)
_RE_NE = re.compile(r"(\d{4})NE(\d{3,6})\s*\n?\s*(\d{2})[/-](\d{2})[/-](\d{2,4})")
_RE_REFORCO_DE = re.compile(r"refor[çc]o\s*:?\s*(\d{4}NE\d{3,6})", re.I)


def confissoes(texto: str) -> list[str]:
    """Trechos em que a administração declara despesa sem prévio empenho (não a norma citada). Função pura."""
    out = []
    for m in _RE_CONFISSAO.finditer(texto):
        antes = texto[max(0, m.start() - 120): m.start()]
        if _RE_NORMATIVO.search(antes) and not re.search(r"justificativa", m.group(0), re.I):
            continue
        out.append(C.trecho(texto, m.start(), m.end(), 160))
    return out


def _arquivos_de(tag: str):
    for base in (C.ARQUIVO / tag / "texto", C.CACHE / f"integra_{tag}"):
        if base.is_dir():
            yield from base.glob("*.txt")


def _doc_do_arquivo(docs: list[dict], arq: Path) -> dict | None:
    s = str(arq)
    for d in docs:
        if s in (d.get("caminhos") or []):
            return d
    return None


def nes_dos_autos(docs: list[dict]) -> dict[str, dict]:
    """numero → {data, reforco_de, doc}. Só NE juntada (doc próprio do processo)."""
    out = {}
    for d in docs:
        if d.get("alheio") or not _RE_TIT_NE.search(d["titulo"] or ""):
            continue
        t = C.ler(d, 6000)
        m = _RE_NE.search(t)
        if not m:
            continue
        ano = m.group(5) if len(m.group(5)) == 4 else "20" + m.group(5)
        num = f"{m.group(1)}NE{m.group(2)}"
        mr = _RE_REFORCO_DE.search(t)
        reforco = bool(re.search(r"refor[çc]o", d["titulo"] or "", re.I)) or bool(mr)
        out.setdefault(num, {"data": f"{ano}-{m.group(4)}-{m.group(3)}", "reforco": reforco,
                             "reforco_de": mr.group(1) if mr and mr.group(1) != num else None,
                             "doc": d["i"], "titulo": d["titulo"]})
    return out


def nfs_dos_autos(docs: list[dict]) -> list[dict]:
    out = []
    for d in docs:
        if d.get("alheio") or not _RE_TIT_NF.search(d["titulo"] or "") or _RE_TIT_NE.search(d["titulo"] or ""):
            continue
        t = C.ler(d, 8000)
        m = _RE_NF_DATA.search(t)
        if m:
            out.append({"data": C.data_br(m.group(1)), "doc": d["i"], "titulo": d["titulo"],
                        "trecho": C.trecho(t, m.start(), m.end(), 30)})
    return out


def ne_posterior(nes: dict, nfs: list[dict]) -> dict | None:
    """Primeira NF do exercício anterior a TODA NE original do exercício juntada. Função pura."""
    for nf in sorted(nfs, key=lambda x: x["data"] or ""):
        ano = (nf["data"] or "")[:4]
        do_ano = {k: v for k, v in nes.items() if k.startswith(ano)}
        if not do_ano:
            continue
        originais = [v | {"numero": k} for k, v in do_ano.items() if not v["reforco"]]
        for k, v in do_ano.items():
            if v["reforco"] and v.get("reforco_de") in nes:
                originais.append(nes[v["reforco_de"]] | {"numero": v["reforco_de"]})
        if not originais:
            continue
        if all(o["data"] > nf["data"] for o in originais):
            o = min(originais, key=lambda x: x["data"])
            return {"nf": nf, "ne": o}
    return None


def varrer(limite: int | None = None) -> dict:
    idx = C.indice(limite=limite)["processos"]
    funil = {"processos": len(idx), "com_frase_previo_empenho": 0, "confissao": 0, "normativo_descartado": 0,
             "com_nf_e_ne_original": 0, "ne_original_posterior_a_nf": 0}
    cob = {"nota": "(a) varre todo .txt do processo (arquivo + cache); (b) só processos com NF e NE ORIGINAL juntadas"}
    achados = []
    for tag, p in idx.items():
        prova_a, docs_a = [], set()
        for arq in _arquivos_de(tag):
            try:
                b = arq.read_bytes()
            except OSError:
                continue
            if not _PRE.search(b):
                continue
            funil["com_frase_previo_empenho"] += 1
            d = _doc_do_arquivo(p["docs"], arq)
            if d is not None and d.get("alheio"):
                continue
            t = sem_etiqueta(b.decode("utf-8", "ignore"))
            cs = confissoes(t)
            if not cs:
                funil["normativo_descartado"] += 1
                continue
            rotulo = f"doc {d['i']} ({d['titulo'][:60]})" if d else f"arquivo {arq.parent.name}/{arq.name}"
            if rotulo in docs_a:
                continue
            docs_a.add(rotulo)
            prova_a.append(f"{rotulo} — \"{cs[0]}\"")
        chave = C.chave_de_tag(tag)
        if prova_a:
            funil["confissao"] += 1
            achados.append(C.achado(
                chave, "forte", prova="; ".join(prova_a[:4]), sinal="confissao",
                porque=("A administração registra nos autos que a despesa foi executada sem prévio empenho (L4.320 art. "
                        "60). Texto normativo ('é vedada…') excluído. Não é dano por si: pede a NE posterior, a "
                        "responsabilização (art. 167 II CF) e se houve reconhecimento de dívida."),
                fonte=f"autos ({p['fonte']})", n_docs=len(prova_a)))
            continue
        nes = nes_dos_autos(p["docs"])
        if not nes:
            continue
        nfs = nfs_dos_autos(p["docs"])
        if not nfs:
            continue
        funil["com_nf_e_ne_original"] += 1
        r = ne_posterior(nes, nfs)
        if not r:
            continue
        funil["ne_original_posterior_a_nf"] += 1
        nf, ne = r["nf"], r["ne"]
        achados.append(C.achado(
            chave, "medio", sinal="ne_posterior_a_nf",
            prova=(f"doc {nf['doc']} ({nf['titulo'][:60]}) — \"{nf['trecho']}\"; doc {ne['doc']} ({ne['titulo'][:60]}) — "
                   f"NE {ne['numero']} emitida {ne['data']}"),
            porque=(f"A NE original {ne['numero']} ({ne['data']}) — única(s) original(is) do exercício juntada(s) — é "
                    f"posterior à NF de {nf['data']}. Explicação inocente a afastar: NE global/estimativa em outro "
                    "processo (o contrato) emitida antes da NF."),
            fonte=f"NF e NE juntadas ({p['fonte']})", nf_data=nf["data"], ne=ne["numero"], ne_data=ne["data"]))
    return C.resultado(ID, len(idx), cob, achados, funil)
