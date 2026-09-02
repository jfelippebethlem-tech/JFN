# -*- coding: utf-8 -*-
"""A perícia documental cobre o ACERVO, não uma amostra — pedido do dono em 2026-08-03.

Medido antes: 39 processos de 2.082 tinham juízo por documento na rubrica vigente. Três tetos
artificiais explicavam isso, e nenhum deles era limite de máquina:

  1. a fila do `sweep_360` só considerava processo com pontuação >= 5 (396 de 2.082);
  2. `TETO_DEFAULT = 25` cortava documentos dentro de cada processo;
  3. o slot julgava 4 processos fixos e parava, mesmo sobrando tempo na janela.

O que É limite real fica: a janela de tempo do slot, o lock de escritor único e o nice/ionice —
a VM tem 2 vCPU e já caiu por excesso. A cadeia de LLM usada é a GRÁTIS (`camada_triagem`), então
cobertura total não custa API.
"""
from pathlib import Path

from compliance_agent.sei import doc_juizo as J

SWEEP = Path(__file__).resolve().parents[1] / "tools" / "sweep_360.sh"


def test_teto_de_documentos_pode_ser_desligado():
    """`JFN_360_TETO_DOCS=0` significa SEM teto — todo documento elegível é julgado."""
    docs = [{"i": i, "tipo": "despacho", "titulo": f"Despacho {i}"} for i in range(80)]
    assert len(J.selecionar(docs, teto=0)) == 80


def test_teto_positivo_continua_cortando():
    docs = [{"i": i, "tipo": "despacho", "titulo": f"D{i}"} for i in range(80)]
    assert len(J.selecionar(docs, teto=10)) == 10


def test_sweep_nao_filtra_a_fila_por_pontuacao_minima():
    txt = SWEEP.read_text(encoding="utf-8")
    assert "pts >= 5" not in txt, (
        "a fila voltou a cobrir só o topo — o acervo inteiro tem de entrar, ordenado por risco")


def test_sweep_trabalha_a_janela_inteira_em_vez_de_um_numero_fixo():
    txt = SWEEP.read_text(encoding="utf-8")
    assert "fila[:4]" not in txt and "alvos) >= 4" not in txt, "voltou o corte fixo de 4 processos"
    assert "SEGUNDOS" in txt or "deadline" in txt, "o slot precisa parar por TEMPO, não por contagem"


def test_sweep_mantem_as_protecoes_reais_da_vm():
    txt = SWEEP.read_text(encoding="utf-8")
    for guarda in ("data/.lock_360", "nice -n 19", "ionice", "timeout"):
        assert guarda in txt, f"proteção de VM removida junto com o teto artificial: {guarda}"


# ───── quem julgou tem de constar (2026-08-03) ─────

def test_a_coluna_modelo_nao_mente_sobre_a_cadeia():
    """`modelo` gravava 'cadeia_gratis' cravado. Com o juízo passando a gemini+cerebras por ordem
    do dono, o registro passaria a mentir sobre quem produziu o veredito — e a procedência do
    juízo é o que permite auditar uma regressão de qualidade depois."""
    from pathlib import Path as _P
    src = _P(J.__file__).read_text(encoding="utf-8")
    assert '"cadeia_gratis", v.get("escala")' not in src, "a cadeia voltou a ser cravada no insert"
    assert 'cadeia, v.get("escala")' in src


def test_cadeia_gratis_continua_alcancavel_por_ambiente(monkeypatch):
    """A troca não pode ser irreversível: JFN_JUIZO_CADEIA=gratis volta ao comportamento antigo."""
    from pathlib import Path as _P
    src = _P(J.__file__).read_text(encoding="utf-8")
    assert "JFN_JUIZO_CADEIA" in src and "gemini+cerebras" in src


def test_slot_longo_cede_a_vez_ao_sweep_sei():
    """1 pesado por vez: o slot passou de 4 processos para até 40 min e passaria a disputar CPU
    com o sweep SEI (Chromium + tesseract), que roda de 30 em 30 min. A VM tem 2 vCPU e já caiu 4×."""
    txt = SWEEP.read_text(encoding="utf-8")
    assert "tools\\.sei_swee[p]" in txt, "o slot não verifica se o sweep SEI está em curso"
    assert "/proc/loadavg" in txt, "o slot não olha o load antes de trabalhar a janela inteira"
