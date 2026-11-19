# -*- coding: utf-8 -*-
"""PAGO de um processo SEI = OB do SIAFE ligada por CAMADAS, cada OB com a sua proveniência (`via`).

Por que existe (18/11/2026): 4 agentes de perícia, na leitura integral de 40 processos, acharam a soma por
`ob_orcamentaria_siafe.processo` SUBCONTANDO e DUPLICANDO:
  · OB com `processo` vazio (2021–2023) ou gravada no processo-mãe / de outra unidade (Caxias no de Bangu);
  · grafia variante ("210108/000153/2023", "SEI-…/23") — Seleta: a regra exata dava 31 OB/R$ 35.581.392,67,
    o certo é 35 OB/R$ 39.340.668,31;
  · OB devolvida e reemitida (Lar São Francisco: 2026OB16652 devolvida pela 2026GD00778, reemitida como
    2026OB16931 — a soma dava R$ 8.756.528,30 em vez de R$ 4.378.264,15);
  · regularização de OB devolvida (SES × OPAS 2022: OB de R$ 56,8 mi com GD + duas OB de regularização).

Camadas (todas DENTRO de `cruzamentos_intel._ob_paga` — OB não paga nunca entra):
  processo_exato        `processo` = "SEI-XXXXXX/XXXXXX/AAAA" literal
  processo_normalizado  mesma chave por `lex_execucao._chave_processo` (sem "SEI-", ano com 2 dígitos, espaços)
  ob_dos_autos          espelho da OB juntado nos autos — nº + UG + credor + VALOR iguais
  pd_dos_autos          PD juntada nos autos (espelho ou título) — nº + UG + credor (+ valor, se o espelho o traz)
  nl_dos_autos          NL juntada/citada nos autos — UG + credor e soma ≤ valor da NL (espelho ou `nl_siafe`);
                        só puxa OB com `processo` VAZIO: NL citada como referência histórica não traz OB alheia.
OB que o SIAFE OU o espelho juntado atribuem a OUTRO processo não é somada aqui: vai para `candidatas` com o
motivo (Caxias × Bangu: SIAFE e espelho dizem Bangu — atribuição a decidir por quem lê, não por regra). Devolução: Guia de Devolução da base (`gd_siafe`) ou dos autos (espelho da GD) desconta
pela regra canônica `pericia_contabil.valor_efetivo_ob`; GD marcada na OB sem valor conhecido → fora da soma,
marcada, e o total vira PISO. OB que só existe no PDF dos autos vai em `nos_autos_fora_da_base`, nunca na soma.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

VIAS = ("processo_exato", "processo_normalizado", "ob_dos_autos", "pd_dos_autos", "nl_dos_autos")
_TOL = 0.01
_PREFILTRO_MAX = 50           # até aqui, um LIKE por processo no SQL; acima, varredura única de toda OB com processo

_RE_DOC = re.compile(r"\b(20\d{2})\s*(NL|PD|OB|GD)\s*0*(\d{1,5})\b", re.I)
_RE_MOEDA = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})*,\d{2})(?![\d,])")
_RE_UG = re.compile(r"^\s*(\d{6})\s*-\s", re.M)
_RE_CREDOR = re.compile(r"(?:Credor|Favorecido)\s*\n(?:.*\n){0,2}?\s*(\d{14}|\d{11})\s*-", re.I)
_RE_PROC = re.compile(r"Processo\s*\n\s*(\S+)", re.I)
_CAB = (("GD", re.compile(r"^\s*Guia\s+(?:de\s+)?Devolu", re.I | re.M)),
        ("NL", re.compile(r"^\s*Nota\s+de\s+Liquida", re.I | re.M)),
        ("PD", re.compile(r"^\s*Programa\S*\s+de\s+Desembolso", re.I | re.M)),
        ("OB", re.compile(r"^\s*(?:Rela\S+\s+de\s+)?Orde(?:m|ns)\s+Banc\S+", re.I | re.M)))
_RE_TITULO_DESPESA = re.compile(r"(?i)liquida|desembolso|ordem|ordens|devolu|\b(?:NL|PD|OB|GD)\b|pagamento")
_TETO_LEITURA = 8000          # espelho cabe em ~3 mil caracteres; despacho de liquidação cita a NL no início


def chave_processo(p: str | None) -> str | None:
    from tools.lex_execucao import _chave_processo
    return _chave_processo(p)


def _chave_tolerante(p: str | None, pedidos) -> str | None:
    """Grafias do SIAFE que `chave_processo` não lê (19/11/2026: R$ 468,96 mi em OB pagas): 'SEI-80001/001096/2025'
    (zero da unidade caído — a posição varia: '03001' é 030001), 'SEI02/0004/000108/2025' (unidade partida) e
    'SEI-080001002471/2024' (sem barra). Só devolve chave de processo PEDIDO, e só se a candidata for única."""
    s = re.sub(r"\s", "", (p or "").upper())
    m = re.search(r"(?<!\d)(\d{6})(\d{6})/(\d{4})(?!\d)", s)
    if m:
        k = f"{m[1]}/{int(m[2])}/{m[3]}"
        return k if k in pedidos else None
    m = re.search(r"(?<!\d)(\d{2})/(\d{4})/0*(\d+)/(\d{4})(?!\d)", s)
    if m:
        k = f"{m[1]}{m[2]}/{int(m[3])}/{m[4]}"
        return k if k in pedidos else None
    m = re.search(r"(?<!\d)(\d{5})/0*(\d+)/(\d{4})(?!\d)", s)
    if m:
        u = m[1]
        cands = {f"{u[:i]}0{u[i:]}/{int(m[2])}/{m[3]}" for i in range(6)} & set(pedidos)
        return cands.pop() if len(cands) == 1 else None
    return None


def _canonico(chave: str) -> str:
    a, b, ano = chave.split("/")
    return f"SEI-{a}/{int(b):06d}/{ano}"


def _doc(ano: str, tipo: str, n: str) -> str:
    return f"{ano}{tipo.upper()}{int(n):05d}"


def _brl(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _dig(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


# ── autos ────────────────────────────────────────────────────────────────────────────────────────────────
def espelho(texto: str) -> dict | None:
    """Espelho do SIAFE-Rio (NL/PD/OB/GD) em texto → {tipo, numero, ug, valor, credor, nl, pd, ob, processo}.
    Só reconhece o LAYOUT do espelho (cabeçalho logo após "Governo do Estado do Rio de Janeiro"); citação solta em
    despacho não é espelho."""
    m = re.search(r"Governo do Estado do Rio de Janeiro\s*\n", texto)
    if not m:
        return None
    corpo = texto[m.end():]
    cab = corpo[:120]
    tipo = next((t for t, rx in _CAB if rx.match(cab)), None)
    if not tipo:
        return None
    nums = [_doc(*x.groups()) for x in _RE_DOC.finditer(corpo[:1500]) if x.group(2).upper() == tipo]
    if not nums:
        return None
    e = {"tipo": tipo, "numero": nums[0]}
    if (u := _RE_UG.search(corpo)):
        e["ug"] = u.group(1)
    if (v := _RE_MOEDA.search(corpo)):
        e["valor"] = _brl(v.group(1))
    if (c := _RE_CREDOR.search(corpo)):
        e["credor"] = c.group(1)
    for rot, t in (("Nota\\s+Liquida\\S*", "nl"), ("Ordem\\s+Banc\\S*", "ob"),
                   ("Programa\\S*\\s+de\\s+Desembolso\\s*\\n\\s*Documento", "pd")):
        r = re.search(rot + r"\s*\n\s*(20\d{2})\s*(NL|PD|OB)\s*0*(\d{1,5})\b", corpo, re.I)
        if r and r.group(2).upper() == t.upper():
            e[t] = _doc(*r.groups())
    if (p := _RE_PROC.search(corpo)):
        e["processo"] = p.group(1).strip()
    return e


def refs_dos_autos(man: dict) -> dict:
    """O que os autos dizem do pagamento: espelhos (NL/PD/OB/GD) e NL citadas em texto de liquidação."""
    pasta = Path(man["_pasta"])
    out = {"espelhos": [], "titulos": [], "nl_texto": set()}
    for d in man.get("docs") or []:
        titulo = str(d.get("titulo") or "")
        if not (_RE_TITULO_DESPESA.search(titulo) or d.get("tipo") in
                ("nota_liquidacao", "liquidacao", "programacao_desembolso", "ordem_bancaria")):
            continue
        for x in _RE_DOC.finditer(titulo):
            out["titulos"].append({"tipo": x.group(2).upper(), "numero": _doc(*x.groups()), "doc": titulo})
        rel = d.get("texto")
        if not rel:
            continue
        try:
            with open(pasta / rel, encoding="utf-8", errors="ignore") as f:
                texto = f.read(_TETO_LEITURA)
        except OSError:
            continue
        e = espelho(texto)
        if e:
            e["doc"] = re.sub(r"\s*\(\d+\)\s*$", "", titulo)
            out["espelhos"].append(e)
        elif re.search(r"(?i)liquida", titulo):
            out["nl_texto"] |= {_doc(*x.groups()) for x in _RE_DOC.finditer(texto) if x.group(2).upper() == "NL"}
    return out


def _carregar_autos(numero: str) -> dict | None:
    from compliance_agent.sei import manifesto_norm
    return manifesto_norm.carregar(numero)


# ── base ─────────────────────────────────────────────────────────────────────────────────────────────────
_CAMPOS = ("numero_ob", "ug_emitente", "ug_liquidante", "data_emissao", "status_envio", "nl", "pd", "gd", "credor",
           "processo", "tipo_regularizacao", "valor")


def _select(con) -> str:
    cols = {r[1] for r in con.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}
    return ", ".join(c if c in cols else f"'' AS {c}" for c in _CAMPOS)


def _linha(r) -> dict:
    d = dict(zip(_CAMPOS, r))
    d["valor"] = float(d["valor"] or 0)
    for k in _CAMPOS[:-1]:
        d[k] = str(d[k] or "").strip()
    return d


def _gds(con) -> dict[tuple[str, str], dict[str, float]]:
    """{(ob, ug): {nº GD: valor}} das guias válidas de `gd_siafe` (anulada/estornada não vale)."""
    from compliance_agent.siafe_gd import _RE_NAO_VALE
    try:
        rows = con.execute("SELECT numero, ug_emitente, ob, status, valor FROM gd_siafe "
                           "WHERE ob IS NOT NULL AND ob<>''").fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict = {}
    for numero, ug, ob, status, valor in rows:
        if valor is None or _RE_NAO_VALE.search(status or ""):
            continue
        out.setdefault((str(ob).strip(), str(ug).strip()), {})[str(numero).strip()] = float(valor)
    return out


def _valor_nl(con, nl: str, ug: str, espelhos: list[dict]) -> float | None:
    vs = [e["valor"] for e in espelhos if e["tipo"] == "NL" and e["numero"] == nl and e.get("ug") == ug
          and e.get("valor") is not None]
    if vs:
        return max(vs)                                   # NL com reforço: o espelho maior é o valor vigente
    try:
        r = con.execute("SELECT max(valor) FROM nl_siafe WHERE numero=? AND ug_emitente=?", (nl, ug)).fetchone()
    except sqlite3.OperationalError:
        return None
    return float(r[0]) if r and r[0] is not None else None


# ── núcleo ───────────────────────────────────────────────────────────────────────────────────────────────
def obs_por_processo(con: sqlite3.Connection, processos: list[str], *, autos: bool = True,
                     so_pagos: bool = False) -> dict[str, dict]:
    """{chave_processo: {n, total, datas, obs, por_via, descartadas, candidatas, nos_autos_fora_da_base, piso}}.
    `total` = soma de `valor_efetivo` (OB paga menos o devolvido). Uma varredura da tabela por lote; a camada dos
    autos só roda para processo com pasta no acervo (`data/sei_arquivo`). `so_pagos`: só devolve processo com OB
    paga (contrato antigo de `mapa_obs_siafe`: chave presente ⇔ há pagamento); sem ele, vem também o processo que
    só tem candidata, descartada ou OB dos autos fora da base."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    numeros = {}
    for p in processos:
        k = chave_processo(p)
        if k:
            numeros.setdefault(k, p)
    out: dict[str, dict] = {}
    if not numeros:
        return out
    try:
        sel = _select(con)
        paga = _ob_paga(con)
        # poucos processos (ficha, dossiê): pré-filtro no SQL — superconjunto da regex de `chave_processo` (unidade,
        # "/", nº sem zeros, "/"); a chave é reconferida abaixo. Sem ele, cada ficha trazia ~1,3 mi linhas ao Python.
        pre, args = "processo LIKE '%/%'", []
        if len(numeros) <= _PREFILTRO_MAX:
            pre = "(" + " OR ".join("processo LIKE ?" for _ in numeros) + ")"
            args = [f"%{k.split('/')[0]}%/%{k.split('/')[1]}%/%" for k in numeros]
            # grafias irregulares (`_chave_tolerante`): o nº/ano sempre aparece inteiro
            pre = pre[:-1] + "".join(" OR processo LIKE ?" for _ in numeros) + ")"
            args += [f"%{k.split('/')[1]}/{k.split('/')[2]}%" for k in numeros]
        rows = con.execute(f"SELECT {sel} FROM ob_orcamentaria_siafe WHERE {paga} AND {pre}", args).fetchall()
    except sqlite3.OperationalError:
        return out                                       # base sem SIAFE: quem chama diz INDISPONÍVEL
    achadas: dict[str, dict[tuple, dict]] = {k: {} for k in numeros}
    for i, r in enumerate(rows):
        o = _linha(r)
        k = chave_processo(o["processo"]) or _chave_tolerante(o["processo"], achadas)
        if k in achadas:
            exato = o["processo"].upper() == _canonico(k)
            # base sem nº de OB (fixture antiga): cada linha é uma OB — a chave não pode colapsá-las
            achadas[k][(o["numero_ob"] or f"#{i}", o["ug_emitente"])] = {**o, "via": "processo_exato" if exato
                                                              else "processo_normalizado"}
    gds = _gds(con)
    for k, numero in numeros.items():
        extra = {"descartadas": [], "candidatas": [], "nos_autos_fora_da_base": []}
        gd_autos: dict[tuple, dict[str, float]] = {}
        if autos:
            man = _carregar_autos(numero)
            if man is not None:
                _camada_autos(con, k, achadas[k], refs_dos_autos(man), extra, gd_autos, sel, paga)
        res = _consolidar(achadas[k], gds, gd_autos)
        res.update(extra)
        if res["n"] if so_pagos else (res["obs"] or any(extra.values())):
            out[k] = res
    return out


