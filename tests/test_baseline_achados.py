# -*- coding: utf-8 -*-
"""Um detector que salte de 40 para 400 achados subia em SILÊNCIO.

`tools/pos_correcao.fotografia()` produz, a cada rodada, exatamente o número que serviria de
baseline — faixas de risco e achados por código·grau — e **nada dele era versionado**. Nenhum teste
comparava "hoje" com "o commit anterior"; o `_drift` do `tools/autoauditoria.py` só compara com a
última execução local, e ninguém a executava.

Em 2026-08-05 e 06, sete correções mudaram contagens de família inteira (I6 6→2, CD_ 24→10,
`F_EXECUCAO_SEM_EVIDENCIA` 319→251 críticas, `X_PAGAMENTO_SEM_ATESTACAO` nascendo com 109). Todas
deliberadas, cada uma com leitura dos autos. **O risco não é a mudança — é a mudança que ninguém
pretendeu.**

O teste que compara contra o acervo real é `skipif` sem banco: ele mede o MOTOR, e sem `compliance.db`
não há motor a medir. O que roda em qualquer ambiente é a integridade do próprio baseline.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
ALVO = RAIZ / "tests" / "golden" / "achados_360.json"
DB = RAIZ / "data" / "compliance.db"


def test_o_baseline_existe_e_declara_como_regravar():
    assert ALVO.exists(), "o golden de achados sumiu — sem ele nada trava"
    d = json.loads(ALVO.read_text(encoding="utf-8"))
    assert d.get("faixas") and d.get("graus"), "baseline vazio não protege nada"
    assert "baseline_achados --gravar" in d.get("_leia_isto", ""), \
        "o baseline tem de dizer COMO se regrava — golden sem instrução vira golden apagado"
    assert d.get("_medido_em"), "sem data não se sabe de quando é o retrato"


def test_o_baseline_tem_as_familias_que_a_casa_conhece():
    """Trava de sanidade: um baseline vazio ou truncado passaria em qualquer comparação."""
    d = json.loads(ALVO.read_text(encoding="utf-8"))
    codigos = {k.split(" · ")[0] for k in d["graus"]}
    assert len(codigos) >= 20, f"só {len(codigos)} códigos no baseline — truncado?"
    # as famílias estruturais do 360, que não podem sumir sem alguém notar
    for esperado in ("F_EXECUCAO_SEM_EVIDENCIA", "AC_SEM_PARECER_LOCALIZADO", "C9"):
        assert esperado in codigos, f"{esperado} sumiu do baseline"


def _tem_avaliacoes() -> bool:
    """O banco pode EXISTIR sem a tabela — é o caso do espelho da VM-2, que tem um
    `compliance.db` parcial. `skipif` por existência do arquivo falhava lá com
    OperationalError; a condição honesta é a tabela que o motor escreve."""
    if not DB.exists():
        return False
    import sqlite3
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return bool(con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='processo_avaliacao'"
        ).fetchone())
    finally:
        con.close()


@pytest.mark.skipif(not _tem_avaliacoes(),
                    reason="sem processo_avaliacao não há motor a medir (acervo parcial)")
def test_o_acervo_bate_com_o_baseline():
    from tools.baseline_achados import comparar, ler, medir

    linhas = comparar(ler(), medir())
    assert not linhas, (
        "o motor mudou e o baseline não:\n  " + "\n  ".join(linhas)
        + "\n\nSe foi deliberado, rode `python -m tools.baseline_achados --gravar` e diga no "
          "commit POR QUE cada linha mudou. Se não foi, você acabou de achar uma regressão.")


def test_deriva_organica_nao_alarma_mas_salto_sim():
    """A fronteira que mudou quando a recaptura passou a funcionar (2026-08-08).

    Com o acervo parado, igualdade exata funcionava. Com a recaptura viva, processos saem de
    NAO_AVALIAVEL a cada slot e trazem os achados do que agora se lê — exigir igualdade faria a
    catraca reprovar toda rodada, e regravação diária vira carimbo. A catraca continua pegando o
    que motivou sua criação: família que zera, família que nasce, e o salto 40→400.
    """
    from tools.baseline_achados import comparar

    base = {"graus": {"E7 · alta": 13, "C9 · media": 16, "X7 · critica": 4},
            "faixas": {"BAIXO": 586, "EXTREMO": 6}}
    # +1 numa família existente e +2 numa faixa = acervo crescendo → não alarma
    organico = {"graus": {"E7 · alta": 14, "C9 · media": 16, "X7 · critica": 4},
                "faixas": {"BAIXO": 588, "EXTREMO": 7}}
    assert comparar(base, organico) == []

    # o salto que motivou o baseline → alarma
    salto = {"graus": {"E7 · alta": 130, "C9 · media": 16, "X7 · critica": 4},
             "faixas": {"BAIXO": 586, "EXTREMO": 6}}
    assert any("E7" in x for x in comparar(base, salto))

    # família ZERADA (detector desligado) → alarma mesmo sendo -4
    zerada = {"graus": {"E7 · alta": 13, "C9 · media": 16, "X7 · critica": 0},
              "faixas": {"BAIXO": 586, "EXTREMO": 6}}
    assert any("X7" in x for x in comparar(base, zerada))

    # família NOVA (detector novo/mudado) → alarma mesmo sendo +2
    nova = {"graus": {"E7 · alta": 13, "C9 · media": 16, "X7 · critica": 4,
                      "Z9_INVENTADO · alta": 2},
            "faixas": {"BAIXO": 586, "EXTREMO": 6}}
    assert any("Z9_INVENTADO" in x for x in comparar(base, nova))


def test_o_diff_impresso_nao_esconde_a_deriva():
    """Tolerar não é esconder: `comparar_tudo` mostra a deriva com a marca dela."""
    from tools.baseline_achados import comparar_tudo

    base = {"graus": {"E7 · alta": 13}, "faixas": {}}
    agora = {"graus": {"E7 · alta": 14}, "faixas": {}}
    linhas = comparar_tudo(base, agora)
    assert len(linhas) == 1 and "deriva orgânica" in linhas[0]
