# -*- coding: utf-8 -*-
"""ISS declarado RETIDO na NFS-e × OB que pagou o prestador SEM a retenção (pedido do dono, 18/11/2026).

ORIGEM (medido em 18/11/2026 lendo a fonte primária): quando a NFS-e manda o tomador reter o ISS, a OB ao
prestador deveria sair por bruto − retenções federais aplicáveis − ISS. Se a OB = bruto − retenções federais
(sem o ISS), o valor do ISS foi pago ao prestador. AGILE CORP × SEEDUC (35 processos, R$ 2.270.009,39) e
IDESI × FSERJ (jan.–jul./2024 e 2025, NF de Matias Barbosa/MG) são os casos-índice
(`~/vault/casos/agile-corp-seeduc-emergencia-do-incumbente.md`, `~/vault/casos/idesi-fundacao-saude-rj.md`).

A PROVA (independe do layout da NF): W = Σ bruto das NFs − Σ OB paga ao prestador.
  · "ISS não retido" só quando W fecha AO CENTAVO (tolerância de arredondamento por NF) com um subconjunto das
    retenções federais DECLARADAS na própria NF (INSS, IRRF, PIS, COFINS, CSLL…) e NÃO fecha com esse subconjunto
    + o ISS. OB = bruto (nenhuma retenção) é o subconjunto vazio.
  · fecha com o ISS e não sem ele → RETIDO (correto).
  · fecha dos dois jeitos → INDISPONÍVEL (ambíguo). Não fecha → INDISPONÍVEL (pagamento parcial, glosa, outra NF).

HIPÓTESES INOCENTES EXCLUÍDAS POR CÓDIGO
  · regime muda no mesmo fornecedor (IDESI ago.–set./2024, "Data de vencimento do ISS" = o prestador recolhe):
    a bandeira é lida NF a NF; só NF que manda o TOMADOR reter entra (`extrair_nfs`, `_bandeira`);
  · PIS/COFINS/CSLL destacados e não retidos pelo tomador estadual: qualquer subconjunto das federais é aceito
    como "o que o Estado reteve" — a falta delas nunca vira ISS (`decidir`);
  · retenção paga em OB separada ao Município/Fundo/DARM: OB paga a QUALQUER outro credor no mesmo processo ou na
    mesma NL rebaixa a PENDENTE (`decidir`, `_obs_terceiros`);
  · arredondamento de centavos: tolerância de R$ 0,05 por NF, e o ISS tem de ser > 20× a tolerância (`decidir`);
  · OCR que troca dígito: o ISS só é aceito se ≈ base × alíquota (2% a 5%) e a NF fecha a própria conta
    (líquido = bruto − retenções declaradas); formato que não fecha não é lido (`_validar_*`);
  · documento órfão na pasta do processo: só documentos DECLARADOS no manifesto (`ler_nfs_do_processo`).

DOMÍNIO: NFS-e de serviço (Nota Carioca e layouts "VALOR DA NOTA =", ISSnet, Futurize, DANFSe nacional) em
processos de pagamento do acervo SEI com OB Contabilizada do SIAFE (`_ob_paga`). Fora disso: INDISPONÍVEL com
o motivo. O detector afirma que o VALOR do ISS foi pago ao prestador; se o prestador recolheu o ISS por conta
própria, não há dano — o recolhimento é INDISPONÍVEL aqui (pedir as guias à Secretaria de Fazenda do Município).
Indício para requerer documentos, não acusação.

CLI:
  python -m compliance_agent.detector_iss_retido [--processo SEI-…] [--saida data/iss_nao_retido.json]
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ACERVO = REPO / "data" / "sei_arquivo"
DB = REPO / "data" / "compliance.db"
SAIDA = REPO / "data" / "iss_nao_retido.json"

TOL_POR_NF = 0.05          # arredondamento de centavos por NF somada
ISS_MIN_X_TOL = 20         # ISS precisa ser > 20× a tolerância para a decisão valer
ALIQ_MIN, ALIQ_MAX = 2.0, 5.0   # LC 116/2003 art. 8º-A e art. 8º, II

# Documento que é (ou carrega) NFS-e: pelo título ou pelo arquivo declarado no manifesto.
RE_DOC_NF = re.compile(r"nota[\s_]+fiscal|\bnfs|nfse|danfse|(?:^|[\s_])nf(?:[\s_.]|$)", re.I)

_MOEDA = r"\d{1,3}(?:\.\d{3})*,\d{2}"


def _num(s: str) -> float:
    return float(s.replace("R$", "").strip().replace(".", "").replace(",", "."))


def _fmt(v: float) -> str:
    """1234567.8 → '1.234.567,80' (como a NF imprime)."""
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tem_moeda(texto: str, v: float) -> bool:
    return re.search(r"(?<![\d.,])" + re.escape(_fmt(v)) + r"(?![\d])", texto) is not None


def _iss_confere(base: float, aliq: float, iss: float) -> bool:
    return ALIQ_MIN <= aliq <= ALIQ_MAX and abs(round(base * aliq / 100, 2) - iss) <= 0.02


def _nf(formato, numero, bruto, iss, aliq, retido, comps, liquido, segmento) -> dict:
    return {"formato": formato, "numero": numero, "bruto": round(bruto, 2), "iss": round(iss, 2), "aliquota": aliq,
            "iss_retido_tomador": retido, "componentes": {k: round(v, 2) for k, v in comps.items() if v > 0.004},
            "liquido_nf": None if liquido is None else round(liquido, 2), "_digitos": re.sub(r"\D", "", segmento)}


# ───────────────────────────── extratores (cada um valida a própria conta da NF) ─────────────────────────────

# ISSnet (Duque de Caxias e outros): bloco de 7 retenções + "Valor Líquido da Nota Fiscal".
_RE_ISSNET_BLOCO = re.compile(
    r"Reten[çc][õo]es de Impostos\s*PIS\s*COFINS\s*INSS\s*IRRF\s*CSLL\s*Outras Reten[çc][õo]es\s*ISSQN\s*"
    r"((?:R\$\s*" + _MOEDA + r"\s*){7})Valor L[íi]quido da Nota Fiscal\s*R\$\s*(" + _MOEDA + ")")


def _issnet(texto: str) -> list[dict]:
    out, ini = [], 0
    for m in _RE_ISSNET_BLOCO.finditer(texto):
        seg = texto[ini:m.end()]
        ini = m.end()
        v = [_num(x) for x in re.findall(_MOEDA, m.group(1))]
        pis, cofins, inss, irrf, csll, outras, iss = v
        liq = _num(m.group(2))
        mb = re.findall(r"Desconto Condicionado\s*R\$\s*(" + _MOEDA + ")", seg)
        mr = re.search(r"ISSQN Retido(.{0,300}?)\b(Sim|N[ãa]o)\b", seg, re.S)
        ma = re.search(r"Al[íi]quota.{0,300}?\n\s*(\d{1,2},\d{2})\s*\n", seg, re.S)
        mn = re.search(r"N[úu]mero da Nota Fiscal\s*\n\s*(\d+)", seg)
        if not (mb and mr and ma):
            continue
        bruto, aliq = _num(mb[-1]), _num(ma.group(1))
        if abs(bruto - (pis + cofins + inss + irrf + csll + outras + iss) - liq) > 0.05:
            continue                        # a NF não fecha a própria conta (leitura errada) → não se usa
        retido = mr.group(2).lower() == "sim"
        if retido and not _iss_confere(bruto, aliq, iss):
            continue
        out.append(_nf("issnet", mn.group(1) if mn else None, bruto, iss, aliq, retido,
                       {"PIS": pis, "COFINS": cofins, "INSS": inss, "IRRF": irrf, "CSLL": csll, "Outras": outras},
                       liq, seg))
    return out


# Futurize (Matias Barbosa/MG e outros): 7 federais + 8 valores do ISS.
_RE_FUTURIZE = re.compile(
    r"PIS \(R\$\)\s*COFINS \(R\$\)\s*INSS \(R\$\)\s*IR \(R\$\)\s*CSLL \(R\$\)\s*SEST SENAT \(R\$\)\s*"
    r"Outras Reten[çc][õo]es \(R\$\)\s*((?:" + _MOEDA + r"\s*){7})"
    r"Dedu[çc][õo]es \(R\$\)\s*Desc\. Incond \+ Cond\s*\(R\$\)\s*Base de C[áa]lculo \(R\$\)\s*Al[íi]quota \(%\)\s*"
    r"Valor do ISS \(R\$\)\s*ISS Retido \(R\$\)\s*ISS Devido \(R\$\)\s*Valor L[íi]quido \(R\$\)\s*"
    r"((?:" + _MOEDA + r"\s*){8})")


def _futurize(texto: str) -> list[dict]:
    out, ini = [], 0
    for m in _RE_FUTURIZE.finditer(texto):
        seg = texto[ini:m.end()]
        ini = m.end()
        fed = [_num(x) for x in re.findall(_MOEDA, m.group(1))]
        ded, desc, base, aliq, iss, iss_ret, _devido, liq = [_num(x) for x in re.findall(_MOEDA, m.group(2))]
        mb = re.findall(r"VALOR TOTAL DE SERVI[ÇC]OS\s*=\s*R\$\s*(" + _MOEDA + ")", seg)
        mn = re.search(r"N[ºo°] da Nota\s*\n\s*([\d/]+)", seg)
        if not mb:
            continue
        bruto = _num(mb[-1])
        if abs(bruto - ded - desc - sum(fed) - iss_ret - liq) > 0.05 or abs(bruto - ded - desc - base) > 0.05:
            continue
        retido = iss_ret > 0.004
        if retido and (abs(iss_ret - iss) > 0.02 or not _iss_confere(base, aliq, iss)):
            continue
        nomes = ["PIS", "COFINS", "INSS", "IRRF", "CSLL", "SEST_SENAT", "Outras"]
        out.append(_nf("futurize", mn.group(1) if mn else None, bruto, iss, aliq, retido, dict(zip(nomes, fed)),
                       liq, seg))
    return out


# DANFSe (NFS-e nacional): pares rótulo → valor na linha seguinte; um arquivo pode ter várias notas.
def _campo(seg: str, rotulo: str) -> str | None:
    m = re.search(rotulo + r"\s*\n\s*([^\n]+)", seg)
    return m.group(1).strip() if m else None


def _val(s: str | None) -> float | None:
    if s is None:
        return None
    if s.strip() in {"-", "R$", ""}:
        return 0.0
    m = re.search(_MOEDA, s)
    return _num(m.group(0)) if m else None


def _danfse(texto: str) -> list[dict]:
    out = []
    partes = re.split(r"Documento Auxiliar da NFS-e", texto)
    for seg in partes[1:]:
        reten = _campo(seg, r"Reten[çc][ãa]o do ISSQN")
        bruto = _val(_campo(seg, r"Valor do Servi[çc]o"))
        iss = _val(_campo(seg, r"ISSQN Apurado"))
        aliq_s = _campo(seg, r"Al[íi]quota Aplicada")
        liq = _val(_campo(seg, r"Valor L[íi]quido da NFS-e"))
        irrf = _val(_campo(seg, r"\nIRRF"))
        cp = _val(_campo(seg, r"CP Retido"))
        pcc = _val(_campo(seg, r"PIS/COFINS/CSLL Retidos"))
        if None in (reten, bruto, iss, liq, irrf, cp, pcc) or not aliq_s:
            continue
        ma = re.search(r"(\d{1,2},\d{2})\s*%", aliq_s)
        if not ma:
            continue
        aliq = _num(ma.group(1))
        retido = reten.lower().startswith("retido pelo tomador")
        bc = _val(_campo(seg, r"BC ISSQN")) or bruto
        if abs(bruto - (iss if retido else 0) - irrf - cp - pcc - liq) > 0.05:
            continue
        if retido and not _iss_confere(bc, aliq, iss):
            continue
        out.append(_nf("danfse", _campo(seg, r"N[úu]mero da NFS-e"), bruto, iss, aliq, retido,
                       {"IRRF": irrf, "INSS": cp, "PIS_COFINS_CSLL": pcc}, liq, seg))
    return out


# Nota Carioca e layouts "VALOR (TOTAL) DA NOTA = R$" (Nova Iguaçu e outros, quase sempre OCR).
_RE_RETIDO_TOMADOR = re.compile(r"ser[áa]\s+RETIDO\s+pelo\s+Tomador|ISS\s+RETIDO\s+NA\s+FONTE\s+PELO\s+TOMADOR", re.I)
_RE_PRESTADOR_RECOLHE = re.compile(r"Data\s+de\s+vencimento\s+do\s+I[S5$3]{2}|N[ÃA]O\s+RETIDO|ISS\s+A\s+RECOLHER", re.I)
_RE_CARIOCA_BRUTO = re.compile(r"VALOR\s+(?:TOTAL\s+)?DA\s+NOTA\s*=\s*R\$\s*(" + _MOEDA + ")", re.I)
_RE_FED_PCT = re.compile(r"\b(PIS|COFINS|INSS|IRRF|IR|CSLL)\s*\(\s*(\d{1,2},\d{2,4})\s*%\s*\)", re.I)


def _bandeira(seg: str) -> bool | None:
    pos, neg = bool(_RE_RETIDO_TOMADOR.search(seg)), bool(_RE_PRESTADOR_RECOLHE.search(seg))
    return None if pos == neg else pos


def _carioca(texto: str) -> list[dict]:
    out = []
    achados = list(_RE_CARIOCA_BRUTO.finditer(texto))
    for i, m in enumerate(achados):
        a = achados[i - 1].end() if i else 0
        b = achados[i + 1].start() if i + 1 < len(achados) else len(texto)
        seg = texto[a:b]
        bruto = _num(m.group(1))
        retido = _bandeira(seg)
        if retido is None:
            continue
        valores = sorted({_num(x) for x in re.findall(_MOEDA, seg)})
        # ISS = base × alíquota, conferido contra um valor IMPRESSO na nota (OCR troca dígito; a conta não)
        iss = aliq = None
        for al in {_num(x) for x in re.findall(r"(\d{1,2},\d{2})\s*%", seg)}:
            if not (ALIQ_MIN <= al <= ALIQ_MAX):
                continue
            for base in [bruto] + [v for v in valores if v < bruto]:
                cand = round(base * al / 100, 2)
                # 0,015: a Nota Carioca TRUNCA o centavo (681.234,34 × 5% = 34.061,717 → impresso 34.061,71)
                if base >= bruto * 0.3 and any(abs(cand - v) <= 0.015 for v in valores):
                    iss, aliq = next(v for v in valores if abs(cand - v) <= 0.015), al
                    break
            if iss is not None:
                break
        if iss is None:
            continue
        ml = re.search(r"Valor\s+L[íi]quido(?:\s+a\s+Pagar)?:?\s*R\$\s*(" + _MOEDA + ")", seg, re.I)
        liq = _num(ml.group(1)) if ml else None
        comps: dict[str, float] = {}
        # federais com percentual impresso: valor = alguma base × % ; aceitas só se a NF fechar a conta inteira
        for nome, pct in _RE_FED_PCT.findall(seg):
            p = _num(pct)
            for v in valores:
                if any(abs(round(bb * p / 100, 2) - v) <= 0.015 for bb in valores if bb > v):
                    comps["IRRF" if nome.upper() == "IR" else nome.upper()] = v
                    break
        if liq is not None:
            resto = bruto - (iss if retido else 0) - liq
            if resto < -0.05:
                continue
            if comps and abs(sum(comps.values()) - resto) > 0.05:
                comps = {}
            if not comps and resto > 0.05:
                comps = {"retencoes_federais_nf": resto}   # só o total: vale como bloco único
        elif comps:
            comps = {}                                     # sem líquido não há como conferir as federais
        mn = re.search(r"N[úu]mero da Nota\s*\n+[^\n]*?(\d{5,9})", seg)
        out.append(_nf("carioca", mn.group(1).lstrip("0") if mn else None, bruto, iss, aliq, retido, comps, liq, seg))
    return out


def extrair_nfs(texto: str) -> list[dict]:
    """NFs de serviço lidas e conferidas num texto. Formato que não fecha a própria conta não entra."""
    for f in (_danfse, _futurize, _issnet):
        r = f(texto)
        if r:
            return r
    return _carioca(texto)


# Prova de que o ISS foi RECOLHIDO por alguém (o prestador com guia própria, ou o Estado em PD de retenção): rebaixa a
# PENDENTE. Medido em 18/11/2026: Construverde/Brasform/RJL2/Ctesa juntam "Guia de ISS e comp. pagto" ("IMPOSTO ISS PAG
# ANTECIPADO REF NF 4732") — o prestador recolheu e o Estado reembolsou na OB: sem dano. Só TÍTULO do documento ou
# CONTEÚDO de guia contam: o e-mail de faturamento da SEEDUC PEDE "comprovante de pagamento de ISS" no checklist, e
# pedir não é provar (AGILE, 22 processos com o checklist e nenhuma guia nos autos).
_RE_TITULO_GUIA_ISS = re.compile(
    r"guia\W{0,3}(?:d[eo]\W{1,3})?iss|\bdarm\b|comp\w*\W{1,3}(?:d[eo]\W{1,3})?(?:pag\w*|recolh\w*)\W{1,3}(?:d[eo]\W{1,3})?iss"
    r"|programa[çc][ãa]o\W{1,3}de\W{1,3}desembolso.{0,60}\biss", re.I)
_RE_CONTEUDO_GUIA_ISS = re.compile(
    r"Documento\s+de\s+Arrecada[çc][ãa]o\s+(?:de\s+Receitas\s+)?Municipa|ISSQN\s+RETEN[ÇC][ÃA]O\s+CORRENTE"
    r"|IMPOSTO\s+ISS\s+PAG|Tipo\s+de\s+Reten[çc][ãa]o\s*\n\s*ISS", re.I)


def provas_de_recolhimento(docs: list[tuple[str, str, str]]) -> list[str]:
    """[(arquivo, título, texto)] → evidências literais de guia/DARM/PD de ISS nos autos."""
    out = []
    for arq, tit, txt in docs:
        m = _RE_TITULO_GUIA_ISS.search(tit) or _RE_TITULO_GUIA_ISS.search(Path(arq).name.replace("_", " "))
        m = m or _RE_CONTEUDO_GUIA_ISS.search(txt)
        if m:
            out.append(f"{arq}: «{' '.join(m.group(0).split())}»")
    return out


def nf_menciona_iss_retido(texto: str) -> bool:
    """Para a cobertura: o texto fala em ISS retido pelo tomador (lido ou não)."""
    return bool(_RE_RETIDO_TOMADOR.search(texto) or re.search(
        r"Retido pelo Tomador|ISSQN Retido.{0,300}?\bSim\b|ISS Retido \(R\$\)", texto, re.I | re.S))


# ───────────────────────────── decisão (pura, testável) ─────────────────────────────

def _somas_federais(nfs: list[dict]) -> list[tuple[float, tuple[str, ...]]]:
    """Σ de cada subconjunto de NOMES de retenção federal (o mesmo tratamento para todas as NFs do conjunto)."""
    nomes = sorted({k for n in nfs for k in n["componentes"]})
    out = []
    for r in range(len(nomes) + 1):
        for sub in itertools.combinations(nomes, r):
            out.append((sum(n["componentes"].get(k, 0.0) for n in nfs for k in sub), sub))
    return out


def decidir(nfs: list[dict], obs_prestador: list[dict], obs_terceiros: list[dict],
            provas: list[str] | None = None) -> dict:
    """Um conjunto de NFs (todas do mesmo prestador) × as OB pagas ao prestador que as quitam.

    Devolve {classe, estado, motivo, w, iss, subconjunto}. classe ∈ ISS_NAO_RETIDO | RETIDO | INDISPONIVEL |
    FORA_DO_DOMINIO. estado ∈ VERIFICADO | PENDENTE | INDISPONÍVEL."""
    if not nfs:
        return {"classe": "INDISPONIVEL", "estado": "INDISPONÍVEL", "motivo": "nenhuma NF lida"}
    if any(n["iss_retido_tomador"] is not True for n in nfs):
        return {"classe": "FORA_DO_DOMINIO", "estado": "INDISPONÍVEL",
                "motivo": "a NF não manda o tomador reter o ISS (o prestador recolhe)"}
    if not obs_prestador:
        return {"classe": "INDISPONIVEL", "estado": "INDISPONÍVEL", "motivo": "sem OB paga ao prestador no processo"}
    tol = TOL_POR_NF * len(nfs)
    bruto = sum(n["bruto"] for n in nfs)
    iss = round(sum(n["iss"] for n in nfs), 2)
    ob = round(sum(o["valor"] for o in obs_prestador), 2)
    w = round(bruto - ob, 2)
    base = {"w": w, "iss": iss, "bruto": round(bruto, 2), "ob": ob, "tolerancia": round(tol, 2)}
    if iss <= ISS_MIN_X_TOL * tol:
        return {**base, "classe": "INDISPONIVEL", "estado": "INDISPONÍVEL", "motivo": "ISS menor que a margem de arredondamento"}
    somas = _somas_federais(nfs)
    sem = [sub for s, sub in somas if abs(w - s) <= tol]
    com = [sub for s, sub in somas if abs(w - s - iss) <= tol]
    if sem and com:
        return {**base, "classe": "INDISPONIVEL", "estado": "INDISPONÍVEL",
                "motivo": "a conta fecha com e sem o ISS (ambíguo)"}
    if com:
        return {**base, "classe": "RETIDO", "estado": "VERIFICADO", "subconjunto": list(com[0]),
                "motivo": "OB = bruto − retenções federais − ISS: o ISS foi retido"}
    if not sem:
        return {**base, "classe": "INDISPONIVEL", "estado": "INDISPONÍVEL",
                "motivo": "a OB não fecha com a NF (pagamento parcial, glosa ou outra NF)"}
    r = {**base, "classe": "ISS_NAO_RETIDO", "subconjunto": list(sem[0]),
         "motivo": "OB = bruto − " + (" − ".join(sem[0]) if sem[0] else "nada") + ": o ISS foi pago ao prestador"}
    if provas:
        return {**r, "estado": "PENDENTE", "provas_recolhimento": provas[:5],
                "motivo": r["motivo"] + "; os autos trazem guia/DARM/PD de ISS — o ISS pode ter sido recolhido (sem dano)"}
    if obs_terceiros:
        return {**r, "estado": "PENDENTE",
                "motivo": r["motivo"] + "; há OB a outro credor no mesmo processo/NL — conferir se é o recolhimento do ISS"}
    return {**r, "estado": "VERIFICADO"}


def _casar(nfs: list[dict], obs: list[dict], terceiros: list[dict], provas: list[str] | None = None) -> list[dict]:
    """Casa NFs com OB. 1º o processo inteiro (todas as NFs × todas as OB); se não fecha, NF a NF contra cada NL."""
    if not nfs:
        return []
    tudo = decidir(nfs, obs, terceiros, provas)
    if tudo["classe"] in ("ISS_NAO_RETIDO", "RETIDO") or len(nfs) == 1 and len({o.get("nl") for o in obs}) <= 1:
        return [{**tudo, "nfs": nfs, "obs": obs}]
    por_nl = defaultdict(list)
    for o in obs:
        por_nl[o.get("nl") or o["numero_ob"]].append(o)
    out, usadas = [], set()
    for n in nfs:
        achou = None
        for nl, grupo in por_nl.items():
            if nl in usadas:
                continue
            ter = [t for t in terceiros if not t.get("nl") or t.get("nl") == nl or t.get("so_processo")]
            d = decidir([n], grupo, ter, provas)
            if d["classe"] in ("ISS_NAO_RETIDO", "RETIDO"):
                achou = {**d, "nfs": [n], "obs": grupo}
                usadas.add(nl)
                break
        out.append(achou or {**decidir([n], [], []), "motivo": "nenhuma OB/NL do processo fecha com esta NF",
                             "classe": "INDISPONIVEL", "estado": "INDISPONÍVEL", "nfs": [n], "obs": []})
    return out


# ───────────────────────────── leitura do acervo e do SIAFE ─────────────────────────────

def processo_sei(pasta: Path) -> str | None:
    m = re.fullmatch(r"(\d{6})_(\d{6})_(\d{4})", pasta.name)
    return f"SEI-{m[1]}/{m[2]}/{m[3]}" if m else None


def ler_nfs_do_processo(pasta: Path) -> tuple[list[dict], int, list[str]]:
    """(NFs lidas e deduplicadas, nº de documentos que falam em ISS retido pelo tomador mas não foram lidos,
    provas de recolhimento de ISS nos autos — só lidas se houver NF de ISS retido).
    Só documentos DECLARADOS no manifesto (a pasta pode ter órfãos de outra captura)."""
    from compliance_agent.sei import acervo_texto as A
    try:
        man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], 0, []
    vistos, nfs, nao_lidos = set(), [], 0
    for d in man.get("docs") or []:
        if not isinstance(d, dict) or not d.get("texto"):
            continue
        if not (RE_DOC_NF.search(str(d.get("titulo") or "")) or RE_DOC_NF.search(Path(str(d["texto"])).name)):
            continue
        try:
            t = A.ler(pasta, d)
        except OSError:
            continue
        lidas = extrair_nfs(t)
        if not lidas and nf_menciona_iss_retido(t):
            nao_lidos += 1
        for n in lidas:
            chave = (n["numero"], n["bruto"], n["iss"]) if n["numero"] else (None, n["bruto"], n["iss"])
            if chave in vistos:
                continue
            vistos.add(chave)
            nfs.append({**n, "documento": f"{pasta.name}/{d['texto']}", "titulo_sei": str(d.get("titulo") or "")[:160]})
    provas: list[str] = []
    if any(n["iss_retido_tomador"] for n in nfs):
        docs = []
        for d in man.get("docs") or []:
            if isinstance(d, dict) and d.get("texto"):
                try:
                    docs.append((str(d["texto"]), str(d.get("titulo") or ""), A.ler(pasta, d)))
                except OSError:
                    continue
        provas = provas_de_recolhimento(docs)
    return nfs, nao_lidos, provas


_COLS_OB = "numero_ob, ug_emitente, data_emissao, nl, credor, nome_credor, valor, exercicio, processo"


def _obs_dos_processos(con, processos: list[str]) -> dict[str, list[dict]]:
    from compliance_agent.cruzamentos_intel import _ob_paga
    out = defaultdict(list)
    for i in range(0, len(processos), 500):
        lote = processos[i:i + 500]
        q = (f"SELECT {_COLS_OB} FROM ob_orcamentaria_siafe WHERE processo IN ({','.join('?' * len(lote))}) "
             f"AND {_ob_paga(con)}")
        for r in con.execute(q, lote):
            d = dict(zip([c.strip() for c in _COLS_OB.split(",")], r))
            out[d["processo"]].append(d)
    return out


def _obs_terceiros_por_nl(con, chaves: set[tuple[str, str]]) -> dict[tuple[str, str], list[dict]]:
    """OB paga a OUTRO credor na mesma NL (mesma UG), fora do processo — a retenção pode sair assim."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    out = defaultdict(list)
    nls = sorted({nl for nl, _ in chaves if nl})
    for i in range(0, len(nls), 500):
        lote = nls[i:i + 500]
        q = f"SELECT {_COLS_OB} FROM ob_orcamentaria_siafe WHERE nl IN ({','.join('?' * len(lote))}) AND {_ob_paga(con)}"
        for r in con.execute(q, lote):
            d = dict(zip([c.strip() for c in _COLS_OB.split(",")], r))
            if (d["nl"], d["ug_emitente"]) in chaves:
                out[(d["nl"], d["ug_emitente"])].append(d)
    return out


