# -*- coding: utf-8 -*-
"""Minerador do D.O. RIO — estrutura o texto cru de ``pcrj_doe_materia`` em EVENTOS.

O coletor ``doweb.py`` guarda o texto (OCR) das matérias do Diário Oficial do
Município. Aqui esse texto vira dado estruturado de contratação municipal:

* **Atas de Registro de Preços** — nº da ata, órgão gestor, objeto, processo,
  modalidade, **empresa vencedora + CNPJ + valor total adjudicado**.
* **Empenhos** (``AAAA NE NNNNNN``) por credor — rotulados **empenho**, jamais
  "pago" (empenho ≠ liquidação ≠ OB; só a Ordem Bancária é pagamento — §2 CLAUDE.md).
* **Canal informal ``@gmail.com``** — órgão/hospital municipal conduzindo pesquisa
  de mercado e retirada de empenho por e-mail pessoal (baixa transparência).

Tudo determinístico (sem IA). Indício ≠ acusação; INDISPONÍVEL ≠ 0. O texto é OCR:
a extração é tolerante e reporta cobertura honesta, nunca "0 achados" como "limpo".

Detectores derivados (função pura, shape da casa ``{ok, n, achados, ressalva}``):
* :func:`concentracao_vencedor` — CNPJ que vence muitas atas / concentra valor num órgão.
* :func:`canal_informal` — e-mails ``@gmail.com`` usados como canal de compra.
"""
from __future__ import annotations

import json
import re

from . import db

RESSALVA = (
    "Indício para apuração interna, não acusação. Fonte: OCR do D.O. RIO (pode conter ruído). "
    "Valores de empenho NÃO são pagamento (empenho ≠ liquidação ≠ Ordem Bancária). "
    "Confirmar no processo/extrato-fonte antes de qualquer uso externo."
)

# ── parsing de valores (formato BR: 2.159.344,95 · às vezes 4 casas por OCR) ──
_RE_VALOR = re.compile(r"R\$\s*([\d][\d.]*,\d{2,4})")


def valor_br(s: str) -> float:
    """Converte '2.159.344,95' → 2159344.95. Tolera 3-4 casas (precisão de preço unitário)."""
    s = (s or "").strip()
    if not s:
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return round(float(s), 4)
    except ValueError:
        return 0.0


# ── Ata de Registro de Preços ────────────────────────────────────────────────
# Cada bloco começa no cabeçalho do extrato; o vencedor/CNPJ/valor vêm no corpo.
_RE_ATA_HEAD = re.compile(
    r"EXTRATO DA ATA DE REGISTRO DE PRE[ÇC]OS N[ºo°]?\s*(\d+)\s*/\s*(\d{4})", re.I)
_RE_ORGAO_GESTOR = re.compile(r"[ÓO]rg[ãa]o Gestor:\s*(.+?)(?:\.|Objeto:|Processo:)", re.I | re.S)
_RE_OBJETO = re.compile(r"Objeto:\s*(.+?)(?:Processo:|Modalidade:|Validade)", re.I | re.S)
_RE_PROCESSO_ATA = re.compile(r"Processo:\s*([A-Z0-9./\-]+(?:/\d{2,6})?)", re.I)
_RE_MODALIDADE = re.compile(r"Modalidade:\s*(.+?)(?:Validade|[ÓO]rg[ãa]o|$)", re.I | re.S)
_RE_VENCEDOR = re.compile(
    r"Empresa Vencedora:\s*(.+?)\s*[-–]\s*(?:Item|Itens|CNPJ)",
    re.I | re.S)
_RE_VENC_CNPJ_VALOR = re.compile(
    r"Empresa Vencedora:\s*(.+?)\s*[-–].{0,80}?CNPJ:\s*([\d./\-]+)"
    r".{0,200}?Valor Total Adjudicado:\s*R\$\s*([\d][\d.]*,\d{2,4})",
    re.I | re.S)


