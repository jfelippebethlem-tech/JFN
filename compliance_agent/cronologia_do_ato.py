# -*- coding: utf-8 -*-
"""CRONOLOGIA DO ATO — a data escrita DENTRO da peça, não a da juntada.

`cadeia_processo` afere a ordem legal pela data do TÍTULO ou, na falta, pelo ID do documento no SEI — que mede
quando a peça foi JUNTADA. A fraude de calendário mais eloquente não aparece aí. Caso que originou o módulo
(SEEDUC × EUREKA, Contrato 39/2024, R$ 125.949.837,44, lido em 25/09/2026):

    30/12/2024 20:18  contrato assinado            (dotação "do corrente exercício de 2024")
    31/12/2024        NL 2024NL26909 — "passivo reconhecido e LIQUIDADO", valor integral
    08/01/2025 12:57  ordem de fornecimento (e-mail, "considerando a publicação")
    08/01/2025 14:56  NF 1.780 pelo valor integral
    08/01/2025        conferência, aceite e atesto de todo o material

Pelo ID do SEI a NL (91016913) vem DEPOIS da NF (90442592) — "em ordem". Pela data de emissão escrita na NL, a
liquidação é 8 dias ANTERIOR à ordem de fornecimento: liquidou-se o que ainda não tinha sido pedido. A Nota
Patrimonial "de 31/12/24" cita o processo SEI-…/2025, que não existia em 2024 — o documento foi gerado com data
retroativa no período de encerramento do exercício.

Regras (todas determinísticas; cada achado cita as duas peças e as duas datas):
  • liquidacao_antes_da_entrega — NL emitida antes da NF, da ordem ou do aceite (Lei 4.320/1964, art. 63, §2º:
    a liquidação se baseia nos comprovantes da entrega). 🔴
  • ato_anterior_ao_processo — NL/NP/NE com emissão anterior à CRIAÇÃO do processo que a contém (data do
    catálogo público). 🔴 — só quando a data de criação é conhecida.
  • conferencia_antes_da_ordem — termo de recebimento com conferência ANTERIOR à ordem de fornecimento: ou o
    material chegou antes de ser pedido, ou o termo foi copiado sem nova conferência. 🟡
  • entrega_no_dia_da_ordem — NF e aceite no MESMO dia da ordem. Sozinho não é irregular (estoque pronto); é o
    que dá peso aos outros. 🟡 (atributo)

HONESTIDADE: data que não se lê não vira cronologia (INDISPONÍVEL ≠ 0). Peça ausente é lacuna, não inversão.
Indício a verificar nos autos; presunção de legitimidade.
"""
from __future__ import annotations

import re
from datetime import date

_D4 = r"(\d{2})/(\d{2})/(\d{4})"


def _dt(d: str, m: str, a: str) -> date | None:
    a = int(a)
    if a < 100:
        a += 2000
    if not 2000 <= a <= 2035:          # OCR: "27/08/7024", "31/03/2625" viraram 1.826.177 dias de inversão
        return None
    try:
        return date(a, int(m), int(d))
    except ValueError:
        return None


def _primeira(rx: re.Pattern, texto: str) -> date | None:
    m = rx.search(texto or "")
    return _dt(*m.groups()) if m else None


# NL do SIAFE: "…\n2024NL26909\n31/12/24" (número do documento e, logo abaixo, a emissão)
_RX_NL = re.compile(r"\b20\d{2}NL\d+\s*\n\s*(\d{2})/(\d{2})/(\d{2,4})\b")
# NF-e (DANFE / consulta): "DATA DA EMISSÃO\n08/01/2025" · "Data de Emissão\n08/01/2025 14:56" · "EMISSÃO: 08/01/2025"
_RX_NF = re.compile(r"(?:data\s+d[ae]\s+emiss[ãa]o|\bemiss[ãa]o:)\s*\n?\s*" + _D4, re.I)
# ordem de fornecimento: planilha "Data da Emissão | 2025-01-28" · e-mail "Data Qua, 08/01/2025 12:57"
_RX_OF_ISO = re.compile(r"data\s+da\s+emiss[ãa]o\s*\|\s*(\d{4})-(\d{2})-(\d{2})", re.I)
_RX_OF_MAIL = re.compile(r"^\s*Data\s+\w{3},?\s+" + _D4, re.I | re.M)
_RX_CONF = re.compile(r"data\s+de\s+confer[êe]ncia:\s*" + _D4, re.I)
_RX_ACEITE = re.compile(r"data\s+(?:do\s+)?aceite:\s*" + _D4, re.I)

_T_NL = re.compile(r"nota\s+de\s+liquida|\b20\d{2}NL\d+", re.I)
_T_NF = re.compile(r"nota\s+fiscal|\bnf-?e?\b|\bnfs-?e\b|danfe", re.I)
_T_OF = re.compile(r"ordem[\s_]+(?:de[\s_]+)?(?:fornecimento|servi[çc]o|in[íi]cio|execu[çc][ãa]o)", re.I)
_T_REC = re.compile(r"termo\s+de\s+recebimento|relat[óo]rio\s+de\s+fiscaliza|atestado\s+de\s+recebimento", re.I)
_T_PATRIM = re.compile(r"nota\s+patrimonial|\b20\d{2}NP\d+|nota\s+de\s+empenho|\b20\d{2}NE\d+", re.I)
_RX_NP = re.compile(r"\b20\d{2}N[PE]\d+\s*\n\s*(\d{2})/(\d{2})/(\d{2,4})\b")


