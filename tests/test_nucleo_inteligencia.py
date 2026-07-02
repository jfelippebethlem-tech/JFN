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

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Isola o estado de runtime do Núcleo (memória pericial etc.) — sem isto os
# testes do adaptador escreveriam em data/nucleo_memoria.db de produção.
_TMP = Path(tempfile.mkdtemp(prefix="nucleo_int_"))
os.environ["NUCLEO_MEMORIA_DB"] = str(_TMP / "mem.db")
os.environ["NUCLEO_EVOLUCAO_FILE"] = str(_TMP / "evo.json")
os.environ["NUCLEO_PARAMS_FILE"] = str(_TMP / "params.json")
os.environ["NUCLEO_FEEDBACK_FILE"] = str(_TMP / "fb.json")
os.environ["NUCLEO_CASOS_OURO"] = str(_TMP / "ouro.json")

from compliance_agent.nucleo import parametros as P
from compliance_agent.nucleo.dossie import (
    Contratacao, Dossie, Fornecedor, cnpj_valido, para_reais, para_data,
)
from compliance_agent.nucleo.extracao_robusta import Campo, extrair
from compliance_agent.nucleo.indicadores import avaliar_todos
from compliance_agent.nucleo.nucleo import periciar
from compliance_agent.nucleo.scoring import pontuar

import pytest


@pytest.fixture(autouse=True)
def _repina_env(monkeypatch, tmp_path):
    # Na coleta o pytest importa TODOS os arquivos de teste da suíte, e o
    # último a setar os.environ vence — repina a cada teste. Aqui nenhum teste
    # depende de memória persistida entre testes, então cada um ganha um
    # diretório zerado (tmp_path) e não polui os vizinhos.
    monkeypatch.setenv("NUCLEO_MEMORIA_DB", str(tmp_path / "mem.db"))
    monkeypatch.setenv("NUCLEO_EVOLUCAO_FILE", str(tmp_path / "evo.json"))
    monkeypatch.setenv("NUCLEO_PARAMS_FILE", str(tmp_path / "params.json"))
    monkeypatch.setenv("NUCLEO_FEEDBACK_FILE", str(tmp_path / "fb.json"))
    monkeypatch.setenv("NUCLEO_CASOS_OURO", str(tmp_path / "ouro.json"))


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


# ── Adaptador banco → Dossiê (pula se SQLAlchemy ausente) ────────────────────

def _tem_sqlalchemy() -> bool:
    try:
        import sqlalchemy  # noqa: F401
        from compliance_agent.database import models  # noqa: F401
        return True
    except Exception:
        return False


def test_adaptador_db_end_to_end():
    if not _tem_sqlalchemy():
        return  # ambiente sem ORM: teste não aplicável, conta como pass
    from datetime import date as _date
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from compliance_agent.database.models import Base, Empresa, Contrato
    from compliance_agent.nucleo.adaptador_db import periciar_contrato

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    emp = Empresa(cnpj="11222333000181", razao_social="XPTO LTDA",
                  data_abertura=_date(2024, 2, 1), capital_social=5000, situacao="ATIVA")
    s.add(emp); s.flush()
    ctr = Contrato(numero="CT-1", objeto="reforma predial", empresa_id=emp.id,
                   orgao_contrat="ORG", modalidade="dispensa", valor_total=8_000_000,
                   data_assinatura=_date(2024, 5, 20), fonte="pncp")
    s.add(ctr); s.commit()
    laudo = periciar_contrato(s, ctr.id)
    assert laudo is not None
    assert "IND-EMP-01" in {a.indicador_id for a in laudo.veredito.achados}


