# -*- coding: utf-8 -*-
"""O ciclo pós-correção vira ferramenta — porque foi repetido cinco vezes à mão num dia.

Em 2026-08-04 a sequência "corrigir detector → reavaliar 2.174 processos → regravar
`data/fila_fiscal_360.md` → medir o que mudou" foi executada cinco vezes com comandos ad-hoc.
Duas dessas medições saíram ERRADAS: uma porque o script engolia exceção, outra porque comparava
uma chave de 19 caracteres com um conjunto de chaves de 20 — e devolveu um "zero" limpo que quase
virou relatório.

O que o teste protege: a fotografia é comparável entre rodadas, o diff mostra o que mudou (e só
isso), e a ferramenta RESPEITA a regra de carga da casa — com load >= 4 ela não começa.
"""
import json
import sqlite3

import tools.pos_correcao as PC


def _db(tmp_path, linhas):
    """linhas: (faixa, [(codigo, origem), ...])."""
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE processo_avaliacao (numero_sei TEXT, faixa TEXT, score100 REAL, "
                "achados_json TEXT)")
    for i, (faixa, achados) in enumerate(linhas):
        aj = json.dumps([{"codigo": c, "origem": o} for c, o in achados])
        con.execute("INSERT INTO processo_avaliacao VALUES (?,?,?,?)",
                    (f"SEI-000000/{i:06d}/2025", faixa, 50.0, aj))
    con.commit(); con.close()
    return p


def test_fotografia_conta_faixas_codigos_e_origens(tmp_path):
    db = _db(tmp_path, [("EXTREMO", [("A1", "triagem"), ("C9", "fornecedor")]),
                        ("ALTO", [("A1", "triagem")])])
    f = PC.fotografia(db=db)
    assert f["faixas"] == {"EXTREMO": 1, "ALTO": 1}
    assert f["codigos"]["A1"] == 2 and f["codigos"]["C9"] == 1
    assert f["origens"]["triagem"] == 2


def test_achado_sem_codigo_nao_some_da_contagem(tmp_path):
    """As lacunas de fase entram sem `codigo`; contá-las como inexistentes esconderia metade do
    movimento entre rodadas."""
    db = _db(tmp_path, [("ALTO", [(None, "fases.lacunas")])])
    f = PC.fotografia(db=db)
    assert f["codigos"]["—"] == 1 and f["origens"]["fases.lacunas"] == 1


def test_json_ilegivel_nao_derruba_a_fotografia(tmp_path):
    db = _db(tmp_path, [("ALTO", [("A1", "triagem")])])
    con = sqlite3.connect(db)
    con.execute("INSERT INTO processo_avaliacao VALUES ('SEI-x','BAIXO',1.0,'{ nao é json')")
    con.commit(); con.close()
    f = PC.fotografia(db=db)
    assert f["faixas"]["BAIXO"] == 1 and f["codigos"]["A1"] == 1


def test_diff_mostra_so_o_que_mudou():
    antes = {"codigos": {"A1": 10, "A3": 28, "C9": 42}}
    depois = {"codigos": {"A1": 4, "A3": 28, "C9": 42, "X9": 1}}
    linhas = PC._diff(antes, depois, "codigos")
    texto = "\n".join(linhas)
    assert "A1" in texto and "-6" in texto
    assert "X9" in texto and "+1" in texto
    assert "A3" not in texto and "C9" not in texto, "o que não mudou não entra no diff"


def test_base_ausente_devolve_fotografia_vazia_sem_levantar(tmp_path):
    f = PC.fotografia(db=tmp_path / "nao_existe.db")
    assert f["faixas"] == {} and f["codigos"] == {}


def test_respeita_a_regra_de_carga_da_casa(monkeypatch, capsys):
    """2 vCPU é o gargalo: com load >= 4 a casa manda ADIAR, nunca somar trabalho."""
    monkeypatch.setattr(PC, "_carga", lambda: 7.0)
    assert PC.main(["--sem-fila"]) == 1
    assert "ADIAR" in capsys.readouterr().out


def test_nao_existe_laco_infinito_na_ferramenta():
    """Registro explícito da decisão: passe ÚNICO. Um lane que se relança sozinho já foi removido
    desta casa por bom motivo."""
    from pathlib import Path
    src = Path(PC.__file__).read_text(encoding="utf-8")
    codigo = [ln.split("#", 1)[0] for ln in src.splitlines()]
    assert not [ln for ln in codigo if "while True" in ln]
