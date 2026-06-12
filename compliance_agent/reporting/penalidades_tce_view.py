# -*- coding: utf-8 -*-
"""Sanções do TCE-RJ (`penalidades_tcerj`) por UG, para o relatório de órgão — com INTELIGÊNCIA de vínculo.

O TCE-RJ é o controle externo do Estado: multas e débitos imputados a órgãos/entes são o sinal mais DIRETO
de irregularidade já reconhecida pela Corte de Contas. O dado estava parado por falta de chave de join: o TCE
usa nome abreviado ("SEC EST SAÚDE", "DETRAN-...") e o relatório é por código de UG.

**Por que não um dict chumbado:** secretarias e órgãos mudam de NOME e de UG com frequência (fusões, extinções,
re-codificações). Um mapa fixo apodrece e vira mentira. Aqui o vínculo é **re-derivado dos dados vivos** por um
auto-matcher e **auto-auditado** (`depurar`), com uma camada pequena de overrides só para o que a heurística erra.

Inteligência do auto-matcher (honestidade > recall):
- **Similaridade de tokens com prefixo** ("DEPART"≈"DEPARTAMENTO", "ASSIST"≈"ASSISTENCIA") — acompanha abreviação.
- **Discriminador de TIPO de entidade** (SECRETARIA ≠ FUNDO ≠ FUNDAÇÃO ≠ EMPRESA ≠ INSTITUTO ≠ TRIBUNAL…). Isso
  evita o erro clássico: a sanção do "TRIBUNAL DE JUSTICA" cairia no "Fundo Especial do TJ" porque o nome do FUNDO
  contém os tokens do órgão — o tipo desempata para o órgão certo.
- **Bônus de acrônimo** quando o acrônimo do TCE aparece como token no nome da UG (PRODERJ, FES).
- **Marcador temporal:** "(EXTINTA)/em Extinção/em Liquidação" → sanção é **histórica**; sucessão a confirmar,
  nunca imputada automaticamente à gestão atual.

Overrides curados = só as **exceções não-deriváveis**: 1 órgão→N UGs (reorganização), sucessões sem tokens em
comum (AGE→Controladoria), e órgãos do TCE **sem UG** no canônico (CEDAE) → sem âncora (o dado não some, só não
tem relatório-alvo). `confianca`: **alta** (match forte/tipo OK) | **media** (incerto — ressalva no texto).

Honestidade (regra-mãe): a sanção do TCE é FATO já julgado (não indício nosso). DÉBITO = imputação de devolução;
MULTA = penalidade. Reportamos o que a Corte decidiu, citando processo e sessão. INDISPONÍVEL ≠ ausência.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

_DB = Path("data") / "compliance.db"
_UG_CANONICO = Path("data") / "ug_canonico.json"

# ───────────────────────── normalização e tokens ─────────────────────────
_STOP = {"DE", "DA", "DO", "DOS", "DAS", "E", "RJ", "ERJ", "ESTADO", "EST", "A", "O", "EM",
         "RIO", "JANEIRO", "SA", "S", "AO", "AOS", "DOEST", "P"}
# expansão de abreviações comuns do TCE/SIAFE (prefixo já cobre a maioria; estes são os irregulares)
_SYN = {"SEC": "SECRETARIA", "FUND": "FUNDACAO", "FUNDAÇÃO": "FUNDACAO", "DEPART": "DEPARTAMENTO",
        "DEPTO": "DEPARTAMENTO", "DEP": "DEPARTAMENTO", "EMP": "EMPRESA", "CIA": "COMPANHIA",
        "COMP": "COMPANHIA", "INST": "INSTITUTO", "SUPERINT": "SUPERINTENDENCIA", "ASSIST": "ASSISTENCIA",
        "TECN": "TECNICA", "TRANSP": "TRANSPORTE", "RODOV": "RODOVIARIO", "DESENV": "DESENVOLVIMENTO",
        "PESQ": "PESQUISA", "AGROPEC": "AGROPECUARIA", "SOC": "SOCIAL", "PUB": "PUBLICO",
        "SERV": "SERVIDORES", "REG": "REGULADORA", "ACÕES": "ACOES", "ACOES": "ACOES"}
# marcadores de descontinuidade temporal (sanção histórica; sucessão a confirmar)
_EXTINTO_RE = re.compile(r"EXTIN|LIQUIDAC|EM EXTINC")


def _strip(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()


def _tokens(s: str) -> list[str]:
    base = re.sub(r"[^A-Z]+", " ", _strip(s))
    out: list[str] = []
    for w in base.split():
        w = _SYN.get(w, w)
        if w in _STOP or len(w) < 3:
            continue
        out.append(w)
    return out


def _acronimo(orgao: str) -> str:
    """Acrônimo do TCE = primeiro pedaço antes de '-' ou '/' se parecer sigla (>=3 letras, sem espaço)."""
    head = re.split(r"[-/]", orgao.strip(), 1)[0].strip()
    head = _strip(head)
    return head if (3 <= len(head) <= 14 and " " not in head and head.isalpha()) else ""


_TIPOS = (
    ("FUNDO", ("FUNDO",)),
    ("FUNDACAO", ("FUNDACAO",)),
    ("EMPRESA", ("EMPRESA", "COMPANHIA")),
    ("INSTITUTO", ("INSTITUTO",)),
    ("SUPERINTENDENCIA", ("SUPERINTENDENCIA",)),
    ("AGENCIA", ("AGENCIA",)),
    ("TRIBUNAL", ("TRIBUNAL",)),
    ("DEPARTAMENTO", ("DEPARTAMENTO",)),
    ("JUNTA", ("JUNTA",)),
    ("CONTROLADORIA", ("CONTROLADORIA", "AUDITORIA")),
    ("SECRETARIA", ("SECRETARIA",)),
)


def _tipo(tokens: list[str]) -> str:
    s = set(tokens)
    for nome, gat in _TIPOS:
        if any(g in s for g in gat):
            return nome
    return "OUTRO"


def _tmatch(a: str, b: str) -> bool:
    if a == b:
        return True
    m = min(len(a), len(b))
    return m >= 4 and (a.startswith(b) or b.startswith(a))


def _sim(tce: list[str], ug: list[str]) -> float:
    if not tce:
        return 0.0
    matched = sum(1 for t in tce if any(_tmatch(t, u) for u in ug))
    return matched / len(tce)


# ───────────────────────── carga do canônico (cache) ─────────────────────────
_UG_CACHE: dict | None = None


def _ug_canonico() -> dict[str, str]:
    global _UG_CACHE
    if _UG_CACHE is None:
        try:
            _UG_CACHE = json.loads(Path(_UG_CANONICO).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _UG_CACHE = {}
    return _UG_CACHE


# ───────────────────────── overrides curados (só exceções) ─────────────────────────
# Apenas o que o auto-matcher NÃO deriva sozinho: 1 órgão→N UGs (reorganização), sucessão sem tokens
# comuns, ou ausência de âncora. Mantido MÍNIMO de propósito (o resto se re-deriva dos dados vivos).
# valor: (lista de UGs | None p/ sem-âncora, confianca, nota)
OVERRIDES: dict[str, tuple[list[str] | None, str, str]] = {
    "SEC EST INFRAESTRUTURA E OBRAS (EXTINTA)": (["070100", "530100"], "alta", "mesmo órgão em 2 códigos de UG"),
    "SEC EST INFRAESTRUTURA E CIDADES": (["070100", "530100", "660100"], "media",
                                         "pasta combinada infra+cidades: sanções imputadas tanto às UGs de "
                                         "Infraestrutura/Obras (070100/530100) quanto à sucessora Sec. das Cidades (660100)"),
    "SEC EST SEGURANÇA": (["260100", "260200"], "alta", "segurança em 2 códigos"),
    "UERJ-FUND UNIVERSIDADE DO ESTADO RJ": (["404300", "404350"], "alta", "UERJ em 2 códigos"),
    "AGE-AUDITORIA GERAL DO ESTADO": (["500100"], "media", "AGE = predecessora da Controladoria (CGE)"),
    "RIOPREVIDENCIA - FUNDO DE PREV DO EST RJ": (["123400"], "media", "RioPrevidência ↔ Fundo Único de Previdência"),
    "CORPO DE BOMBEIROS DO ESTADO": (["160100", "166100"], "media", "bombeiros sob Defesa Civil + fundo próprio"),
    "SEC EST SAÚDE E DEFESA CIVIL (EXTINTA)": (["290100"], "media", "fusão extinta; sucessão p/ Saúde"),
    "SEC EST DE FAZENDA E PLANEJAMENTO": (["200100", "210100"], "media", "fazenda+planejamento combinadas"),
    "SEC EST ENVELHEC SAUDE QUAL VIDA": (["290100"], "media", "pasta de envelhecimento/saúde; sem UG própria"),
    "CEDAE-COMPANHIA ESTADUAL AGUAS E ESGOTOS": (None, "media", "CEDAE não é UG do Tesouro no canônico (sem âncora)"),
    # exceções pegas pelo depurar() (auto erra: acrônimo colide com fundo homônimo, ou sigla curta 'Ag'/'Dep'):
    "ALERJ-ASSEMBLEIA LEGISLATIVA": (["010100"], "alta", "ALERJ = a Assembleia, não o Fundo de Previdência homônimo"),
    "AGETRANSP - AGENCIA REG SERV PUB TRANSP": (["043400"], "alta", "agência reguladora de transporte (sigla 'Ag' no canônico)"),
    "DETRO-DEP. DE TRANSPORTES RODOVIARIOS RJ": (["313300"], "alta", "Depto de Transportes Rodoviários (sigla 'Dep' no canônico)"),
    "SEC EST DESENV SOCIAL E DIREITOS HUMANOS": (["490100", "320100"], "media", "desenv. social ↔ assist. social (pastas próximas)"),
}

_LIMIAR_SCORE = 0.6   # similaridade mínima de tokens p/ aceitar auto-match
_LIMIAR_MARGEM = 0.15  # vantagem mínima sobre o 2º colocado p/ confiar


def auto_match(orgao: str) -> dict:
    """Deriva o vínculo órgão-TCE → UG a partir dos dados vivos (tokens + tipo + acrônimo). Sem override."""
    ug = _ug_canonico()
    ot = _tokens(orgao)
    tipo_tce = _tipo(ot)
    acr = _acronimo(orgao)
    ranked: list[tuple[float, str]] = []
    for cod, nome in ug.items():
        ut = _tokens(nome)
        s = _sim(ot, ut)
        if s <= 0:
            continue
        # discriminador de TIPO: concordância soma, divergência (ambos tipados) penaliza forte
        tipo_ug = _tipo(ut)
        if tipo_tce != "OUTRO" and tipo_ug != "OUTRO":
            s += 0.30 if tipo_tce == tipo_ug else -0.35
        # bônus se o acrônimo do TCE aparece literal no nome da UG (PRODERJ, FES)
        if acr and acr in [_strip(x) for x in re.sub(r"[^A-Za-z]+", " ", nome).split()]:
            s += 0.40
        ranked.append((round(s, 3), cod))
    if not ranked:
        return {"ug_codes": [], "score": 0.0, "margem": 0.0, "confianca": "", "fonte": "nenhum"}
    ranked.sort(reverse=True)
    s0, c0 = ranked[0]
    s1 = ranked[1][0] if len(ranked) > 1 else 0.0
    margem = round(s0 - s1, 3)
    # multi-UG do MESMO órgão: 2º empata (mesmo score) e é do mesmo tipo → inclui ambos
    ugs = [c0]
    if len(ranked) > 1 and abs(ranked[1][0] - s0) < 1e-6:
        ugs.append(ranked[1][1])
    ok = s0 >= _LIMIAR_SCORE and (margem >= _LIMIAR_MARGEM or len(ugs) > 1)
    conf = "alta" if (ok and s0 >= 0.85 and margem >= 0.25) else ("media" if ok else "")
    return {"ug_codes": ugs if ok else [], "score": s0, "margem": margem,
            "confianca": conf, "fonte": "auto" if ok else "nenhum"}


def resolver(orgao: str) -> dict:
    """Resolve um órgão-TCE → {ug_codes, confianca, fonte, historico, nota, score}. Override > auto > nenhum."""
    historico = bool(_EXTINTO_RE.search(_strip(orgao)))
    if orgao in OVERRIDES:
        ugs, conf, nota = OVERRIDES[orgao]
        return {"ug_codes": list(ugs) if ugs else [], "confianca": conf, "fonte": "override",
                "historico": historico, "nota": nota, "score": 1.0, "sem_ancora": ugs is None}
    a = auto_match(orgao)
    return {"ug_codes": a["ug_codes"], "confianca": a["confianca"] or "media",
            "fonte": a["fonte"], "historico": historico, "nota": "", "score": a["score"],
            "sem_ancora": False}


# ───────────────────────── agregação por UG ─────────────────────────
def _con(db_path: str | Path | None):
    return sqlite3.connect(f"file:{Path(db_path or _DB)}?mode=ro", uri=True)


def _vazio(motivo: str = "indisponivel", orgaos_tce: list[str] | None = None) -> dict:
    """Resultado vazio. motivo distingue:
    - 'indisponivel': nenhum órgão-TCE mapeia p/ a UG (correspondência nome↔UG não estabelecida) — INDISPONÍVEL;
    - 'sem_sancao': órgão(s)-TCE mapeado(s), porém SEM condenação na base — histórico LIMPO de fato (≠ INDISPONÍVEL)."""
    return {"ok": False, "motivo": motivo, "n_condenacoes": 0, "n_eventos": 0, "n_processos": 0,
            "valor_total": 0.0, "por_tipo": {}, "por_ano": {}, "itens": [], "confianca": "",
            "orgaos_tce": orgaos_tce or [],
            "tem_media": False, "tem_historico": False, "tem_solidaria": False}


def _orgaos_distintos(con) -> list[str]:
    return [r[0] for r in con.execute("SELECT DISTINCT orgao FROM penalidades_tcerj WHERE orgao IS NOT NULL")]


def por_ug(ug: str, db_path: str | Path | None = None) -> dict:
    """Sanções do TCE-RJ imputadas ao órgão desta UG. Resolve os órgãos-TCE pelos dados vivos. Degrada honesto."""
    ug = str(ug).strip()
    try:
        con = _con(db_path)
        try:
            distintos = _orgaos_distintos(con)
            # universo de resolução = órgãos com linhas + chaves curadas nos OVERRIDES (o join curado
            # estabelece a correspondência nome↔UG mesmo que aquele órgão ainda não tenha condenação na base).
            universo = set(distintos) | set(OVERRIDES.keys())
            res = {o: resolver(o) for o in universo}
            nomes = [o for o, r in res.items() if ug in r["ug_codes"]]
            if not nomes:
                # nenhum órgão-TCE (vivo ou curado) mapeia p/ esta UG → correspondência não estabelecida (INDISPONÍVEL)
                return _vazio("indisponivel")
            ph = ",".join("?" * len(nomes))
            rows = con.execute(
                f"""SELECT orgao, processo, ano_condenacao, tipo, valor, condenacao,
                           grupo_natureza, data_sessao
                      FROM penalidades_tcerj WHERE orgao IN ({ph})""", nomes).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — tabela/DB ausente → vazio honesto
        return _vazio("indisponivel")
    if not rows:
        # órgão(s)-TCE mapeado(s) mas SEM condenação na base → histórico limpo de fato (≠ INDISPONÍVEL)
        return _vazio("sem_sancao", orgaos_tce=nomes)

    # DEDUP por EVENTO de condenação (mesmo órgão+processo+valor+sessão+tipo). Responsabilidade SOLIDÁRIA
    # (1 débito imputado a N responsáveis) vem como N linhas idênticas — somar INFLA o erário. Contamos o
    # VALOR uma vez por evento e registramos quantos responsáveis (n_resp). n_condenacoes = linhas brutas
    # (responsáveis julgados); o dinheiro usa o valor por evento (conservador — nunca superestima).
    eventos: dict[tuple, dict] = {}
    for orgao, processo, ano, tipo, valor, cond, grupo, sessao in rows:
        v = float(valor or 0.0)
        tp = (tipo or "—").upper()
        ses = (sessao or "")[:10]
        key = (orgao, processo, round(v, 2), ses, tp)
        ev = eventos.get(key)
        if ev is None:
            r = res[orgao]
            eventos[key] = {"orgao_tce": orgao, "processo": processo or "—", "ano": ano, "tipo": tp,
                            "valor": v, "n_resp": 1, "grupo_natureza": grupo or "—", "data_sessao": ses,
                            "confianca": r["confianca"], "historico": r["historico"], "fonte": r["fonte"]}
        else:
            ev["n_resp"] += 1

    por_tipo: dict[str, dict] = {}
    por_ano: dict[int, dict] = {}
    processos: set = set()
    valor_total = 0.0
    for ev in eventos.values():
        v = ev["valor"]
        valor_total += v
        tp = ev["tipo"]
        por_tipo.setdefault(tp, {"n": 0, "valor": 0.0})
        por_tipo[tp]["n"] += 1
        por_tipo[tp]["valor"] += v
        if ev["ano"] is not None:
            por_ano.setdefault(int(ev["ano"]), {"n": 0, "valor": 0.0})
            por_ano[int(ev["ano"])]["n"] += 1
            por_ano[int(ev["ano"])]["valor"] += v
        if ev["processo"] and ev["processo"] != "—":
            processos.add(ev["processo"])
    itens = sorted(eventos.values(), key=lambda i: i["valor"], reverse=True)
    confs = {res[o]["confianca"] for o in nomes}
    confianca = "alta" if "alta" in confs else "media"
    return {"ok": True, "n_condenacoes": len(rows), "n_eventos": len(eventos),
            "n_processos": len(processos), "valor_total": round(valor_total, 2), "por_tipo": por_tipo,
            "por_ano": dict(sorted(por_ano.items())), "itens": itens, "confianca": confianca,
            "orgaos_tce": nomes, "tem_media": "media" in confs,
            "tem_historico": any(res[o]["historico"] for o in nomes),
            "tem_solidaria": len(rows) > len(eventos)}


# ───────────────────────── depuração / auto-auditoria ─────────────────────────
def depurar(db_path: str | Path | None = None) -> dict:
    """Reconcilia os órgãos-TCE vivos × o vínculo resolvido. Sinaliza o que precisa de revisão humana:
    sem âncora, match incerto, override que diverge do auto, e UG cujo nome não bate mais (renomeação)."""
    ug = _ug_canonico()
    try:
        con = _con(db_path)
        try:
            distintos = sorted(_orgaos_distintos(con))
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "_nota": str(exc)[:160], "linhas": []}
    linhas = []
    for o in distintos:
        r = resolver(o)
        a = auto_match(o)
        flags = []
        if r.get("sem_ancora"):
            flags.append("sem_ancora")
        if not r["ug_codes"] and not r.get("sem_ancora"):
            flags.append("sem_match")
        if r["fonte"] == "override" and a["ug_codes"] and set(a["ug_codes"]) - set(r["ug_codes"]) and a["score"] >= 0.85:
            flags.append("override_diverge_auto")  # o auto acha outra coisa com força → revisar o override
        if r["fonte"] == "auto" and r["confianca"] == "media":
            flags.append("auto_incerto")
        if r["historico"]:
            flags.append("historico")
        linhas.append({"orgao": o, "ug_codes": r["ug_codes"], "fonte": r["fonte"],
                       "confianca": r["confianca"], "score": r["score"], "auto_top": a["ug_codes"],
                       "auto_score": a["score"], "nomes_ug": [ug.get(c, "?") for c in r["ug_codes"]],
                       "flags": flags, "nota": r.get("nota", "")})
    resumo = {"total": len(linhas),
              "override": sum(1 for x in linhas if x["fonte"] == "override"),
              "auto": sum(1 for x in linhas if x["fonte"] == "auto"),
              "sem_ancora": sum(1 for x in linhas if "sem_ancora" in x["flags"]),
              "sem_match": sum(1 for x in linhas if "sem_match" in x["flags"]),
              "revisar": sum(1 for x in linhas if x["flags"] and x["flags"] != ["historico"])}
    return {"ok": True, "resumo": resumo, "linhas": linhas}


# ───────────────────────── leitura (prosa honesta) ─────────────────────────
def _moeda(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def leitura(agg: dict, nome_orgao: str = "este órgão") -> str:
    """CONCLUSÃO em prosa honesta. Fato julgado pela Corte, não indício nosso."""
    if not agg.get("ok") or not agg.get("n_condenacoes"):
        # sem_sancao: a UG resolveu para órgão(s)-TCE, mas a Corte não registrou condenação → limpo de fato.
        if agg.get("motivo") == "sem_sancao":
            return (f"**Sem sanção do TCE-RJ** registrada para {nome_orgao} na base local de penalidades: "
                    "a correspondência órgão↔UG foi estabelecida e não consta condenação (débito/multa) atribuída — "
                    "histórico limpo na cobertura desta base (não exclui processos em curso).")
        # indisponivel: nenhum órgão-TCE casou com a UG → não dá p/ afirmar limpo nem condenado.
        return (f"Não constam sanções do TCE-RJ atribuíveis a {nome_orgao} na base local de penalidades "
                "(INDISPONÍVEL — correspondência de nome↔UG não estabelecida com confiança; "
                "não equivale automaticamente a histórico limpo).")
    n, npr, tot = agg["n_condenacoes"], agg["n_processos"], agg["valor_total"]
    nev = agg.get("n_eventos", n)
    pt = agg.get("por_tipo", {})
    deb = pt.get("DEBITO", {}).get("valor", 0.0)
    mul = pt.get("MULTA", {}).get("valor", 0.0)
    partes = []
    if deb:
        partes.append(f"**R$ {_moeda(deb)}** em DÉBITO (imputação de devolução ao erário)")
    if mul:
        partes.append(f"**R$ {_moeda(mul)}** em MULTA")
    detalhe = " e ".join(partes) if partes else f"R$ {_moeda(tot)}"
    anos = agg.get("por_ano", {})
    faixa = ""
    if anos:
        ks = list(anos.keys())
        faixa = f" entre {min(ks)} e {max(ks)}" if min(ks) != max(ks) else f" em {min(ks)}"
    ress = ""
    if agg.get("tem_solidaria"):
        ress += (f" Há **responsabilidade solidária** ({n} condenações individuais em {nev} eventos distintos): "
                 "o valor acima conta cada débito **uma vez** (não soma os co-responsáveis) — exposição real ao erário, "
                 "sem dupla contagem.")
    if agg.get("tem_media"):
        ress += (" ⚠ Parte da correspondência nome-TCE↔UG é **incerta** (órgão extinto/reorganizado) — "
                 "confirmar o ente exato no processo antes de imputar à gestão atual.")
    if agg.get("tem_historico"):
        ress += (" Há condenações de **órgão extinto/em liquidação** (sanção histórica) — a sucessão à estrutura "
                 "atual deve ser confirmada.")
    return (f"O TCE-RJ registra **{n}** condenação(ões) em **{npr}** processo(s) de contas imputada(s) a "
            f"{nome_orgao}{faixa}, somando {detalhe}. São **decisões da Corte de Contas** (fato julgado, não "
            "indício interno) que sinalizam falhas já reconhecidas na gestão/prestação de contas do órgão — "
            "contexto relevante de risco institucional para a leitura da execução financeira." + ress)


# ───────────────────────── CLI de depuração ─────────────────────────
if __name__ == "__main__":  # pragma: no cover
    import sys
    if "--depurar" in sys.argv:
        d = depurar()
        if not d["ok"]:
            print("erro:", d.get("_nota")); sys.exit(1)
        print("RESUMO:", d["resumo"])
        print("\nÓRGÃO-TCE → UG (fonte/conf/score) [flags]:")
        for x in sorted(d["linhas"], key=lambda y: (not y["flags"], y["orgao"])):
            fl = (" ⚑ " + ",".join(x["flags"])) if x["flags"] else ""
            ugs = ",".join(f"{c}={n[:24]}" for c, n in zip(x["ug_codes"], x["nomes_ug"])) or "(sem âncora)"
            print(f"  {x['orgao'][:42]:42} → {ugs:34} [{x['fonte']}/{x['confianca']}/{x['score']:.2f}]{fl}")
