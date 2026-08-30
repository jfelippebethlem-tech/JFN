"""Fracionamento de dispensa por valor (art. 75, §1º, Lei 14.133/2021) na Prefeitura do Rio.

CRITÉRIO POR EXTENSO
--------------------
O art. 75, §1º, veda o fracionamento: os valores das dispensas dos incisos I e II
"serão duplicados para compras, obras e serviços contratados por consórcio público ou por
autarquia ou fundação qualificadas como agências executivas" e, para efeito do teto,
"considerar-se-á o somatório do que for despendido no exercício financeiro pela respectiva
UNIDADE GESTORA". Ou seja, o teto é do EXERCÍCIO e da UNIDADE, não da dispensa isolada.

Este detector marca dois padrões, em ordem decrescente de força probatória:

  (A) MESMO PROCESSO ADMINISTRATIVO, várias dispensas, soma acima do teto.
      É o corte mais forte: não cabe a defesa de "objetos diferentes" nem de "unidades
      diferentes" — a própria Administração instruiu tudo num só processo.

  (B) MESMA UNIDADE + objeto semelhante + mesmo exercício, soma acima do teto.
      Corte mais amplo e mais atacável: depende da similaridade de objeto (Jaccard sobre
      palavras de conteúdo) e da unidade extraída do texto do aviso.

TETOS — fonte declarada
-----------------------
Art. 75, II (compras e serviços em geral), atualizado anualmente pelo Executivo federal
(art. 182 da Lei 14.133) e aplicável a todos os entes:
  2021 R$  50.000,00  (valor original da Lei 14.133/2021)
  2023 R$  59.906,02  (Decreto nº 11.317/2022)
  2024 R$  59.906,02
  2025 R$  62.725,59  (Decreto nº 12.343/2024, vigente 01/01/2025) — CONFERIDO na fonte
  2026 R$  62.725,59  (fallback; ATUALIZAR — há Decreto nº 12.807/2025 para 2026 ainda não conferido)

LIMITES DE FONTE — leia antes de citar qualquer número
------------------------------------------------------
1. O valor usado é o **ESTIMADO no aviso de dispensa** (`edital_documento.valor_estimado`),
   NÃO o valor pago. Empenho ≠ liquidação ≠ OB. Para afirmar despesa, cruzar com `pcrj_despesa`.
2. Cobrimos **1.095 editais da PCRJ** com documento — não é o universo das dispensas do
   município. O resultado é PISO, nunca total. INDISPONÍVEL ≠ 0.
3. A unidade é extraída por regex do texto do aviso; quando não há casamento, o registro
   entra como `unidade=None` e NÃO é agrupado em (B).
4. Indício ≠ acusação. Fracionamento admite justificativa (urgência superveniente, itens
   de natureza distinta, unidades gestoras autônomas). O detector aponta o que MERECE exame.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import defaultdict

DB = "data/compliance.db"
RAIZ_PCRJ = "42498733"

TETO_ART75_II = {
    2021: 50_000.00, 2022: 54_020.41, 2023: 59_906.02,
    2024: 59_906.02, 2025: 62_725.59, 2026: 62_725.59,
}
TETO_PADRAO = 62_725.59

_RX_PROCESSO = re.compile(r"\b([A-Z]{2,6})[-–]([A-Z]{3})[-–](20\d{2})\s*/\s*(\d{3,8})\b")
_RX_INCISO = re.compile(
    r"art\.?\s*75[^\n]{0,40}?inciso\s*([IVX]+)|art\.?\s*75\s*,?\s*(?:inc\.?\s*)?([IVX]+)", re.I)
_RX_DISPENSA = re.compile(r"DISPENSA", re.I)
_RX_UNIDADE = re.compile(
    r"(Hospital[^,\n\.]{3,60}|Maternidade[^,\n\.]{3,50}|Instituto[^,\n\.]{3,50}"
    r"|Policl[íi]nica[^,\n\.]{3,50}|Centro Municipal de Sa[úu]de[^,\n\.]{0,45}|UPA[^,\n\.]{0,40})")

# palavras que não distinguem objeto — sem elas, "aquisição de material" casaria com tudo
_STOP = {
    "de", "da", "do", "das", "dos", "para", "e", "a", "o", "em", "com", "por", "aquisicao",
    "contratacao", "fornecimento", "prestacao", "servicos", "servico", "material", "materiais",
    "futura", "eventual", "registro", "precos", "preco", "atender", "destinada", "unidade",
    "visando", "n", "no", "na",
}
LIMIAR_JACCARD = 0.5


def teto(ano: int | None) -> float:
    return TETO_ART75_II.get(ano or 0, TETO_PADRAO)


def _palavras(texto) -> set[str]:
    s = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z]{3,}", s) if w not in _STOP}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a and b) else 0.0


def carregar_dispensas(db_path: str = DB) -> list[dict]:
    """Dispensas do art. 75, II, da PCRJ com documento capturado."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT numero_controle_pncp, ano, objeto, valor_estimado, texto "
            "FROM edital_documento WHERE substr(orgao_cnpj,1,8)=? AND texto IS NOT NULL",
            (RAIZ_PCRJ,)).fetchall()
    finally:
        con.close()

    out = []
    for cert, ano, objeto, valor, texto in rows:
        if not _RX_DISPENSA.search(texto[:900]):
            continue
        m = _RX_INCISO.search(texto)
        inciso = (m.group(1) or m.group(2)).upper() if m else None
        if inciso != "II":
            continue
        p = _RX_PROCESSO.search(texto)
        u = _RX_UNIDADE.findall(texto)
        unidade = re.sub(r"\s+", " ", u[0]).strip()[:52] if u else None
        out.append({
            "certame": cert,
            "ano": ano or (int(p.group(3)) if p else None),
            "processo": p.group(0) if p else None,
            "orgao": p.group(1) if p else None,
            "unidade": unidade,
            "objeto": objeto,
            "valor_estimado": valor or 0.0,
        })
    return out


