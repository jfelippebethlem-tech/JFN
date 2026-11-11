# -*- coding: utf-8 -*-
"""(B) Contratos da PREFEITURA DO RIO → Área de Planejamento (AP1…AP5), com RA/bairro quando há.

BASE: `pcrj.db.contasrio_contrato` (portal Contas Rio). "Pago" aqui é o `total_pago` DECLARADO pelo
portal para o contrato — não é soma de OB; a fonte vai escrita na tela.

ATRIBUIÇÃO, por ordem de força:
  1. orgao     a UG É regional: "… DA AP 3.2" traz a AP no próprio nome (confiança alta); CREs e
               hospitais sem AP no nome vêm de `dados/pcrj_orgao_ap.csv`, com a fonte de cada linha.
               Também vale a regional citada no OBJETO ("E/8ª CRE", "CAP 5.1"), com confiança média.
  2. unidade   o objeto cita escola/creche municipal de bairro conhecido
               (`data/tse_cache/escolas_capital_bairro_oficial.csv` → bairro oficial → AP).
  3. endereço  CEP → bairro: SEM BASE LOCAL de CEP por bairro — método INDISPONÍVEL nesta versão.
  4. texto     bairro carioca oficial no objeto (`dicionario.ler_bairros`) → RA → AP.
Bairros de APs diferentes → `multi=1` (balde), sem dividir valor. Sem AP → "cidade inteira / sem AP".
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path

from compliance_agent.territorio import base
from compliance_agent.territorio.dicionario import ler_bairros
from compliance_agent.territorio.atribui_estado import natureza_corporativa
from compliance_agent.territorio.geo import bairros, norm

FONTE = "Contas Rio — contratos da Prefeitura do Rio (pago = total declarado no portal)"
_DADOS = Path(__file__).resolve().parent / "dados"
FORCA = {"orgao": 5, "orgao_objeto": 4, "unidade": 3, "texto": 1}
_RE_AP_UG = re.compile(r"\bDA AP (\d)\b")
_RE_CRE_OBJ = re.compile(r"\b(\d{1,2})A CRE\b")
_RE_CAP_OBJ = re.compile(r"\b(?:CAP|AP) ?([1-5])(?: ?[0-7])?\b")      # "AP 5.3", "AP5", "CAP 3.1" (apartamento "AP 101" não casa)
_RE_ESC = re.compile(r"^(ESCOLA MUNICIPAL|E M|EM|CRECHE MUNICIPAL|EDI|ESPACO DE DESENVOLVIMENTO INFANTIL|CIEP)\b ?(.*)$")
_GATILHO = re.compile(r"\b(ESCOLA MUNICIPAL|E M|CRECHE MUNICIPAL|EDI|ESPACO DE DESENVOLVIMENTO INFANTIL|CIEP)\b")


def orgaos_regionais() -> list[tuple[re.Pattern, int, str, str]]:
    with open(_DADOS / "pcrj_orgao_ap.csv", encoding="utf-8") as f:
        return [(re.compile(rf"\b{re.escape(r['padrao'])}\b"), int(r["ap"]), r["confianca"], r["fonte"]) for r in csv.DictReader(f)]


def cre_para_ap(regionais) -> dict[int, int]:
    out = {}
    for rg, ap, _c, _f in regionais:
        m = re.match(r"\\b(\d{1,2})A\\ COORDENADORIA", rg.pattern)
        if m:
            out[int(m.group(1))] = ap
    return out


def escolas_municipais(log=print) -> list[tuple[re.Pattern, int, str, str]]:
    """[(regex do nome, ap, bairro, nome)] — só nomes que caem em UMA AP."""
    p = base.DATA / "tse_cache" / "escolas_capital_bairro_oficial.csv"
    if not p.exists():
        log(f"[pcrj] {p.name} ausente — método `unidade` sem cadastro (INDISPONÍVEL)")
        return []
    achados: dict[str, set] = {}
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            m = _RE_ESC.match(norm(r.get("nome")))
            try:
                ap = int(float(r.get("ap_of") or 0))
            except ValueError:
                ap = 0
            if not m or not ap:
                continue
            tipo, resto = m.group(1), m.group(2).strip()
            if tipo == "CIEP":
                num = re.match(r"(?:BRIZOLAO )?(\d{2,3})\b", resto)
                chaves = {f"CIEP {num.group(1)}"} if num else set()
            elif len(resto) >= 8 and " " in resto:
                t = {"E M": "ESCOLA MUNICIPAL", "EM": "ESCOLA MUNICIPAL", "EDI": "ESPACO DE DESENVOLVIMENTO INFANTIL"}.get(tipo, tipo)
                chaves = {f"{t} {resto}"}
                if t == "ESCOLA MUNICIPAL":
                    chaves.add(f"E M {resto}")
                if t == "ESPACO DE DESENVOLVIMENTO INFANTIL":
                    chaves.add(f"EDI {resto}")
            else:
                chaves = set()
            for k in chaves:
                achados.setdefault(k, set()).add((ap, r.get("b_of") or ""))
    out = []
    for k, v in achados.items():
        aps = {a for a, _ in v}
        if len(aps) == 1:
            ap, bairro = next(iter(v))
            out.append((re.compile(rf"\b{re.escape(k)}\b"), ap, bairro, k))
    log(f"[pcrj] {len(out)} escolas/creches municipais com AP única no cadastro")
    return out


_GATILHO_SAUDE = re.compile(r"\b(CLINICA DA FAMILIA|CENTRO MUNICIPAL DE SAUDE|HOSPITAL|MATERNIDADE|UPA|CMS|CF|POLICLINICA|CER)\b")
_RE_RA = re.compile(r"\b([IVXL]{1,7}) ?R ?A\b")
_ROMANO = {"I": 1, "V": 5, "X": 10, "L": 50}
_ABR_CIDADE = re.compile(r"\b(?:NO AMBITO DO MUNICIPIO|EM TODO O MUNICIPIO|TODO O MUNICIPIO|REDE MUNICIPAL|DIVERSOS BAIRROS|VARIOS BAIRROS|"
                         r"DIVERSOS LOGRADOUROS|TODAS AS (?:AREAS DE PLANEJAMENTO|APS|UNIDADES)|UNIDADES (?:ESCOLARES|DE SAUDE) DA REDE|"
                         r"ALUNOS DA REDE|EM TODA A CIDADE|NA CIDADE DO RIO DE JANEIRO|PREDIOS ESCOLARES|UNIDADES ESCOLARES|COMPLEXO REGULADOR|"
                         r"LOGRADOUROS PUBLICOS DO MUNICIPIO|SERVIDOR(?:ES)? (?:PUBLICOS? )?DO MUNICIPIO)\b")
_ORGAO_MEIO_PCRJ = re.compile(r"PROCURADORIA|FAZENDA|CONTROLADORIA|CASA CIVIL|IPLANRIO|EMPRESA MUNICIPAL DE INFORMATICA|PREVIDENCIA|"
                              r"GABINETE DO PREFEITO|PLANEJAMENTO|ARTES GRAFICAS|MULTIRIO")


def _romano(s: str) -> int:
    tot = 0
    for a, b in zip(s, s[1:] + " "):
        v = _ROMANO[a]
        tot += -v if b != " " and _ROMANO[b] > v else v
    return tot


def ra_para_ap() -> dict[int, int]:
    return {int(b["codra"]): int(b["ap"]) for b in bairros()}


def unidades_saude() -> list[tuple[str, int]]:
    """[(nome normalizado, AP)] das unidades municipais de saúde do Rio com AP conhecida (CNES).
    A SMS grava a AP no próprio nome da unidade no CNES ("… AP 51"); "CF"/"CMS" entram por extenso e abreviados."""
    out = []
    with open(_DADOS / "cnes_unidades.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["cod_ibge"] != "3304557" or not r["ap"] or len(r["nome_norm"].split()) < 3:
                continue
            n, ap = r["nome_norm"], int(r["ap"])
            out.append((n, ap))
            if n.startswith("CLINICA DA FAMILIA "):
                out.append(("CF " + n[19:], ap))
            if n.startswith("CENTRO MUNICIPAL DE SAUDE "):
                out.append(("CMS " + n[26:], ap))
    return sorted(set(out), key=lambda x: -len(x[0]))


def abrangencia_cidade(objeto: str | None, orgao: str | None) -> str | None:
    """Motivo pelo qual o contrato é da cidade inteira / da sede — ou None ("sem AP identificada")."""
    o = norm(objeto)
    m = _ABR_CIDADE.search(o)
    if m:
        return f"Cidade inteira — objeto de âmbito municipal: “{m.group(0).lower()}”"
    nat = natureza_corporativa(o)
    if nat:
        return f"Cidade inteira / sede — {nat}"
    if _ORGAO_MEIO_PCRJ.search(norm(orgao)):
        return f"sede — órgão-meio sem atividade territorial ({(orgao or '').strip()})"
    return None


def atribuir(objeto: str | None, ug: str | None, regionais, cres, escolas, saude=(), ras=None, orgao: str | None = None) -> dict:
    """Aplica os métodos e decide. Função PURA (é a que os testes exercitam)."""
    metodos: list[dict] = []
    # projeto da Lei de Incentivo à Cultura: depois de "C.I." vem o nome do PATROCINADOR ("C.I. Hospitais
    # Integrados da Gávea") — não é lugar. A auditoria da fase 7b pegou esse falso bairro; o trecho sai.
    if objeto and "INCENTIVO" in objeto.upper():
        objeto = re.sub(r"\bC\.\s?I\.\s.*$", "", objeto, flags=re.S)
    u, o = norm(ug), norm(objeto)
    m = _RE_AP_UG.search(u)
    if m and 1 <= int(m.group(1)) <= 5:
        metodos.append({"metodo": "orgao", "aps": [int(m.group(1))], "confianca": "alta", "evidencia": f"UG regional: {ug}"})
    else:
        for rg, ap, conf, fonte in regionais:
            if rg.search(u):
                metodos.append({"metodo": "orgao", "aps": [ap], "confianca": conf, "evidencia": f"UG: {ug} — {fonte}"})
                break
    aps_obj, evid = [], []
    for mm in _RE_CRE_OBJ.finditer(o):
        ap = cres.get(int(mm.group(1)))
        if ap and ap not in aps_obj:
            aps_obj.append(ap)
            evid.append(mm.group(0))
    for mm in _RE_CAP_OBJ.finditer(o):
        ap = int(mm.group(1))
        if 1 <= ap <= 5 and ap not in aps_obj:
            aps_obj.append(ap)
            evid.append(mm.group(0))
    for mm in _RE_RA.finditer(o):                        # "XIX R.A." → região administrativa → AP
        ap = (ras or {}).get(_romano(mm.group(1)))
        if ap and ap not in aps_obj:
            aps_obj.append(ap)
            evid.append(mm.group(0))
    if aps_obj:
        metodos.append({"metodo": "orgao_objeto", "aps": aps_obj, "confianca": "media", "evidencia": "regional citada no objeto: " + ", ".join(evid[:4])})
    bairro = None
    if escolas and _GATILHO.search(o):
        aps, ev = [], []
        for rg, ap, b, nome in escolas:
            if rg.search(o):
                if ap not in aps:
                    aps.append(ap)
                ev.append(nome)
                bairro = bairro or b
        if aps:
            metodos.append({"metodo": "unidade", "aps": aps, "confianca": "alta", "evidencia": "unidade citada: " + "; ".join(ev[:3])})
    if saude and _GATILHO_SAUDE.search(o):
        aps, ev, alvo = [], [], f" {o} "
        for nome, ap in saude:
            if f" {nome} " in alvo:
                if ap not in aps:
                    aps.append(ap)
                ev.append(nome + " (CNES)")
                alvo = alvo.replace(f" {nome} ", " # ")
        if aps:
            un = next((x for x in metodos if x["metodo"] == "unidade"), None)
            if un:
                un["aps"] += [a for a in aps if a not in un["aps"]]
                un["evidencia"] += "; " + "; ".join(ev[:3])
            else:
                metodos.append({"metodo": "unidade", "aps": aps, "confianca": "alta", "evidencia": "unidade citada: " + "; ".join(ev[:3])})
    bs = ler_bairros(objeto)
    if bs:
        aps = []
        for b in bs:
            if b["ap"] not in aps:
                aps.append(b["ap"])
        metodos.append({"metodo": "texto", "aps": aps, "confianca": "media", "evidencia": "; ".join(b["evidencia"] for b in bs[:4]),
                        "bairro": bs[0]["bairro"] if len(bs) == 1 else None, "ra": bs[0]["ra"] if len(bs) == 1 else None})
    metodos.sort(key=lambda x: -FORCA[x["metodo"]])
    out = {"ap": None, "ra": None, "bairro": None, "multi": 0, "aps": [], "metodo": None, "confianca": None, "evidencia": None,
           "metodos": metodos, "abrangencia": None}
    if not metodos:
        ab = abrangencia_cidade(objeto, orgao or ug)
        if ab:
            out.update(abrangencia="cidade_inteira", evidencia=ab)
        return out
    v = metodos[0]
    out.update(metodo="orgao" if v["metodo"] == "orgao_objeto" else v["metodo"], confianca=v["confianca"], evidencia=v["evidencia"],
               aps=v["aps"])
    if len(v["aps"]) == 1:
        out["ap"] = v["aps"][0]
        tx = next((x for x in metodos if x["metodo"] == "texto" and x["aps"] == v["aps"]), None)
        out["bairro"] = (tx or {}).get("bairro") or (bairro if v["metodo"] == "unidade" else None)
        out["ra"] = (tx or {}).get("ra")
    else:
        out["multi"] = 1
    return out


def _iso(d: str | None) -> str | None:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def rodar(incremental: bool = False, log=print) -> dict:
    hoje = date.today().isoformat()
    src = base.fonte_ro("pcrj.db")
    regionais = orgaos_regionais()
    cres, escolas = cre_para_ap(regionais), escolas_municipais(log)
    saude, ras = unidades_saude(), ra_para_ap()
    log(f"[pcrj] {len(saude)} nomes de unidades municipais de saúde com AP (CNES)")
    db = base.abrir(escrita=True)
    ja = {r[0]: r[1] for r in db.execute("SELECT contrato_id, assinatura FROM territorio_contrato_pcrj")} if incremental else {}
    agora, n, n_grav, vivos = base.agora(), 0, 0, set()
    for r in src.execute("SELECT contrato, favorecido_doc, favorecido_nome, orgao, ug, objeto, situacao, vigencia_ini, vigencia_fim, "
                         "valor_atualizado, total_pago FROM contasrio_contrato"):
        n += 1
        cid = str(r["contrato"])
        vivos.add(cid)
        ini, fim = _iso(r["vigencia_ini"]), _iso(r["vigencia_fim"])
        sit = (r["situacao"] or "").lower()
        status = "executado" if (sit.startswith("encerr") or sit.startswith("vencid") or (fim and fim < hoje)) else "em_execucao"
        pago = r["total_pago"]
        ass = hashlib.sha1(json.dumps([r["objeto"], r["ug"], r["valor_atualizado"], fim, status, pago, "7b"], ensure_ascii=False,
                                      default=str).encode()).hexdigest()
        if incremental and ja.get(cid) == ass:
            continue
        at = atribuir(r["objeto"], r["ug"], regionais, cres, escolas, saude, ras, r["orgao"])
        db.execute("INSERT OR REPLACE INTO territorio_contrato_pcrj(contrato_id,fonte,orgao,ug,fornecedor_cnpj,fornecedor_nome,objeto,valor,"
                   "vig_ini,vig_fim,status,pago,ap,ra,bairro,multi,aps_json,metodo,confianca,evidencia,metodos_json,assinatura,atualizado_em,abrangencia) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (cid, FONTE, re.sub(r"^\d+ - ", "", r["orgao"] or ""), re.sub(r"^\d+ - ", "", r["ug"] or ""),
                    re.sub(r"\D", "", r["favorecido_doc"] or ""), r["favorecido_nome"], r["objeto"], r["valor_atualizado"], ini, fim,
                    status, pago, at["ap"], at["ra"], at["bairro"], at["multi"], json.dumps(at["aps"]), at["metodo"], at["confianca"],
                    at["evidencia"], json.dumps(at["metodos"], ensure_ascii=False), ass, agora, at["abrangencia"]))
        n_grav += 1
    src.close()
    if not incremental:
        mortos = [x[0] for x in db.execute("SELECT contrato_id FROM territorio_contrato_pcrj") if x[0] not in vivos]
        db.executemany("DELETE FROM territorio_contrato_pcrj WHERE contrato_id=?", [(m,) for m in mortos])
    base.por_meta(db, "pcrj_rodado_em", agora)
    db.commit()
    db.close()
    log(f"[pcrj] {n} contratos lidos do Contas Rio; {n_grav} gravados em territorio.db")
    return {"contratos": n, "gravados": n_grav}
