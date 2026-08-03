# -*- coding: utf-8 -*-
"""A síntese global tem de CHEGAR ao 360, ao banco e ao painel.

O módulo `sei/sintese_global` nasceu chamável, não automático — e módulo sem caller é a família de
falha mais cara desta casa ("construído, testado, nunca rodado"). Aqui se trava o caminho inteiro:
o `avaliar_pasta` produz a síntese, o `gravar` a persiste em coluna própria, e o card do painel
sabe lê-la.
"""
import json
import sqlite3

from compliance_agent import processo_360 as P


def test_avaliar_devolve_a_sintese():
    from pathlib import Path
    out = P.avaliar_pasta(Path("data/sei_arquivo/270131_000548_2023"))
    s = out.get("sintese")
    assert s, "o 360 não produziu síntese — o módulo continua sem caller"
    assert s["n_docs"] > 0 and s["chars"] > 0
    assert "leitura" in s and s["leitura"]
    assert isinstance(s.get("contradicoes"), list)


def test_a_sintese_conta_a_lacuna_de_captura_do_proprio_processo():
    """A leitura parcial precisa vir do que o 360 mediu, não de um número solto."""
    from pathlib import Path
    out = P.avaliar_pasta(Path("data/sei_arquivo/270131_000548_2023"))
    if out.get("lacunas_captura"):
        assert "PARCIAL" in out["sintese"]["leitura"]


def test_gravar_persiste_a_sintese_em_coluna_propria(tmp_path):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    out = {"status": "OK", "numero_sei": "X/1/2026", "score": 0.5, "score100": 50.0,
           "grau": {"grau": "C"}, "faixa": "ALTO", "achados": [], "lacunas_processo": [],
           "lacunas_captura": [], "docs_chave": [], "acatamento": {}, "escalada": {},
           "cobertura": {}, "sintese": {"leitura": "o conjunto diz X", "contradicoes": []}}
    assert P.gravar(out, con=con) is True
    linha = con.execute("select sintese_json from processo_avaliacao").fetchone()[0]
    assert json.loads(linha)["leitura"] == "o conjunto diz X"
    con.close()


def test_o_painel_le_a_sintese_do_processo():
    from pathlib import Path as _P
    js = _P("static/js/src/abas/index.js").read_text(encoding="utf-8")
    assert "sintese" in js, "o painel não surfa a síntese do processo"


def test_a_rota_do_processo_devolve_a_sintese():
    """A coluna existir no banco não basta: a rota tem de trazê-la, senão o painel nunca vê."""
    from pathlib import Path as _P
    src = _P("rotas/produtos.py").read_text(encoding="utf-8")
    assert '"cobertura_json", "sintese_json"' in src
