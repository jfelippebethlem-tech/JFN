# -*- coding: utf-8 -*-
"""O4.9 — lote de correções jurídicas (plano mestre v2, §4.6). Um par positivo/negativo por item.

Cada regra cita o dispositivo conferido VERBATIM nas cópias com md5 de ~/vault/fontes/juridicas (o trecho está no
docstring do módulo de produção). Sem rede; banco só em arquivo temporário.
"""
from __future__ import annotations

import math
import sqlite3

import pytest

from compliance_agent.detectores.base import ANCORAS


# ── 1. X2 por regime: 8.666 art. 57 II + §4º; 14.133 art. 107; 13.303 art. 71 ──────────────────────────────────────
def test_x2_contagem_de_prorrogacoes_sozinha_e_sinal():
    from compliance_agent.detectores.x2_prorrogacao_perpetua import X2ProrrogacaoPerpetua
    r = X2ProrrogacaoPerpetua().avaliar({"processo": "X", "prorrogacoes": [{"n": i} for i in range(4)]})
    assert r.score == pytest.approx(ANCORAS["medio"])


@pytest.mark.parametrize("regime,anos,esperado", [
    ("L8666", 4.9, 0.0),
    ("L8666", 5.5, ANCORAS["forte"]),       # acima de 60 meses: só pelo §4º
    ("L8666", 6.5, ANCORAS["critico"]),     # acima de 60 + 12
    ("L14133", 8.0, 0.0),                   # lícito: até 10 anos (art. 107)
    ("L14133", 10.5, ANCORAS["critico"]),
    ("L13303", 7.0, ANCORAS["medio"]),      # art. 71 I/II admite prazo maior
    ("INDETERMINADO", 7.0, ANCORAS["medio"]),
    (None, 11.0, ANCORAS["critico"]),       # ilegal nos dois regimes
])
def test_x2_mede_o_tempo_contra_o_prazo_do_regime(regime, anos, esperado):
    from compliance_agent.detectores.x2_prorrogacao_perpetua import X2ProrrogacaoPerpetua
    r = X2ProrrogacaoPerpetua().avaliar({"processo": "X", "tempo_total_anos": anos, "regime": regime})
    assert r.score == pytest.approx(esperado)
    assert r.valores["regime"] == (regime or "INDETERMINADO")


def test_x2_contexto_da_execucao_traz_o_regime_por_contrato():
    from compliance_agent.varredura_execucao_ctx import montar_contexto
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE pcrj_contratos (numero_controle_pncp TEXT, objeto TEXT, orgao_cnpj TEXT, orgao_nome TEXT,"
                " fornecedor_documento TEXT, fornecedor_nome TEXT, valor_global REAL, valor_inicial REAL,"
                " data_assinatura TEXT, vigencia_ini TEXT, vigencia_fim TEXT, num_aditivos INT)")
    con.execute("CREATE TABLE contrato_aditivo (id INTEGER PRIMARY KEY, numero_controle_pncp TEXT, sequencial_termo INT,"
                " numero_termo TEXT, objeto TEXT, valor_acrescido REAL, prazo_aditado_dias INT, vigencia_fim TEXT,"
                " qualif_acrescimo TEXT, qualif_vigencia TEXT, qualif_reajuste TEXT, fundamento_legal TEXT,"
                " data_assinatura TEXT)")
    con.execute("INSERT INTO pcrj_contratos VALUES ('A','limpeza','','','','',1,1,'2019-05-02','2019-05-02',"
                "'2020-05-01',0)")
    con.execute("INSERT INTO pcrj_contratos VALUES ('B','limpeza','','','','',1,1,'2022-05-02','2022-05-02',"
                "'2023-05-01',0)")
    assert montar_contexto(con, "A")["regime"] == "L8666"          # assinado antes de 01/04/2021: art. 190
    assert montar_contexto(con, "B")["regime"] == "INDETERMINADO"  # período de opção, lei não declarada