def _camada_autos(con, k: str, achadas: dict, refs: dict, extra: dict, gd_autos: dict, sel: str, paga: str):
    esp = refs["espelhos"]
    ugs = {e["ug"] for e in esp if e.get("ug")} | {o["ug_emitente"] for o in achadas.values()}
    credores = {e["credor"] for e in esp if e.get("credor")} | {o["credor"] for o in achadas.values() if o["credor"]}
    for e in esp:                                            # GD juntada: devolução que a base pode não ter
        if e["tipo"] == "GD" and e.get("ob") and e.get("ug") and e.get("valor") is not None:
            gd_autos.setdefault((e["ob"], e["ug"]), {})[e["numero"]] = e["valor"]
    if not credores or not ugs:
        return
    q, qu = ",".join("?" * len(credores)), ",".join("?" * len(ugs))
    # UG no SQL: o credor de retenção (Receita, INSS) citado no espelho de IRRF tem OB em todas as UGs do Estado
    cands = [_linha(r) for r in con.execute(
        f"SELECT {sel} FROM ob_orcamentaria_siafe WHERE {paga} AND credor IN ({q}) AND ug_emitente IN ({qu})",
        sorted(credores) + sorted(ugs))]
    cands = [o for o in cands if (o["ug_emitente"] in ugs or o["ug_liquidante"] in ugs)
             and (o["numero_ob"], o["ug_emitente"]) not in achadas]

    def _outro_processo(o):
        ck = chave_processo(o["processo"])
        return ck is not None and ck != k

    def _atribuida_a_outro(o, e) -> str:
        """SIAFE ou o próprio espelho dizem OUTRO processo: juntada aqui não basta para somar aqui (Seleta: o
        espelho da 2023OB00365 diz SEI-210108/000339/21, o contrato anterior). Vai para `candidatas`."""
        if _outro_processo(o):
            return f"registrada no SIAFE no processo {o['processo']}"
        ce = chave_processo(e.get("processo"))
        if ce is not None and ce != k:
            return f"o espelho juntado aponta o processo {e['processo']}"
        return ""

    def _entra(o, via, nota=""):
        achadas[(o["numero_ob"], o["ug_emitente"])] = {**o, "via": via, "processo_siafe": o["processo"],
                                                        **({"nota_via": nota} if nota else {})}

    def _cand(o, motivo):
        extra["candidatas"].append({"numero_ob": o["numero_ob"], "ug": o["ug_emitente"], "valor": o["valor"],
                                    "nl": o["nl"], "pd": o["pd"], "motivo": motivo})

    # 1) espelho da OB: nº + UG + credor + valor
    esp_ob = {(e["numero"], e.get("ug")): e for e in esp if e["tipo"] == "OB"}
    restantes = []
    for o in cands:
        e = esp_ob.get((o["numero_ob"], o["ug_emitente"]))
        if e is None:
            restantes.append(o)
        elif e.get("credor") and e["credor"] != o["credor"]:
            _cand(o, "credor do espelho da OB diverge")
        elif e.get("valor") is None or abs(e["valor"] - o["valor"]) > _TOL:
            _cand(o, f"valor do espelho da OB ({e.get('valor')}) diverge do SIAFE ({o['valor']})")
        elif (outro := _atribuida_a_outro(o, e)):
            _cand(o, outro)
        else:
            _entra(o, "ob_dos_autos", e.get("doc", ""))
    # 2) PD juntada (espelho ou título): nº + UG + credor (+ valor do espelho)
    esp_pd = {(e["numero"], e.get("ug")): e for e in esp if e["tipo"] == "PD"}
    pd_titulo = {t["numero"] for t in refs["titulos"] if t["tipo"] == "PD"}
    cands, restantes = restantes, []
    for o in cands:
        e = esp_pd.get((o["pd"], o["ug_emitente"])) or esp_pd.get((o["pd"], o["ug_liquidante"]))
        if o["pd"] and e is not None:
            if e.get("credor") and e["credor"] != o["credor"]:
                _cand(o, "credor do espelho da PD diverge")
            elif e.get("valor") is not None and abs(e["valor"] - o["valor"]) > _TOL:
                _cand(o, f"valor do espelho da PD ({e['valor']}) diverge do SIAFE ({o['valor']})")
            elif (outro := _atribuida_a_outro(o, e)):
                _cand(o, outro)
            else:
                _entra(o, "pd_dos_autos", e.get("doc", ""))
        elif o["pd"] and o["pd"] in pd_titulo and not _outro_processo(o):
            _entra(o, "pd_dos_autos", "PD no título de documento dos autos")
        else:
            restantes.append(o)
    # 3) NL juntada/citada: só OB SEM processo, e a soma por NL não passa do valor da NL
    nls = {e["numero"] for e in esp if e["tipo"] == "NL"} | {e["nl"] for e in esp if e.get("nl")} \
        | {t["numero"] for t in refs["titulos"] if t["tipo"] == "NL"} | refs["nl_texto"]
    por_nl: dict[tuple, list] = {}
    for o in restantes:
        if not o["nl"] or o["nl"] not in nls:
            continue
        if _outro_processo(o):
            continue                                     # NL citada não puxa OB gravada noutro processo
        por_nl.setdefault((o["nl"], o["ug_emitente"]), []).append(o)
    for (nl, ug), lista in por_nl.items():
        teto = _valor_nl(con, nl, ug, esp)
        ja = sum(x["valor"] for x in achadas.values() if x["nl"] == nl and x["ug_emitente"] == ug)
        if teto is None:
            for o in lista:
                _cand(o, "valor da NL desconhecido: não há como conferir a coerência")
        elif ja + sum(o["valor"] for o in lista) > teto + _TOL:
            for o in lista:
                _cand(o, f"valor incoerente: OB da NL somariam mais que a NL ({teto:.2f})")
        else:
            for o in lista:
                _entra(o, "nl_dos_autos")
    # OB citada nos autos: não paga no SIAFE → descartada; ausente da base → à parte, nunca somada
    citadas = {(e["numero"], e.get("ug")): e for e in esp if e["tipo"] == "OB" and e.get("ug")}
    faltam = [c for c in citadas if c not in achadas and not any(
        x["numero_ob"] == c[0] and x["ug"] == c[1] for x in extra["candidatas"])]
    if faltam:
        q = ",".join("?" * len(faltam))
        # ob-qualquer-status: aqui se pergunta se a OB EXISTE na base, não se soma nada
        vistas = {(r[0], r[1]): r[2] for r in con.execute(
            f"SELECT numero_ob, ug_emitente, status FROM ob_orcamentaria_siafe WHERE numero_ob IN ({q})",
            [c[0] for c in faltam])}
        for c in faltam:
            e = citadas[c]
            if c in vistas:
                extra["descartadas"].append({"numero_ob": c[0], "ug": c[1], "valor": e.get("valor"),
                                             "motivo": "nao_paga_no_siafe", "status": vistas[c]})
            else:
                extra["nos_autos_fora_da_base"].append({"numero_ob": c[0], "ug": c[1], "valor": e.get("valor"),
                                                        "doc": e.get("doc", "")})


