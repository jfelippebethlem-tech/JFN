# -*- coding: utf-8 -*-
"""Conferência BARATA (23/11/2026, dono: "leva a conferência e arquivamento pra VM-2"): o nó pré-confere (lê todo
.txt) e manda o resultado no MANIFESTO; a VM-1 confere md5 + a conta do manifesto + uma amostra pequena relida.
Lote bom entra; md5 divergente e manifesto sem texto vão à quarentena; sem pré-conferência ou com a chave desligada,
vale a conferência completa de sempre."""
from __future__ import annotations

import json

import tools.vm2_conferencia as C
import tools.vm2_lote as L
from tests.test_vm2_conferencia import TEXTO, _isolar, _pasta

P1, P2 = "100000/000101/2025", "100000/000102/2025"
T1, T2 = P1.replace("/", "_"), P2.replace("/", "_")


def _lote(src, procs, pre_por_proc=None):
    """Lote como o nó monta: pré-conferência calculada sobre a pasta do nó (ou a fornecida pelo teste)."""
    processos = {}
    for p in procs:
        t = p.replace("/", "_")
        pre = (pre_por_proc or {}).get(p, C.preconferir(src / t, "ok"))
        processos[p] = {"status": "ok", "juizo": None, **({"preconferencia": pre} if pre else {})}
    return L.montar("integras", {f"arquivo/{p.replace('/', '_')}": src / p.replace("/", "_") for p in procs},
                    processos, {"linhas_log": [f"[2026-11-23 21:00:00]   {p}: ok" for p in procs]})


def _ligar(monkeypatch, modo="barata"):
    monkeypatch.setenv("JFN_VM2_CONFERENCIA", modo)


def test_lote_bom_entra_pela_conferencia_barata(monkeypatch, tmp_path):
    d = _isolar(monkeypatch, tmp_path)
    _ligar(monkeypatch)
    src = tmp_path / "no"
    _pasta(src, T1, n=4)
    base = _lote(src, [P1])                            # o nó pré-confere (lê tudo) ao montar o lote
    lidos = []
    original = C.conferir_integra
    monkeypatch.setattr(C, "conferir_integra", lambda *a, **k: lidos.append(a) or original(*a, **k))
    r = C.importar(base.name)
    assert r["aprovados"] == [P1] and not r["reprovados"]
    assert not lidos                                   # a leitura completa NÃO rodou na VM-1
    assert (d / "sei_arquivo" / T1 / "manifest.json").exists()
    log = (d / "vm2_conferencia.log").read_text(encoding="utf-8")
    assert '"conferencia": "barata"' in log and '"amostra_vm1": "3/3 legíveis"' in log
    assert f"{P1}: ok\n" in (d / "sei_integra_fila.log").read_text(encoding="utf-8")


def test_md5_divergente_vai_para_a_quarentena(monkeypatch, tmp_path):
    d = _isolar(monkeypatch, tmp_path)
    _ligar(monkeypatch)
    src = tmp_path / "no"
    _pasta(src, T1)
    _pasta(src, T2)
    base = _lote(src, [P1, P2])
    (base / f"arquivo/{T2}/texto/001_despacho_1.txt").write_text(TEXTO + " adulterado", encoding="utf-8")
    r = C.importar(base.name)
    assert r["aprovados"] == [P1]
    assert "md5 divergente" in " ".join(r["reprovados"][P2])
    assert not (d / "sei_arquivo" / T2).exists()
    assert (d / "vm2_quarentena" / base.name / f"{T2}.motivo.json").exists()


def test_manifesto_com_teor_e_txt_vazio_e_recusado(monkeypatch, tmp_path):
    """O nó diz "tudo legível" (pré-conferência forjada/defeituosa) e os .txt estão vazios: a conta do manifesto
    (chars ≥ 40 com .txt vazio) e a amostra relida na VM-1 pegam — mesmo com md5 batendo."""
    d = _isolar(monkeypatch, tmp_path)
    _ligar(monkeypatch)
    src = tmp_path / "no"
    p = _pasta(src, T1, n=3)
    pre = C.preconferir(p, "ok")                       # medida com texto…
    for f in (p / "texto").glob("*.txt"):
        f.write_text("", encoding="utf-8")             # …e o lote sai sem texto
    r = C.importar(_lote(src, [P1], {P1: pre}).name)
    assert P1 in r["reprovados"]
    motivos = " ".join(r["reprovados"][P1])
    assert ".txt vazio" in motivos and "amostra relida na VM-1" in motivos
    assert not (d / "sei_arquivo" / T1).exists()


def test_pasta_texto_ausente_e_recusada(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    _ligar(monkeypatch)
    p = _pasta(tmp_path / "no", T1)
    pre = C.preconferir(p, "ok")
    for f in (p / "texto").glob("*.txt"):
        f.unlink()
    ok, motivos, _ = C.conferir_barata(p, "ok", T1, None, pre)
    assert not ok and "pasta texto/ vazia" in motivos


def test_preconferencia_de_outro_manifesto_e_recusada(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    p = _pasta(tmp_path / "no", T1, n=3)
    pre = C.preconferir(p, "ok")
    pre["metricas"]["docs"] = 9
    ok, motivos, _ = C.conferir_barata(p, "ok", T1, None, pre)
    assert not ok and any("não bate com o manifesto" in m for m in motivos)


def test_sem_preconferencia_ou_chave_desligada_vale_a_completa(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    p = _pasta(tmp_path / "no", T1)
    pre = C.preconferir(p, "ok")
    _ligar(monkeypatch)
    assert "conferencia" not in C._conferir_entrega_integra(p, "ok", T1, {"juizo": None})[2]
    _ligar(monkeypatch, "completa")
    assert "conferencia" not in C._conferir_entrega_integra(p, "ok", T1, {"preconferencia": pre})[2]
    _ligar(monkeypatch)
    assert C._conferir_entrega_integra(p, "ok", T1, {"preconferencia": pre})[2]["conferencia"] == "barata"


def test_flag_em_arquivo_liga_e_env_manda(monkeypatch, tmp_path):
    monkeypatch.delenv("JFN_VM2_CONFERENCIA", raising=False)
    monkeypatch.setattr(C, "FLAG_BARATA", tmp_path / ".vm2_conferencia_barata")
    assert not C.barata_ligada()
    (tmp_path / ".vm2_conferencia_barata").touch()
    assert C.barata_ligada()
    monkeypatch.setenv("JFN_VM2_CONFERENCIA", "completa")
    assert not C.barata_ligada()


def test_preconferir_lista_ilegiveis(tmp_path):
    p = _pasta(tmp_path, T1, n=3)
    (p / "texto" / "001_despacho_1.txt").write_text("@@@@ #### 1234 5678 9999 %%%% ----" * 3, encoding="utf-8")
    pre = C.preconferir(p, "ok")
    assert pre["versao"] == C.PRE_VERSAO and pre["ilegiveis"] == ["001_despacho_1.txt"]
    assert json.dumps(pre)                              # vai no MANIFESTO: tem de serializar


def test_referencia_da_vm1_divergente_reprova_na_barata(monkeypatch, tmp_path):
    """A leitura independente continua: o arquivo que a VM-1 já tem diverge do texto entregue ⇒ quarentena."""
    d = _isolar(monkeypatch, tmp_path)
    _pasta(d / "sei_arquivo", T1, texto="Contrato de locação de veículos blindados " * 10)
    novo = _pasta(tmp_path / "no", T1)
    ok, motivos, _ = C.conferir_barata(novo, "ok", T1, None, C.preconferir(novo, "ok"))
    assert not ok and "diverge" in " ".join(motivos)
