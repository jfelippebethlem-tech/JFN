"""Ninho e pela SALA e por CONJUNTO de fatores — nao pelo predio nem por um sinal so.

Pedido do dono (25/07/2026): "queremos saber se existem na mesma SALA... e um conjunto de
fatores que faz uma empresa ser de fachada".

Medido no acervo: agrupar por PREDIO poe no topo "AV. PRES. ANTONIO CARLOS 375" (3 de 13
CNPJs, R$ 7,2 bi) e "RUA DA ASSEMBLEIA 10" com 318 CNPJs — edificios comerciais do Centro.
Agrupar por SALA poe no topo "RUA CONSELHEIRO SARAIVA 28 · SALA 601": 2 de 3 recebendo,
2 de 3 baixadas, todas abertas em 2018, mesmo telefone.
"""
import sqlite3
import tempfile

import pytest

from compliance_agent.ninho_sala import SALA_MASSA, ninhos_por_sala, norm_complemento

DDL_REC = """CREATE TABLE estabelecimentos (cnpj TEXT PRIMARY KEY, endereco_norm TEXT,
  complemento TEXT, situacao_cadastral TEXT, data_inicio_atividade TEXT, telefone1 TEXT,
  cnae_principal TEXT, nome_fantasia TEXT);"""
DDL_OB = """CREATE TABLE favorecido_resumo (favorecido_cpf TEXT, total_pago REAL);"""
END = "RUA X 10 CENTRO 20000000"


def _bases(estabs, pagos):
    a = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    b = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    c = sqlite3.connect(a); c.executescript(DDL_REC)
    c.executemany("INSERT INTO estabelecimentos VALUES (?,?,?,?,?,?,?,?)", estabs)
    c.commit(); c.close()
    c = sqlite3.connect(b); c.executescript(DDL_OB)
    c.executemany("INSERT INTO favorecido_resumo VALUES (?,?)", pagos)
    c.commit(); c.close()
    return b, a          # (compliance, receita)


def cnpj(n: int | str) -> str:
    """CNPJ de teste com 14 dígitos e RAIZ distinta por `n`.

    A raiz são os 8 primeiros dígitos, e o detector (corretamente) descarta grupos de uma
    raiz só como matriz+filiais. Preencher com zeros à esquerda dava a MESMA raiz a todos e
    o grupo era rejeitado — defeito da fixture, não do detector.
    """
    return f"{int(n):08d}000191"


def _e(n, compl, sit="ATIVA", ano="2018", tel="21999", cnae="4711"):
    return (cnpj(n), END, compl, sit, f"{ano}-01-01", tel, cnae, "")


@pytest.mark.parametrize("bruto,esperado", [
    ("SALA 601", "SALA 601"), ("sala 601", "SALA 601"), (" Conj. 1204 ", "CONJ 1204"),
    ("LOJA A", "LOJA A"), ("APT 107", "APT 107"),
])
def test_complemento_que_identifica_unidade_passa(bruto, esperado):
    assert norm_complemento(bruto) == esperado


@pytest.mark.parametrize("generico", ["CASA", "LOJA", "FUNDOS", "PARTE", "TERREO", "", None,
                                      "SALA", "ANDAR", "GALPAO"])
def test_complemento_generico_NAO_identifica_sala(generico):
    """226 mil dizem só 'CASA' e 135 mil só 'LOJA' — não são unidades."""
    assert norm_complemento(generico) == ""


def test_mesma_sala_com_dois_recebendo_e_varios_fatores_e_ALTO():
    estabs = [_e(111, "SALA 601", sit="BAIXADA"), _e(222, "SALA 601", sit="INAPTA"),
              _e(333, "SALA 601")]
    db, rec = _bases(estabs, [(cnpj(111), 500.0), (cnpj(222), 700.0)])
    r = ninhos_por_sala(db_path=db, receita_path=rec)
    assert r["ok"] and r["n"] == 1
    g = r["grupos"][0]
    assert g["grau"] == "alto", g["fatores"]
    assert g["n_recebem_ob"] == 2 and g["n_cnpjs"] == 3
    juntos = " | ".join(g["fatores"]).lower()
    assert "mesmo telefone" in juntos
    assert "mesmo ano" in juntos
    assert "baixada" in juntos


def test_UM_recebendo_nao_e_ninho():
    """O defeito original: 1 recebedor é fornecedor com vizinhos."""
    estabs = [_e(111, "SALA 601"), _e(222, "SALA 601"), _e(333, "SALA 601")]
    db, rec = _bases(estabs, [(cnpj(111), 900.0)])
    r = ninhos_por_sala(db_path=db, receita_path=rec)
    assert r["ok"] and r["n"] == 0


def test_salas_DIFERENTES_do_mesmo_predio_nao_se_misturam():
    """Era exatamente o erro de agrupar por endereço: 601 e 1001 viravam um grupo só."""
    estabs = [_e(111, "SALA 601"), _e(222, "SALA 1001")]
    db, rec = _bases(estabs, [(cnpj(111), 500.0), (cnpj(222), 500.0)])
    r = ninhos_por_sala(db_path=db, receita_path=rec)
    assert r["n"] == 0, "salas distintas não podem formar um ninho"


def test_escritorio_virtual_fica_de_fora():
    """'VISCONDE DE PIRAJA 414 · SAL 718' tem 3.183 CNPJs no dump — é caixa postal."""
    estabs = [_e(1000 + i, "SALA 718") for i in range(SALA_MASSA + 3)]
    db, rec = _bases(estabs, [(cnpj(1000), 500.0), (cnpj(1001), 500.0)])
    r = ninhos_por_sala(db_path=db, receita_path=rec)
    assert r["n"] == 0


def test_matriz_e_filiais_da_mesma_raiz_nao_e_ninho():
    estabs = [("12345678000101", END, "SALA 5", "ATIVA", "2018-01-01", "21999", "4711", ""),
              ("12345678000292", END, "SALA 5", "ATIVA", "2018-01-01", "21999", "4711", "")]
    db, rec = _bases(estabs, [("12345678000101", 500.0), ("12345678000292", 500.0)])
    r = ninhos_por_sala(db_path=db, receita_path=rec)
    assert r["n"] == 0, "matriz+filiais é grupo próprio, não ninho"


def test_fator_ausente_vira_INDISPONIVEL_e_nao_conta_contra():
    estabs = [(cnpj(111), END, "SALA 9", "", "", "", "", ""),
              (cnpj(222), END, "SALA 9", "", "", "", "", "")]
    db, rec = _bases(estabs, [(cnpj(111), 10.0), (cnpj(222), 10.0)])
    r = ninhos_por_sala(db_path=db, receita_path=rec)
    g = r["grupos"][0]
    assert "situação cadastral" in g["indisponivel"]
    assert "telefone" in g["indisponivel"]
    assert g["grau"] != "alto", "sem fatores medidos não se sobe para alto"


def test_dump_ausente_e_INDISPONIVEL_nao_lista_vazia():
    r = ninhos_por_sala(receita_path="/tmp/nao_existe_receita.db")
    assert r["ok"] is False and "INDISPON" in r["erro"].upper()