def avaliar_processo(sei: str, nfs: list[dict], obs: list[dict], obs_nl: dict | None = None,
                     provas: list[str] | None = None) -> list[dict]:
    """Agrupa as NFs por prestador (CNPJ do credor da OB impresso na NF) e decide cada grupo."""
    obs_nl = obs_nl or {}
    credores = {o["credor"] for o in obs if o.get("credor")}
    res = []
    for cred in sorted(credores):
        raiz = re.sub(r"\D", "", cred)[:8]
        if len(raiz) < 8:
            continue
        do_cred = [n for n in nfs if raiz in n["_digitos"]]
        if not do_cred:
            continue
        obs_p = [o for o in obs if o["credor"] == cred]
        ter = [{**o, "so_processo": True} for o in obs if o["credor"] != cred]
        for o in obs_p:
            ter += [t for t in obs_nl.get((o.get("nl"), o.get("ug_emitente")), []) if t["credor"] != cred
                    and t["numero_ob"] not in {x["numero_ob"] for x in ter}]
        retidas = [n for n in do_cred if n["iss_retido_tomador"]]
        for r in _casar(retidas, obs_p, ter, provas) if retidas else []:
            res.append(_registro(sei, cred, obs_p, r, ter))
        for n in do_cred:
            if not n["iss_retido_tomador"]:
                d = decidir([n], obs_p, ter)
                res.append(_registro(sei, cred, obs_p, {**d, "nfs": [n], "obs": []}, ter))
    return res


