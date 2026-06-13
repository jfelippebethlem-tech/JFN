# -*- coding: utf-8 -*-
"""Testes do verificador externo de CPF (tier C) — orquestração offline com provider FAKE (sem rede)."""
from compliance_agent import cpf_externo as ce
from compliance_agent.resolucao_cpf import gerar_cpfs_da_mascara


# CPF real de teste: gera um válido com middle6 conhecido p/ os fakes
_CANDS = gerar_cpfs_da_mascara("***223344**")
_CPF_REAL = _CANDS[42]          # um candidato válido qualquer (middle6=223344)
_M6 = "223344"


class _FakeCpfNome:
    """Provider cpf→nome: só o _CPF_REAL devolve o nome certo; resto devolve nome diferente."""
    nome = "fake"

    def __init__(self, alvo, nome_alvo="JOAO DA SILVA"):
        self.alvo, self.nome_alvo = alvo, nome_alvo

    def nome_por_cpf(self, cpf):
        if cpf == self.alvo:
            return {"ok": True, "nome": self.nome_alvo, "motivo": ""}
        return {"ok": True, "nome": "OUTRA PESSOA", "motivo": ""}


class _FakeBloqueio:
    nome = "fake_block"

    def nome_por_cpf(self, cpf):
        return {"ok": False, "nome": "", "motivo": "bloqueio/captcha (HTTP 403)"}


def test_candidatos_estreitados_usa_fusao():
    # pos3a9 = pos3..9 = '1' + middle6  → estreita p/ 100
    estreito = ce.candidatos_estreitados("***223344**", "1223344")
    assert len(estreito) == 100
    assert all(c[2:9] == "1223344" for c in estreito)   # posições 3-9 fixas
    # sem fusão → 1000
    assert len(ce.candidatos_estreitados("***223344**", None)) == 1000
    # pos3a9 inconsistente com a máscara → ignora e volta p/ 1000
    assert len(ce.candidatos_estreitados("***223344**", "9999999")) == 1000


def test_desmascarar_cpf_nome_resolve():
    prov = _FakeCpfNome(_CPF_REAL)
    r = ce.desmascarar_cpf_nome("JOAO DA SILVA", "***223344**", prov, pausa=0)
    assert r.resolvido and r.cpf == _CPF_REAL and "1:1" in r.motivo


def test_desmascarar_cpf_nome_nao_acha():
    prov = _FakeCpfNome("00000000000")   # alvo inexistente entre candidatos
    r = ce.desmascarar_cpf_nome("JOAO DA SILVA", "***223344**", prov, max_consultas=50, pausa=0)
    assert not r.resolvido and r.consultas == 50


def test_desmascarar_para_em_bloqueio():
    r = ce.desmascarar_cpf_nome("JOAO DA SILVA", "***223344**", _FakeBloqueio(), pausa=0)
    assert not r.resolvido and "bloqueado" in r.motivo.lower() and r.consultas == 1


def test_modo_nome_cpf_confirma_pela_mascara():
    class _FakeNomeCpf:
        nome = "judicial"
        def cpfs_por_nome(self, nome):
            # devolve o real + um homônimo (middle6 diferente)
            return {"ok": True, "cpfs": [_CPF_REAL, "11199988877"], "motivo": ""}
    r = ce.desmascarar_nome_cpf("JOAO DA SILVA", "***223344**", _FakeNomeCpf())
    assert r.resolvido and r.cpf == _CPF_REAL


def test_modo_nome_cpf_rejeita_homonimo():
    class _SoHomonimo:
        nome = "judicial"
        def cpfs_por_nome(self, nome):
            return {"ok": True, "cpfs": ["11199988877"], "motivo": ""}   # middle6 != 223344
    r = ce.desmascarar_nome_cpf("JOAO DA SILVA", "***223344**", _SoHomonimo())
    assert not r.resolvido
