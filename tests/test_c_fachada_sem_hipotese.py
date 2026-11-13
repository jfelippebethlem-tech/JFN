from compliance_agent.detectores.c_fachada import _sem_hipotese

BASE = {"capital": "verificado", "porte": "verificado", "recencia": "verificado", "situacao_cadastral": "verificado"}


def test_olhada_e_limpa_vira_descartado_dizendo_o_que_nao_viu():
    r = _sem_hipotese("1", {"cobertura": {**BASE, "endereco_residencial": "INDISPONIVEL (endereço não ingerido)",
                                          "sede_google": "AFASTADO (ROOFTOP)"}})
    assert r.status == "descartado"
    assert "endereco_residencial" in r.motivo_refutacao and "INDISPONÍVEL" in r.motivo_refutacao


def test_sinal_de_outro_card_nao_e_descartado():
    for extra in ({"sede_google": "INDICIO (ROOFTOP)"}, {"veredito_humano": "CONFIRMADO fachada"},
                  {"socio_servidor": "1 sócio(s) servidor(es) (fusão)"}):
        r = _sem_hipotese("1", {"cobertura": {**BASE, **extra}})
        assert r.status == "nao_avaliavel", extra
        assert list(extra)[0] in r.motivo_refutacao


def test_sem_as_basicas_continua_nao_avaliavel():
    r = _sem_hipotese("1", {"cobertura": {"recencia": "verificado", "capital": "INDISPONIVEL"}})
    assert r.status == "nao_avaliavel" and "capital" in r.motivo_refutacao
