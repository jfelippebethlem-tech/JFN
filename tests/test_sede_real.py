"""Verificador de sede real SEM Google/Mapillary — lógica pura.

Doutrina que estes testes travam:
  · ausência de dado NUNCA vira acusação (INDISPONÍVEL ≠ fachada);
  · nenhum sinal isolado condena — veredito nasce de composição;
  · OSM não mapear o prédio ≠ prédio não existe (foi esse o vício do Mapillary);
  · torre comercial ≠ ninho — contagem de prédio é CONTEXTO, nunca prova.

A calibração de 2026-07-23 nasceu de falsos-positivos reais: com peso alto na
coabitação, o detector acusou RIOCARD (R$ 4,18 bi), Telemar, Ampla Energia e
Barcas Rio de serem empresas de fachada. Os testes de regressão abaixo existem
para que isso não volte.
"""
import pytest

from compliance_agent.geo.sede_real import (
    avaliar_sede,
    complemento_e_unidade,
    normalizar_complemento,
    telefone_valido,
)


def _base(**kw):
    p = {
        "cnpj": "11222333000181", "razao": "EMPRESA TESTE LTDA",
        "logradouro": "RUA DAS FLORES", "numero": "100", "complemento": "",
        "bairro": "CENTRO", "cep": "20000000", "uf": "RJ",
        "situacao": "ATIVA", "cnae": "4120400", "data_inicio": "2005-03-01",
        "telefone": None, "email": None,
        "no_predio": 1, "no_predio_terceiros": 0, "na_sala_terceiros": 0,
        "contabilidade_na_sala": 0, "filiais_proprias": 1,
        "com_mesmo_telefone": 1, "com_mesmo_email": 1,
        "osm": None, "cep_coerente": None, "total_recebido": None,
    }
    p.update(kw)
    return p


# ── honestidade: o default é não saber ───────────────────────────────────────

def test_sem_dado_nenhum_e_inapuravel_nao_acusacao():
    r = avaliar_sede(_base(numero="", no_predio=0))
    assert r["veredito"] == "inapuravel"
    assert r["score_suspeita"] == 0


def test_endereco_sem_numero_e_inapuravel():
    r = avaliar_sede(_base(numero="S/N"))
    assert r["veredito"] == "inapuravel"
    assert any(s["id"] == "sem_numero" for s in r["sinais"])


def test_osm_sem_edificacao_com_regiao_NAO_mapeada_nao_acusa():
    """O erro do Mapillary: dado ruim virando falso-positivo."""
    osm = {"apuravel": True, "classe": "sem_edificacao", "regiao_mapeada": False}
    r = avaliar_sede(_base(osm=osm))
    assert not any(s["id"] == "osm_sem_edificacao" for s in r["sinais"])
    assert r["veredito"] != "forte_suspeita"


def test_osm_sem_edificacao_com_regiao_mapeada_acusa():
    osm = {"apuravel": True, "classe": "sem_edificacao", "regiao_mapeada": True}
    r = avaliar_sede(_base(osm=osm))
    assert any(s["id"] == "osm_sem_edificacao" for s in r["sinais"])


def test_osm_indisponivel_nao_gera_sinal_algum():
    r = avaliar_sede(_base(osm={"apuravel": False}))
    assert not any(s["id"].startswith("osm_") for s in r["sinais"])


# ── REGRESSÃO: torre comercial não é ninho ───────────────────────────────────

def test_torre_comercial_sozinha_nunca_condena():
    """RIOCARD: 317 terceiros no prédio e nada mais. Não pode ser acusada."""
    r = avaliar_sede(_base(no_predio_terceiros=317))
    assert r["veredito"] not in {"forte_suspeita", "suspeita"}


def test_empresa_com_rede_propria_e_antiga_resiste_ao_predio_cheio():
    """Telemar/Ampla: 300 vizinhos, mas 270+ estabelecimentos próprios desde 1966."""
    r = avaliar_sede(_base(no_predio_terceiros=299, filiais_proprias=270,
                           data_inicio="1966-08-01"))
    assert r["veredito"] == "sede_provavel"


def test_ninho_e_contexto_e_nao_escala_alto():
    """O peso do prédio é limitado por projeto — 20 ou 300 dá no mesmo."""
    a = avaliar_sede(_base(no_predio_terceiros=20))
    b = avaliar_sede(_base(no_predio_terceiros=300))
    assert a["score_suspeita"] == b["score_suspeita"] <= 10


# ── mesma sala: só complemento de UNIDADE ────────────────────────────────────

def test_mesmo_andar_nao_e_mesma_sala():
    """'ANDAR 2' junta dezenas de empresas legítimas numa torre."""
    r = avaliar_sede(_base(complemento="ANDAR 2", na_sala_terceiros=27))
    assert not any(s["id"] == "mesma_sala" for s in r["sinais"])


def test_mesma_sala_com_unidade_dispara():
    r = avaliar_sede(_base(complemento="BLOCO 001 SALA 721", na_sala_terceiros=6))
    assert any(s["id"] == "mesma_sala" for s in r["sinais"])


