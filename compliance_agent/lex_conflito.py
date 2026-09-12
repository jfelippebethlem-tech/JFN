# -*- coding: utf-8 -*-
"""
lex_conflito — conflito de interesse: doações eleitorais (TSE) × fornecedores do Estado (OBs).
JFN 2.0, Onda 2. Fonte 100% gratuita (TSE Dados Abertos + base interna de OBs/QSA).

REQUISITO-CHAVE (instrução do dono): o cruzamento NÃO é só doador-CNPJ == fornecedor-CNPJ. Tem que casar
**doadores TSE × SÓCIOS (QSA) das empresas que receberam OB/contrato**. Ou seja, o doador (CPF/CNPJ) pode ser
SÓCIO da contratada, não a contratada em si — é assim que se pega o vínculo escondido.

⚠️ LGPD: `socios_fornecedor.socio_doc` vem MASCARADO (ex.: `***550179**` — só 6 dígitos do meio do CPF).
Então o match doador↔sócio é por NOME normalizado (sinal forte) corroborado pelo CPF mascarado (6 dígitos) quando
possível — princípio de ≥2 sinais independentes (OSINT). Saída = INDÍCIO a verificar, nunca acusação.

Uso:
    cd ~/JFN && PYTHONPATH=. .venv/bin/python -m compliance_agent.lex_conflito --cnpj 12345678000199
    from compliance_agent.lex_conflito import conflito
"""
from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata

from compliance_agent.database.models import _resolver_db


logger = logging.getLogger(__name__)


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _norm_nome(s: str) -> str:
    s = (s or "").upper()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^A-Z ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _mask_cpf(cpf: str) -> str:
    """Formata um CPF de 11 dígitos no mesmo padrão mascarado do QSA: ***DDDDDD** (6 dígitos do meio)."""
    d = _digits(cpf)
    return f"***{d[3:9]}**" if len(d) == 11 else ""


def _empresas_com_ob(con) -> dict[str, dict]:
    """CNPJ -> {n_ob, total} a partir de ordens_bancarias (TFE) + ob_orcamentaria_siafe (SIAFE)."""
    emp: dict[str, dict] = {}
    for sql, campo in [("SELECT favorecido_cpf, COUNT(*), COALESCE(SUM(valor),0) FROM ordens_bancarias "
                        "WHERE favorecido_cpf IS NOT NULL GROUP BY favorecido_cpf", "tfe"),
                       ("SELECT credor, COUNT(*), 0 FROM ob_orcamentaria_siafe WHERE credor IS NOT NULL GROUP BY credor", "siafe")]:
        try:
            for c, n, tot in con.execute(sql):
                d = _digits(c)
                if len(d) != 14:
                    continue
                e = emp.setdefault(d, {"n_ob": 0, "total": 0.0})
                e["n_ob"] += n or 0
                e["total"] += float(tot or 0)
        except sqlite3.Error as exc:
            logger.warning("fonte %s do conflito falhou (vínculos podem sumir mudos): %s", campo, exc)
            continue
    return emp