def _sessao_ob_memoria():
    """Sessão in-memory com OBs cuja categoria real vive em tipo_ob (dado TFE)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from compliance_agent.database.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_periciar_ob_categoria_vem_do_tipo_ob():
    """No dado TFE real, `categoria` guarda o marcador de fonte ('tfe_ob') e a
    categoria de verdade vive em `tipo_ob` — o adaptador precisa saber disso."""
    if not _tem_sqlalchemy():
        return
    from compliance_agent.database.models import OrdemBancaria
    from compliance_agent.nucleo.adaptador_db import periciar_ob

    s = _sessao_ob_memoria()
    ob = OrdemBancaria(numero_ob="2026OB00001", data_emissao=date(2026, 5, 1),
                       ug_codigo="133100", favorecido_cpf="11222333000181",
                       valor=126.0, tipo_ob="Diárias / Viagens a serviço",
                       categoria="tfe_ob")
    s.add(ob); s.commit()
    laudo = periciar_ob(s, ob)
    assert laudo.dossie.contratacao.categoria == "diárias"

    ob2 = OrdemBancaria(numero_ob="2026OB00002", data_emissao=date(2026, 5, 1),
                        ug_codigo="133100", favorecido_cpf="11222333000181",
                        valor=500.0, tipo_ob="Outros / a classificar",
                        categoria="tfe_ob")
    s.add(ob2); s.commit()
    # "Outros" não é categoria — não pode contaminar a referência aprendida.
    assert periciar_ob(s, ob2).dossie.contratacao.categoria == ""


def test_periciar_ob_alimenta_e_consome_memoria():
    """A inteligência progressiva tem de valer no fluxo REAL (Yoda/ciclo):
    perícias de OB alimentam a memória e a referência aprendida dispara a
    superfaturada seguinte — sem ninguém informar preço de mercado."""
    if not _tem_sqlalchemy():
        return
    from compliance_agent.database.models import OrdemBancaria
    from compliance_agent.nucleo import memoria_pericial
    from compliance_agent.nucleo.adaptador_db import periciar_ob

    s = _sessao_ob_memoria()
    for i, v in enumerate([1_000_000, 1_100_000, 950_000, 1_050_000,
                           1_020_000, 980_000]):
        ob = OrdemBancaria(numero_ob=f"2026OB1000{i}", data_emissao=date(2026, 3, 1),
                           ug_codigo="290100", ug_nome="SES-RJ",
                           favorecido_cpf="11222333000181", valor=v,
                           tipo_ob="Saúde", categoria="tfe_ob")
        s.add(ob); s.commit()
        periciar_ob(s, ob)

    perfil = memoria_pericial.perfil_fornecedor("11222333000181")
    assert perfil.total_pericias == 6          # registrou sem dupla contagem

    suspeita = OrdemBancaria(numero_ob="2026OB19999", data_emissao=date(2026, 4, 1),
                             ug_codigo="290100", ug_nome="SES-RJ",
                             favorecido_cpf="11222333000181", valor=5_000_000,
                             tipo_ob="Saúde", categoria="tfe_ob")
    s.add(suspeita); s.commit()
    laudo = periciar_ob(s, suspeita)
    assert "IND-SUP-01" in {a.indicador_id for a in laudo.veredito.achados}
    assert "memória pericial" in laudo.fontes.get("referencia_categoria", "")


def test_doacoes_do_fornecedor_filtra_no_sql():
    """Com 542 mil doações na base real, filtrar em Python depois de um
    limit(500) cego = indicador de quid pro quo morto. O filtro tem de ser SQL."""
    if not _tem_sqlalchemy():
        return
    from compliance_agent.database.models import DoacaoEleitoral
    from compliance_agent.nucleo.adaptador_db import _doacoes_do_fornecedor

    s = _sessao_ob_memoria()
    # 600 doações de terceiros ANTES da doação que interessa
    for i in range(600):
        s.add(DoacaoEleitoral(cpf_cnpj_doador=f"99{i:09d}", valor=100.0,
                              data_doacao=date(2024, 8, 1), nome_candidato="X"))
    s.add(DoacaoEleitoral(cpf_cnpj_doador="11222333000181", valor=50_000.0,
                          data_doacao=date(2024, 8, 15), nome_candidato="FULANO"))
    # filial da mesma raiz também conta
    s.add(DoacaoEleitoral(cpf_cnpj_doador="11222333000262", valor=20_000.0,
                          data_doacao=date(2024, 9, 1), nome_candidato="FULANO"))
    s.commit()
    doacoes = _doacoes_do_fornecedor(s, "11222333000181")
    assert len(doacoes) == 2
    assert {d["valor"] for d in doacoes} == {50_000.0, 20_000.0}


def test_periciar_ob_identificador_sem_numero():
    """OB sem numero_ob ganha identificador estável 'ob:<id>' (dedup do ciclo)."""
    if not _tem_sqlalchemy():
        return
    from compliance_agent.database.models import OrdemBancaria
    from compliance_agent.nucleo.adaptador_db import periciar_ob

    s = _sessao_ob_memoria()
    ob = OrdemBancaria(numero_ob=None, data_emissao=date(2026, 5, 1),
                       ug_codigo="133100", favorecido_cpf="11222333000181",
                       valor=1000.0, tipo_ob="Saúde", categoria="tfe_ob")
    s.add(ob); s.commit()
    laudo = periciar_ob(s, ob)
    assert laudo.dossie.contratacao.identificador == f"ob:{ob.id}"


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