def _consolidar(achadas: dict, gds: dict, gd_autos: dict) -> dict:
    from compliance_agent.pericia_contabil import situacao_devolucao, valor_efetivo_ob, _RE_GD
    obs, piso = [], False
    for (ob, ug), o in achadas.items():
        guias = {**gds.get((ob, ug), {}), **gd_autos.get((ob, ug), {})}
        marcadas = set(_RE_GD.findall(o["gd"]))
        sit = situacao_devolucao(o["gd"], o["status_envio"])
        devolvido = None
        if guias and marcadas <= set(guias):
            devolvido = round(sum(guias.values()), 2)    # toda guia marcada na OB tem valor conhecido
        efetivo, marca = valor_efetivo_ob(o["valor"], sit, devolvido=devolvido)
        piso |= marca == "devolvida_sem_valor"
        nota = (f"devolvida: {', '.join(sorted(guias))} (R$ {devolvido:.2f})" if devolvido is not None
                else f"GD {', '.join(sorted(marcadas))} sem valor conhecido — fora da soma" if marca else "")
        obs.append({"numero_ob": ob, "ug": ug, "data": o["data_emissao"], "valor": o["valor"],
                    "valor_efetivo": efetivo, "marca": marca, "credor": o["credor"], "nl": o["nl"], "pd": o["pd"],
                    "via": o["via"], "processo_siafe": o.get("processo_siafe", o["processo"]),
                    "tipo_regularizacao": o["tipo_regularizacao"], "nota": nota})
    obs.sort(key=lambda x: (x["data"][6:10] + x["data"][3:5] + x["data"][0:2], x["numero_ob"]))
    por_via: dict[str, float] = {}
    for x in obs:
        por_via[x["via"]] = round(por_via.get(x["via"], 0.0) + x["valor_efetivo"], 2)
    contadas = [x for x in obs if x["valor_efetivo"] > 0]
    return {"n": len(contadas), "total": round(sum(x["valor_efetivo"] for x in obs), 2),
            "datas": [x["data"] for x in contadas], "obs": obs, "por_via": por_via, "piso": piso}


def resumo_auditavel(d: dict) -> str:
    """Uma linha por via, para o bloco de prompt/parecer: de onde vem cada real somado."""
    partes = [f"{v}: R$ {t:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
              for v, t in sorted((d.get("por_via") or {}).items(), key=lambda kv: VIAS.index(kv[0]))]
    return json.dumps(partes, ensure_ascii=False) if partes else "[]"
