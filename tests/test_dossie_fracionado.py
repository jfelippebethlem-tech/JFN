# -*- coding: utf-8 -*-
"""Leitura de processo grande demais para o modelo — sem perder a citação.

Medido no acervo (2026-07-28): mediana de 6.295 tokens, mas a cauda vai a 1.847.408 em 291
documentos. Fracionar todo processo seria desperdício; não fracionar a cauda seria truncamento
silencioso. Estes testes travam a decisão medida e, principalmente, a rastreabilidade: um
achado que não diz de qual documento veio não vale nada em peça.

Nada aqui chama IA.
"""
from __future__ import annotations

import json

from compliance_agent.sei import dossie_fracionado as D


def _processo(tmp_path, docs: dict[str, str], titulos: dict | None = None):
    p = tmp_path / "260007_004415_2025"
    (p / "texto").mkdir(parents=True)
    for nome, txt in docs.items():
        (p / "texto" / nome).write_text(txt)
    if titulos is not None:
        (p / "manifest.json").write_text(json.dumps({"docs": [
            {"texto": f"texto/{n}", "titulo": t} for n, t in titulos.items()]}))
    return p


# ── a decisão de fracionar ────────────────────────────────────────────────────────────────

def test_processo_pequeno_e_lido_inteiro(tmp_path):
    """97% do acervo cabe. Fracionar por precaução piora a leitura sem motivo."""
    p = _processo(tmp_path, {"000_a.txt": "x" * 1000, "001_b.txt": "y" * 1000})
    plano = D.planejar("p", p, contexto_modelo=128_000)
    assert plano.cabe_inteiro and len(plano.lotes) == 1


def test_processo_gigante_vira_varios_lotes(tmp_path):
    p = _processo(tmp_path, {f"{i:03d}.txt": "z" * 40_000 for i in range(10)})
    plano = D.planejar("p", p, contexto_modelo=100_000)
    assert not plano.cabe_inteiro and len(plano.lotes) > 1


def test_nenhum_lote_estoura_o_orcamento(tmp_path):
    p = _processo(tmp_path, {f"{i:03d}.txt": "z" * 30_000 for i in range(12)})
    plano = D.planejar("p", p, contexto_modelo=100_000)
    for lote in plano.lotes:
        assert lote.tokens <= plano.orcamento, f"lote {lote.indice} estourou"


def test_orcamento_deixa_margem_para_prompt_e_resposta(tmp_path):
    """Encher a janela até a borda trunca o último documento sem avisar."""
    assert D.orcamento_tokens(100_000) < 100_000


# ── o corte por caractere é a exceção, e é declarado ──────────────────────────────────────

def test_documento_maior_que_o_orcamento_e_cortado_e_o_corte_fica_registrado(tmp_path):
    p = _processo(tmp_path, {"000_gigante.txt": "z" * 900_000})
    plano = D.planejar("p", p, contexto_modelo=100_000)
    assert any(lote.truncado for lote in plano.lotes)
    md = D.cabecalho_md(plano, "modelo/x:free")
    assert "cortado" in md.lower(), "o cabeçalho tem de dizer que houve corte"


def test_corte_nao_perde_texto(tmp_path):
    p = _processo(tmp_path, {"000_gigante.txt": "abcdefghij" * 90_000})
    plano = D.planejar("p", p, contexto_modelo=100_000)
    junto = "".join(d.texto for lote in plano.lotes for d in lote.docs)
    assert len(junto) == 900_000


# ── rastreabilidade: a citação sobrevive ao fracionamento ─────────────────────────────────

def test_prompt_do_lote_identifica_cada_documento(tmp_path):
    p = _processo(tmp_path, {"000_tr.txt": "objeto: manutenção", "001_ata.txt": "sessão"},
                  titulos={"000_tr.txt": "Termo de Referência", "001_ata.txt": "Ata"})
    plano = D.planejar("p", p, contexto_modelo=128_000)
    _, prompt = D.prompt_map(plano.lotes[0])
    assert "[doc 000_tr.txt]" in prompt and "Termo de Referência" in prompt
    assert "[doc 001_ata.txt]" in prompt


def test_sistema_do_map_proibe_inventar_e_proibe_acusar(tmp_path):
    p = _processo(tmp_path, {"000_a.txt": "texto"})
    sistema, _ = D.prompt_map(D.planejar("p", p, contexto_modelo=128_000).lotes[0])
    baixo = sistema.lower()
    assert "nunca invente" in baixo
    assert "não conclua por irregularidade" in baixo
    assert "nunca escreva zero" in baixo


def test_reduce_manda_preservar_citacao_e_registrar_contradicao():
    sistema, roteiro = D.prompt_reduce("SEI-X", ["bloco 1", "bloco 2"])
    assert "[doc" in sistema
    assert "contradição" in sistema.lower()
    assert "Lacunas" in roteiro


# ── cobertura declarada ───────────────────────────────────────────────────────────────────

def test_documento_sem_texto_e_contado_e_denunciado(tmp_path):
    """Dossiê que leu 2 de 5 documentos e não diz isso é pior que nenhum dossiê."""
    p = _processo(tmp_path, {"000_a.txt": "conteúdo", "001_vazio.txt": "",
                             "002_branco.txt": "   "})
    plano = D.planejar("p", p, contexto_modelo=128_000)
    assert plano.n_docs == 1 and plano.docs_vazios == 2
    md = D.cabecalho_md(plano, "modelo/x:free")
    assert "não foram lidos" in md
    assert "ausência de problema" in md


def test_cabecalho_declara_presuncao_de_legitimidade(tmp_path):
    p = _processo(tmp_path, {"000_a.txt": "x"})
    md = D.cabecalho_md(D.planejar("p", p, contexto_modelo=128_000), "modelo/x:free")
    assert "presunção de legitimidade" in md
    assert "hipóteses a verificar" in md


def test_processo_sem_pasta_de_texto_nao_quebra(tmp_path):
    (tmp_path / "vazio").mkdir()
    plano = D.planejar("p", tmp_path / "vazio", contexto_modelo=128_000)
    assert plano.n_docs == 0 and plano.lotes == []


def test_manifest_ilegivel_nao_impede_a_leitura(tmp_path):
    p = _processo(tmp_path, {"000_a.txt": "conteúdo"})
    (p / "manifest.json").write_text("{ não é json")
    assert D.planejar("p", p, contexto_modelo=128_000).n_docs == 1
