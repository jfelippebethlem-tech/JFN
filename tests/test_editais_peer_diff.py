# -*- coding: utf-8 -*-
"""T5 — peer-diff (raridade no grupo × força E7)."""
from compliance_agent.editais import peer_diff


def test_raridade():
    # 'X' aparece em 1 de 4 editais → raridade 0.75
    clau = [("e1", "X"), ("e2", "Y"), ("e3", "Y"), ("e4", "Y")]
    assert peer_diff.raridade("X", clau) == 0.75
    assert peer_diff.raridade("Y", clau) == 0.25


def test_forca_e7_por_subtipo():
    nivel, sumula = peer_diff.forca_e7("marca")
    assert nivel == "forte" and "270" in sumula
    nivel2, _ = peer_diff.forca_e7("indices")
    assert nivel2 == "medio"
    nivel3, _ = peer_diff.forca_e7("desconhecido")
    assert nivel3 == "fraco"


def test_score_candidatura():
    # rara (0.75) × forte (1.0) = 0.75
    assert abs(peer_diff._score(0.75, "forte") - 0.75) < 1e-9
    assert abs(peer_diff._score(0.75, "medio") - 0.45) < 1e-9


def _con_cluster_pequeno():
    """Cluster de 2 editais (não avaliável por peer-diff) com cláusula FORTE (marca)."""
    import sqlite3, json
    from compliance_agent.editais import db as ed
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    ed.init_schema(con)
    con.execute("INSERT INTO edital_cluster (id, assinatura_objeto, membros_json, tamanho, avaliavel) "
                "VALUES (1, 'toner', ?, 2, 1)", (json.dumps(["a", "b"]),))
    con.execute("INSERT INTO edital_clausula (id, numero_controle_pncp, eixo, subtipo, texto, assinatura) "
                "VALUES (1, 'a', 'tecnica', 'marca', 'exclusivamente marca HP', 'tecnica:marca:1')")
    con.execute("INSERT INTO edital_clausula (id, numero_controle_pncp, eixo, subtipo, texto, assinatura) "
                "VALUES (2, 'b', 'tecnica', 'indices', 'liquidez 2.0', 'economica:indices:1')")
    return con


def test_cluster_pequeno_cai_no_catalogo_absoluto():
    # cluster < 3: peer-diff indisponível, mas cláusula de tier FORTE ainda vira candidata
    # (raridade=None = comparação honesta indisponível; força vem do catálogo E7 absoluto)
    con = _con_cluster_pequeno()
    cands = peer_diff.candidatas(con, 1)
    fortes = [c for c in cands if c["forca_e7"] == "forte"]
    assert fortes, "cláusula forte de cluster pequeno não pode ser silenciada (falso negativo estrutural)"
    c = fortes[0]
    assert c["raridade"] is None and c.get("origem") == "absoluto"
    # tier médio/fraco NÃO entra no fallback (sem comparação, só força alta sustenta indício)
    assert all(x["forca_e7"] == "forte" for x in cands)
