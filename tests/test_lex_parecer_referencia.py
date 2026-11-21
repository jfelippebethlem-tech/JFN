# -*- coding: utf-8 -*-
"""Parecer referência do Lex (20/11/2026) — catracas dos defeitos medidos no golden antigo.

Cada teste prende um defeito que o parecer tinha: grau 🟢 com sinais citados como relevantes no mérito, fonte
dupla para o mesmo fato, contagens que não fechavam, OB do espelho TFE como "pago", numeração fora de ordem,
recomendação genérica sem achado, escalada fabricada por ano parcial, multa estimada sobre o total pago e
camada subjetiva assinada por motor fora da régua. Controle positivo e negativo onde a régua decide.
"""
import re
from collections import OrderedDict

from compliance_agent import lex_fatos as lf
from compliance_agent import lex_parecer as lp
from compliance_agent import lex_subjetiva
from compliance_agent.lex_analise_conteudo import _detectar
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "golden"


def _base(pagas, regularizacoes=(), nao_pagas=()):
    return {"estado": lf.VERIFICADO, "motivo": "", "tipo": "fornecedor", "pagas": list(pagas),
            "regularizacoes": list(regularizacoes), "nao_pagas": list(nao_pagas), "ne": [], "nl": [],
            "coletado_em": "2026-11-20 10:00:00", "fonte": lf.FONTE_OB}


def _ob(n, data, valor, ug="133100"):
    return {"numero_ob": n, "ug_emitente": ug, "data": data, "valor": valor, "exercicio": int(data[:4]),
            "credor": "11222333000181", "nome_credor": "X", "nl": "", "processo": ""}


def test_pagamentos_so_ob_paga_com_valor_e_totais_fecham():
    base = _base([_ob("2023OB1", "2023-03-10", 120000.0), _ob("2025OB7", "2025-02-15", 2400000.0)],
                 regularizacoes=[_ob("2023OB2", "2023-05-02", 0.0)],
                 nao_pagas=[dict(_ob("2025OB6", "2025-02-10", 2400000.0), motivo="devolvida")])
    p = lf.pagamentos(base)
    linhas = [x for b in p["por_ano"].values() for x in b["linhas"]]
    assert p["n_geral"] == len(linhas) == 2                      # OB zero e OB devolvida fora da série paga
    assert p["total_geral"] == sum(x["valor"] for x in linhas) == 2520000.0
    assert p["n_regularizacoes"] == 1
    assert p["fonte"] == lf.FONTE_OB and "TFE" not in p["fonte"]


def test_escalada_ignora_ano_de_inicio_e_exercicio_em_curso():
    # controle NEGATIVO (caso Engeprat): 1 OB no ano de início e o ano em curso não fabricam "+78.838%"
    def ctx(totais, data="2026-11-20"):
        pa = OrderedDict((a, {"total": v, "n": 1, "linhas": [{"data": f"{a}-06-01", "valor": v}]}) for a, v in totais)
        return {"data": data, "pagamentos": {"tem_dados": True, "anos": [a for a, _ in totais], "por_ano": pa,
                                             "hhi": {}, "por_orgao_geral": {}, "n_regularizacoes": 0}}
    neg = _detectar(ctx([(2021, 73_180.52), (2022, 74_684_538.35), (2025, 168_732_475.36), (2026, 57_767_105.55)]))
    assert not any(a["rf"] == "F-ESCALADA" for a in neg)
    # controle POSITIVO: salto real entre exercícios completos
    pos = _detectar(ctx([(2023, 120_000.0), (2024, 300_000.0), (2025, 4_200_000.0)], data="2026-07-06"))
    esc = [a for a in pos if a["rf"] == "F-ESCALADA"]
    assert esc and "2024" in esc[0]["obs"] and "2023 (ano de início da relação)" in esc[0]["obs"]
    assert not any(a["rf"] == "R12" for a in pos)              # salto de pagamento não é "planejamento de fachada"


def test_renumeracao_continua_das_subsecoes():
    md = "## 4. X\n### 4.1 a\n### 4.5 b\n### 4.7 c\n## 5. Y\n### 5.3 d"
    assert lp.renumerar(md) == "## 4. X\n### 4.1 a\n### 4.2 b\n### 4.3 c\n## 5. Y\n### 5.1 d"


def test_golden_secoes_em_ordem_e_sem_contradicao():
    md = (GOLDEN / "lex_parecer_fornecedor.md").read_text(encoding="utf-8")
    secoes = [int(n) for n in re.findall(r"^## (\d+)\. ", md, re.M)]
    assert secoes == list(range(1, len(secoes) + 1)) and secoes[0] == 1
    assert md.index("## 1. SUMÁRIO EXECUTIVO") < md.index("## 3. BASE DE FATOS")
    for sec in secoes:
        subs = [int(m) for m in re.findall(rf"^### {sec}\.(\d+) ", md, re.M)]
        assert subs == list(range(1, len(subs) + 1)), f"subseções da seção {sec} fora de ordem: {subs}"
    # um número, uma fonte: o capital que o quadro usa não aparece INDISPONÍVEL na cobertura da due diligence
    assert "| Capital social | R$ 10.000,00 |" in md and "capital: INDISPONIVEL" not in md
    # OB só do SIAFE
    assert "SIAFE/TFE" not in md
    grau = re.search(r"\*\*Grau de atenção:\*\* (\S+) \*\*(\w+)\*\*", md).group(2)
    n_ind = len(re.findall(r"^#### ", md.split("## 8.")[0], re.M))
    assert (grau == "VERDE") == (n_ind == 0)


def test_sem_achado_nao_lista_mp_cade_cge():
    md = "\n".join(lp.encaminhamento({"achados": [], "exculpatorio": [], "destinatarios": []}))
    assert "Sem achado" in md and "CADE" not in md and "MP-RJ" not in md and "CGE" not in md


def test_sancao_nao_projeta_multa_em_parecer_amarelo():
    an = {"achados": [{"rf": "R4", "grav": 3, "obs": "x"}], "exculpatorio": [{"rf": "R4", "sobrevive": False}],
          "rotulo": "AMARELO", "emoji": "🟡"}
    md = "\n".join(lp._secao_sancao({"pagamentos": {"total_geral": 1e8}}, an))
    assert "Não se propõe sanção" in md and "Multa estimada" not in md


class _P:
    def __init__(self, modelo, dados):
        self.modelo, self.dados, self.texto = modelo, dados, ""


def test_camada_subjetiva_so_opus_da_assinatura(monkeypatch):
    monkeypatch.delenv("JFN_VEREDITO_LLM_DISABLED", raising=False)
    monkeypatch.setenv("JFN_LEX_SUBJETIVA", "1")
    dados = {"juizo": "leitura", "explicacao_inocente": "inocente", "confianca": "media", "diligencias": ["d1"]}
    ok = lex_subjetiva.avaliar("alvo", [], [], [], pensar=lambda *a, **k: _P("claude-opus-5-5", dados))
    assert ok["estado"] == "OPINIÃO" and ok["confianca"] == "média"
    api = lex_subjetiva.avaliar("alvo", [], [], [], pensar=lambda *a, **k: _P("claude-haiku@api", dados))
    assert api["estado"] == "INDISPONÍVEL"                    # API paga / modelo barato não assina a opinião
    nada = lex_subjetiva.avaliar("alvo", [], [], [], pensar=lambda *a, **k: None)
    assert nada["estado"] == "INDISPONÍVEL"
    monkeypatch.setenv("JFN_LEX_SUBJETIVA", "0")
    assert lex_subjetiva.avaliar("alvo", [], [], [])["estado"] == "INDISPONÍVEL"
