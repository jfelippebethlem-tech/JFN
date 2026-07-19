# -*- coding: utf-8 -*-
"""Peer-diff — o núcleo do direcionamento: uma exigência é suspeita quando os
PARES que compram o mesmo objeto NÃO a fazem.

raridade = fração dos editais do cluster que NÃO têm a assinatura.
forca_e7 = tier de restritividade do catálogo E7 (mesmos limiares/súmulas),
           via knowledge.jurisprudencia.
candidata = raridade alta × força alta. Só candidatas sobem ao enxame.
"""
from __future__ import annotations

import json

from compliance_agent.knowledge.jurisprudencia import fundamentar_clausula

# subtipo (da assinatura) → tier E7. 'forte' = âncora forte do catálogo E7
# (atestado>50%, marca sem equivalente, capital/PL, visita, vínculo, geográfico).
_FORTE = {"atestado", "marca", "capital", "patrimonio", "visita", "vinculo", "geografico"}
_MEDIO = {"indices", "amostra", "pontuacao", "temporal"}
# subtipo → tipo canônico do catálogo E7 p/ buscar a súmula
_SUBTIPO_PARA_TIPO_E7 = {
    "atestado": "atestado_quantitativo", "marca": "marca_dirigida",
    "capital": "capital_patrimonio", "patrimonio": "capital_patrimonio",
    "visita": "visita_tecnica", "vinculo": "vinculo_profissional",
    "geografico": "recorte_geografico", "indices": "indices_contabeis",
    "temporal": "recorte_temporal",
}
_PESO = {"forte": 1.0, "medio": 0.6, "fraco": 0.3}


def raridade(assin: str, pares: list[tuple]) -> float:
    """pares = [(edital_id, assinatura)]. Fração de editais DISTINTOS sem a assinatura."""
    editais = {e for e, _ in pares}
    com = {e for e, a in pares if a == assin}
    if not editais:
        return 0.0
    return round(1 - len(com) / len(editais), 4)


def forca_e7(subtipo: str) -> tuple[str, str]:
    """(nivel, sumula). Nível pelo catálogo E7; súmula pela jurisprudência da casa."""
    nivel = "forte" if subtipo in _FORTE else ("medio" if subtipo in _MEDIO else "fraco")
    fund = fundamentar_clausula(_SUBTIPO_PARA_TIPO_E7.get(subtipo, ""))
    sumulas = (fund.get("sumulas") or fund.get("dispositivos_legais") or []) if fund else []
    return nivel, (sumulas[0] if sumulas else "")


def _score(rar: float, nivel: str) -> float:
    return round(rar * _PESO.get(nivel, 0.3), 4)


def candidatas(con, cluster_id: int, limiar_raridade: float = 0.7) -> list[dict]:
    """Cláusulas raras no cluster (raridade ≥ limiar), com força E7 e score, desc."""
    row = con.execute("select membros_json from edital_cluster where id=?", (cluster_id,)).fetchone()
    if not row:
        return []
    membros = json.loads(row["membros_json"])
    if len(membros) < 3:
        # cluster pequeno = peer-diff indisponível. Mas silenciar cláusula de tier FORTE
        # (marca sem equivalente, capital, visita…) seria falso negativo ESTRUTURAL para
        # objetos raros no PNCP. Fallback: catálogo E7 absoluto — raridade=None (honesto:
        # comparação indisponível ≠ 0), só tier forte sobe, score ancorado no peso do tier.
        q = ",".join("?" * len(membros))
        linhas = con.execute(
            f"""select numero_controle_pncp, assinatura, subtipo, id, texto, trecho_fonte
                from edital_clausula where numero_controle_pncp in ({q})""", membros).fetchall()
        out = []
        vistas: set[str] = set()
        for l in linhas:
            if l["assinatura"] in vistas:
                continue
            vistas.add(l["assinatura"])
            nivel, sumula = forca_e7(l["subtipo"])
            if nivel != "forte":
                continue
            out.append({
                "clausula_id": l["id"], "numero_controle_pncp": l["numero_controle_pncp"],
                "assinatura": l["assinatura"], "subtipo": l["subtipo"], "texto": l["texto"],
                "trecho_fonte": l["trecho_fonte"], "raridade": None, "forca_e7": nivel,
                "sumula": sumula, "score": _PESO["forte"] * 0.5, "origem": "absoluto",
            })
        return out
    # raridade máxima num cluster de n é (n-1)/n: com n=3 ela é 0.667 < 0.7 e o limiar fixo
    # silenciava TODO cluster de 3 ("0 candidatas sem erro" é a pior falha). O limiar efetivo
    # acompanha o teto do cluster.
    limiar_raridade = min(limiar_raridade, (len(membros) - 1) / len(membros) - 1e-9)
    q = ",".join("?" * len(membros))
    linhas = con.execute(
        f"""select numero_controle_pncp, assinatura, subtipo, id, texto, trecho_fonte
            from edital_clausula where numero_controle_pncp in ({q})""", membros).fetchall()
    pares = [(l["numero_controle_pncp"], l["assinatura"]) for l in linhas]
    vistas: set[str] = set()
    out = []
    for l in linhas:
        assin = l["assinatura"]
        if assin in vistas:
            continue
        vistas.add(assin)
        rar = raridade(assin, pares)
        if rar < limiar_raridade:
            continue
        nivel, sumula = forca_e7(l["subtipo"])
        out.append({
            "clausula_id": l["id"], "numero_controle_pncp": l["numero_controle_pncp"],
            "assinatura": assin, "subtipo": l["subtipo"], "texto": l["texto"],
            "trecho_fonte": l["trecho_fonte"], "raridade": rar, "forca_e7": nivel,
            "sumula": sumula, "score": _score(rar, nivel),
        })
    out.sort(key=lambda c: -c["score"])
    return out
