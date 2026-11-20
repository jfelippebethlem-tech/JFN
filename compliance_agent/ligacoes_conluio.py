# -*- coding: utf-8 -*-
"""Ligações novas entre fornecedores que JÁ são nós da galáxia — semelhança calculada para achar conluio.

Pedido do dono (18/11/2026): "calcular semelhanças entre milhares de fornecedores e sócios para achar
conluio". Três tipos de aresta, todos entre dois CNPJs de RAÍZES distintas (filial não é outra empresa)
e todos com estado `indício a verificar` — ligação é hipótese de relação, nunca prova:

  · `contato` — o mesmo telefone ou o mesmo e-mail no cadastro CNPJ da Receita
    (`receita_estab.db › estabelecimentos`: telefone1, telefone2, correio_eletronico).
  · `socio_variante` — o MESMO sócio grafado diferente: nome muito parecido (rapidfuzz) E os seis
    dígitos visíveis do CPF mascarado iguais. Nome idêntico já é a aresta `socio` da galáxia; nome
    parecido com dígitos diferentes é homônimo e nunca casa.
  · `concorrentes_ligados` — dois fornecedores que estiveram no MESMO certame e têm qualquer vínculo
    (sócio, sócio variante, endereço, contato). A aresta diz qual certame e qual vínculo.

LIMIARES — MEDIDOS NA BASE REAL EM 18/11/2026 (4.627 CNPJs da galáxia, 4.235 com registro na Receita):

  Telefone. Fan-out = quantas RAÍZES usam o número na base de 6,17 mi estabelecimentos (`telefone1`,
  o campo indexado) somadas às da galáxia que o têm em qualquer dos dois campos. Dos 3.916 telefones
  válidos da galáxia: 2.279 são de 1 raiz, 428 de 2, 162 de 3, 84 de 4, 61 de 5 — e de 6 a 10 a
  contagem fica achatada (13 a 26 por degrau) até a cauda de 440 números usados por 11 a 200+ raízes
  (central de atendimento, contabilidade). O joelho está em 5: `TETO_TELEFONE = 5`, o mesmo
  `TETO_FANOUT` que `osint/contato_compartilhado` mediu no país inteiro (345.782 números ligam
  exatamente 2 empresas, 100.242 ligam de 3 a 5).
  E-mail. Dos 2.886 e-mails não-de-serviço: 2.296 de 1 raiz, 244 de 2, 78 de 3, 42 de 4, 23 de 5,
  13–16 de 6 a 8, e cauda de 151 acima de 8. `TETO_EMAIL = 8` (`TETO_FANOUT_EMAIL` da casa: grupo
  econômico real usa uma caixa só, contador médio tem dezenas de clientes). E-mail de prestador de
  serviço (`_de_servico`: contabilidade, abertura de empresa — 267 na galáxia) nunca liga ninguém.
  Domínio genérico (gmail, hotmail…) só vale pelo ENDEREÇO COMPLETO: esta aresta nunca compara
  domínio, só a caixa inteira.
  Sócio. Dos pares (raízes distintas, mesmos 6 dígitos, nome DIFERENTE) da galáxia, a semelhança
  máxima medida foi 56,6/100 — todos são colisão de dígitos entre pessoas distintas (a casa já mediu
  ~4% de colisão na máscara). Nenhum par ficou entre 57 e 100, então `LIMIAR_NOME = 90` não está
  na fronteira de nada: qualquer corte entre 57 e 99 daria o mesmo resultado na base de hoje.

Nada de pessoa física vira nó; CPF nunca sai — nem os dígitos visíveis: a evidência diz "mesmos
dígitos visíveis", não quais. Telefone e e-mail saem PARCIALMENTE mascarados (conferência: cadastro
CNPJ da Receita pelos dois CNPJs).
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import defaultdict
from itertools import combinations

from compliance_agent.osint.contato_compartilhado import (
    TETO_FANOUT, TETO_FANOUT_EMAIL, _de_servico, normalizar_telefone, telefone_valido)
from compliance_agent.osint.marca_grupo import mesmo_grupo

__all__ = ["TETO_TELEFONE", "TETO_EMAIL", "LIMIAR_NOME", "ESTADO", "contatos", "registros_socios",
           "socios_identicos", "socios_variantes", "participacoes", "concorrentes_ligados", "levantar"]

TETO_TELEFONE = TETO_FANOUT          # 5 raízes — medido (docstring)
TETO_EMAIL = TETO_FANOUT_EMAIL       # 8 raízes — medido (docstring)
LIMIAR_NOME = 90                     # rapidfuzz.ratio sem partículas, 0–100 — medido (docstring)
ESTADO = "indício a verificar"
_LOTE = 900
_PARTICULAS = {"DA", "DE", "DO", "DAS", "DOS", "E"}
_RE_MASC = re.compile(r"^\*{3}(\d{6})\*{2}$")


from compliance_agent.cpf_cnpj import digitos as _dig  # noqa: E402


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s.upper())).strip()


def _lotes(seq, n=_LOTE):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def representantes(cnpjs) -> dict[str, str]:
    """Raiz → um CNPJ (a matriz 0001 quando está entre os nós; senão o menor)."""
    rep: dict[str, str] = {}
    for c in sorted(cnpjs):
        r = rep.get(c[:8])
        if r is None or (c[8:12] == "0001" and r[8:12] != "0001"):
            rep[c[:8]] = c
    return rep


def _mascara_tel(t: str) -> str:
    return f"({t[:2]}) {t[2:-4]}-****" if len(t) >= 10 else t[:-4] + "****"


def _mascara_mail(e: str) -> str:
    local, dom = e.rsplit("@", 1)
    return f"{local[:2]}***@{dom}"


# ── 1. contato ──────────────────────────────────────────────────────────────────────────────────

def contatos(estab: sqlite3.Connection, cnpjs) -> dict:
    """Pares de raízes (da galáxia) com o mesmo telefone ou e-mail, já filtrados por fan-out medido.

    Devolve `{"pares": {(raiz_a, raiz_b): [via, ...]}, "medida": {...}}`. Descarte nunca é silencioso:
    `medida` conta cada motivo.
    """
    cnpjs = sorted({c for c in cnpjs if len(c) == 14})
    tel_de: dict[str, set] = defaultdict(set)       # telefone normalizado → raízes da galáxia
    tel_cru: dict[str, set] = defaultdict(set)      # telefone normalizado → valores crus (para o índice)
    mail_de: dict[str, set] = defaultdict(set)
    mail_cru: dict[str, set] = defaultdict(set)
    med = {"cnpjs": len(cnpjs), "com_registro": 0, "telefone_invalido": 0, "email_de_servico": 0,
           "telefone_acima_do_teto": 0, "email_acima_do_teto": 0, "telefones_compartilhados": 0,
           "emails_compartilhados": 0, "teto_telefone": TETO_TELEFONE, "teto_email": TETO_EMAIL}
    for lote in _lotes(cnpjs):
        for c, t1, t2, em in estab.execute(
                "SELECT cnpj, telefone1, telefone2, correio_eletronico FROM estabelecimentos "
                f"WHERE cnpj IN ({','.join('?' * len(lote))})", lote):
            med["com_registro"] += 1
            for cru in {t1, t2}:
                t = normalizar_telefone(cru)
                if not t:
                    continue
                if not telefone_valido(t):
                    med["telefone_invalido"] += 1
                    continue
                tel_de[t].add(c[:8])
                tel_cru[t].add(str(cru))
            e = str(em or "").strip()
            if "@" in e:
                if _de_servico(e):
                    med["email_de_servico"] += 1
                    continue
                mail_de[e.lower()].add(c[:8])
                mail_cru[e.lower()].add(e)

    def fanout(coluna: str, crus: set, da_galaxia: set) -> int:
        raizes = set(da_galaxia)
        for v in crus:
            raizes.update(r[0] for r in estab.execute(
                f"SELECT substr(cnpj, 1, 8) FROM estabelecimentos WHERE {coluna} = ? LIMIT 500", (v,)))
        return len(raizes)

    pares: dict[tuple, list] = defaultdict(list)
    for chave, de, crus, coluna, teto, rot, masc in (
            ("telefone", tel_de, tel_cru, "telefone1", TETO_TELEFONE, "mesmo telefone", _mascara_tel),
            ("email", mail_de, mail_cru, "correio_eletronico", TETO_EMAIL, "mesmo e-mail", _mascara_mail)):
        for v, raizes in de.items():
            if len(raizes) < 2:
                continue
            med[f"{chave}s_compartilhados"] += 1
            n = fanout(coluna, crus[v], raizes)
            if n > teto:
                med[f"{chave}_acima_do_teto"] += 1
                continue
            for a, b in combinations(sorted(raizes), 2):
                pares[(a, b)].append({"tipo": chave, "via": f"{rot} {masc(v)}", "raizes_que_usam": n})
    return {"pares": dict(pares), "medida": med}


# ── 2. sócio ────────────────────────────────────────────────────────────────────────────────────

def registros_socios(con: sqlite3.Connection, cnpjs) -> tuple[list[tuple[str, str, str, str]], dict]:
    """(raiz, nome normalizado, tipo_doc, chave_doc) do QSA público — `socios_fornecedor` por CNPJ e
    `socios_receita` por raiz — e o estado de cada fonte. tipo_doc ∈ {pf, pj, sem}; chave_doc = 6
    dígitos visíveis (pf), raiz do CNPJ sócio (pj) ou vazio. A chave fica DENTRO do módulo; nunca vai
    para a saída."""
    cnpjs = sorted({c for c in cnpjs if len(c) == 14})
    raizes = sorted({c[:8] for c in cnpjs})
    regs = set()
    fontes = {}

    def doc(d):
        d = str(d or "").strip()
        m = _RE_MASC.match(d)
        if m:
            return "pf", m.group(1)
        dd = _dig(d)
        if len(dd) in (8, 14) and "*" not in d:
            return "pj", dd[:8]
        return "sem", ""

    try:
        for lote in _lotes(cnpjs):
            for c, nome, d in con.execute(
                    "SELECT cnpj, socio_nome_norm, socio_doc FROM socios_fornecedor "
                    f"WHERE cnpj IN ({','.join('?' * len(lote))})", lote):
                n = _norm(nome)
                if n and not n.startswith("SEM QSA"):
                    regs.add((c[:8], n, *doc(d)))
        fontes["socios_fornecedor"] = "ok"
    except sqlite3.OperationalError:           # tabela ausente: a outra fonte segue, e o estado sai
        fontes["socios_fornecedor"] = "INDISPONÍVEL"
    try:
        for lote in _lotes(raizes):
            for b, nome, d in con.execute(
                    "SELECT cnpj_basico, nome_norm, doc_socio FROM socios_receita "
                    f"WHERE cnpj_basico IN ({','.join('?' * len(lote))})", lote):
                n = _norm(nome)
                if n:
                    regs.add((b, n, *doc(d)))
        fontes["socios_receita"] = "ok"
    except sqlite3.OperationalError:
        fontes["socios_receita"] = "INDISPONÍVEL"
    return sorted(regs), fontes


def socios_identicos(regs) -> dict[tuple, list]:
    """Mesmo sócio em raízes distintas, pelo documento: PF = mesmo nome E mesmos dígitos visíveis
    (nome igual com dígitos diferentes é HOMÔNIMO e não liga); PJ = mesmo CNPJ sócio; sem documento
    num dos lados = mesmo nome, marcado `documento_indisponivel`."""
    por_nome = defaultdict(list)
    por_pj = defaultdict(set)
    for raiz, nome, tipo, chave in regs:
        por_nome[nome].append((raiz, tipo, chave))
        if tipo == "pj":
            por_pj[chave].add((raiz, nome))
    pares = defaultdict(list)
    for nome, ocorr in por_nome.items():
        for (ra, ta, ka), (rb, tb, kb) in combinations(sorted(set(ocorr)), 2):
            sem_doc = "sem" in (ta, tb)
            if ra == rb or not (sem_doc or (ta == tb == "pf" and ka == kb)):
                continue                          # homônimo (CPF diferente) nunca casa; PJ casa abaixo
            par = tuple(sorted((ra, rb)))
            pares[par].append({"tipo": "socio", "via": f"sócio em comum {nome}"
                               + (" (documento indisponível num dos lados)" if sem_doc else "")})
    for _, ocorr in por_pj.items():
        for (ra, na), (rb, nb) in combinations(sorted(ocorr), 2):
            if ra != rb:
                pares[tuple(sorted((ra, rb)))].append({"tipo": "socio", "via": f"sócio PJ em comum {na}"})
    return {k: _dedup(v) for k, v in pares.items()}


def _sem_particulas(n: str) -> str:
    return " ".join(t for t in n.split() if t not in _PARTICULAS)


def socios_variantes(regs, limiar: int = LIMIAR_NOME) -> dict[tuple, list]:
    """Mesmo sócio grafado diferente: mesmos 6 dígitos visíveis, nome NÃO idêntico, semelhança ≥ limiar."""
    from rapidfuzz import fuzz
    por_dig = defaultdict(set)
    for raiz, nome, tipo, chave in regs:
        if tipo == "pf":
            por_dig[chave].add((raiz, nome))
    pares = defaultdict(list)
    for _, ocorr in por_dig.items():
        for (ra, na), (rb, nb) in combinations(sorted(ocorr), 2):
            if ra == rb or na == nb:
                continue
            sim = fuzz.ratio(_sem_particulas(na), _sem_particulas(nb))
            if sim < limiar:
                continue
            a, b = (ra, na), (rb, nb)
            if ra > rb:
                a, b = b, a
            pares[(a[0], b[0])].append({
                "tipo": "socio_variante", "semelhanca": round(sim, 1),
                "via": f"sócio grafado «{a[1]}» e «{b[1]}» — mesmos dígitos visíveis do CPF mascarado, "
                       f"semelhança {sim:.0f}/100"})
    return {k: _dedup(v) for k, v in pares.items()}


def _dedup(vs: list) -> list:
    vistos, out = set(), []
    for v in vs:
        if v["via"] not in vistos:
            vistos.add(v["via"])
            out.append(v)
    return out


# ── 3. certames ─────────────────────────────────────────────────────────────────────────────────

def _razao_unica(estab: sqlite3.Connection, raizes) -> dict[str, str]:
    """Razão social normalizada → raiz, só quando a razão é ÚNICA entre as raízes da Receita
    (`empresas`, 29,3 mi) e entre as da galáxia. Razão repetida não resolve — não se adivinha."""
    razao = {}
    for lote in _lotes(sorted(raizes)):
        for b, r in estab.execute("SELECT cnpj_basico, razao_social FROM empresas "
                                  f"WHERE cnpj_basico IN ({','.join('?' * len(lote))})", lote):
            if r:
                razao[b] = r
    cont = defaultdict(int)
    for r in razao.values():
        cont[_norm(r)] += 1
    out = {}
    for b, r in razao.items():
        n = _norm(r)
        if cont[n] == 1 and estab.execute("SELECT COUNT(*) FROM empresas WHERE razao_social = ?",
                                          (r,)).fetchone()[0] == 1:
            out[n] = b
    return out


def participacoes(con: sqlite3.Connection, estab: sqlite3.Connection | None, cnpjs) -> dict:
    """Certames com 2+ raízes da galáxia. `{"certames": {chave: {...}}, "fontes": {...}}`.

    Fontes (contadas em 18/11/2026): `pncp_resultado` (82.987 linhas; resultado homologado por item —
    os dois têm resultado no MESMO certame), `proposta_item` só `sei_proposta`/`ata` (proposta nos
    autos; `sei_precos` é pesquisa de preço, não disputa) e `tcerj_licitante` (126.251 linhas, vencedor
    E perdedor, mas só pelo NOME — resolvido para CNPJ só por razão social única na Receita).
    """
    gs = {c for c in cnpjs if len(c) == 14}
    raizes = {c[:8] for c in gs}
    cert: dict[str, dict] = {}
    fontes = {}

    def add(chave, fonte, rotulo, orgao, objeto, raiz):
        d = cert.setdefault(chave, {"fonte": fonte, "certame": rotulo, "orgao": (orgao or "")[:90],
                                    "objeto": (objeto or "")[:140], "raizes": set()})
        d["raizes"].add(raiz)

    try:
        for c_, doc, org, obj in con.execute(
                "SELECT certame, fornecedor_cnpj, orgao_nome, objeto FROM pncp_resultado "
                "WHERE fornecedor_cnpj IS NOT NULL"):
            if doc in gs:
                add(f"pncp:{c_}", "PNCP (resultado homologado)", c_, org, obj, doc[:8])
        fontes["pncp_resultado"] = "ok"
    except sqlite3.OperationalError:
        fontes["pncp_resultado"] = "INDISPONÍVEL"
    try:
        for c_, doc, fonte in con.execute("SELECT certame, fornecedor_cnpj, fonte FROM proposta_item "
                                          "WHERE fonte IN ('sei_proposta', 'ata')"):
            if doc in gs:
                add(f"sei:{c_}", "proposta nos autos (SEI)", c_, "", "", doc[:8])
        fontes["proposta_item"] = "ok"
    except sqlite3.OperationalError:
        fontes["proposta_item"] = "INDISPONÍVEL"
    if estab is None:
        fontes["tcerj_licitante"] = "INDISPONÍVEL (sem a Receita para resolver o nome)"
    else:
        try:
            unico = _razao_unica(estab, raizes)
            for ente, ano, proc, part, obj in con.execute(
                    "SELECT ente, ano, processo, participante, objeto FROM tcerj_licitante"):
                b = unico.get(_norm(part))
                if b:
                    add(f"tcerj:{ente}|{ano}|{proc}", "TCE-RJ licitantes (por razão social única)",
                        f"{proc} ({ano})", ente, obj, b)
            fontes["tcerj_licitante"] = "ok"
        except sqlite3.OperationalError:
            fontes["tcerj_licitante"] = "INDISPONÍVEL"
    return {"certames": {k: v for k, v in cert.items() if len(v["raizes"]) >= 2}, "fontes": fontes}


def concorrentes_ligados(certames: dict, vinculos: dict[tuple, list], nomes: dict | None = None) -> dict:
    """Par de raízes no MESMO certame que tem vínculo. `{(a, b): {"certames": [...], "vinculos": [...]}}`."""
    nomes = nomes or {}
    out: dict[tuple, dict] = {}
    for chave in sorted(certames):
        c = certames[chave]
        for a, b in combinations(sorted(c["raizes"]), 2):
            v = vinculos.get((a, b))
            if not v:
                continue
            d = out.setdefault((a, b), {"certames": [], "vinculos": v,
                                        "mesmo_grupo_aparente": mesmo_grupo(nomes.get(a, ""), nomes.get(b, ""))})
            d["certames"].append({k: c[k] for k in ("fonte", "certame", "orgao", "objeto")})
    return out


# ── junção ──────────────────────────────────────────────────────────────────────────────────────

def levantar(con: sqlite3.Connection | None, estab: sqlite3.Connection | None, cnpjs,
             end_grupos: dict[str, set] | None = None, nomes: dict[str, str] | None = None) -> dict:
    """As três famílias de aresta, por par de RAÍZES, mais a medida de cada uma.

    `end_grupos`: CNPJ → rótulos de endereço compartilhado que a galáxia já tem (hub/d12). `nomes`:
    CNPJ → razão social (para marcar grupo econômico aparente — marca, não absolve).
    Devolve `{"arestas": [{"a": raiz, "b": raiz, "tipo", "peso", "det", "ev"}], "medida", "fontes"}`.
    """
    cnpjs = sorted({c for c in cnpjs if len(c) == 14})
    fontes, medida, arestas = {}, {}, []
    nomes_r = {}
    for c in cnpjs:
        if (nomes or {}).get(c):
            nomes_r.setdefault(c[:8], nomes[c])

    ct = {"pares": {}, "medida": {}}
    if estab is None:
        fontes["contato_receita"] = "INDISPONÍVEL"
    else:
        try:
            ct = contatos(estab, cnpjs)
            fontes["contato_receita"] = "ok"
        except sqlite3.OperationalError:
            fontes["contato_receita"] = "INDISPONÍVEL"
    medida["contato"] = ct["medida"]

    regs, f_qsa = registros_socios(con, cnpjs) if con is not None else ([], {"socios_fornecedor": "INDISPONÍVEL"})
    fontes.update(f_qsa)
    ident = socios_identicos(regs)
    var = socios_variantes(regs)
    medida["socio"] = {"registros": len(regs), "pares_socio_identico_por_documento": len(ident),
                       "pares_socio_variante": len(var), "limiar_nome": LIMIAR_NOME}

    end = defaultdict(list)
    por_raiz = defaultdict(set)
    for c, gs in (end_grupos or {}).items():
        por_raiz[c[:8]].update(gs)
    for a, b in combinations(sorted(por_raiz), 2):
        for rot in sorted(por_raiz[a] & por_raiz[b]):
            end[(a, b)].append({"tipo": "endereco", "via": rot})

    for (a, b), vs in sorted(ct["pares"].items()):
        arestas.append({"a": a, "b": b, "tipo": "contato", "peso": float(len(vs)),
                        "det": " · ".join(v["via"] for v in vs) + " (cadastro CNPJ da Receita)",
                        "ev": {"vias": vs, "fonte": "receita_estab.estabelecimentos"}})
    for (a, b), vs in sorted(var.items()):
        arestas.append({"a": a, "b": b, "tipo": "socio_variante", "peso": 1.0,
                        "det": " · ".join(v["via"] for v in vs) + " (QSA público)",
                        "ev": {"vias": vs, "fonte": "socios_fornecedor / socios_receita"}})

    vinculos: dict[tuple, list] = defaultdict(list)
    for fonte_v in (ident, var, end, ct["pares"]):
        for par, vs in fonte_v.items():
            vinculos[par] += vs
    pt = participacoes(con, estab, cnpjs) if con is not None else {"certames": {}, "fontes": {}}
    fontes.update(pt["fontes"])
    cl = concorrentes_ligados(pt["certames"], vinculos, nomes_r)
    for (a, b), d in sorted(cl.items()):
        n = len(d["certames"])
        tipos_v = sorted({v["tipo"] for v in d["vinculos"]})
        c0 = d["certames"][0]
        det = (f"{n} certame(s) em comum — ex.: {c0['certame']}"
               + (f" ({c0['orgao']})" if c0["orgao"] else "") + f" [{c0['fonte']}]"
               + " · vínculo: " + "; ".join(v["via"] for v in d["vinculos"][:3])
               + (" · grupo econômico aparente: " + d["mesmo_grupo_aparente"] if d["mesmo_grupo_aparente"] else ""))
        arestas.append({"a": a, "b": b, "tipo": "concorrentes_ligados", "peso": float(n), "det": det,
                        "ev": {"n_certames": n, "certames": d["certames"][:5], "vinculos": d["vinculos"][:6],
                               "tipos_vinculo": tipos_v, "mesmo_grupo_aparente": d["mesmo_grupo_aparente"]}})
    medida["certames"] = {"certames_com_2_ou_mais_nos": len(pt["certames"]),
                          "por_fonte": {f: sum(1 for k in pt["certames"] if k.startswith(f + ":"))
                                        for f in ("pncp", "sei", "tcerj")},
                          "pares_concorrentes_ligados": len(cl)}
    for e in arestas:
        e["estado"] = ESTADO
    return {"arestas": arestas, "medida": medida, "fontes": fontes}
