# -*- coding: utf-8 -*-
"""comparador_precos — quanto cada ÓRGÃO paga pelo MESMO item, quem é caro/barato.

Responde às perguntas do dono: para um objeto (aluguel de carro, medicamento, refeição…),
QUAIS ÓRGÃOS pagam mais ou menos? QUAIS FORNECEDORES são caros/baratos? QUAIS ÓRGÃOS gastam
melhor o recurso público? Fonte: preço UNITÁRIO homologado do PNCP (mesmo dado do sobrepreço),
agrupado pela descrição normalizada do item + unidade de medida.

Três produtos:
  • `buscar_grupos(termo)`  — grupos de item que casam o termo, com mediana/min/max/dispersão.
  • `comparar(grupo, un)`   — ranking de ÓRGÃOS e de FORNECEDORES por preço unitário desse item.
  • `ranking_orgaos()` / `ranking_fornecedores()` — eficiência transversal (paga acima/abaixo da
    mediana do item, agregado por muitos itens): quem gasta melhor, quem cobra mais caro.

Determinístico. Robusto a outlier (mediana). Guarda anti-artefato: preço < 10% da mediana do item
(erro de unidade/lote no PNCP) é descartado da comparação. Indício ≠ acusação; a descrição do
PNCP é curta e pode misturar marca/especificação — confirmar no termo de referência."""
from __future__ import annotations

import logging
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from compliance_agent.cruzamentos_intel import _mediana, _norm_item

_REPO = Path(__file__).resolve().parent.parent
_DB = str(_REPO / "data" / "compliance.db")

logger = logging.getLogger(__name__)

RESSALVA = ("Preço unitário do PNCP; a descrição é curta e pode misturar marca/especificação/"
            "embalagem entre compras. Preços < 10% da mediana do item são descartados (artefato de "
            "unidade/lote). É comparação de mercado para priorizar auditoria, não veredito de "
            "sobrepreço — confirmar o termo de referência. Indício ≠ acusação.")


