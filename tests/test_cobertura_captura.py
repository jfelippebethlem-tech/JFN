# -*- coding: utf-8 -*-
"""O número que limita todos os outros: sobre quanto do dinheiro a casa consegue falar.

Mostrar 51 processos EXTREMO sem dizer que eles saem de 1.941 lidos, num universo de 40.482
processos com OB paga, deixa a impressão contrária à verdade.
"""
import json

from compliance_agent.reporting import cobertura_captura as CC


def _acervo(tmp_path, processos):
    base = tmp_path / "sei_arquivo"
    for nome, textos in processos.items():
        p = base / nome
        (p / "texto").mkdir(parents=True)
        man = {"docs": []}
        for i, corpo in enumerate(textos):
            (p / "texto" / f"{i:03d}.txt").write_text(corpo, encoding="utf-8")
            man["docs"].append({"i": i, "titulo": f"D{i}", "texto": f"texto/{i:03d}.txt"})
        (p / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return base


TEOR = "[X] (tipo: despacho)\n\nTeor real do documento, com folga acima do piso de 40 chars."
VAZIO = "[X] (tipo: despacho)\n\n"


def test_separa_integro_parcial_sem_teor_e_sem_indice(tmp_path):
    base = _acervo(tmp_path, {
        "aaa": [TEOR, TEOR, TEOR],
        "bbb": [TEOR, VAZIO, VAZIO, VAZIO, VAZIO],   # 1 de 5 → abaixo de 60%
        "ccc": [VAZIO, VAZIO],
    })
    (base / "ddd").mkdir()
    (base / "ddd" / "manifest.json").write_text(json.dumps({"docs": []}), encoding="utf-8")
    e = CC._estado_do_acervo(base)
    assert e == {"integro": 1, "parcial": 1, "sem_teor": 1, "sem_docs": 1}


def test_pasta_de_quarentena_nao_conta(tmp_path):
    """`_orfaos_residuo/` e `_truncados/` são quarentena, não acervo — contá-las inflaria o
    denominador com o que a casa já afastou de propósito."""
    base = _acervo(tmp_path, {"aaa": [TEOR, TEOR], "_orfaos_residuo": [VAZIO]})
    assert CC._estado_do_acervo(base)["sem_teor"] == 0


def test_sem_base_devolve_indisponivel_nunca_zero(tmp_path):
    r = CC.medir(db=tmp_path / "nao_existe.db", acervo=tmp_path)
    assert r["ok"] is False and r["indisponivel"] is True
    assert "0%" not in json.dumps(r), "zero afirmaria cobertura nula onde não houve medição"
