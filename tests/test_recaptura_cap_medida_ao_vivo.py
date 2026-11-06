# -*- coding: utf-8 -*-
"""Lista estática para um alvo que se move — o processo novo nunca voltava à fila.

`sei_reparar_truncados --cap` devolve à fila os processos cujo texto foi cortado no cap de 20.000
caracteres por documento. A lista de alvos vinha de `data/recaptura_cap21k.json`, **curada uma vez**
em 2026-08-01 (375 processos) e nunca mais regerada.

Medido em 2026-08-04: o acervo tem **2.025 documentos no cap em 446 processos** — a lista cobre
343, ignora **103 novos** e ainda traz 32 já resolvidos. Todo processo capturado depois da
curadoria ficava fora para sempre, e entre eles estava o contrato do SEI-030001/111011/2025, cujo
texto para em 20.000 exatamente onde ficam a assinatura e a data — os dois dados que decidiriam
se o achado "contrato ANTES do parecer" se sustenta.

A medição em tempo de execução se autocorrige: processo já recapturado com o cap novo (60k) não
tem mais documento parado em 20.000 e sai sozinho do conjunto. Some com ele a necessidade da lista
de "prioridade", que existia para não afastar cache fresco por engano.
"""
import json

import tools.sei_reparar_truncados as R


def _acervo(tmp_path, monkeypatch, processos):
    """processos: {tag: [tamanhos de texto]}."""
    base = tmp_path / "data" / "sei_arquivo"
    base.mkdir(parents=True)
    for tag, tamanhos in processos.items():
        pasta = base / tag
        (pasta / "texto").mkdir(parents=True)
        docs = []
        for i, n in enumerate(tamanhos):
            nome = f"{i:03d}_doc.txt"
            corpo = "[Doc] (tipo: outro)\n\n" + ("x" * n)
            (pasta / "texto" / nome).write_text(corpo, encoding="utf-8")
            docs.append({"i": i, "titulo": f"Doc {i}", "tipo": "outro", "texto": f"texto/{nome}"})
        (pasta / "manifest.json").write_text(json.dumps({"docs": docs}), encoding="utf-8")
    monkeypatch.setattr(R, "RAIZ", tmp_path)
    return base


def test_processo_com_documento_no_cap_entra(tmp_path, monkeypatch):
    _acervo(tmp_path, monkeypatch, {"080002_000001_2025": [20_000, 500]})
    assert R.tags_no_cap() == ["080002_000001_2025"]


def test_processo_ja_recapturado_sai_sozinho(tmp_path, monkeypatch):
    """Com o cap novo (60k) o documento passa de 20.000 e o processo deixa de ser alvo — é isto
    que torna a lista de 'prioridade' desnecessária."""
    _acervo(tmp_path, monkeypatch, {"080002_000002_2025": [45_000, 500]})
    assert R.tags_no_cap() == []


def test_ordena_por_quanto_texto_se_perdeu(tmp_path, monkeypatch):
    """Quem perdeu mais documentos volta primeiro — a fila é bounded por `--max`."""
    _acervo(tmp_path, monkeypatch, {
        "080002_000003_2025": [20_000],
        "080002_000004_2025": [20_000, 20_000, 19_999],
    })
    assert R.tags_no_cap()[0] == "080002_000004_2025"


def test_texto_curto_nao_e_confundido_com_corte(tmp_path, monkeypatch):
    _acervo(tmp_path, monkeypatch, {"080002_000005_2025": [100, 19_000]})
    assert R.tags_no_cap() == []


def test_acervo_ausente_nao_levanta(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "RAIZ", tmp_path)
    assert R.tags_no_cap() == []


def test_alvo_DIRIGIDO_atende_processo_que_a_ordenacao_deixaria_no_fim(tmp_path, monkeypatch):
    """Processo com UM documento cortado fica no fim da ordenação por perda e nunca entraria numa
    rodada bounded. Foi o caso do SEI-030001/111011/2025, segundo da fila do fiscal, cujo contrato
    para em 20.000 exatamente onde ficam a assinatura e a data. Refilar à mão (mover cache + zerar
    progresso) é a mesma operação com risco de errar."""
    _acervo(tmp_path, monkeypatch, {
        "030001_111011_2025": [20_000],
        "080002_000009_2025": [20_000, 20_000, 20_000],
    })
    cache = tmp_path / "data" / "sei_cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "cdp_SEI_030001_111011_2025.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(R, "CACHE", cache)
    monkeypatch.setattr(R, "QUARENTENA", cache / "_truncados")
    prog = tmp_path / "prog.json"
    prog.write_text(json.dumps({"feitos": {}}), encoding="utf-8")
    monkeypatch.setattr(R, "PROGRESS", prog)
    r = R.reparar_cap(aplicar=True, max_n=40, tags=["030001_111011_2025"])
    assert r["encontrados"] == 1
    feitos = json.loads(prog.read_text())["feitos"]
    assert feitos["SEI-030001/111011/2025"]["n_docs"] == 0
    assert "080002_000009_2025" not in str(feitos), "o dirigido não pode arrastar os outros"


def test_a_gravacao_do_progresso_faz_MERGE_e_nao_apaga_o_sweep(tmp_path, monkeypatch):
    """O padrão anterior era read-modify-write com MINUTOS entre a leitura e a escrita: a rodada
    lia o progresso, varria o acervo inteiro (a medição do cap leva 1 a 2 minutos) e só então
    gravava o dicionário que tinha em mãos. O sweep escreve no MESMO arquivo o tempo todo — cada
    processo lido é uma entrada nova —, e tudo o que ele gravou nesse intervalo era APAGADO.

    O dano real: apagar a prova de que um processo já fora capturado faz o sweep lê-lo de novo,
    gastando a capacidade que está em anos de atraso.
    """
    prog = tmp_path / "prog.json"
    prog.write_text(json.dumps({"feitos": {"SEI-000000/000001/2020": {"n_docs": 7}}}),
                    encoding="utf-8")
    monkeypatch.setattr(R, "PROGRESS", prog)
    # o "sweep" escreve DEPOIS que a rodada leu o arquivo
    prog.write_text(json.dumps({"feitos": {
        "SEI-000000/000001/2020": {"n_docs": 7},
        "SEI-000000/000002/2020": {"n_docs": 12},   # entrada nova, do sweep
    }}), encoding="utf-8")
    R._gravar_progresso({"SEI-000000/000003/2020": {"n_docs": 0, "tentativas": 0}})
    feitos = json.loads(prog.read_text())["feitos"]
    assert feitos["SEI-000000/000002/2020"]["n_docs"] == 12, "apagou o que o sweep gravou"
    assert feitos["SEI-000000/000003/2020"]["n_docs"] == 0
    assert feitos["SEI-000000/000001/2020"]["n_docs"] == 7


def test_progresso_ilegivel_nao_derruba_a_rodada(tmp_path, monkeypatch):
    prog = tmp_path / "prog.json"
    prog.write_text("{ isto não é json", encoding="utf-8")
    monkeypatch.setattr(R, "PROGRESS", prog)
    R._gravar_progresso({"SEI-000000/000004/2020": {"n_docs": 0}})
    assert json.loads(prog.read_text())["feitos"]["SEI-000000/000004/2020"]["n_docs"] == 0