def _registro(sei, cred, obs_p, r, ter) -> dict:
    nome = next((o["nome_credor"] for o in obs_p if o.get("nome_credor")), "")
    ugs = sorted({o["ug_emitente"] for o in (r.get("obs") or obs_p)})
    return {
        "processo": sei, "credor": cred, "nome_credor": nome, "ug": ugs[0] if len(ugs) == 1 else ",".join(ugs),
        "classe": r["classe"], "estado": r["estado"], "motivo": r["motivo"],
        "iss_nao_retido": r.get("iss") if r["classe"] == "ISS_NAO_RETIDO" else 0.0,
        "bruto": r.get("bruto"), "ob": r.get("ob"), "w": r.get("w"), "iss": r.get("iss"),
        "subconjunto_federal": r.get("subconjunto"),
        "nfs": [{k: v for k, v in n.items() if not k.startswith("_")} for n in r["nfs"]],
        "obs": [{k: o[k] for k in ("numero_ob", "ug_emitente", "data_emissao", "nl", "valor")} for o in r.get("obs", [])],
        "obs_terceiros": [{k: o[k] for k in ("numero_ob", "nome_credor", "nl", "valor")} for o in ter][:10]
        if r["classe"] == "ISS_NAO_RETIDO" else [],
        "provas_recolhimento": r.get("provas_recolhimento", []),
    }


