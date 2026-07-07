# -*- coding: utf-8 -*-
"""Perícia: nomeados (Câmara + Prefeitura do Rio) × benefício assistencial + fantasmas de gabinete.

Eixos do relatório:
  A) Nomeados recebendo Bolsa Família / BPC DURANTE a nomeação — organizado POR ÓRGÃO, com a série
     temporal (de quando até quando, e quantos meses em cada ano) e a filiação partidária em coluna.
  B) Gabinete sob SUPLÊNCIA — nomeado que ingressou ANTES da posse do suplente e segue no gabinete:
     equipe do titular que o suplente (que deveria montar a própria) não trocou. Sinal de que o
     titular ainda comanda parte do gabinete que não é mais dele. Livre nomeação = sinal forte;
     requisitado = servidor administrativo que persiste entre mandatos (padrão distinto).

Fontes: folha PCRJ/CMRJ (nomeados vigentes) · arquivos mensais do Portal da Transparência
(Bolsa Família/BPC) · filiação partidária (foto pública TSE 2018). Cruzamento por nome normalizado,
desambiguado pelo fragmento público de CPF. Relatório sem marca institucional.

Honesto: indício, nunca acusação. Sem CPF completo não se prova identidade; a filiação é de 2018
(cobertura parcial); o histórico dia-a-dia de titular/suplente não é público em fonte estruturada
(só atos de licença no Diário Oficial) — por isso o eixo B parte das suplências VIGENTES na tabela
oficial de gabinetes e aponta o comissionado que ingressou antes da posse do suplente.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.folha_pref import eh_ativo
from compliance_agent.pcrj.orgaos_siglas import decodificar  # noqa: F401 (usado via _orgaos_do_nome)

BENEF_DB = _db.DB_PATH.parent / "pcrj_benef.db"
_REPORTS = Path(__file__).resolve().parents[2] / "reports"

_LEGISLATURA_YM = "202501"  # início da legislatura 2025–2028 (referência p/ ingresso)
_VINCULO_COMISSIONADO = ("livre nomeação", "livre nomeacao", "requisitado")

# Data de POSSE do suplente por gabinete ('AAAAMM'), curada do Diário Oficial/CMRJ. Os gabinetes
# hoje sob suplência (6, 11, 20, 41, 44) tiveram o titular indo ao Executivo NO INÍCIO do mandato,
# com o suplente empossado em jan/2025 (CMRJ, "Suplentes tomam posse"). Comissionado ingressado
# antes disso e ainda nomeado = equipe do titular que o suplente não trocou. Ampliar com as
# licenças MID-mandato (titular que se afasta no meio do período) exige varrer o DOM da CMRJ.
_POSSE_SUPLENTE = {6: "202501", 11: "202501", 20: "202501", 41: "202501", 44: "202501"}

_MESES = ["", "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _comp_legivel(ym: str) -> str:
    try:
        return f"{_MESES[int(ym[4:6])]}/{ym[:4]}"
    except Exception:
        return ym


def _ingresso_ym(data1: str) -> str | None:
    """'01/01/2025' -> '202501'."""
    if not data1:
        return None
    m = data1.strip().split("/")
    if len(m) == 3 and len(m[2]) == 4:
        try:
            return f"{m[2]}{int(m[1]):02d}"
        except ValueError:
            return None
    return None


def _partido_de(con, nome_norm: str) -> str:
    """Filiação partidária (foto TSE 2018) — coluna integrada, '—' se não consta."""
    r = con.execute(
        "SELECT partido, situacao FROM pcrj_filiado WHERE nome_norm=? "
        "ORDER BY CASE WHEN situacao='REGULAR' THEN 0 ELSE 1 END LIMIT 1", (nome_norm,)).fetchone()
    if not r or not r["partido"]:
        return "—"
    return r["partido"] if r["situacao"] == "REGULAR" else f"{r['partido']} (cancel.)"


def _orgao_limpo(orgao_decod: str) -> str:
    """'Comlurb (COMLURB/...)' -> 'Comlurb'; agrupa pelo órgão de topo, sem a sigla interna."""
    return (orgao_decod or "").split(" (")[0].strip() or "(órgão não informado)"


def _orgaos_do_nome(con, nome_norm: str) -> dict:
    """(poder, orgao_legivel, cargo, ingresso, gabinete_num, vinculo) do nomeado.
    Prefeitura vem da folha COMPLETA (pcrj_folha_pref); Câmara da relação de servidores."""
    d = {"poder": "", "orgao": "", "cargo": "", "ingresso": "", "gab": None,
         "vinculo": "", "tipo_folha": ""}
    cam = con.execute(
        "SELECT lotacao, cargo, data1, gabinete_num, vinculo FROM pcrj_camara_servidores "
        "WHERE nome_norm=? ORDER BY CASE WHEN data1 LIKE '__/__/____' "
        "THEN substr(data1,7,4)||substr(data1,4,2)||substr(data1,1,2) ELSE '99999999' END "
        "LIMIT 1", (nome_norm,)).fetchone()
    if cam:
        d.update(poder="Câmara Municipal", orgao=cam["lotacao"] or "(lotação não informada)",
                 cargo=cam["cargo"] or "", ingresso=cam["data1"] or "",
                 gab=cam["gabinete_num"], vinculo=cam["vinculo"] or "")
    # Prefeitura: folha completa. Pega o registro mais recente; agrega os órgãos distintos da pessoa.
    prefs = []
    try:
        prefs = con.execute(
            "SELECT orgao, tipo_folha, competencia FROM pcrj_folha_pref WHERE nome_norm=? "
            "ORDER BY competencia DESC", (nome_norm,)).fetchall()
    except Exception:
        prefs = []
    if prefs:
        orgs = sorted({_orgao_limpo(r["orgao"]) for r in prefs if r["orgao"]})
        pref_org = " ; ".join(orgs) if orgs else "(órgão não informado)"
        tipo = prefs[0]["tipo_folha"] or ""
        comps = sorted({r["competencia"] for r in prefs})
        d["folha_desde"], d["folha_ate"] = comps[0], comps[-1]  # tenure aprox. (faixa na folha)
        if d["poder"]:
            d["poder"] = "Câmara + Prefeitura"
            d["orgao"] = f"{d['orgao']} | {pref_org}"
        else:
            d.update(poder="Prefeitura", orgao=pref_org)
        d["tipo_folha"] = tipo
    else:
        d["folha_desde"] = d["folha_ate"] = ""
    if not d["poder"]:
        d["poder"] = "(poder não identificado)"
    return d


def _orgao_topo(reg: dict) -> str:
    """Chave de agrupamento por órgão (1º órgão listado; gabinete da Câmara vira o título do vereador
    quando conhecido — resolvido depois, aqui fica a lotação bruta)."""
    return (reg["orgao"] or "(órgão não informado)").split(" | ")[0].split(" ; ")[0]


def analisar() -> dict:
    b = _db.sqlite3.connect(f"file:{BENEF_DB}?mode=ro", uri=True)
    b.row_factory = _db.sqlite3.Row
    p = _db.conectar()

    comps = [r[0] for r in b.execute("SELECT DISTINCT competencia FROM pcrj_beneficio ORDER BY 1")]
    ultima = comps[-1] if comps else None
    anos = sorted({c[:4] for c in comps})
    try:  # última competência da folha carregada — quem aparece nela ainda está ativo (tenure)
        ultima_folha = p.execute("SELECT MAX(competencia) FROM pcrj_folha_pref").fetchone()[0] or ""
    except Exception:
        ultima_folha = ""

    # DEDUPLICAÇÃO DE HOMÔNIMOS (certeza). Todo nome aqui já é servidor/nomeado (o filtro do
    # coletor usa o alvo). O risco é o beneficiário homônimo de OUTRO estado. Duas travas:
    #   1) MUNICÍPIO: só conta benefício pago no RIO DE JANEIRO (servidor do Rio recebe no Rio) —
    #      elimina o homônimo nacional (a maioria das 287k linhas brutas).
    #   2) FRAGMENTO DE CPF: identidade da pessoa = (nome, cpf_frag) unificada entre TODOS os
    #      programas (BPC+BF+Auxílio Brasil+Emergencial). Se, no Rio, o nome tem UM único fragmento,
    #      o beneficiário é uma pessoa só; se tem vários, é homônimo mesmo dentro do Rio → fora.
    # Carga no NÍVEL DE MÊS (cursor, memória-segura): por (nome,frag) o conjunto de competências de
    # cada programa. Isso é o que permite o cruzamento EXATO benefício×vínculo (só conta benefício
    # recebido DURANTE a nomeação — evita a injustiça de flagrar quem recebeu entre empregos).
    frags_rio: dict[str, set] = {}
    pessoa: dict[tuple, dict] = {}
    cur = b.execute("SELECT nome_norm, cpf_frag, beneficio, competencia FROM pcrj_beneficio "
                    "WHERE municipio='RIO DE JANEIRO'")
    while True:
        lote = cur.fetchmany(50000)
        if not lote:
            break
        for nn, frag, ben, comp in lote:
            frag = frag or "?"
            frags_rio.setdefault(nn, set()).add(frag)
            pessoa.setdefault((nn, frag), {}).setdefault(ben, set()).add(comp)
    nome_de = {r[0]: (r[1] or r[0].title()) for r in b.execute(
        "SELECT nome_norm, MAX(nome) FROM pcrj_beneficio WHERE municipio='RIO DE JANEIRO' "
        "GROUP BY nome_norm")}

    # nomes do alvo com benefício mas NENHUM no município do Rio (informativo) — 1 varredura leve
    fora_rio = b.execute(
        "SELECT COUNT(*) FROM (SELECT nome_norm FROM pcrj_beneficio GROUP BY nome_norm "
        "HAVING MAX(municipio='RIO DE JANEIRO')=0)").fetchone()[0]

    registros, homonimos, fora_vinculo = [], 0, 0
    gab_cache: dict[int, str] = {}
    for nn in set(nome_de):
        fr = frags_rio.get(nn)
        if len(fr) != 1:              # homônimo dentro do próprio Rio (fragmentos distintos) → fora
            homonimos += 1
            continue
        frag = next(iter(fr))
        prog_meses = pessoa[(nn, frag)]   # {beneficio: set(competências)}
        info = _orgaos_do_nome(p, nn)
        if info["poder"] == "(poder não identificado)":
            continue  # nome do alvo que é só sócio de fornecedor (não servidor) → outro relatório

        # ── FAIRNESS: janelas de VÍNCULO PÚBLICO e só benefício recebido DENTRO delas ──────────
        # Câmara: do ingresso (data1) até hoje (está no quadro atual = ativo). Prefeitura: faixa de
        # presença na folha (se sai antes da última folha, o vínculo terminou ali). Benefício fora de
        # toda janela = pessoa estava ENTRE empregos → NÃO é irregularidade (não flagra).
        janelas, vinculos = [], []
        iy = _ingresso_ym(info["ingresso"])
        if em_camara_ing := info["poder"].startswith("Câmara"):
            lo = iy or "200001"
            janelas.append((lo, ultima))
            vinculos.append(f"Câmara: {info['ingresso'] or _comp_legivel(lo)}→atual")
        if info["folha_desde"]:
            pref_ativo = (not ultima_folha) or (info["folha_ate"] >= ultima_folha)
            hi = ultima if pref_ativo else info["folha_ate"]
            janelas.append((info["folha_desde"], hi))
            vinculos.append(f"Prefeitura: {_comp_legivel(info['folha_desde'])}→"
                            f"{'atual' if pref_ativo else _comp_legivel(info['folha_ate'])}")
        # filtra os meses de cada programa às janelas de vínculo
        prog_ok = {}
        for ben, meses in prog_meses.items():
            dentro = {m for m in meses if any(lo <= m <= hi for lo, hi in janelas)}
            if dentro:
                prog_ok[ben] = dentro
        if not prog_ok:              # recebeu só FORA de qualquer vínculo → não flagra (fairness)
            fora_vinculo += 1
            continue
        # nº de identidades de servidor com esse nome (matrículas na folha + presença na Câmara):
        # 1 => atribuição limpa; >1 => há mais de um servidor homônimo, atribuição incerta.
        try:
            n_mat = p.execute("SELECT COUNT(DISTINCT matricula) FROM pcrj_folha_pref WHERE nome_norm=?",
                              (nn,)).fetchone()[0]
        except Exception:
            n_mat = 0
        n_serv = max(n_mat, 0) + (1 if (em_camara_ing and n_mat == 0) else 0)
        # ALTA exige: um único servidor com o nome E um fragmento de CPF legível (não vazio).
        certeza = "ALTA" if (n_serv <= 1 and frag != "?") else "MÉDIA"
        ativo = eh_ativo(info["tipo_folha"]) if info["tipo_folha"] else em_camara_ing

        titular = ""
        if info["gab"] is not None:
            if info["gab"] not in gab_cache:
                g = p.execute("SELECT titular FROM pcrj_gabinetes WHERE gabinete_num=?",
                              (info["gab"],)).fetchone()
                gab_cache[info["gab"]] = (g["titular"] if g else "") or ""
            titular = gab_cache[info["gab"]]
        topo = _orgao_topo({"orgao": info["orgao"]})
        if titular and topo.lower().startswith("gabinete"):
            topo = f"{topo} — {titular}"
        # trajetória por programa — SÓ os meses DENTRO do vínculo (prog_ok)
        progs, todos_meses, por_ano = [], set(), {}
        for ben, meses in sorted(prog_ok.items(), key=lambda kv: min(kv[1])):
            ms = sorted(meses)
            progs.append({"ben": ben, "desde": _comp_legivel(ms[0]), "ate": _comp_legivel(ms[-1]),
                          "n": len(ms)})
            todos_meses |= meses
            for m in meses:
                por_ano[m[:4]] = por_ano.get(m[:4], set())
                por_ano[m[:4]].add(m)
        cmin, cmax = min(todos_meses), max(todos_meses)
        registros.append({
            "nome": nome_de[nn], "nome_norm": nn, "cpf_frag": frag,
            "poder": info["poder"], "orgao": info["orgao"], "cargo": info["cargo"],
            "vinculo": info["vinculo"], "ingresso": info["ingresso"], "gab_titular": titular,
            "partido": _partido_de(p, nn),
            "programas": progs,
            "beneficios_str": ", ".join(pr["ben"] for pr in progs),
            "desde": _comp_legivel(cmin), "ate": _comp_legivel(cmax),
            "n_meses": len(todos_meses),
            "por_ano": {a: len(por_ano.get(a, set())) for a in anos},
            "ainda_recebe": (cmax == ultima),
            "rio": True, "certeza": certeza, "n_serv": n_serv,
            "ativo": ativo, "situacao": "ativo/nomeado" if ativo else "aposent./pensão",
            # vínculos COERENTES (cada um com sua janela); benefício acima já é só o recebido nelas.
            "vinculos": " · ".join(vinculos),
            "nomeacao": info["ingresso"] or (_comp_legivel(info["folha_desde"]) if info["folha_desde"] else ""),
            "exoneracao": vinculos[0].split("→")[-1] if vinculos else "",
            "_orgao_topo": topo,
        })

    # ── EIXO B: gabinete sob SUPLÊNCIA — equipe do titular sobrevivente ────────────────────
    # Sinal correto (correção 2026-07-06): quando o titular se licencia e o SUPLENTE assume, o
    # suplente deveria montar a própria equipe. Comissionado que ingressou ANTES da posse do
    # suplente e continua nomeado sob ele = pessoa do titular que o suplente não trocou — indício
    # de que o titular segue mandando em parte do gabinete que não é mais dele. (NÃO confundir com
    # reeleição/manutenção de equipe, que é normal — era o erro do proxy anterior.)
    # Requer a DATA DE POSSE do suplente (Diário Oficial da CMRJ). Mapa curado abaixo; sem a data,
    # o gabinete é listado mas sem apontar sobreviventes (honesto: não inventa).
    fantasmas, gabs_suplencia = [], []
    for g in p.execute("SELECT gabinete_num, titular, suplente FROM pcrj_gabinetes "
                       "WHERE suplente IS NOT NULL AND suplente<>''"):
        posse = _POSSE_SUPLENTE.get(g["gabinete_num"])   # 'AAAAMM' ou None
        sobreviventes = []
        for r in p.execute(
                "SELECT nome, nome_norm, cargo, vinculo, data1 FROM pcrj_camara_servidores "
                "WHERE gabinete_num=?", (g["gabinete_num"],)):
            if not any(v in (r["vinculo"] or "").lower() for v in _VINCULO_COMISSIONADO):
                continue
            iy = _ingresso_ym(r["data1"])
            if posse and iy and iy < posse:   # ingressou ANTES da posse do suplente → sobrevivente
                vinc = r["vinculo"] or ""
                sobreviventes.append({
                    "nome": r["nome"], "cargo": r["cargo"] or "", "ingresso": r["data1"] or "",
                    "vinculo": vinc, "eh_livre": "livre" in vinc.lower(),
                    "partido": _partido_de(p, r["nome_norm"]),
                })
        gabs_suplencia.append({
            "gabinete": g["gabinete_num"], "titular": g["titular"] or "",
            "suplente": g["suplente"] or "",
            "posse": _comp_legivel(posse) if posse else "(posse não confirmada)",
            "sobreviventes": sorted(sobreviventes, key=lambda x: x["ingresso"]),
        })
        fantasmas.extend([{**s, "titular_atual": g["titular"] or "", "suplente": g["suplente"] or "",
                           "gabinete": f"Gabinete {g['gabinete_num']}"} for s in sobreviventes])

    b.close(); p.close()
    _ordem = {"ALTA": 0, "MÉDIA": 1}
    registros.sort(key=lambda x: (_ordem.get(x["certeza"], 9), not x["ainda_recebe"],
                                  -x["n_meses"], x["nome"]))

    # A tabela detalhada por órgão traz só a CERTEZA ALTA (núcleo defensável); a MÉDIA — nome comum
    # com mais de um servidor homônimo, ou fragmento de CPF ausente — vai resumida (contagens), para
    # o documento não inchar com dezenas de milhares de linhas de baixa atribuição.
    por_orgao: dict[str, list] = {}
    for r in registros:
        if r["certeza"] != "ALTA":
            continue
        por_orgao.setdefault(r["_orgao_topo"], []).append(r)
    grupos = sorted(por_orgao.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    def _tem(reg, sub):
        return any(sub in pr["ben"] for pr in reg["programas"])

    # cobertura real das fontes (para a nota de janelas temporais do relatório)
    try:
        fol = [r[0] for r in p.execute("SELECT DISTINCT competencia FROM pcrj_folha_pref ORDER BY 1")]
    except Exception:
        fol = []
    def _faixas(ms):
        out, ini, ant = [], None, None
        for m in ms:
            if ini is None:
                ini = ant = m
                continue
            prox = f"{int(ant[:4])+1}01" if ant[4:6] == "12" else f"{ant[:4]}{int(ant[4:6])+1:02d}"
            if m != prox:
                out.append((ini, ant))
                ini = m
            ant = m
        if ini:
            out.append((ini, ant))
        return out
    cobertura_folha = "; ".join(f"{_comp_legivel(a)}→{_comp_legivel(b)}" for a, b in _faixas(fol)) or "—"
    cobertura_benef = f"{_comp_legivel(comps[0])}→{_comp_legivel(comps[-1])}" if comps else "—"

    return {
        "competencias": comps, "anos": anos, "ultima": ultima,
        "cobertura_folha": cobertura_folha, "cobertura_benef": cobertura_benef,
        "registros": registros, "grupos": grupos,
        "homonimos": homonimos, "fora_rio": fora_rio, "fora_vinculo": fora_vinculo,
        "fantasmas": fantasmas, "gabs_suplencia": gabs_suplencia,
        "n_alta": sum(1 for x in registros if x["certeza"] == "ALTA"),
        "n_media": sum(1 for x in registros if x["certeza"] == "MÉDIA"),
        "n_bpc": sum(1 for x in registros if _tem(x, "BPC")),
        "n_bf": sum(1 for x in registros if _tem(x, "Bolsa")),
        "n_ab": sum(1 for x in registros if _tem(x, "Brasil")),
        "n_ae": sum(1 for x in registros if _tem(x, "Emergencial")),
        "n_ainda": sum(1 for x in registros if x["ainda_recebe"]),
    }


_TPL = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>
  @page { size: A4 landscape; margin: 12mm 10mm; }
  body { font-family:'Helvetica Neue',Arial,sans-serif; color:#1a1a1a; font-size:9.5px; line-height:1.45; }
  .capa { border-bottom:3px solid #7a1f1f; padding-bottom:9px; margin-bottom:12px; }
  .classif { color:#7a1f1f; font-weight:700; letter-spacing:1px; font-size:9.5px; }
  h1 { font-size:19px; color:#3a1010; margin:4px 0; }
  .meta { color:#555; font-size:9px; }
  h2 { font-size:13px; color:#7a1f1f; border-bottom:1px solid #e0d3d3; padding-bottom:3px; margin-top:16px; }
  h3 { font-size:11px; color:#3a1010; margin:12px 0 2px; background:#f2e9e9; padding:3px 7px; border-radius:4px; }
  .kpis { display:flex; gap:9px; margin:11px 0; flex-wrap:wrap; }
  .kpi { border:1px solid #e2d5d5; border-radius:8px; padding:9px 13px; background:#fbf7f7; min-width:110px; }
  .kpi .n { font-size:21px; font-weight:700; color:#7a1f1f; line-height:1; }
  .kpi .l { font-size:8.5px; color:#666; margin-top:3px; }
  table { width:100%; border-collapse:collapse; font-size:8.5px; margin:4px 0 10px; }
  th,td { text-align:left; padding:3px 5px; border-bottom:1px solid #eee; vertical-align:top; }
  th { background:#7a1f1f; color:#fff; }
  table tr:nth-child(even) td { background:#f7f0f0; }
  .tag { padding:1px 5px; border-radius:3px; font-size:8px; font-weight:600; }
  .sim { background:#fdecea; color:#c62828; } .rio { background:#fff3e0; color:#e65100; }
  .part { background:#e8eef7; color:#1f4e79; padding:1px 5px; border-radius:3px; font-size:8px; }
  .nota { font-size:8.5px; color:#666; font-style:italic; }
  footer { margin-top:18px; border-top:1px solid #ddd; padding-top:6px; font-size:8px; color:#888; }
</style></head><body>
  <div class="capa">
    <div class="classif">CONFIDENCIAL — SUBSÍDIO PARA APURAÇÃO</div>
    <h1>{{ titulo }}</h1>
    <div class="meta">Emitido em {{ data }} · Cruzamento nominal com desambiguação por fragmento de
    CPF · Período coberto: {{ periodo }} · Filiação partidária: foto pública TSE 2018 (cobertura parcial)</div>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="n">{{ total }}</div><div class="l">nomeados com benefício no Rio (dedup.)</div></div>
    <div class="kpi"><div class="n">{{ n_alta }}</div><div class="l">certeza ALTA (1 pessoa, 1 servidor) — detalhados</div></div>
    <div class="kpi"><div class="n">{{ n_media }}</div><div class="l">certeza MÉDIA (nome comum/CPF ausente)</div></div>
    <div class="kpi"><div class="n">{{ n_ainda }}</div><div class="l">ainda recebendo em {{ ultima }}</div></div>
    <div class="kpi"><div class="n">{{ n_bpc }}</div><div class="l">BPC/LOAS</div></div>
    <div class="kpi"><div class="n">{{ n_bf }}</div><div class="l">Bolsa Família</div></div>
    <div class="kpi"><div class="n">{{ n_ab }}</div><div class="l">Auxílio Brasil</div></div>
    <div class="kpi"><div class="n">{{ n_ae }}</div><div class="l">Auxílio Emergencial</div></div>
    <div class="kpi"><div class="n">{{ n_suplencia }}</div><div class="l">gabinetes sob suplência</div></div>
    <div class="kpi"><div class="n">{{ n_fantasmas }}</div><div class="l">sobreviventes do titular sob suplente</div></div>
  </div>

  <h2>1. Nomeados recebendo benefício assistencial durante a nomeação — por órgão</h2>
  <p class="nota">Identidade da pessoa unificada por (nome + fragmento de CPF) entre <b>todos</b> os
  programas, restrita a benefício pago <b>no município do Rio</b> (afasta o homônimo de outro
  estado). A tabela detalha os <b>{{ n_alta }}</b> casos de <b>certeza ALTA</b> (um único
  beneficiário e um único servidor com o nome, CPF legível); os <b>{{ n_media }}</b> de certeza
  MÉDIA (nome comum com mais de um servidor homônimo, ou fragmento de CPF ausente) entram só nas
  contagens — atribuição individual incerta. As colunas de ano contam meses com benefício; a coluna
  Programas traz a trajetória com datas. <b>Observação:</b> o Auxílio Emergencial (2020–2021) teve
  elegibilidade ampla na pandemia (inclusive trabalhadores informais de baixa renda), então recebê-lo
  é sinal mais fraco que BPC/Bolsa Família/Auxílio Brasil, cuja renda exigida é incompatível com cargo.</p>
  {% for orgao, regs in grupos %}
  <h3>{{ orgao }} — {{ regs|length }} nomeado(s)</h3>
  <table>
    <tr><th>Nome</th><th>Certeza</th><th>CPF (frag.)</th><th>Poder</th><th>Situação</th><th>Cargo</th><th>Titular do gab.</th>
        <th>Partido</th><th>Ingresso</th><th>Programas (trajetória)</th>{% for a in anos %}<th>{{ a }}</th>{% endfor %}
        <th>Ainda?</th></tr>
    {% for r in regs %}
    <tr><td>{{ r.nome }}</td>
        <td><span class="tag {% if r.certeza=='ALTA' %}sim{% else %}rio{% endif %}">{{ r.certeza }}</span></td>
        <td>…{{ r.cpf_frag }}…</td><td>{{ r.poder }}</td><td>{{ r.situacao }}</td><td>{{ r.cargo }}</td><td>{{ r.gab_titular }}</td>
        <td><span class="part">{{ r.partido }}</span></td><td>{{ r.ingresso }}</td>
        <td>{% for pr in r.programas %}{{ pr.ben }} ({{ pr.desde }}→{{ pr.ate }}, {{ pr.n }}m){% if not loop.last %}; {% endif %}{% endfor %}</td>
        {% for a in anos %}<td style="text-align:center">{{ r.por_ano[a] or '·' }}</td>{% endfor %}
        <td>{% if r.ainda_recebe %}<span class="tag sim">SIM</span>{% else %}não{% endif %}</td></tr>
    {% endfor %}
  </table>
  {% endfor %}

  <h2>2. Gabinetes sob suplência — equipe do titular sobrevivente sob o suplente</h2>
  <p class="nota">Quando o titular se licencia e o <b>suplente</b> assume, o suplente deveria formar a
  própria equipe. Comissionado que ingressou <b>antes da posse do suplente</b> e permanece nomeado
  sob ele é pessoa do titular que o suplente não trocou — indício de que o titular ainda comanda
  parte de um gabinete que não é mais dele. (Não confundir com manutenção de equipe por reeleição,
  que é normal.) Confirmar exige a <b>data de posse do suplente</b> (Diário Oficial da CMRJ).</p>
  {% for g in gabs_suplencia %}
  <h3>Gabinete Nº {{ g.gabinete }} — titular {{ g.titular }} · suplente em exercício {{ g.suplente }} (posse {{ g.posse }})</h3>
  {% if g.sobreviventes %}
  <table>
    <tr><th>#</th><th>Nomeado (ingressou antes da posse do suplente)</th><th>Vínculo</th><th>Cargo</th><th>Partido</th><th>Ingresso</th></tr>
    {% for s in g.sobreviventes %}
    <tr><td>{{ loop.index }}</td><td>{{ s.nome }}</td>
        <td>{% if s.eh_livre %}<span class="tag sim">livre nomeação</span>{% else %}{{ s.vinculo }}{% endif %}</td>
        <td>{{ s.cargo }}</td><td><span class="part">{{ s.partido }}</span></td><td>{{ s.ingresso }}</td></tr>
    {% endfor %}
  </table>
  <p class="nota"><b>Leitura:</b> "livre nomeação" ingressado antes da posse do suplente é o sinal
  forte (equipe POLÍTICA do titular mantida). "Requisitado" é servidor administrativo cedido, que
  costuma persistir através de mandatos independentemente do ocupante — padrão distinto, atenção
  menor.</p>
  {% else %}
  <p class="nota">Nenhum nomeado ingressado antes da posse do suplente — neste caso o titular foi ao
  Executivo no início do mandato e o suplente montou a própria equipe (sem sobrevivente).</p>
  {% endif %}
  {% endfor %}
  <p class="nota">Cobertura atual: apenas as suplências <b>vigentes</b> constam da tabela oficial de
  gabinetes. As suplências encerradas ou iniciadas no meio do mandato (titular que se licencia e
  depois retorna) exigem varredura do Diário Oficial da CMRJ — recomendável para fechar o quadro.</p>

  <h2>3. Método, cobertura e ressalvas</h2>
  <p><b>Cruzamento e deduplicação de homônimos.</b> Nomes normalizados dos nomeados/servidores
  contra os arquivos mensais oficiais dos quatro programas — BPC, Bolsa Família, Auxílio Brasil e
  Auxílio Emergencial — competência a competência. Duas travas de identidade dão a certeza: (1) só
  conta benefício pago <b>no município do Rio de Janeiro</b> — um servidor municipal do Rio recebe
  no Rio, o que elimina o beneficiário homônimo de outro estado (a origem do grosso das centenas de
  milhares de linhas brutas); (2) a pessoa é identificada por <b>(nome + fragmento público de CPF)</b>
  unificada entre <b>todos</b> os programas — se, no Rio, o nome tem um único fragmento, o
  beneficiário é uma pessoa só (afastados {{ homonimos }} nomes por terem fragmentos distintos no
  próprio Rio, e {{ fora_rio }} por só terem benefício fora do município). <b>Certeza ALTA</b> exige
  ainda um único servidor com o nome; <b>MÉDIA</b> quando há mais de um servidor homônimo. Sem o CPF
  completo do servidor (não público, LGPD), a atribuição final é <b>indício qualificado</b>, não
  acusação — mas a dupla trava torna o homônimo residual improvável. Benefício assistencial
  pressupõe baixa renda (BPC: renda per capita &lt; ¼ do salário mínimo; Bolsa Família/Brasil: linha
  de pobreza), em tensão com cargo remunerado.</p>
  <p><b>Cobertura por poder.</b> Câmara Municipal: quadro completo de nomeados (relação oficial de
  servidores). Prefeitura: <b>folha completa</b> (~200 mil servidores/mês, todos os órgãos), obtida
  em bloco do repositório oficial de remuneração; o órgão vem decodificado da sigla da unidade
  administrativa (Gabinete do Prefeito, Comlurb, Secretaria de Educação/Saúde/Obras etc.). Inclui
  efetivos, comissionados, cedidos e — quando a folha assim indica — aposentados/pensionistas.</p>
  <p><b>Janelas temporais (regra de justiça).</b> Benefício só conta se recebido <b>durante</b> uma
  janela de vínculo público: Câmara = do ato de ingresso (registro mais antigo) até hoje (a relação
  oficial é o quadro ATUAL — quem saiu não consta); Prefeitura = faixa de presença na folha
  ({{ cobertura_folha }}); benefício recebido fora de toda janela (pessoa entre empregos) <b>não é
  flagrado</b>. Vínculo anterior ao início da cobertura da folha não gera flag (limite conservador
  da fonte). Benefícios: {{ cobertura_benef }}.</p>
  <p><b>Ressalvas.</b> A filiação partidária é a foto pública de 2018 (cobertura parcial — "—" =
  não consta na base de 2018). O eixo de suplência parte da tabela oficial de gabinetes (suplências
  vigentes) e da data de posse do suplente (Diário Oficial da CMRJ); a cobertura de suplências
  encerradas ou iniciadas no meio do mandato exige varredura do Diário Oficial. Apuração formal
  compete aos órgãos de controle e ao Ministério Público.</p>

  <footer>Peça de subsídio à apuração — indícios, não acusação; presunção de legitimidade dos atos
  administrativos preservada. Fonte pública oficial. CPF de terceiros mascarado (LGPD).</footer>
</body></html>"""


