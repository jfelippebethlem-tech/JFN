# -*- coding: utf-8 -*-
"""Subsunção auditável — o raciocínio com as juntas à mostra, e o que ele se recusa a montar.

O veredito da casa é `{grau, raciocinio (texto livre), trechos}`. O `raciocinio` é prosa: ninguém
verifica item a item, e o que não se verifica não se corrige. Um parecer que conclui "há indício
porque a exigência é desproporcional" pode estar certo ou pode estar pulando três degraus — e do
lado de fora as duas coisas se parecem.

Três recusas travadas aqui, cada uma corrigindo um modo de falhar:

  1. **Norma que não resolve** em súmula, acórdão confirmado ou base legal não fundamenta —
     citação plausível foi o que a auditoria de 2026-07-27 achou dentro da base curada da casa.
  2. **Fato sem trecho ancorado é REMOVIDO**, não rebaixado. Se sobrarem zero, a subsunção vira
     `nao_aferivel` — nunca "conclusão fraca", que é como raciocínio vazio se disfarça de cauteloso.
  3. **Sem contra-argumento não é raciocínio jurídico, é acusação** — e é a primeira coisa que
     derruba a peça.
"""
from __future__ import annotations

from compliance_agent.knowledge.subsuncao import SCHEMA_PROMPT, montar, render_texto

_DOC = ("3. DA QUALIFICAÇÃO TÉCNICA. A licitante deverá apresentar atestado de capacidade "
        "técnica registrado no CREA com quantitativo mínimo de 80% do objeto, vedado o "
        "somatório de atestados.")


def _dados(**kw):
    d = {
        "norma_dispositivo": "Súmula TCU 263",
        "norma_verbatim": "Para a comprovação da capacidade técnico-operacional das licitantes...",
        "premissa_maior": "a exigência de quantitativo mínimo deve guardar proporção com o objeto",
        "fatos": [{"enunciado": "o edital exige 80% do objeto em atestado",
                   "trecho": "quantitativo mínimo de 80% do objeto",
                   "documento": "Edital 015/2024", "folha": "12", "grau": "A"}],
        "subsuncao": "o percentual excede a praxe aceita de 50%, sem motivação nos autos",
        "contra_argumento": "objeto complexo pode justificar quantitativo maior, se demonstrado",
        "conclusao_enquadra": True,
    }
    d.update(kw)
    return d


# ───────────────────────── caminho feliz ──────────────────────────────────────────────────────

def test_subsuncao_completa_e_aferivel():
    r = montar(_dados(), _DOC)
    assert r["aferivel"] is True and r["conclusao"] == "enquadra"
    assert r["problemas"] == [] and r["n_fatos"] == 1
    assert r["grau_maximo"] == "A"


def test_texto_e_montado_pelo_CODIGO_com_todas_as_pecas():
    t = render_texto(montar(_dados(), _DOC))
    for esperado in ("Norma aplicável", "O que a norma exige", "Fatos apurados",
                     "Subsunção", "Contra-argumento considerado", "Conclusão"):
        assert esperado in t
    assert "fl. 12" in t and "Edital 015/2024" in t


def test_texto_traz_a_ressalva_de_que_nao_tipifica():
    t = render_texto(montar(_dados(), _DOC))
    assert "17-C" in t and "não podem ser presumidos" in t


# ───────────────────────── 1 · norma que não resolve ──────────────────────────────────────────

def test_norma_inexistente_torna_a_subsuncao_nao_aferivel():
    r = montar(_dados(norma_dispositivo="Súmula TCU 9999"), _DOC)
    assert r["aferivel"] is False
    assert any("premissa maior" in p for p in r["problemas"])


def test_acordao_impossivel_e_recusado():
    """9.999/2024 extrapola a série anual de qualquer colegiado — o índice detecta sem tê-lo."""
    r = montar(_dados(norma_dispositivo="Acórdão 9999/2024-Plenário"), _DOC)
    assert r["aferivel"] is False


def test_norma_sem_verbatim_e_recusada():
    """Paráfrase de norma não fundamenta."""
    r = montar(_dados(norma_verbatim=""), _DOC)
    assert any("verbatim" in p for p in r["problemas"])


# ───────────────────────── 2 · fato sem âncora ────────────────────────────────────────────────

def test_fato_com_citacao_inventada_e_REMOVIDO():
    r = montar(_dados(fatos=[{"enunciado": "o gestor admitiu o direcionamento",
                              "trecho": "eu direcionei o certame", "grau": "A"}]), _DOC)
    assert r["n_fatos"] == 0 and r["descartados"]
    assert r["aferivel"] is False


def test_sem_fato_ancorado_vira_NAO_AFERIVEL_nao_conclusao_fraca():
    r = montar(_dados(fatos=[]), _DOC)
    assert r["conclusao"] == "nao_aferivel"
    assert r["subsuncao"].conclusao_enquadra is None


def test_fatos_validos_sobrevivem_ao_descarte_dos_invalidos():
    r = montar(_dados(fatos=[
        {"enunciado": "exigência de 80%", "trecho": "quantitativo mínimo de 80% do objeto",
         "documento": "Edital", "grau": "A"},
        {"enunciado": "inventado", "trecho": "frase que nunca existiu", "grau": "A"},
    ]), _DOC)
    assert r["n_fatos"] == 1 and len(r["descartados"]) == 1
    assert r["aferivel"] is True


def test_descarte_aparece_no_texto_final():
    t = render_texto(montar(_dados(fatos=[
        {"enunciado": "ok", "trecho": "vedado o somatório de atestados", "documento": "E",
         "grau": "A"},
        {"enunciado": "x", "trecho": "frase inexistente", "grau": "A"}]), _DOC))
    assert "descartados por" in t


def test_sem_fonte_documental_os_fatos_entram_MAS_o_texto_declara():
    r = montar(_dados(), "")
    assert r["aferivel"] is True and r["fonte_conferida"] is False
    assert "NÃO foram conferidas" in render_texto(r)


# ───────────────────────── 3 · contra-argumento ───────────────────────────────────────────────

def test_sem_contra_argumento_a_subsuncao_e_recusada():
    r = montar(_dados(contra_argumento=""), _DOC)
    assert r["aferivel"] is False
    assert any("acusação" in p for p in r["problemas"])


def test_sem_o_passo_de_subsuncao_tambem_e_recusada():
    r = montar(_dados(subsuncao=""), _DOC)
    assert any("ponte entre norma e fato" in p for p in r["problemas"])


# ───────────────────────── robustez e contrato ────────────────────────────────────────────────

def test_entrada_vazia_nao_quebra():
    r = montar({}, _DOC)
    assert r["aferivel"] is False and r["conclusao"] == "nao_aferivel"


def test_fato_malformado_e_ignorado_sem_derrubar():
    r = montar(_dados(fatos=[None, "lixo", {}, _dados()["fatos"][0]]), _DOC)
    assert r["n_fatos"] == 1


def test_schema_do_prompt_exige_verbatim_trecho_e_contra_argumento():
    for exigencia in ("norma_verbatim", "trecho", "contra_argumento", "DESCARTADO"):
        assert exigencia in SCHEMA_PROMPT


def test_conclusao_negativa_tambem_e_valida():
    r = montar(_dados(conclusao_enquadra=False), _DOC)
    assert r["conclusao"] == "nao_enquadra"
    assert "NÃO se enquadra" in render_texto(r)
