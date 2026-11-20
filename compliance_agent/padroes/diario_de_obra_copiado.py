# -*- coding: utf-8 -*-
"""Diário de obra de uma medição COPIADO de outra medição do MESMO processo/contrato.

ORIGEM (perícia integral 18/11/2026): INEA × Hydra, SEI-070002/026015/2024 — doc 397 "Diário de Obras - 17ª Medição
(PETROPOLIS)" com 99% das linhas iguais ao doc 381 (16ª), datas "01/11/2025 ... 30/11/2025" do período ANTERIOR,
enquanto a 17ª medição era de "01/12/2025 até 15/12/2025".

LIGADO A `sei/reuso_documento_execucao` (não duplica): de lá vêm a normalização do corpo (sem etiqueta, assinatura,
rodapé, números SEI, CPF), os shingles de 6 palavras e os filtros de formulário em branco e de catálogo EMOP. Aquele
detector procura o mesmo corpo ENTRE processos e por regra nunca pareia documentos do mesmo processo ("juntada em
duplicidade não é achado"); este cobre exatamente o caso que ele exclui de propósito: mesmo processo, MEDIÇÕES
DIFERENTES (número da medição no título), corpo praticamente igual.

SINAL: dois diários do mesmo processo e do mesmo local (título sem o número da medição igual), de medições de
número diferente, com contenção de shingles ≥ 0,95 (forte) ou ≥ 0,85 (medio), corpo com ≥ 150 shingles. Fora:
mesmo número SEI, mesmas assinaturas eletrônicas (é o mesmo documento juntado duas vezes), formulário em branco,
catálogo. Indício ≠ acusação: diário repetido pede o diário real, o RDO do sistema da fiscalização e a vistoria;
não prova sozinho que o serviço não foi feito.
EXPLICAÇÕES INOCENTES: obra parada (diário "sem atividade" repetido — anotado se o corpo diz paralisação/chuva);
diário de período que atravessa duas medições juntado nas duas (as datas iguais aparecem no achado).
"""
from __future__ import annotations

import re

from compliance_agent.padroes import _aditivos_comum as C
from compliance_agent.sei import reuso_documento_execucao as R

ID = "diario_de_obra_copiado"
LIMIAR_FORTE, LIMIAR_MEDIO, MIN_SHINGLES = 0.95, 0.85, 150
_RE_TIT = re.compile(r"di[áa]rio\s+d[ea]\s+obras?|\bRDO\b|relat[óo]rio\s+di[áa]rio", re.I)
_RE_NUM_MED = re.compile(r"(\d{1,3})\s*[ªaº°o]?\s*(?:medi[çc][ãa]o|med\b)", re.I)
_RE_PARADA = re.compile(r"paralisa|sem\s+atividade|chuva|impratic[áa]vel", re.I)
_RE_DATA = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")


def local(titulo: str) -> str:
    t = re.sub(r"\(\d{6,10}\)", " ", titulo or "")
    t = _RE_NUM_MED.sub(" ", t)
    t = C.sem_acento(t).lower()
    t = re.sub(r"di[a]rio\s+d[ea]\s+obras?|\brdo\b|relatorio\s+diario|\d+|[^a-z ]", " ", t)
    return " ".join(t.split())


_RE_DATA_SOLTA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b")


def datas_canonicas(texto: str) -> str:
    """'1/11/25' e '01/11/2025' viram a mesma data. Medido na Hydra (docs 381 × 397): o mesmo RDO exportado duas
    vezes trazia a data em formatos diferentes, e a contenção caía de ~1,0 para 0,58 só por isso."""
    def f(m):
        a = m.group(3)
        a = ("20" + a) if len(a) == 2 else a
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{a}"
    return _RE_DATA_SOLTA.sub(f, texto or "")


def preparar(texto: str) -> dict | None:
    texto = datas_canonicas(texto)
    if R.formulario_em_branco(texto) or R.predominio_de_catalogo(texto):
        return None
    corpo = R.normalizar_corpo(texto)
    sh = R.shingles(corpo)
    if len(sh) < MIN_SHINGLES:
        return None
    return {"sh": sh, "assinaturas": R.assinaturas(texto), "datas": sorted(set(_RE_DATA.findall(texto))),
            "parada": bool(_RE_PARADA.search(texto))}


def contencao(a: set, b: set) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def varrer(limite: int | None = None) -> dict:
    idx = C.indice(limite=limite)["processos"]
    funil = {"processos": len(idx), "com_2_diarios": 0, "diarios_comparados": 0, "pares": 0, "achados": 0}
    cob = {"diarios_sem_texto": 0, "diarios_curtos_ou_em_branco": 0}
    achados = []
    for tag, p in idx.items():
        docs = [d for d in p["docs"] if _RE_TIT.search(d["titulo"] or "") and not d.get("alheio")]
        if len(docs) < 2:
            continue
        funil["com_2_diarios"] += 1
        grupos: dict[str, list] = {}
        for d in docs:
            m = _RE_NUM_MED.search(d["titulo"] or "")
            if not m:
                continue
            t = C.ler(d)
            if not t.strip():
                cob["diarios_sem_texto"] += 1
                continue
            pr = preparar(t)
            if pr is None:
                cob["diarios_curtos_ou_em_branco"] += 1
                continue
            funil["diarios_comparados"] += 1
            grupos.setdefault(local(d["titulo"]), []).append((int(m.group(1)), d, pr))
        pares = []
        for g in grupos.values():
            g.sort(key=lambda x: (x[0], x[1]["i"]))
            for i in range(len(g)):
                for j in range(i + 1, min(i + 3, len(g))):
                    (na, da, pa), (nb, db, pb) = g[i], g[j]
                    if na == nb or R.numero_sei_do_titulo(da["titulo"]) == R.numero_sei_do_titulo(db["titulo"]):
                        continue
                    if pa["assinaturas"] and pa["assinaturas"] == pb["assinaturas"]:
                        continue
                    funil["pares"] += 1
                    c = contencao(pa["sh"], pb["sh"])
                    if c >= LIMIAR_MEDIO:
                        pares.append((c, na, da, pa, nb, db, pb))
        if not pares:
            continue
        pares.sort(key=lambda x: -x[0])
        c, na, da, pa, nb, db, pb = pares[0]
        g = "forte" if c >= LIMIAR_FORTE else "medio"
        mesmas_datas = pa["datas"] == pb["datas"]
        funil["achados"] += 1
        achados.append(C.achado(
            C.chave_de_tag(tag), g,
            prova=(f"doc {da['i']} ({da['titulo'][:70]}) × doc {db['i']} ({db['titulo'][:70]}) — {c:.0%} dos trechos de 6 "
                   f"palavras do menor contidos no outro; datas no corpo "
                   + ("IDÊNTICAS" if mesmas_datas else f"{pa['datas'][:2]}…{pa['datas'][-1:]} × {pb['datas'][:2]}…{pb['datas'][-1:]}")),
            porque=(f"Diários de medições diferentes ({na}ª × {nb}ª) com corpo praticamente igual"
                    + (" e as MESMAS datas (o diário de uma medição foi reapresentado na outra)" if mesmas_datas else "")
                    + (". O corpo cita paralisação/chuva — obra parada repete diário" if pa["parada"] or pb["parada"] else "")
                    + ". Pede o RDO real e a vistoria; não prova sozinho serviço não executado."),
            fonte=f"diários de obra ({p['fonte']}) — normalização de sei/reuso_documento_execucao",
            contencao=round(c, 4), medicoes=[na, nb], n_pares=len(pares)))
    return C.resultado(ID, funil["com_2_diarios"], cob, achados, funil)