def render(dados: dict) -> str:
    from jinja2 import Template
    comps = dados["competencias"]
    periodo = f"{_comp_legivel(comps[0])} a {_comp_legivel(comps[-1])}" if comps else "—"
    return Template(_TPL).render(
        titulo="Perícia — Nomeados da Câmara e da Prefeitura do Rio: benefício assistencial e fantasmas de gabinete",
        data=datetime.now().strftime("%d/%m/%Y"),
        periodo=periodo, ultima=_comp_legivel(dados["ultima"]) if dados["ultima"] else "—",
        anos=dados["anos"], total=len(dados["registros"]), n_ainda=dados["n_ainda"],
        n_alta=dados["n_alta"], n_media=dados["n_media"],
        n_bpc=dados["n_bpc"], n_bf=dados["n_bf"], n_ab=dados["n_ab"], n_ae=dados["n_ae"],
        n_fantasmas=len(dados["fantasmas"]), n_suplencia=len(dados["gabs_suplencia"]),
        homonimos=dados["homonimos"], fora_rio=dados["fora_rio"],
        grupos=dados["grupos"], gabs_suplencia=dados["gabs_suplencia"],
        cobertura_folha=dados.get("cobertura_folha", "—"),
        cobertura_benef=dados.get("cobertura_benef", "—"),
    )