@pytest.mark.parametrize("compl,esperado", [
    ("BLOCO 001 SALA 721", True), ("SL 402", True), ("CJ 1502", True),
    ("APTO 107", True), ("1201", True),
    ("ANDAR 2", False), ("PAVMTO4", False), ("LOJA", False),
    ("PARTE", False), ("", False), ("FUNDOS", False),
])
def test_classificacao_de_complemento(compl, esperado):
    assert complemento_e_unidade(compl) is esperado


# ── identificadores: raridade é que dá sentido ───────────────────────────────

@pytest.mark.parametrize("tel,ok", [
    ("2125714476", True), ("2122222222", False), ("2199999999", False),
    ("2100000000", False), ("00", False), ("210", False), ("", False),
])
def test_telefone_lixo_e_descartado(tel, ok):
    assert telefone_valido(tel) is ok


def test_email_raro_e_sinal_forte():
    r = avaliar_sede(_base(email="tathyane@contato.org.br", com_mesmo_email=7))
    s = [x for x in r["sinais"] if x["id"] == "email_compartilhado"]
    assert s and s[0]["peso"] >= 20


def test_email_de_servico_de_massa_nao_acusa():
    """meucnpj@contabilizei.com.br aparece em 16.846 empresas: não diz nada."""
    r = avaliar_sede(_base(email="meucnpj@contabilizei.com.br", com_mesmo_email=16846))
    assert not any(s["id"] == "email_compartilhado" for s in r["sinais"])


def test_email_de_grupo_medio_pesa_pouco():
    r = avaliar_sede(_base(email="fiscpro@enel.com", com_mesmo_email=616))
    assert not any(s["id"] == "email_compartilhado" for s in r["sinais"])


def test_telefone_compartilhado_pesa_menos_que_email():
    tel = avaliar_sede(_base(telefone="2125714476", com_mesmo_telefone=7))
    mail = avaliar_sede(_base(email="a@b.org", com_mesmo_email=7))
    assert mail["score_suspeita"] > tel["score_suspeita"]


# ── composição ───────────────────────────────────────────────────────────────

def test_contabilidade_na_sala_e_sinal():
    r = avaliar_sede(_base(complemento="SALA 302", na_sala_terceiros=4,
                           contabilidade_na_sala=2))
    assert any(s["id"] == "contabilidade_na_sala" for s in r["sinais"])


def test_complemento_residencial_e_sinal():
    r = avaliar_sede(_base(complemento="APT 107"))
    assert any(s["id"] == "complemento_residencial" for s in r["sinais"])


def test_cep_incoerente_e_sinal_forte():
    r = avaliar_sede(_base(cep_coerente=False))
    assert any(s["id"] == "cep_incoerente" for s in r["sinais"])


def test_composicao_condena_e_sinal_isolado_nao():
    isolado = avaliar_sede(_base(no_predio_terceiros=80))
    assert isolado["veredito"] != "forte_suspeita"
    composto = avaliar_sede(_base(
        no_predio_terceiros=80, complemento="SALA 721", na_sala_terceiros=6,
        contabilidade_na_sala=1, email="a@b.c", com_mesmo_email=7,
        telefone="2125714476", com_mesmo_telefone=7,
        osm={"apuravel": True, "classe": "residencial", "regiao_mapeada": True}))
    assert composto["veredito"] == "forte_suspeita"


# ── substância ───────────────────────────────────────────────────────────────

def test_unica_no_predio_e_antiga_indica_sede_real():
    r = avaliar_sede(_base(
        no_predio_terceiros=0, data_inicio="1998-05-10",
        osm={"apuravel": True, "classe": "comercial", "regiao_mapeada": True},
        cep_coerente=True))
    assert r["veredito"] == "sede_provavel"
    assert r["score_substancia"] > 0


def test_substancia_nao_apaga_suspeita_forte():
    """As duas escalas convivem e ficam visíveis no laudo."""
    r = avaliar_sede(_base(
        no_predio_terceiros=80, complemento="SALA 721", na_sala_terceiros=6,
        email="a@b.c", com_mesmo_email=7,
        osm={"apuravel": True, "classe": "comercial", "regiao_mapeada": True}))
    assert r["score_suspeita"] > 0 and r["score_substancia"] > 0
    assert r["veredito"] != "sede_provavel"


# ── normalização de complemento ──────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("      BLOCO 001 SALA 721", "BLOCO 001;SALA 721"),
    ("BLOCO 03;SALA 3", "bloco 03 sala 3"),
    ("SL 402", "SL  402  "),
])
def test_complementos_equivalentes_normalizam_igual(a, b):
    assert normalizar_complemento(a) == normalizar_complemento(b)


def test_complemento_vazio_nao_agrupa():
    assert normalizar_complemento("") == ""
    assert normalizar_complemento("   ") == ""


def test_veredito_sempre_declara_apuravel():
    for p in (_base(), _base(numero=""), _base(no_predio_terceiros=80)):
        assert "apuravel" in avaliar_sede(p)
