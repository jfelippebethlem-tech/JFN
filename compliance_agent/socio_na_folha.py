# -*- coding: utf-8 -*-
"""Sócio na folha — servidor público que é sócio de fornecedor pago pelo Estado, UMA LINHA POR PESSOA,
com a identidade desambiguada em camadas (`identidade_pessoa`) antes de qualquer afirmação.

Substitui o miolo de `cruzamentos_intel.socio_servidor` (que agora delega para cá). O que mudou e por quê
(medido em 19/11/2026 no acervo real; números em `medir()`):

* A versão anterior presumia que TODA folha mostra os dígitos 3–8 do CPF. O GESPERJ (Executivo, 1,08 mi de
  registros) mostra 4–9. Resultado: 911 "homônimos descartados" que eram, em boa parte, a mesma pessoa, e
  0 casamento no Executivo. Agora a janela é a AFERIDA por fonte.
* "Confiança MÉDIA = só o nome" aparecia na lista principal. Agora par só-por-nome é INDETERMINADO, fica
  fora da lista e diz qual dado falta (TJRJ e Câmara não publicam CPF).
* O teste de art. 9 (empresa paga pela própria repartição) mapeava órgão→UG com códigos errados
  (Educação→190100, que é a SEHAB; Polícia Civil→263100, que é o DETRAN). Mapa refeito contra o índice
  de UG do SIAFE e os códigos que de fato emitem OB.
* Valor = OB PAGA do SIAFE (`_ob_paga`), por UG pagadora. Empresa sem OB no SIAFE coletado sai como
  INDISPONÍVEL (≠ 0), com o espelho TFE apenas como referência rotulada.

Indício ≠ acusação: servidor pode ser sócio (quotista). O que pesa é gerência (vedação estatutária) e a
empresa ser paga pelo órgão do próprio servidor (Lei 14.133, art. 9º).
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from compliance_agent import identidade_pessoa as ip

_REPO = Path(__file__).resolve().parent.parent
_DB = str(_REPO / "data" / "compliance.db")

# Órgão da folha → UGs EMITENTES de OB no SIAFE (códigos conferidos em data/ug_index_siafe.json e em
# ob_orcamentaria_siafe.ug_emitente, 19/11/2026). Ordem importa: o trecho mais específico primeiro.
ORGAO_UG = [
    ("FUNDACAO SAUDE", ["294200", "226300"]),            # FS / FSERJ
    ("SECRETARIA DE ESTADO DE SAUDE", ["290100", "296100"]),  # SES / FES
    ("SECRETARIA DE ESTADO DE EDUCACAO", ["180100"]),    # SEEDUC
    ("POLICIA MILITAR", ["261100", "266500"]),           # SEPM / FUNESPOM
    ("POLICIA CIVIL", ["260400", "520100"]),             # SEPOL
    ("POLICIA PENAL", ["250100"]),                       # SEPPEN
    ("DEFESA CIVIL", ["160100", "166100"]),              # SEDEC / FUNESBOM
    ("UNIVERSIDADE DO ESTADO", ["404300", "404310", "404320", "404350"]),  # UERJ
    ("NORTE FLUMINENSE", ["404500"]),                    # UENF
    ("ESCOLA TECNICA", ["404400"]),                      # FAETEC
    ("DEPARTAMENTO DE TRANSITO", ["263100"]),            # DETRAN
    ("SECRETARIA DE ESTADO DE FAZENDA", ["200100"]),     # SEFAZ
    ("ESTRADAS DE RODAGEM", ["044100"]),                 # DER
    ("INSTITUTO ESTADUAL DO AMBIENTE", ["243200"]),      # INEA
    ("PROCURADORIA GERAL DO ESTADO", ["090100"]),        # PGE
    ("ASSISTENCIA DOS SERVIDORES", ["293100"]),          # IASERJ
    ("DEFENSORIA", ["110100"]),                          # DPGE
]
UG_FONTE = {"dprj_transparencia": ["110100"], "tjrj_anexo8": ["030100", "036100"]}  # DPGE; TJ / FETJ

# favorecido NÃO-comercial e qualificação de DONO/gerência: régua única, em cruzamentos_intel
from compliance_agent.cruzamentos_intel import _RX_DONO, _RX_GERENCIA, _RX_NAOCOM  # noqa: E402

# Medido em 19/11/2026 com a janela de CPF corrigida: 180 das 368 entidades casadas eram associações de apoio
# a escola estadual ("Aa Ce …", "Ciep …", "Eees …" — professor como presidente É o desenho da APM), sociedades
# musicais/Pestalozzi/espíritas e estatais (CEDAE, Imprensa Oficial). Não são fornecedor comercial: o servidor
# preside por ofício. Saem da lista e são CONTADAS (`fora_do_escopo`), nunca somem caladas.
_RX_NAOCOM_ESCOLA = re.compile(
    r"^A ?A ?[EFR]?\b|^AAEE|^AAEEES|^AAE\b|\bCIEP\b|BRIZOL|^C ?E\b|^CES\b|^CEJA\b|^E ?E\b|^EEES\b|\bESCOLA\b|"
    r"COLEGIO ESTADUAL|^GP\b|GINASIO|\bASSOC|^AS RURAL|SOCIEDADE (MUSICAL|PESTALOZZI|CULTURAL|PROPAGADORA|BRASILEIRA)|"
    r"^SOC (MUSICAL|PESTALOZZI)|PESTALOZZI|ESPIRITA|OBRA SOCIAL|OBRA DO BERCO|^LAR\b|CENTRO COMUNIT|CENTRO CULTURAL|"
    r"CENTRO DE DEFESA|CENTRO DE ESTUDOS|ACADEMIA .*LETRAS|CONSORCIO INTERMUNICIPAL|COMPANHIA ESTADUAL|CEDAE|"
    r"IMPRENSA OFICIAL|\bCAMPUS\b")
_RX_COMERCIAL = re.compile(r"\bLTDA\b|\bEIRELI\b|\bME\b|\bEPP\b|\bS A\b|\bSA\b|COMERCIO|ENGENHARIA|SERVICOS")


def ugs_do_vinculo(orgao_nome: str, fonte: str) -> list[str]:
    o = ip.normalizar_nome(orgao_nome)
    for chave, ugs in ORGAO_UG:
        if chave in o:
            return ugs
    return UG_FONTE.get(fonte, [])


def _ro(db_path: str | None) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path or _DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _cnpj_fmt(c: str) -> str:
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}" if len(c or "") == 14 else (c or "")


def _ano(comp: str) -> str:
    return (comp or "")[:7]


def _tabela_existe(con, t: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def _socios_alvo(con, fora: dict | None = None) -> list[dict]:
    """Sócios-donos de fornecedor COMERCIAL pago. `fora` (opcional) recebe a contagem do que saiu e por quê."""
    out = []
    fora = fora if fora is not None else {}
    q = ("SELECT s.socio_nome, s.socio_doc, s.cnpj, s.qualificacao, s.cpf_resolvido, "
         "f.favorecido_nome, f.total_pago, f.n_obs FROM socios_fornecedor s "
         "JOIN favorecido_resumo f ON f.favorecido_cpf=s.cnpj WHERE f.total_pago>0 AND s.socio_nome<>''")
    for r in con.execute(q):
        emp = r["favorecido_nome"] or ""
        en = ip.normalizar_nome(emp)
        if _RX_NAOCOM.search(en):
            continue
        if _RX_NAOCOM_ESCOLA.search(en) and not _RX_COMERCIAL.search(en):
            fora.setdefault("entidade_sem_fins_ou_estatal", set()).add(r["cnpj"])
            continue
        if not _RX_DONO.search(ip.normalizar_nome(r["qualificacao"] or "")):
            continue
        nn = ip.normalizar_nome(r["socio_nome"])
        if nn.count(" ") < 1:
            continue
        out.append({**dict(r), "nome_norm": nn})
    return out


def _carregar_folha(con, nomes: set[str]) -> dict[str, list[dict]]:
    """nome → pessoas distintas da folha com esse nome. Pessoa = (fonte, CPF posicional) quando a fonte
    publica CPF; senão (fonte, órgão, cargo). Guarda o período (1ª e última competência)."""
    pessoas: dict[tuple, dict] = {}
    cache: dict[str, str] = {}
    for r in con.execute("SELECT nome, cpf, orgao_nome, cargo, vinculo, fonte, competencia, matricula "
                         "FROM registros_folha WHERE nome IS NOT NULL"):
        nn = cache.get(r["nome"])
        if nn is None:
            nn = cache[r["nome"]] = ip.normalizar_nome(r["nome"])
        if nn not in nomes:
            continue
        pos = ip.posicoes_folha(r["cpf"], r["fonte"], r["competencia"])
        chave = (nn, r["fonte"], tuple(sorted(pos.items())) if pos else (r["orgao_nome"], r["cargo"]))
        p = pessoas.get(chave)
        comp = r["competencia"] or ""
        if p is None:
            pessoas[chave] = {"nome_norm": nn, "fonte": r["fonte"], "cpf": r["cpf"] or "", "pos": pos,
                              "orgao": r["orgao_nome"] or "", "cargo": r["cargo"] or "",
                              "vinculo": r["vinculo"] or "", "comp_min": comp, "comp_max": comp,
                              "matricula": r["matricula"] or ""}
        else:
            if comp and (not p["comp_min"] or comp < p["comp_min"]):
                p["comp_min"] = comp
            if comp and comp > p["comp_max"]:
                p["comp_max"], p["orgao"], p["cargo"], p["vinculo"] = (
                    comp, r["orgao_nome"] or p["orgao"], r["cargo"] or p["cargo"], r["vinculo"] or p["vinculo"])
    idx: dict[str, list[dict]] = {}
    for p in pessoas.values():
        idx.setdefault(p["nome_norm"], []).append(p)
    return idx


def _n_pessoas_folha(lst: list[dict]) -> int:
    """Pessoas distintas com o nome: registros de fontes diferentes cujo CPF posicional é compatível
    contam como UMA pessoa; sem CPF, cada (fonte, órgão, cargo) conta como uma (conservador)."""
    grupos: list[dict] = []
    n_sem = 0
    for p in lst:
        if not p["pos"]:
            n_sem += 1
            continue
        for g in grupos:
            if ip.comparar_cpf(g, p["pos"])[0] == ip.COMPATIVEL:
                g.update(p["pos"])
                break
        else:
            grupos.append(dict(p["pos"]))
    return len(grupos) + n_sem


def _prevalencia_qsa(con, nomes: set[str]) -> dict[str, int]:
    """nome → documentos distintos com esse nome no QSA das empresas coletadas (snapshot + atual)."""
    docs: dict[str, set] = {}
    fontes = [("socios_fornecedor", "socio_nome", "socio_doc"), ("socios_receita", "nome_socio", "doc_socio")]
    if _tabela_existe(con, "socio_snapshot"):
        fontes.append(("socio_snapshot", "nome_norm", "doc_socio"))
    for t, cn, cd in fontes:
        if not _tabela_existe(con, t):
            continue
        cache: dict[str, str] = {}
        for nome, doc in con.execute(f"SELECT {cn}, {cd} FROM {t}"):
            nn = cache.get(nome)
            if nn is None:
                nn = cache[nome] = ip.normalizar_nome(nome)
            if nn in nomes:
                docs.setdefault(nn, set()).add(re.sub(r"\D", "", doc or "") or "?")
    return {n: len(s) for n, s in docs.items()}


def _receita(con, nomes: set[str]) -> tuple[dict, dict]:
    """(cnpj_basico, nome) → {data_entrada, faixa_etaria}; (nome, doc) → set(cnpj_basico) (outras empresas)."""
    det, emp = {}, {}
    if not _tabela_existe(con, "socios_receita"):
        return det, emp
    for r in con.execute("SELECT cnpj_basico, nome_socio, doc_socio, data_entrada, faixa_etaria FROM socios_receita"):
        nn = ip.normalizar_nome(r["nome_socio"])
        if nn not in nomes:
            continue
        det[(r["cnpj_basico"], nn)] = {"data_entrada": r["data_entrada"] or "", "faixa": r["faixa_etaria"] or ""}
        emp.setdefault((nn, re.sub(r"\D", "", r["doc_socio"] or "")), set()).add(r["cnpj_basico"])
    return det, emp


def _ob_siafe(con, cnpj: str, ob_paga: str, ug_nome: dict) -> dict:
    rows = con.execute(f"SELECT ug_emitente ug, SUM(valor) v, COUNT(*) n FROM ob_orcamentaria_siafe "
                       f"WHERE {ob_paga} AND credor=? AND valor>0 GROUP BY ug_emitente ORDER BY v DESC",
                       (cnpj,)).fetchall()
    if not rows:
        return {"estado": "INDISPONIVEL", "total": None, "n_ob": 0, "ugs": []}
    return {"estado": "VERIFICADO", "total": round(sum(r["v"] for r in rows), 2), "n_ob": sum(r["n"] for r in rows),
            "ugs": [{"ug": r["ug"], "nome": ug_nome.get(r["ug"], ""), "valor": round(r["v"], 2)} for r in rows]}


def _data_br(d: str) -> str:
    d = re.sub(r"\D", "", d or "")
    return f"{d[6:8]}/{d[4:6]}/{d[:4]}" if len(d) == 8 else ""


def calcular(db_path: str | None = None) -> dict:
    """Cruzamento completo. Devolve pessoas por selo + contagem antes/depois + compatibilidade (`achados`)."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    con = _ro(db_path)
    try:
        try:
            ug_nome = json.loads((_REPO / "data" / "ug_index_siafe.json").read_text())["ugs"]
        except Exception:  # noqa: BLE001 — índice ausente: UG sem nome, número intacto
            ug_nome = {}
        fora: dict = {}
        socios = _socios_alvo(con, fora)
        nomes = {s["nome_norm"] for s in socios}
        folha = _carregar_folha(con, nomes)
        nomes_na_folha = set(folha)
        prev_qsa = _prevalencia_qsa(con, nomes_na_folha)
        receita, outras = _receita(con, nomes_na_folha)
        ob_paga = _ob_paga(con)
        tem_siafe = _tabela_existe(con, "ob_orcamentaria_siafe")

        # 1) cada (sócio × pessoa da folha de mesmo nome) é um PAR; classificar todos
        pessoas: dict[tuple, dict] = {}
        n_pares = 0
        for s in socios:
            cands = folha.get(s["nome_norm"])
            if not cands:
                continue
            doc = re.sub(r"\D", "", s["socio_doc"] or "")
            chave = (s["nome_norm"], doc)
            n_f = _n_pessoas_folha(cands)
            n_q = prev_qsa.get(s["nome_norm"], 1)
            rc = receita.get((s["cnpj"][:8], s["nome_norm"]), {})
            pe = pessoas.setdefault(chave, {"nome": s["socio_nome"], "nome_norm": s["nome_norm"],
                                            "cpf_mascarado": ip.mascarar(s["socio_doc"]), "doc": doc,
                                            "faixa": rc.get("faixa", ""), "n_folha_nome": n_f, "n_qsa_nome": n_q,
                                            "empresas": {}, "pares": {}})
            if rc.get("faixa") and not pe["faixa"]:
                pe["faixa"] = rc["faixa"]
            pe["empresas"].setdefault(s["cnpj"], {
                "cnpj": s["cnpj"], "cnpj_fmt": _cnpj_fmt(s["cnpj"]), "empresa": s["favorecido_nome"] or "",
                "qualificacao": s["qualificacao"] or "", "gerencia": bool(_RX_GERENCIA.search(ip.normalizar_nome(s["qualificacao"] or ""))),
                "data_entrada": _data_br(rc.get("data_entrada", "")), "tfe_total": s["total_pago"], "tfe_n_ob": s["n_obs"]})
            for p in cands:
                k = (p["fonte"], tuple(sorted(p["pos"].items())), p["orgao"], p["cargo"])
                if k in pe["pares"]:
                    continue
                n_pares += 1
                c = ip.classificar(doc_qsa=s["socio_doc"], cpf_folha=p["cpf"], fonte_folha=p["fonte"],
                                   competencia=p["comp_max"], pos_folha=p["pos"],
                                   n_folha_nome=n_f, n_qsa_nome=n_q, faixa_etaria=pe["faixa"] or rc.get("faixa"),
                                   vinculo=p["vinculo"], cpf_resolvido=s.get("cpf_resolvido"))
                pe["pares"][k] = {**c, "vinculo": p}

        # 2) cada PESSOA fica com o melhor selo; os vínculos que sustentam esse selo são os exibidos
        saida = {ip.VERIFICADO: [], ip.PROVAVEL: [], ip.INDETERMINADO: [], ip.HOMONIMO: []}
        for pe in pessoas.values():
            pares = list(pe["pares"].values())
            melhor = min(pares, key=lambda c: ip.ORDEM_SELO[c["selo"]])
            selo = melhor["selo"]
            vincs = [c for c in pares if c["selo"] == selo]
            n_hom = sum(1 for c in pares if c["selo"] == ip.HOMONIMO)
            vinculos = []
            ugs_vinc: set[str] = set()
            por_vinc: dict[tuple, dict] = {}
            for c in vincs:
                v = c["vinculo"]
                ugs = ugs_do_vinculo(v["orgao"], v["fonte"])
                ugs_vinc.update(ugs)
                k = (v["fonte"], v["orgao"], v["cargo"])
                if k in por_vinc:   # mesmo vínculo em janelas de CPF diferentes (DPRJ 2018): junta o período
                    pv = por_vinc[k]["periodo"]
                    pv[0] = min(x for x in (pv[0], _ano(v["comp_min"])) if x) if (pv[0] or v["comp_min"]) else ""
                    pv[1] = max(pv[1], _ano(v["comp_max"]))
                    continue
                por_vinc[k] = {"fonte": v["fonte"], "fonte_rotulo": ip.ROTULO_FONTE.get(v["fonte"], v["fonte"]),
                               "orgao": v["orgao"], "cargo": v["cargo"], "vinculo": v["vinculo"],
                               "periodo": [_ano(v["comp_min"]), _ano(v["comp_max"])],
                               "art9_verificavel": bool(ugs)}
            vinculos = list(por_vinc.values())
            empresas = []
            for e in pe["empresas"].values():
                ob = _ob_siafe(con, e["cnpj"], ob_paga, ug_nome) if tem_siafe else {
                    "estado": "INDISPONIVEL", "total": None, "n_ob": 0, "ugs": []}
                mesmo = [u for u in ob["ugs"] if u["ug"] in ugs_vinc]
                for u in ob["ugs"]:
                    u["mesmo_orgao"] = u["ug"] in ugs_vinc
                empresas.append({**e, "ob_siafe": ob, "mesmo_orgao": bool(mesmo),
                                 "ob_mesmo_orgao": round(sum(u["valor"] for u in mesmo), 2) if mesmo else 0.0})
            empresas.sort(key=lambda e: -(e["ob_siafe"]["total"] or 0))
            n_outras = max(0, len(outras.get((pe["nome_norm"], pe["doc"]), set()) - {e["cnpj"][:8] for e in empresas}))
            row = {"nome": pe["nome"], "cpf_mascarado": pe["cpf_mascarado"], "selo": selo,
                   "motivo": melhor["motivo"], "falta": melhor.get("falta", ""), "camadas": melhor["camadas"],
                   "faixa_etaria": ip.FAIXA_ETARIA.get(str(pe["faixa"]), ""),
                   "n_folha_nome": pe["n_folha_nome"], "n_qsa_nome": pe["n_qsa_nome"],
                   "homonimos_na_folha_descartados": n_hom if selo != ip.HOMONIMO else 0,
                   "vinculos": vinculos, "empresas": empresas, "outras_empresas_mesmo_cpf": n_outras,
                   "mesmo_orgao": any(e["mesmo_orgao"] for e in empresas),
                   "gerencia": any(e["gerencia"] for e in empresas),
                   "ob_total": round(sum(e["ob_siafe"]["total"] or 0 for e in empresas), 2),
                   "ob_mesmo_orgao": round(sum(e["ob_mesmo_orgao"] for e in empresas), 2)}
            saida[selo].append(row)
        for lst in saida.values():
            lst.sort(key=lambda r: (not r["mesmo_orgao"], not r["gerencia"], -(r["ob_total"] or 0)))
        folhas = sorted({p["fonte"] for lst in folha.values() for p in lst})
        return {"ok": True, "por_selo": saida, "n_pares_por_nome": n_pares, "n_pessoas_por_nome": len(pessoas),
                "contagem": {k.lower(): len(v) for k, v in saida.items()},
                "fora_do_escopo": {k: len(v) for k, v in fora.items()},
                "folhas": [ip.ROTULO_FONTE.get(f, f) for f in folhas]}
    finally:
        con.close()


