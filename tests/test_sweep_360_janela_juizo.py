# -*- coding: utf-8 -*-
"""Regra que sempre adia o mesmo job não é prioridade, é inanição.

Medido em 2026-08-04: o juízo por documento rodou em 02/08 e 03/08 e nunca mais — 39 processos
de 1.940 periciáveis (2%). A causa não era custo: a guarda "1 pesado por vez" testava a PRESENÇA
do sweep SEI, que roda `*/30` e ocupa do minuto 00 ao 59 em todas as horas. Não existia janela.

O critério certo é a CARGA. A cadeia do juízo é a grátis: ele lê texto de disco e ESPERA HTTP;
quem come os 2 vCPU é o Chromium + tesseract do sweep. O limite duro da casa (load >= 4 = adiar)
fica intacto.
"""
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "sweep_360.sh"


def _fonte() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_presenca_do_sweep_sozinha_nao_zera_mais_o_slot():
    """Zerar o slot só pode acontecer com load alto — nunca só por o sweep existir.

    A verificação é semântica: toda linha que zera o slot tem de estar sob uma condição de CARGA
    dentro do bloco. Antes, `JUIZO_SEGUNDOS=0` vinha logo depois do `pgrep`, sem olhar load.
    """
    src = _fonte()
    bloco = src[src.index("if pgrep -f"):src.index("export JUIZO_SEGUNDOS")]
    linhas = bloco.splitlines()
    zeros = [i for i, l in enumerate(linhas) if "JUIZO_SEGUNDOS=0" in l]
    assert zeros, "o caminho de adiar sumiu — load alto TEM de adiar"
    for i in zeros:
        anteriores = "\n".join(linhas[max(0, i - 3):i])
        assert re.search(r'-ge\s*4', anteriores), (
            f"linha {i} zera o slot sem olhar a carga: {linhas[i].strip()}")


def test_o_limite_duro_da_casa_continua_de_pe():
    """load >= 4 em 2 vCPU adia; é a regra que já salvou a VM quatro vezes."""
    src = _fonte()
    assert re.search(r'\$L"?\s*-ge\s*4', src), "sumiu a guarda de load >= 4"


def test_juizo_ganha_slot_curto_quando_a_vm_esta_folgada():
    src = _fonte()
    bloco = src[src.index("if pgrep -f"):src.index("export JUIZO_SEGUNDOS")]
    assert "JUIZO_SEGUNDOS=600" in bloco, "sem slot curto, a inanição volta"