def _limpa(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def minerar_atas(texto: str) -> list[dict]:
    """Extrai atas de registro de preços do texto de UMA matéria.

    Retorna lista de ``{ata, ano, orgao_gestor, objeto, processo, modalidade,
    vencedor, cnpj, valor_adjudicado}``. Só emite registros com vencedor+CNPJ+valor
    (o tripé confiável); o cabeçalho da ata contextualiza quando presente no bloco.
    """
    texto = texto or ""
    # contexto de cabeçalho mais próximo (último visto antes do vencedor)
    heads = [(m.start(), m.group(1), m.group(2)) for m in _RE_ATA_HEAD.finditer(texto)]

    def _head_antes(pos: int):
        ata = ano = None
        for start, a, y in heads:
            if start <= pos:
                ata, ano = a, y
            else:
                break
        return ata, ano

    out: list[dict] = []
    for m in _RE_VENC_CNPJ_VALOR.finditer(texto):
        vencedor = _limpa(m.group(1))
        cnpj = re.sub(r"\D", "", m.group(2))
        if len(cnpj) != 14:            # honestidade: só CNPJ completo vira registro forte
            continue
        valor = valor_br(m.group(3))
        ata, ano = _head_antes(m.start())
        # janela local p/ órgão gestor / processo / modalidade (bloco da ata)
        bloco = texto[max(0, m.start() - 900):m.end()]
        og = _RE_ORGAO_GESTOR.search(bloco)
        pr = _RE_PROCESSO_ATA.search(bloco)
        md = _RE_MODALIDADE.search(bloco)
        out.append({
            "ata": ata, "ano": int(ano) if ano else None,
            "orgao_gestor": _limpa(og.group(1)) if og else None,
            "processo": _limpa(pr.group(1)) if pr else None,
            "modalidade": _limpa(md.group(1))[:80] if md else None,
            "vencedor": vencedor, "cnpj": cnpj,
            "valor_adjudicado": valor,
        })
    return out


# ── Empenhos (commitment, NÃO pagamento) ─────────────────────────────────────
_RE_EMPENHO = re.compile(r"(\d{4})\s*NE\s*(\d{6})")


def extrair_empenhos(texto: str) -> list[dict]:
    """Empenhos ``AAAANEnnnnnn`` com o credor imediatamente anterior no texto.

    Rótulo sempre 'empenho' (valor comprometido, não pago). O credor é o nome em
    caixa-alta que precede o número — heurística de OCR, portanto indício.
    """
    texto = texto or ""
    out: list[dict] = []
    for m in _RE_EMPENHO.finditer(texto):
        antes = texto[max(0, m.start() - 120):m.start()]
        # último trecho em CAIXA ALTA (nome de empresa) antes do NE
        nomes = re.findall(r"([A-ZÀ-Ú][A-ZÀ-Ú&.\-\s]{6,}?(?:LTDA|S\.?A\.?|ME|EIRELI|EPP)?)\s*$", antes)
        credor = _limpa(nomes[-1]) if nomes else None
        out.append({
            "empenho": f"{m.group(1)}NE{m.group(2)}",
            "ano": int(m.group(1)),
            "credor": credor,
            "natureza": "empenho",   # NUNCA 'pago'
        })
    return out


# ── Canal informal @gmail.com ────────────────────────────────────────────────
_RE_GMAIL = re.compile(r"\b([a-z0-9][a-z0-9._%+\-]*@gmail\.com)\b", re.I)


def extrair_gmails(texto: str) -> list[str]:
    vistos: list[str] = []
    for m in _RE_GMAIL.finditer(texto or ""):
        e = m.group(1).lower()
        if e not in vistos:
            vistos.append(e)
    return vistos


# ── Mineração do corpus (lê pcrj_doe_materia) ────────────────────────────────
def _ro(db_path=None):
    con = db.conectar(db_path)
    return con


def minerar_corpus(db_path=None) -> dict:
    """Varre ``pcrj_doe_materia`` e agrega atas, empenhos e canais @gmail.

    Retorna resumo com as listas estruturadas (não persiste — os detectores leem daqui).
    """
    con = _ro(db_path)
    try:
        rows = con.execute(
            "SELECT id_materia, data, orgao, termo_busca, texto FROM pcrj_doe_materia").fetchall()
    except Exception:
        rows = []
    finally:
        con.close()
    atas: list[dict] = []
    empenhos: list[dict] = []
    gmails: dict[str, dict] = {}
    for r in rows:
        texto = r["texto"] if not isinstance(r, (tuple, list)) else r[4]
        data = r["data"] if not isinstance(r, (tuple, list)) else r[1]
        termo = r["termo_busca"] if not isinstance(r, (tuple, list)) else r[3]
        for a in minerar_atas(texto):
            a["data"] = data
            a["termo_busca"] = termo
            atas.append(a)
        empenhos.extend(extrair_empenhos(texto))
        for e in extrair_gmails(texto):
            g = gmails.setdefault(e, {"email": e, "n_materias": 0, "termos": set()})
            g["n_materias"] += 1
            if termo:
                g["termos"].add(termo)
    for g in gmails.values():
        g["termos"] = sorted(g["termos"])
    return {
        "materias": len(rows),
        "atas": atas,
        "empenhos": empenhos,
        "gmails": list(gmails.values()),
    }


# ── Detector B1b — concentração de vencedor ──────────────────────────────────
def concentracao_vencedor(db_path=None, min_atas: int = 2, min_valor: float = 100_000.0) -> dict:
    """CNPJ que vence ≥``min_atas`` atas de registro de preços no corpus do D.O. RIO.

    Sinal de concentração de mercado (captura/rodízio) na fonte municipal. Guarda:
    exige ≥2 atas E valor material; reporta órgãos gestores distintos (concentração
    dentro de um mesmo gestor é mais forte que espalhada).
    """
    corpus = minerar_corpus(db_path)
    por_cnpj: dict[str, dict] = {}
    for a in corpus["atas"]:
        c = a["cnpj"]
        d = por_cnpj.setdefault(c, {
            "cnpj": c, "nome": a["vencedor"], "n_atas": 0,
            "valor_adjudicado": 0.0, "orgaos": set(), "atas": []})
        d["n_atas"] += 1
        d["valor_adjudicado"] += a["valor_adjudicado"]
        if a["orgao_gestor"]:
            d["orgaos"].add(a["orgao_gestor"])
        d["atas"].append({"ata": a["ata"], "ano": a["ano"], "valor": a["valor_adjudicado"]})
    achados = []
    for d in por_cnpj.values():
        if d["n_atas"] >= min_atas and d["valor_adjudicado"] >= min_valor:
            d["orgaos"] = sorted(d["orgaos"])
            d["valor_adjudicado"] = round(d["valor_adjudicado"], 2)
            achados.append(d)
    achados.sort(key=lambda x: (-x["n_atas"], -x["valor_adjudicado"]))
    return {
        "ok": True, "n": len(achados),
        "materias": corpus["materias"], "atas_mineradas": len(corpus["atas"]),
        "achados": achados, "ressalva": RESSALVA,
    }


# ── Detector B1c — canal informal @gmail ─────────────────────────────────────
def canal_informal(db_path=None) -> dict:
    """E-mails ``@gmail.com`` usados como canal de compra por órgão municipal.

    Pesquisa de mercado / retirada de empenho por e-mail pessoal (gratuito, sem
    rastro institucional) é vetor de baixa transparência e de direcionamento —
    contorna o processo formal (SIGA/SEI). Indício de fragilidade de controle.
    """
    corpus = minerar_corpus(db_path)
    achados = sorted(corpus["gmails"], key=lambda g: -g["n_materias"])
    return {
        "ok": True, "n": len(achados),
        "materias": corpus["materias"],
        "achados": achados, "ressalva": RESSALVA,
    }


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "resumo"
    if cmd == "concentracao":
        print(json.dumps(concentracao_vencedor(), ensure_ascii=False, indent=1))
    elif cmd == "gmail":
        print(json.dumps(canal_informal(), ensure_ascii=False, indent=1))
    else:
        c = minerar_corpus()
        print(json.dumps({"materias": c["materias"], "atas": len(c["atas"]),
                          "empenhos": len(c["empenhos"]), "gmails": len(c["gmails"])},
                         ensure_ascii=False, indent=1))