def _ro(db_path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path or _DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _un(u: str | None) -> str:
    return re.sub(r"[^a-z]", "", (u or "").lower())[:8]


def _linhas(con):
    return con.execute(
        "SELECT item_descricao d, unidade_medida un, valor_unitario vu, quantidade, orgao_nome, "
        "unidade_nome, fornecedor_nome, fornecedor_cnpj, certame, data_pub "
        "FROM pncp_resultado WHERE ordem_classificacao=1 AND valor_unitario>0 AND quantidade>=2 "
        "AND item_descricao IS NOT NULL AND length(item_descricao)>=4").fetchall()


def _grupos(con) -> dict:
    g: dict[tuple, list] = defaultdict(list)
    for r in _linhas(con):
        base = _norm_item(r["d"])
        if base:
            g[(base, _un(r["un"]))].append(r)
    return g


def buscar_grupos(termo: str, db_path: str | None = None, min_compras: int = 3,
                  min_orgaos: int = 2, limite: int = 40) -> dict:
    """Grupos de item cuja descrição normalizada casa TODAS as palavras do termo, com estatística
    de preço. Ex.: 'aluguel carro' → grupos de locação de veículo comparáveis entre órgãos."""
    toks = [t for t in _norm_item(termo).split() if t] or [t for t in re.sub(r"[^a-z ]", " ",
            (termo or "").lower()).split() if len(t) >= 3]
    con = _ro(db_path)
    try:
        achados = []
        for (base, un), itens in _grupos(con).items():
            if not all(t in base for t in toks):
                continue
            orgaos = {r["unidade_nome"] or r["orgao_nome"] for r in itens}
            if len(itens) < min_compras or len(orgaos) < min_orgaos:
                continue
            precos = sorted(r["vu"] for r in itens)
            med = _mediana(precos)
            achados.append({
                "grupo": base, "unidade_medida": itens[0]["un"],
                "exemplo": itens[0]["d"], "n_compras": len(itens), "n_orgaos": len(orgaos),
                "mediana": round(med, 2), "min": round(precos[0], 2), "max": round(precos[-1], 2),
                "dispersao": round(precos[-1] / precos[0], 1) if precos[0] > 0 else None})
        achados.sort(key=lambda a: -(a["dispersao"] or 0))
        return {"ok": True, "termo": termo, "grupos": achados[:limite], "n": len(achados),
                "explicacao": ("Grupos de item comprados por ≥2 órgãos que casam o termo. Dispersão "
                               "alta = os órgãos pagam preços MUITO diferentes pelo mesmo item — "
                               "abra o grupo para ver quem paga mais/menos."),
                "ressalva": RESSALVA}
    finally:
        con.close()


def comparar(grupo: str, unidade: str | None = None, db_path: str | None = None) -> dict:
    """Para UM item (grupo normalizado + unidade), ranqueia ÓRGÃOS e FORNECEDORES pelo preço
    unitário mediano. Mostra quem paga acima/abaixo da mediana geral do item."""
    un_alvo = _un(unidade) if unidade is not None else None
    con = _ro(db_path)
    try:
        itens = [r for (b, u), lst in _grupos(con).items() if b == grupo
                 and (un_alvo is None or u == un_alvo) for r in lst]
        if not itens:
            return {"ok": False, "erro": f"grupo '{grupo}' sem compras comparáveis"}
        med_geral = _mediana(sorted(r["vu"] for r in itens))
        piso = 0.10 * med_geral                      # < 10% da mediana = artefato
        val = [r for r in itens if r["vu"] >= piso]

        def _rank(chave_fn, ident_fn=None):
            agg: dict = defaultdict(list)
            ident: dict = {}
            for r in val:
                k = chave_fn(r)
                agg[k].append(r["vu"])
                if ident_fn:
                    ident[k] = ident_fn(r)
            out = []
            for k, ps in agg.items():
                m = _mediana(sorted(ps))
                out.append({"nome": k, "id": ident.get(k), "n": len(ps),
                            "mediana": round(m, 2),
                            "vs_geral": round(m / med_geral, 2) if med_geral > 0 else None})
            out.sort(key=lambda x: -(x["vs_geral"] or 0))
            return out

        orgaos = _rank(lambda r: r["unidade_nome"] or r["orgao_nome"])
        fornecedores = _rank(lambda r: r["fornecedor_nome"], lambda r: r["fornecedor_cnpj"])
        return {"ok": True, "grupo": grupo, "unidade_medida": itens[0]["un"],
                "exemplo": itens[0]["d"], "mediana_geral": round(med_geral, 2),
                "n_compras": len(val), "n_orgaos": len(orgaos), "n_fornecedores": len(fornecedores),
                "orgaos": orgaos, "fornecedores": fornecedores[:60],
                "explicacao": ("Preço unitário mediano por órgão e por fornecedor para o MESMO item. "
                               "'vs_geral' = quantas vezes acima/abaixo da mediana geral do item "
                               "(>1 paga/cobra mais caro; <1 mais barato)."),
                "ressalva": RESSALVA}
    finally:
        con.close()


def _eficiencia(con, por: str, min_itens: int) -> list:
    """Agrega, por órgão OU fornecedor, a razão preço/mediana-do-item ao longo de MUITOS itens.
    razão mediana <1 = paga/cobra abaixo do mercado; >1 = acima. Exige ≥`min_itens` itens DISTINTOS
    comparáveis (diversidade real, não a mesma compra repetida) para significância."""
    razoes: dict = defaultdict(list)
    itens_de: dict = defaultdict(set)                 # k -> conjunto de itens distintos (sem cap)
    ident: dict = {}
    for (base, un), itens in _grupos(con).items():
        orgaos = {r["unidade_nome"] or r["orgao_nome"] for r in itens}
        if len(itens) < 3 or len(orgaos) < 2:
            continue                                  # só item comparável entra na eficiência
        med = _mediana(sorted(r["vu"] for r in itens))
        if med <= 0:
            continue
        piso = 0.10 * med
        for r in itens:
            if r["vu"] < piso:
                continue
            if por == "orgao":
                k = r["unidade_nome"] or r["orgao_nome"]
            else:
                k = r["fornecedor_nome"]
                ident[k] = r["fornecedor_cnpj"]
            razoes[k].append(r["vu"] / med)
            itens_de[k].add(base)
    out = []
    for k, rs in razoes.items():
        n_itens = len(itens_de[k])
        if n_itens < min_itens:                       # significância = DIVERSIDADE de itens
            continue
        out.append({"nome": k, "id": ident.get(k), "n_compras": len(rs),
                    "n_itens": n_itens, "razao_mediana": round(_mediana(sorted(rs)), 2),
                    "itens_exemplo": sorted(itens_de[k])[:5]})
    return out


def ranking_orgaos(db_path: str | None = None, min_itens: int = 8, limite: int = 60) -> dict:
    """Órgãos por eficiência de gasto: razão mediana preço/mercado ao longo de muitos itens.
    <1 = compra abaixo do mercado (gasta bem); >1 = paga acima (auditar)."""
    con = _ro(db_path)
    try:
        r = _eficiencia(con, "orgao", min_itens)
        r.sort(key=lambda x: x["razao_mediana"])
        return {"ok": True, "melhores": r[:limite], "piores": list(reversed(r))[:limite],
                "n": len(r),
                "explicacao": ("Para cada órgão, a razão mediana entre o que ele paga e a mediana de "
                               "mercado do item, ao longo de ≥8 itens comparáveis. <1 = gasta melhor "
                               "que o mercado; >1 = paga acima (candidato a auditoria de preços)."),
                "ressalva": RESSALVA}
    finally:
        con.close()


def ranking_fornecedores(db_path: str | None = None, min_itens: int = 8, limite: int = 60) -> dict:
    """Fornecedores por preço relativo: razão mediana preço/mercado ao longo de muitos itens.
    >1 = cobra acima do mercado (caro); <1 = abaixo (barato)."""
    con = _ro(db_path)
    try:
        r = _eficiencia(con, "fornecedor", min_itens)
        r.sort(key=lambda x: -x["razao_mediana"])
        return {"ok": True, "mais_caros": r[:limite], "mais_baratos": list(reversed(r))[:limite],
                "n": len(r),
                "explicacao": ("Para cada fornecedor, a razão mediana entre o que ele cobra e a "
                               "mediana de mercado do item, ao longo de ≥8 itens. >1 = cobra acima "
                               "do mercado; <1 = abaixo."),
                "ressalva": RESSALVA}
    finally:
        con.close()


def economia_potencial(db_path: str | None = None, min_orgaos: int = 3, min_amostra: int = 5,
                       min_certames: int = 3, teto_razao: float = 10.0, limite: int = 60) -> dict:
    """QUANTO os cofres públicos economizariam se cada compra acima da mediana tivesse pago a
    MEDIANA de mercado do item. Economia = Σ (preço_pago − mediana) × quantidade, sobre as compras
    com preço > mediana, em grupos comparáveis. Quebra por ITEM, ÓRGÃO e FORNECEDOR.

    Honestidade: é um teto teórico (a mediana é atingível — metade já paga abaixo). Robusto a
    outlier (mediana como referência); razões acima de `teto_razao`× a mediana são CAPADAS no teto
    (a descrição do PNCP mistura especificação — sem o cap, 1 artefato de 500× dominaria o total).
    Artefato (<10% da mediana) descartado. Só compras com quantidade real entram."""
    con = _ro(db_path)
    try:
        total = 0.0
        por_item: dict[str, dict] = {}
        por_orgao: dict[str, dict] = {}
        por_forn: dict[str, dict] = {}
        n_compras_caras = 0
        for (base, un), itens in _grupos(con).items():
            orgaos = {r["unidade_nome"] or r["orgao_nome"] for r in itens}
            n_cert = len({r["certame"] for r in itens})
            # amostra E diversidade suficientes → a mediana é confiável e um único item genérico
            # de alto valor ('Sistema para compressão' com 1 compra) não domina a economia.
            if len(itens) < min_amostra or len(orgaos) < min_orgaos or n_cert < min_certames:
                continue
            precos = sorted(r["vu"] for r in itens)
            med = _mediana(precos)
            if med <= 0:
                continue
            # a mediana só vale se o grupo é homogêneo: ≥60% dos certames perto dela (mesma
            # guarda do sobrepreço) — senão são produtos diferentes sob rótulo genérico.
            n_perto = len({r["certame"] for r in itens if r["vu"] <= 2 * med})
            if n_perto < 0.6 * n_cert:
                continue
            piso = 0.10 * med
            teto = teto_razao * med                    # cap anti-artefato: preço efetivo p/ economia
            for r in itens:
                p = r["vu"]
                if p < piso or p <= med:
                    continue
                p_ef = min(p, teto)
                qtd = r["quantidade"] if ("quantidade" in r.keys() and r["quantidade"]) else 1
                excesso = (p_ef - med) * qtd
                if excesso <= 0:
                    continue
                total += excesso
                n_compras_caras += 1
                org = r["unidade_nome"] or r["orgao_nome"] or "—"
                it = por_item.setdefault(base, {"item": r["d"], "unidade_medida": r["un"],
                                                "economia": 0.0, "n": 0})
                it["economia"] += excesso
                it["n"] += 1
                og = por_orgao.setdefault(org, {"orgao": org, "economia": 0.0, "n": 0})
                og["economia"] += excesso
                og["n"] += 1
                fk = r["fornecedor_cnpj"]
                fo = por_forn.setdefault(fk, {"fornecedor": r["fornecedor_nome"],
                                              "fornecedor_cnpj": fk, "economia": 0.0, "n": 0})
                fo["economia"] += excesso
                fo["n"] += 1

        def _top(d):
            xs = sorted(d.values(), key=lambda x: -x["economia"])
            for x in xs:
                x["economia"] = round(x["economia"], 2)
            return xs[:limite]

        return {"ok": True, "economia_total": round(total, 2),
                "n_compras_acima_mediana": n_compras_caras,
                "por_item": _top(por_item), "por_orgao": _top(por_orgao),
                "por_fornecedor": _top(por_forn),
                "explicacao": ("Economia potencial = quanto o poder público deixaria de gastar se "
                               "cada compra acima da mediana tivesse pago a MEDIANA de mercado do "
                               "item (por unidade × quantidade). Referência conservadora — metade "
                               "das compras já paga abaixo dela."),
                "ressalva": ("Teto teórico. Preços acima de "
                             f"{teto_razao:g}× a mediana são capados (a descrição do PNCP mistura "
                             "especificação; sem o cap um artefato dominaria). Confirmar termo de "
                             "referência. É priorização de auditoria, não valor a ressarcir. Indício ≠ acusação.")}
    finally:
        con.close()


_ESFERA_PNCP = {"E": "estadual", "F": "federal", "M": "municipal", "N": "federal"}


def economia_vedada(db_path: str | None = None, min_orgaos: int = 3, min_amostra: int = 5,
                    min_certames: int = 3, teto_razao: float = 10.0, limite: int = 60) -> dict:
    """O número mais forte: sobrepreço (economia acima da mediana) pago a fornecedor que estava
    JURIDICAMENTE VEDADO de contratar com AQUELE ente comprador, À ÉPOCA da compra.

    Rigor: (a) a sanção precisa VEDAR o ente do órgão comprador (inidoneidade veda todos; impedimento/
    suspensão só se a esfera/UF do sancionador coincide — via sancao_abrangencia.veda_ente); (b) a
    sanção precisa estar VIGENTE na data da compra (teste à época); (c) só compras acima da mediana
    em grupos comparáveis (mesma robustez da economia_potencial). Esfera do comprador vem do
    pncp_ente (oficial). Separa 'total' (inidoneidade, alcance certo) de 'ente' (impedimento)."""
    from compliance_agent.sancao_abrangencia import classificar_sancao, veda_ente
    con = _ro(db_path)
    try:
        # sanções que vedam (algum ente) por CNPJ, com vigência
        sanc: dict[str, list] = {}
        for r in con.execute(
                "SELECT cpf_cnpj, categoria, fundamentacao, cadastro, orgao, uf, data_inicio, "
                "data_fim FROM sancoes_federais WHERE length(cpf_cnpj)=14"):
            cl = classificar_sancao(r["categoria"], r["fundamentacao"], r["cadastro"])
            if cl["veda_contratacao"]:
                sanc.setdefault(r["cpf_cnpj"], []).append(dict(r))
        # esfera OFICIAL do comprador (pncp_ente) por orgao_cnpj
        try:
            esfera = {r["cnpj"]: _ESFERA_PNCP.get(r["esfera_id"]) for r in
                      con.execute("SELECT cnpj, esfera_id FROM pncp_ente")}
        except sqlite3.OperationalError:
            esfera = {}

        rows = con.execute(
            "SELECT item_descricao d, unidade_medida un, valor_unitario vu, quantidade, "
            "orgao_cnpj, orgao_nome, unidade_nome, uf, fornecedor_nome, fornecedor_cnpj, "
            "certame, data_pub FROM pncp_resultado WHERE ordem_classificacao=1 AND valor_unitario>0 "
            "AND quantidade>=2 AND item_descricao IS NOT NULL AND length(item_descricao)>=4").fetchall()
        from collections import defaultdict
        grupos: dict[tuple, list] = defaultdict(list)
        for r in rows:
            b = _norm_item(r["d"])
            if b:
                grupos[(b, _un(r["un"]))].append(r)

        total = 0.0
        por_forn: dict[str, dict] = {}
        por_abr = {"total": 0.0, "ente": 0.0, "orgao": 0.0}
        n_compras = 0
        for (base, un), itens in grupos.items():
            orgaos = {r["unidade_nome"] or r["orgao_nome"] for r in itens}
            n_cert = len({r["certame"] for r in itens})
            if len(itens) < min_amostra or len(orgaos) < min_orgaos or n_cert < min_certames:
                continue
            precos = sorted(r["vu"] for r in itens)
            med = _mediana(precos)
            if med <= 0:
                continue
            n_perto = len({r["certame"] for r in itens if r["vu"] <= 2 * med})
            if n_perto < 0.6 * n_cert:
                continue
            piso, teto = 0.10 * med, teto_razao * med
            for r in itens:
                p = r["vu"]
                if p < piso or p <= med:
                    continue
                cnpj = r["fornecedor_cnpj"]
                if cnpj not in sanc:
                    continue
                data = (r["data_pub"] or "")[:10]
                esfera_alvo = esfera.get(r["orgao_cnpj"]) or "estadual"
                uf_alvo = (r["uf"] or "RJ").upper()
                # a sanção mais forte que VEDA este comprador E está vigente na data
                melhor = None
                for s in sanc[cnpj]:
                    ini, fim = s.get("data_inicio") or "0000", s.get("data_fim") or "9999"
                    if data and not (ini <= data <= fim):
                        continue                       # não vigente à época
                    v = veda_ente(s, esfera_alvo, uf_alvo)
                    if v["veda"]:
                        rank = {"total": 3, "ente": 2, "orgao": 1}
                        if melhor is None or rank[v["abrangencia"]] > rank[melhor["abrangencia"]]:
                            melhor = v
                if not melhor:
                    continue                           # sancionado, mas não vedava ESTE comprador à época
                qtd = r["quantidade"] or 1
                excesso = (min(p, teto) - med) * qtd
                if excesso <= 0:
                    continue
                total += excesso
                por_abr[melhor["abrangencia"]] += excesso
                n_compras += 1
                fo = por_forn.setdefault(cnpj, {
                    "fornecedor": r["fornecedor_nome"], "fornecedor_cnpj": cnpj,
                    "economia_vedada": 0.0, "n": 0, "abrangencia": melhor["abrangencia"],
                    "exemplos": []})
                fo["economia_vedada"] += excesso
                fo["n"] += 1
                rank = {"total": 3, "ente": 2, "orgao": 1}
                if rank[melhor["abrangencia"]] > rank[fo["abrangencia"]]:
                    fo["abrangencia"] = melhor["abrangencia"]
                if len(fo["exemplos"]) < 5:
                    fo["exemplos"].append({
                        "item": r["d"], "orgao": r["unidade_nome"] or r["orgao_nome"],
                        "preco": round(p, 2), "mediana": round(med, 2),
                        "data": data, "veda": melhor["motivo"]})

        forn = sorted(por_forn.values(), key=lambda x: -x["economia_vedada"])
        for f in forn:
            f["economia_vedada"] = round(f["economia_vedada"], 2)
        return {"ok": True, "economia_vedada_total": round(total, 2), "n_compras": n_compras,
                "por_abrangencia": {k: round(v, 2) for k, v in por_abr.items()},
                "por_fornecedor": forn[:limite], "n_fornecedores": len(forn),
                "explicacao": ("Sobrepreço (valor acima da mediana de mercado) pago a fornecedor que "
                               "estava juridicamente VEDADO de contratar com aquele ente comprador, "
                               "VIGENTE à época da compra. Inidoneidade veda qualquer ente; "
                               "impedimento/suspensão só o ente/órgão sancionador. É o dinheiro pago "
                               "caro a quem não podia sequer contratar — o alvo mais forte."),
                "ressalva": ("Vedação e sobrepreço vêm de fontes independentes; confirmar a vigência "
                             "e o alcance no cadastro-fonte (CGU) e o termo de referência antes de uso "
                             "externo. Suspensão (art. 87 III) tem divergência jurisprudencial. Indício ≠ acusação.")}
    finally:
        con.close()


def caro_e_suspeito(db_path: str | None = None, fator: float = 3.0, min_orgaos: int = 2,
                    min_certames: int = 3, limite: int = 120) -> dict:
    """DOSSIÊ AUTOMÁTICO: item comprado MUITO acima da mediana (≥`fator`×) por um órgão, cujo
    fornecedor vencedor É SUSPEITO por outra fonte independente — sancionado (CEIS/CNEP), no radar
    de risco, ou fantasma. É o cruzamento 'paga caro + fornecedor com problema': prioriza o que
    tem preço fora da curva E fornecedor já marcado, o alvo mais forte para auditoria.

    Guarda anti-FP: grupo comparável (≥`min_orgaos` órgãos, ≥`min_certames` certames); preço do
    achado ≥`fator`× a mediana E ≥ mediana+3·MAD (fora da banda robusta); artefato (<10% da
    mediana) descartado. O 'suspeito' vem de fonte INDEPENDENTE do preço."""
    from compliance_agent.sancao_abrangencia import classificar_sancao
    con = _ro(db_path)
    try:
        # sanção → maior abrangência por CNPJ (total > ente > órgão) para exibir o alcance
        sanc: dict[str, str] = {}
        _ordem = {"total": 3, "ente": 2, "orgao": 1, "nenhuma": 0}
        for r in con.execute(
                "SELECT cpf_cnpj, categoria, fundamentacao, cadastro FROM sancoes_federais "
                "WHERE length(cpf_cnpj)=14"):
            cl = classificar_sancao(r["categoria"], r["fundamentacao"], r["cadastro"])
            if not cl["veda_contratacao"]:
                continue
            atual = sanc.get(r["cpf_cnpj"])
            if atual is None or _ordem[cl["abrangencia"]] > _ordem[atual]:
                sanc[r["cpf_cnpj"]] = cl["abrangencia"]
        try:
            fant = {r["cnpj"]: r["classificacao"] for r in con.execute(
                "SELECT cnpj, classificacao FROM fantasma_score WHERE classificacao IN ('alto','medio')")}
        except sqlite3.OperationalError:
            fant = {}
        try:
            from compliance_agent.cruzamentos_intel import ler_cache_intel
            radar = {a["cnpj"]: a["score"] for a in
                     (ler_cache_intel("radar_risco") or {}).get("achados") or [] if a.get("cnpj")}
        except Exception:  # noqa: BLE001
            radar = {}

        achados = []
        for (base, un), itens in _grupos(con).items():
            orgaos = {r["unidade_nome"] or r["orgao_nome"] for r in itens}
            n_cert = len({r["certame"] for r in itens})
            if len(orgaos) < min_orgaos or n_cert < min_certames:
                continue
            precos = sorted(r["vu"] for r in itens)
            med = _mediana(precos)
            if med <= 0:
                continue
            mad = _mediana([abs(p - med) for p in precos]) or (med * 0.1)
            for r in itens:
                p = r["vu"]
                if p < fator * med or (p - med) < 3 * 1.4826 * mad:
                    continue                      # não está caro o bastante / dentro da banda
                cnpj = r["fornecedor_cnpj"]
                sinais = []
                if cnpj in sanc:
                    sinais.append({"sinal": "sancionada", "peso": 3,
                                   "abrangencia": sanc.get(cnpj)})
                if cnpj in radar:
                    sinais.append({"sinal": f"radar_{radar[cnpj]}", "peso": 2})
                if cnpj in fant:
                    sinais.append({"sinal": f"fantasma_{fant[cnpj]}", "peso": 2})
                if not sinais:
                    continue                      # caro MAS sem outro sinal → fica no sobrepreço, não aqui
                achados.append({
                    "item": r["d"], "grupo": base, "unidade_medida": r["un"],
                    "orgao": r["unidade_nome"] or r["orgao_nome"], "municipio": r["municipio"] if "municipio" in r.keys() else None,
                    "fornecedor": r["fornecedor_nome"], "fornecedor_cnpj": cnpj,
                    "preco": round(p, 2), "mediana": round(med, 2),
                    "vs_mediana": round(p / med, 1), "sobrepreco_est": round(p - med, 2),
                    "certame": r["certame"], "data": (r["data_pub"] or "")[:10],
                    "sinais": sinais, "gravidade": sum(s["peso"] for s in sinais)})
        # ranking: mais sinais/sanção primeiro, depois quão acima da mediana
        achados.sort(key=lambda a: (-a["gravidade"], -a["vs_mediana"]))
        return {"ok": True, "achados": achados[:limite], "n": len(achados),
                "n_sancionada": sum(1 for a in achados
                                    if any(s["sinal"] == "sancionada" for s in a["sinais"])),
                "explicacao": ("Cruzamento do comparador de preços com o gabarito de risco: item pago "
                               f"≥{fator:g}× a mediana de mercado por um órgão, cujo FORNECEDOR já é "
                               "sancionado (CEIS/CNEP), está no radar de risco ou é fantasma. Preço "
                               "fora da curva + fornecedor marcado por fonte independente = alvo forte."),
                "ressalva": ("O preço alto e o sinal de risco vêm de FONTES INDEPENDENTES — a "
                             "coincidência é o indício, não prova. Descrição do PNCP é curta (pode "
                             "misturar especificação). Confirmar termo de referência. Indício ≠ acusação.")}
    finally:
        con.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "orgaos"
    if cmd == "buscar":
        d = buscar_grupos(" ".join(sys.argv[2:]) or "locacao veiculo")
        print(f"{d['n']} grupos p/ '{d['termo']}':")
        for g in d["grupos"][:15]:
            print(f"  {g['dispersao']:6}x '{g['exemplo'][:34]:34}' {g['n_orgaos']}órgãos "
                  f"med R${g['mediana']:.2f} (R${g['min']:.2f}–R${g['max']:.2f})")
    elif cmd == "comparar":
        d = comparar(sys.argv[2])
        if d.get("ok"):
            print(f"{d['exemplo']} | mediana geral R${d['mediana_geral']:.2f} | {d['n_orgaos']} órgãos")
            print(" ÓRGÃOS (mais caro → mais barato):")
            for o in d["orgaos"][:12]:
                print(f"   {o['vs_geral']:5}x  R${o['mediana']:>10.2f}  {(o['nome'] or '')[:44]} (n={o['n']})")
    elif cmd == "vedada":
        d = economia_vedada()
        print(f"ECONOMIA PAGA A FORNECEDOR VEDADO: R${d['economia_vedada_total']:,.2f}  "
              f"({d['n_compras']} compras) | por abrangência: {d['por_abrangencia']}")
        for f in d["por_fornecedor"][:12]:
            print(f"   R${f['economia_vedada']:>12,.2f}  [{f['abrangencia']}]  "
                  f"{(f['fornecedor'] or '')[:40]:40} (n={f['n']})")
    elif cmd == "economia":
        d = economia_potencial()
        print(f"ECONOMIA POTENCIAL: R${d['economia_total']:,.2f}  "
              f"({d['n_compras_acima_mediana']} compras acima da mediana)")
        print(" TOP itens:")
        for x in d["por_item"][:8]:
            print(f"   R${x['economia']:>14,.2f}  {(x['item'] or '')[:36]:36} (n={x['n']})")
        print(" TOP órgãos:")
        for x in d["por_orgao"][:8]:
            print(f"   R${x['economia']:>14,.2f}  {(x['orgao'] or '')[:44]:44} (n={x['n']})")
    elif cmd == "dossie":
        d = caro_e_suspeito()
        print(f"{d['n']} casos 'paga caro + fornecedor suspeito' ({d['n_sancionada']} c/ sanção):")
        for a in d["achados"][:15]:
            ss = ",".join(s["sinal"] for s in a["sinais"])
            print(f"  {a['vs_mediana']:5}x med  R${a['preco']:>10.2f}  {(a['item'] or '')[:24]:24} "
                  f"{(a['fornecedor'] or '')[:24]:24} [{ss}] @ {(a['orgao'] or '')[:22]}")
    elif cmd == "fornecedores":
        d = ranking_fornecedores()
        print(f"{d['n']} fornecedores. MAIS CAROS:")
        for f in d["mais_caros"][:12]:
            print(f"   {f['razao_mediana']:5}x  {(f['nome'] or '')[:40]:40} ({f['n_itens']} itens)")
    else:
        d = ranking_orgaos()
        print(f"{d['n']} órgãos. MELHORES (gastam abaixo do mercado):")
        for o in d["melhores"][:10]:
            print(f"   {o['razao_mediana']:5}x  {(o['nome'] or '')[:44]:44} ({o['n_itens']} itens)")
        print(" PIORES (pagam acima do mercado):")
        for o in d["piores"][:10]:
            print(f"   {o['razao_mediana']:5}x  {(o['nome'] or '')[:44]:44} ({o['n_itens']} itens)")
