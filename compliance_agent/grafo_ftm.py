# -*- coding: utf-8 -*-
"""Export do Grafo de Poder no modelo FollowTheMoney (FtM) — JFN 2.0, Onda 12.

Alinha o Grafo de Poder (Onda 4) ao padrão FtM (OCCRP/Aleph/OpenSanctions) para interoperar com
Aleph/Gephi SEM migrar de plataforma nem auto-hospedar nada (decisão do dono: nada de self-host).
PURO (sem rede): converte a vizinhança local em entidades FtM válidas.

Mapa: cnpj→Company · socio→Person · ug→PublicBody · cand→Person · arestas pago_por→Payment,
socio→Ownership, doou→Payment(donation), co_endereco→Address. Honesto: vínculo = indício.
"""
from __future__ import annotations

_SCHEMA_NO = {"cnpj": "Company", "socio": "Person", "ug": "PublicBody", "cand": "Person", "end": "Address"}
_SCHEMA_ARESTA = {"pago_por": "Payment", "socio": "Ownership", "doou": "Payment", "co_endereco": "UnknownLink"}


def _ent_id(node: str) -> str:
    return "ftm-" + node.replace(":", "-")


def export(alvo: str, saltos: int = 2, so_contrato: bool = False) -> dict:
    """Exporta a vizinhança do alvo como entidades FtM. {ok, alvo, entidades:[...], n}."""
    from compliance_agent.grafo_poder import vizinhanca

    g = vizinhanca(alvo, saltos=saltos, so_contrato=so_contrato)
    if not g.get("ok"):
        return g
    if not g.get("nos"):
        return {"ok": True, "alvo": alvo, "entidades": [], "n": 0, "_nota": g.get("_nota", "")}

    entidades = []
    # nós → entidades FtM
    for n in g["nos"]:
        tipo = n["tipo"]
        schema = _SCHEMA_NO.get(tipo, "Thing")
        nome = n.get("label") or n["id"].split(":", 1)[-1]
        props = {"name": [str(nome)]}
        if tipo == "cnpj":
            props["registrationNumber"] = [n["id"].split(":", 1)[-1]]
            props["jurisdiction"] = ["br"]
        entidades.append({"id": _ent_id(n["id"]), "schema": schema, "properties": props})
    # arestas → entidades de relação FtM (intervalo: source/target)
    for i, a in enumerate(g.get("arestas", [])):
        schema = _SCHEMA_ARESTA.get(a["rel"], "UnknownLink")
        props = {}
        if schema == "Ownership":
            props = {"owner": [_ent_id(a["para"])], "asset": [_ent_id(a["de"])]}
        elif schema == "Payment":
            props = {"payer": [_ent_id(a["de"])], "beneficiary": [_ent_id(a["para"])]}
            if a.get("total_ob"):
                props["amount"] = [str(a["total_ob"])]
            if a.get("valor"):
                props["amount"] = [str(a["valor"])]
        else:
            props = {"subject": [_ent_id(a["de"])], "object": [_ent_id(a["para"])]}
        entidades.append({"id": f"ftm-rel-{i}", "schema": schema,
                          "properties": {**props, "summary": [a["rel"]]}})

    return {"ok": True, "alvo": alvo, "n": len(entidades), "entidades": entidades,
            "_fonte": "Grafo de Poder (JFN) → FollowTheMoney",
            "_nota": "Formato FtM p/ Aleph/Gephi (interoperar sem migrar). Vínculo = indício, nunca acusação."}
