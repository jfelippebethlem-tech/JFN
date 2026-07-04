# -*- coding: utf-8 -*-
"""Resolvedor de MUNICÍPIO DE VÍNCULO por nome — fusão de fontes PÚBLICAS (OSINT legal).

Objetivo honesto: para cada nomeado da Câmara/Prefeitura, reunir os municípios com que
ele tem **vínculo comprovável em fonte pública** (domicílio eleitoral, empresa onde é
sócio, registro profissional, comarca de processo...), com evidência e nível de confiança.

O que ISTO É e o que NÃO É:
  • NÃO é "onde a pessoa mora" (endereço residencial não é dado público — só requisição).
  • É indício de VÍNCULO por NOME. Sem CPF nas bases da Câmara → casamento por nome é
    indício, homônimo é risco (marcado). Nunca prova.
  • NUNCA usa base vazada/broker — só dado público oficial. Fonte ilícita = prova ilícita.

Arquitetura: cada fonte é uma função `_fonte_*` que devolve `dict[nome_norm] -> [evidência]`.
Fontes já ao vivo: TSE (domicílio eleitoral), QSA (sócio→sede). Plugáveis (via coletores
Scrapling, quando ingeridos): RAB/ANAC, conselhos, DataJud, filiação partidária.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.nomes import normalizar

RIO = "RIO DE JANEIRO"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pcrj_municipio_vinculo (
    nome_norm    TEXT NOT NULL,
    nome         TEXT,
    municipio    TEXT NOT NULL,
    uf           TEXT,
    fontes       TEXT,          -- evidências concatenadas (fonte + ref)
    forca        INTEGER,       -- soma das forças das evidências (3=domicílio, 2=empresa, 1=fraco)
    outra_cidade INTEGER,       -- município ≠ Rio de Janeiro
    gerado_em    TEXT,
    PRIMARY KEY (nome_norm, municipio, uf)
);
CREATE INDEX IF NOT EXISTS ix_munvinc_nome ON pcrj_municipio_vinculo(nome_norm);
"""


def _nomes_alvo(con) -> dict[str, str]:
    """Nomes a resolver: servidores da Câmara (distintos)."""
    return {r["nome_norm"]: r["nome"] for r in con.execute(
        "SELECT DISTINCT nome_norm, nome FROM pcrj_camara_servidores")}


def _fonte_tse(con, alvo: set[str]) -> dict[str, list[dict]]:
    """Domicílio eleitoral (candidatos) — o sinal público mais próximo de residência."""
    out: dict[str, list[dict]] = defaultdict(list)
    for r in con.execute("SELECT nome_norm, municipio, uf, ano FROM tse_candidatura"):
        nn, mun = r["nome_norm"], (r["municipio"] or "").upper()
        if nn in alvo and mun:
            out[nn].append({"municipio": mun, "uf": r["uf"] or "",
                            "fonte": f"TSE domicílio eleitoral {r['ano']}", "forca": 3})
    return out


def _fonte_qsa(alvo: set[str]) -> dict[str, list[dict]]:
    """Sócio de empresa (Receita QSA) → município da sede. Cobertura real depende do
    dump COMPLETO da Receita (o compliance.db hoje só tem sócios de fornecedores)."""
    out: dict[str, list[dict]] = defaultdict(list)
    comp = _db.DB_PATH.parent / "compliance.db"
    if not comp.exists():
        return out
    try:
        c = sqlite3.connect(str(comp)); c.row_factory = sqlite3.Row
        for r in c.execute(
            "SELECT s.nome nome, e.municipio mun, e.uf uf, e.razao_social rz "
            "FROM empresa_socios s JOIN empresas e ON e.id = s.empresa_id "
            "WHERE e.municipio IS NOT NULL"):
            nn = normalizar(r["nome"] or "")
            if nn in alvo and r["mun"]:
                out[nn].append({"municipio": (r["mun"] or "").upper(), "uf": r["uf"] or "",
                                "fonte": f"sócio de {r['rz']}", "forca": 2})
        c.close()
    except Exception:  # noqa: BLE001 — fonte auxiliar, nunca derruba o resolvedor
        pass
    return out


def montar(db_path=None) -> dict:
    """Funde as fontes públicas disponíveis e grava `pcrj_municipio_vinculo`.
    Retorna um resumo honesto de cobertura por fonte."""
    con = _db.conectar(db_path)
    con.executescript(_SCHEMA)
    alvo_nomes = _nomes_alvo(con)
    alvo = set(alvo_nomes)

    fontes = {"TSE": _fonte_tse(con, alvo), "QSA": _fonte_qsa(alvo)}

    # agrega por (nome, município, uf)
    agg: dict[tuple, dict] = {}
    for evid_por_nome in fontes.values():
        for nn, evids in evid_por_nome.items():
            for e in evids:
                k = (nn, e["municipio"], e["uf"])
                a = agg.get(k)
                if not a:
                    a = {"fontes": [], "forca": 0}
                    agg[k] = a
                a["fontes"].append(e["fonte"])
                a["forca"] += e["forca"]

    agora = datetime.now().isoformat(timespec="seconds")
    con.execute("DELETE FROM pcrj_municipio_vinculo")
    for (nn, mun, uf), a in agg.items():
        con.execute(
            "INSERT OR REPLACE INTO pcrj_municipio_vinculo "
            "(nome_norm, nome, municipio, uf, fontes, forca, outra_cidade, gerado_em) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (nn, alvo_nomes.get(nn, ""), mun, uf, " · ".join(sorted(set(a["fontes"]))),
             a["forca"], 0 if mun == RIO else 1, agora))
    con.commit()

    resumo = {
        "nomes_alvo": len(alvo),
        "com_tse": len(fontes["TSE"]),
        "com_qsa": len(fontes["QSA"]),
        "vinculos_municipio": len(agg),
        "pessoas_outra_cidade": len({nn for (nn, mun, _uf) in agg if mun != RIO}),
    }
    con.close()
    return resumo


if __name__ == "__main__":
    import json
    print(json.dumps(montar(), ensure_ascii=False, indent=1))
