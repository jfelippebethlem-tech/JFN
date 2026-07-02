"""
Testes do ciclo de inteligência progressiva (memória + avaliação + loop).

Provam as três propriedades que fazem o autoaprimoramento ser confiável:
  1. SEGURANÇA   — com placar perfeito, o loop reverte TUDO que tentar
                   (nunca "melhora" para pior).
  2. APRENDIZADO — um caso-ouro novo que falha faz o loop encontrar sozinho a
                   calibração que o corrige, e mantê-la.
  3. PROGRESSÃO  — cada perícia registrada melhora a referência de preço usada
                   pelas perícias seguintes.

Offline, sem IA, sem rede.
    python tests/test_nucleo_autoaprimoramento.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Isola TODO o estado de runtime num diretório temporário, antes dos imports
# de módulos que congelam caminhos no import (aprendizado, parametros).
_TMP = Path(tempfile.mkdtemp(prefix="nucleo_test_"))
os.environ["NUCLEO_MEMORIA_DB"] = str(_TMP / "mem.db")
os.environ["NUCLEO_EVOLUCAO_FILE"] = str(_TMP / "evo.json")
os.environ["NUCLEO_PARAMS_FILE"] = str(_TMP / "params.json")
os.environ["NUCLEO_FEEDBACK_FILE"] = str(_TMP / "fb.json")
os.environ["NUCLEO_CASOS_OURO"] = str(_TMP / "ouro.json")

from compliance_agent.nucleo import aprendizado, memoria_pericial, parametros as P

# Módulos que congelam Path no import: redireciona explicitamente (cinto e
# suspensório, caso o import da suíte inteira aconteça antes deste arquivo).
P.ARQUIVO_OVERRIDES = _TMP / "params.json"
aprendizado.ARQUIVO_FEEDBACK = _TMP / "fb.json"

from compliance_agent.nucleo.autoaprimoramento import executar_loop, historico_evolucao
from compliance_agent.nucleo.avaliacao import (
    CasoOuro, adicionar_caso_ouro, avaliar_sistema,
)
from compliance_agent.nucleo.nucleo import periciar

import pytest


@pytest.fixture(autouse=True)
def _repina_env(monkeypatch):
    # Na coleta o pytest importa TODOS os arquivos de teste da suíte, e o
    # último a setar os.environ vence — repina para o _TMP DESTE módulo a
    # cada teste, para não dividir mem.db com as outras suítes do Núcleo.
    monkeypatch.setenv("NUCLEO_MEMORIA_DB", str(_TMP / "mem.db"))
    monkeypatch.setenv("NUCLEO_EVOLUCAO_FILE", str(_TMP / "evo.json"))
    monkeypatch.setenv("NUCLEO_PARAMS_FILE", str(_TMP / "params.json"))
    monkeypatch.setenv("NUCLEO_FEEDBACK_FILE", str(_TMP / "fb.json"))
    monkeypatch.setenv("NUCLEO_CASOS_OURO", str(_TMP / "ouro.json"))


def _limpar_estado():
    for f in ("params.json", "fb.json", "ouro.json", "evo.json"):
        p = _TMP / f
        if p.exists():
            p.unlink()
    db = _TMP / "mem.db"
    if db.exists():
        db.unlink()
    P.recarregar()


# ── 1. SEGURANÇA: placar perfeito → tudo revertido ───────────────────────────

def test_loop_com_placar_perfeito_reverte_tudo():
    _limpar_estado()
    assert avaliar_sistema().f1_global == 1.0
    rel = executar_loop(max_rodadas=1)
    assert rel.placar_final.f1_global == 1.0
    assert rel.mantidos == []            # nada melhorou → nada mantido
    assert rel.revertidos > 0            # mas o loop TENTOU (e reverteu)
    # nenhum override residual no disco
    assert not (_TMP / "params.json").exists() or \
        json.loads((_TMP / "params.json").read_text()) == {}


# ── 2. APRENDIZADO: caso novo falhando → loop acha e mantém a correção ───────

def test_loop_aprende_com_caso_ouro_novo():
    _limpar_estado()
    # Caso real confirmado: quid pro quo com ROI 95x — abaixo do limiar padrão
    # (100x), então HOJE o sistema perde este caso.
    adicionar_caso_ouro(CasoOuro(
        id="ouro_qpq_roi95",
        descricao="Doação seguida de contrato com ROI 95x (caso confirmado)",
        dossie={
            "contratacao": {"valor": 9_500_000, "data": "2024-06-01"},
            "fornecedor": {"cnpj": "11222333000181",
                           "data_abertura": "2010-01-01",
                           "capital_social": 1_000_000,
                           "doacoes_eleitorais": [{"valor": 100_000,
                                                   "data": "2023-10-01",
                                                   "candidato": "Z"}]},
        },
        deve_disparar=["IND-QPQ-01"],
    ))
    antes = avaliar_sistema()
    assert antes.f1_global < 1.0 and antes.perdidos >= 1

    rel = executar_loop(max_rodadas=3)

    # O loop deve ter encontrado a calibração (baixar quid_pro_quo_roi_min)
    # e mantido só porque o placar SUBIU.
    assert rel.placar_final.f1_global > antes.f1_global
    params_mantidos = {m["parametro"] for m in rel.mantidos}
    assert "quid_pro_quo_roi_min" in params_mantidos
    assert P.valor("quid_pro_quo_roi_min") < 100.0
    # E os casos limpos continuam limpos (sem falso alarme novo).
    assert rel.placar_final.falsos_alarmes == 0
    # Diário de evolução registrado (auditabilidade).
    assert historico_evolucao()[-1]["f1_final"] == rel.placar_final.f1_global


def test_loop_nao_toca_parametro_legal():
    _limpar_estado()
    rel = executar_loop(max_rodadas=1)
    tocados = {m["parametro"] for m in rel.mantidos}
    for pid in ("limite_dispensa_compras", "limite_dispensa_obras",
                "aditivo_limite_frac", "teto_remuneratorio_rj"):
        assert pid not in tocados


# ── 3. PROGRESSÃO: cada perícia melhora a referência das próximas ────────────

def test_memoria_referencia_progressiva():
    _limpar_estado()
    # 6 perícias "normais" de saúde alimentam a memória…
    for i, v in enumerate([1_000_000, 1_100_000, 950_000, 1_050_000,
                           1_020_000, 980_000]):
        periciar(
            contratacao={"identificador": f"OB-{i}", "valor": v,
                         "data": "2024-03-01", "categoria": "saúde",
                         "orgao": "SES-RJ", "modalidade": "pregão",
                         "propostas_validas": 5},
            fornecedor={"cnpj": "11222333000181",
                        "data_abertura": "2010-01-01",
                        "capital_social": 2_000_000},
            usar_memoria=True,
        )
    ref = memoria_pericial.obter_referencia("saúde")
    assert ref and 950_000 <= ref["mediana"] <= 1_100_000

    # …então a 7ª perícia, superfaturada, dispara SEM ninguém informar a
    # referência: o sistema aprendeu o preço de mercado sozinho.
    laudo = periciar(
        contratacao={"identificador": "OB-SUSP", "valor": 5_000_000,
                     "data": "2024-04-01", "categoria": "saúde",
                     "orgao": "SES-RJ"},
        fornecedor={"cnpj": "11222333000181", "data_abertura": "2010-01-01",
                    "capital_social": 2_000_000},
        usar_memoria=True,
    )
    assert "IND-SUP-01" in {a.indicador_id for a in laudo.veredito.achados}
    assert "memória pericial" in laudo.fontes.get("referencia_categoria", "")


def test_memoria_amostra_pequena_nao_inventa_referencia():
    _limpar_estado()
    periciar(contratacao={"identificador": "OB-X", "valor": 100_000,
                          "data": "2024-01-01", "categoria": "obras"},
             fornecedor={"cnpj": "11222333000181"},
             usar_memoria=True)
    # 1 amostra < mínimo → sem referência (honestidade estatística).
    assert memoria_pericial.obter_referencia("obras") == {}


def test_perfil_fornecedor_acumula_reincidencia():
    _limpar_estado()
    for i in range(3):
        periciar(
            contratacao={"identificador": f"C-{i}", "valor": 2_000_000,
                         "data": "2024-05-01", "modalidade": "dispensa"},
            fornecedor={"cnpj": "11222333000181",
                        "data_abertura": "2024-03-01", "capital_social": 100},
            usar_memoria=True,
        )
    perfil = memoria_pericial.perfil_fornecedor("11222333000181")
    assert perfil.total_pericias == 3
    assert perfil.criticos_e_altos >= 1
    assert perfil.risco_medio > 0


def test_veredito_propaga_para_feedback():
    _limpar_estado()
    periciar(
        contratacao={"identificador": "OB-CONF", "valor": 2_000_000,
                     "data": "2024-05-01"},
        fornecedor={"cnpj": "11222333000181", "data_abertura": "2024-03-01",
                    "capital_social": 100},
        usar_memoria=True,
    )
    n = memoria_pericial.registrar_veredito("OB-CONF", "confirmado")
    assert n == 1
    precisoes = {p.indicador_id: p for p in aprendizado.precisao_por_indicador()}
    assert precisoes["IND-EMP-01"].confirmados == 1


def _run_sem_pytest():
    import types
    testes = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and isinstance(v, types.FunctionType)]
    ok = falhas = 0
    for t in testes:
        try:
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
