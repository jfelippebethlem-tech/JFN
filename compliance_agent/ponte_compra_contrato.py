# -*- coding: utf-8 -*-
"""A ponte COMPRA → CONTRATO → ADITIVO — o elo que se dava por inexistente.

O QUE ESTAVA ESCRITO, E O QUE ERA VERDADE. `editais/indice_certame.py:19-23` declara que
"`contrato_aditivo.numero_controle_pncp` é chave de CONTRATO ('-2-') ≠ chave de compra ('-1-') e
NÃO há tabela-ponte compra→contrato → 0 casamentos", e por isso a família EXECUÇÃO do índice sai
INDISPONÍVEL por construção. A observação sobre as chaves está certa e o join direto realmente dá
zero — mas a conclusão não se sustenta: **a ponte já estava no dado**.

`pcrj_contratos.numero_compra` guarda a chave da COMPRA, preenchida em 50.426 de 54.645 contratos
(92%). Medido em 2026-07-29:

    contratos que casam com `pncp_resultado` via `numero_compra` ......... 4.120
    certames com contrato identificado ................................... 2.058 de 17.242 (11,9%)
    contratos com aditivo E com chave de compra .......................... 1.152

Os 11,9% não são defeito da ponte: são a interseção real entre o que foi coletado de resultado de
certame e o que foi coletado de contrato. É pouco, e é MUITO mais que zero — e a diferença entre
"11,9%" e "não existe" muda o que se pode afirmar sobre execução contratual.

O QUE ISSO DESTRAVA. Com a cadeia fechada, a família EXECUÇÃO do índice de certame deixa de ser
indisponível por construção; o X3 (tríade da despesa) ganha caminho até o certame que originou o
contrato; e o `direcionamento_consumado` pode ligar o vínculo societário do vencedor ao contrato
que ele de fato executa.

HONESTIDADE: toda função devolve a COBERTURA junto do resultado. Uma ponte de 11,9% usada como se
fosse total produziria "nenhum contrato com aditivo excessivo neste certame" para 88% dos casos em
que simplesmente não se sabe.
"""
from __future__ import annotations

import sqlite3
from typing import Any


