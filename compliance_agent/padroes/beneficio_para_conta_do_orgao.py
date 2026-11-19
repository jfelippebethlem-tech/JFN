# -*- coding: utf-8 -*-
"""Benefício a pessoa física pago à conta do PRÓPRIO órgão — o "pago" do SIAFE não chegou ao cidadão.

ORIGEM (perícia por agente, 18/11/2026): Cartão Recomeçar — SEI-310001/000167/2024, 310003/000233/2024 e
310003/000236/2024. A OB sai com credor genérico "CG0013218 - Programa Recomeçar", natureza 339048 (Outros
Auxílios Financeiros a Pessoas Físicas), e o "Domicílio Bancário Destino" é a conta da própria SEDSODH
(CNPJ 28.165.513/0001-71, natureza jurídica 1023). O SIAFE registra R$ 15,68 mi como "pago", mas o dinheiro só mudou
de conta dentro do Estado; o retorno da operadora (carga dos cartões) e os termos de entrega não estão nos autos.

SINAL (lido na OB juntada ao SEI, não no espelho): credor genérico (CGnnnnnnn) + natureza de despesa de benefício a
pessoa física (3390 48 auxílio financeiro, 3390 18 bolsas, 3390 32 distribuição gratuita) + CNPJ do domicílio destino
cuja natureza jurídica (Receita) é ADMINISTRAÇÃO PÚBLICA. Grau:
  · forte  = destino é órgão/entidade ESTADUAL (1023 órgão do Executivo estadual, 1112 autarquia, 1147/1260 fundação, 1236 Estado, 1295/1325 fundo…);
  · medio  = destino é ente MUNICIPAL (1031, 1120, 1155, 1244, 1333…) — repasse a município executor também não prova o benefício;
  · fraco  = destino público de outra esfera.
O valor da OB é o do documento SEI; `valor_pago_ob` = soma das OB pagas do processo no SIAFE (piso).

EXPLICAÇÕES INOCENTES: é o desenho operacional de programas de cartão pré-pago (a Secretaria recebe e carrega os
cartões via operadora). Não é desvio por si; o vício é a liquidação sem prova de que o benefício chegou (Lei
4.320/1964 art. 63) — fecha com o retorno da operadora (arquivo de carga/crédito por CPF) e a conciliação da conta.
Indício para requerer documentos, não acusação.
"""
from __future__ import annotations

import re
import sqlite3

from compliance_agent.padroes import _pagamento_comum as C

ID = "beneficio_para_conta_do_orgao"

_TIT_OB = re.compile(r"ordem banc[aá]ria|^\s*anexo\s+\d{4}ob\d", re.I)
_RE_CG = re.compile(r"Credor\s+(CG\d{5,})\s*-\s*([^\n]{3,90})", re.I)
_RE_NAT = re.compile(r"Natureza\s+(3390(48|18|32))\s*-\s*([^\n]{3,80})", re.I)
_RE_DEST = re.compile(r"Domic[íi]lio\s+Banc[áa]rio\s+Destino\s+([^\n]{0,60}?)\((\d{14})\)", re.I)
_RE_VAL = re.compile(r"\bValor\s*\n(?:[^\n]*\n){0,3}?\s*(" + C.MOEDA + r")\s*\n", re.I)
_RE_NUM = re.compile(r"\b(\d{4}OB\d{5})\b")
_RE_EMI = re.compile(r"Emiss[ãa]o\s*\n(?:[^\n]*\n){0,3}?\s*(\d{2}/\d{2}/\d{2,4})\s*\n", re.I)

# Tabela de natureza jurídica da Receita (grupo 1 = administração pública).
ESTADUAL = {"1023", "1058", "1082", "1112", "1147", "1171", "1236", "1260", "1295", "1325"}
MUNICIPAL = {"1031", "1066", "1120", "1155", "1180", "1244", "1279", "1309", "1333"}


def ler_ob(texto: str) -> dict | None:
    """OB de benefício a credor genérico com destino identificado; senão None."""
    cg, nat, dest = _RE_CG.search(texto), _RE_NAT.search(texto), _RE_DEST.search(texto)
    if not (cg and nat and dest):
        return None
    v, n, e = _RE_VAL.search(texto), _RE_NUM.search(texto), _RE_EMI.search(texto)
    return {"credor": f"{cg[1]} - {re.sub(r' +', ' ', cg[2]).strip()}", "natureza": f"{nat[1]} - {nat[3].strip()}",
            "destino_cnpj": dest[2], "destino_conta": dest[1].strip(" -"), "valor": C.num(v[1]) if v else None,
            "ob": n[1] if n else None, "emissao": e[1] if e else None,
            "_prova": C.trecho(texto, dest.start(), dest.end(), 10), "_prova_cg": re.sub(r"\s+", " ", cg[0]).strip()}