def _ugs_sei_por_empresa(con, cnpjs: set[str], max_ug: int = 8, max_sei: int = 12) -> dict[str, dict]:
    """Para cada CNPJ contratado, devolve {ugs:[{ug, nome, total, n_ob}], seis:[numero_sei...]}.

    Fonte: ordens_bancarias (TFE, tem ug_codigo/ug_nome/numero_sei) + ob_orcamentaria_siafe (SIAFE, tem
    ug_pagadora/processo). UG resolvida pelo CÓDIGO via mapa canônico (a OB às vezes rotula com o órgão
    superior — ver compliance_agent/ugs.py). Só leitura; seguro com o sweep rodando (WAL)."""
    if not cnpjs:
        return {}
    try:
        from compliance_agent import ugs as _ugs
        _rotulo = _ugs.rotulo
    except Exception:
        def _rotulo(cod, nome=""):  # fallback sem mapa canônico
            return (nome or f"UG {cod}").strip()

    out: dict[str, dict] = {c: {"_ug": {}, "_sei": {}} for c in cnpjs}
    place = ",".join("?" * len(cnpjs))
    alvos = list(cnpjs)

    # (1) TFE — favorecido_cpf guarda o CNPJ (14 díg.); ug_codigo + ug_nome + numero_sei
    try:
        for cnpj_e, ugc, ugn, sei, n, tot in con.execute(
                f"SELECT favorecido_cpf, ug_codigo, ug_nome, numero_sei, COUNT(*), COALESCE(SUM(valor),0) "
                f"FROM ordens_bancarias WHERE favorecido_cpf IN ({place}) "
                f"GROUP BY favorecido_cpf, ug_codigo, ug_nome, numero_sei", alvos):
            d = _digits(cnpj_e)
            if d not in out:
                continue
            cod = _digits(ugc) or (ugc or "")
            rot = _rotulo(cod, ugn or "")
            u = out[d]["_ug"].setdefault(rot, {"ug": cod, "nome": rot, "total": 0.0, "n_ob": 0})
            u["total"] += float(tot or 0); u["n_ob"] += int(n or 0)
            if sei and str(sei).strip():
                out[d]["_sei"][str(sei).strip()] = out[d]["_sei"].get(str(sei).strip(), 0) + int(n or 0)
    except sqlite3.Error as exc:
        logger.warning("query TFE do conflito doador-contrato falhou (vínculo pode sumir mudo): %s", exc)

    # (2) SIAFE — credor guarda o CNPJ; ug_pagadora/ug_emitente + processo (=SEI de origem)
    try:
        for cnpj_e, ugp, uge, proc, n, tot in con.execute(
                f"SELECT credor, ug_pagadora, ug_emitente, processo, COUNT(*), COALESCE(SUM(valor),0) "
                f"FROM ob_orcamentaria_siafe WHERE credor IN ({place}) "
                f"GROUP BY credor, ug_pagadora, ug_emitente, processo", alvos):
            d = _digits(cnpj_e)
            if d not in out:
                continue
            cod = _digits(ugp) or _digits(uge) or (ugp or uge or "")
            rot = _rotulo(cod, "")
            u = out[d]["_ug"].setdefault(rot, {"ug": cod, "nome": rot, "total": 0.0, "n_ob": 0})
            u["total"] += float(tot or 0); u["n_ob"] += int(n or 0)
            if proc and str(proc).strip():
                out[d]["_sei"][str(proc).strip()] = out[d]["_sei"].get(str(proc).strip(), 0) + int(n or 0)
    except sqlite3.Error as exc:
        logger.warning("query SIAFE do conflito doador-contrato falhou (vínculo pode sumir mudo): %s", exc)

    # consolida: top UGs por valor, top SEIs por nº de OBs
    res: dict[str, dict] = {}
    for c, agg in out.items():
        ugs_l = sorted(agg["_ug"].values(), key=lambda x: x["total"], reverse=True)
        for u in ugs_l:
            u["total"] = round(u["total"], 2)
        seis_l = [s for s, _ in sorted(agg["_sei"].items(), key=lambda kv: kv[1], reverse=True)]
        res[c] = {"ugs": ugs_l[:max_ug], "seis": seis_l[:max_sei],
                  "n_ugs": len(ugs_l), "n_seis": len(seis_l)}
    return res


