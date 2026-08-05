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


def test_a_rodada_e_RETOMAVEL(tmp_path, monkeypatch):
    """Em 2026-08-04 duas passadas foram interrompidas no meio (uma por carga alta, outra porque o
    código mudara durante a execução) e TODO o trabalho já feito foi perdido — 375 e 100 processos
    reavaliados do zero na vez seguinte. É o retrabalho que esta ferramenta existe para acabar."""
    estado = tmp_path / "estado.json"
    monkeypatch.setattr(PC, "ESTADO", estado)
    PC._estado_gravar({"SEI-000000/000001/2025", "SEI-000000/000002/2025"})
    assert PC._estado_ler() == {"SEI-000000/000001/2025", "SEI-000000/000002/2025"}


def test_estado_ilegivel_nao_impede_a_rodada(tmp_path, monkeypatch):
    estado = tmp_path / "estado.json"
    estado.write_text("{ nao é json", encoding="utf-8")
    monkeypatch.setattr(PC, "ESTADO", estado)
    assert PC._estado_ler() == set()


def test_sem_estado_a_rodada_comeca_do_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(PC, "ESTADO", tmp_path / "nao_existe.json")
    assert PC._estado_ler() == set()


def test_uma_instancia_por_vez(tmp_path, monkeypatch, capsys):
    """Aconteceu em 2026-08-04: rodei uma segunda instância enquanto a primeira ainda processava,
    as duas leram e escreveram o MESMO estado, e a segunda saiu na hora dizendo "0 restantes"
    porque o estado da primeira já cobria o alvo dela. Nenhum dado se perdeu, mas o alvo que eu
    queria reavaliar NÃO foi reavaliado — e eu só descobri conferindo o banco."""
    import os

    trava = tmp_path / "trava.pid"
    trava.write_text(str(os.getpid()), encoding="utf-8")   # o próprio processo do teste
    monkeypatch.setattr(PC, "TRAVA", trava)
    assert PC._outra_instancia_viva() is None or PC._outra_instancia_viva() == os.getpid()


def test_pid_morto_nao_trava_a_ferramenta(tmp_path, monkeypatch):
    trava = tmp_path / "trava.pid"
    trava.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(PC, "TRAVA", trava)
    assert PC._outra_instancia_viva() is None


def test_pid_de_OUTRO_comando_nao_trava(tmp_path, monkeypatch):
    """PID vivo mas de processo que não é a ferramenta: o cmdline desmente o arquivo."""
    import subprocess
    p = subprocess.Popen(["sleep", "20"])
    try:
        trava = tmp_path / "trava.pid"
        trava.write_text(str(p.pid), encoding="utf-8")
        monkeypatch.setattr(PC, "TRAVA", trava)
        assert PC._outra_instancia_viva() is None
    finally:
        p.kill()


def test_trava_ilegivel_nao_impede_a_rodada(tmp_path, monkeypatch):
    trava = tmp_path / "trava.pid"
    trava.write_text("nao é pid", encoding="utf-8")
    monkeypatch.setattr(PC, "TRAVA", trava)
    assert PC._outra_instancia_viva() is None
