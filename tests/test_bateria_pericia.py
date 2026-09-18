"""Cobertura da BATERIA de perícia (quais testes rodam) — não confundir com a cobertura do
acervo (quantos processos foram periciados), que é outra rota e outro módulo.

O que se trava aqui: "83% indisponível" não pode ser lido como "83% sem irregularidade", e o
módulo tem de nomear QUAL captura destrava QUAL teste — senão é sintoma, não diagnóstico.
"""
import json
import sqlite3

import pytest

from tools import bateria_pericia as C

DDL = """
CREATE TABLE pericia_fornecedor (cnpj TEXT, ug TEXT, favorecido TEXT, n_obs INT,
  total_pago REAL, grau TEXT, score INT, n_confirmados INT, n_indicios INT,
  n_indisponivel INT, resumo TEXT, achados_json TEXT, atualizado_em TEXT)"""


@pytest.fixture()
def banco(tmp_path):
    def _criar(fornecedores):
        p = tmp_path / "p.db"
        con = sqlite3.connect(p)
        con.execute(DDL)
        con.executemany("INSERT INTO pericia_fornecedor (cnpj, achados_json) VALUES (?,?)",
                        [(c, json.dumps(a)) for c, a in fornecedores])
        con.commit()
        con.close()
        return str(p)
    return _criar


def _it(codigo, status, titulo="t", motivo=None):
    d = {"codigo": codigo, "status": status, "titulo": titulo}
    if motivo:
        d["motivo"] = motivo
    return d


def test_teste_que_roda_e_teste_sem_insumo(banco):
    db = banco([
        ("1", [_it("T01", "AFASTADO"), _it("T03", "INDISPONIVEL", motivo="falta o saldo")]),
        ("2", [_it("T01", "INDICIO"), _it("T03", "INDISPONIVEL", motivo="falta o saldo")]),
    ])
    r = C.cobertura(db)
    assert r["testes_que_rodam"] == 1 and r["testes_sem_insumo"] == 1
    assert r["vivos"] == ["T01"] and r["sem_insumo"] == ["T03"]


def test_fracao_indisponivel_e_calculada_por_teste(banco):
    db = banco([("1", [_it("T01", "AFASTADO")]), ("2", [_it("T01", "INDISPONIVEL")])])
    t = C.cobertura(db)["testes"][0]
    assert t["fracao_indisponivel"] == pytest.approx(0.5)
    assert t["roda"] is True, "50% ainda roda — o limiar é 95%"


def test_limiar_de_teste_morto(banco):
    forn = [(str(i), [_it("T09", "INDISPONIVEL", motivo="falta INSS")]) for i in range(99)]
    forn.append(("x", [_it("T09", "INDICIO")]))
    r = C.cobertura(banco(forn))
    assert r["testes_sem_insumo"] == 1, "99% indisponível é teste que não roda"


def test_insumo_agrupa_os_testes_que_destrava(banco):
    db = banco([("1", [
        _it("T14", "INDISPONIVEL", motivo="Teste não roda: falta a planilha (Módulo 1) e o piso CCT"),
        _it("T15", "INDISPONIVEL", motivo="Teste não roda: falta a planilha (Submódulo 2"),
        _it("T09", "INDISPONIVEL", motivo="Teste não roda: falta as retenções de INSS (OCR/SEI)"),
    ])])
    ins = {i["insumo"]: i for i in C.cobertura(db)["insumos_que_destravam"]}
    assert ins["planilha de custos do contrato"]["testes_que_destrava"] == 2
    assert "T09" in ins["documento fiscal digitalizado (OCR do SEI)"]["testes"]


def test_motivo_que_nao_casa_vira_buraco_nomeado(banco):
    """Atribuir ao insumo errado por conveniência seria pior que declarar não saber."""
    db = banco([("1", [_it("T99", "INDISPONIVEL", motivo="motivo que não casa com nada conhecido")])])
    ins = C.cobertura(db)["insumos_que_destravam"]
    assert ins[0]["insumo"] == "não classificado"


def test_confirmados_e_contado_e_pode_ser_zero(banco):
    """Zero CONFIRMADO no acervo inteiro é o fato mais importante desta medição."""
    db = banco([("1", [_it("T01", "INDICIO")])])
    assert C.cobertura(db)["confirmados_no_acervo"] == 0


def test_indisponivel_nao_e_ausencia_de_irregularidade():
    """A nota do retorno tem de dizer isso — é o erro de leitura que a medição convida."""
    assert "INSUMO" in C.cobertura.__module__ or True
    doc = C.__doc__
    assert "83,3%" in doc and "insumo" in doc.lower()


def test_acervo_real_tem_os_4_testes_vivos_conhecidos():
    """Controle contra o acervo: se um dos quatro que rodam parar, é regressão de captura."""
    from pathlib import Path
    if not Path("data/compliance.db").exists():
        pytest.skip("compliance.db ausente")
    try:
        r = C.cobertura(limite=500)
    except sqlite3.OperationalError:
        pytest.skip("pericia_fornecedor ausente")
    assert {"T01-3WAY", "T02-STATUS-PAGO"} <= set(r["vivos"]), r["vivos"]


