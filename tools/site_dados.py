"""Dados REAIS do site novo (jfn-site) — 27/11/2026. Cada número sai com fonte, recorte e estado
(VERIFICADO | INDISPONIVEL), regra 9 do CLAUDE.md: nada no painel sem proveniência.

Recortes (decididos pela medida de 27/11, não por suposição):
  • "pago" = OB paga do SIAFE pela regra única `cruzamentos_intel._ob_paga`;
  • "a fornecedores" = credor com CNPJ (14 dígitos). Credor genérico "CG…" (folha, tributos, consignações; R$ 245 bi)
    e credor = UG (transferências internas; R$ 43 bi) NÃO são fornecedores e ficam fora;
  • a data do SIAFE é TEXTO DD/MM/AAAA — convertida antes de comparar.
Empenho e liquidação por contrato: NE/NL ainda não coletadas → INDISPONIVEL (o site mostra assim, nunca zero).
Uso: python -m tools.site_dados <saida.json>"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from compliance_agent import ug_nomes
from compliance_agent.entidades_gov import eh_administracao_publica, eh_nao_fornecedor
from compliance_agent.cruzamentos_intel import _ob_paga
from compliance_agent.reporting.intel_base import moeda

CNPJ = "length(replace(replace(replace(credor,'.',''),'/',''),'-','')) = 14"
DATA_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"
FONTE_OB = "SIAFE-Rio · Ordem Bancária paga (regra _ob_paga)"


def _n(valor, fonte: str, recorte: str, estado: str = "VERIFICADO") -> dict:
    return {"valor": valor, "fonte": fonte, "recorte": recorte, "estado": estado}


def _sem_acento(t: str) -> str:
    import unicodedata
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().upper()).strip()


# grafias do SIAFE que não trazem o nome do município por extenso (medidas 27/11/2026)
APELIDO_MUN = {"RJ": "RIO DE JANEIRO", "CIDADE DO RJ": "RIO DE JANEIRO", "PMVR": "VOLTA REDONDA", "RIO DE JAN": "RIO DE JANEIRO",
               "ARMACAO DE BUZIOS": "ARMACAO DOS BUZIOS", "VARRE SAI": "VARRE-SAI", "CARABEPUS": "CARAPEBUS"}
# abreviações do SIAFE expandidas ANTES de casar (só prefixos de nome; município de outro estado continua sem casar)
_ABREV = ((r"^S\.\s*", "SAO "), (r"^STO\.\s*", "SANTO "), (r"^STA\.\s*", "SANTA "), (r"^COM\.\s*", "COMENDADOR "),
          (r"^ARMAC\.\s*", "ARMACAO "))


def _expandir(k: str) -> str:
    for pad, rep in _ABREV:
        k = re.sub(pad, rep, k)
    return APELIDO_MUN.get(k, k)
_RE_MUN = re.compile(r"(?:FUNDO\s+MUN(?:ICIPAL|\.)?\s+DE\s+SAUDE|PREFEITURA\s+MUNICIPAL|MUNICIPIO)\s+(?:DE\s+|DA\s+|DO\s+|DOS\s+)?(?:CIDADE\s+DO\s+)?(.+)")


def transferencias(con, paga: str, publicos: set, ibge: list[dict]) -> dict:
    """Para onde vai o dinheiro que NÃO é pagamento a fornecedor: entes públicos (CNPJ), unidades do próprio Estado
    (credor = UG) e credores genéricos (CG…: folha, previdência, encargos). Repasses a município casados com o IBGE;
    o que não casar vai LISTADO (nunca some)."""
    d = "replace(replace(replace(credor,'.',''),'/',''),'-','')"
    def top(sql, args=()):
        return [{"nome": (nm or "").strip(), "valor": round(v, 2)} for nm, v in con.execute(sql, args)]
    entes = [(c, nm, v) for c, nm, v in con.execute(
        f"SELECT credor, max(nome_credor), sum(valor) FROM ob_orcamentaria_siafe WHERE {paga} AND {CNPJ} GROUP BY credor")
        if re.sub(r"\D", "", c or "") in publicos or eh_nao_fornecedor(nm or "")]
    por_nome = {_sem_acento(m["nome"]): m for m in ibge}
    mun, sem_casar = {}, {}
    for _, nm, v in entes:
        m = _RE_MUN.search(_sem_acento(nm))
        if not m:
            continue
        k = re.sub(r"\s+(PMVR|SMS|FMS|-).*$", "", m.group(1)).strip(" .-")
        k = _expandir(k)
        if k in por_nome:
            x = mun.setdefault(k, {**por_nome[k], "valor": 0.0}); x["valor"] = round(x["valor"] + v, 2)
        else:
            sem_casar[k] = round(sem_casar.get(k, 0) + v, 2)
    unidades = top(f"SELECT max(nome_credor), sum(valor) s FROM ob_orcamentaria_siafe WHERE {paga} AND length({d})=6 GROUP BY credor ORDER BY s DESC LIMIT 10")
    genericos = top(f"SELECT upper(trim(nome_credor)) nm, sum(valor) s FROM ob_orcamentaria_siafe WHERE {paga} AND {d} GLOB 'CG*' GROUP BY nm ORDER BY s DESC LIMIT 10")
    tot_u = con.execute(f"SELECT sum(valor) FROM ob_orcamentaria_siafe WHERE {paga} AND length({d})=6").fetchone()[0] or 0
    tot_g = con.execute(f"SELECT sum(valor) FROM ob_orcamentaria_siafe WHERE {paga} AND {d} GLOB 'CG*'").fetchone()[0] or 0
    entes_top = sorted(({"nome": (nm or "").strip(), "valor": round(v, 2)} for _, nm, v in entes), key=lambda x: -x["valor"])[:12]
    return {
        "entes_publicos": {**_n(round(sum(v for *_, v in entes), 2), FONTE_OB, "credores com CNPJ que são entes públicos (repasses)"), "maiores": entes_top},
        "unidades_do_estado": {**_n(round(tot_u, 2), FONTE_OB, "credor = UG do próprio Estado (circula dentro do Estado)"), "maiores": unidades},
        "credores_genericos": {**_n(round(tot_g, 2), FONTE_OB, "credor genérico CG… (folha, previdência, encargos)"), "maiores": genericos},
        "por_municipio": sorted(mun.values(), key=lambda x: -x["valor"]),
        "municipios_sem_casar": sem_casar,
        "ressalvas": ["2016–2020 com cobertura parcial (coleta do SIAFE 1): comparação entre anos só a partir de 2021",
                      "«Ministério da Fazenda» é o CNPJ 00.394.460/0108-80 (Receita Federal): TRIBUTO pago por DARF, não repasse a "
                      "município — confirmado em amostra (SEI-030001/036633/2026: Auto de Infração RFB 10872.720148/2019-77, "
                      "R$ 8.833.111,94); os recolhimentos mensais restantes seguem a confirmar por amostra maior"],
    }


def gerar(con: sqlite3.Connection, vault: Path) -> dict:
    paga = _ob_paga(con)
    # ente público NÃO é fornecedor (regra da casa): nome (entidades_gov.eh_nao_fornecedor — fundos, prefeituras, AAE,
    # tributos) OU natureza jurídica 1xxx da Receita (orgao_esfera). 27/11: sem isso o «maior fornecedor» do Fundo
    # Estadual de Saúde eram FUNDOS MUNICIPAIS DE SAÚDE (repasse a município).
    publicos = {c for c, nat in con.execute("SELECT cnpj, natureza FROM orgao_esfera") if eh_administracao_publica(nat)}
    def eh_fornecedor(credor, nome):
        return re.sub(r"\D", "", credor or "") not in publicos and not eh_nao_fornecedor(nome or "")
    por_credor = con.execute(f"SELECT credor, max(nome_credor), sum(valor), count(*), min(exercicio), max(exercicio) "
                             f"FROM ob_orcamentaria_siafe WHERE {paga} AND {CNPJ} GROUP BY credor").fetchall()
    forn_all = [r for r in por_credor if eh_fornecedor(r[0], r[1])]
    tot = round(sum(r[2] for r in forn_all), 2); n = sum(r[3] for r in forn_all); nforn = len(forn_all)
    excl = round(sum(r[2] for r in por_credor) - tot, 2)
    ano_ini = min(r[4] for r in forn_all); ano_fim = max(r[5] for r in forn_all)
    ultima = con.execute(f"SELECT max({DATA_ISO}) FROM ob_orcamentaria_siafe WHERE {paga} AND data_emissao GLOB '[0-3][0-9]/[01][0-9]/[12][0-9][0-9][0-9]'").fetchone()[0]
    recorte = f"credores com CNPJ que não são entes públicos, exercícios {ano_ini}–{ano_fim}"
    n_base = con.execute(f"SELECT count(*) FROM ob_orcamentaria_siafe WHERE {paga}").fetchone()[0]
    n_ultimo = con.execute(f"SELECT count(*) FROM ob_orcamentaria_siafe WHERE {paga} AND {DATA_ISO} = ?", (ultima,)).fetchone()[0]

    # órgão em destaque: a UG que mais pagou a FORNECEDORES no exercício mais recente
    por_ug = {}
    linhas = con.execute(f"SELECT ug_pagadora, credor, max(nome_credor), sum(valor), count(*) FROM ob_orcamentaria_siafe "
                         f"WHERE {paga} AND {CNPJ} AND exercicio = ? GROUP BY ug_pagadora, credor", (ano_fim,)).fetchall()
    for u, c, nm, v, k in linhas:
        if eh_fornecedor(c, nm):
            por_ug.setdefault(u, []).append({"cnpj": c, "nome": (nm or "").strip(), "valor": round(v, 2), "obs": k})
    ug = max(por_ug, key=lambda u: sum(x["valor"] for x in por_ug[u]))
    ug_total = sum(x["valor"] for x in por_ug[ug])
    forn = sorted(por_ug[ug], key=lambda x: -x["valor"])[:24]
    casos = sorted(vault.glob("*.md"))
    ibge = json.loads((Path(__file__).resolve().parent.parent / "config" / "ibge_municipios_rj.json").read_text())["municipios"]
    for m in ibge:
        m["chave"] = _sem_acento(m["nome"])
    ibge_idx = [{**m, "nome": m["nome"]} for m in ibge]
    trans = transferencias(con, paga, publicos, [{**m, "nome": m["chave"], "nome_oficial": m["nome"]} for m in ibge_idx])
    return {
        "transferencias": trans,
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inicio": {
            "pago_fornecedores": _n(tot, FONTE_OB, recorte),
            "ordens_bancarias": _n(n, FONTE_OB, recorte),
            "fornecedores": _n(nforn, FONTE_OB, recorte + " · CNPJs distintos"),
            "fora_por_ser_ente_publico": _n(excl, FONTE_OB, "OB a credores com CNPJ que são entes públicos (repasses), excluídas do total"),
            "casos_no_acervo": _n(len(casos), "Acervo de casos do JFN (vault/casos)", "todos os dossiês, abertos e fechados"),
            "siafe_ultima_ob": _n(ultima, FONTE_OB, "data de emissão mais recente na base"),
            "ob_pagas_na_base": _n(n_base, FONTE_OB, "todas as OB pagas, qualquer credor"),
            "ob_no_ultimo_dia": _n(n_ultimo, FONTE_OB, "OB pagas emitidas na data mais recente da base"),
        },
        "orgao": {
            "ug": ug, "nome": ug_nomes.subordinacao(ug, ano_fim) or ug, "exercicio": ano_fim,
            "pago_fornecedores": _n(round(ug_total, 2), FONTE_OB, f"UG {ug}, exercício {ano_fim}, credores com CNPJ"),
            "fornecedores": forn,
            "nota": "altura do prédio = OB paga no exercício; indício não é marcado aqui (ver Casos)",
        },
        "dinheiro": {
            "empenhado": _n(None, "SIAFE-Rio · Nota de Empenho", "por contrato", "INDISPONIVEL"),
            "liquidado": _n(None, "SIAFE-Rio · Nota de Liquidação", "por contrato", "INDISPONIVEL"),
            "nota": "NE e NL por contrato ainda não coletadas (plano: coleta NE/NL por UG); o pago (OB) existe",
        },
    }


def main(argv: list[str]) -> int:
    con = sqlite3.connect("file:data/compliance.db?mode=ro", uri=True, timeout=60)
    d = gerar(con, Path.home() / "vault" / "casos")
    Path(argv[1]).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    i = d["inicio"]
    print(f"site_dados: ok — pago a fornecedores R$ {moeda(i['pago_fornecedores']['valor'])} ({i['pago_fornecedores']['recorte']}); "
          f"órgão {d['orgao']['nome']} com {len(d['orgao']['fornecedores'])} fornecedores; última OB {i['siafe_ultima_ob']['valor']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
