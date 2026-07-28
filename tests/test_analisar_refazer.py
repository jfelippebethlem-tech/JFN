# -*- coding: utf-8 -*-
"""Tirar o processo do índice NÃO faz o dossiê ser refeito — e isso enganou a mim.

`analisar()` só chama o gerador quando o arquivo não existe (`if not destino.exists()`), o que
está certo: refazer dossiê custa cota de modelo, e a maioria das reanálises quer apenas
reaplicar as réguas sobre o texto já extraído.

O efeito colateral custou duas horas hoje. Removi 22 processos de `analise_serie.json` para
que fossem RELIDOS com o teto prático de contexto já em vigor; a série os pegou, encontrou os
dossiês antigos em disco, reaproveitou-os e os marcou como analisados de novo. Medido depois:
**0 de 22 tinham dossiê refeito**, com os mesmos bytes e as mesmas citações de antes.

Sem um caminho explícito, quem vier depois repete o engano — inclusive eu. `refazer=True` diz
o que quer: ignore o dossiê em disco e leia de novo.
"""
import pathlib

import tools.sei_analise_em_serie as S


def _cenario(tmp_path, monkeypatch):
    """Dossiê já existente em disco, gerador instrumentado."""
    dossies = tmp_path / "output" / "dossies"   # o caminho REAL que `analisar` usa
    dossies.mkdir(parents=True)
    (dossies / "proc_x.md").write_text("# dossiê antigo\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    chamou = []
    monkeypatch.setattr(S, "VAULT", tmp_path / "vault")
    return dossies, chamou


def test_por_padrao_reaproveita_o_dossie_existente(tmp_path, monkeypatch):
    """O comportamento atual precisa continuar: refazer custa cota."""
    dossies, chamou = _cenario(tmp_path, monkeypatch)
    monkeypatch.setattr("tools.sei_dossie_md.gerar", lambda *a, **k: chamou.append(a))
    S.analisar("proc_x", 0.0, vault=False)
    assert chamou == [], "com o dossiê em disco, não se gasta cota refazendo"


def test_refazer_ignora_o_dossie_em_disco(tmp_path, monkeypatch):
    dossies, chamou = _cenario(tmp_path, monkeypatch)
    monkeypatch.setattr("tools.sei_dossie_md.gerar", lambda *a, **k: chamou.append(a))
    S.analisar("proc_x", 0.0, vault=False, refazer=True)
    assert chamou, "com refazer=True o gerador tem de ser chamado mesmo havendo dossiê"


def test_o_dossie_antigo_e_preservado_ao_refazer(tmp_path, monkeypatch):
    """Sobrescrever sem guardar apagaria a evidência de como a leitura antiga era."""
    dossies, chamou = _cenario(tmp_path, monkeypatch)
    monkeypatch.setattr("tools.sei_dossie_md.gerar", lambda *a, **k: chamou.append(a))
    S.analisar("proc_x", 0.0, vault=False, refazer=True)
    guardados = list((dossies / "_substituidos").glob("proc_x*.md"))
    assert guardados, "o dossiê anterior tem de ficar guardado para comparação"
    assert guardados[0].read_text() == "# dossiê antigo\n"