# Termos institucionais/agentes/produtos que NÃO podem constar do entregável (ordem do dono).
# A checagem é feita contra o TEMPLATE (texto fixo do relatório), não contra os dados — um cidadão
# chamado "Hermes" ou "Alex" é dado legítimo e não pode barrar a geração.
_PROIBIDOS = ("jfn", "yoda", "hermes", "massare", "politimonitor", "gitnexus",
              "kroll", "deloitte", "control risks", "mckinsey", "claude", "opus", "anthropic")


def _verificar_neutralidade() -> None:
    """Garante que o texto fixo do relatório não carrega marca institucional/agente/produto."""
    low = _TPL.lower()
    achados = [t for t in _PROIBIDOS if t in low]
    if achados:
        raise AssertionError(f"template contém termo(s) proibido(s): {achados}")


async def gerar_pdf() -> str:
    from compliance_agent.reporting.render_html import html_to_pdf
    _verificar_neutralidade()
    html = render(analisar())
    destino = str(_REPORTS / f"pericia_beneficios_nomeados_{datetime.now().date()}.pdf")
    await html_to_pdf(html, destino)
    return destino


if __name__ == "__main__":
    import asyncio
    import json
    d = analisar()
    print(json.dumps({k: v for k, v in d.items()
                      if k not in ("registros", "grupos", "fantasmas")}, ensure_ascii=False, indent=1))
    print("registros:", len(d["registros"]), "| grupos:", len(d["grupos"]),
          "| fantasmas:", len(d["fantasmas"]))
    print(asyncio.run(gerar_pdf()))
