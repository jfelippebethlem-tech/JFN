"""
Testes da interface Telegram do Núcleo (comandos determinísticos + roteador NL).

O ponto central: o bot precisa entender o perito SEM depender de LLM.
Cada caso aqui é uma frase real de uso → comando esperado. Offline, sem rede.

    python tests/test_nucleo_telegram.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = Path(tempfile.mkdtemp(prefix="nucleo_tg_"))
os.environ["NUCLEO_MEMORIA_DB"] = str(_TMP / "mem.db")
os.environ["NUCLEO_EVOLUCAO_FILE"] = str(_TMP / "evo.json")
os.environ["NUCLEO_PARAMS_FILE"] = str(_TMP / "params.json")
os.environ["NUCLEO_FEEDBACK_FILE"] = str(_TMP / "fb.json")
os.environ["NUCLEO_CASOS_OURO"] = str(_TMP / "ouro.json")

from compliance_agent.nucleo import telegram_nucleo as tn


# ── Roteador de linguagem natural (o coração anti-"bot burro") ───────────────

def test_nl_pericia_por_cnpj():
    rota = tn.interpretar_texto_livre("pericia o 19.088.605/0001-04 pra mim")
    assert rota == ("/pericia", "19.088.605/0001-04")


def test_nl_pericia_por_nome():
    rota = tn.interpretar_texto_livre("audita a mgs clean")
    assert rota is not None and rota[0] == "/pericia"
    assert "mgs clean" in rota[1]


def test_nl_cnpj_solto_vira_pericia():
    rota = tn.interpretar_texto_livre("19.088.605/0001-04")
    assert rota == ("/pericia", "19.088.605/0001-04")


def test_nl_ob_solta_vira_pericia():
    rota = tn.interpretar_texto_livre("2024OB01234")
    assert rota == ("/pericia", "2024OB01234")


def test_nl_veredito_confirmado():
    rota = tn.interpretar_texto_livre("a 2024OB01234 procede, confirmado")
    assert rota == ("/veredito", "2024OB01234 confirmado")


def test_nl_veredito_descartado():
    rota = tn.interpretar_texto_livre("2024OB01234 era falso alarme")
    assert rota == ("/veredito", "2024OB01234 descartado")


def test_nl_ciclo():
    rota = tn.interpretar_texto_livre("roda o ciclo de autoaprimoramento")
    assert rota == ("/ciclo_nucleo", "")


def test_nl_placar():
    rota = tn.interpretar_texto_livre("quanto aprendeu até agora?")
    assert rota == ("/placar", "")


def test_nl_perfil_fornecedor():
    rota = tn.interpretar_texto_livre(
        "qual o historico do 19.088.605/0001-04?")
    assert rota == ("/fornecedor", "19.088.605/0001-04")


def test_nl_nao_reconhecido_vai_para_llm():
    # Frases genéricas NÃO podem ser sequestradas pelo roteador.
    assert tn.interpretar_texto_livre("bom dia, tudo bem?") is None
    assert tn.interpretar_texto_livre("qual a previsão do tempo?") is None


# ── Handlers (nunca levantam exceção; sempre devolvem texto útil) ────────────

def test_cmd_pericia_sem_args_orienta():
    r = tn.cmd_pericia("")
    assert "/pericia" in r and "CNPJ" in r


def test_cmd_veredito_malformado_orienta():
    r = tn.cmd_veredito("2024OB01234")
    assert "confirmado|descartado" in r


def test_cmd_veredito_ref_inexistente():
    r = tn.cmd_veredito("REF-QUE-NAO-EXISTE confirmado")
    assert "Nenhuma perícia" in r


def test_cmd_placar_offline():
    r = tn.cmd_placar()
    assert "PLACAR" in r and "F1" in r


def test_cmd_fornecedor_sem_historico():
    r = tn.cmd_fornecedor("19.088.605/0001-04")
    assert "sem perícias" in r


def test_cmd_parametros_marca_travados():
    r = tn.cmd_parametros()
    assert "🔒" in r and "🔧" in r and "limite_dispensa_compras" in r


def test_cmd_evolucao_vazio_orienta():
    r = tn.cmd_evolucao()
    assert "ciclo" in r.lower()


def test_fluxo_pericia_veredito_fecha_ciclo():
    """Fluxo completo via 'Telegram': pericia → memória → veredito → feedback."""
    from compliance_agent.nucleo.nucleo import periciar
    from compliance_agent.nucleo import aprendizado, memoria_pericial

    laudo = periciar(
        contratacao={"identificador": "2024OB99999", "valor": 2_000_000,
                     "data": "2024-05-01"},
        fornecedor={"cnpj": "11222333000181", "data_abertura": "2024-03-01",
                    "capital_social": 100},
        usar_memoria=True,
    )
    assert laudo.veredito.achados  # empresa recém-aberta dispara
    # o perito responde pelo Telegram:
    r = tn.cmd_veredito("2024OB99999 confirmado")
    assert "✅" in r
    perfil = memoria_pericial.perfil_fornecedor("11222333000181")
    assert perfil.confirmados == 1
    assert any(p.confirmados >= 1 for p in aprendizado.precisao_por_indicador())


def test_formatacao_laudo_telegram():
    from compliance_agent.nucleo.nucleo import periciar
    laudo = periciar(
        contratacao={"identificador": "OB-FMT", "valor": 18_500_000,
                     "data": "2024-05-20", "modalidade": "dispensa"},
        fornecedor={"cnpj": "11222333000181", "data_abertura": "2024-02-01",
                    "capital_social": 10_000},
    )
    msg = tn._fmt_laudo(laudo, referencia="OB-FMT")
    assert "PERÍCIA — OB-FMT" in msg
    assert "🔴" in msg or "🟡" in msg
    assert "R$ 18.500.000,00" in msg           # padrão brasileiro
    assert "/veredito OB-FMT" in msg           # convite ao feedback
    assert "Lei" in msg or "Art" in msg        # base legal citada


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
