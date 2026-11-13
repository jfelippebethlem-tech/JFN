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
from compliance_agent.reporting.intel_base import moeda

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


def _linhas(con, certs: set | None = None):
    rows = con.execute(
        "SELECT item_descricao d, unidade_medida un, valor_unitario vu, quantidade, orgao_nome, "
        "unidade_nome, fornecedor_nome, fornecedor_cnpj, certame, data_pub "
        "FROM pncp_resultado WHERE ordem_classificacao=1 AND valor_unitario>0 AND quantidade>=2 "
        "AND item_descricao IS NOT NULL AND length(item_descricao)>=4").fetchall()
    return rows if certs is None else [r for r in rows if r["certame"] in certs]


def _certs(con, esfera: str | None) -> set | None:
    """Filtro canônico de esfera (aba Estado = 'estado', Prefeitura = 'prefeitura')."""
    from compliance_agent.collectors.pncp_resultados import certames_da_esfera
    return certames_da_esfera(con, esfera)


# Os dois entes que o gabinete fiscaliza. É o alvo PADRÃO do sobrepreço: sem escolher
# aba, o achado não deve listar órgão federal nem de outro município (a MEDIANA segue
# global — mercado; só o ACHADO é restrito). Pedido do dono 2026-07-24.
_ESFERAS_FISCALIZADAS = ("estado", "prefeitura")


def _certs_alvo(con, esfera: str | None) -> set | None:
    """Certames do ACHADO de sobrepreço. 'todas' → None (tudo, quem pedir explicitamente);
    esfera específica → só ela (aba); vazio/None → união {estado, prefeitura}."""
    if esfera == "todas":
        return None
    if esfera:
        return _certs(con, esfera)
    from compliance_agent.collectors.pncp_resultados import certames_das_esferas
    return certames_das_esferas(con, set(_ESFERAS_FISCALIZADAS))


def _grupos(con, certs: set | None = None, por_medida: bool = False) -> dict:
    """Agrupa compras comparáveis. `por_medida=True` refina a chave com a assinatura de
    tamanho/embalagem (medida_item) e a unidade canônica — só os DETECTORES DE ALERTA usam,
    para não comparar fardo com copinho (chave de 3: base, unidade_canon, sig). A navegação
    (catálogo/comparar) mantém a chave de 2 (base, unidade), sem fragmentar a exploração."""
    g: dict[tuple, list] = defaultdict(list)
    for r in _linhas(con, certs):
        base = _norm_item(r["d"])
        if not base:
            continue
        if por_medida:
            from compliance_agent.medida_item import assinatura_medida, un_canon
            sig = assinatura_medida(r["d"], r["un"])["sig"]
            g[(base, un_canon(r["un"]), sig)].append(r)
        else:
            g[(base, _un(r["un"]))].append(r)
    return g


# ── comparação HOMOGÊNEA (base única do sobrepreço, da economia e do caro+suspeito) ──────
# Pedido do dono (2026-11-13): "não pode comparar itens de unidades métricas diferentes [...]
# não pode ter margem pra erro em nada". Regras em compliance_agent/preco_normalizado.py.

_COLS_RICAS = ("item_descricao d", "unidade_medida un", "valor_unitario vu", "quantidade",
               "orgao_cnpj", "orgao_nome", "unidade_nome", "uf", "municipio", "fornecedor_nome",
               "fornecedor_cnpj", "certame", "item", "data_pub", "modalidade", "objeto")

# preço que não é de MERCADO: não serve de referência nem de achado
_OBJ_FORA_DE_MERCADO = re.compile(
    r"agricultura familiar|chamada publica|\bpnae\b|homologad\w* pelo fabricante|genuin|"
    r"originais? (?:do|de) fabrica|exclusiv\w* d[ao] marca|comodato")
_MODALIDADE_INEXIGIBILIDADE = 9   # código PNCP


def _linhas_ricas(con) -> list[dict]:
    cols = {r[1] for r in con.execute("PRAGMA table_info(pncp_resultado)")}
    sel = ", ".join(c if c.split()[0] in cols else f"NULL {c.split()[-1]}" for c in _COLS_RICAS)
    return [dict(r) for r in con.execute(
        f"SELECT {sel} FROM pncp_resultado WHERE ordem_classificacao=1 AND valor_unitario>0 "
        "AND quantidade>=2 AND item_descricao IS NOT NULL AND length(item_descricao)>=3")]


