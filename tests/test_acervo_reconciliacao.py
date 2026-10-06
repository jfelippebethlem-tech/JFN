"""Perícia × SIAFE na ficha do Acervo (24/09/2026): a perícia lê o trecho; o SIAFE sabe se houve pagamento."""
from compliance_agent.acervo import reconciliar_pericia_siafe

PER_SEM_OB = {"achados": ["Ausência de Ordem Bancária (OB) no trecho que comprove o pagamento efetivo"],
              "conclusao": "Liquidação de despesa no valor de R$ 1.719.165,00, sem OB no trecho."}


def _obs(*obs):
    lista = [{"data_emissao": d, "valor": v, "status": st} for d, v, st in obs]
    pagas = [x for x in lista if x["status"] == "Contabilizado"]
    return {"n": len(pagas), "total": round(sum(x["valor"] for x in pagas), 2), "lista": lista}


def test_siafe_responde_a_ob_que_a_pericia_nao_viu():
    r = reconciliar_pericia_siafe(PER_SEM_OB, _obs(("15/03/2025", 1_000_000.0, "Contabilizado"),
                                                   ("02/11/2024", 719_165.0, "Contabilizado")))
    ob = next(x for x in r if x["tipo"] == "ob_ausente_no_trecho")
    assert ob["veredito"] == "respondido_pelo_siafe"
    assert "2 OB(s)" in ob["diz"] and "R$ 1.719.165,00" in ob["diz"]
    assert "(02/11/2024 a 15/03/2025)" in ob["diz"]          # ordem cronológica, não de string
    assert "processo, total" in ob["diz"]                    # a vírgula da frase não virou ponto
    liq = next(x for x in r if x["tipo"] == "liquidado_x_pago")
    assert liq["veredito"] == "pago_bate_liquidado"


def test_ob_anulada_nao_responde_pela_pericia():
    r = reconciliar_pericia_siafe(PER_SEM_OB, _obs(("15/03/2025", 1_719_165.0, "Anulado")))
    assert [x["veredito"] for x in r] == ["sem_ob_nas_duas_fontes"]
    assert "Não prova" in r[0]["diz"]


def test_pago_diverge_do_liquidado():
    r = reconciliar_pericia_siafe(PER_SEM_OB, _obs(("15/03/2025", 1_000_000.0, "Contabilizado")))
    liq = next(x for x in r if x["tipo"] == "liquidado_x_pago")
    assert liq["veredito"] == "pago_diverge_liquidado"
    assert "R$ 1.719.165,00" in liq["diz"] and "R$ 1.000.000,00" in liq["diz"]
    assert "diferença de R$ 719.165,00 (41,8%)" in liq["diz"]   # valor pt-BR intacto, percentual com vírgula


def test_pericia_que_nao_fala_de_ob_nao_gera_nada():
    assert reconciliar_pericia_siafe({"achados": ["objeto genérico"]}, _obs(("01/01/2025", 10.0, "Contabilizado"))) == []
    assert reconciliar_pericia_siafe(None, {}) == []