def datas_do_processo(docs: list[dict]) -> dict:
    """{marco: [(data, titulo)]} lido do TEXTO de cada peça. `docs`: [{titulo, tipo, texto}]."""
    out: dict[str, list] = {"liquidacao": [], "nota_fiscal": [], "ordem": [], "conferencia": [], "aceite": [],
                            "patrimonial": []}
    for d in docs or []:
        t = str(d.get("titulo") or "")
        x = str(d.get("texto") or "")
        tipo = str(d.get("tipo") or "")
        if _T_NL.search(t) or tipo == "nota_liquidacao":
            for m in _RX_NL.finditer(x):
                if (dd := _dt(*m.groups())):
                    out["liquidacao"].append((dd, t))
        elif _T_NF.search(t) or tipo == "nota_fiscal":
            if (dd := _primeira(_RX_NF, x)):
                out["nota_fiscal"].append((dd, t))
        if _T_OF.search(t) or tipo == "ordem_inicio":
            m = _RX_OF_ISO.search(x)
            dd = _dt(m.group(3), m.group(2), m.group(1)) if m else _primeira(_RX_OF_MAIL, x)
            if dd:
                out["ordem"].append((dd, t))
        if _T_REC.search(t) or tipo in ("aceite", "fiscalizacao"):
            if (dd := _primeira(_RX_CONF, x)):
                out["conferencia"].append((dd, t))
            if (dd := _primeira(_RX_ACEITE, x)):
                out["aceite"].append((dd, t))
        if _T_PATRIM.search(t):
            for m in _RX_NP.finditer(x):
                if (dd := _dt(*m.groups())):
                    out["patrimonial"].append((dd, t))
    return out


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _citam_o_processo(docs: list[dict], numero: str) -> set[str]:
    """Títulos das peças orçamentárias (NL/NP/NE) cujo TEXTO cita o número deste processo."""
    m = re.search(r"(\d{6})/(\d{6})/(\d{4})", numero or "")
    if not m:
        return set()
    rx = re.compile(rf"{m[1]}\D{{0,2}}{m[2]}\D{{0,2}}{m[3]}")
    return {str(d.get("titulo")) for d in docs or []
            if (_T_NL.search(str(d.get("titulo") or "")) or _T_PATRIM.search(str(d.get("titulo") or "")))
            and rx.search(str(d.get("texto") or ""))}


