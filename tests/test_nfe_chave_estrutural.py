"""O DV sozinho NAO valida chave de acesso — e nem toda chave e NF-e.

Dois defeitos medidos no acervo em 25/07/2026, com 845 chaves aceitas so pelo DV:

1. **49 eram lixo.** O modulo 11 aceita ~1 em 11 sequencias por acaso, e processo e cheio
   de numero longo. Passavam chaves com UF inexistente (20, 85, 30) e modelo inexistente
   (00, 24, 43), de emitentes que nao aparecem em nenhuma OB. Elas produziram um alarme
   falso de "20 notas em contingencia" — das quais **1** era real, e 11 diziam SCAN,
   modalidade desativada desde 2014, numa nota de 2026.

2. **640 nao eram NF-e.** Eram modelo 66 = NF3e, nota de ENERGIA ELETRICA, de dois
   emitentes so (Ampla e Light). A chave de 44 digitos e o formato de TODO documento
   fiscal eletronico, nao so da NF-e. Chamar conta de luz de "NF-e que lastreia o
   pagamento" num dossie e erro de rotulo.

Todas as chaves abaixo sao REAIS, colhidas do acervo.
"""
import pytest

from compliance_agent.nfe_verifica import chave_valida, decompor, extrair_chaves, tp_emissao

NFE_REAL = "26241013569390000167550010000098937175550310"      # NF-e, PE, em contingência SVC-RS
NF3E_REAL = "33260233050071000158660001230385011086268486"     # NF3e de energia (Ampla), RJ
LIXO_UF = "20263166821006702700101126500101332600000000"       # passa no DV, UF 20 não existe


def test_chave_de_nfe_real_continua_valida():
    assert chave_valida(NFE_REAL)
    assert decompor(NFE_REAL)["uf_nome"] == "PE"
    assert decompor(NFE_REAL)["eh_nfe"] is True


def test_chave_de_energia_e_valida_mas_NAO_e_nfe():
    """O erro que motivou a correção: 640 contas de luz eram chamadas de NF-e."""
    assert chave_valida(NF3E_REAL), "NF3e é documento fiscal legítimo, não pode ser descartada"
    d = decompor(NF3E_REAL)
    assert d["modelo"] == "66"
    assert "energia" in d["modelo_nome"].lower()
    assert d["eh_nfe"] is False, "conta de luz não é NF-e — o rótulo vai para o dossiê"


def test_numero_que_so_passa_no_DV_e_recusado():
    from compliance_agent.nfe_verifica import digito_verificador
    assert digito_verificador(LIXO_UF[:43]) == int(LIXO_UF[43]), "o cenário exige que o DV feche"
    assert not chave_valida(LIXO_UF), "UF 20 não existe — o DV sozinho deixava passar"


@pytest.mark.parametrize("uf_ruim", ["20", "85", "30", "99", "00"])
def test_uf_fora_da_tabela_oficial_nao_passa(uf_ruim):
    from compliance_agent.nfe_verifica import digito_verificador
    base = uf_ruim + NFE_REAL[2:43]
    assert not chave_valida(base + str(digito_verificador(base)))


@pytest.mark.parametrize("mod_ruim", ["00", "24", "43", "10", "99"])
def test_modelo_que_nao_e_documento_fiscal_nao_passa(mod_ruim):
    from compliance_agent.nfe_verifica import digito_verificador
    base = NFE_REAL[:20] + mod_ruim + NFE_REAL[22:43]
    assert not chave_valida(base + str(digito_verificador(base)))


def test_mes_impossivel_nao_passa():
    from compliance_agent.nfe_verifica import digito_verificador
    base = NFE_REAL[:4] + "13" + NFE_REAL[6:43]        # mês 13
    assert not chave_valida(base + str(digito_verificador(base)))


def test_extrair_so_traz_o_que_e_plausivel():
    texto = f"nota {NFE_REAL} e conta de luz {NF3E_REAL} e o numero {LIXO_UF} do protocolo"
    achadas = extrair_chaves(texto)
    assert NFE_REAL in achadas and NF3E_REAL in achadas
    assert LIXO_UF not in achadas


def test_contingencia_continua_sendo_lida_offline():
    """O sinal que vale sem rede: tpEmis na posição 35."""
    t = tp_emissao(NFE_REAL)
    assert t["contingencia"] is True and t["valida"] is True
    assert "SVC-RS" in t["descricao"]
    assert tp_emissao(NF3E_REAL)["contingencia"] is False
