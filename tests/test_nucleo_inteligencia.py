"""
Testes do Núcleo de Inteligência Progressiva.

Provam que a perícia é determinística e correta SEM nenhuma IA: cada indicador
dispara (ou não) conforme os dados, e a extração robusta blinda a saída de uma
IA fraca simulada. Rodável offline, só stdlib + o pacote.

    python -m pytest tests/test_nucleo_inteligencia.py -q
    # ou sem pytest:
    python tests/test_nucleo_inteligencia.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_agent.nucleo import parametros as P
from compliance_agent.nucleo.dossie import (
    Contratacao, Dossie, Fornecedor, cnpj_valido, para_reais, para_data,
)
from compliance_agent.nucleo.extracao_robusta import Campo, extrair
from compliance_agent.nucleo.indicadores import avaliar_todos
from compliance_agent.nucleo.nucleo import periciar
from compliance_agent.nucleo.scoring import pontuar


# ── Validadores determinísticos ──────────────────────────────────────────────

def test_cnpj_valido():
    assert cnpj_valido("11.222.333/0001-81")   # CNPJ válido conhecido
    assert not cnpj_valido("11.222.333/0001-00")
    assert not cnpj_valido("00000000000000")
    assert not cnpj_valido("123")


def test_para_reais_formatos_br():
    assert para_reais("R$ 1.234.567,89") == 1234567.89
    assert para_reais("59.906,02") == 59906.02
    assert para_reais("1234.5") == 1234.5
    assert para_reais("texto sem numero") is None


def test_para_data_formatos():
    assert para_data("2024-03-15") == date(2024, 3, 15)
    assert para_data("15/03/2024") == date(2024, 3, 15)
    assert para_data("") is None


# ── Indicadores ──────────────────────────────────────────────────────────────

def test_empresa_recente_dispara():
    d = Dossie(
        contratacao=Contratacao(valor=2_000_000, data=date(2024, 6, 1),
                                modalidade="dispensa"),
        fornecedor=Fornecedor(cnpj="11.222.333/0001-81",
                              data_abertura=date(2024, 3, 1),   # 92 dias antes
                              capital_social=1_000),
    )
    achados = avaliar_todos(d)
    ids = {a.indicador_id for a in achados}
    assert "IND-EMP-01" in ids
    emp = next(a for a in achados if a.indicador_id == "IND-EMP-01")
    assert emp.confianca >= 0.85  # capital baixíssimo eleva a confiança
    assert any("14.133" in b for b in emp.base_legal)


def test_empresa_antiga_nao_dispara():
    d = Dossie(
        contratacao=Contratacao(valor=2_000_000, data=date(2024, 6, 1)),
        fornecedor=Fornecedor(cnpj="11.222.333/0001-81",
                              data_abertura=date(2010, 1, 1),
                              capital_social=5_000_000),
    )
    ids = {a.indicador_id for a in avaliar_todos(d)}
    assert "IND-EMP-01" not in ids


def test_fracionamento_dispara():
    base = date(2024, 5, 1)
    hist = [
        Contratacao(identificador="E-2", valor=49_000, data=date(2024, 5, 20),
                    modalidade="dispensa"),
        Contratacao(identificador="E-3", valor=48_000, data=date(2024, 6, 10),
                    modalidade="dispensa"),
    ]
    d = Dossie(
        contratacao=Contratacao(identificador="E-1", valor=48_500, data=base,
                                modalidade="dispensa"),
        fornecedor=Fornecedor(cnpj="11.222.333/0001-81"),
        historico_orgao_fornecedor=hist,
    )
    achados = avaliar_todos(d)
    assert "IND-FRAC-01" in {a.indicador_id for a in achados}


def test_aditivo_excessivo_dispara():
    d = Dossie(
        contratacao=Contratacao(valor=1_000_000, aditivos_valor=300_000,
                                aditivos_qtd=1, data=date(2024, 1, 1)),
        fornecedor=Fornecedor(cnpj="11.222.333/0001-81"),
    )
    achados = avaliar_todos(d)
    adt = next((a for a in achados if a.indicador_id == "IND-ADT-01"), None)
    assert adt is not None and adt.severidade == "alta"


def test_superfaturamento_estatistico():
    d = Dossie(
        contratacao=Contratacao(valor=500_000, data=date(2024, 1, 1),
                                categoria="saúde"),
        fornecedor=Fornecedor(cnpj="11.222.333/0001-81"),
        referencia_categoria={"mediana": 100_000, "desvio_padrao": 50_000},
    )
    achados = avaliar_todos(d)
    assert "IND-SUP-01" in {a.indicador_id for a in achados}


def test_quid_pro_quo_dispara():
    d = Dossie(
        contratacao=Contratacao(valor=10_000_000, data=date(2024, 6, 1)),
        fornecedor=Fornecedor(
            cnpj="11.222.333/0001-81",
            doacoes_eleitorais=[{"valor": 50_000, "data": "2023-08-01",
                                 "candidato": "Fulano"}],
        ),
    )
    achados = avaliar_todos(d)
    assert "IND-QPQ-01" in {a.indicador_id for a in achados}


def test_sancionado_dispara_alta_confianca():
    d = Dossie(
        contratacao=Contratacao(valor=100_000, data=date(2024, 1, 1)),
        fornecedor=Fornecedor(cnpj="11.222.333/0001-81", sancionado=True),
    )
    san = next((a for a in avaliar_todos(d) if a.indicador_id == "IND-SAN-01"), None)
    assert san is not None and san.confianca >= 0.9


def test_dossie_limpo_nao_dispara_nada():
    d = Dossie(
        contratacao=Contratacao(valor=80_000, data=date(2024, 1, 1),
                                modalidade="pregão", propostas_validas=5,
                                prazo_edital_dias=15),
        fornecedor=Fornecedor(cnpj="11.222.333/0001-81",
                              data_abertura=date(2005, 1, 1),
                              capital_social=2_000_000),
    )
    assert avaliar_todos(d) == []


# ── Score / matriz TCU ───────────────────────────────────────────────────────

def test_score_sobe_com_severidade_e_valor():
    d = Dossie(
        contratacao=Contratacao(valor=20_000_000, data=date(2024, 6, 1),
                                modalidade="dispensa"),
        fornecedor=Fornecedor(cnpj="11.222.333/0001-81",
                              data_abertura=date(2024, 5, 1), capital_social=100,
                              sancionado=True),
    )
    v = pontuar(avaliar_todos(d), valor_contrato=20_000_000)
    assert v.classificacao in ("alto", "crítico")
    assert v.risco_score >= 48
    assert v.base_legal  # citação consolidada não-vazia


def test_score_zero_sem_achados():
    v = pontuar([], valor_contrato=1_000_000)
    assert v.risco_score == 0.0 and v.classificacao == "baixo"


# ── Extração robusta com IA fraca simulada ───────────────────────────────────

def test_extracao_repara_json_sujo():
    # IA fraca que devolve JSON embrulhado em texto e markdown.
    def llm_ruim(prompt, system):
        return ('Claro! Aqui está:\n```json\n'
                '{"objeto": "aquisição de ambulâncias", '
                '"valor": "R$ 2.500.000,00", "cnpj_vencedor": "11.222.333/0001-81"}\n```')
    campos = [
        Campo("objeto", "texto", "objeto"),
        Campo("valor", "reais", "valor", critico=True),
        Campo("cnpj_vencedor", "cnpj", "cnpj", critico=True),
    ]
    res = extrair("edital...", campos, llm_ruim, votos_criticos=1)
    assert res.dados["valor"] == 2_500_000.0
    assert res.dados["cnpj_vencedor"] == "11222333000181"
    assert res.dados["objeto"].startswith("aquisição")


def test_extracao_rejeita_cnpj_invalido():
    def llm(prompt, system):
        return '{"cnpj_vencedor": "11.222.333/0001-00"}'  # dígito verificador errado
    campos = [Campo("cnpj_vencedor", "cnpj", "cnpj", critico=True)]
    res = extrair("x", campos, llm, votos_criticos=1)
    assert "cnpj_vencedor" not in res.dados
    assert "cnpj_vencedor" in res.faltando


def test_extracao_votacao_dilui_erro():
    # Modelo que erra 1 vez e acerta 2 no valor crítico.
    respostas = iter([
        '{"valor": "R$ 999,00"}',        # 1ª passada (erro)
        '{"valor": "R$ 1.000.000,00"}',  # voto
        '{"valor": "R$ 1.000.000,00"}',  # voto
    ])
    def llm(prompt, system):
        return next(respostas)
    campos = [Campo("valor", "reais", "valor", critico=True)]
    res = extrair("x", campos, llm, votos_criticos=3, max_reparos=0)
    assert res.dados["valor"] == 1_000_000.0


def test_extracao_ia_indisponivel_nao_quebra():
    def llm(prompt, system):
        raise RuntimeError("429 rate limit")
    campos = [Campo("valor", "reais", "valor", critico=True)]
    res = extrair("x", campos, llm, votos_criticos=1)
    assert res.dados == {} and res.faltando == ["valor"]
    assert any("indisponível" in w for w in res.avisos)


# ── Orquestrador end-to-end ──────────────────────────────────────────────────

def test_periciar_end_to_end_sem_ia():
    laudo = periciar(
        contratacao={"valor": 5_000_000, "data": "2024-06-01",
                     "modalidade": "dispensa", "categoria": "saúde"},
        fornecedor={"cnpj": "11.222.333/0001-81", "data_abertura": "2024-04-01",
                    "capital_social": 500},
        referencia_categoria={"mediana": 1_000_000, "desvio_padrao": 400_000},
    )
    assert laudo.veredito.classificacao in ("alto", "crítico")
    assert laudo.veredito.achados
    d = laudo.para_dict()
    assert d["base_legal"] and "achados" in d
    assert "LAUDO" in laudo.texto()


def test_periciar_usa_ia_para_campos_faltantes():
    def llm(prompt, system):
        return ('{"valor": "R$ 3.000.000,00", "modalidade": "dispensa", '
                '"cnpj_vencedor": "11.222.333/0001-81"}')
    laudo = periciar(
        contratacao={"data": "2024-06-01", "categoria": "obras"},
        fornecedor={"data_abertura": "2024-05-15", "capital_social": 1000},
        documento_edital="Edital de dispensa para reforma...",
        llm_fn=llm,
    )
    # A IA preencheu valor/cnpj; o indicador de empresa recente deve disparar.
    assert laudo.dossie.contratacao.valor == 3_000_000.0
    assert "IND-EMP-01" in {a.indicador_id for a in laudo.veredito.achados}


# ── Parâmetros / calibração ──────────────────────────────────────────────────

def test_parametro_legal_nao_afrouxa():
    import pytest
    with pytest.raises(ValueError):
        P.definir_override("aditivo_limite_frac", 0.10)  # abaixo da lei → recusa


def _run_sem_pytest():
    """Executa os testes sem pytest (fallback), reportando no stdout."""
    import types
    testes = [v for k, v in globals().items()
              if k.startswith("test_") and isinstance(v, types.FunctionType)]
    ok = falhas = 0
    for t in testes:
        try:
            # test_parametro_legal_nao_afrouxa depende de pytest.raises
            if t.__name__ == "test_parametro_legal_nao_afrouxa":
                try:
                    P.definir_override("aditivo_limite_frac", 0.10)
                    raise AssertionError("deveria ter recusado")
                except ValueError:
                    pass
            else:
                t()
            print(f"  ok   {t.__name__}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FALHA {t.__name__}: {e}")
            falhas += 1
    print(f"\n{ok} passaram, {falhas} falharam.")
    return falhas == 0


if __name__ == "__main__":
    sys.exit(0 if _run_sem_pytest() else 1)
