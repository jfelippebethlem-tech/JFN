# -*- coding: utf-8 -*-
"""Contratada cujo SÓCIO é sócio de empresa SANCIONADA — pagamento dentro da janela de risco.

POR QUE EXISTE. O caso GRANÁ × GUARAILHA (03/11/2026) só apareceu por leitura humana: desde 08/10/2025 o
sócio único da GUARAILHA é o sócio único da M L DISTRIBUIDORA, declarada inidônea sem prazo (CEIS, 2021),
na loja vizinha do mesmo número, mesmo CNAE. O C7 (sancionada contratada) olha só o CNPJ contratado, e a
sanção não passava para a empresa irmã. Este cruzamento procura o padrão na base inteira.

BASE (conferida na fonte, 03/11/2026):
  • Lei 14.133/2021, art. 14, III e §1º — o impedimento "será também aplicado ao licitante" "que atue em
    substituição a outra pessoa, física ou jurídica" (interposta pessoa).
  • Lei 14.133/2021, art. 160 — desconsideração da personalidade jurídica estende a sanção a "administradores
    e sócios com poderes de administração", à "pessoa jurídica sucessora" e à "empresa do mesmo ramo com
    relação de coligação ou controle", com "contraditório, ampla defesa" e "análise jurídica prévia".
  • TCU, Acórdão 1831/2014-Plenário (rel. José Múcio, TC 022.685/2013-8; existência conferida no índice
    TCU local; teor por fontes secundárias): abuso evidenciado por (a) identidade dos sócios, (b) mesmo
    ramo, (c) transferência do acervo técnico e humano.
  A força do sinal espelha esses critérios: mesmo CNAE = (b); mesmo endereço/telefone = proxy de (c).

O QUE CONTA. Só a OB SIAFE Contabilizada paga à contratada na JANELA em que, ao mesmo tempo, a pessoa era
sócia da contratada, era sócia da sancionada e a sanção VEDAVA contratar com o Estado do RJ (alcance por
`sancao_abrangencia.veda_ente`: inidoneidade alcança todos; impedimento só o ente que aplicou).

LIMITES. Indício, não acusação: art. 160 exige abuso provado em processo próprio. QSA da Receita com
snapshots desde 2023-03 (antes disso vale a data de entrada declarada). CPF mascarado; homônimo com o
mesmo fragmento de CPF é raro, mas possível. Pagamento é piso (cobertura parcial do SIAFE).
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from compliance_agent.sancao_abrangencia import veda_ente

_REPO = Path(__file__).resolve().parents[1]
_SQL_PAGO = (
    "SELECT COALESCE(SUM(valor),0), COUNT(*) FROM ob_orcamentaria_siafe "
    "WHERE substr(credor,1,8)=? AND status='Contabilizado' AND valor>0 AND "
    "substr(data_emissao,7,4)||substr(data_emissao,4,2)||substr(data_emissao,1,2) BETWEEN ? AND ?")


def _iso(d: str | None) -> str:
    d = (d or "").strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    if len(d) == 7:
        return d + "-01"
    return d[:10]


def _forca(cnae: bool, endereco: bool, telefone: bool) -> str:
    if cnae and (endereco or telefone):
        return "forte"
    return "medio" if (cnae or endereco or telefone) else "fraco"


def socio_de_sancionada(db_path: str | None = None, estab_path: str | None = None,
                        hoje: str | None = None) -> dict:
    hoje = hoje or date.today().isoformat()
    con = sqlite3.connect(f"file:{db_path or _REPO / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=30)
    try:
        sanc: dict[str, list[dict]] = defaultdict(list)
        for cad, cnpj, cat, ini, fim, org, uf, fund in con.execute(
                "SELECT cadastro, cpf_cnpj, categoria, data_inicio, data_fim, orgao, uf, fundamentacao "
                "FROM sancoes_federais WHERE length(cpf_cnpj)=14"):
            v = veda_ente({"cadastro": cad, "categoria": cat, "orgao": org, "uf": uf, "fundamentacao": fund})
            if v["veda"] and ini:
                sanc[cnpj[:8]].append({"categoria": cat, "inicio": ini, "fim": fim or "9999-12-31",
                                       "orgao": org, "abrangencia": v["abrangencia"]})
        por_pessoa: dict[tuple, list[dict]] = defaultdict(list)
        n_socios: dict[str, int] = defaultdict(int)
        for b, doc, nome, ent, de, ate, st in con.execute(
                "SELECT cnpj_basico, doc_socio, nome_norm, data_entrada, visto_de, visto_ate, status "
                "FROM socio_historico WHERE doc_socio LIKE '***%'"):
            por_pessoa[(doc, nome)].append({"b": b, "ent": _iso(ent) or _iso(de),
                                            "fim": hoje if st == "ativo" else _iso(ate)[:7] + "-28"})
            n_socios[b] += st == "ativo"

        melhor: dict[tuple, dict] = {}
        for (doc, nome), emps in por_pessoa.items():
            nas_sanc = [e for e in emps if e["b"] in sanc]
            if not nas_sanc:
                continue
            for a in emps:
                if a["b"] in sanc:
                    continue                         # a própria sancionada contratada é o C7, não aqui
                for s in nas_sanc:
                    for sc in sanc[s["b"]]:
                        if (s["ent"] and s["ent"] > sc["fim"]) or s["fim"] < sc["inicio"]:
                            continue                 # não era sócio da sancionada durante a sanção
                        ini, fim = max(a["ent"] or "0000-00-00", sc["inicio"]), min(a["fim"], sc["fim"], hoje)
                        if ini > fim:
                            continue
                        v, n = con.execute(_SQL_PAGO, (a["b"], ini.replace("-", ""), fim.replace("-", ""))).fetchone()
                        if v > 0 and v > melhor.get((a["b"], s["b"]), {}).get("pago_janela", 0):
                            melhor[(a["b"], s["b"])] = {
                                "contratada": a["b"], "sancionada": s["b"], "socio": nome, "socio_doc": doc,
                                "janela": [ini, fim], "pago_janela": round(v, 2), "n_obs": n, "sancao": sc}
    finally:
        con.close()

    estab = sqlite3.connect(f"file:{estab_path or _REPO / 'data' / 'receita_estab.db'}?mode=ro", uri=True, timeout=30)
    try:
        def _cad(b):
            e = estab.execute("SELECT cnae_principal, endereco_norm, telefone1 FROM estabelecimentos "
                              "WHERE cnpj_basico=? AND matriz_filial='1'", (b,)).fetchone() or (None, None, None)
            r = estab.execute("SELECT razao_social FROM empresas WHERE cnpj_basico=?", (b,)).fetchone()
            return e, (r[0] if r else "")
        achados = []
        for d in melhor.values():
            (ca, ra), (cb, rb) = _cad(d["contratada"]), _cad(d["sancionada"])
            m = {k: bool(ca[i] and ca[i] == cb[i]) for i, k in enumerate(("cnae", "endereco", "telefone"))}
            achados.append({**d, "razao_contratada": ra, "razao_sancionada": rb, "mesmo": m,
                            "socios_ativos_contratada": n_socios.get(d["contratada"], 0),
                            "forca": _forca(m["cnae"], m["endereco"], m["telefone"])})
    finally:
        estab.close()
    ordem = {"forte": 0, "medio": 1, "fraco": 2}
    achados.sort(key=lambda x: (ordem[x["forca"]], -x["pago_janela"]))
    return {"ok": True, "n": len(achados),
            "por_forca": {k: sum(a["forca"] == k for a in achados) for k in ordem},
            "nota": "Indício a verificar, não acusação: a extensão da sanção exige abuso provado (Lei 14.133, "
                    "art. 160). Pagamento = OB SIAFE na janela de risco (piso).",
            "achados": achados}
