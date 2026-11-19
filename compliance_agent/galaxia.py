"""Galáxia dos casos — todos os casos que o sistema já tem, num só grafo, com as ligações reais.

Até a v63 eram só os dossiês do vault (92 casos). Desde a v64 entram:
  · ÓRGÃOS/UGs — centro de cada aglomerado (cluster). O fornecedor mora no aglomerado do órgão que
    mais o PAGOU (OB contabilizada no SIAFE = pagamento); sem OB no SIAFE, o órgão do contrato
    (PCRJ/PNCP) — e a aresta diz qual das duas coisas é;
  · FORNECEDORES com sinal do Radar (`radar_risco`, score 0–100, todos — não só os 100 do card) e
    os citados por alerta aberto ou por dossiê;
  · ALERTAS abertos (`alertas`, status ≠ descartado) agrupados no fornecedor ou no órgão a que se
    referem — alerta de pessoa (acúmulo, teto) vira CONTAGEM no órgão, nunca nó com nome/CPF;
  · DOSSIÊS do vault (`casos_vault.listar`) — as estrelas maiores, com halo;
  · SÓCIOS do QSA público (`socios_fornecedor`, só o nome) e processos SEI citados nos dossiês.

Arestas reais: órgão pagou/contratou, sócio em comum, processo SEI, dossiê cita CNPJ/órgão,
endereço compartilhado (grupos de risco do `hub_compartilhado`, co-endereço do alerta d12) e, desde
18/11/2026, as ligações de conluio de `ligacoes_conluio` entre fornecedores que já são nós: `contato`
(mesmo telefone/e-mail na Receita, fan-out medido), `socio_variante` (mesmo sócio grafado diferente,
mesmos dígitos visíveis do CPF) e `concorrentes_ligados` (mesmo certame + qualquer vínculo).
Ligação = indício de relação a conferir, nunca prova. Sem CPF/documento de pessoa na saída.

O layout (x, y) é calculado AQUI, uma vez por ciclo: aglomerado = órgão no centro, fornecedores em
filotaxia (maior score mais perto do centro), sócios em volta do fornecedor; aglomerados empacotados
numa espiral sem sobreposição. O JSON fica em `data/cache/galaxia.json` (gerado pela ronda) e a rota
só filtra a cópia em memória — responde em milissegundos.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from compliance_agent import cores_orgaos
from compliance_agent.cruzamentos_intel import _ob_paga
from compliance_agent.orgao_fonte import esfera_de

SOCIOS_POR_CNPJ = 4
ORGAOS_POR_CNPJ = 3
EXEMPLOS_ALERTA = 4
_SEM_QSA = "(sem QSA público)"
_REPO = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("JFN_DATA_DIR") or (_REPO / "data")) / "cache" / "galaxia.json"
AVISO = "Ligação = indício de relação a conferir, nunca prova."
CRITICO = 50                                   # score ≥ 50 = 🔴 no Radar (mesma régua)

# alerta → o que ele ancora. Pessoa nunca vira nó: só conta no órgão (ou fica "sem âncora").
_ROTULO_ALERTA = {
    "acumulacao": "acúmulo de cargos (servidor)", "enriquecimento": "remuneração acima do teto",
    "pcrj_d7_fracionamento": "fracionamento (PCRJ)", "emendas_d3_favorecido_sancionado": "emenda a sancionado",
    "pcrj_d10_rede_concorrentes": "rede societária entre concorrentes", "pcrj_d9_socio_na_folha": "sócio na folha",
    "direcionamento": "direcionamento / empresa nova", "emendas_d6_empenho_sem_pagamento": "emenda empenhada sem OB",
    "fracionamento": "fracionamento de OB", "emendas_d1_pix_impedida": "emenda PIX impedida",
    "pcrj_d12_coendereco_concorrentes": "co-endereço entre concorrentes", "emendas_d2_concentracao_autor": "concentração de emendas",
    "doerj_anomalia": "OB × publicação suspeita no DOERJ", "pcrj_d11_aditivo_estourado": "aditivo acima do limite",
    "emendas_d4_favorecido_fantasma": "sinais de fachada", "pcrj_d8_credor_recem_aberto": "credor recém-aberto",
}


def _dig(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s.upper())).strip()


def _h01(s: str) -> float:
    h = 2166136261
    for ch in s.encode():
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return (h % 100000) / 100000


def _q(con, sql, args=()):
    """Consulta tolerante: tabela ausente → [] (a fonte vira INDISPONÍVEL no resumo, nunca 0 silencioso)."""
    if con is None:
        raise sqlite3.OperationalError("sem base")
    return con.execute(sql, args).fetchall()


def _em_lotes(con, sql_fmt, chaves, lote=500):
    out = []
    for i in range(0, len(chaves), lote):
        parte = chaves[i:i + lote]
        out += _q(con, sql_fmt.format(",".join("?" * len(parte))), parte)
    return out


# ── coleta ───────────────────────────────────────────────────────────────────────────────────────

class _G:
    def __init__(self):
        self.forn: dict[str, dict] = {}
        self.org: dict[str, dict] = {}
        self.casos: list[dict] = []
        self.socio_de: dict[str, set] = defaultdict(set)        # nome → cnpjs
        self.arestas: dict[tuple, dict] = {}
        self.fontes: dict[str, str] = {}
        self.sem_ancora: Counter = Counter()
        self.n_alertas = 0
        self.end_grupos: dict[str, set] = defaultdict(set)      # cnpj → rótulos de endereço compartilhado
        self.conluio: dict = {}

    def f(self, cnpj, nome=""):
        d = self.forn.get(cnpj)
        if d is None:
            d = self.forn[cnpj] = {"cnpj": cnpj, "nome": "", "score": 0, "sinais": [], "al": Counter(),
                                   "ex": [], "org": Counter(), "org_via": {}, "casos": set()}
        if nome and not d["nome"]:
            d["nome"] = str(nome).strip()[:90]
        return d

    def o(self, chave, rotulo):
        d = self.org.get(chave)
        if d is None:
            d = self.org[chave] = {"chave": chave, "nome": str(rotulo or chave).strip()[:90], "al": Counter(),
                                   "ex": [], "casos": set()}
        return d

    def liga(self, a, b, tipo, peso=1.0, **extra):
        if a == b:
            return
        k = (a, b, tipo) if a < b else (b, a, tipo)
        e = self.arestas.get(k)
        if e:
            e["peso"] += peso
        else:
            self.arestas[k] = {"a": k[0], "b": k[1], "tipo": tipo, "peso": peso, **extra}


def _alertas(g: _G, con, nomes_ug: dict):
    try:
        rows = _q(con, "SELECT id, tipo, severidade, titulo, evidencias FROM alertas WHERE status != 'descartado'")
        g.fontes["alertas"] = "ok"
    except sqlite3.Error:
        g.fontes["alertas"] = "INDISPONÍVEL"
        return
    por_nome = {_norm(v): k for k, v in nomes_ug.items()}
    for aid, tipo, sev, tit, ev in rows:
        g.n_alertas += 1
        try:
            d = json.loads(ev or "{}")
        except ValueError:
            d = {}
        if not isinstance(d, dict):
            d = {}
        ex = {"id": aid, "tipo": tipo, "sev": (sev or "").replace("média", "media"), "titulo": (tit or "")[:140]}
        ancorou = False

        def no_forn(cnpj, nome=""):
            nonlocal ancorou
            c = _dig(cnpj)
            if len(c) != 14:
                return None
            f = g.f(c, nome)
            f["al"][tipo] += 1
            if len(f["ex"]) < EXEMPLOS_ALERTA:
                f["ex"].append(ex)
            ancorou = True
            return f

        def no_org(chave, rotulo, pessoal=False):
            nonlocal ancorou
            o = g.o(chave, rotulo)
            o["al"][tipo] += 1
            if not pessoal and len(o["ex"]) < EXEMPLOS_ALERTA:
                o["ex"].append(ex)
            ancorou = True
            return o

        def org_nome(nome):
            n = _norm(nome)
            ug = por_nome.get(n)
            return (f"ug:{ug}", nomes_ug[ug]) if ug else (f"nome:{n}", nome.strip())

        if tipo == "acumulacao":                                    # pessoa → só conta no órgão
            for nome in str(d.get("orgaos") or "").split(","):
                if nome.strip():
                    no_org(*org_nome(nome), pessoal=True)
        elif tipo == "pcrj_d7_fracionamento":
            f = no_forn(d.get("fornecedor"), (tit or "").split("—")[-1].split("×")[0].strip())
            oc = _dig(d.get("orgao"))
            if f and len(oc) == 14:
                rot = (tit or "").split("×")[-1].strip() or oc
                g.o(f"cnpj:{oc}", rot)
                f["org"][f"cnpj:{oc}"] += 1
                f["org_via"].setdefault(f"cnpj:{oc}", "contrato")
        elif tipo in ("emendas_d3_favorecido_sancionado",):
            no_forn(d.get("doc"), (tit or "").split("—")[-1].split("(")[0].strip())
        elif tipo in ("emendas_d4_favorecido_fantasma", "pcrj_d8_credor_recem_aberto"):
            no_forn(d.get("cnpj"), (tit or "").split("—")[-1].strip())
        elif tipo == "doerj_anomalia":
            no_forn(d.get("cpf_cnpj"), d.get("favorecido"))
        elif tipo == "direcionamento":
            f = no_forn(d.get("cnpj") or d.get("favorecido_cpf"), d.get("razao_social") or d.get("favorecido_nome"))
            for ug in str(d.get("ugs") or "").replace(";", ",").split(","):
                ug = _dig(ug)
                if f and len(ug) == 6:
                    f["org"][f"ug:{ug}"] += 1
                    f["org_via"].setdefault(f"ug:{ug}", "OB")
        elif tipo == "fracionamento":
            f = no_forn(d.get("favorecido_cpf"), d.get("favorecido_nome"))
            ug = _dig(d.get("ug_codigo"))
            if f and len(ug) == 6:
                f["org"][f"ug:{ug}"] += 1
                f["org_via"].setdefault(f"ug:{ug}", "OB")
        elif tipo == "pcrj_d9_socio_na_folha":
            f = no_forn(d.get("credor"))
            s = _norm(d.get("socio"))
            if f and s:
                g.socio_de[s].add(f["cnpj"])
        elif tipo == "pcrj_d10_rede_concorrentes":
            s = _norm(d.get("socio"))
            for c in d.get("fornecedores") or []:
                f = no_forn(c)
                if f and s:
                    g.socio_de[s].add(f["cnpj"])
        elif tipo == "pcrj_d12_coendereco_concorrentes":
            cs = [f["cnpj"] for f in (no_forn(c) for c in d.get("fornecedores") or []) if f]
            for c in cs:
                g.end_grupos[c].add(f"co-endereço entre concorrentes (alerta d12, CEP {d.get('cep', '')})")
            for a, b in combinations(sorted(set(cs)), 2):
                g.liga(f"cnpj:{a}", f"cnpj:{b}", "endereco", 1.0, det=f"mesmo CEP {d.get('cep', '')}")
        elif tipo == "pcrj_d11_aditivo_estourado":
            oc = _dig(str(d.get("controle") or "")[:18])[:14]
            if len(oc) == 14:
                no_org(f"cnpj:{oc}", oc)
        elif tipo == "emendas_d1_pix_impedida":
            c = _dig(d.get("cnpj"))
            if len(c) == 14:
                no_org(f"cnpj:{c}", (tit or "").split("—")[-1].split("(")[0].strip() or c)
        if not ancorou:
            g.sem_ancora[tipo] += 1


def _radar(g: _G, radar: dict | None):
    if not radar or not radar.get("ok"):
        g.fontes["radar"] = "INDISPONÍVEL"
        return
    g.fontes["radar"] = "ok"
    for a in radar.get("achados", []):
        c = _dig(a.get("cnpj"))
        if len(c) != 14:
            continue
        f = g.f(c, a.get("nome") if a.get("nome") not in (None, "—") else "")
        f["score"] = int(a.get("score") or 0)
        f["sinais"] = [{"sinal": s.get("sinal"), "peso": s.get("peso"), "detalhe": s.get("detalhe", "")}
                       for s in a.get("sinais", [])][:8]


def _casos(g: _G, casos: list[dict], nomes_ug: dict):
    for caso in casos:
        cnpjs = sorted({_dig(c) for c in caso.get("cnpjs", []) if len(_dig(c)) == 14})
        ug = re.search(r"\bUG\s*(\d{6})\b", caso.get("entidade") or "")
        ug = _dig(caso.get("ug")) if len(_dig(caso.get("ug"))) == 6 else (ug.group(1) if ug else "")   # frontmatter vence
        g.casos.append({"slug": caso["slug"], "titulo": caso.get("titulo") or caso["slug"],
                        "nivel": caso.get("nivel", 0), "nivel_rotulo": caso.get("nivel_rotulo", ""),
                        "situacao": caso.get("situacao", ""), "entidade": caso.get("entidade", ""),
                        "cnpjs": cnpjs, "sei": list(dict.fromkeys(caso.get("sei", []))),
                        "ug": ug, "esfera": esfera_de(caso.get("esfera", ""), caso.get("tags", []), caso.get("entidade", ""))})
        for c in cnpjs:
            g.f(c)["casos"].add(caso["slug"])
        if ug:
            g.o(f"ug:{ug}", nomes_ug.get(ug) or f"UG {ug}")


def _orgaos(g: _G, con, nomes_ug: dict):
    """Quem pagou (OB SIAFE contabilizada) ou contratou (PCRJ/PNCP) cada fornecedor."""
    cn = sorted(g.forn)
    paga = _ob_paga(con) if con is not None else ""   # sem base: _q levanta e a fonte vira INDISPONÍVEL
    try:
        for c, ug, n, v in _em_lotes(con, "SELECT credor, ug_emitente, COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe "
                                          "WHERE credor IN ({}) AND " + paga + " GROUP BY 1, 2", cn):
            if c in g.forn and ug and (v or 0) > 0:
                f = g.forn[c]
                f["org"][f"ug:{ug}"] += float(v)
                f["org_via"][f"ug:{ug}"] = "OB"
                f.setdefault("pago", Counter())[f"ug:{ug}"] += float(v)
        g.fontes["ob_siafe"] = "ok"
    except sqlite3.Error:
        g.fontes["ob_siafe"] = "INDISPONÍVEL"
    sem = [c for c in cn if not any(v == "OB" for v in g.forn[c]["org_via"].values())]
    try:
        from compliance_agent.esfera_orgao import no_rj
        for c, oc, on, n in _em_lotes(con, "SELECT fornecedor_documento, orgao_cnpj, MAX(orgao_nome), COUNT(*) "
                                           "FROM pcrj_contratos WHERE fornecedor_documento IN ({}) GROUP BY 1, 2", sem):
            oc = _dig(oc)
            # pcrj_contratos tem 82 mil contratos FEDERAIS (UNIRIO, Fiocruz, Marinha…): só órgão do RJ vira
            # elo na galáxia (dono, 19/11/2026: "esquece a parte federal")
            if len(oc) == 14 and no_rj(oc, on or ""):
                g.o(f"cnpj:{oc}", on)
                g.forn[c]["org"][f"cnpj:{oc}"] += n * 1e-3          # contrato pesa menos que OB paga
                g.forn[c]["org_via"].setdefault(f"cnpj:{oc}", "contrato")
        g.fontes["contratos_pncp"] = "ok"
    except sqlite3.Error:
        g.fontes["contratos_pncp"] = "INDISPONÍVEL"
    try:                                                    # sem OB no SIAFE: o órgão MUNICIPAL que PAGOU (PCRJ)
        for c, on, v, e0, e1 in _em_lotes(con, "SELECT credor_documento, orgao, SUM(pago), MIN(exercicio), MAX(exercicio) "
                                                "FROM pcrj_despesa WHERE credor_documento IN ({}) AND pago > 0 GROUP BY 1, 2", sem):
            n = _norm(on)
            if n and (v or 0) > 0:
                g.o(f"pcrj:{n}", f"{str(on).strip()} (Prefeitura do Rio)")
                f = g.forn[c]
                f["org"][f"pcrj:{n}"] += float(v)                 # R$ pago pesa como a OB; contrato (1e-3) fica atrás
                f["org_via"][f"pcrj:{n}"] = "PCRJ"
                f.setdefault("pago", Counter())[f"pcrj:{n}"] += float(v)
                f.setdefault("pago_ex", {})[f"pcrj:{n}"] = f"{e0}–{e1}" if e0 != e1 else str(e0)
        g.fontes["despesa_pcrj"] = "ok"
    except sqlite3.Error:
        g.fontes["despesa_pcrj"] = "INDISPONÍVEL"
    for chave in {k for f in g.forn.values() for k in f["org"]}:
        if chave.startswith("ug:"):
            ug = chave[3:]
            g.o(chave, nomes_ug.get(ug) or f"UG {ug}")
    for sql in ("SELECT favorecido_cpf, favorecido_nome FROM favorecido_resumo WHERE favorecido_cpf IN ({})",
                "SELECT cnpj, razao_social FROM empresas WHERE cnpj IN ({})",
                "SELECT cnpj, razao FROM endereco_fornecedor WHERE cnpj IN ({})",
                "SELECT cnpj, razao_social FROM fantasma_score WHERE cnpj IN ({})",
                "SELECT fornecedor_cnpj, MAX(fornecedor_nome) FROM pncp_resultado WHERE fornecedor_cnpj IN ({}) GROUP BY 1"):
        try:
            for c, rz in _em_lotes(con, sql, [c for c in cn if not g.forn[c]["nome"]]):
                g.f(c, rz)
        except sqlite3.Error:
            pass


# Fornecedor sem órgão: o MOTIVO medido vira o aglomerado (um balde por motivo, nunca o texto genérico).
SEM_FORN = {
    "sem:base": "Sem órgão — base de OB indisponível (não medido)",
    "sem:outra_raiz": "Sem órgão — OB paga no SIAFE só para outro estabelecimento da mesma empresa (raiz do CNPJ)",
    "sem:so_tfe": "Sem órgão — OB só no espelho TFE, nenhuma no SIAFE",
    "sem:so_pncp": "Sem órgão — só resultado de licitação no PNCP; sem OB no SIAFE, pagamento PCRJ ou contrato",
    "sem:sem_ob": "Sem órgão — CNPJ sem OB no SIAFE, sem pagamento PCRJ e sem contrato publicado",
}


def _motivos_sem_orgao(g: _G, con, cs: list[str]) -> dict[str, str]:
    """{cnpj: chave de SEM_FORN} para os fornecedores sem órgão. Cada motivo é uma consulta real (índice por CNPJ)."""
    if not cs:
        return {}
    if g.fontes.get("ob_siafe") != "ok":
        return {c: "sem:base" for c in cs}
    out = {}
    try:
        paga = _ob_paga(con)
        por_raiz = defaultdict(list)
        for c in cs:
            por_raiz[c[:8]].append(c)
        for r, cs_r in por_raiz.items():
            if _q(con, "SELECT 1 FROM ob_orcamentaria_siafe WHERE credor >= ? AND credor < ? AND " + paga + " LIMIT 1",
                  (r, r + "~")):
                out.update({c: "sem:outra_raiz" for c in cs_r})
    except sqlite3.Error:
        pass
    for chave, sql in (("sem:so_tfe", "SELECT DISTINCT favorecido_cpf FROM ordens_bancarias WHERE favorecido_cpf IN ({})"),
                       ("sem:so_pncp", "SELECT DISTINCT fornecedor_cnpj FROM pncp_resultado WHERE fornecedor_cnpj IN ({})")):
        try:
            for (c,) in _em_lotes(con, sql, [c for c in cs if c not in out]):
                out.setdefault(c, chave)
        except sqlite3.Error:
            pass
    return {c: out.get(c, "sem:sem_ob") for c in cs}


def _socios(g: _G, con):
    """Sócios (nome do QSA público). Entra: o sócio compartilhado por 2+ fornecedores do grafo, e até
    SOCIOS_POR_CNPJ sócios de quem tem dossiê ou score ≥ 25. Sem documento na saída."""
    cn = sorted(g.forn)
    por_cnpj = defaultdict(list)
    try:
        for c, rz, nome in _em_lotes(con, "SELECT cnpj, MAX(razao), socio_nome_norm FROM socios_fornecedor WHERE cnpj IN ({}) "
                                          "GROUP BY cnpj, socio_nome_norm ORDER BY cnpj, socio_nome_norm", cn):
            if rz:
                g.f(c, rz)
            if nome and nome != _SEM_QSA:
                por_cnpj[c].append(nome)
                g.socio_de[nome].add(c)
        g.fontes["qsa"] = "ok"
    except sqlite3.Error:
        g.fontes["qsa"] = "INDISPONÍVEL"
    manter = {s for s, cs in g.socio_de.items() if len(cs) >= 2}
    for c, nomes in por_cnpj.items():
        f = g.forn[c]
        if f["casos"] or f["score"] >= 25:
            manter.update(nomes[:SOCIOS_POR_CNPJ])
    for s in list(g.socio_de):
        if s not in manter:
            del g.socio_de[s]


def _hubs(g: _G, hubs: dict | None):
    if not hubs or not hubs.get("ok"):
        g.fontes["endereco"] = "INDISPONÍVEL"
        return
    g.fontes["endereco"] = "ok"
    for gr in hubs.get("grupos", []):
        if gr.get("risco") not in ("alto", "medio"):
            continue
        cs = sorted({_dig(c) for c in gr.get("cnpjs", []) if _dig(c) in g.forn})
        for c in cs:
            g.end_grupos[c].add(f"mesmo {gr.get('chave', 'endereço')} (grupo de {gr.get('n_cnpjs')} CNPJs, "
                                f"risco {gr.get('risco')})")
        # corrente em vez de clique: todos dividem a mesma âncora; desenhar os n(n-1)/2 pares só embola
        for a, b in zip(cs, cs[1:]):
            g.liga(f"cnpj:{a}", f"cnpj:{b}", "endereco", 1.0,
                   det=f"mesmo {gr.get('chave', 'endereço')} — grupo de {gr.get('n_cnpjs')} CNPJs (risco {gr.get('risco')})")


def _conluio(g: _G, con, estab):
    """Ligações novas entre fornecedores que já são nós: contato, sócio variante e concorrentes ligados
    (`ligacoes_conluio`). Uma aresta por par de EMPRESAS (raiz), desenhada entre os representantes."""
    from compliance_agent.ligacoes_conluio import levantar, representantes
    rep = representantes(g.forn)
    r = levantar(con, estab, list(g.forn), g.end_grupos, {c: f["nome"] for c, f in g.forn.items()})
    for e in r["arestas"]:
        a, b = rep.get(e["a"]), rep.get(e["b"])
        if a and b:
            g.liga(f"cnpj:{a}", f"cnpj:{b}", e["tipo"], e["peso"], det=e["det"], ev=e["ev"], estado=e["estado"])
    g.fontes.update({f"conluio_{k}": v for k, v in r["fontes"].items()})
    g.conluio = r["medida"]


def _casos_pela_fonte(g: _G, con, resto: list[dict], nomes_ug: dict):
    from compliance_agent import orgao_fonte as of
    try:
        seis = [s for k in resto for s in k["sei"]]
        pref = of.mapa_prefixos(con) if seis else {}
        proc = of.ugs_dos_processos(con, seis) if seis else {}
        pago = of.ugs_pagadoras(con, [c for k in resto for c in k["cnpjs"]])
        g.fontes["sei_prefixo_ug"] = "ok"
    except sqlite3.Error:
        g.fontes["sei_prefixo_ug"] = "INDISPONÍVEL"
        for k in resto:
            k["cl"] = "sem:dossie_base"
            g.o(k["cl"], "Dossiês sem órgão — base de OB indisponível (não medido)")
        return
    for k in resto:
        r = of.resolver(k["sei"], k["cnpjs"], pref, proc, pago, k.get("esfera", ""))
        if r["ug"]:
            k["cl"], k["via"] = f"ug:{r['ug']}", f"{r['via']}: {r['det']}"
            g.o(k["cl"], nomes_ug.get(r["ug"]) or f"UG {r['ug']}")
        else:
            k["cl"], k["mot"] = f"sem:dossie_{r['motivo']}", of.MOTIVOS_CASO[r["motivo"]]
            g.o(k["cl"], f"Dossiês sem órgão — {k['mot']}")


# ── layout ───────────────────────────────────────────────────────────────────────────────────────

_GA = math.pi * (3 - math.sqrt(5))             # ângulo de ouro


def _empacotar(raios: list[float], folga: float = 26.0) -> list[tuple[float, float]]:
    """Círculos (maior primeiro) numa espiral de Arquimedes, cada um no primeiro ponto livre.
    A busca continua de onde o anterior parou (recuando uma volta, para os pequenos taparem os
    vãos) e o teste de colisão é vetorizado — 330 aglomerados em ~0,1 s (era 93 s)."""
    import numpy as np
    n = len(raios)
    px, py, pr = np.zeros(n), np.zeros(n), np.asarray(raios, dtype=float)
    B = 14.0 / (2 * math.pi)                       # 14 unidades entre voltas
    th = 0.0
    for i in range(1, n):
        r = pr[i]
        th = max(0.0, th - 2 * math.pi)
        while True:
            rho = B * th
            x, y = rho * math.cos(th), rho * math.sin(th)
            if np.all((px[:i] - x) ** 2 + (py[:i] - y) ** 2 >= (pr[:i] + r + folga) ** 2):
                px[i], py[i] = x, y
                break
            th += 9.0 / max(rho, 9.0)
    return list(zip(px.tolist(), py.tolist()))


def montar(casos: list[dict], con: sqlite3.Connection | None = None, radar: dict | None = None,
           hubs: dict | None = None, estab: sqlite3.Connection | None = None) -> dict:
    t0 = time.time()
    g = _G()
    nomes_ug = {}
    try:
        nomes_ug = {ug: nm for ug, nm in _q(con, "SELECT ug_codigo, MAX(ug_nome) FROM ordens_bancarias "
                                                 "WHERE ug_nome IS NOT NULL GROUP BY ug_codigo") if ug}
    except sqlite3.Error:
        pass
    _casos(g, casos, nomes_ug)
    _radar(g, radar)
    _alertas(g, con, nomes_ug)
    _orgaos(g, con, nomes_ug)
    _socios(g, con)
    _hubs(g, hubs)
    _conluio(g, con, estab)

    # aglomerado de cada fornecedor = órgão de maior peso; sem órgão → um aglomerado POR MOTIVO medido
    membro = defaultdict(list)
    motivo = _motivos_sem_orgao(g, con, sorted(c for c, f in g.forn.items() if not f["org"]))
    for c, f in g.forn.items():
        chave = f["org"].most_common(1)[0][0] if f["org"] else motivo[c]
        f["cl"] = chave
        membro[chave].append(c)
        if chave in SEM_FORN:
            g.o(chave, SEM_FORN[chave])
    # dossiê: UG declarada (frontmatter/entidade) → órgão dos fornecedores citados → OB do processo SEI citado →
    # prefixo SEI no índice de OB → quem mais pagou o CNPJ citado (orgao_fonte); sem nada → balde com o motivo
    resto = []
    for k in g.casos:
        cont = Counter(g.forn[c]["cl"] for c in k["cnpjs"] if c in g.forn and not g.forn[c]["cl"].startswith("sem:"))
        k["cl"] = f"ug:{k['ug']}" if k["ug"] else (cont.most_common(1)[0][0] if cont else "")
        if not k["cl"]:
            resto.append(k)
    if resto:
        _casos_pela_fonte(g, con, resto, nomes_ug)
    for k in g.casos:
        g.org[k["cl"]]["casos"].add(k["slug"])

    # sócios: mora perto do primeiro fornecedor (maior score) que o tem
    socio_dono = {}
    socios_de_forn = defaultdict(list)
    for s, cs in sorted(g.socio_de.items()):
        dono = max(cs, key=lambda c: (g.forn[c]["score"], c))
        socio_dono[s] = dono
        socios_de_forn[dono].append(s)

    # ─ layout local de cada aglomerado
    ESP = 15.0
    locais, raios = {}, {}
    for chave, o in g.org.items():
        cs = sorted(membro.get(chave, []), key=lambda c: (-len(g.forn[c]["casos"]), -g.forn[c]["score"],
                                                           -sum(g.forn[c]["al"].values()), c))
        ks = [k for k in g.casos if k["cl"] == chave]
        loc = {f"org:{chave}": (0.0, 0.0)}
        nucleo = 26.0 + 9.0 * math.sqrt(len(ks))
        for i, k in enumerate(ks):                           # dossiês num anel colado ao órgão
            a = i * _GA + _h01(k["slug"]) * 0.3
            r = 22.0 + 9.0 * math.sqrt(i + 1)
            loc[f"caso:{k['slug']}"] = (r * math.cos(a), r * math.sin(a))
            for j, sei in enumerate(k["sei"]):
                b = a + (j - len(k["sei"]) / 2) * 0.32
                loc.setdefault(f"sei:{sei}", (r * math.cos(a) + 13 * math.cos(b + 1.5), r * math.sin(a) + 13 * math.sin(b + 1.5)))
        rmax = nucleo
        for i, c in enumerate(cs):                           # filotaxia: score maior perto do centro
            r = nucleo + ESP * math.sqrt(i + 0.5)
            a = i * _GA
            x, y = r * math.cos(a), r * math.sin(a)
            loc[f"cnpj:{c}"] = (x, y)
            ss = socios_de_forn.get(c, [])
            for j, s in enumerate(ss):
                b = a + (j - (len(ss) - 1) / 2) * 0.9
                loc[f"socio:{s}"] = (x + 6.5 * math.cos(b), y + 6.5 * math.sin(b))
            rmax = max(rmax, r + (7 if ss else 0))
        locais[chave], raios[chave] = loc, rmax + 6
    ordem = sorted(g.org, key=lambda k: (k.startswith(("sem:", "vault:")), -raios[k], k))   # "sem órgão" na borda
    centros = dict(zip(ordem, _empacotar([raios[k] for k in ordem])))

    # ─ nós
    nos, idx = [], {}

    def add(nid, **kw):
        idx[nid] = len(nos)
        nos.append({"id": nid, **kw})

    for chave in ordem:
        o, (cx, cy) = g.org[chave], centros[chave]
        loc = locais[chave]
        n_forn = len(membro.get(chave, []))
        s_max = max((g.forn[c]["score"] for c in membro.get(chave, [])), default=0)
        add(f"org:{chave}", t="orgao", l=o["nome"], x=round(cx, 1), y=round(cy, 1), cl=chave,
            R=round(raios[chave], 1), nf=n_forn, nal=sum(o["al"].values()) + sum(sum(g.forn[c]["al"].values()) for c in membro.get(chave, [])),
            al=dict(o["al"].most_common(6)), ex=o["ex"], s=s_max, nk=len(o["casos"]),
            ug=chave[3:] if chave.startswith("ug:") else "", ocnpj=chave[5:] if chave.startswith("cnpj:") else "")
        for k in g.casos:
            if k["cl"] != chave:
                continue
            x, y = loc[f"caso:{k['slug']}"]
            add(f"caso:{k['slug']}", t="caso", l=k["titulo"], x=round(cx + x, 1), y=round(cy + y, 1), cl=chave,
                slug=k["slug"], nv=k["nivel"], nvr=k["nivel_rotulo"], sit=k["situacao"], ent=k["entidade"][:120],
                **({"via": k["via"]} if k.get("via") else {}), **({"mot": k["mot"]} if k.get("mot") else {}))
            for sei in k["sei"]:
                if f"sei:{sei}" not in idx:
                    x, y = loc.get(f"sei:{sei}", (0, 0))
                    add(f"sei:{sei}", t="sei", l=sei, x=round(cx + x, 1), y=round(cy + y, 1), cl=chave)
        for c in membro.get(chave, []):
            f = g.forn[c]
            x, y = loc[f"cnpj:{c}"]
            pago = f.get("pago") or {}
            add(f"cnpj:{c}", t="cnpj", l=f["nome"] or f"CNPJ {c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}",
                x=round(cx + x, 1), y=round(cy + y, 1), cl=chave, cnpj=c, s=f["score"], sin=f["sinais"],
                nal=sum(f["al"].values()), al=dict(f["al"].most_common(6)), ex=f["ex"],
                k=sorted(f["casos"]), pago=round(sum(pago.values()), 2) if pago else None,
                # órgão principal + secundários (peso = R$ pago; contrato pesa 1e-3 por contrato) para o front mostrar
                orgs=[{"cl": ch, "l": g.org[ch]["nome"] if ch in g.org else ch, "via": f["org_via"].get(ch, "contrato"),
                       "pago": round(pago.get(ch, 0), 2) or None} for ch, _ in f["org"].most_common(ORGAOS_POR_CNPJ)],
                **({"mot": SEM_FORN[chave]} if chave in SEM_FORN else {}))
            for s in socios_de_forn.get(c, []):
                x, y = loc[f"socio:{s}"]
                add(f"socio:{s}", t="socio", l=s, x=round(cx + x, 1), y=round(cy + y, 1), cl=chave,
                    nf=len(g.socio_de[s]))

    # ─ arestas
    for c, f in g.forn.items():
        for chave, peso in f["org"].most_common(ORGAOS_POR_CNPJ):
            if chave in g.org:
                via = f["org_via"].get(chave, "contrato")
                rs = f"R$ {(f.get('pago') or {}).get(chave, 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                det = (f"OB contabilizada no SIAFE: {rs}" if via == "OB"
                       else f"pago pela Prefeitura do Rio (despesa aberta PCRJ, {f.get('pago_ex', {}).get(chave, '')}): {rs}"
                       if via == "PCRJ" else "contrato/compra publicada (PCRJ/PNCP) — não é pagamento")
                g.liga(f"org:{chave}", f"cnpj:{c}", "orgao", 1.0, det=det, via=via)
    for s, cs in g.socio_de.items():
        for c in cs:
            g.liga(f"cnpj:{c}", f"socio:{s}", "socio")
    for k in g.casos:
        for c in k["cnpjs"]:
            g.liga(f"caso:{k['slug']}", f"cnpj:{c}", "cita_cnpj")
        for sei in k["sei"]:
            g.liga(f"caso:{k['slug']}", f"sei:{sei}", "cita_sei")
        g.liga(f"caso:{k['slug']}", f"org:{k['cl']}", "caso_orgao")
    pertence = defaultdict(set)                           # pontes entre dossiês (mesma regra da v61)
    for k in g.casos:
        for c in k["cnpjs"]:
            pertence[f"cnpj:{c}"].add(k["slug"])
        for sei in k["sei"]:
            pertence[f"sei:{sei}"].add(k["slug"])
        ent = (k["entidade"] or "").strip().lower()
        if ent:
            pertence[f"ent:{ent}"].add(k["slug"])
    for s, cs in g.socio_de.items():
        for c in cs:
            for slug in g.forn[c]["casos"]:
                pertence[f"socio:{s}"].add(slug)
    ponte = defaultdict(Counter)
    for chave, ss in pertence.items():
        for a, b in combinations(sorted(ss), 2):
            ponte[(a, b)][chave.split(":", 1)[0]] += 1
    for (a, b), mot in ponte.items():
        g.liga(f"caso:{a}", f"caso:{b}", "caso_caso", float(sum(mot.values())), motivos=dict(mot))

    arestas = []
    grau = Counter()
    for e in g.arestas.values():
        if e["a"] in idx and e["b"] in idx:
            arestas.append({"s": idx[e["a"]], "t": idx[e["b"]], **{k: v for k, v in e.items() if k not in ("a", "b")}})
            grau[idx[e["a"]]] += 1
            grau[idx[e["b"]]] += 1
    for i, n in enumerate(nos):
        n["g"] = grau[i]

    novas = {}
    for t in TIPOS_CONLUIO:                               # quantas cruzam aglomerado / dossiê
        es = [e for e in arestas if e["tipo"] == t]
        novas[t] = {"arestas": len(es),
                    "entre_orgaos_diferentes": sum(1 for e in es if nos[e["s"]]["cl"] != nos[e["t"]]["cl"]),
                    "entre_casos_diferentes": sum(1 for e in es if set(nos[e["s"]].get("k") or [])
                                                  != set(nos[e["t"]].get("k") or [])
                                                  and (nos[e["s"]].get("k") or nos[e["t"]].get("k")))}

    tipos = Counter(n["t"] for n in nos)
    forn_score = [f["score"] for f in g.forn.values()]
    n_anc = g.n_alertas - sum(g.sem_ancora.values())
    resumo = {
        "casos": tipos["caso"], "orgaos": sum(1 for k in g.org if not k.startswith(("sem:", "vault:"))),
        "fornecedores": tipos["cnpj"], "cnpjs": tipos["cnpj"],
        "fornecedores_radar": sum(1 for s in forn_score if s > 0),
        "criticos": sum(1 for s in forn_score if s >= CRITICO),
        "atencao": sum(1 for s in forn_score if 25 <= s < CRITICO),
        "socios": tipos["socio"], "processos_sei": tipos["sei"],
        "alertas_abertos": g.n_alertas, "alertas_no_grafo": n_anc,
        "alertas_sem_ancora": dict(g.sem_ancora.most_common()),
        "arestas": len(arestas),
        "pontes_entre_casos": sum(1 for e in arestas if e["tipo"] == "caso_caso"),
        "ligacoes_endereco": sum(1 for e in arestas if e["tipo"] == "endereco"),
        "ligacoes_socio_compartilhado": sum(1 for s, cs in g.socio_de.items() if len(cs) >= 2),
        "ligacoes_contato": novas["contato"]["arestas"],
        "ligacoes_socio_variante": novas["socio_variante"]["arestas"],
        "ligacoes_concorrentes": novas["concorrentes_ligados"]["arestas"],
        "conluio": {"por_tipo": novas, "medida": g.conluio, "estado": "indício a verificar"},
        # o que ficou sem órgão, por motivo medido (fornecedores e dossiês)
        "sem_orgao": {"fornecedores": dict(Counter(f["cl"] for f in g.forn.values() if f["cl"].startswith("sem:")).most_common()),
                      "casos": dict(Counter(k["cl"] for k in g.casos if k["cl"].startswith("sem:")).most_common())},
    }
    return {"ok": True, "versao": 2, "gerado_em": time.strftime("%Y-%m-%d %H:%M"), "segundos": round(time.time() - t0, 2),
            "nos": nos, "arestas": arestas, "resumo": resumo, "fontes": g.fontes,
            "rotulos_alerta": _ROTULO_ALERTA, "critico": CRITICO, "aviso": AVISO,
            "nota": ("Score = soma de sinais independentes do Radar (0–100; 🔴 ≥ 50 · 🟡 25–49 · 🟢 < 25), indício interno. "
                     "Alerta de pessoa (acúmulo, teto) conta no órgão, sem nome. Órgão do fornecedor = quem mais pagou "
                     "(OB contabilizada no SIAFE); sem OB, o órgão da Prefeitura do Rio que pagou (despesa aberta PCRJ) ou o do "
                     "contrato publicado. Sem nenhum deles, o aglomerado cinza diz o MOTIVO medido.")}


# ── geração, cache e recorte ────────────────────────────────────────────────────────────────────

def gerar(salvar: bool = True) -> dict:
    from compliance_agent.casos_vault import listar
    from compliance_agent.database.models import _resolver_db
    r = listar()
    casos = r.get("casos", []) if r.get("ok") else []
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel, radar_risco
        radar = radar_risco(limite=None)
        hubs = ler_cache_intel("hub_compartilhado")
    except Exception:                                      # noqa: BLE001 — fonte vira INDISPONÍVEL
        radar, hubs = None, None
    try:
        con = sqlite3.connect(f"file:{_resolver_db()}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        con = None
    estab = None
    arq_estab = Path(_resolver_db()).parent / "receita_estab.db"
    if arq_estab.exists():
        try:
            estab = sqlite3.connect(f"file:{arq_estab}?mode=ro", uri=True, timeout=10)
        except sqlite3.Error:
            estab = None                                   # contato vira INDISPONÍVEL em `fontes`
    try:
        d = montar(casos, con, radar, hubs, estab)
    finally:
        for c in (con, estab):
            if c is not None:
                c.close()
    if not r.get("ok"):
        d["fontes"]["vault"] = "INDISPONÍVEL"
    else:
        d["fontes"]["vault"] = "ok"
    if salvar:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(CACHE)
    return d


_MEM: dict = {"mtime": None, "d": None, "leve": {}}
# Tipos NOVOS entram sempre no FIM: `leve()` manda o índice, e o front colore pelo índice.
TIPOS_CONLUIO = ("contato", "socio_variante", "concorrentes_ligados")
TIPOS_ARESTA = ("orgao", "socio", "cita_cnpj", "cita_sei", "caso_orgao", "caso_caso", "endereco") + TIPOS_CONLUIO
_LEVE = ("id", "t", "l", "x", "y", "cl", "s", "nal", "nv", "g", "R", "nf", "slug", "cnpj", "mot")


def ler() -> dict | None:
    """Cópia em memória do JSON pré-calculado (relida só quando o arquivo muda)."""
    try:
        mt = CACHE.stat().st_mtime
    except OSError:
        return None
    if _MEM["mtime"] != mt:
        try:
            _MEM.update(d=json.loads(CACHE.read_text(encoding="utf-8")), mtime=mt, leve={})
        except (OSError, ValueError):
            return None
    return _MEM["d"]


def recortar(d: dict, limite: int | None = None, score_min: int = 0, orgao: str = "") -> dict:
    """Recorte do grafo: os `limite` fornecedores de maior prioridade (dossiê > score > alertas), só
    score ≥ score_min, só um aglomerado. Órgãos e dossiês ficam sempre; o resumo é sempre o GLOBAL."""
    nos = d["nos"]
    if not (limite or score_min or orgao):
        return d
    forn = [i for i, n in enumerate(nos) if n["t"] == "cnpj" and (n.get("s") or 0) >= score_min
            and (not orgao or n["cl"] == orgao)]
    forn.sort(key=lambda i: (-len(nos[i].get("k") or []), -(nos[i].get("s") or 0), -(nos[i].get("nal") or 0)))
    if limite:
        forn = forn[:max(0, int(limite))]
    manter = set(forn) | {i for i, n in enumerate(nos) if n["t"] in ("orgao", "caso", "sei")
                          and (not orgao or n["cl"] == orgao)}
    viz = defaultdict(list)
    for e in d["arestas"]:
        viz[e["s"]].append(e["t"])
        viz[e["t"]].append(e["s"])
    for i in list(forn):
        manter.update(j for j in viz[i] if nos[j]["t"] == "socio")
    novo = {i: k for k, i in enumerate(sorted(manter))}
    arestas = [{**e, "s": novo[e["s"]], "t": novo[e["t"]]} for e in d["arestas"] if e["s"] in novo and e["t"] in novo]
    return {**d, "nos": [nos[i] for i in sorted(manter)], "arestas": arestas,
            "recorte": {"limite": limite, "score_min": score_min, "orgao": orgao,
                        "fornecedores": len(forn), "nos": len(novo), "arestas": len(arestas)}}


def leve(d: dict) -> dict:
    """O que o desenho precisa: nó sem prova/alertas (vêm de `detalhe`), aresta como [s, t, tipo]."""
    nos = []
    for n in d["nos"]:
        m = {k: n[k] for k in _LEVE if n.get(k) not in (None, "", 0) or k in ("x", "y")}
        if n["t"] == "cnpj" and n.get("k"):
            m["nk"] = len(n["k"])
        m["cor"] = cores_orgaos.cor(n.get("cl"))           # cor do ÓRGÃO do aglomerado (config/cores_orgaos.yaml)
        nos.append(m)
    ti = {t: i for i, t in enumerate(TIPOS_ARESTA)}
    ar = [[e["s"], e["t"], ti.get(e["tipo"], 0)] for e in d["arestas"]]
    fora = ("nos", "arestas")
    return {**{k: v for k, v in d.items() if k not in fora}, "nos": nos, "arestas": ar, "tipos_aresta": list(TIPOS_ARESTA)}


def detalhe(no_id: str) -> dict:
    """Um nó com a prova (sinais do Radar, alertas, dossiês) e os vizinhos com o motivo de cada ligação."""
    d = ler()
    if d is None:
        return {"ok": False, "erro": "galáxia ainda não gerada"}
    idx = next((i for i, n in enumerate(d["nos"]) if n["id"] == no_id), None)
    if idx is None:
        return {"ok": False, "erro": "nó não encontrado"}
    viz = []
    for e in d["arestas"]:
        if idx in (e["s"], e["t"]):
            o = d["nos"][e["t"] if e["s"] == idx else e["s"]]
            viz.append({"id": o["id"], "t": o["t"], "l": o["l"], "s": o.get("s"), "tipo": e["tipo"],
                        "det": e.get("det", ""), "via": e.get("via", ""), "motivos": e.get("motivos"),
                        "ev": e.get("ev"), "estado": e.get("estado")})
    ordem = {"caso_caso": 0, "cita_cnpj": 1, "caso_orgao": 1, "concorrentes_ligados": 2, "orgao": 2, "contato": 3,
             "socio_variante": 3, "endereco": 3, "socio": 4, "cita_sei": 5}
    viz.sort(key=lambda v: (ordem.get(v["tipo"], 9), -(v["s"] or 0), v["l"]))
    return {"ok": True, "no": d["nos"][idx], "vizinhos": viz[:80], "n_vizinhos": len(viz),
            "rotulos_alerta": d.get("rotulos_alerta", {}), "aviso": d.get("aviso", AVISO), "gerado_em": d.get("gerado_em")}


def galaxia(limite: int | None = None, score_min: int = 0, orgao: str = "", forcar: bool = False) -> dict:
    d = None if forcar else ler()
    if d is None:
        d = gerar(salvar=True)
        ler()
    return leve(recortar(d, limite, score_min, orgao))


def galaxia_bytes(limite: int | None = None, score_min: int = 0, orgao: str = "") -> bytes:
    """JSON já serializado, memorizado por recorte enquanto o arquivo não muda (a rota responde em ms)."""
    if ler() is None:
        galaxia()
    chave = (limite or 0, score_min or 0, orgao or "")
    memo = _MEM.setdefault("leve", {})
    if chave not in memo:
        if len(memo) > 24:
            memo.clear()
        memo[chave] = json.dumps(galaxia(limite, score_min, orgao), ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
    return memo[chave]


def galaxia_gz(limite: int | None = None, score_min: int = 0, orgao: str = "") -> bytes:
    """O mesmo JSON já comprimido (gzip nível 6), memorizado — a rota não recomprime 1 MB a cada visita."""
    import gzip
    b = galaxia_bytes(limite, score_min, orgao)
    memo = _MEM.setdefault("gz", {})
    if memo.get("_mt") != _MEM["mtime"]:
        memo.clear()
        memo["_mt"] = _MEM["mtime"]
    chave = (limite or 0, score_min or 0, orgao or "")
    if chave not in memo:
        memo[chave] = gzip.compress(b, 6)
    return memo[chave]


if __name__ == "__main__":
    import sys
    if (sys.argv[1] if len(sys.argv) > 1 else "gerar") == "gerar":
        d = gerar()
        print(json.dumps({"ok": d["ok"], "segundos": d["segundos"], "resumo": d["resumo"], "fontes": d["fontes"],
                          "bytes": CACHE.stat().st_size}, ensure_ascii=False))