def conflito(cnpj: str | None = None, candidato: str | None = None, limite: int = 200) -> dict:
    """Rede de conflito doador↔(empresa|sócio da empresa)↔OB.

    - cnpj: foca numa empresa (mostra doações DELA e dos SÓCIOS dela).
    - candidato: foca em quem RECEBEU (lista doadores-empresa/sócio que viraram fornecedores).
    - nenhum: varredura geral (top por valor de OB), até `limite`.
    Retorna {ok, rede:[{doador, doc, candidato, partido, ano, valor_doacao, empresa_cnpj, empresa, n_ob,
    total_ob, via:"direto"|"socio", sinais[]}], _fonte, _nota}.
    """
    _DB = _resolver_db()
    if not _DB.exists():
        # O módulo já declarava INDISPONÍVEL quando a tabela está VAZIA (logo abaixo), mas devolvia
        # um `ok=False` seco quando o BANCO falta — duas formas para a mesma situação, e a segunda
        # sem fonte nem ressalva. Quem consome não distinguia "não há conflito" de "não há base".
        return {"ok": False, "indisponivel": True, "rede": [],
                "erro": "compliance.db ausente",
                "_fonte": "TSE Dados Abertos",
                "_nota": "INDISPONÍVEL: base local ausente nesta máquina — nada foi medido, e "
                         "ausência de medida não é ausência de conflito."}
    con = sqlite3.connect(str(_DB))
    try:
        try:
            n_doacoes = con.execute("SELECT COUNT(*) FROM doacoes_eleitorais").fetchone()[0]
        except sqlite3.OperationalError as exc:
            # Banco presente mas SEM a tabela é a mesma situação de tabela vazia — e virava HTTP
            # 500 (visto no runner do CI, onde outro teste cria o compliance.db sem o schema do
            # TSE). Erro de execução e ausência de fonte são coisas diferentes para quem consome.
            return {"ok": False, "indisponivel": True, "rede": [],
                    "erro": f"tabela doacoes_eleitorais ausente ({exc})",
                    "_fonte": "TSE Dados Abertos",
                    "_nota": "INDISPONÍVEL: a base do TSE não foi coletada nesta máquina — rodar "
                             "compliance_agent.collectors.tse baixar_doacoes_ano."}
        if n_doacoes == 0:
            return {"ok": True, "rede": [], "_fonte": "TSE Dados Abertos",
                    "_nota": "INDISPONÍVEL: base doacoes_eleitorais vazia — rodar coletor TSE "
                             "(compliance_agent.collectors.tse baixar_doacoes_ano) antes."}
        emp = _empresas_com_ob(con)

        # filtro de doações
        where, params = "", []
        if candidato:
            where = "WHERE UPPER(nome_candidato) LIKE ?"; params = [f"%{candidato.upper()}%"]
        doacoes = con.execute(
            "SELECT cpf_cnpj_doador, nome_doador, nome_candidato, partido, ano_eleicao, COALESCE(SUM(valor),0) "
            f"FROM doacoes_eleitorais {where} GROUP BY cpf_cnpj_doador, nome_doador, nome_candidato, partido, ano_eleicao",
            params).fetchall()

        # índice de sócios por nome_norm e por cpf mascarado (p/ o cruzamento via sócio)
        socios_por_nome: dict[str, list[str]] = {}
        socios_por_doc: dict[str, list[str]] = {}
        for cnpj_emp, nome_norm, doc in con.execute(
                "SELECT cnpj, socio_nome_norm, socio_doc FROM socios_fornecedor WHERE socio_nome_norm!=''"):
            d = _digits(cnpj_emp)
            if nome_norm:
                socios_por_nome.setdefault(nome_norm, []).append(d)
            if doc:
                socios_por_doc.setdefault(str(doc).strip(), []).append(d)

        alvo_cnpj = _digits(cnpj) if cnpj else None
        rede = []
        for doc_doador, nome_doador, cand, partido, ano, valor in doacoes:
            dd = _digits(doc_doador)
            nome_norm = _norm_nome(nome_doador)
            empresas_vinculadas: dict[str, dict] = {}

            # (a) DIRETO: doador-PJ é a própria empresa com OB
            if len(dd) == 14 and dd in emp:
                empresas_vinculadas[dd] = {"via": "direto", "sinais": ["doador_cnpj==fornecedor"]}

            # (b) VIA SÓCIO: doador (PF/PJ) é SÓCIO de empresa com OB — casa por nome e/ou cpf mascarado
            cnpjs_socio: set[str] = set()
            if nome_norm and nome_norm in socios_por_nome:
                cnpjs_socio |= {c for c in socios_por_nome[nome_norm]}
            if len(dd) == 11:
                mc = _mask_cpf(dd)
                if mc and mc in socios_por_doc:
                    cnpjs_socio |= set(socios_por_doc[mc])
            for c in cnpjs_socio:
                if c in emp:
                    # confiança: nome + cpf-mascarado batendo = 2 sinais
                    sinais = []
                    if nome_norm in socios_por_nome and c in socios_por_nome[nome_norm]:
                        sinais.append("nome_socio")
                    if len(dd) == 11 and _mask_cpf(dd) in socios_por_doc and c in socios_por_doc[_mask_cpf(dd)]:
                        sinais.append("cpf_mascarado")
                    prev = empresas_vinculadas.get(c)
                    if not prev or prev["via"] == "socio":
                        empresas_vinculadas[c] = {"via": "socio", "sinais": sinais or ["nome_socio"]}

            for c, meta in empresas_vinculadas.items():
                if alvo_cnpj and c != alvo_cnpj:
                    continue
                e = emp[c]
                rede.append({
                    "doador": nome_doador, "doc": doc_doador, "candidato": cand, "partido": partido,
                    "ano": ano, "valor_doacao": round(float(valor or 0), 2),
                    "empresa_cnpj": c, "n_ob": e["n_ob"], "total_ob": round(e["total"], 2),
                    "via": meta["via"], "sinais": meta["sinais"],
                })

        # score simples: via direto + corroboração de 2 sinais pesa mais; ordenar por (valor_ob, valor_doacao)
        for r in rede:
            r["score"] = (2 if r["via"] == "direto" else 1) + (1 if len(r["sinais"]) >= 2 else 0)
        rede.sort(key=lambda r: (r["total_ob"], r["valor_doacao"]), reverse=True)
        rede = rede[:limite]

        # enriquece SÓ as empresas que sobraram na rede: UG pagadora (canônica) + processos SEI
        cnpjs_rede = {r["empresa_cnpj"] for r in rede}
        det = _ugs_sei_por_empresa(con, cnpjs_rede)
        for r in rede:
            d = det.get(r["empresa_cnpj"], {})
            r["ugs"] = d.get("ugs", [])
            r["seis"] = d.get("seis", [])

        return {"ok": True, "rede": rede, "n_doacoes_base": n_doacoes,
                "_fonte": "TSE Dados Abertos + OBs (TFE/SIAFE) + QSA BrasilAPI",
                "_nota": "INDÍCIO a verificar (presunção de legitimidade). socio_doc é mascarado (LGPD); "
                         "match por nome+CPF-mascarado. Score = via + corroboração, não prova."}
    finally:
        con.close()


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Conflito doador(TSE)↔sócio↔fornecedor(OB).")
    ap.add_argument("--cnpj"); ap.add_argument("--candidato"); ap.add_argument("--limite", type=int, default=50)
    a = ap.parse_args()
    print(json.dumps(conflito(cnpj=a.cnpj, candidato=a.candidato, limite=a.limite), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()


# ── Sócio na folha pública (folha do Estado × QSA) — a segunda perna do conflito de interesse ──────────
# A primeira perna (acima) é doador × sócio. Esta é agente público × sócio: `agente_publico_societario`
# casa a folha do Estado (cargo, vínculo, órgão) com o QSA por NOME normalizado. Nasceu do caso da
# Fundação Saúde (09/09/2026): a Diretora Assistencial de uma UPA era sócia da clínica que a UPA pagava
# por TAC. Grau pelo ENTE: saúde estadual (FSERJ/SES) = alto; outro órgão = médio. Nome curto = homônimo
# provável — o achado diz isso e pede CPF.

def socios_agentes_publicos(cnpj: str) -> list[dict]:
    """Sócios da raiz do CNPJ que constam na folha do Estado. Vazio = nada casou OU base ausente."""
    raiz = _digits(cnpj)[:8]
    if len(raiz) != 8:
        return []
    _DB = _resolver_db()
    if not _DB.exists():
        return []
    con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=30)
    try:
        rows = con.execute("SELECT nome_socio, cargo, vinculo, orgao, origem FROM agente_publico_societario "
                           "WHERE cnpj_basico=? LIMIT 20", (raiz,)).fetchall()
    except sqlite3.Error as exc:
        logger.debug("agente_publico_societario indisponível para %s: %s", raiz, exc)
        return []
    finally:
        con.close()
    return [{"nome": r[0], "cargo": r[1] or "", "vinculo": r[2] or "", "orgao": r[3] or "", "origem": r[4] or ""} for r in rows]


def achado_socio_agente(socios: list[dict]) -> dict | None:
    """Achado estrutural do Lex ({rf, grav, obs}) a partir dos sócios-agentes; None quando não há."""
    if not socios:
        return None
    def _saude(o: str) -> int:
        n = _norm_nome(o)
        return 2 if ("FUNDACAO SAUDE" in n or "FSERJ" in n) else 1 if "SAUDE" in n else 0
    nivel = max(_saude(s["orgao"]) for s in socios)
    grav = 4 if nivel == 2 else 3 if nivel == 1 else 2
    def _peso(nome: str) -> str:
        toks = [t for t in _norm_nome(nome).split() if t not in {"DE", "DA", "DO", "DOS", "DAS", "E"}]
        return "nome forte" if len(toks) >= 3 else "nome comum — confirmar CPF"
    linhas = "; ".join(f"{s['nome']} — {s['cargo'] or '?'} ({s['vinculo'] or '?'}) em {s['orgao'] or '?'} [{_peso(s['nome'])}]"
                       for s in socios[:4])
    ente = "da própria saúde estadual (FSERJ)" if nivel == 2 else "da saúde estadual (SES)" if nivel == 1 else "de outro órgão público"
    return {"rf": "DD/SOCIO-AGENTE", "grav": grav,
            "obs": (f"**Sócio na folha pública {ente}.** {linhas}. Casamento por NOME (folha × QSA); "
                    f"vínculo tem de valer na data do ato. Art. 14, IV da Lei 14.133 quando o ente for o contratante; "
                    f"indício, não acusação.")}


# ── TAC recorrente (D.O. do Estado × fornecedor) — 10/09/2026 ─────────────────────────────────
_GENERICOS_TAC = {"LTDA", "EIRELI", "SERVICOS", "MEDICOS", "MEDICA", "SAUDE", "DISTRIBUIDORA", "COMERCIO",
                  "HOSPITALAR", "PRODUTOS", "CLINICA", "SOCIEDADE", "SIMPLES", "EPP", "ME", "SA", "S/A"}


def _tokens_tac(nome: str | None) -> list[str]:
    return [t for t in _norm_nome(nome or "").split() if len(t) >= 3 and t not in _GENERICOS_TAC][:2]


def tacs_do_fornecedor(cnpj: str | None, nome: str | None) -> list[dict]:
    """Termos de Ajuste de Contas publicados no DOERJ (tabela `doerj_tac`) para este fornecedor.
    Casa por CNPJ quando o extrato o publicou (raro) e, senão, pelos 2 primeiros tokens distintivos do
    nome — o mesmo casamento do `doerj_tac_favorecimento`. Vazio = nada casou OU base ausente."""
    _DB = _resolver_db()
    if not _DB.exists():
        return []
    toks = _tokens_tac(nome)
    dig = _digits(cnpj or "")
    if not toks and len(dig) != 14:
        return []
    con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=30)
    try:
        # O upper() do SQLite não dobra acento ('GESTÃO' ≠ 'GESTAO'): busca pelo 1º token e confere o resto em
        # Python com o nome normalizado (a TUISE sumia do Lex por isso — 10/09).
        cond, args = [], []
        if len(dig) == 14:
            cond.append("cnpj = ?"); args.append(dig)
        if toks:
            cond.append("upper(fornecedor) LIKE ?"); args.append(f"%{toks[0]}%")
        rows = con.execute(
            "SELECT data_doe, numero_tac, orgao, valor, processo, fornecedor FROM doerj_tac WHERE " + " OR ".join(cond) +
            " ORDER BY data_doe LIMIT 400", args).fetchall()
    except sqlite3.Error as exc:
        logger.debug("doerj_tac indisponível para %s: %s", cnpj, exc)
        return []
    finally:
        con.close()
    rows = [r for r in rows if all(t in _norm_nome(r[5] or "") for t in toks)] if toks else rows
    return [{"data": r[0], "numero": r[1] or "", "orgao": r[2] or "", "valor": r[3], "processo": r[4] or ""} for r in rows[:200]]