def analisar(docs: list[dict], *, criado_em: date | None = None, numero_processo: str = "") -> dict:
    """Veredito RESOLVIDO: {grau, achados[], datas, resumo, ressalva}.

    `criado_em`: data de criação do processo (catálogo público), quando conhecida. Sem ela, o limite EXATO é o
    ano do número do processo — mas só vale contra peça que CITA o próprio processo no texto (um processo de 2025
    pode juntar anexos legítimos de 2024; a NL que diz "Processo SEI-…/2025" não pode ser de 2024)."""
    dt = datas_do_processo(docs)
    if not criado_em and (m := re.search(r"/(\d{4})\b", numero_processo or "")):
        citam = _citam_o_processo(docs, numero_processo)
        piso = date(int(m[1]), 1, 1)
        retro = [(d, t) for d, t in dt["liquidacao"] + dt["patrimonial"] if t in citam and d < piso]
        if retro:
            d0, t0 = min(retro)
            criado_em, _limite = piso, t0
    achados: list[dict] = []
    # 🔴 NL antes da ORDEM: a ordem precede tudo — liquidou-se o que nem tinha sido pedido. Comparar a 1ª NL com
    # a 1ª NF confundia MESES em serviço contínuo com várias NLs (030002/000307/2025: NF do 1º mês sem data lida).
    if dt["liquidacao"] and dt["ordem"]:
        nl_d, nl_t = min(dt["liquidacao"])
        o_d, o_t = min(dt["ordem"])
        if nl_d < o_d:
            achados.append({
                "tipo": "liquidacao_antes_da_ordem", "grau": "vermelho",
                "fundamento": "Lei 4.320/1964, art. 63, §2º — a liquidação se baseia nos comprovantes da entrega",
                "diz": (f"A liquidação ({nl_t}) foi emitida em {_fmt(nl_d)}, {(o_d - nl_d).days} dia(s) ANTES da "
                        f"ordem de fornecimento/serviço ({o_t}, {_fmt(o_d)}): liquidou-se o que ainda não tinha "
                        "sido pedido — ou a NL foi datada retroativamente."),
                "pecas": [nl_t, o_t]})
    # 🟡 NL antes da NF: só num ÚNICO ciclo — toda NF legível posterior à ÚLTIMA NL. Em serviço contínuo com
    # faturamento de dezembro emitido em janeiro (SEGOV × PRIME, 420001/000112/2025) é lançamento por competência
    # no encerramento do exercício: conferir se o fato ocorreu no exercício, não acusar.
    if dt["liquidacao"] and dt["nota_fiscal"] and not any(a["tipo"] == "liquidacao_antes_da_ordem" for a in achados):
        nl_max, nl_t = max(dt["liquidacao"])
        nf_min, nf_t = min(dt["nota_fiscal"])
        if nl_max < nf_min:
            achados.append({
                "tipo": "liquidacao_antes_da_nf", "grau": "amarelo",
                "fundamento": "Lei 4.320/1964, art. 63, §2º, III — comprovante da entrega; conferir a competência",
                "diz": (f"Toda liquidação (a última: {nl_t}, {_fmt(nl_max)}) é anterior à primeira nota fiscal "
                        f"({nf_t}, {_fmt(nf_min)}). Em serviço contínuo pode ser lançamento por competência no "
                        "encerramento do exercício; em compra, é liquidação sem documento fiscal."),
                "pecas": [nl_t, nf_t]})
    if criado_em:
        citam = _citam_o_processo(docs, numero_processo) if numero_processo else None
        retro = [(d, t) for d, t in dt["liquidacao"] + dt["patrimonial"]
                 if d < criado_em and (citam is None or t in citam)]
        if retro:
            d0, t0 = min(retro)
            achados.append({
                "tipo": "ato_anterior_ao_processo",
                "grau": "vermelho" if any(a["tipo"] == "liquidacao_antes_da_ordem" for a in achados) else "amarelo",
                "fundamento": ("data retroativa — o SIAFE aceita lançamento com data de 31/12 no encerramento do "
                               "exercício, o que só é legítimo se o FATO ocorreu no exercício"),
                "diz": (f"{t0} traz emissão em {_fmt(d0)} e cita no próprio texto o processo {numero_processo or ''}"
                        f", que não existia antes de {_fmt(criado_em)}: o documento foi gerado depois, com data "
                        "anterior.").replace(" o processo ,", " este processo,"),
                "pecas": [t0]})
    if dt["conferencia"] and dt["ordem"]:
        c_d, c_t = min(dt["conferencia"])
        o_d, o_t = max(dt["ordem"])
        if c_d < o_d:
            achados.append({
                "tipo": "conferencia_antes_da_ordem", "grau": "amarelo",
                "fundamento": "Lei 14.133/2021, art. 140 — recebimento após a execução do que foi pedido",
                "diz": (f"O termo de recebimento ({c_t}) registra conferência em {_fmt(c_d)}, antes da ordem de "
                        f"fornecimento ({o_t}, {_fmt(o_d)}): o material chegou antes de ser pedido, ou o termo foi "
                        "copiado de outra entrega sem nova conferência."),
                "pecas": [c_t, o_t]})
    if dt["ordem"] and dt["nota_fiscal"] and dt["aceite"]:
        o_d = min(d for d, _ in dt["ordem"])
        if any(d == o_d for d, _ in dt["nota_fiscal"]) and any(d == o_d for d, _ in dt["aceite"]):
            achados.append({
                "tipo": "entrega_no_dia_da_ordem", "grau": "amarelo",
                "fundamento": "atributo — dá peso aos demais; sozinho não é irregular (estoque pronto)",
                "diz": f"Ordem, nota fiscal e aceite no mesmo dia ({_fmt(o_d)}).",
                "pecas": []})
    datas = {k: [(_fmt(d), t) for d, t in sorted(v)] for k, v in dt.items() if v}
    if not any(dt.values()):
        return {"grau": "nao_aplicavel", "achados": [], "datas": {},
                "resumo": "Nenhuma data de ato legível nas peças de despesa — a cronologia não é avaliável aqui.",
                "ressalva": _RESSALVA, "fonte": "cronologia_do_ato (determinístico/offline)"}
    grau = "vermelho" if any(a["grau"] == "vermelho" for a in achados) else (
        "amarelo" if achados else "verde")
    return {"grau": grau, "achados": achados, "datas": datas,
            "resumo": ("; ".join(a["diz"] for a in achados) if achados
                       else "Datas dos atos de despesa em ordem compatível (ordem → NF/aceite → liquidação)."),
            "ressalva": _RESSALVA, "fonte": "cronologia_do_ato (determinístico/offline)"}


_RESSALVA = ("datas lidas do TEXTO das peças (emissão da NL/NF, da ordem, conferência/aceite); OCR pode errar um "
             "dígito — conferir no documento. Indício a verificar nos autos, nunca prova; presunção de legitimidade.")


def docs_do_arquivo(dir_processo) -> list[dict]:
    """[{titulo, tipo, texto}] de `data/sei_arquivo/<proc>/` (manifesto + textos)."""
    import json
    from pathlib import Path
    d = Path(dir_processo)
    try:
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError):
        return []
    out = []
    for x in man.get("docs") or []:
        if not isinstance(x, dict) or not x.get("texto"):
            continue
        try:
            txt = (d / x["texto"]).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        out.append({"titulo": x.get("titulo"), "tipo": x.get("tipo"), "texto": txt})
    return out