def _ro(caminho: str | None = None) -> sqlite3.Connection:
    import os
    db = caminho or os.environ.get("JFN_DB", "data/compliance.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def contratos_do_certame(con: sqlite3.Connection, certame: str) -> list[dict]:
    """Contratos originados de um certame. Lista vazia = não identificado, NÃO 'não existe'."""
    try:
        return [dict(r) for r in con.execute(
            "SELECT numero_controle_pncp, ano, orgao_cnpj, orgao_nome, fornecedor_documento, "
            "fornecedor_nome, objeto, valor_inicial, valor_global, vigencia_ini, vigencia_fim, "
            "num_aditivos FROM pcrj_contratos WHERE numero_compra = ?", (str(certame),))]
    except sqlite3.OperationalError:
        return []


def certame_do_contrato(con: sqlite3.Connection, contrato: str) -> str | None:
    try:
        r = con.execute("SELECT numero_compra FROM pcrj_contratos "
                        "WHERE numero_controle_pncp = ? LIMIT 1", (str(contrato),)).fetchone()
    except sqlite3.OperationalError:
        return None
    return (r["numero_compra"] or None) if r else None


def cadeia(con: sqlite3.Connection, certame: str) -> dict[str, Any]:
    """Certame → contratos → aditivos, com a cobertura DECLARADA em cada elo.

    `elo_faltante` diz onde a cadeia parou: `contrato` (o certame não tem contrato identificado)
    ou `aditivo` (tem contrato, e nenhum termo coletado). Saber ONDE parou é o que separa
    "contrato regular" de "contrato não observado".
    """
    contratos = contratos_do_certame(con, certame)
    if not contratos:
        return {"certame": certame, "contratos": [], "n_contratos": 0, "n_aditivos": 0,
                "completa": False, "elo_faltante": "contrato",
                "motivo": ("nenhum contrato identificado para este certame — a ponte cobre 11,9% "
                           "dos certames coletados; ausência aqui é lacuna de captura, não "
                           "ausência de contrato")}

    total_aditivos = 0
    for c in contratos:
        try:
            c["aditivos"] = [dict(a) for a in con.execute(
                "SELECT numero_termo, sequencial_termo, objeto, valor_acrescido, valor_global, "
                "prazo_aditado_dias, vigencia_fim, qualif_acrescimo, qualif_vigencia, "
                "qualif_reajuste, fundamento_legal FROM contrato_aditivo "
                "WHERE numero_controle_pncp = ? ORDER BY COALESCE(sequencial_termo, 0)",
                (c["numero_controle_pncp"],))]
        except sqlite3.OperationalError:
            c["aditivos"] = []
        total_aditivos += len(c["aditivos"])

    declarados = sum(int(c.get("num_aditivos") or 0) for c in contratos)
    return {
        "certame": certame, "contratos": contratos, "n_contratos": len(contratos),
        "n_aditivos": total_aditivos, "n_aditivos_declarados": declarados,
        "completa": total_aditivos > 0 or declarados == 0,
        "elo_faltante": None if (total_aditivos or not declarados) else "aditivo",
        "motivo": ("cadeia fechada" if total_aditivos or not declarados else
                   f"os contratos declaram {declarados} aditivo(s) e nenhum foi coletado — "
                   f"lacuna de CAPTURA, não contrato sem aditivo"),
    }


def contexto_execucao_do_certame(con: sqlite3.Connection, certame: str) -> dict[str, Any]:
    """Contexto de execução no formato que X1/X2/X7/X9 consomem, a partir do CERTAME.

    Quando o certame gerou mais de um contrato, devolve o de maior valor global — e diz quantos
    ficaram de fora. Escolher em silêncio o primeiro faria o índice do certame refletir um
    contrato arbitrário.
    """
    from compliance_agent.varredura_execucao_ctx import montar_contexto

    c = cadeia(con, certame)
    if not c["contratos"]:
        return {"certame": certame, "encontrado": False, "motivo": c["motivo"]}
    principal = max(c["contratos"], key=lambda x: float(x.get("valor_global") or 0))
    ctx = montar_contexto(con, principal["numero_controle_pncp"])
    ctx.update({
        "certame": certame, "encontrado": True,
        "n_contratos_do_certame": c["n_contratos"],
        "contratos_nao_considerados": c["n_contratos"] - 1,
        "elo_faltante": c["elo_faltante"],
        "ressalva": (("o certame gerou %d contratos; este é o de maior valor global e os demais "
                      "NÃO entraram na análise" % c["n_contratos"]) if c["n_contratos"] > 1
                     else "contrato único do certame"),
    })
    return ctx


def cobertura(con: sqlite3.Connection) -> dict[str, Any]:
    """Quanto a ponte cobre, de verdade. É o número que precisa acompanhar qualquer conclusão."""
    def _um(sql: str) -> int:
        try:
            r = con.execute(sql).fetchone()
            return int(r[0]) if r and r[0] is not None else 0
        except sqlite3.OperationalError:
            return 0

    total_contratos = _um("SELECT COUNT(*) FROM pcrj_contratos")
    com_chave = _um("SELECT COUNT(*) FROM pcrj_contratos WHERE COALESCE(numero_compra,'') <> ''")
    casam = _um("SELECT COUNT(DISTINCT p.numero_controle_pncp) FROM pcrj_contratos p "
                "JOIN pncp_resultado r ON p.numero_compra = r.certame")
    certames = _um("SELECT COUNT(DISTINCT certame) FROM pncp_resultado")
    certames_com_contrato = _um("SELECT COUNT(DISTINCT r.certame) FROM pncp_resultado r "
                                "JOIN pcrj_contratos p ON p.numero_compra = r.certame")
    cadeia_completa = _um(
        "SELECT COUNT(DISTINCT p.numero_controle_pncp) FROM pcrj_contratos p "
        "JOIN pncp_resultado r ON p.numero_compra = r.certame "
        "JOIN contrato_aditivo a ON a.numero_controle_pncp = p.numero_controle_pncp")
    return {
        "contratos": total_contratos, "contratos_com_chave_de_compra": com_chave,
        "frac_com_chave": round(com_chave / total_contratos, 3) if total_contratos else 0.0,
        "contratos_que_casam": casam,
        "certames": certames, "certames_com_contrato": certames_com_contrato,
        "frac_certames_cobertos": (round(certames_com_contrato / certames, 3)
                                   if certames else 0.0),
        "cadeia_completa_com_aditivo": cadeia_completa,
        "nota": ("A ponte é `pcrj_contratos.numero_compra` → `pncp_resultado.certame`. O join "
                 "DIRETO por `numero_controle_pncp` dá zero porque são chaves de entidades "
                 "diferentes ('-1-' compra × '-2-' contrato) — foi o que levou a documentação a "
                 "registrar que a ponte não existia."),
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Ponte compra → contrato → aditivo")
    ap.add_argument("--cobertura", action="store_true")
    ap.add_argument("--certame")
    a = ap.parse_args(argv)
    con = _ro()
    try:
        if a.certame:
            print(json.dumps(cadeia(con, a.certame), ensure_ascii=False, indent=2, default=str))
        else:
            print(json.dumps(cobertura(con), ensure_ascii=False, indent=2))
    finally:
        con.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
