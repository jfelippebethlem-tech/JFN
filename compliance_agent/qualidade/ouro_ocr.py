# -*- coding: utf-8 -*-
"""Ouro CONGELADO do OCR — páginas escaneadas por tipo documental, separadas da calibração (plano mestre v2 §7
"ouro congelado de 200 páginas por tipo, separado da calibração"; item O3.6). Irmão do `qualidade/ouro.py` (O5.4):
mesma separação por bloco (`ouro.bloco`/`ouro.reservado_ouro`/`ouro.vazamentos`) e o mesmo congelamento com sha256
no manifesto, com o rótulo próprio do OCR (os números críticos da página).

RÓTULO "HUMANO-EQUIVALENTE" — SEM HUMANO (declarado em cada linha: `humano=False`, `metodo`):
  um número (valor, CNPJ, data, processo, NF, contrato, ata — `ocr_ia_prova.extrair`) é RÓTULO da página quando
  (a) motores de DUAS FAMÍLIAS independentes o leram igual (Surya; Paddle = RapidOCR/PP-OCRv5 e PP-OCRv6, que são
  a MESMA linhagem e contam como UMA família; Tesseract) e (b) a conferência por RECORTE da bbox (motor de outra
  família, `ocr_recorte`) o leu igual. Faltou (a) ou (b) ⇒ o número vai à lista de REVISÃO (`revisar`), nunca ao
  rótulo; a página fica no ouro (tirar a página difícil enviesaria o ouro para o fácil). Tipo sem recorte (NF,
  contrato, ata) só vira rótulo com as TRÊS famílias concordando.
  A revisão por IA independente (assinatura, DEPOIS de sáb 28/11/2026 19h — `tools/ocr_ouro_revisao_ia.py`) gera uma
  VERSÃO NOVA do ouro (nunca regrava), também marcada `humano=False`.

SEPARAÇÃO: só entra página de processo cujo bloco o `ouro.reservado_ouro` reserva ao ouro, e nunca de processo que
já serviu de calibração (as bancadas de 18 e 23/11 que escolheram RapidOCR e PP-OCRv6) — `vazamentos()` confere.
Módulo puro (sem banco, sem OCR): a bancada `tools/ocr_bancada_o36.py` lê e grava.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from compliance_agent.qualidade import ouro as OU

POR_TIPO = 200
GRUPOS = {"nota_fiscal": ("nota_fiscal",),
          "empenho_ob": ("nota_empenho", "ordem_bancaria", "nota_liquidacao", "programacao_desembolso"),
          "contrato": ("contrato", "aditivo", "ata_rp"),
          "oficio_despacho": ("oficio", "despacho"),
          "medicao_atesto": ("medicao", "aceite", "fiscalizacao")}
FAMILIAS = {"surya": "surya", "gpu": "surya", "rapidocr": "paddle", "reserva": "paddle", "ppocrv6": "paddle",
            "paddle": "paddle", "tesseract": "tesseract"}
METODO = "consenso_2_familias+recorte"
# processos das bancadas que DECIDIRAM motor (18/11 e 23/11: data/bancada_ocr_20261123/paginas.json) — calibração
CALIBRACAO_BANCADAS = ("030001/087722/2024", "210108/000159/2023", "210108/000165/2023")


class ErroOuroOCR(ValueError):
    """Ouro adulterado, rótulo posterior ao congelamento, conjunto já congelado ou vazamento de calibração."""


def grupo_do_tipo(tipo: str | None) -> str | None:
    return next((g for g, ts in GRUPOS.items() if tipo in ts), None)


def familia(motor: str) -> str | None:
    m = (motor or "").lower()
    return next((f for k, f in FAMILIAS.items() if m.startswith(k) or f"{k}@" in m or f":{k}" in m), None)


def chave_processo(processo: str) -> str | None:
    from compliance_agent.ob_processo import chave_processo as K
    return K(processo)


def reservado(processo: str) -> bool:
    """O processo é do ouro? Mesmo sorteio por bloco do `ouro.py` (1 em `OURO_A_CADA`), pela chave canônica."""
    k = chave_processo(processo)
    return bool(k) and OU.reservado_ouro(OU.bloco({"processo": k}))


def vazamentos(ouro_processos: list[str], calibracao_processos: list[str]) -> list[str]:
    cal = [{"processo": chave_processo(p) or p} for p in list(calibracao_processos) + list(CALIBRACAO_BANCADAS)]
    our = [{"processo": chave_processo(p) or p} for p in ouro_processos]
    return [v for v in OU.vazamentos(cal, our) if v.startswith("processo:")] + \
        [f"nao_reservado:{p}" for p in ouro_processos if not reservado(p)]


def chaves(texto: str) -> set[tuple[str, str]]:
    from compliance_agent.sei import ocr_ia_prova as P
    return {(x["tipo"], x["norma"]) for x in P.extrair(texto or "")}


def rotular_pagina(leituras: dict[str, str], recorte_ok: set[tuple[str, str]],
                   recortaveis: set[str] | None = None) -> tuple[list, list]:
    """(rotulos, revisar) de UMA página. `leituras` = {motor@versão: texto}; `recorte_ok` = números que o recorte de
    outra família leu igual. Tipo fora de `recortaveis` (NF, contrato, ata: o número depende de palavra fora da linha)
    não tem recorte: só vira rótulo com as TRÊS famílias concordando. Cada item de `revisar` diz o porquê."""
    por_fam: dict[str, set] = {}
    for m, t in leituras.items():
        f = familia(m)
        if f is None:
            raise ErroOuroOCR(f"motor sem família conhecida: {m!r}")
        por_fam.setdefault(f, set()).update(chaves(t))
    todos = set().union(*por_fam.values()) if por_fam else set()
    rot, rev = [], []
    for k in sorted(todos):
        fams = sorted(f for f, ks in por_fam.items() if k in ks)
        sem_recorte = recortaveis is not None and k[0] not in recortaveis
        if (sem_recorte and len(fams) >= 3) or (not sem_recorte and len(fams) >= 2 and k in recorte_ok):
            rot.append(f"{k[0]}:{k[1]}")
        else:
            rev.append({"numero": f"{k[0]}:{k[1]}", "familias": fams, "recorte": k in recorte_ok,
                        "motivo": "uma_familia" if len(fams) < 2 else
                        "tipo_sem_recorte_e_sem_as_3_familias" if sem_recorte else "recorte_nao_conferiu"})
    return rot, rev


@dataclass(frozen=True)
class PaginaOuro:
    item: str                       # "<tag>/<NNN>.pdf#<página>" — a cópia do frio (HD do it-campo)
    processo: str
    grupo: str
    tipo_doc: str
    img_sha: str                    # sha256 dos pixels a 200 dpi (`ocr.sha_imagem`): re-renderizar confere a página
    rotulos: tuple                  # ("tipo:norma", …) — os números da página com rótulo
    revisar: tuple = ()             # números SEM rótulo (vão à revisão), com o porquê (JSON canônico)
    motores: tuple = ()
    metodo: str = METODO
    humano: bool = False
    revisor: str = "consenso_motores"
    rotulado_em: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        date.fromisoformat(self.rotulado_em)
        if self.grupo not in GRUPOS:
            raise ErroOuroOCR(f"grupo inválido: {self.grupo!r}")
        if len(self.img_sha) != 64:
            raise ErroOuroOCR("img_sha precisa ser o sha256 da imagem")


def _canonico(pags: list[PaginaOuro]) -> str:
    return "".join(sorted(json.dumps(asdict(p), ensure_ascii=False, sort_keys=True) + "\n" for p in pags))


def congelar(pags: list[PaginaOuro], pasta: Path, congelado_em: str, nome: str = "ouro-ocr") -> Path:
    """`<nome>-<data>.jsonl` + manifesto (sha256, n por grupo, vazamentos = 0). Recusa sobrescrever, rótulo posterior
    à data, página repetida (mesma imagem) e qualquer vazamento de calibração."""
    date.fromisoformat(congelado_em)
    if any(p.rotulado_em > congelado_em for p in pags):
        raise ErroOuroOCR("rótulo posterior ao congelamento")
    shas = [p.img_sha for p in pags]
    if len(set(shas)) != len(shas):
        raise ErroOuroOCR("página repetida (mesma imagem) no ouro")
    vz = vazamentos(sorted({p.processo for p in pags}), [])
    if vz:
        raise ErroOuroOCR(f"vazamento de calibração: {vz[:5]}")
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"{nome}-{congelado_em}.jsonl"
    if arq.exists():
        raise ErroOuroOCR(f"{arq.name} já congelado — rótulo novo = versão nova, nunca regravar")
    txt = _canonico(pags)
    arq.write_text(txt, encoding="utf-8")
    por_grupo: dict[str, int] = {}
    for p in pags:
        por_grupo[p.grupo] = por_grupo.get(p.grupo, 0) + 1
    arq.with_name(arq.name.replace(".jsonl", ".manifesto.json")).write_text(json.dumps(
        {"congelado_em": congelado_em, "n": len(pags), "por_grupo": por_grupo, "metodo": METODO, "humano": False,
         "rotulos": sum(len(p.rotulos) for p in pags), "revisar": sum(len(p.revisar) for p in pags),
         "sha256": hashlib.sha256(txt.encode()).hexdigest()}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return arq


def ler_congelado(arq: Path) -> list[PaginaOuro]:
    man = json.loads(arq.with_name(arq.name.replace(".jsonl", ".manifesto.json")).read_text(encoding="utf-8"))
    txt = arq.read_text(encoding="utf-8")
    if hashlib.sha256(txt.encode()).hexdigest() != man["sha256"]:
        raise ErroOuroOCR(f"{arq.name}: sha256 não confere com o manifesto — ouro alterado depois de congelado")
    pags = []
    for ln in txt.splitlines():
        if ln.strip():
            d = json.loads(ln)
            d["rotulos"], d["revisar"], d["motores"] = (tuple(d.get(k) or ()) for k in ("rotulos", "revisar",
                                                                                        "motores"))
            pags.append(PaginaOuro(**d))
    if any(p.rotulado_em > man["congelado_em"] for p in pags):
        raise ErroOuroOCR(f"{arq.name}: rótulo posterior ao congelamento")
    return pags


def medir(pags: list[PaginaOuro], leituras: dict[str, dict[str, str]]) -> dict:
    """Acerto de UM motor no ouro: `leituras` = {img_sha: {motor: texto}}. Conta só o rotulado (o `revisar` fica fora
    do acerto e do inventado — declarado). inventado = número emitido que não é rótulo nem está em revisão."""
    ok = tot = emit = inv = 0
    for p in pags:
        t = next(iter((leituras.get(p.img_sha) or {}).values()), None)
        if t is None:
            continue
        lidos = {f"{a}:{b}" for a, b in chaves(t)}
        rot = set(p.rotulos)
        rev = {r["numero"] if isinstance(r, dict) else str(r) for r in p.revisar}
        ok += len(rot & lidos)
        tot += len(rot)
        emit += len(lidos)
        inv += len(lidos - rot - rev)
    return {"rotulos": tot, "lidos": ok, "acerto_%": round(100 * ok / tot, 2) if tot else None,
            "emitidos": emit, "inventados": inv, "inventado_%": round(100 * inv / emit, 2) if emit else None}