# ───────────────────────────── varredura e resumo ─────────────────────────────

def varrer(acervo: Path = ACERVO, db: Path = DB, so: str | None = None, workers: int = 1) -> dict:
    pastas = sorted(p for p in acervo.iterdir() if p.is_dir() and processo_sei(p)) if not so else \
        [acervo / so.replace("SEI-", "").replace("/", "_")]
    lidas: dict[str, list[dict]] = {}
    provas: dict[str, list[str]] = {}
    cobertura = defaultdict(int)
    if workers > 1:
        from multiprocessing import Pool
        with Pool(workers) as pool:
            leituras = pool.map(ler_nfs_do_processo, pastas, chunksize=32)
    else:
        leituras = map(ler_nfs_do_processo, pastas)
    for p, (nfs, nao, prv) in zip(pastas, leituras):
        cobertura["docs_iss_retido_nao_lidos"] += nao
        if nfs:
            lidas[processo_sei(p)] = nfs
            provas[processo_sei(p)] = prv
            cobertura["nfs_lidas"] += len(nfs)
            cobertura["nfs_lidas_iss_retido_tomador"] += sum(1 for n in nfs if n["iss_retido_tomador"])
            for n in nfs:
                cobertura[f"formato_{n['formato']}"] += 1
    cobertura["processos_com_nf_lida"] = len(lidas)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    obs = _obs_dos_processos(con, sorted(lidas))
    chaves = {(o["nl"], o["ug_emitente"]) for v in obs.values() for o in v if o.get("nl")}
    obs_nl = _obs_terceiros_por_nl(con, chaves)
    con.close()
    registros = []
    for sei, nfs in lidas.items():
        registros += avaliar_processo(sei, nfs, obs.get(sei, []), obs_nl, provas.get(sei))
    return {"gerado_em": datetime.now().isoformat(timespec="seconds"),
            "fonte": {"nf": "data/sei_arquivo/*/texto (documentos declarados no manifesto)",
                      "ob": "ob_orcamentaria_siafe, filtro cruzamentos_intel._ob_paga"},
            "parametros": {"tol_por_nf": TOL_POR_NF, "iss_min_x_tol": ISS_MIN_X_TOL, "aliquota": [ALIQ_MIN, ALIQ_MAX]},
            "cobertura": dict(cobertura), "registros": registros, **resumir(registros)}


