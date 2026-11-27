"""27/11/2026: o OXR saiu da bancada (inventava 21,37% dos números no controle nativo). O leitor externo só aceita os
motores que ainda têm ambiente no it-campo — pedir um removido tem de falhar ALTO, nunca ler com outro motor calado."""
import pytest

from tools import ocr_bancada_externo as X


def test_motor_removido_e_recusado():
    with pytest.raises(SystemExit):
        X.main(["--motor", "oxr", "--dir", "/nao/existe"])


def test_so_restam_motores_com_ambiente():
    assert not hasattr(X, "leitor_oxr") and hasattr(X, "leitor_paddlevl")
