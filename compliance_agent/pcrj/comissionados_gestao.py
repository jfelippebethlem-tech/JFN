# -*- coding: utf-8 -*-
"""Comissionados da Prefeitura do Rio nas gestões Eduardo Paes (01/01/2021–20/03/2026) e Eduardo Cavaliere
(20/03/2026–) que já foram CANDIDATOS (TSE-RJ 2012–2026).

Universo: pessoas de `tse_candidatura` (todas as candidaturas do RJ casadas por NOME com a folha inteira da
Prefeitura) que aparecem na folha em bloco (`pcrj_folha_pref`) de 01/2021 em diante. A folha não traz cargo — o
CARGO, a ADMISSÃO e a EXONERAÇÃO de cada matrícula vêm do portal de remuneração (contrachequeapi), consultado na
ÚLTIMA competência em que a matrícula aparece na janela, e ficam em cache em `pcrj_cargo_portal` (coleta retomável).
A CONTINUIDADE do vínculo é medida mês a mês na folha em bloco (lacuna = mês em que a base tem folha e a matrícula
não aparece).

Sem CPF → o casamento servidor × candidato é por nome (indício); a confiança é declarada por pessoa.
"""
from __future__ import annotations

import html
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.nomes import normalizar

INICIO = "202101"                     # posse de Eduardo Paes (3º mandato): 01/01/2021
PAES_FIM = "20260320"                 # renúncia de Paes / posse de Cavaliere: 20/03/2026
PAES_ULTIMA_COMP = "202603"           # competência 03/2026 contada na gestão Paes (a troca foi no dia 20)
# Eleições gerais 2026: 1º turno 04/10/2026 → comissionado exonerado até 04/07/2026 (LC 64/90, art. 1º, II, l; Súm. TSE 54)
DESINC_INI, DESINC_PRAZO, DESINC_FIM = "20260601", "20260704", "20260731"
# 1º turno de cada eleição (datas oficiais do TSE)
ELEICAO = {2012: date(2012, 10, 7), 2014: date(2014, 10, 5), 2016: date(2016, 10, 2), 2018: date(2018, 10, 7),
           2020: date(2020, 11, 15), 2022: date(2022, 10, 2), 2024: date(2024, 10, 6), 2026: date(2026, 10, 4)}
_NUM = "CAST(replace(replace(remun_bruta,'.',''),',','.') AS REAL)"


