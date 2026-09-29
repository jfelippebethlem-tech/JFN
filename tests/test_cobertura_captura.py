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
    # `teto_de_coleta` entrou em 2026-08-05: arquivo do CACHE parado em EXATAMENTE 40 documentos
    # é corte, não processo completo — o painel dizia 1.941 íntegros enquanto o motor recusava 176
    # deles. Nenhum dos quatro deste cenário tem 40 docs, então o balde novo fica em zero.
    assert e == {"integro": 1, "parcial": 1, "sem_teor": 1, "sem_docs": 1, "teto_de_coleta": 0}


def test_pasta_de_quarentena_nao_conta(tmp_path):
    """`_orfaos_residuo/` e `_truncados/` são quarentena, não acervo — contá-las inflaria o
    denominador com o que a casa já afastou de propósito."""
    base = _acervo(tmp_path, {"aaa": [TEOR, TEOR], "_orfaos_residuo": [VAZIO]})
    assert CC._estado_do_acervo(base)["sem_teor"] == 0


def test_sem_base_devolve_indisponivel_nunca_zero(tmp_path):
    r = CC.medir(db=tmp_path / "nao_existe.db", acervo=tmp_path)
    assert r["ok"] is False and r["indisponivel"] is True
    assert "0%" not in json.dumps(r), "zero afirmaria cobertura nula onde não houve medição"


def test_teto_de_coleta_nao_conta_como_integro(tmp_path):
    """O painel dizia 1.941 íntegros enquanto o motor recusava 176 deles.

    Arquivo montado a partir do CACHE do sweep parado em EXATAMENTE 40 documentos é corte, não
    processo completo: medido em 2026-08-05, dos 1.902 arquivos vindos do cache, 176 param em 40
    e ZERO passa disso — e o cache do SEI-170002/000732/2022 registra árvore de **783 documentos
    contra 40 lidos**. Somá-los ao balde de "íntegro" seria repetir no painel o erro que o gate
    de captura cometia.
    """
    import json as _j

    from compliance_agent.reporting.cobertura_captura import _estado_do_acervo

    def _proc(nome: str, n: int, aviso: str | None):
        pasta = tmp_path / nome
        (pasta / "texto").mkdir(parents=True)
        docs = []
        for i in range(n):
            arq = f"{i:03d}.txt"
            (pasta / "texto" / arq).write_text(
                "Teor com mais de quarenta caracteres, para contar como lido de verdade.",
                encoding="utf-8")
            docs.append({"i": i, "titulo": f"Doc {i}", "tipo": "despacho", "texto": f"texto/{arq}"})
        man = {"processo": nome.replace("_", "/", 2), "docs": docs}
        if aviso:
            man["aviso"] = aviso
        (pasta / "manifest.json").write_text(_j.dumps(man), encoding="utf-8")

    _proc("111111_000001_2025", 40, "arquivo montado a partir do CACHE do sweep: contém o TEXTO")
    _proc("111111_000002_2025", 39, "arquivo montado a partir do CACHE do sweep: contém o TEXTO")
    _proc("111111_000003_2025", 40, None)      # outra origem: 40 é só um número

    e = _estado_do_acervo(tmp_path)
    assert e["teto_de_coleta"] == 1
    assert e["integro"] == 2, "39 do cache e 40 de outra origem seguem íntegros"