def resumir(registros: list[dict]) -> dict:
    """Por fornecedor×UG e grupo de controle: os DEMAIS fornecedores da mesma UG com NF de ISS retido decidida."""
    forn = defaultdict(lambda: {"processos_nao_retido": set(), "processos_retido": set(), "iss_nao_retido": 0.0,
                                "bruto_nao_retido": 0.0, "pendentes": set(), "indisponiveis": 0, "nome": ""})
    contadas: set = set()   # COR-12: a mesma NF (credor, número, bruto) juntada em dois processos soma uma vez só
    for r in registros:
        f = forn[(r["ug"], r["credor"])]
        f["nome"] = r["nome_credor"]
        chaves = {(r["credor"], n.get("numero"), n.get("bruto")) for n in r.get("nfs") or []}
        if r["classe"] == "ISS_NAO_RETIDO" and r["estado"] == "VERIFICADO" and chaves and chaves <= contadas:
            continue
        contadas |= chaves if r["classe"] == "ISS_NAO_RETIDO" and r["estado"] == "VERIFICADO" else set()
        if r["classe"] == "ISS_NAO_RETIDO" and r["estado"] == "VERIFICADO":
            f["processos_nao_retido"].add(r["processo"])
            f["iss_nao_retido"] += r["iss"]
            f["bruto_nao_retido"] += r["bruto"]
        elif r["classe"] == "ISS_NAO_RETIDO":
            f["pendentes"].add(r["processo"])
        elif r["classe"] == "RETIDO":
            f["processos_retido"].add(r["processo"])
        elif r["classe"] == "INDISPONIVEL":
            f["indisponiveis"] += 1
    linhas = []
    for (ug, cred), f in forn.items():
        nr, rt = len(f["processos_nao_retido"]), len(f["processos_retido"] - f["processos_nao_retido"])
        if nr + rt + len(f["pendentes"]) == 0:
            continue
        outros = [(k, g) for k, g in forn.items() if k[0] == ug and k[1] != cred]
        c_nr = sum(len(g["processos_nao_retido"]) for _, g in outros)
        c_rt = sum(len(g["processos_retido"] - g["processos_nao_retido"]) for _, g in outros)
        c_forn = [g for _, g in outros if g["processos_nao_retido"] or g["processos_retido"]]
        linhas.append({
            "ug": ug, "credor": cred, "nome_credor": f["nome"],
            "processos_iss_nao_retido": nr, "processos_iss_retido": rt, "processos_pendentes": len(f["pendentes"]),
            "nfs_indisponiveis": f["indisponiveis"],
            "iss_nao_retido": round(f["iss_nao_retido"], 2), "bruto_nao_retido": round(f["bruto_nao_retido"], 2),
            "controle_ug": {"fornecedores_decididos": len(c_forn),
                            "fornecedores_com_nao_retido": sum(1 for g in c_forn if g["processos_nao_retido"]),
                            "processos_nao_retido": c_nr, "processos_retido": c_rt,
                            "taxa_nao_retido": round(c_nr / (c_nr + c_rt), 4) if c_nr + c_rt else None},
        })
    linhas.sort(key=lambda x: -x["iss_nao_retido"])
    por_ug = defaultdict(lambda: {"iss_nao_retido": 0.0, "processos": 0, "fornecedores": 0})
    for x in linhas:
        if x["processos_iss_nao_retido"]:
            u = por_ug[x["ug"]]
            u["iss_nao_retido"] = round(u["iss_nao_retido"] + x["iss_nao_retido"], 2)
            u["processos"] += x["processos_iss_nao_retido"]
            u["fornecedores"] += 1
    tot = {"processos_iss_nao_retido_verificado": sum(x["processos_iss_nao_retido"] for x in linhas),
           "fornecedores": sum(1 for x in linhas if x["processos_iss_nao_retido"]),
           "iss_nao_retido_verificado": round(sum(x["iss_nao_retido"] for x in linhas), 2),
           "processos_pendentes": sum(x["processos_pendentes"] for x in linhas),
           "processos_iss_retido": sum(x["processos_iss_retido"] for x in linhas)}
    return {"totais": tot, "por_fornecedor": linhas, "por_ug": dict(por_ug)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--processo")
    ap.add_argument("--saida", default=str(SAIDA))
    ap.add_argument("--sem-gravar", action="store_true")
    ap.add_argument("--workers", type=int, default=1, help="processos de leitura em paralelo (use no it-campo)")
    ap.add_argument("--acervo", default=str(ACERVO))
    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args(argv)
    r = varrer(Path(a.acervo), Path(a.db), so=a.processo, workers=a.workers)
    if not a.sem_gravar and not a.processo:
        tmp = Path(a.saida).with_suffix(".tmp")
        tmp.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(a.saida)
    json.dump({k: r[k] for k in ("cobertura", "totais")}, sys.stdout, ensure_ascii=False, indent=1)
    print()
    for x in r["por_fornecedor"][:40]:
        if x["processos_iss_nao_retido"] or x["processos_pendentes"]:
            print(f"{x['ug']} {x['credor']} {x['nome_credor'][:40]:40} nr={x['processos_iss_nao_retido']} "
                  f"ret={x['processos_iss_retido']} pend={x['processos_pendentes']} ISS=R$ {_fmt(x['iss_nao_retido'])} "
                  f"controle={x['controle_ug']}")
    if a.processo:
        for reg in r["registros"]:
            print(json.dumps({k: v for k, v in reg.items() if k != "nfs"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