def para_api(d: dict, limite: int = 150) -> dict:
    """Formato da rota /api/intel/socio_servidor: lista principal = VERIFICADO + PROVÁVEL; indeterminados
    e homônimos recolhidos. Mantém `achados` (uma linha por pessoa×empresa) para o relatório de inteligência."""
    if not d.get("ok"):
        return d
    ps = d["por_selo"]
    principal = ps[ip.VERIFICADO] + ps[ip.PROVAVEL]
    principal.sort(key=lambda r: (ip.ORDEM_SELO[r["selo"]], not r["mesmo_orgao"], not r["gerencia"], -(r["ob_total"] or 0)))
    achados = []
    for r in principal:
        v = (r["vinculos"] or [{}])[0]
        for e in r["empresas"]:
            achados.append({"socio": r["nome"], "cnpj": e["cnpj"], "cnpj_fmt": e["cnpj_fmt"], "empresa": e["empresa"],
                            "qualificacao": e["qualificacao"], "gerencia": e["gerencia"],
                            "confianca": "ALTA" if r["selo"] == ip.VERIFICADO else "MEDIA", "selo": r["selo"],
                            "servidor_orgao": v.get("orgao", ""), "servidor_cargo": v.get("cargo", ""),
                            "vinculo": v.get("vinculo", ""), "fonte_folha": v.get("fonte", ""),
                            "mesmo_orgao": e["mesmo_orgao"], "total_pago": e["ob_siafe"]["total"],
                            "n_obs": e["ob_siafe"]["n_ob"]})
    c = d["contagem"]
    return {"ok": True, "pessoas": principal[:limite], "n": len(principal),
            "indeterminados": ps[ip.INDETERMINADO][:limite], "homonimos": ps[ip.HOMONIMO][:limite],
            "contagem": c, "fora_do_escopo": d.get("fora_do_escopo", {}), "n_pares_por_nome": d["n_pares_por_nome"], "n_pessoas_por_nome": d["n_pessoas_por_nome"],
            "n_verificado": c["verificado"], "n_provavel": c["provavel"],
            "n_indeterminado": c["indeterminado"], "homonimos_descartados": c["homonimo"],
            "n_alta": c["verificado"], "n_gerencia": sum(1 for r in principal if r["gerencia"]),
            "n_art9": sum(1 for r in principal if r["mesmo_orgao"]),
            "achados": achados, "folhas": d["folhas"],
            "janela_cpf": {"QSA da Receita": "dígitos 4–9", "Executivo (GESPERJ)": "dígitos 4–9",
                           "Defensoria (DPRJ)": "dígitos 3–8", "TJRJ / Câmara do Rio": "sem CPF publicado"},
            "explicacao": ("Servidor público (folhas coletadas) que é sócio-dono de empresa paga pelo Estado. A "
                           "identidade é desambiguada antes de qualquer afirmação: CPF parcial comparado na janela "
                           "que cada fonte publica, prevalência do nome nas folhas e no QSA, faixa etária da Receita. "
                           "Par só-por-nome nunca entra na lista."),
            "ressalva": ("Indício ≠ acusação. Sócio quotista sem gerência pode ser lícito. VERIFICADO = CPF parcial "
                         "confere e um segundo dado converge; ainda assim, confirmar CPF completo pelo órgão antes "
                         "de citar em peça. Valores = OB paga no SIAFE (Contabilizada, sem erro de pagamento).")}


def medir(db_path: str | None = None) -> dict:
    """Antes × depois para o relatório: régua antiga (janela 3–8 para todas as folhas; nome-só = MÉDIA) ×
    régua em camadas."""
    d = calcular(db_path)
    return {"pares_por_nome": d["n_pares_por_nome"], "pessoas_por_nome": d["n_pessoas_por_nome"], **d["contagem"]}


if __name__ == "__main__":
    print(json.dumps(medir(), ensure_ascii=False, indent=1))