def _criar_tabelas(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS pcrj_cargo_portal (
        nome_norm TEXT, competencia TEXT, matricula TEXT, nome TEXT, cargo TEXT, lotacao TEXT,
        admissao TEXT, exoneracao TEXT, folha TEXT, vantagens TEXT, coletado_em TEXT,
        PRIMARY KEY (nome_norm, competencia, matricula, folha))""")
    con.execute("""CREATE TABLE IF NOT EXISTS pcrj_cargo_portal_consulta (
        nome_norm TEXT, competencia TEXT, n INTEGER, coletado_em TEXT, PRIMARY KEY (nome_norm, competencia))""")


def pares(con) -> dict[tuple[str, str], dict]:
    """{(nome_norm, matrícula sem zeros): {primeira, ultima, meses{comp: bruto}, orgao}} na janela, só de candidatos."""
    con.execute("CREATE TEMP TABLE IF NOT EXISTS _cand AS SELECT DISTINCT nome_norm FROM tse_candidatura")
    out: dict[tuple[str, str], dict] = {}
    for nn, mat, comp, orgao, sigla, bruto in con.execute(
            f"SELECT f.nome_norm, ltrim(f.matricula,'0'), competencia, orgao, sigla_ua, {_NUM} "
            "FROM pcrj_folha_pref f JOIN _cand USING(nome_norm) WHERE competencia >= ?", (INICIO,)):
        d = out.setdefault((nn, mat), {"primeira": comp, "ultima": comp, "meses": {}, "orgao": None})
        d["primeira"] = min(d["primeira"], comp)
        if comp >= d["ultima"]:
            d["ultima"] = comp
            d["orgao"] = orgao or sigla or d["orgao"]
        d["meses"][comp] = d["meses"].get(comp, 0.0) + (bruto or 0.0)
    return out


def coletar(workers: int = 2, pausa: float = 0.4, db_path=None) -> dict:
    """Consulta o portal (nome × última competência de cada matrícula) e grava em cache. Retomável."""
    from compliance_agent.pcrj.pcrj_remuneracao import Sessao
    con = _db.conectar(db_path)
    _criar_tabelas(con)
    con.commit()
    alvo = {(nn, d["ultima"]) for (nn, _m), d in pares(con).items()}
    feitas = {tuple(r) for r in con.execute("SELECT nome_norm, competencia FROM pcrj_cargo_portal_consulta")}
    fila = sorted(alvo - feitas)
    # nome como publicado (com acento) — de qualquer competência, não só da mais recente
    nomes = {nn: nome for nn, nome in con.execute(
        "SELECT f.nome_norm, MAX(f.nome) FROM pcrj_folha_pref f JOIN _cand USING(nome_norm) "
        "WHERE competencia >= ? GROUP BY f.nome_norm", (INICIO,))}
    print(f"{len(alvo)} consultas no total · {len(feitas & alvo)} em cache · {len(fila)} a fazer", flush=True)
    sessoes = [Sessao(pausa=pausa) for _ in range(workers)]

    def tarefa(i_item):
        i, (nn, comp) = i_item
        nome = nomes.get(nn) or nn.upper()
        return nn, comp, sessoes[i % workers].consultar_nome(nome, int(comp[4:]), int(comp[:4]))

    agora = datetime.now(timezone.utc).isoformat()
    n = falhas = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for nn, comp, linhas in ex.map(tarefa, enumerate(fila)):
            n += 1
            if linhas is None:                      # INDISPONÍVEL ≠ vazio: não grava a consulta, fica para a próxima rodada
                falhas += 1
                continue
            for r in linhas:
                if normalizar(r.get("nome", "")) != nn:
                    continue                        # o portal busca por CONTÉM ("… JUNIOR" também volta)
                con.execute("INSERT OR REPLACE INTO pcrj_cargo_portal VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (nn, comp, str(r.get("matricula") or "").lstrip("0"), r.get("nome"), r.get("cargo"),
                             r.get("lotacao"), r.get("admissao"), r.get("exoneracao"), r.get("folha"),
                             r.get("vantagens"), agora))
            con.execute("INSERT OR REPLACE INTO pcrj_cargo_portal_consulta VALUES (?,?,?,?)",
                        (nn, comp, len(linhas), agora))
            if n % 50 == 0:
                for t in range(6):
                    try:
                        con.commit()
                        break
                    except sqlite3.OperationalError:
                        time.sleep(5 * (t + 1))
                print(f"  {n}/{len(fila)} · falhas {falhas}", flush=True)
    con.commit()
    con.close()
    return {"consultas": n, "falhas": falhas, "pendentes_antes": len(fila)}


# classificador canônico da casa (com vetos: "AGENTE DE APOIO A EDUCACAO ESPECIAL", estágios, "ESPECIALIDADE")
from compliance_agent.pcrj.pericia_beneficios import _cargo_comissionado  # noqa: E402


def _data(d: str | None) -> str:
    """'dd/mm/aaaa' → 'aaaammdd' (ordenável); vazio → ''."""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d or "")
    return f"{m.group(3)}{m.group(2)}{m.group(1)}" if m else ""


def _prox(comp: str) -> str:
    a, m = int(comp[:4]), int(comp[4:])
    return f"{a + (m == 12)}{(m % 12) + 1:02d}"


def _faixas(comps: list[str]) -> str:
    """['202203','202204','202206'] → '03/2022–04/2022, 06/2022'."""
    out, ini, ant = [], None, None
    for c in sorted(comps):
        if ini is None:
            ini = ant = c
        elif c == _prox(ant):
            ant = c
        else:
            out.append(ini if ini == ant else (ini, ant))
            ini = ant = c
    if ini:
        out.append(ini if ini == ant else (ini, ant))
    return ", ".join(_comp(x) if isinstance(x, str) else f"{_comp(x[0])}–{_comp(x[1])}" for x in out)


def continuidade(meses: set[str], ini: str, fim: str, base: set[str]) -> list[str]:
    """Competências SEM a matrícula entre ini e fim, contando só meses que a base tem (lacuna da fonte ≠ lacuna do
    vínculo)."""
    falta, c = [], ini
    while c <= fim:
        if c in base and c not in meses:
            falta.append(c)
        c = _prox(c)
    return falta


def pessoas(con) -> tuple[list[dict], dict]:
    """Uma entrada por pessoa com ≥1 matrícula COMISSIONADA na janela; + cobertura da coleta."""
    pr = pares(con)
    base = {r[0] for r in con.execute("SELECT DISTINCT competencia FROM pcrj_folha_pref WHERE competencia >= ?",
                                      (INICIO,))}
    cargos: dict[tuple[str, str], dict] = {}
    for nn, comp, mat, nome, cargo, lot, adm, exo in con.execute(
            "SELECT nome_norm, competencia, matricula, nome, cargo, lotacao, admissao, exoneracao FROM pcrj_cargo_portal"):
        d = pr.get((nn, mat))
        if d is None or comp != d["ultima"]:
            continue
        c = cargos.setdefault((nn, mat), {"nome": nome, "cargos": set(), "lotacao": lot, "admissao": adm,
                                          "exoneracao": exo})
        if cargo:
            c["cargos"].add(cargo)
        c["exoneracao"] = c["exoneracao"] or exo
    # exoneração já publicada em varreduras anteriores do portal (mesma matrícula) completa a data que falta
    exo_antiga: dict[str, str] = {}
    try:
        for mat, exo in con.execute("SELECT ltrim(matricula,'0'), exoneracao FROM pcrj_comissionado_candidato "
                                    "WHERE exoneracao IS NOT NULL AND exoneracao <> ''"):
            exo_antiga[str(mat)] = exo
    except sqlite3.Error:
        pass
    consultadas = {tuple(r) for r in con.execute("SELECT nome_norm, competencia FROM pcrj_cargo_portal_consulta")}
    alvo = {(nn, d["ultima"]) for (nn, _m), d in pr.items()}
    sem_cargo = sum(1 for k, d in pr.items() if (k[0], d["ultima"]) in consultadas and k not in cargos)
    cands: dict[str, list[dict]] = {}
    for r in con.execute("SELECT nome_norm, nome_tse, nome_urna, ano, cargo, municipio, partido, situacao, "
                         "resultado, eleito, outra_cidade FROM tse_candidatura ORDER BY ano"):
        cands.setdefault(r[0], []).append(dict(zip(
            ("nn", "nome", "urna", "ano", "cargo", "cidade", "partido", "situacao", "resultado", "eleito", "outra"), r)))
    mats_nome: dict[str, int] = {}
    for (nn, _m) in pr:
        mats_nome[nn] = mats_nome.get(nn, 0) + 1
    ultima = max(base) if base else None
    por: dict[str, dict] = {}
    for (nn, mat), c in cargos.items():
        com = sorted(x for x in c["cargos"] if _cargo_comissionado(x))
        if not com:
            continue
        d = pr[(nn, mat)]
        exo = c["exoneracao"] or exo_antiga.get(mat, "")
        adm8 = _data(c["admissao"])
        meses = set(d["meses"])
        # continuidade conta do 1º PAGAMENTO, não da admissão: nomeado no fim do mês só recebe no mês seguinte
        # (1ª versão contava da admissão e marcou 599 de 735 com "interrupção" — era o atraso normal da folha)
        lac = continuidade(meses, d["primeira"], d["ultima"], base)
        p = por.setdefault(nn, {"nn": nn, "nome": c["nome"], "vinculos": [], "cands": cands.get(nn, []),
                                "mats_nome": mats_nome.get(nn, 0)})
        p["vinculos"].append({
            "matricula": mat, "cargo": " / ".join(com), "lotacao": c["lotacao"], "orgao": d["orgao"],
            "admissao": c["admissao"], "adm8": adm8, "exoneracao": exo, "exo8": _data(exo),
            "primeira": d["primeira"], "ultima": d["ultima"], "meses": len(meses), "lacunas": lac,
            "em_curso": d["ultima"] == ultima and not exo,
            "bruto": sum(d["meses"].values()),
            "bruto_paes": sum(v for k, v in d["meses"].items() if k <= PAES_ULTIMA_COMP),
            "bruto_cav": sum(v for k, v in d["meses"].items() if k > PAES_ULTIMA_COMP),
            "na_transicao": PAES_ULTIMA_COMP in meses and any(k > PAES_ULTIMA_COMP for k in meses),
            # toda a gestão Paes: já nomeado em 01/2021 (1º pagamento até 02/2021) e sem interrupção até 03/2026
            "paes_inteiro": bool(adm8) and adm8 <= INICIO + "31" and d["primeira"] <= _prox(INICIO)
                            and PAES_ULTIMA_COMP in meses
                            and not continuidade(meses, d["primeira"], PAES_ULTIMA_COMP, base),
            "gestao": ("anterior a 2021" if adm8 and adm8 < INICIO + "01" else
                       "Cavaliere" if adm8 and adm8 >= PAES_FIM else "Paes" if adm8 else "admissão não publicada"),
        })
    cob = {"matriculas": len(pr), "nomes": len({k[0] for k in pr}), "consultas": len(alvo),
           "consultas_feitas": len(alvo & consultadas), "sem_cargo_no_portal": sem_cargo,
           "meses_base": sorted(base)}
    return list(por.values()), cob


_PARTICULAS = {"da", "de", "do", "dos", "das", "e", "d"}


def _e(x) -> str:
    return html.escape(str(x or ""))


def _comp(c: str | None) -> str:
    return f"{c[4:6]}/{c[:4]}" if c and len(c) == 6 else "—"


def _d8(d: str | None) -> str:
    return f"{d[6:]}/{d[4:6]}/{d[:4]}" if d and len(d) == 8 else "—"


def _brl(v) -> str:
    return "R$ " + f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _int(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def _confianca(nn: str, freq_top: set[str], cands: list[dict], mats_nome: int) -> tuple[str, list[str]]:
    """Confiança de que o COMISSIONADO é o mesmo CANDIDATO (sem CPF). Critérios mensuráveis e declarados:
    nome de 4+ palavras significativas = ALTA; 3 palavras com no máximo 1 entre as 200 mais comuns da folha =
    MÉDIA; resto = BAIXA. Rebaixa um nível se o nome tem candidaturas em 3+ cidades (homônimos no TSE) ou 3+
    matrículas na folha da janela (homônimos na Prefeitura)."""
    sig = [w for w in nn.split() if w.lower() not in _PARTICULAS]
    comuns = sum(1 for w in sig if w in freq_top)
    nivel = 2 if len(sig) >= 4 else 1 if (len(sig) == 3 and comuns < 2) else 0
    motivos = []
    if len({c["cidade"] for c in cands}) >= 3:
        motivos.append("candidaturas em 3+ cidades (homônimo provável no TSE)")
    if mats_nome >= 3:
        motivos.append(f"{mats_nome} matrículas com este nome na folha")
    if motivos:
        nivel = max(0, nivel - 1)
    return ("BAIXA", "MÉDIA", "ALTA")[nivel], motivos


def _meses_entre(a: date, b8: str) -> int | None:
    if not b8:
        return None
    b = date(int(b8[:4]), int(b8[4:6]), int(b8[6:]))
    return (b.year - a.year) * 12 + (b.month - a.month)


def _cand_txt(c: dict, adm8: str) -> str:
    rel = ""
    if adm8 and c["ano"] in ELEICAO:
        dm = _meses_entre(ELEICAO[c["ano"]], adm8)
        if dm is not None:
            rel = (f" · nomeado {dm} meses depois" if dm > 0 else
                   f" · eleição {-dm} meses depois da nomeação" if dm < 0 else " · nomeado no mês da eleição")
    res = f" — <b>{_e(c['resultado'])}</b>" if c.get("resultado") else ""
    fora = " <span class='flag'>outra cidade</span>" if c["outra"] else ""
    urna = f" «{_e(c['urna'])}»" if c.get("urna") else ""
    return (f"{c['ano']} · {_e((c['cargo'] or '').title())} · {_e((c['cidade'] or '').title())} · "
            f"{_e(c['partido'] or '—')}{urna}{res}{fora}{rel}")


def _vinc_txt(v: dict, ultima: str) -> str:
    if v["exoneracao"]:
        fim = f"<b>{_e(v['exoneracao'])}</b> (exoneração publicada)"
    elif v["em_curso"]:
        fim = f"<b>em curso</b> (na folha de {_comp(ultima)})"
    else:
        fim = f"<b>saída da folha em {_comp(v['ultima'])}</b> (data do ato não publicada)"
    if v["lacunas"]:
        cont = f"<span class='flag'>meses sem pagamento: {_e(_faixas(v['lacunas']))}</span>"
    elif v["paes_inteiro"]:
        cont = "<span class='flag' style='background:#1f4e79;color:#fff'>contínuo em TODA a gestão Paes</span>"
    else:
        cont = "pago em todos os meses do período"
    trans = " · <span class='flag'>atravessou a transição Paes→Cavaliere</span>" if v["na_transicao"] else ""
    return (f"<b>{_e(v['cargo'])}</b> · mat. {_e(v['matricula'])}<br>{_e(v['orgao'] or '')}"
            f"{(' · ' + _e(v['lotacao'])) if v['lotacao'] else ''}"
            f"<br>Início: <b>{_e(v['admissao'] or '—')}</b> (nomeação na gestão {_e(v['gestao'])}) · Fim: {fim}"
            f"<br>Folha {_comp(v['primeira'])}–{_comp(v['ultima'])}: {v['meses']} meses · {cont}{trans}"
            f"<br>Bruto {_brl(v['bruto'])} (Paes {_brl(v['bruto_paes'])} · Cavaliere {_brl(v['bruto_cav'])})")


def _tabela(cab: list[str], linhas: list[list], alinhar_dir: set[int] = frozenset()) -> str:
    th = "".join(f"<th{' style=\"text-align:right\"' if i in alinhar_dir else ''}>{c}</th>" for i, c in enumerate(cab))
    tr = "".join("<tr>" + "".join(f"<td{' style=\"text-align:right\"' if i in alinhar_dir else ''}>{v}</td>"
                                  for i, v in enumerate(ln)) + "</tr>" for ln in linhas)
    return f"<table><tr>{th}</tr>{tr}</table>"


def _barra(k: int, maximo: int) -> str:
    return (f"<span style='display:inline-block;height:9px;background:#9b1c1c;"
            f"width:{max(2, round(240 * k / max(1, maximo)))}px'></span>")


def montar_ctx(db_path=None) -> dict:  # noqa: C901 — um relatório, lido de cima a baixo
    from collections import Counter, defaultdict
    con = _db.conectar(db_path)
    try:
        ps, cob = pessoas(con)
        ultima = con.execute("SELECT MAX(competencia) FROM pcrj_folha_pref").fetchone()[0]
        cont = Counter(w for (n,) in con.execute("SELECT DISTINCT nome_norm FROM pcrj_folha_pref WHERE competencia=?",
                                                 (ultima,)) for w in set((n or "").split())
                       if w.lower() not in _PARTICULAS)
        freq_top = {w for w, _ in cont.most_common(200)}
        anos_tse = sorted({r[0] for r in con.execute("SELECT DISTINCT ano FROM tse_candidatura")})
    finally:
        con.close()
    ordem_conf = ("ALTA", "MÉDIA", "BAIXA")
    conf_n = Counter()
    por_orgao = defaultdict(lambda: {"pessoas": set(), "bruto": 0.0})
    por_partido = defaultdict(set)
    por_cidade = defaultdict(set)
    adm_por_ano = Counter()
    adm_por_gestao = Counter()
    eleitos, fora, pos_eleicao, paes_inteiro, com_lacuna, transicao = [], [], [], [], [], []
    tot = {"bruto": 0.0, "paes": 0.0, "cav": 0.0}
    for p in ps:
        conf, motivos = _confianca(p["nn"], freq_top, p["cands"], p["mats_nome"])
        p["conf"] = conf
        conf_n[conf] += 1
        vs = sorted(p["vinculos"], key=lambda v: v["adm8"] or v["primeira"])
        p["vinculos"] = vs
        p["adm8"] = min((v["adm8"] for v in vs if v["adm8"]), default="")
        for v in vs:
            tot["bruto"] += v["bruto"]
            tot["paes"] += v["bruto_paes"]
            tot["cav"] += v["bruto_cav"]
            o = por_orgao[v["orgao"] or v["lotacao"] or "—"]
            o["pessoas"].add(p["nn"])
            o["bruto"] += v["bruto"]
            if v["adm8"]:
                adm_por_ano[v["adm8"][:4]] += 1
            adm_por_gestao[v["gestao"]] += 1
        if any(v["paes_inteiro"] for v in vs):
            paes_inteiro.append(p)
        if any(v["lacunas"] for v in vs):
            com_lacuna.append(p)
        if any(v["na_transicao"] for v in vs):
            transicao.append(p)
        rec = p["cands"][-1] if p["cands"] else None
        if rec:
            por_partido[rec["partido"] or "—"].add(p["nn"])
        if conf != "BAIXA" and any(c["outra"] for c in p["cands"]):
            fora.append(p)
            for c in p["cands"]:
                if c["outra"]:
                    por_cidade[(c["cidade"] or "?").title()].add(p["nome"])
        if any(c["eleito"] for c in p["cands"]):
            eleitos.append(p)
        # nomeado até 6 meses depois de uma eleição em que NÃO se elegeu
        for v in vs:
            for c in p["cands"]:
                dm = _meses_entre(ELEICAO[c["ano"]], v["adm8"]) if c["ano"] in ELEICAO and v["adm8"] else None
                if dm is not None and 0 <= dm <= 6 and not c["eleito"] and v["adm8"] >= INICIO + "01":
                    pos_eleicao.append((p, v, c, dm))
        # grupo (capítulos nominais)
        ativo_agora = any(v["em_curso"] for v in vs)
        saida = max(v["ultima"] for v in vs)
        p["saida"] = None if ativo_agora else saida
        exo_j = sorted(v["exo8"] for v in vs if v["exo8"] and DESINC_INI <= v["exo8"] <= DESINC_FIM)
        p["exo_desinc"] = exo_j[-1] if exo_j else None
        c26 = [c for c in p["cands"] if c["ano"] == 2026]
        p["cand2026"] = c26
        if exo_j or (not ativo_agora and DESINC_INI[:6] <= saida <= DESINC_FIM[:6]):
            p["grupo"] = "desinc"
        elif ativo_agora:
            p["grupo"] = "ativo"
        else:
            p["grupo"] = "demais"
        flags = f"<span class='flag' style='background:#eee;color:#555'>confiança {conf}</span>"
        if motivos:
            flags += f"<br><span class='dim'>{_e('; '.join(motivos))}</span>"
        if c26:
            flags += ("<br><span class='flag' style='background:#9b1c1c;color:#fff'>CANDIDATO EM 2026: "
                      + _e("; ".join(f"{(c['cargo'] or '').title()} ({c['partido'] or '—'})" for c in c26)) + "</span>")
        if p["grupo"] == "desinc":
            flags += (f"<br><span class='flag'>exonerado em {_d8(p['exo_desinc'])}"
                      + (" — dentro do prazo" if p["exo_desinc"] <= DESINC_PRAZO else " — APÓS o prazo de 04/07") + "</span>"
                      if p["exo_desinc"] else
                      f"<br><span class='flag'>saiu da folha em {_comp(saida)} (data do ato não publicada)</span>")
        p["linha"] = [f"<b>{_e(p['nome'])}</b><br>{flags}", "<br><br>".join(_vinc_txt(v, ultima) for v in vs),
                      "<br>".join(_cand_txt(c, p["adm8"]) for c in p["cands"]) or "—"]
    n = len(ps)
    pct = round(100 * (conf_n["ALTA"] + conf_n["MÉDIA"]) / max(1, n))

    def _cnt(lst):
        return sum(1 for p in lst if p["conf"] != "BAIXA")

    def _ord(lst, cand26_primeiro=False):
        return sorted(lst, key=lambda p: ((not p["cand2026"]) if cand26_primeiro else 0,
                                          ordem_conf.index(p["conf"]), p["nome"]))

    grupos = {k: [p for p in ps if p["grupo"] == k] for k in ("desinc", "ativo", "demais")}
    cand26 = [p for p in ps if p["cand2026"]]
    c26_ativos = [p for p in cand26 if p["grupo"] == "ativo"]
    c26_desinc = [p for p in cand26 if p["grupo"] == "desinc"]
    c26_antes = [p for p in cand26 if p["grupo"] == "demais"]
    nomeados_paes = [p for p in ps if any(v["gestao"] == "Paes" for v in p["vinculos"])]
    nomeados_cav = [p for p in ps if any(v["gestao"] == "Cavaliere" for v in p["vinculos"])]
    herdados = [p for p in ps if any(v["gestao"] == "anterior a 2021" for v in p["vinculos"])]
    cab = ["Nome · confiança", "Vínculo(s) comissionado(s): início, fim, continuidade, remuneração",
           "Candidatura(s) — ano · cargo · cidade · partido «urna» — resultado · distância da nomeação"]
    alerta = "style='border-left:4px solid #9b1c1c;background:#fbeaea;padding:8px 12px;margin:8px 0'"
    info = "style='border-left:4px solid #1f4e79;background:#eef3f9;padding:8px 12px;margin:8px 0'"

    sumario = _tabela(["Indicador", "Total", "Confiança ALTA/MÉDIA"], [
        [f"Comissionados na folha 01/2021–{_comp(ultima)} que já foram candidatos", _int(n), _int(_cnt(ps))],
        ["… nomeados na gestão Paes (01/01/2021–19/03/2026)", _int(len(nomeados_paes)), _int(_cnt(nomeados_paes))],
        ["… nomeados na gestão Cavaliere (desde 20/03/2026)", _int(len(nomeados_cav)), _int(_cnt(nomeados_cav))],
        ["… nomeados antes de 2021 e mantidos", _int(len(herdados)), _int(_cnt(herdados))],
        ["… no cargo durante TODA a gestão Paes (01/2021–03/2026, sem interrupção)", _int(len(paes_inteiro)),
         _int(_cnt(paes_inteiro))],
        ["… atravessaram a transição Paes → Cavaliere", _int(len(transicao)), _int(_cnt(transicao))],
        ["… com mês(es) sem pagamento no meio do vínculo", _int(len(com_lacuna)), _int(_cnt(com_lacuna))],
        ["… nomeados até 6 meses depois de uma eleição em que não se elegeram",
         _int(len({x[0]['nn'] for x in pos_eleicao})), _int(_cnt(list({x[0]['nn']: x[0] for x in pos_eleicao}.values())))],
        ["… com candidatura registrada em 2026", _int(len(cand26)), _int(_cnt(cand26))],
        ["… saíram na janela da desincompatibilização (06–07/2026)", _int(len(grupos["desinc"])), _int(_cnt(grupos["desinc"]))],
        [f"… continuam nomeados ({_comp(ultima)})", _int(len(grupos["ativo"])), _int(_cnt(grupos["ativo"]))],
        ["… candidatos em OUTRA cidade do RJ", "—", _int(len(fora))],
        ["… eleitos em alguma candidatura", _int(len(eleitos)), _int(_cnt(eleitos))],
        ["Confiança ALTA · MÉDIA · BAIXA", f"{conf_n['ALTA']} · {conf_n['MÉDIA']} · {conf_n['BAIXA']}", "—"],
        [f"Remuneração bruta desses vínculos, 01/2021–{_comp(ultima)} (folha)", _brl(tot["bruto"]), "—"],
        ["… na gestão Paes (competências até 03/2026)", _brl(tot["paes"]), "—"],
        ["… na gestão Cavaliere (competências desde 04/2026)", _brl(tot["cav"]), "—"],
    ], {1, 2})

    anos = sorted(adm_por_ano)
    mx = max(adm_por_ano.values(), default=1)
    gestoes = (
        f"<p {info}><b>Gestões.</b> Eduardo Paes tomou posse em 01/01/2021 (reeleito em 2024) e renunciou em "
        "<b>20/03/2026</b> para disputar o Governo do Estado; o vice Eduardo Cavaliere assumiu no mesmo dia. A "
        "competência 03/2026 é contada na gestão Paes.</p>"
        + _tabela(["Recorte", "Vínculos", ""], [[_e(k), _int(v), ""] for k, v in adm_por_gestao.most_common()], {1})
        + "<p><b>Nomeações por ano (data de admissão no cargo comissionado)</b> — anos eleitorais em negrito:</p>"
        + _tabela(["Ano", "Nomeações", ""],
                  [[f"<b>{a}</b>" if int(a) in ELEICAO else a, _int(adm_por_ano[a]), _barra(adm_por_ano[a], mx)]
                   for a in anos], {1}))

    lista_pos = sorted(pos_eleicao, key=lambda x: (x[3], ordem_conf.index(x[0]["conf"]), x[0]["nome"]))
    cap_pos = (
        f"<p {info}>Pessoas nomeadas para cargo em comissão <b>até 6 meses depois</b> de uma eleição em que "
        "concorreram e <b>não</b> se elegeram (suplentes e não eleitos). É um padrão a ser explicado pela "
        "administração, não uma irregularidade em si.</p>"
        + _tabela(["Nome · confiança", "Eleição (resultado)", "Nomeação", "Meses depois", "Cargo · órgão"],
                  [[f"{_e(p['nome'])}<br><span class='dim'>{p['conf']}</span>",
                    f"{c['ano']} · {_e((c['cargo'] or '').title())} · {_e((c['cidade'] or '').title())} "
                    f"({_e(c['partido'] or '—')}) — {_e(c['resultado'] or '—')}",
                    _e(v["admissao"]), str(dm), f"{_e(v['cargo'])} · {_e(v['orgao'] or '')}"]
                   for p, v, c, dm in lista_pos], {3}))

    cap_cont = (
        f"<p {info}>Continuidade medida mês a mês na folha em bloco. <b>Contínuo em toda a gestão Paes</b> = presente "
        "desde o 1º pagamento (nomeados até 01/2021) até 03/2026, sem mês vazio. <b>Mês sem pagamento</b> = mês em que a "
        "base tem folha e a matrícula não aparece — conferido por amostra no portal de remuneração, que também não "
        "traz pagamento nesses meses. Pode ser exoneração e renomeação na mesma matrícula, licença sem vencimento ou "
        "pagamento acumulado no mês seguinte; não é, por si, irregularidade.</p>"
        + "<p><b>A. No cargo durante toda a gestão Paes</b></p>"
        + _tabela(["Nome · confiança", "Cargo · órgão", "Início", "Situação atual"],
                  [[f"{_e(p['nome'])}<br><span class='dim'>{p['conf']}</span>",
                    "<br>".join(f"{_e(v['cargo'])} · {_e(v['orgao'] or '')}" for v in p["vinculos"] if v["paes_inteiro"]),
                    "<br>".join(_e(v["admissao"] or "—") for v in p["vinculos"] if v["paes_inteiro"]),
                    "em curso" if any(v["em_curso"] for v in p["vinculos"]) else f"saiu em {_comp(p['saida'])}"]
                   for p in _ord(paes_inteiro)])
        + "<p><b>B. Vínculos com mês sem pagamento</b></p>"
        + _tabela(["Nome · confiança", "Cargo · órgão", "Período na folha", "Meses sem a matrícula"],
                  [[f"{_e(p['nome'])}<br><span class='dim'>{p['conf']}</span>",
                    "<br>".join(f"{_e(v['cargo'])} · {_e(v['orgao'] or '')}" for v in p["vinculos"] if v["lacunas"]),
                    "<br>".join(f"{_comp(v['primeira'])}–{_comp(v['ultima'])}" for v in p["vinculos"] if v["lacunas"]),
                    "<br>".join(_e(_faixas(v["lacunas"])) for v in p["vinculos"] if v["lacunas"])]
                   for p in _ord(com_lacuna)]))

    if 2026 in anos_tse:
        cap26 = (
            f"<p {alerta}><b>Candidatos de 2026 que ocuparam cargo em comissão na Prefeitura.</b> Prazo de "
            "desincompatibilização: <b>04/07/2026</b> (LC 64/1990, art. 1º, II, <i>l</i>; Súmula TSE nº 54 — exige "
            "<b>exoneração</b>, não mero afastamento). Quem segue nomeado depois do prazo expõe o registro de "
            "candidatura a impugnação. No arquivo do TSE usado, a <b>situação do registro de 2026 ainda não foi "
            "publicada</b> (campo \"#NE\" em todas as 2.055 candidaturas do RJ): trata-se de <b>pedido de registro</b>; "
            "deferimento, indeferimento ou renúncia precisam ser conferidos no DivulgaCandContas.</p>"
            + _tabela(["Situação", "Pessoas", "Confiança ALTA/MÉDIA"], [
                [f"<b>Continuam nomeados em {_comp(ultima)}</b>", _int(len(c26_ativos)), _int(_cnt(c26_ativos))],
                ["Saíram na janela 06–07/2026", _int(len(c26_desinc)), _int(_cnt(c26_desinc))],
                ["Saíram antes de 06/2026", _int(len(c26_antes)), _int(_cnt(c26_antes))]], {1, 2})
            + _tabela(cab, [p["linha"] for p in sorted(cand26, key=lambda p: (("ativo", "desinc", "demais").index(p["grupo"]),
                                                                        ordem_conf.index(p["conf"]), p["nome"]))]))
    else:
        cap26 = "<p>Lista de candidatos de 2026 do TSE ainda não importada — cruzamento INDISPONÍVEL.</p>"

    saidas_mes = Counter(p["saida"] for p in ps if p.get("saida") and p["saida"] >= "202501")
    mxs = max(saidas_mes.values(), default=1)
    jun = [p for p in grupos["desinc"] if (p["exo_desinc"] or p["saida"] or "")[:6] == DESINC_INI[:6]]
    jul = [p for p in grupos["desinc"] if p not in jun]
    cap_desinc = (
        f"<p {alerta}><b>Prazo legal.</b> Eleições gerais de 2026: 1º turno em <b>04/10/2026</b>. O ocupante de cargo em "
        "comissão que pretende concorrer deve ser <b>exonerado</b> até <b>três meses antes do pleito — 04/07/2026</b> "
        "(LC 64/1990, art. 1º, II, <i>l</i>; Súmula TSE nº 54: a desincompatibilização do comissionado \"pressupõe a "
        "exoneração do cargo comissionado, e não apenas seu afastamento de fato\"). O servidor efetivo, ao contrário, "
        "apenas se afasta, com vencimentos, e pode seguir afastado até 10 dias após o 2º turno (redação da LC 219/2025). "
        "Para concorrer a outro cargo, o Prefeito renuncia até 6 meses antes (art. 1º, § 1º): Eduardo Paes renunciou "
        "em 20/03/2026, antes de 04/04/2026. Aqui: quem saiu da folha em "
        "<b>06/2026 ou 07/2026</b> (ou com exoneração publicada nesse período). Os candidatos de 2026 confirmados no TSE "
        "estão marcados em vermelho e no topo.</p>"
        + _tabela(["Recorte", "Pessoas", "Confiança ALTA/MÉDIA"], [
            ["Saíram em 06/2026 (mês anterior ao prazo)", _int(len(jun)), _int(_cnt(jun))],
            ["Saíram em 07/2026 (mês do prazo — até 04/07 é tempestivo)", _int(len(jul)), _int(_cnt(jul))]], {1, 2})
        + "<p><b>Saídas da folha por mês, 2025–2026</b> — o pico antes do prazo é o padrão da desincompatibilização:</p>"
        + _tabela(["Última competência na folha", "Pessoas que saíram", ""],
                  [[_comp(m), _int(k), _barra(k, mxs)] for m, k in sorted(saidas_mes.items())], {1})
        + _tabela(cab, [p["linha"] for p in _ord(grupos["desinc"], True)]))
    cap_ativo = (
        f"<p {alerta}><b>Continuam nomeados</b> na folha de {_comp(ultima)}, sem exoneração publicada. "
        + (f"<b>{_int(len(c26_ativos))} deles têm candidatura registrada em 2026</b> — marcados em vermelho e no topo."
           if c26_ativos else "Nenhum tem candidatura em 2026 na lista do TSE-RJ importada." if 2026 in anos_tse else "")
        + "</p>" + _tabela(cab, [p["linha"] for p in _ord(grupos["ativo"], True)]))
    cap_demais = _tabela(cab, [p["linha"] for p in _ord(grupos["demais"], True)])

    orgaos = _tabela(["Órgão (folha, última competência)", "Pessoas", "Remuneração bruta 2021–2026"],
                     [[_e(o), _int(len(d["pessoas"])), _brl(d["bruto"])]
                      for o, d in sorted(por_orgao.items(), key=lambda x: (-len(x[1]["pessoas"]), x[0]))], {1, 2})
    partidos = _tabela(["Partido (candidatura mais recente)", "Pessoas"],
                       [[_e(k), _int(len(v))] for k, v in sorted(por_partido.items(), key=lambda x: (-len(x[1]), x[0]))],
                       {1})
    cidades = _tabela(["Cidade da candidatura", "Pessoas", "Nomes"],
                      [[_e(c), _int(len(ns)), _e("; ".join(sorted(ns)))]
                       for c, ns in sorted(por_cidade.items(), key=lambda x: (-len(x[1]), x[0]))], {1})
    eleit = _tabela(["Nome", "Confiança", "Eleição(ões) com resultado ELEITO", "Cargo comissionado"],
                    [[_e(p["nome"]), p["conf"],
                      "<br>".join(f"{c['ano']} · {_e((c['cargo'] or '').title())} · {_e((c['cidade'] or '').title())} "
                                  f"({_e(c['partido'] or '—')}) — {_e(c['resultado'])}" for c in p["cands"] if c["eleito"]),
                      "<br>".join(f"{_e(v['cargo'])} · {_e(v['orgao'] or '')} ({_e(v['admissao'] or '—')} → "
                                  f"{'em curso' if v['em_curso'] else _e(v['exoneracao']) or 'saída ' + _comp(v['ultima'])})"
                                  for v in p["vinculos"])]
                     for p in _ord(eleitos)])
    pend = cob["consultas"] - cob["consultas_feitas"]
    faltam_meses = [c for c in (f"{a}{m:02d}" for a in range(2021, 2027) for m in range(1, 13))
                    if INICIO <= c <= ultima and c not in set(cob["meses_base"])]
    metodo = (
        f"<p><b>Universo.</b> Todas as candidaturas do Estado do Rio de Janeiro nos anos {', '.join(map(str, anos_tse))} "
        "(TSE, dados abertos, arquivo do RJ) cruzadas por <b>nome</b> com a folha inteira da Prefeitura "
        "(tabela <code>tse_candidatura</code>). Dessas, as que aparecem na folha mensal em bloco "
        f"(contrachequedoc.rio.gov.br) entre 01/2021 e {_comp(ultima)}: {_int(cob['nomes'])} nomes, "
        f"{_int(cob['matriculas'])} matrículas."
        + (f" <b>Competências ausentes na base: {_e(_faixas(faltam_meses))}</b> — não contam como interrupção." if faltam_meses
           else " Todas as competências do período estão na base.") + "</p>"
        "<p><b>Cargo, início e fim.</b> O cargo, a data de admissão e a de exoneração de cada matrícula vêm do portal de "
        "remuneração (contrachequeapi.rio.gov.br), consultado na <b>última competência</b> em que a matrícula aparece: "
        f"{_int(cob['consultas_feitas'])} de {_int(cob['consultas'])} consultas concluídas"
        + (f" — <b>{_int(pend)} INDISPONÍVEIS</b> (o portal não respondeu)" if pend else "")
        + f"; {_int(cob['sem_cargo_no_portal'])} matrícula(s) sem linha no portal para o nome exato. O portal raramente "
        "publica a exoneração no último mês pago: sem data, o fim é a <b>saída da folha</b>. Exonerações publicadas em "
        "varreduras anteriores do portal completam a data quando existem.</p>"
        "<p><b>Continuidade.</b> Mês a mês na folha em bloco, do 1º pagamento à última competência (o 1º pagamento costuma "
        "vir no mês seguinte à nomeação).</p>"
        "<p><b>Comissionado</b> = classificador canônico da casa: cargo iniciado por <i>ESPECIAL</i>, <i>ASSESSOR</i> ou "
        "<i>ASSISTENTE ESPECIAL</i>, símbolo <i>DAS</i>/<i>DAI</i> ou contendo <i>COMISS</i>; vetados Educação Especial, "
        "estágios e 'especialidade'. Efetivos ficam fora, inclusive com função gratificada na mesma matrícula. Cargos "
        "eletivos (Prefeito, Vice) aparecem na folha como <i>ESPECIAL</i> e estão incluídos.</p>"
        "<p><b>Identidade.</b> O TSE publica CPF mascarado e a folha não traz CPF: casamento por <b>nome</b>. Confiança "
        "ALTA: 4+ palavras significativas; MÉDIA: 3 palavras, no máximo 1 entre as 200 mais comuns da folha; BAIXA: o "
        "resto; rebaixada com candidaturas do nome em 3+ cidades ou 3+ matrículas do nome na folha.</p>"
        "<p><b>Limitações.</b> Remuneração = bruto da folha em bloco (inclui 13º e férias), não o custo total; 07/2026 "
        "saiu na base majoritariamente como adiantamento do 13º. Organizações Sociais não entram (sem nomes na fonte).</p>")
    return {
        "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
        "titulo": "Comissionados da Prefeitura do Rio que já foram candidatos — gestões Paes e Cavaliere",
        "subtitulo": f"Cargos em comissão 01/2021–{_comp(ultima)} × candidaturas TSE-RJ "
                     f"{min(anos_tse)}–{max(anos_tse)}: início, fim e continuidade de cada nomeação",
        "metodologia": "Folha em bloco + portal de remuneração × TSE-RJ (casamento nominal; indício)",
        "score": pct, "rotulo_score": "Identificação confiável (% alta+média)", "faixa": "MÉDIO",
        "top_flags": [f"{_int(n)} comissionados candidatos", f"{_int(len(cand26))} candidatos em 2026",
                      f"{_int(len(c26_ativos))} candidatos 2026 ainda nomeados", f"{_int(len(paes_inteiro))} em toda a gestão Paes"],
        "secoes": [
            {"titulo": "1. Sumário executivo", "html": sumario},
            {"titulo": "2. Gestões Paes e Cavaliere — nomeações por gestão e por ano", "html": gestoes},
            {"titulo": f"3. Candidatos de 2026 que ocuparam cargo em comissão ({_int(len(cand26))})", "html": cap26},
            {"titulo": f"4. Exonerados na desincompatibilização eleitoral de 2026 ({_int(len(grupos['desinc']))})",
             "html": cap_desinc},
            {"titulo": f"5. Continuam nomeados até {_comp(ultima)} ({_int(len(grupos['ativo']))})", "html": cap_ativo},
            {"titulo": f"6. Nomeados logo após perder a eleição (≤ 6 meses) ({_int(len(lista_pos))} nomeações)",
             "html": cap_pos},
            {"titulo": f"7. Continuidade dos vínculos ({_int(len(paes_inteiro))} em toda a gestão Paes · "
                       f"{_int(len(com_lacuna))} com mês sem pagamento)", "html": cap_cont},
            {"titulo": f"8. Demais — saíram em outros momentos ({_int(len(grupos['demais']))})", "html": cap_demais},
            {"titulo": f"9. Distribuição por órgão ({len(por_orgao)})", "html": orgaos},
            {"titulo": "10. Distribuição por partido (candidatura mais recente)", "html": partidos},
            {"titulo": f"11. Candidatos em outras cidades do RJ ({len(por_cidade)} cidades · confiança alta/média)",
             "html": cidades},
            {"titulo": f"12. Eleitos ({len(eleitos)})", "html": eleit},
            {"titulo": "13. Método, cobertura e limitações", "html": metodo},
        ],
        "proveniencia": [
            {"dado": "Folha mensal em bloco", "estado": "REAL", "fonte": "contrachequedoc.rio.gov.br",
             "data": f"01/2021–{_comp(ultima)}"},
            {"dado": "Cargo, admissão, exoneração", "estado": "REAL" if not pend else "PARCIAL",
             "fonte": "contrachequeapi.rio.gov.br", "data": datetime.now().strftime("%d/%m/%Y")},
            {"dado": f"Candidaturas RJ {min(anos_tse)}–{max(anos_tse)}", "estado": "REAL", "fonte": "TSE — dados abertos",
             "data": "jul–set/2026"}],
        "ressalva": "Indícios por nome para apuração por CPF; presunção de legitimidade dos atos de nomeação. "
                    "Ter sido candidato não é irregularidade — o relatório serve ao controle de nomeações políticas.",
        "_n": n, "_conf": dict(conf_n), "_pend": pend,
    }


async def gerar(db_path=None) -> dict:
    from pathlib import Path

    from compliance_agent.reporting.render_html import html_to_pdf, render_html
    ctx = montar_ctx(db_path)
    base = Path(__file__).resolve().parents[2] / "reports"
    base.mkdir(exist_ok=True)
    pdf = str(base / f"pcrj_comissionados_candidatos_gestao_{datetime.now().date()}.pdf")
    await html_to_pdf(render_html(ctx), pdf)
    return {"pdf": pdf, "pessoas": ctx["_n"], "confianca": ctx["_conf"], "consultas_pendentes": ctx["_pend"]}


if __name__ == "__main__":
    import sys
    if "--pdf" in sys.argv:
        import asyncio
        print(asyncio.run(gerar()))
    else:
        print(coletar())