def fora_de_mercado(r: dict) -> str | None:
    """Motivo pelo qual o preço desta compra não é preço de mercado comparável (ou None)."""
    if r.get("modalidade") == _MODALIDADE_INEXIGIBILIDADE:
        return ("inexigibilidade: preço sem disputa (fornecedor exclusivo, chamada pública) — "
                "não é referência de mercado nem se compara com ela")
    from compliance_agent.medida_item import _norm as _n
    m = _OBJ_FORA_DE_MERCADO.search(_n(r.get("objeto") or ""))
    if m:
        return (f"objeto com condição que muda o preço (agricultura familiar, marca exigida, "
                f"comodato) ('{m.group(0)}') — não se compara com o item genérico")
    return None


def comparacao_homogenea(con, min_amostra: int = 5, min_certames: int = 4,
                         min_orgaos: int = 3) -> dict:
    """Todas as compras do PNCP → grupos homogêneos (preço normalizado) + INDETERMINADOS.
    A mediana é GLOBAL (mercado); quem filtra esfera é o chamador, no ACHADO.

    Memo de 10 min por (banco, parâmetros): a aba Estado, a Prefeitura, a economia e o
    caro+suspeito pedem a MESMA base — sob carga cada passada custa minutos. Só leitura."""
    import time
    try:
        db_id = con.execute("PRAGMA database_list").fetchone()[2]
    except Exception:  # noqa: BLE001 — sem identificação do banco, não memoriza
        db_id = None
    chave = (db_id, min_amostra, min_certames, min_orgaos)
    hit = _MEMO_COMP.get(chave) if db_id else None
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    g = _comparacao_homogenea(con, min_amostra, min_certames, min_orgaos)
    if db_id:
        if len(_MEMO_COMP) >= 4:
            _MEMO_COMP.clear()
        _MEMO_COMP[chave] = (time.time(), g)
    return g


_MEMO_COMP: dict = {}


def _comparacao_homogenea(con, min_amostra: int, min_certames: int, min_orgaos: int) -> dict:
    from compliance_agent.preco_normalizado import agrupar
    ok, fora = [], []
    for r in _linhas_ricas(con):
        m = fora_de_mercado(r)
        (fora.append((r, m)) if m else ok.append(r))
    g = agrupar(ok, _norm_item, min_amostra=min_amostra, min_certames=min_certames,
                min_orgaos=min_orgaos)
    g["indeterminados"] = fora + g["indeterminados"]
    return g


def achados_do_grupo(grp: dict, fator: float = 2.0, z_min: float = 3.5):
    """(registro, z) das compras do grupo HOMOGÊNEO com preço normalizado ≥ fator×mediana E
    fora da banda robusta (z de Iglewicz–Hoaglin ≥ z_min)."""
    med = grp["mediana"]
    if med <= 0:
        return
    from compliance_agent.preco_normalizado import mediana
    mad = mediana([abs(r["pn"] - med) for r in grp["itens"]]) or (med * 0.1)
    for r in grp["itens"]:
        z = (r["pn"] - med) / (1.4826 * mad)
        if r["pn"] >= fator * med and z >= z_min:
            yield r, z