def _moeda(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def sinais_tac_do_fornecedor(nome: str | None) -> list[dict]:
    """Sinais do cruzamento TAC × favorecimento (`doerj_tac_sinal`, tools/doerj_tac_favorecimento) para o nome."""
    _DB = _resolver_db()
    toks = _tokens_tac(nome)
    if not _DB.exists() or not toks:
        return []
    con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=30)
    try:
        rows = con.execute(
            "SELECT sinal, grau, detalhe, fornecedor FROM doerj_tac_sinal WHERE sinal NOT IN ('sem_sinal','cnpj_nao_localizado') "
            "AND upper(fornecedor) LIKE ? ORDER BY grau <> '🔴', sinal LIMIT 40", (f"%{toks[0]}%",)).fetchall()
        rows = [r for r in rows if all(t in _norm_nome(r[3] or "") for t in toks)][:8]
    except sqlite3.Error as exc:
        logger.debug("doerj_tac_sinal indisponível: %s", exc)
        return []
    finally:
        con.close()
    return [{"sinal": r[0], "grau": r[1], "detalhe": r[2] or ""} for r in rows]


def achado_tac_recorrente(tacs: list[dict], sinais: list[dict] | None = None) -> dict | None:
    """Achado estrutural do Lex: pagamento por TAC como ROTINA. 1 TAC é exceção prevista no Decreto 47.283/2020;
    a partir de 3 é serviço contínuo sem contrato (grav 3); 6+ ou R$ 10 mi+ é regime permanente (grav 4)."""
    n = len(tacs)
    if n < 3:
        return None
    soma = sum(t["valor"] or 0 for t in tacs)
    grav = 4 if (n >= 6 or soma >= 10_000_000) else 3
    orgaos = sorted({t["orgao"] for t in tacs if t["orgao"]})
    de, ate = tacs[0]["data"], tacs[-1]["data"]
    return {"rf": "DD/TAC-RECORRENTE", "grav": grav,
            "obs": (f"**{n} Termos de Ajuste de Contas publicados no DOERJ** ({de} → {ate}), somando "
                    f"R$ {_moeda(soma)}, por {', '.join(o[:60] for o in orgaos[:2]) or 'órgão não lido'}. TAC é o instrumento que "
                    "indeniza serviço prestado SEM contrato (Decreto 47.283/2020): como rotina mensal, indica "
                    "serviço contínuo sem licitação e exige, a cada termo, a apuração de responsabilidade pela "
                    "lacuna (art. 4º, III). Conferir nos autos se ela existe; indício, não acusação."
                    + (" Cruzamentos: " + "; ".join(f"{x['grau']} {x['sinal']} — {x['detalhe'][:160]}" for x in sinais[:3]) if sinais else ""))}