def grau(natureza_juridica: str | None) -> str | None:
    if not natureza_juridica or not natureza_juridica.startswith("1"):
        return None                          # destino privado (operadora, banco): não é este padrão
    if natureza_juridica in ESTADUAL:
        return "forte"
    if natureza_juridica in MUNICIPAL:
        return "medio"
    return "fraco"


# Prova de que o crédito chegou ao beneficiário (retorno da operadora/banco): se os autos a têm, o grau cai a medio.
_TIT_RETORNO = re.compile(r"arquivo de retorno|\bretorno\b|cr[eé]ditos? efetivad|comprovante de (carga|cr[eé]dito)|"
                          r"rela[cç][aã]o de cr[eé]ditos|presta[cç][aã]o de contas", re.I)


# Folha nominal de pagamento (beneficiário, CPF, agência e conta — Aluguel Social, SEI-310001/000106/2026): o banco
# credita a partir da conta do órgão em conta individual; a destinação está individualizada, falta só o retorno.
_TIT_FOLHA_NOMINAL = re.compile(r"planilha de pagamento|folha de pagamento|rela[cç][aã]o de pagamento", re.I)


def _pasta(pasta, man, sel):
    retorno = [C.numero_doc(d) for d in C.docs(man) if _TIT_RETORNO.search(str(d.get("titulo") or ""))
               or _TIT_FOLHA_NOMINAL.search(str(d.get("titulo") or ""))]
    obs = []
    for d in sel:
        t = C.ler(pasta, man, d, teto=6000)
        o = ler_ob(t) if t else None
        if o:
            obs.append({**o, "doc": C.numero_doc(d), "titulo": str(d.get("titulo") or "")[:120]})
    return ([{"tag": pasta.name, "obs": obs, "retorno": retorno[:5]}] if obs else []), {"obs_lidas": len(sel), "obs_beneficio_cg": len(obs)}


def varrer(limite: int | None = None, so: list[str] | None = None) -> dict:
    brutos, cob, n = C.varrer_acervo(_TIT_OB, _pasta, so=so, limite=limite)
    est = sqlite3.connect(f"file:{C.RAIZ / 'data' / 'receita_estab.db'}?mode=ro", uri=True, timeout=30)
    con = C.con_ro()
    pagos = C.obs_pagas(con, [C.processo(b["tag"]) for b in brutos])
    achados = []
    for b in brutos:
        proc = C.processo(b["tag"])
        por_destino: dict[str, list[dict]] = {}
        for o in b["obs"]:
            por_destino.setdefault(o["destino_cnpj"], []).append(o)
        for cnpj, obs in por_destino.items():
            r = est.execute("SELECT razao_social, natureza_cod FROM empresas WHERE cnpj_basico=?",
                            (cnpj[:8],)).fetchone()
            g = grau(r[1] if r else None)
            if g == "forte" and b["retorno"]:
                g = "medio"                  # retorno, prestação de contas ou folha nominal: quem abre confere o valor
            if not g:
                cob["destino_privado_ou_desconhecido"] = cob.get("destino_privado_ou_desconhecido", 0) + 1
                continue
            uniq = {o["ob"] or o["doc"]: o for o in obs}
            soma_docs = round(sum(o["valor"] or 0 for o in uniq.values()), 2)
            o0 = next(iter(uniq.values()))
            achados.append({
                "processo": proc, "grau": g, "orgao_destino": r[0], "natureza_juridica_destino": r[1],
                "destino_cnpj": f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}",
                "credor_siafe": o0["credor"], "natureza_despesa": o0["natureza"],
                "obs_sei": sorted(k for k in uniq), "valor_obs_sei": soma_docs,
                "prova": f"{o0['doc']} — \"{o0['_prova_cg']}\" … \"{o0['_prova']}\"",
                "valor_pago_ob": C.pago(pagos.get(proc, [])), "docs_de_retorno": b["retorno"],
                "porque": ("benefício a pessoa física com credor genérico depositado na conta de ente público "
                           f"({r[0]}); inocente plausível: modelo de cartão pré-pago — falta o retorno da operadora "
                           "(carga por beneficiário) e a conciliação da conta para provar a liquidação"),
                "fonte": "OB juntada ao SEI (domicílio destino) + receita_estab.empresas (natureza jurídica) + "
                         "ob_orcamentaria_siafe/_ob_paga (piso)"})
    est.close()
    con.close()
    return C.resultado(ID, n, cob, achados, "data/sei_arquivo (OB juntadas) × receita_estab × SIAFE")
