# -*- coding: utf-8 -*-
"""Comissionados da Prefeitura do Rio em 2025–2026 que já foram CANDIDATOS (TSE-RJ 2012–2024).

Universo: pessoas de `tse_candidatura` (todas as candidaturas do RJ 2012–2024 já casadas por NOME com a folha
inteira da Prefeitura) que aparecem na folha em bloco (`pcrj_folha_pref`) de 01/2025 em diante. A folha não traz
cargo — o CARGO de cada matrícula vem do portal de remuneração (contrachequeapi), consultado na ÚLTIMA competência
em que a matrícula aparece na janela, e fica em cache em `pcrj_cargo_portal` (a coleta é retomável).

Sem CPF → o casamento servidor × candidato é por nome (indício); a confiança é declarada por pessoa.
"""
from __future__ import annotations

import html
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.nomes import normalizar

INICIO = "202501"
# Eleições gerais 2026: 1º turno 04/10/2026 → comissionado exonerado até 04/07/2026 (LC 64/90, art. 1º, II, l; Súm. TSE 54)
DESINC_INI, DESINC_PRAZO, DESINC_FIM = "20260601", "20260704", "20260731"
_NUM = "CAST(replace(replace(remun_bruta,'.',''),',','.') AS REAL)"


def _criar_tabelas(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS pcrj_cargo_portal (
        nome_norm TEXT, competencia TEXT, matricula TEXT, nome TEXT, cargo TEXT, lotacao TEXT,
        admissao TEXT, exoneracao TEXT, folha TEXT, vantagens TEXT, coletado_em TEXT,
        PRIMARY KEY (nome_norm, competencia, matricula, folha))""")
    con.execute("""CREATE TABLE IF NOT EXISTS pcrj_cargo_portal_consulta (
        nome_norm TEXT, competencia TEXT, n INTEGER, coletado_em TEXT, PRIMARY KEY (nome_norm, competencia))""")


def pares(con) -> dict[tuple[str, str], dict]:
    """{(nome_norm, matrícula sem zeros): {primeira, ultima, meses, bruto, orgao}} na janela, só de quem foi candidato."""
    con.execute("CREATE TEMP TABLE IF NOT EXISTS _cand AS SELECT DISTINCT nome_norm FROM tse_candidatura")
    out: dict[tuple[str, str], dict] = {}
    for nn, mat, comp, orgao, sigla, bruto in con.execute(
            f"SELECT f.nome_norm, ltrim(f.matricula,'0'), competencia, orgao, sigla_ua, {_NUM} "
            "FROM pcrj_folha_pref f JOIN _cand USING(nome_norm) WHERE competencia >= ?", (INICIO,)):
        d = out.setdefault((nn, mat), {"primeira": comp, "ultima": comp, "meses": set(), "bruto": 0.0, "orgao": None})
        d["primeira"] = min(d["primeira"], comp)
        if comp >= d["ultima"]:
            d["ultima"] = comp
            d["orgao"] = orgao or sigla or d["orgao"]
        d["meses"].add(comp)
        d["bruto"] += bruto or 0.0
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
    nomes = {nn: nome for nn, nome in con.execute(
        "SELECT nome_norm, MAX(nome) FROM pcrj_folha_pref WHERE competencia=? GROUP BY nome_norm", ("202608",))}
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


def pessoas(con) -> tuple[list[dict], dict]:
    """Uma entrada por pessoa com ≥1 matrícula COMISSIONADA na janela; + cobertura da coleta."""
    pr = pares(con)
    cargos: dict[tuple[str, str], dict] = {}
    for nn, comp, mat, nome, cargo, lot, adm, exo, folha in con.execute(
            "SELECT nome_norm, competencia, matricula, nome, cargo, lotacao, admissao, exoneracao, folha "
            "FROM pcrj_cargo_portal"):
        d = pr.get((nn, mat))
        if d is None or comp != d["ultima"]:
            continue
        c = cargos.setdefault((nn, mat), {"nome": nome, "cargos": set(), "lotacao": lot, "admissao": adm,
                                          "exoneracao": exo})
        if cargo:
            c["cargos"].add(cargo)
        c["exoneracao"] = c["exoneracao"] or exo
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
    por: dict[str, dict] = {}
    for (nn, mat), c in cargos.items():
        com = sorted(x for x in c["cargos"] if _cargo_comissionado(x))
        if not com:
            continue
        d = pr[(nn, mat)]
        p = por.setdefault(nn, {"nn": nn, "nome": c["nome"], "vinculos": [], "cands": cands.get(nn, []),
                                "mats_nome": mats_nome.get(nn, 0)})
        p["vinculos"].append({"matricula": mat, "cargo": " / ".join(com), "lotacao": c["lotacao"],
                              "orgao": d["orgao"], "admissao": c["admissao"], "exoneracao": c["exoneracao"],
                              "primeira": d["primeira"], "ultima": d["ultima"], "meses": len(d["meses"]),
                              "bruto": d["bruto"]})
    cob = {"matriculas": len(pr), "nomes": len({k[0] for k in pr}), "consultas": len(alvo),
           "consultas_feitas": len(alvo & consultadas), "sem_cargo_no_portal": sem_cargo}
    return list(por.values()), cob


_PARTICULAS = {"da", "de", "do", "dos", "das", "e", "d"}


def _e(x) -> str:
    return html.escape(str(x or ""))


def _comp(c: str | None) -> str:
    return f"{c[4:6]}/{c[:4]}" if c and len(c) == 6 else "—"


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


def _cand_txt(c: dict, adm: str) -> str:
    rel = ""
    if adm and c["ano"]:
        a = int(adm[:4])
        rel = " · antes da nomeação" if c["ano"] < a else " · depois da nomeação" if c["ano"] > a else " · no ano da nomeação"
    res = f" — <b>{_e(c['resultado'])}</b>" if c.get("resultado") else ""
    fora = " <span class='flag'>outra cidade</span>" if c["outra"] else ""
    urna = f" «{_e(c['urna'])}»" if c.get("urna") else ""
    return (f"{c['ano']} · {_e((c['cargo'] or '').title())} · {_e((c['cidade'] or '').title())} · "
            f"{_e(c['partido'] or '—')}{urna}{res}{fora}{rel}")


def _tabela(cab: list[str], linhas: list[list], alinhar_dir: set[int] = frozenset()) -> str:
    th = "".join(f"<th{' style=\"text-align:right\"' if i in alinhar_dir else ''}>{c}</th>" for i, c in enumerate(cab))
    tr = "".join("<tr>" + "".join(f"<td{' style=\"text-align:right\"' if i in alinhar_dir else ''}>{v}</td>"
                                  for i, v in enumerate(ln)) + "</tr>" for ln in linhas)
    return f"<table><tr>{th}</tr>{tr}</table>"


def montar_ctx(db_path=None) -> dict:
    from collections import Counter, defaultdict
    con = _db.conectar(db_path)
    try:
        ps, cob = pessoas(con)
        ultima = con.execute("SELECT MAX(competencia) FROM pcrj_folha_pref").fetchone()[0]
        cont = Counter(w for (n,) in con.execute("SELECT DISTINCT nome_norm FROM pcrj_folha_pref WHERE competencia=?",
                                                 (ultima,)) for w in set((n or "").split())
                       if w.lower() not in _PARTICULAS)
        freq_top = {w for w, _ in cont.most_common(200)}
    finally:
        con.close()
    conf_n = Counter()
    por_orgao = defaultdict(lambda: {"pessoas": set(), "bruto": 0.0})
    por_partido = defaultdict(set)
    por_cidade = defaultdict(set)
    eleitos, fora, nomeados_janela, ativos, exonerados = [], [], [], [], []
    total_bruto = 0.0
    linhas = []
    for p in ps:
        conf, motivos = _confianca(p["nn"], freq_top, p["cands"], p["mats_nome"])
        p["conf"] = conf
        conf_n[conf] += 1
        adm = min((_data(v["admissao"]) for v in p["vinculos"] if _data(v["admissao"])), default="")
        confiavel = conf != "BAIXA"
        bruto = sum(v["bruto"] for v in p["vinculos"])
        total_bruto += bruto
        for v in p["vinculos"]:
            o = por_orgao[v["orgao"] or v["lotacao"] or "—"]
            o["pessoas"].add(p["nn"])
            o["bruto"] += v["bruto"]
        if any(_data(v["admissao"]) >= INICIO + "01" for v in p["vinculos"]):
            nomeados_janela.append(p)
        if any(v["ultima"] == ultima for v in p["vinculos"]):
            ativos.append(p)
        else:
            exonerados.append(p)
        rec = p["cands"][-1] if p["cands"] else None
        if rec:
            por_partido[rec["partido"] or "—"].add(p["nn"])
        if confiavel and any(c["outra"] for c in p["cands"]):
            fora.append(p)
            for c in p["cands"]:
                if c["outra"]:
                    por_cidade[(c["cidade"] or "?").title()].add(p["nome"])
        if any(c["eleito"] for c in p["cands"]):
            eleitos.append(p)
        vinc = "<br>".join(
            f"<b>{_e(v['cargo'])}</b> · mat. {_e(v['matricula'])}<br>{_e(v['orgao'] or '')}"
            f"{(' · ' + _e(v['lotacao'])) if v['lotacao'] else ''}<br>admissão {_e(v['admissao'] or '—')}"
            f"{(' · exoneração ' + _e(v['exoneracao'])) if v['exoneracao'] else ''}"
            f"<br>folha {_comp(v['primeira'])}–{_comp(v['ultima'])} ({v['meses']} meses) · {_brl(v['bruto'])}"
            for v in sorted(p["vinculos"], key=lambda v: _data(v["admissao"])))
        flags = f"<span class='flag' style='background:#eee;color:#555'>confiança {conf}</span>"
        if motivos:
            flags += f"<br><span class='dim'>{_e('; '.join(motivos))}</span>"
        exo = sorted(_data(v["exoneracao"]) for v in p["vinculos"] if _data(v["exoneracao"]))
        na_janela = [d for d in exo if DESINC_INI <= d <= DESINC_FIM]
        ativo_agora = any(v["ultima"] == ultima and not v["exoneracao"] for v in p["vinculos"])
        # o portal quase nunca publica a data de exoneração no último mês pago (sai depois): a SAÍDA DA FOLHA
        # (última competência do vínculo comissionado) é o sinal observável; a data exata entra quando existe
        saida = max(v["ultima"] for v in p["vinculos"])
        p["saida"] = None if ativo_agora else saida
        if na_janela or (not ativo_agora and DESINC_INI[:6] <= saida <= DESINC_FIM[:6]):
            grupo = "desinc"
            p["exo_desinc"] = na_janela[-1] if na_janela else None
            if na_janela:
                d = na_janela[-1]
                flags += (f"<br><span class='flag'>exonerado em {d[6:]}/{d[4:6]}/{d[:4]}"
                          + (" — dentro do prazo" if d <= DESINC_PRAZO else " — APÓS o prazo de 04/07") + "</span>")
            else:
                flags += f"<br><span class='flag'>saiu da folha em {_comp(saida)} (data do ato não publicada)</span>"
        elif ativo_agora:
            grupo = "ativo"
        else:
            grupo = "demais"
        p["grupo"] = grupo
        linhas.append((("ALTA", "MÉDIA", "BAIXA").index(conf), p["nome"], grupo,
                       [f"<b>{_e(p['nome'])}</b><br>{flags}", vinc,
                        "<br>".join(_cand_txt(c, adm) for c in p["cands"]) or "—"]))
    linhas.sort(key=lambda x: (x[0], x[1]))
    n = len(ps)
    pct = round(100 * (conf_n["ALTA"] + conf_n["MÉDIA"]) / max(1, n))

    def _cnt(lst, so_confiaveis=True):
        return sum(1 for p in lst if not so_confiaveis or p["conf"] != "BAIXA")

    g = {k: [x for x in linhas if x[2] == k] for k in ("desinc", "ativo", "demais")}
    ps_g = {k: [p for p in ps if p["grupo"] == k] for k in g}
    jun = [p for p in ps_g["desinc"] if p["saida"] == DESINC_INI[:6] or (p["exo_desinc"] or "")[:6] == DESINC_INI[:6]]
    jul = [p for p in ps_g["desinc"] if p not in jun]
    saidas_mes = Counter(p["saida"] for p in ps if p.get("saida"))

    sumario = _tabela(["Indicador", "Total", "Confiança ALTA/MÉDIA"], [
        ["Comissionados em 2025–2026 que já foram candidatos", _int(n), _int(_cnt(ps))],
        ["… nomeados (admissão) em 2025 ou 2026", _int(len(nomeados_janela)), _int(_cnt(nomeados_janela))],
        [f"… ainda na folha em {_comp(ultima)}", _int(len(ativos)), _int(_cnt(ativos))],
        ["… saíram da folha dentro da janela", _int(len(exonerados)), _int(_cnt(exonerados))],
        ["… saíram na janela da desincompatibilização (06–07/2026)", _int(len(ps_g["desinc"])),
         _int(_cnt(ps_g["desinc"]))],
        [f"… continuam nomeados ({_comp(ultima)}, sem exoneração)", _int(len(ps_g["ativo"])), _int(_cnt(ps_g["ativo"]))],
        ["… candidatos em OUTRA cidade do RJ", "—", _int(len(fora))],
        ["… eleitos em alguma candidatura (titular)", _int(len(eleitos)), _int(_cnt(eleitos))],
        ["Confiança ALTA · MÉDIA · BAIXA", f"{conf_n['ALTA']} · {conf_n['MÉDIA']} · {conf_n['BAIXA']}", "—"],
        ["Remuneração bruta dos vínculos comissionados, 01/2025–" + _comp(ultima) + " (folha)", _brl(total_bruto), "—"],
    ], {1, 2})
    orgaos = _tabela(["Órgão (folha, última competência)", "Pessoas", "Remuneração bruta na janela"],
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
                      "<br>".join(f"{_e(v['cargo'])} · {_e(v['orgao'] or '')}" for v in p["vinculos"])]
                     for p in sorted(eleitos, key=lambda p: (("ALTA", "MÉDIA", "BAIXA").index(p["conf"]), p["nome"]))])
    cab = ["Nome · confiança", "Vínculo(s) comissionado(s) em 2025–2026",
           "Candidatura(s) — ano · cargo · cidade · partido «urna» — resultado"]
    alerta = "style='border-left:4px solid #9b1c1c;background:#fbeaea;padding:8px 12px;margin:8px 0'"
    cap_desinc = (
        f"<p {alerta}><b>Prazo legal.</b> Eleições gerais de 2026: 1º turno em <b>04/10/2026</b>. O ocupante de cargo em "
        "comissão que pretende concorrer deve ser <b>exonerado</b> até <b>três meses antes do pleito — 04/07/2026</b> "
        "(LC 64/1990, art. 1º, II, <i>l</i>; Súmula TSE nº 54: a desincompatibilização do comissionado \"pressupõe a "
        "exoneração do cargo comissionado, e não apenas seu afastamento de fato\"). Aqui: comissionados que já foram "
        "candidatos e saíram da folha em <b>06/2026 ou 07/2026</b> (ou com exoneração publicada nesse período). O portal "
        "raramente publica a data do ato no último mês pago; quando a data existe, ela aparece no nome.</p>"
        + _tabela(["Recorte", "Pessoas", "Confiança ALTA/MÉDIA"], [
            ["Saíram em 06/2026 (mês anterior ao prazo)", _int(len(jun)), _int(_cnt(jun))],
            ["Saíram em 07/2026 (mês do prazo — até 04/07 é tempestivo)", _int(len(jul)), _int(_cnt(jul))]], {1, 2})
        + "<p><b>Saídas da folha por mês</b> (comissionados que já foram candidatos — o pico antes do prazo é o padrão "
        "da desincompatibilização):</p>"
        + _tabela(["Última competência na folha", "Pessoas que saíram", ""],
                  [[_comp(m), _int(k), "<span style='display:inline-block;height:9px;background:#9b1c1c;width:"
                    f"{min(260, 12 * k)}px'></span>"] for m, k in sorted(saidas_mes.items())], {1})
        + "<p class='dim'>Saída nesta janela é forte indício de pré-candidatura em 2026, não prova: a lista de "
        "candidatos de 2026 do TSE ainda não foi cruzada (download bloqueado para a nuvem). Quem foi exonerado depois de "
        "04/07 e registrou candidatura está sujeito a impugnação por desincompatibilização intempestiva.</p>"
        + _tabela(cab, [x[3] for x in g["desinc"]]))
    cap_ativo = (
        f"<p {alerta}><b>Continuam nomeados.</b> Na folha de {_comp(ultima)} e sem data de exoneração no portal. Se algum "
        "deles tiver registrado candidatura em 2026, não se desincompatibilizou no prazo — cruzamento a fazer assim "
        "que a lista de candidatos de 2026 do TSE chegar.</p>" + _tabela(cab, [x[3] for x in g["ativo"]]))
    lista = _tabela(cab, [x[3] for x in g["demais"]])
    pend = cob["consultas"] - cob["consultas_feitas"]
    metodo = (
        "<p><b>Universo.</b> Todas as candidaturas do Estado do Rio de Janeiro de 2012 a 2024 (TSE, dados abertos, "
        "arquivo do RJ) já cruzadas por <b>nome</b> com a folha inteira da Prefeitura (tabela <code>tse_candidatura</code>, "
        f"{_int(3718)} pessoas). Dessas, as que aparecem na folha mensal em bloco da Prefeitura "
        f"(contrachequedoc.rio.gov.br) entre 01/2025 e {_comp(ultima)}: {_int(cob['nomes'])} nomes, "
        f"{_int(cob['matriculas'])} matrículas.</p>"
        "<p><b>Cargo.</b> A folha em bloco não traz o cargo. O cargo de cada matrícula foi consultado no portal de "
        "remuneração da Prefeitura (contrachequeapi.rio.gov.br) na <b>última competência</b> em que a matrícula aparece "
        f"na janela: {_int(cob['consultas_feitas'])} de {_int(cob['consultas'])} consultas concluídas"
        + (f" — <b>{_int(pend)} ainda INDISPONÍVEIS</b> (o portal não respondeu; ficam para a próxima rodada)" if pend else "")
        + f". {_int(cob['sem_cargo_no_portal'])} matrícula(s) não retornaram linha no portal para o nome exato.</p>"
        "<p><b>Comissionado</b> = cargo com os rótulos da Prefeitura para cargo em comissão (classificador canônico da casa): cargo iniciado por <i>ESPECIAL</i> ou <i>ASSESSOR</i>, "
        "símbolo <i>DAS</i>/<i>DAI</i> ou contendo <i>COMISS</i>; vetados cargos de Educação Especial, estágios e 'especialidade'. Efetivos (concursados) ficam fora, "
        "inclusive quando exercem função gratificada na mesma matrícula — o portal mostra o cargo efetivo.</p>"
        "<p><b>Identidade.</b> O TSE publica CPF mascarado e a folha não traz CPF: servidor e candidato são casados "
        "por <b>nome</b>. A confiança por pessoa é declarada (ALTA: 4+ palavras significativas no nome; MÉDIA: 3 "
        "palavras, no máximo 1 entre as 200 mais comuns da folha; BAIXA: o resto) e rebaixada quando há candidaturas "
        "do mesmo nome em 3+ cidades ou 3+ matrículas do mesmo nome na folha. Casos de confiança BAIXA são listados, "
        "mas NÃO entram nas contagens de outra cidade.</p>"
        "<p><b>Limitações.</b> (1) As candidaturas de <b>2026</b> não estão incluídas: desde set/2026 o TSE recusa "
        "(403) o download para os servidores em nuvem da casa. (2) Pessoas que entraram na folha depois de 05/2026 "
        "não foram cruzadas com o TSE pelo mesmo motivo. (3) Remuneração = bruto da folha em bloco (competências "
        "da janela), não o custo total para o erário. (4) Organizações Sociais não entram (sem nomes na fonte "
        "pública).</p>")
    return {
        "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
        "titulo": "Comissionados da Prefeitura do Rio (2025–2026) que já foram candidatos",
        "subtitulo": f"Cargos em comissão × candidaturas TSE-RJ 2012–2024 — folha 01/2025 a {_comp(ultima)}",
        "metodologia": "Folha em bloco + cargo no portal de remuneração × TSE-RJ (casamento nominal; indício)",
        "score": pct, "rotulo_score": "Identificação confiável (% alta+média)", "faixa": "MÉDIO",
        "top_flags": [f"{_int(n)} comissionados candidatos", f"{_int(_cnt(ativos))} ainda na folha (alta/média)",
                      f"{_int(len(fora))} candidatos em outra cidade", f"{_int(_cnt(eleitos))} eleitos (alta/média)"],
        "secoes": [
            {"titulo": "1. Sumário executivo", "html": sumario},
            {"titulo": f"2. Distribuição por órgão ({len(por_orgao)})", "html": orgaos},
            {"titulo": "3. Distribuição por partido (candidatura mais recente)", "html": partidos},
            {"titulo": f"4. Candidatos em outras cidades do RJ ({len(por_cidade)} cidades · confiança alta/média)",
             "html": cidades},
            {"titulo": f"5. Eleitos ({len(eleitos)})", "html": eleit},
            {"titulo": f"6. Exonerados na desincompatibilização eleitoral de 2026 ({_int(len(ps_g['desinc']))})",
             "html": cap_desinc},
            {"titulo": f"7. Continuam nomeados até {_comp(ultima)} ({_int(len(ps_g['ativo']))})", "html": cap_ativo},
            {"titulo": f"8. Demais — saíram em outros momentos ({_int(len(ps_g['demais']))})", "html": lista},
            {"titulo": "9. Método, cobertura e limitações", "html": metodo},
        ],
        "proveniencia": [
            {"dado": "Folha mensal em bloco", "estado": "REAL", "fonte": "contrachequedoc.rio.gov.br",
             "data": _comp(ultima)},
            {"dado": "Cargo por matrícula", "estado": "REAL" if not pend else "PARCIAL",
             "fonte": "contrachequeapi.rio.gov.br", "data": datetime.now().strftime("%d/%m/%Y")},
            {"dado": "Candidaturas RJ 2012–2024", "estado": "REAL", "fonte": "TSE — dados abertos",
             "data": "jul–ago/2026"}],
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
    pdf = str(base / f"pcrj_comissionados_candidatos_2025_2026_{datetime.now().date()}.pdf")
    await html_to_pdf(render_html(ctx), pdf)
    return {"pdf": pdf, "pessoas": ctx["_n"], "confianca": ctx["_conf"], "consultas_pendentes": ctx["_pend"]}


if __name__ == "__main__":
    import sys
    if "--pdf" in sys.argv:
        import asyncio
        print(asyncio.run(gerar()))
    else:
        print(coletar())