# ── Cadastro de Empregadores (trabalho escravo, MTE) — 12/09/2026 ──────────────────────────────
def lista_suja(cnpj: str | None) -> dict | None:
    """Entrada do CNPJ (ou da raiz) no Cadastro de Empregadores do MTE (`lista_suja_mte`) + pagamentos do
    Estado (SIAFE) DEPOIS da inclusão. None quando não consta ou a base não existe."""
    dig = _digits(cnpj or "")
    if len(dig) != 14:
        return None
    _DB = _resolver_db()
    if not _DB.exists():
        return None
    con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=30)
    try:
        row = con.execute("SELECT cnpj, nome, inclusao FROM lista_suja_mte WHERE cnpj=? OR substr(cnpj,1,8)=? LIMIT 1",
                          (dig, dig[:8])).fetchone()
        if not row:
            return None
        inc = row[2] or ""
        iso = f"{inc[6:10]}-{inc[3:5]}-{inc[0:2]}" if len(inc) == 10 else ""
        # data_emissao do SIAFE é TEXTO DD/MM/AAAA: converter antes de comparar
        depois = con.execute(
            "SELECT count(*), round(sum(valor),2) FROM ob_orcamentaria_siafe WHERE credor=? AND "
            "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2) >= ?",
            (dig, iso or "9999")).fetchone()
    except sqlite3.Error as exc:
        logger.debug("lista_suja_mte indisponível: %s", exc)
        return None
    finally:
        con.close()
    return {"cnpj": row[0], "nome": row[1], "inclusao": inc, "obs_depois": depois[0] or 0, "pago_depois": depois[1] or 0.0}


def achado_lista_suja(e: dict | None) -> dict | None:
    if not e:
        return None
    pago = e.get("pago_depois") or 0
    grav = 4 if pago > 0 else 2
    return {"rf": "DD/LISTA-SUJA", "grav": grav,
            "obs": (f"**Consta no Cadastro de Empregadores do MTE (trabalho análogo ao de escravo)** — {e['nome']}, "
                    f"inclusão em {e['inclusao'] or '?'}. " +
                    (f"O Estado pagou {e['obs_depois']} OB(s) = R$ {_moeda(pago)} DEPOIS da inclusão — vedação de contratar "
                     ""
                     if pago > 0 else "Sem pagamento estadual após a inclusão nos dados do SIAFE — monitorar. ") +
                    "Fonte pública do MTE; conferir vigência (a lista é semestral).")}