# ── 2. aditivos só por limites_aditivo (D06 da gestão) ────────────────────────────────────────────────────────────
def _d06(tmp_path, termos):
    from types import SimpleNamespace

    from compliance_agent import governo_couto_regras as G
    db = tmp_path / "m.db"
    m = sqlite3.connect(db)
    m.execute("CREATE TABLE contrato_aditivo (numero_controle_pncp TEXT, numero_termo TEXT, objeto TEXT,"
              " valor_acrescido REAL, data_assinatura TEXT, fundamento_legal TEXT, qualif_acrescimo TEXT,"
              " qualif_vigencia TEXT, qualif_reajuste TEXT, prazo_aditado_dias INT)")
    m.execute("CREATE TABLE pcrj_contratos (numero_controle_pncp TEXT, orgao_nome TEXT, fornecedor_nome TEXT,"
              " fornecedor_documento TEXT, valor_inicial REAL)")
    for i, (obj, acr) in enumerate(termos):
        cn = f"42498600000171-2-{i:06d}/2026"
        m.execute("INSERT INTO pcrj_contratos VALUES (?,?,?,?,?)", (cn, "ESTADO DO RIO DE JANEIRO", "F", "1", 100.0))
        m.execute("INSERT INTO contrato_aditivo VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (cn, "1", obj, acr, "2026-05-01", "", None, None, None, 0))
    m.commit()
    m.close()
    w = sqlite3.connect(":memory:")
    w.execute(f"ATTACH DATABASE '{db}' AS m")
    return G.d06(SimpleNamespace(W=w))


def test_d06_acrescimo_quantitativo_acima_de_25_e_caso(tmp_path):
    assert _d06(tmp_path, [("Acréscimo quantitativo do objeto", 30.0)])["n"] == 1


@pytest.mark.parametrize("obj,acr", [
    ("Reforma de edifício — acréscimo quantitativo", 40.0),   # teto de 50% na reforma (art. 125)
    ("Prorrogação do prazo de vigência por mais 12 meses", 100.0),
    ("Revisão dos valores vigentes — reequilíbrio", 60.0),
])
def test_d06_reforma_prorrogacao_e_reequilibrio_nao_consomem_o_25(tmp_path, obj, acr):
    assert _d06(tmp_path, [(obj, acr)])["n"] == 0


def test_limites_aditivo_regime_do_contrato_e_ato():
    from compliance_agent.limites_aditivo import ato_normativo, regime_aditivo, teto_acrescimo
    assert regime_aditivo("L8666") == "8666" and regime_aditivo("L14065_PANDEMIA") == "8666"
    assert regime_aditivo("L13303") == "13303" and regime_aditivo("INDETERMINADO") is None
    assert "13.303" in ato_normativo("13303") and teto_acrescimo("reforma", regime="13303") == pytest.approx(0.50)
    ambos = ato_normativo(None)
    assert "14.133" in ambos and "8.666" in ambos


def test_x1_cita_o_dispositivo_do_regime():
    from compliance_agent.detectores.x1_crescimento_aditivo import X1CrescimentoAditivo
    ctx = {"processo": "X", "valor_inicial": 100.0, "aditivos": [{"tipo": "valor", "valor": 40.0,
                                                                  "objeto": "acréscimo quantitativo"}]}
    antigo = X1CrescimentoAditivo().avaliar({**ctx, "regime": "L8666"})
    novo = X1CrescimentoAditivo().avaliar({**ctx, "regime": "L14133"})
    assert "8.666" in antigo.valores["ato"] and "14.133" in novo.valores["ato"]
    assert antigo.score == novo.score == pytest.approx(ANCORAS["critico"])   # o teto é o mesmo


# ── 3. inexigibilidade ≠ dispensa (nucleo/indicadores IND-FRAC-01) ─────────────────────────────────────────────
def _dossie(modalidades):
    from datetime import date

    from compliance_agent.nucleo.dossie import Contratacao, Dossie, Fornecedor
    hist = [Contratacao(identificador=f"E-{i}", valor=49_000, data=date(2024, 5, 10 + i), modalidade=m)
            for i, m in enumerate(modalidades[1:])]
    return Dossie(contratacao=Contratacao(identificador="E-0", valor=48_500, data=date(2024, 5, 1),
                                          modalidade=modalidades[0]),
                  fornecedor=Fornecedor(cnpj="11.222.333/0001-81"), historico_orgao_fornecedor=hist)


def test_ind_frac_soma_so_dispensa():
    from compliance_agent.nucleo.indicadores import avaliar_todos
    assert "IND-FRAC-01" in {a.indicador_id for a in avaliar_todos(_dossie(["dispensa"] * 3))}
    assert "IND-FRAC-01" not in {a.indicador_id for a in avaliar_todos(_dossie(["dispensa", "inexigível",
                                                                                "inexigibilidade"]))}


def test_lex_r2_nao_soma_inexigibilidade():
    from compliance_agent.lex_analise_conteudo import _analisar_contratos_tcerj
    base = {"_tipo": "compra_direta", "ano_processo": 2024, "unidade": "UG", "objeto": "material de limpeza"}
    dispensas = [{**base, "valor": 40_000.0, "afastamento": "Dispensa",
                  "enquadramento_legal": "Lei 14.133/2021, Art. 75, II"}] * 2
    inexig = [{**base, "valor": 40_000.0, "afastamento": "Inexigibilidade",
               "enquadramento_legal": "Lei 14.133/2021, Art. 74, I"}] * 2
    r2 = lambda ach: [a for a in ach if a["rf"] == "R2" and a["grav"] >= 3]  # noqa: E731
    assert r2(_analisar_contratos_tcerj(dispensas)[0])
    assert not r2(_analisar_contratos_tcerj(inexig)[0])


# ── 4. ente público pela natureza jurídica, não por lista de raízes (processo_360) ─────────────────────────────
def test_360_sem_lista_de_raizes_e_natureza_decide(tmp_path, monkeypatch):
    from compliance_agent import processo_360 as P
    assert not hasattr(P, "_RAIZES_PUBLICAS")
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE empresas_cadastro (cnpj_basico TEXT, natureza_cod TEXT)")
    con.executemany("INSERT INTO empresas_cadastro VALUES (?,?)", [("42498600", "1236"), ("19088605", "2062")])
    con.commit()
    con.close()
    monkeypatch.setattr(P, "_DB", db)
    P._e_ente_publico.cache_clear()
    try:
        assert P._e_ente_publico("42498600000171") is True     # Estado do RJ, natureza 1236
        assert P._e_ente_publico("19088605000104") is False    # empresa privada, 2062
    finally:
        P._e_ente_publico.cache_clear()


# ── 5. X8 (escopo do art. 111; pago após a vigência é sinal) e X9 (supressão por acordo) ──────────────────────────
def _x8(**kw):
    from compliance_agent.detectores.x8_aditivo_retroativo import X8AditivoRetroativo
    ctx = {"processo": "X", "vigencia_fim": "2025-01-01",
           "aditivos": [{"numero_termo": "1", "data_assinatura": "2025-08-01"}], **kw}
    return X8AditivoRetroativo().avaliar(ctx)


def test_x8_escopo_da_14133_nao_e_contrato_morto():
    assert _x8(regime="L14133", objeto="Obra de reforma da escola estadual").status == "nao_avaliavel"
    # 8.666 + escopo: TCU Ac. 1.674/2014-P — extinção só com a conclusão do objeto → no máximo 'medio'
    assert _x8(regime="L8666", objeto="Obra de reforma da escola estadual").score == pytest.approx(ANCORAS["medio"])
    # serviço contínuo 212 dias depois: teto 'forte' sem prova de dano (TCU Ac. 128/2011-P × 2.032/2009-P)
    r = _x8(regime="L14133", objeto="Serviço de limpeza")
    assert r.score == pytest.approx(ANCORAS["forte"]) and r.valores["teto_forte_sem_dano"] is True


def test_x8_escopo_sem_regime_no_maximo_medio():
    assert _x8(objeto="Construção de muro").score == pytest.approx(ANCORAS["medio"])


def test_x8_pago_apos_a_vigencia_e_sinal_nao_sobe_o_nivel():
    sem = _x8(regime="L8666", vigencia_fim="2025-07-20")          # 12 dias → medio
    com = _x8(regime="L8666", vigencia_fim="2025-07-20", pagamentos=[{"data": "2025-07-25", "valor": 10.0}])
    assert sem.score == com.score == pytest.approx(ANCORAS["medio"])
    assert com.valores["pagamento_no_vacuo_e_sinal"] is True


@pytest.mark.parametrize("regime,anuencia,esperado", [
    ("L8666", True, 0.0),                      # 8.666 art. 65 §2º II: supressão por acordo é lícita
    ("L13303", True, 0.0),                     # 13.303 art. 81 §2º
    ("L8666", None, ANCORAS["medio"]),         # a anuência decide; não está na base
    ("L8666", False, ANCORAS["critico"]),
    ("L14133", None, ANCORAS["forte"]),        # 14.133 sem a ressalva, mas art. 137 §2º I: decisão conservadora
    ("L14133", True, ANCORAS["medio"]),
    ("L14133", False, ANCORAS["critico"]),
    (None, True, ANCORAS["medio"]),
])
def test_x9_supressao_acima_do_teto_por_regime(regime, anuencia, esperado):
    from compliance_agent.detectores.x9_supressao_abusiva import X9SupressaoAbusiva
    r = X9SupressaoAbusiva().avaliar({"processo": "X", "valor_inicial": 100.0, "regime": regime,
                                      "houve_anuencia": anuencia,
                                      "aditivos": [{"tipo": "valor", "valor": -30.0, "objeto": "supressão de itens"}]})
    assert r.score == pytest.approx(esperado)


# ── 6. RP no exercício de origem ──────────────────────────────────────────────────────────────────────────────
def test_anomalias_ob_de_restos_a_pagar_fora_da_soma_do_exercicio():
    pd = pytest.importorskip("pandas")
    from compliance_agent import anomalias

    def flags(tipo):
        con = sqlite3.connect(":memory:")
        anomalias._ddl(con)
        df = pd.DataFrame([{"id": i + 1, "numero_ob": f"2025OB{i:05d}", "favorecido_cpf": "05340639000130",
                            "favorecido_nome": "PRIME LTDA", "ug_codigo": "294200", "data_emissao": "2025-03-10",
                            "exercicio": 2025, "valor": 40_000.0, "tipo_ob": tipo} for i in range(3)])
        anomalias.regras(df, con)
        return [r[0] for r in con.execute("SELECT regra FROM ob_redflag_siafe WHERE regra LIKE 'R_FRAC%'")]
    assert flags("Orçamentária")
    assert flags("RPP") == []


def test_anomalias_teto_e_sempre_do_exercicio(monkeypatch):
    from compliance_agent import anomalias
    monkeypatch.delenv("JFN_LIMITE_DISPENSA", raising=False)
    assert not hasattr(anomalias, "LIMITE_DISPENSA")
    assert anomalias._teto(2019) == pytest.approx(17_600.00)
    assert math.isnan(anomalias._teto("sem exercício"))
    monkeypatch.setenv("JFN_LIMITE_DISPENSA", "1000")
    assert anomalias._teto(2019) == pytest.approx(1000.0)


# ── 7. C7: abrangência por ente (14.133 art. 156 §4º) ───────────────────────────────────────────────────────────
def _c7(**sancao):
    from compliance_agent.detectores.c7_sancionada_contratada import C7SancionadaContratada
    s = {"cadastro": "CEIS", "data_inicio": "2025-01-01", "data_fim": "2027-01-01", **sancao}
    return C7SancionadaContratada().avaliar({"processo": "X", "data_referencia": "2026-03-01", "sancoes": [s]})


def test_c7_impedimento_do_proprio_estado_veda():
    r = _c7(categoria="Impedimento/proibição de contratar com prazo determinado",
            fundamentacao="Lei 14.133/2021, art. 156, III", orgao="SECRETARIA DE ESTADO DE SAUDE", uf="RJ")
    assert r.score == pytest.approx(ANCORAS["critico"]) and r.valores["teste_objetivo"] == "violado"


def test_c7_impedimento_de_outro_ente_nao_veda():
    r = _c7(categoria="Impedimento/proibição de contratar com prazo determinado",
            fundamentacao="Lei 14.133/2021, art. 156, III", orgao="CONTROLADORIA-GERAL DA UNIAO", uf="DF")
    assert r.score == pytest.approx(ANCORAS["medio"]) and r.valores["teste_objetivo"] == "fora_da_abrangencia"


def test_c7_inidoneidade_alcanca_todos():
    r = _c7(categoria="Inidoneidade", fundamentacao="Lei 14.133/2021, art. 156, IV",
            orgao="CONTROLADORIA-GERAL DA UNIAO", uf="DF")
    assert r.valores["teste_objetivo"] == "violado"


def test_c7_orgao_ilegivel_e_nao_aferivel():
    r = _c7(categoria="Impedimento/proibição de contratar com prazo determinado",
            fundamentacao="Lei 10.520/2002, art. 7º", orgao="XYZ", uf="")
    assert r.valores["teste_objetivo"] == "nao_aferivel" and r.score == pytest.approx(ANCORAS["forte"])


# ── 8. "pago > contratado" e valores idênticos são SINAL ─────────────────────────────────────────────────────────
def test_lex_r9_pago_maior_que_contratado_e_sinal():
    from compliance_agent.lex_analise_conteudo import _analisar_contratos_tcerj
    ach, _ = _analisar_contratos_tcerj([{"_tipo": "contrato", "processo": "P", "valor_contrato": 100.0,
                                         "valor_pago": 300.0}])
    r9 = [a for a in ach if a["rf"] == "R9"]
    assert r9 and r9[0]["grav"] == 1 and "SINAL" in r9[0]["obs"]
    ach, _ = _analisar_contratos_tcerj([{"_tipo": "contrato", "processo": "P", "valor_contrato": 100.0,
                                         "valor_pago": 110.0}])
    assert not [a for a in ach if a["rf"] == "R9"]


def test_valores_identicos_nao_e_fracionamento():
    from pathlib import Path

    from compliance_agent import lex_redflags as LR
    src = Path(__file__).resolve().parents[1].joinpath("compliance_agent", "lex_orgao.py").read_text(encoding="utf-8")
    assert '"rf": "S/VALORES-IDENTICOS"' in src and "idênticos" in src
    assert "S/VALORES-IDENTICOS" in LR._RF and "S/VALORES-IDENTICOS" not in LR._RF_DESTINATARIO
