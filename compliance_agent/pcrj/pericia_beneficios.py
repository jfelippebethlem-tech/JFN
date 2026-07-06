# -*- coding: utf-8 -*-
"""Perícia: nomeados (Câmara + Prefeitura do Rio) × benefício assistencial + fantasmas de gabinete.

Eixos do relatório:
  A) Nomeados recebendo Bolsa Família / BPC DURANTE a nomeação — organizado POR ÓRGÃO, com a série
     temporal (de quando até quando, e quantos meses em cada ano) e a filiação partidária em coluna.
  B) Sinal de FANTASMA de gabinete — comissionado (Livre Nomeação) cujo ingresso atravessa a virada
     de legislatura (antes de 01/2025 e ainda lotado no mesmo gabinete): sobreviveu à troca de
     titular, o padrão clássico de "servidor que não serve a um mandato, só recebe".

Fontes: folha PCRJ/CMRJ (nomeados vigentes) · arquivos mensais do Portal da Transparência
(Bolsa Família/BPC) · filiação partidária (foto pública TSE 2018). Cruzamento por nome normalizado,
desambiguado pelo fragmento público de CPF. Relatório sem marca institucional.

Honesto: indício, nunca acusação. Sem CPF completo não se prova identidade; a filiação é de 2018
(cobertura parcial); o histórico dia-a-dia de titular/suplente não é público em fonte estruturada
(só atos de licença no Diário Oficial) — por isso o eixo B usa a virada de legislatura como proxy.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.folha_pref import eh_ativo
from compliance_agent.pcrj.orgaos_siglas import decodificar  # noqa: F401 (usado via _orgaos_do_nome)

BENEF_DB = _db.DB_PATH.parent / "pcrj_benef.db"
_REPORTS = Path(__file__).resolve().parents[2] / "reports"

# Legislatura vigente da Câmara começou em 01/01/2025. Comissionado lotado em gabinete cujo
# ingresso é anterior a isto atravessou a posse dos titulares eleitos em 2024 (proxy de fantasma).
_LEGISLATURA_YM = "202501"
_VINCULO_COMISSIONADO = ("livre nomeação", "livre nomeacao", "requisitado")

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
        "WHERE nome_norm=? LIMIT 1", (nome_norm,)).fetchone()
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
        if d["poder"]:
            d["poder"] = "Câmara + Prefeitura"
            d["orgao"] = f"{d['orgao']} | {pref_org}"
        else:
            d.update(poder="Prefeitura", orgao=pref_org)
        d["tipo_folha"] = tipo
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

    # DEDUPLICAÇÃO DE HOMÔNIMOS (certeza). Todo nome aqui já é servidor/nomeado (o filtro do
    # coletor usa o alvo). O risco é o beneficiário homônimo de OUTRO estado. Duas travas:
    #   1) MUNICÍPIO: só conta benefício pago no RIO DE JANEIRO (servidor do Rio recebe no Rio) —
    #      elimina o homônimo nacional (a maioria das 287k linhas brutas).
    #   2) FRAGMENTO DE CPF: identidade da pessoa = (nome, cpf_frag) unificada entre TODOS os
    #      programas (BPC+BF+Auxílio Brasil+Emergencial). Se, no Rio, o nome tem UM único fragmento,
    #      o beneficiário é uma pessoa só; se tem vários, é homônimo mesmo dentro do Rio → fora.
    raw = b.execute("SELECT nome_norm, nome, beneficio, competencia, cpf_frag, municipio, valor "
                    "FROM pcrj_beneficio").fetchall()

    def _rio(m):
        return "RIO DE JANEIRO" in (m or "").upper()

    # por nome: fragmentos vistos no Rio; por (nome,frag): trajetória entre programas
    frags_rio: dict[str, set] = {}
    pessoa: dict[tuple, dict] = {}
    nome_de: dict[str, str] = {}
    for r in raw:
        nn = r["nome_norm"]
        nome_de.setdefault(nn, r["nome"] or nn.title())
        if not _rio(r["municipio"]):
            continue                              # trava 1: fora do Rio não conta
        frag = r["cpf_frag"] or "?"
        frags_rio.setdefault(nn, set()).add(frag)
        e = pessoa.setdefault((nn, frag), {"prog": {}, "comps": set(), "por_ano": {}, "valor": ""})
        e["prog"].setdefault(r["beneficio"], set()).add(r["competencia"])
        e["comps"].add(r["competencia"])
        e["por_ano"].setdefault(r["competencia"][:4], set()).add(r["competencia"])
        if r["valor"]:
            e["valor"] = r["valor"]

    registros, homonimos, fora_rio = [], 0, 0
    gab_cache: dict[int, str] = {}
    nomes_com_benef = set(nome_de)
    for nn in nomes_com_benef:
        fr = frags_rio.get(nn)
        if not fr:                    # tinha benefício, mas nenhum no município do Rio
            fora_rio += 1
            continue
        if len(fr) != 1:              # homônimo dentro do próprio Rio (fragmentos distintos) → fora
            homonimos += 1
            continue
        frag = next(iter(fr))
        e = pessoa[(nn, frag)]
        info = _orgaos_do_nome(p, nn)
        if info["poder"] == "(poder não identificado)":
            continue  # nome do alvo que é só sócio de fornecedor (não servidor) → outro relatório
        # nº de identidades de servidor com esse nome (matrículas na folha + presença na Câmara):
        # 1 => atribuição limpa; >1 => há mais de um servidor homônimo, atribuição incerta.
        try:
            n_mat = p.execute("SELECT COUNT(DISTINCT matricula) FROM pcrj_folha_pref WHERE nome_norm=?",
                              (nn,)).fetchone()[0]
        except Exception:
            n_mat = 0
        em_camara = info["poder"].startswith("Câmara")
        n_serv = max(n_mat, 0) + (1 if (em_camara and n_mat == 0) else 0)
        # ALTA exige: um único servidor com o nome E um fragmento de CPF legível (não vazio).
        certeza = "ALTA" if (n_serv <= 1 and frag != "?") else "MÉDIA"
        ativo = eh_ativo(info["tipo_folha"]) if info["tipo_folha"] else em_camara

        titular = ""
        if info["gab"] is not None:
            if info["gab"] not in gab_cache:
                g = p.execute("SELECT titular FROM pcrj_gabinetes WHERE gabinete_num=?",
                              (info["gab"],)).fetchone()
                gab_cache[info["gab"]] = (g["titular"] if g else "") or ""
            titular = gab_cache[info["gab"]]
        comps_ord = sorted(e["comps"])
        topo = _orgao_topo({"orgao": info["orgao"]})
        if titular and topo.lower().startswith("gabinete"):
            topo = f"{topo} — {titular}"
        # trajetória por programa: "BPC (mai/23→abr/24), Bolsa Família (mai/24→mai/26)"
        progs = []
        for ben, cs in sorted(e["prog"].items(), key=lambda kv: min(kv[1])):
            cs = sorted(cs)
            progs.append({"ben": ben, "desde": _comp_legivel(cs[0]), "ate": _comp_legivel(cs[-1]),
                          "n": len(cs)})
        registros.append({
            "nome": nome_de[nn], "nome_norm": nn, "cpf_frag": frag,
            "poder": info["poder"], "orgao": info["orgao"], "cargo": info["cargo"],
            "vinculo": info["vinculo"], "ingresso": info["ingresso"], "gab_titular": titular,
            "partido": _partido_de(p, nn),
            "programas": progs,
            "beneficios_str": ", ".join(pr["ben"] for pr in progs),
            "desde": _comp_legivel(comps_ord[0]), "ate": _comp_legivel(comps_ord[-1]),
            "n_meses": len(e["comps"]),
            "por_ano": {a: len(e["por_ano"].get(a, set())) for a in anos},
            "ainda_recebe": (comps_ord[-1] == ultima),
            "rio": True, "certeza": certeza, "n_serv": n_serv,
            "ativo": ativo, "situacao": "ativo/nomeado" if ativo else "aposent./pensão",
            "_orgao_topo": topo,
        })

    # ── EIXO B: fantasma de gabinete (comissionado que atravessa a legislatura) ──────────
    fantasmas = []
    for r in p.execute(
            "SELECT nome, nome_norm, cargo, vinculo, data1, gabinete_num, lotacao "
            "FROM pcrj_camara_servidores WHERE gabinete_num IS NOT NULL"):
        vinc = (r["vinculo"] or "").lower()
        if not any(v in vinc for v in _VINCULO_COMISSIONADO):
            continue
        iy = _ingresso_ym(r["data1"])
        if not iy or iy >= _LEGISLATURA_YM:
            continue  # entrou já na legislatura atual — sem sinal
        tit = gab_cache.get(r["gabinete_num"])
        if tit is None:
            g = p.execute("SELECT titular FROM pcrj_gabinetes WHERE gabinete_num=?",
                          (r["gabinete_num"],)).fetchone()
            tit = (g["titular"] if g else "") or ""
            gab_cache[r["gabinete_num"]] = tit
        eh_livre = "livre" in vinc  # livre nomeação = comissionado puro (sinal mais forte)
        fantasmas.append({
            "nome": r["nome"], "cargo": r["cargo"] or "", "ingresso": r["data1"] or "",
            "vinculo": r["vinculo"] or "", "eh_livre": eh_livre,
            "gabinete": r["lotacao"] or f"Gabinete {r['gabinete_num']}",
            "titular_atual": tit, "partido": _partido_de(p, r["nome_norm"]),
        })
    # livre nomeação primeiro (sinal forte), depois por titular e ingresso
    fantasmas.sort(key=lambda x: (not x["eh_livre"], x["titular_atual"], x["ingresso"]))

    b.close(); p.close()
    _ordem = {"ALTA": 0, "MÉDIA": 1}
    registros.sort(key=lambda x: (_ordem.get(x["certeza"], 9), not x["ainda_recebe"],
                                  -x["n_meses"], x["nome"]))

    # agrupa o eixo A por órgão
    por_orgao: dict[str, list] = {}
    for r in registros:
        por_orgao.setdefault(r["_orgao_topo"], []).append(r)
    grupos = sorted(por_orgao.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    def _tem(reg, sub):
        return any(sub in pr["ben"] for pr in reg["programas"])

    return {
        "competencias": comps, "anos": anos, "ultima": ultima,
        "registros": registros, "grupos": grupos,
        "homonimos": homonimos, "fora_rio": fora_rio,
        "fantasmas": fantasmas,
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
    <div class="kpi"><div class="n">{{ n_alta }}</div><div class="l">certeza ALTA (1 pessoa, 1 servidor)</div></div>
    <div class="kpi"><div class="n">{{ n_ainda }}</div><div class="l">ainda recebendo em {{ ultima }}</div></div>
    <div class="kpi"><div class="n">{{ n_bpc }}</div><div class="l">BPC/LOAS</div></div>
    <div class="kpi"><div class="n">{{ n_bf }}</div><div class="l">Bolsa Família</div></div>
    <div class="kpi"><div class="n">{{ n_ab }}</div><div class="l">Auxílio Brasil</div></div>
    <div class="kpi"><div class="n">{{ n_ae }}</div><div class="l">Auxílio Emergencial</div></div>
    <div class="kpi"><div class="n">{{ n_fantasmas }}</div><div class="l">fantasmas de gabinete (proxy)</div></div>
  </div>

  <h2>1. Nomeados recebendo benefício assistencial durante a nomeação — por órgão</h2>
  <p class="nota">Identidade da pessoa unificada por (nome + fragmento de CPF) entre <b>todos</b> os
  programas, restrita a benefício pago <b>no município do Rio</b> (afasta o homônimo de outro
  estado). <b>Certeza ALTA</b> = um único beneficiário e um único servidor com o nome; <b>MÉDIA</b>
  = beneficiário único, mas há mais de um servidor homônimo (qual deles é incerto). As colunas de
  ano contam meses com benefício; a coluna Programas traz a trajetória com datas.</p>
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

  <h2>2. Sinal de fantasma de gabinete (Câmara) — comissionado que atravessou a virada de legislatura</h2>
  <p class="nota">Comissionados (livre nomeação / requisitados) lotados em gabinete cujo ingresso é
  anterior a 01/2025 — ou seja, permaneceram apesar da posse dos titulares eleitos em 2024. É o
  padrão de "servidor que não serve a um mandato específico". Não é prova: o histórico exato de
  quando cada titular/suplente esteve no exercício só consta dos atos de licença no Diário Oficial
  (não estruturado); aqui usa-se a troca de legislatura como marco verificável.</p>
  <table>
    <tr><th>#</th><th>Nome</th><th>Gabinete (titular atual)</th><th>Cargo</th><th>Vínculo</th><th>Partido</th><th>Ingresso (anterior a 2025)</th></tr>
    {% for f in fantasmas %}
    <tr><td>{{ loop.index }}</td><td>{{ f.nome }}</td><td>{{ f.gabinete }} — {{ f.titular_atual }}</td>
        <td>{{ f.cargo }}</td><td>{% if f.eh_livre %}<span class="tag sim">livre nomeação</span>{% else %}{{ f.vinculo }}{% endif %}</td>
        <td><span class="part">{{ f.partido }}</span></td><td>{{ f.ingresso }}</td></tr>
    {% endfor %}
  </table>

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
  <p><b>Ressalvas.</b> A filiação partidária é a foto pública de 2018 (cobertura parcial — "—" =
  não consta na base de 2018). O eixo de fantasmas usa a virada de legislatura (01/2025) como proxy
  verificável, na ausência do histórico estruturado de titular/suplente (que só existe nos atos de
  licença do Diário Oficial). Apuração formal compete aos órgãos de controle e ao Ministério
  Público.</p>

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
        n_fantasmas=len(dados["fantasmas"]), homonimos=dados["homonimos"], fora_rio=dados["fora_rio"],
        grupos=dados["grupos"], fantasmas=dados["fantasmas"],
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