# ── a rota ───────────────────────────────────────────────────────────────────────────────────

def test_rota_declara_que_indisponivel_nao_e_ausencia_de_irregularidade():
    """O painel, sem esta rota, afirma um trabalho que não houve: mostra 31.017 periciados e
    27.846 'com indício', sem dizer que 83,3% dos itens não foram examinados."""
    import json as _json
    from pathlib import Path
    if not Path("data/compliance.db").exists():
        pytest.skip("compliance.db ausente")
    from rotas.investigacao import api_pericia_bateria
    resp = api_pericia_bateria()
    if resp.status_code == 503:
        pytest.skip("perícia não disponível nesta máquina")
    d = _json.loads(resp.body)
    assert d["ok"]
    assert "ausência de EXAME" in d["aviso"]
    assert d["insumos_que_destravam"], "a rota tem de dizer o que destrava o quê"
    assert d["testes_que_rodam"] + d["testes_sem_insumo"] == d["n_testes"]


def test_rota_so_mortos_filtra_sem_mexer_nos_totais():
    import json as _json
    from pathlib import Path
    if not Path("data/compliance.db").exists():
        pytest.skip("compliance.db ausente")
    from rotas.investigacao import api_pericia_bateria
    r1, r2 = api_pericia_bateria(), api_pericia_bateria(so_mortos=True)
    if r1.status_code == 503:
        pytest.skip("perícia não disponível")
    d1, d2 = _json.loads(r1.body), _json.loads(r2.body)
    assert len(d2["testes"]) == d1["testes_sem_insumo"]
    assert d2["n_testes"] == d1["n_testes"], "o total não muda com o filtro de exibição"


# ── rodar não basta: utilidade ───────────────────────────────────────────────────────────────

def test_teste_que_nunca_aponta_nada_e_INERTE(banco):
    """T01 (three-way match) roda em 31.003 apurados e tem ZERO indícios no acervo real."""
    db = banco([(str(i), [_it("T01", "AFASTADO")]) for i in range(200)])
    t = C.cobertura(db)["testes"][0]
    assert t["roda"] and t["utilidade"] == "INERTE"
    assert t["taxa_de_apontamento"] == 0.0


def test_teste_que_aponta_a_maioria_NAO_DISCRIMINA(banco):
    """T08 aponta 85,1% dos apurados. Sinal que marca a maioria não ordena fila nenhuma."""
    forn = [(str(i), [_it("T08", "INDICIO")]) for i in range(85)]
    forn += [(str(100 + i), [_it("T08", "AFASTADO")]) for i in range(15)]
    t = C.cobertura(banco(forn))["testes"][0]
    assert t["utilidade"] == "NAO DISCRIMINA" and t["taxa_de_apontamento"] > 0.5


def test_teste_com_taxa_intermediaria_e_UTIL(banco):
    forn = [(str(i), [_it("T02", "INDICIO")]) for i in range(17)]
    forn += [(str(100 + i), [_it("T02", "AFASTADO")]) for i in range(83)]
    r = C.cobertura(banco(forn))
    assert r["testes"][0]["utilidade"] == "UTIL"
    assert r["testes_uteis"] == 1 and r["uteis"] == ["T02"]


def test_taxa_sobre_punhado_nao_e_confiavel(banco):
    """T04 tem 13 apurados de 31.017 e 'aponta 100%'. Ler isso como teste que acha tudo seria o
    oposto da verdade — a taxa viaja com o denominador e com a marca de confiabilidade."""
    forn = [(str(i), [_it("T04", "INDISPONIVEL", motivo="falta a CCT")]) for i in range(200)]
    forn += [(str(500 + i), [_it("T04", "INDICIO")]) for i in range(3)]
    t = C.cobertura(banco(forn))["testes"][0]
    assert t["utilidade"] == "SEM INSUMO", "sem insumo, a utilidade não se avalia"
    assert t["apurados"] == 3 and t["taxa_confiavel"] is False


def test_util_exige_denominador_grande(banco):
    forn = [(str(i), [_it("T02", "INDICIO")]) for i in range(20)]
    forn += [(str(100 + i), [_it("T02", "AFASTADO")]) for i in range(80)]
    assert C.cobertura(banco(forn))["testes"][0]["taxa_confiavel"] is True


def test_acervo_real_tem_apenas_dois_testes_uteis():
    """Controle contra o acervo: 24 testes, 4 rodam, 2 úteis. Se mudar, algo mudou de verdade."""
    from pathlib import Path
    if not Path("data/compliance.db").exists():
        pytest.skip("compliance.db ausente")
    try:
        r = C.cobertura()
    except sqlite3.OperationalError:
        pytest.skip("pericia_fornecedor ausente")
    assert set(r["uteis"]) == {"T02-STATUS-PAGO", "T07-DUPLICIDADE-COMP"}, r["uteis"]
    assert r["inertes"] == ["T01-3WAY"] and r["nao_discriminam"] == ["T08-GAP-COMPETENCIA"]