def corte_a_mesmo_processo(dispensas: list[dict]) -> list[dict]:
    """(A) mesmo processo administrativo, >1 dispensa, soma acima do teto do exercício."""
    por_processo = defaultdict(list)
    for d in dispensas:
        if d["processo"]:
            por_processo[d["processo"]].append(d)
    achados = []
    for processo, ds in por_processo.items():
        if len(ds) < 2:
            continue
        soma = sum(d["valor_estimado"] for d in ds)
        t = teto(ds[0]["ano"])
        if soma > t:
            achados.append({"processo": processo, "n": len(ds), "soma": soma, "teto": t,
                            "razao": soma / t, "dispensas": sorted(ds, key=lambda x: -x["valor_estimado"])})
    return sorted(achados, key=lambda a: -a["soma"])


def corte_b_mesma_unidade(dispensas: list[dict]) -> list[dict]:
    """(B) mesma unidade + exercício + objeto semelhante (Jaccard >= limiar), soma acima do teto."""
    grupos = defaultdict(list)
    for d in dispensas:
        if d["unidade"] and d["ano"]:
            grupos[(d["unidade"], d["ano"])].append(d)
    achados = []
    for (unidade, ano), ds in grupos.items():
        for d in ds:
            d["_kw"] = _palavras(d["objeto"])
        usados = set()
        for i, d in enumerate(ds):
            if i in usados or not d["_kw"]:
                continue
            grupo = [d]
            usados.add(i)
            for j, e in enumerate(ds):
                if j in usados or not e["_kw"]:
                    continue
                if _jaccard(d["_kw"], e["_kw"]) >= LIMIAR_JACCARD:
                    grupo.append(e)
                    usados.add(j)
            soma = sum(x["valor_estimado"] for x in grupo)
            t = teto(ano)
            if len(grupo) > 1 and soma > t:
                achados.append({"unidade": unidade, "ano": ano, "n": len(grupo), "soma": soma,
                                "teto": t, "razao": soma / t,
                                "processos": sorted({x["processo"] for x in grupo if x["processo"]}),
                                "dispensas": sorted(grupo, key=lambda x: -x["valor_estimado"])})
    return sorted(achados, key=lambda a: -a["soma"])


def agrupamento_no_teto(dispensas: list[dict]) -> dict:
    """Bunching: dispensas coladas logo abaixo do teto vs. acima dele.

    Um teto meramente observado produziria distribuição contínua ao redor dele. Concentração
    logo abaixo com quase nada acima indica que o valor foi ajustado AO teto — indício de que
    o limite é contornado, não respeitado. Não é prova isolada: é sinal agregado."""
    colado = acima = 0
    for d in dispensas:
        t = teto(d["ano"])
        v = d["valor_estimado"]
        if 0.95 * t <= v < t:
            colado += 1
        elif v >= t:
            acima += 1
    return {"colado_5pct_abaixo": colado, "acima_do_teto": acima,
            "razao": colado / acima if acima else None, "n": len(dispensas)}


def resumo(db_path: str = DB) -> dict:
    ds = carregar_dispensas(db_path)
    a, b = corte_a_mesmo_processo(ds), corte_b_mesma_unidade(ds)
    return {
        "n_dispensas_art75_II": len(ds),
        "valor_estimado_total": sum(d["valor_estimado"] for d in ds),
        "corte_a": {"n_processos": len(a), "soma": sum(x["soma"] for x in a), "achados": a},
        "corte_b": {"n_grupos": len(b), "soma": sum(x["soma"] for x in b), "achados": b},
        "bunching": agrupamento_no_teto(ds),
        "_fonte": "edital_documento (PNCP, raiz 42498733) — valor ESTIMADO, não pago",
        "_limite": "1.095 editais capturados; resultado é PISO, não o universo de dispensas da PCRJ",
    }


if __name__ == "__main__":
    r = resumo()
    print(f"dispensas art. 75 II da PCRJ: {r['n_dispensas_art75_II']:,} · "
          f"R$ {r['valor_estimado_total']:,.2f} (estimado)")
    bn = r["bunching"]
    print(f"bunching: {bn['colado_5pct_abaixo']} colados nos 5% abaixo do teto × "
          f"{bn['acima_do_teto']} acima = {bn['razao']:.1f}x")
    print(f"\n(A) mesmo processo administrativo: {r['corte_a']['n_processos']} processos · "
          f"R$ {r['corte_a']['soma']:,.2f}")
    for x in r["corte_a"]["achados"][:5]:
        print(f"   {x['processo']}  {x['n']} disp.  R$ {x['soma']:,.2f}  ({x['razao']:.2f}x o teto)")
    print(f"\n(B) mesma unidade + objeto semelhante: {r['corte_b']['n_grupos']} grupos · "
          f"R$ {r['corte_b']['soma']:,.2f}")
    for x in r["corte_b"]["achados"][:5]:
        print(f"   {x['unidade'][:44]:46s} {x['ano']} {x['n']:3d} disp. "
              f"R$ {x['soma']:>13,.2f}  ({x['razao']:.1f}x)")
    print(f"\nFONTE: {r['_fonte']}\nLIMITE: {r['_limite']}")