def resumo_grupo(grp: dict, n_amostra: int = 12) -> dict:
    """O GRUPO DE COMPARAÇÃO como se mostra ao lado de cada achado."""
    from compliance_agent.verificacao_pncp import link_pncp
    return {
        "descricao_normalizada": grp["desc"], "unidade_normalizada": grp["rotulo"],
        "n": grp["n"], "n_certames": grp["n_certames"], "n_orgaos": grp.get("n_orgaos"),
        "mediana": round(grp["mediana"], 4), "min": round(grp["min"], 4),
        "max": round(grp["max"], 4), "p10": round(grp["p10"], 4), "p90": round(grp["p90"], 4),
        "dispersao_p90_p10": round(grp["dispersao"], 2), "faixa": grp["faixa"],
        "n_faixas": grp["n_faixas"],
        "amostra": [{"preco_normalizado": round(r["pn"], 4), "unidade_medida": r["un"],
                     "orgao": r.get("unidade_nome") or r.get("orgao_nome"),
                     "data": (r.get("data_pub") or "")[:10], "link_pncp": link_pncp(r["certame"])}
                    for r in grp["itens"][:: max(1, len(grp["itens"]) // n_amostra)][:n_amostra]]}


def resumo_indeterminados(indet: list, certs: set | None, n_lista: int = 40) -> dict:
    """Contagem por motivo (só da esfera do achado) + as discrepâncias de SALTO, listadas à parte."""
    from compliance_agent.verificacao_pncp import link_pncp
    por_motivo: dict[str, int] = defaultdict(int)
    saltos = []
    for r, motivo in indet:
        if certs is not None and r["certame"] not in certs:
            continue
        chave = re.sub(r"'[^']*'", "'…'", motivo)
        chave = re.sub(r"R\$ [\d.,]+|[\d.,]+×|\(\d+ compra\(s\)\)", "…", chave)
        por_motivo[chave] += 1
        if "salto" in motivo:
            saltos.append({"item": r["d"], "unidade_medida": r["un"], "preco": r["vu"],
                           "orgao": r.get("unidade_nome") or r.get("orgao_nome"),
                           "fornecedor": r.get("fornecedor_nome"), "motivo": motivo,
                           "certame": r["certame"], "item_n": r.get("item"),
                           "link_pncp": link_pncp(r["certame"])})
    saltos.sort(key=lambda x: -(x["preco"] or 0))
    return {"n": sum(por_motivo.values()),
            "por_motivo": sorted(({"motivo": k, "n": v} for k, v in por_motivo.items()),
                                 key=lambda x: -x["n"]),
            "discrepancias_de_salto": saltos[:n_lista], "n_discrepancias_de_salto": len(saltos)}


def _norm_ente(nome: str | None) -> str:
    """'MRJ-PREFEITURA MUNICIPAL DO RIO DE JANEIRO' e '... DO RIO DE JANEIRO - RJ' = o mesmo ente."""
    from compliance_agent.medida_item import _norm as _n
    s = _n(nome or "—").upper()
    s = re.sub(r"^MRJ\s*-\s*", "", s)
    s = re.sub(r"\s*[-/]\s*RJ$", "", s)
    return re.sub(r"\s+", " ", s).strip() or "—"


def buscar_grupos(termo: str, db_path: str | None = None, min_compras: int = 3,
                  min_orgaos: int = 2, limite: int = 40, esfera: str | None = None) -> dict:
    """Grupos de item cuja descrição normalizada casa TODAS as palavras do termo, com estatística
    de preço. Ex.: 'aluguel carro' → grupos de locação de veículo comparáveis entre órgãos."""
    toks = [t for t in _norm_item(termo).split() if t] or [t for t in re.sub(r"[^a-z ]", " ",
            (termo or "").lower()).split() if len(t) >= 3]
    con = _ro(db_path)
    try:
        achados = []
        for (base, un), itens in _grupos(con, _certs(con, esfera)).items():
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
        parecidos = []
        if not achados and len(toks) >= 1:
            # nada casa TODAS as palavras → sugere grupos que casam QUALQUER uma (o usuário
            # não deve adivinhar o vocabulário da base; 'refeição' devolvia 0 e ponto final)
            for (base, un), itens in _grupos(con, _certs(con, esfera)).items():
                if not any(t in base for t in toks):
                    continue
                orgaos = {r["unidade_nome"] or r["orgao_nome"] for r in itens}
                if len(itens) < min_compras or len(orgaos) < min_orgaos:
                    continue
                precos = sorted(r["vu"] for r in itens)
                parecidos.append({"grupo": base, "unidade_medida": itens[0]["un"],
                                  "exemplo": itens[0]["d"], "n_compras": len(itens),
                                  "n_orgaos": len(orgaos),
                                  "mediana": round(_mediana(precos), 2),
                                  "min": round(precos[0], 2), "max": round(precos[-1], 2),
                                  "dispersao": round(precos[-1] / precos[0], 1)
                                  if precos[0] > 0 else None})
            parecidos.sort(key=lambda a: -(a["dispersao"] or 0))
            parecidos = parecidos[:10]
        return {"ok": True, "termo": termo, "grupos": achados[:limite], "n": len(achados),
                "parecidos": parecidos,
                "explicacao": ("Grupos de item comprados por ≥2 órgãos que casam o termo. Dispersão "
                               "alta = os órgãos pagam preços MUITO diferentes pelo mesmo item — "
                               "abra o grupo para ver quem paga mais/menos."),
                "ressalva": RESSALVA}
    finally:
        con.close()


# ── catálogo navegável: menu de categorias → submenu de itens (grupos comparáveis) ──
# Ordem importa: a PRIMEIRA categoria cujo token aparece no grupo vence (saúde antes de
# limpeza p/ "luva cirúrgica"; veículos antes de serviços p/ "locação de veículo").
_CATALOGO_CATS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("saude", "Saúde e hospitalar", "🩺",
     ("medicamento", "cirurgic", "hospitalar", "seringa", "agulha", "luva", "curativo", "gaze",
      "soro", "sonda", "cateter", "mascara", "ampola", "comprimido", "injetavel", "odontologic",
      "reagente", "laboratorio", "raio", "ultrassom", "estetoscopio", "gastrostomia", "cardiaca",
      "neonatal", "ambulancia", "enfermagem", "clinic", "vacina", "diagnostic")),
    ("alimentacao", "Alimentação", "🍽️",
     ("refeicao", "alimento", "alimenticio", "cesta", "cafe", "acucar", "leite", "carne", "arroz",
      "feijao", "pao", "merenda", "lanche", "achocolatado", "biscoito", "bebida", "agua mineral",
      "coffee", "buffet", "marmitex", "hortifruti")),
    ("veiculos", "Veículos e transporte", "🚗",
     ("veiculo", "veicular", "carro", "pneu", "combustivel", "gasolina", "diesel", "etanol",
      "onibus", "caminhao", "motocicleta", "automotiv", "transporte", "fretamento", "passagem")),
    ("ti", "Tecnologia e informática", "💻",
     ("computador", "notebook", "monitor", "impressora", "toner", "cartucho", "servidor",
      "software", "licenca", "tablet", "scanner", "informatica", "rede", "switch", "roteador",
      "nobreak", "hd", "ssd", "disco", "memoria", "processador", "teclado", "mouse", "projetor")),
    ("limpeza", "Limpeza e higiene", "🧴",
     ("limpeza", "detergente", "sabao", "sabonete", "desinfetante", "sanitaria", "alvejante",
      "higiene", "papel higienico", "lixo", "vassoura", "rodo", "esponja", "alcool")),
    ("escritorio", "Escritório e papelaria", "📎",
     ("papel", "caneta", "lapis", "envelope", "grampeador", "pasta", "resma", "etiqueta",
      "caderno", "expediente", "arquivo", "clips", "pincel", "quadro")),
    ("mobiliario", "Mobiliário", "🪑",
     ("armario", "cadeira", "mesa", "estante", "poltrona", "arquivo aco", "gaveteiro",
      "longarina", "sofa", "mobiliario", "beliche", "colchao")),
    ("vestuario", "Vestuário e EPI", "🦺",
     ("camisa", "camiseta", "uniforme", "farda", "bota", "calcado", "capacete", "colete",
      "epi", "protecao", "avental", "jaleco", "toca", "bone", "calca", "tecido")),
    ("obras", "Obras e manutenção predial", "🧱",
     ("cimento", "tinta", "eletric", "hidraulic", "madeira", "telha", "areia", "brita",
      "argamassa", "tubo pvc", "lampada", "luminaria", "cabo", "disjuntor", "fechadura",
      "vidro", "porta", "janela", "predial", "reforma", "alvenaria")),
    ("servicos", "Serviços", "🛠️",
     ("servico", "locacao", "manutencao", "vigilancia", "seguranca", "evento", "consultoria",
      "assessoria", "impressao", "publicacao", "seguro", "limpeza predial", "capacitacao",
      "treinamento", "hospedagem", "engenharia")),
]


def catalogo(db_path: str | None = None, esfera: str | None = None,
             min_compras: int = 3, min_orgaos: int = 2) -> dict:
    """Catálogo navegável do comparador: TODOS os grupos comparáveis (≥min_compras compras,
    ≥min_orgaos órgãos), organizados em categorias determinísticas (menu → submenu → item).
    Nasceu do achado 2026-07-21: a busca por termo exigia adivinhar a palavra certa da
    descrição normalizada — 'refeição' (exemplo do próprio placeholder) devolvia 0. Aqui o
    usuário NAVEGA pelo que existe, em vez de adivinhar. Filtros/ordenação ficam no cliente."""
    con = _ro(db_path)
    try:
        grupos_raw = _grupos(con, _certs(con, esfera))
    finally:
        con.close()
    cats: dict[str, list] = {c[0]: [] for c in _CATALOGO_CATS}
    cats["outros"] = []
    for (base, _un_k), itens in grupos_raw.items():
        orgaos = {r["unidade_nome"] or r["orgao_nome"] for r in itens}
        if len(itens) < min_compras or len(orgaos) < min_orgaos:
            continue
        precos = sorted(r["vu"] for r in itens)
        med = _mediana(precos)
        g = {"grupo": base, "unidade_medida": itens[0]["un"], "exemplo": itens[0]["d"],
             "n_compras": len(itens), "n_orgaos": len(orgaos), "mediana": round(med, 2),
             "min": round(precos[0], 2), "max": round(precos[-1], 2),
             "dispersao": round(precos[-1] / precos[0], 1) if precos[0] > 0 else None}
        alvo = "outros"
        for cid, _rot, _ic, toks in _CATALOGO_CATS:
            if any(t in base for t in toks):
                alvo = cid
                break
        cats[alvo].append(g)
    categorias = []
    for cid, rot, ic, _toks in _CATALOGO_CATS + [("outros", "Outros itens", "📦", ())]:
        gs = sorted(cats[cid], key=lambda g: -(g["dispersao"] or 0))
        if gs:
            categorias.append({"id": cid, "rotulo": rot, "icone": ic, "n": len(gs), "grupos": gs})
    return {"ok": True, "categorias": categorias,
            "n_grupos": sum(c["n"] for c in categorias),
            "explicacao": ("Todos os itens com preço comparável (comprados ≥%d vezes por ≥%d órgãos),"
                           " por categoria. Dispersão = maior preço ÷ menor preço do MESMO item — "
                           "quanto maior, mais os órgãos pagam preços diferentes."
                           % (min_compras, min_orgaos)),
            "ressalva": RESSALVA}


def comparar(grupo: str, unidade: str | None = None, db_path: str | None = None,
             esfera: str | None = None) -> dict:
    """Para UM item (grupo normalizado + unidade), ranqueia ÓRGÃOS e FORNECEDORES pelo preço
    unitário mediano. Mostra quem paga acima/abaixo da mediana geral do item."""
    un_alvo = _un(unidade) if unidade is not None else None
    con = _ro(db_path)
    try:
        itens = [r for (b, u), lst in _grupos(con, _certs(con, esfera)).items() if b == grupo
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


def _eficiencia(con, por: str, min_itens: int, certs: set | None = None) -> list:
    """Agrega, por órgão OU fornecedor, a razão preço/mediana-do-item ao longo de MUITOS itens.
    razão mediana <1 = paga/cobra abaixo do mercado; >1 = acima. Exige ≥`min_itens` itens DISTINTOS
    comparáveis (diversidade real, não a mesma compra repetida) para significância."""
    razoes: dict = defaultdict(list)
    itens_de: dict = defaultdict(set)                 # k -> conjunto de itens distintos (sem cap)
    ident: dict = {}
    for (base, un), itens in _grupos(con, certs).items():
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


def ranking_orgaos(db_path: str | None = None, min_itens: int = 8, limite: int = 60,
                   esfera: str | None = None) -> dict:
    """Órgãos por eficiência de gasto: razão mediana preço/mercado ao longo de muitos itens.
    <1 = compra abaixo do mercado (gasta bem); >1 = paga acima (auditar)."""
    con = _ro(db_path)
    try:
        r = _eficiencia(con, "orgao", min_itens, _certs(con, esfera))
        r.sort(key=lambda x: x["razao_mediana"])
        return {"ok": True, "melhores": r[:limite], "piores": list(reversed(r))[:limite],
                "n": len(r),
                "explicacao": ("Para cada órgão, a razão mediana entre o que ele paga e a mediana de "
                               "mercado do item, ao longo de ≥8 itens comparáveis. <1 = gasta melhor "
                               "que o mercado; >1 = paga acima (candidato a auditoria de preços)."),
                "ressalva": RESSALVA}
    finally:
        con.close()


def ranking_fornecedores(db_path: str | None = None, min_itens: int = 8, limite: int = 60,
                         esfera: str | None = None) -> dict:
    """Fornecedores por preço relativo: razão mediana preço/mercado ao longo de muitos itens.
    >1 = cobra acima do mercado (caro); <1 = abaixo (barato)."""
    con = _ro(db_path)
    try:
        r = _eficiencia(con, "fornecedor", min_itens, _certs(con, esfera))
        r.sort(key=lambda x: -x["razao_mediana"])
        return {"ok": True, "mais_caros": r[:limite], "mais_baratos": list(reversed(r))[:limite],
                "n": len(r),
                "explicacao": ("Para cada fornecedor, a razão mediana entre o que ele cobra e a "
                               "mediana de mercado do item, ao longo de ≥8 itens. >1 = cobra acima "
                               "do mercado; <1 = abaixo."),
                "ressalva": RESSALVA}
    finally:
        con.close()


def _esferas_das_linhas(con, esfera: str | None) -> dict[str, set] | None:
    """Esfera(s) do ACHADO → {rótulo: certames}. 'todas' → None (sem filtro)."""
    if esfera == "todas":
        return None
    alvo = [esfera] if esfera else list(_ESFERAS_FISCALIZADAS)
    return {e: (_certs(con, e) or set()) for e in alvo}


def economia_potencial(db_path: str | None = None, min_orgaos: int = 3, min_amostra: int = 5,
                       min_certames: int = 4, limite: int = 60, esfera: str | None = None,
                       fator: float = 2.0, verificacao: dict | None = None,
                       info_certames: dict | None = None) -> dict:
    """Quanto se teria deixado de gastar se cada compra com INDÍCIO DE SOBREPREÇO tivesse pago a
    MEDIANA de mercado do MESMO item, na MESMA unidade e apresentação.

    Refeito em 2026-11-13 ("não pode ter margem pra erro em nada"). Só entra na soma a compra que:
      1. está num GRUPO HOMOGÊNEO (preco_normalizado: unidade comprovada, mesma apresentação,
         sem salto de preço, dispersão p90/p10 ≤ 4) — unidade ambígua é INDETERMINADO, fora;
      2. tem preço normalizado ≥ `fator`× a mediana E fora da banda robusta (o mesmo critério
         do sobrepreço da aba — antes a economia somava QUALQUER compra acima da mediana);
      3. não é inexigibilidade, agricultura familiar/chamada pública nem objeto com marca
         exigida (preço legalmente diferenciado não é sobrepreço);
      4. foi VERIFICADA na fonte primária (PNCP: descrição, unidade, quantidade e preço
         homologado conferem) — o resto fica em `economia_pendente`, nunca na manchete;
      5. NÃO é ata de registro de preços: a quantidade de ata é ESTIMATIVA, não compra; vai
         para `economia_ata_teto` (teto, rotulado), nunca para o total.
    Separa Estado × Prefeitura (`por_esfera`). Quantidade = homologada no PNCP — não é OB paga.
    """
    from compliance_agent import verificacao_pncp as V
    con = _ro(db_path)
    try:
        esferas = _esferas_das_linhas(con, esfera)
        g = comparacao_homogenea(con, min_amostra=min_amostra, min_certames=min_certames,
                                 min_orgaos=min_orgaos)
    finally:
        con.close()
    verif = verificacao if verificacao is not None else V.estados(db_path)
    info = info_certames if info_certames is not None else V.info_certames(db_path)

    def _esfera_de(cert):
        if esferas is None:
            return "todas"
        for e, cs in esferas.items():
            if cert in cs:
                return e
        return None

    tot = {"verificada": 0.0, "ata": 0.0, "pendente": 0.0, "divergente": 0.0}
    n = {"verificada": 0, "ata": 0, "pendente": 0, "divergente": 0}
    por_esfera: dict[str, dict] = {}
    por_item: dict[tuple, dict] = {}
    por_orgao: dict[str, dict] = {}
    por_forn: dict[str, dict] = {}
    for grp in g["grupos"]:
        med = grp["mediana"]
        for r, _z in achados_do_grupo(grp, fator=fator):
            esf = _esfera_de(r["certame"])
            if esf is None:
                continue                                  # achado de outra esfera
            excesso = (r["pn"] - med) * (r["qn"] or 0)
            if excesso <= 0:
                continue
            ev = V.estado_de(verif, r["certame"], r.get("item"), r["fornecedor_cnpj"])["estado"]
            srp = (info.get(r["certame"]) or {}).get("srp")
            if ev == V.DIVERGENTE:
                balde = "divergente"
            elif ev != V.VERIFICADO or srp is None:
                balde = "pendente"
            elif srp:
                balde = "ata"
            else:
                balde = "verificada"
            tot[balde] += excesso
            n[balde] += 1
            pe = por_esfera.setdefault(esf, {"esfera": esf, "economia": 0.0, "n": 0,
                                             "ata_teto": 0.0, "pendente": 0.0})
            if balde == "verificada":
                pe["economia"] += excesso
                pe["n"] += 1
            elif balde == "ata":
                pe["ata_teto"] += excesso
            elif balde == "pendente":
                pe["pendente"] += excesso
            if balde != "verificada":
                continue                                  # quebras só com o que se sustenta
            it = por_item.setdefault((grp["desc"], grp["chave"], grp["faixa"]), {
                "item": r["d"], "unidade_medida": r["un"], "unidade_normalizada": grp["rotulo"],
                "mediana": round(med, 4), "dispersao": round(grp["dispersao"], 2),
                "descricao_generica": False, "economia": 0.0, "n": 0})
            it["economia"] += excesso
            it["n"] += 1
            org = _norm_ente(r.get("unidade_nome") or r.get("orgao_nome"))
            og = por_orgao.setdefault(org, {"orgao": org, "esfera": esf, "economia": 0.0, "n": 0})
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

    for pe in por_esfera.values():
        for k in ("economia", "ata_teto", "pendente"):
            pe[k] = round(pe[k], 2)
    certs_todos = set().union(*esferas.values()) if esferas else None
    return {"ok": True,
            # manchete: só compra VERIFICADA no PNCP, fora de ata, em grupo homogêneo
            "economia_total": round(tot["verificada"], 2),
            "n_compras_acima_mediana": n["verificada"],
            "economia_homogenea": round(tot["verificada"], 2),   # compat (cockpit antigo)
            "n_compras_homogeneas": n["verificada"],
            "economia_descricao_generica": 0.0,   # compat: grupo genérico não entra mais em conta
            "economia_ata_teto": round(tot["ata"], 2), "n_compras_ata": n["ata"],
            "economia_pendente": round(tot["pendente"], 2), "n_compras_pendentes": n["pendente"],
            "economia_divergente": round(tot["divergente"], 2),
            "n_compras_divergentes": n["divergente"],
            "por_esfera": por_esfera, "fator": fator, "dispersao_max": 4.0,
            "por_item": _top(por_item), "por_orgao": _top(por_orgao),
            "por_fornecedor": _top(por_forn),
            "indeterminados": resumo_indeterminados(g["indeterminados"], certs_todos, n_lista=0),
            "explicacao": (f"Quanto se teria deixado de gastar se cada compra com indício de "
                           f"sobrepreço (preço ≥ {fator:g}× a mediana do MESMO item, na MESMA "
                           "unidade e apresentação) tivesse pago a mediana — somando só compras "
                           "conferidas no PNCP e fora de ata de registro de preços."),
            "ressalva": ("Quantidade homologada no PNCP, não pagamento (OB): o efetivamente pago a "
                         "mais é INDISPONÍVEL sem empenho/OB. Ata de registro de preços aparece à "
                         "parte como teto (quantidade estimada). Item com unidade ambígua ou grupo "
                         "heterogêneo fica INDETERMINADO e fora da conta. Confirmar termo de "
                         "referência. Indício ≠ acusação.")}


_ESFERA_PNCP = {"E": "estadual", "F": "federal", "M": "municipal", "N": "federal"}


def economia_vedada(db_path: str | None = None, min_orgaos: int = 3, min_amostra: int = 5,
                    esfera: str | None = None,
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
        certs_esf = _certs_alvo(con, esfera)   # mediana GLOBAL; achado restrito à esfera da aba
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
                if certs_esf is not None and r["certame"] not in certs_esf:
                    continue                       # compra de outra esfera não entra na aba
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
                    min_certames: int = 3, limite: int = 120, esfera: str | None = None,
                    min_amostra: int = 5) -> dict:
    """DOSSIÊ AUTOMÁTICO: item comprado MUITO acima da mediana (≥`fator`×) por um órgão, cujo
    fornecedor vencedor É SUSPEITO por outra fonte independente — sancionado (CEIS/CNEP), no radar
    de risco, ou fantasma.

    Corrigido em 2026-11-13 (revisão D6): o card dizia "5 itens pagos caro a fornecedor
    sancionado" e **nenhum** dos 5 estava sancionado na data da compra — todas as sanções eram
    posteriores, e uma vinha de outro ente. Agora 'sancionada' só se a sanção (a) estava VIGENTE
    na data do certame e (b) VEDAVA aquele ente comprador (`sancao_abrangencia.veda_ente`).
    Sanção posterior aparece como 'sancionada_depois' (peso 1, informativo — não é vedação).
    O preço vem da mesma base homogênea do sobrepreço (unidade comprovada, sem salto, sem
    grupo heterogêneo)."""
    from compliance_agent.sancao_abrangencia import classificar_sancao, veda_ente
    con = _ro(db_path)
    try:
        sanc: dict[str, list] = {}
        for r in con.execute(
                "SELECT cpf_cnpj, categoria, fundamentacao, cadastro, orgao, uf, data_inicio, "
                "data_fim FROM sancoes_federais WHERE length(cpf_cnpj)=14"):
            cl = classificar_sancao(r["categoria"], r["fundamentacao"], r["cadastro"])
            if cl["veda_contratacao"]:
                sanc.setdefault(r["cpf_cnpj"], []).append(dict(r))
        try:
            esfera_oficial = {r["cnpj"]: _ESFERA_PNCP.get(r["esfera_id"]) for r in
                              con.execute("SELECT cnpj, esfera_id FROM pncp_ente")}
        except sqlite3.OperationalError:
            esfera_oficial = {}
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
        certs = _certs_alvo(con, esfera)   # mediana GLOBAL; achado restrito à esfera da aba
        g = comparacao_homogenea(con, min_amostra=min_amostra, min_certames=min_certames,
                                 min_orgaos=min_orgaos)
    finally:
        con.close()

    rank = {"total": 3, "ente": 2, "orgao": 1}
    achados = []
    for grp in g["grupos"]:
        med = grp["mediana"]
        for r, _z in achados_do_grupo(grp, fator=fator):
            if certs is not None and r["certame"] not in certs:
                continue
            cnpj = r["fornecedor_cnpj"]
            data = (r.get("data_pub") or "")[:10]
            sinais = []
            if cnpj in sanc:
                melhor, depois = None, False
                esf_alvo = esfera_oficial.get(r.get("orgao_cnpj")) or "estadual"
                uf_alvo = (r.get("uf") or "RJ").upper()
                for s in sanc[cnpj]:
                    ini, fim = s.get("data_inicio") or "", s.get("data_fim") or "9999"
                    if not data or not ini:
                        continue                   # sem data não se afirma vigência
                    if ini > data:
                        depois = True
                        continue
                    if data > fim:
                        continue
                    v = veda_ente(s, esf_alvo, uf_alvo)
                    if v["veda"] and (melhor is None or
                                      rank[v["abrangencia"]] > rank[melhor["abrangencia"]]):
                        melhor = v
                if melhor:
                    sinais.append({"sinal": "sancionada", "peso": 3,
                                   "abrangencia": melhor["abrangencia"],
                                   "motivo": melhor.get("motivo")})
                elif depois:
                    sinais.append({"sinal": "sancionada_depois", "peso": 1})
            if cnpj in radar:
                sinais.append({"sinal": f"radar_{radar[cnpj]}", "peso": 2})
            if cnpj in fant:
                sinais.append({"sinal": f"fantasma_{fant[cnpj]}", "peso": 2})
            if not sinais:
                continue                      # caro MAS sem outro sinal → fica no sobrepreço
            achados.append({
                "item": r["d"], "grupo": grp["desc"], "unidade_medida": r["un"],
                "unidade_normalizada": grp["rotulo"],
                "orgao": r.get("unidade_nome") or r.get("orgao_nome"),
                "municipio": r.get("municipio"),
                "fornecedor": r["fornecedor_nome"], "fornecedor_cnpj": cnpj,
                "preco": round(r["vu"], 2), "preco_normalizado": round(r["pn"], 4),
                "mediana": round(med, 4), "vs_mediana": round(r["pn"] / med, 1),
                "sobrepreco_est": round(r["pn"] - med, 4),
                "certame": r["certame"], "data": data,
                "sinais": sinais, "gravidade": sum(s["peso"] for s in sinais)})
    achados.sort(key=lambda a: (-a["gravidade"], -a["vs_mediana"]))
    return {"ok": True, "achados": achados[:limite], "n": len(achados),
            "n_sancionada": sum(1 for a in achados
                                if any(s["sinal"] == "sancionada" for s in a["sinais"])),
            "explicacao": ("Cruzamento do comparador de preços com o gabarito de risco: item pago "
                           f"≥{fator:g}× a mediana do MESMO item (mesma unidade e apresentação) por "
                           "um órgão, cujo FORNECEDOR estava sancionado À ÉPOCA com vedação para "
                           "aquele ente, está no radar de risco ou é fantasma."),
            "ressalva": ("O preço alto e o sinal de risco vêm de FONTES INDEPENDENTES — a "
                         "coincidência é o indício, não prova. 'sancionada_depois' é sanção "
                         "POSTERIOR à compra: não vedava a contratação. Confirmar termo de "
                         "referência. Indício ≠ acusação.")}



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
        print(f"ECONOMIA PAGA A FORNECEDOR VEDADO: R${moeda(d['economia_vedada_total'])}  "
              f"({d['n_compras']} compras) | por abrangência: {d['por_abrangencia']}")
        for f in d["por_fornecedor"][:12]:
            print(f"   R${f['economia_vedada']:>12,.2f}  [{f['abrangencia']}]  "
                  f"{(f['fornecedor'] or '')[:40]:40} (n={f['n']})")
    elif cmd == "economia":
        d = economia_potencial()
        print(f"ECONOMIA POTENCIAL: R${moeda(d['economia_total'])}  "
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
