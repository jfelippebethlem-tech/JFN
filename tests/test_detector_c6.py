# -*- coding: utf-8 -*-
"""Teste TARGETED do detector C6 — vínculo político-financeiro (doações eleitorais dos sócios), spec V2 do dono.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO (dicts); LLM ausente OU rubrica pré-classificada
injetada (`_rubrica_poder`, sem rede). Cobre: (a) CONFIRMA 'medio' (sócio doou a beneficiário com poder, rubrica
decisor-direto); (b) score NUNCA passa de 0.6 (conservador); (c) DESCARTADO mas REGISTRADO sem vínculo (ausência =
informação); (d) homonímia mitigada por município/CPF; (e) 'sem-poder-sobre-o-contrato' não pontua; (f) sem
QSA/doações → nao_avaliavel.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_c6.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import STATUS_VALIDOS, ANCORAS, ResultadoDetector
from compliance_agent.detectores.c6_vinculo_politico import C6VinculoPolitico


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


def test_c6_identidade():
    det = C6VinculoPolitico()
    assert det.id == "C6"
    assert det.familia == "perfil"
    assert det.peso() == 0.8


# ── (a) CONFIRMA 'medio': sócio doou ≥ R$ 10k a beneficiário com poder (rubrica decisor-direto) ──
def test_c6_confirma_medio_decisor_direto():
    ctx = {
        "processo": "contrato-1",
        "orgao_contratante": "Secretaria de Saúde",
        "qsa": [{"cpf": "12345678900", "nome": "João da Silva", "municipio": "Niterói"}],
        "doacoes": [{
            "doador_cpf": "12345678900", "doador_nome": "João da Silva",
            "beneficiario": "Fulano Gestor", "cargo_beneficiario": "Secretário de Saúde",
            "valor": 25000.0, "ano_eleicao": 2016, "municipio": "Niterói",
        }],
        "data_contrato": "2019-03-01",
        # sem beneficiarios_com_poder → usa a rubrica LLM injetada:
        "_rubrica_poder": {"nivel": "decisor-direto", "trecho": "Secretário de Saúde × Secretaria de Saúde"},
        "irregularidade_no_certame": True,
    }
    r = C6VinculoPolitico().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["medio"]
    assert r.valores["papel"] == "multiplicador_prioridade"
    assert r.valores["vinculos_com_poder"] == 1
    assert r.valores["valor_doado_agregado"] == 25000.0
    assert r.evidencia


# ── (b) score NUNCA passa de 0.6, mesmo com doação enorme + razão retorno/doação alta ──
def test_c6_score_teto_conservador():
    ctx = {
        "processo": "contrato-2",
        "orgao_contratante": "SEINFRA",
        "qsa": [{"cpf": "11111111111", "nome": "Ana Souza", "municipio": "Rio de Janeiro"}],
        "doacoes": [{
            "doador_cpf": "11111111111", "doador_nome": "Ana Souza",
            "beneficiario": "Prefeito X", "cargo_beneficiario": "Prefeito",
            "valor": 500000.0, "ano_eleicao": 2016, "municipio": "Rio de Janeiro",
        }],
        "valor_contratado": 90_000_000.0,  # razão retorno/doação >> 100
        "data_contrato": "2018",
        "beneficiarios_com_poder": ["Prefeito"],
        "irregularidade_no_certame": True,
    }
    r = C6VinculoPolitico().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score <= ANCORAS["medio"]  # CONSERVADOR: jamais 'forte'/'critico' isolado
    assert r.score == ANCORAS["medio"]
    assert r.valores["teto_conservador"] == ANCORAS["medio"]
    assert r.valores["achado_autonomo"] is False
    assert r.valores["razao_retorno_doacao"] is not None and r.valores["razao_retorno_doacao"] >= 100


# ── (c) DESCARTADO mas REGISTRADO quando não há vínculo (ausência = informação de dossiê) ──
def test_c6_descartado_registrado_sem_vinculo():
    ctx = {
        "processo": "contrato-3",
        "orgao_contratante": "ITERJ",
        "qsa": [{"cpf": "99999999999", "nome": "Carlos Lima", "municipio": "Petrópolis"}],
        "doacoes": [{
            "doador_cpf": "22222222222", "doador_nome": "Outra Pessoa",
            "beneficiario": "Candidato Z", "valor": 30000.0, "ano_eleicao": 2016, "municipio": "Petrópolis",
        }],
    }
    r = C6VinculoPolitico().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"          # registrado, não nao_avaliavel
    assert r.score == 0.0
    assert "ausência de vínculo" in r.motivo_refutacao
    assert r.valores["papel"] == "multiplicador_prioridade"
    assert r.valores["vinculos_com_poder"] == 0


# ── (d) homonímia: mesmo NOME, município/CPF diferentes → NÃO atribui a doação ──
def test_c6_homonimia_mitigada_por_municipio_e_cpf():
    # nome idêntico, mas CPFs diferentes (ambos informados) → não casa (é outra pessoa)
    ctx_cpf = {
        "processo": "contrato-4a",
        "qsa": [{"cpf": "33333333333", "nome": "José Santos", "municipio": "Macaé"}],
        "doacoes": [{"doador_cpf": "44444444444", "doador_nome": "José Santos",
                     "beneficiario": "Gestor", "cargo_beneficiario": "Ordenador", "valor": 40000.0,
                     "ano_eleicao": 2016, "municipio": "Macaé"}],
        "beneficiarios_com_poder": ["Ordenador"],
    }
    r1 = C6VinculoPolitico().avaliar(ctx_cpf)
    _valido(r1)
    assert r1.status == "descartado"   # homônimo distinto por CPF → sem vínculo

    # sem CPF, nome igual mas MUNICÍPIO diferente → não casa (homonímia)
    ctx_mun = {
        "processo": "contrato-4b",
        "qsa": [{"nome": "José Santos", "municipio": "Macaé"}],
        "doacoes": [{"doador_nome": "José Santos", "beneficiario": "Gestor",
                     "cargo_beneficiario": "Ordenador", "valor": 40000.0, "ano_eleicao": 2016,
                     "municipio": "Cabo Frio"}],
        "beneficiarios_com_poder": ["Ordenador"],
    }
    r2 = C6VinculoPolitico().avaliar(ctx_mun)
    _valido(r2)
    assert r2.status == "descartado"

    # mesmo nome + MESMO município (sem CPF) → casa (homonímia mitigada positivamente)
    ctx_ok = {
        "processo": "contrato-4c",
        "qsa": [{"nome": "José Santos", "municipio": "Macaé"}],
        "doacoes": [{"doador_nome": "José Santos", "beneficiario": "Gestor",
                     "cargo_beneficiario": "Ordenador", "valor": 40000.0, "ano_eleicao": 2016,
                     "municipio": "Macaé"}],
        "beneficiarios_com_poder": ["Ordenador"],
    }
    r3 = C6VinculoPolitico().avaliar(ctx_ok)
    _valido(r3)
    assert r3.status == "confirmado"
    assert r3.score == ANCORAS["medio"]


# ── (e) 'sem-poder-sobre-o-contrato' → vínculo existe mas NÃO pontua ──
def test_c6_sem_poder_nao_pontua():
    ctx = {
        "processo": "contrato-5",
        "orgao_contratante": "Secretaria de Educação",
        "qsa": [{"cpf": "55555555555", "nome": "Beatriz Rocha", "municipio": "Volta Redonda"}],
        "doacoes": [{
            "doador_cpf": "55555555555", "doador_nome": "Beatriz Rocha",
            "beneficiario": "Vereador Y", "cargo_beneficiario": "Vereador",
            "valor": 80000.0, "ano_eleicao": 2016, "municipio": "Volta Redonda",
        }],
        "_rubrica_poder": {"nivel": "sem-poder-sobre-o-contrato",
                           "trecho": "Vereador não ordena despesa da Secretaria de Educação"},
    }
    r = C6VinculoPolitico().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.valores["vinculos_com_poder"] == 0
    assert r.valores["n_vinculos_brutos"] == 1  # o vínculo bruto FOI registrado
    assert r.evidencia  # registra o vínculo bruto sem poder


# ── (f) sem QSA OU sem doações → nao_avaliavel (campo ausente ≠ 0) ──
def test_c6_sem_qsa_ou_doacoes_nao_avaliavel():
    r_sem_qsa = C6VinculoPolitico().avaliar({
        "processo": "x", "doacoes": [{"doador_nome": "A", "beneficiario": "B", "valor": 1, "ano_eleicao": 2016}],
    })
    _valido(r_sem_qsa)
    assert r_sem_qsa.status == "nao_avaliavel"
    assert r_sem_qsa.valores["tem_qsa"] is False

    r_sem_doa = C6VinculoPolitico().avaliar({
        "processo": "y", "qsa": [{"cpf": "1", "nome": "A"}],
    })
    _valido(r_sem_doa)
    assert r_sem_doa.status == "nao_avaliavel"
    assert r_sem_doa.valores["tem_doacoes"] is False

    r_vazio = C6VinculoPolitico().avaliar({"processo": "z"})
    _valido(r_vazio)
    assert r_vazio.status == "nao_avaliavel"


# ── extra: sem mapa nem LLM → poder não auditado, não pontua (honesto) ──
def test_c6_poder_nao_auditado_nao_pontua():
    ctx = {
        "processo": "contrato-6",
        "orgao_contratante": "SEFAZ",
        "qsa": [{"cpf": "66666666666", "nome": "Diego Alves", "municipio": "Niterói"}],
        "doacoes": [{"doador_cpf": "66666666666", "doador_nome": "Diego Alves",
                     "beneficiario": "Gestor", "valor": 50000.0, "ano_eleicao": 2016, "municipio": "Niterói"}],
        # sem beneficiarios_com_poder e sem _rubrica_poder e sem gerar → poder nao_avaliavel
    }
    r = C6VinculoPolitico().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.valores["poder_avaliado"] is False
    assert r.valores["n_vinculos_brutos"] == 1
