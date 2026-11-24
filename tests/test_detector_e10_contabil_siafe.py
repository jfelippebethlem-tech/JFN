# -*- coding: utf-8 -*-
"""E10 testes contábeis contra o SIAFE (O5.3 fatia 1), portados do lex_fatos: OB paga acima do liquidado na mesma NL
e OB emitida antes da NL. OB paga pela régua canônica (`_ob_paga`); NL ausente é INDISPONÍVEL (contada), nunca zero.
Fixture sintética de compliance.db."""
import sqlite3

import pytest

from compliance_agent.aplicacao.detectores.contabil_siafe import OB_ANTES, PAGO_ACIMA

_DDL = """
CREATE TABLE ob_orcamentaria_siafe(numero_ob, ug_emitente, exercicio INTEGER, data_emissao, nl, credor, valor, status,
  status_envio, tipo_regularizacao);
CREATE TABLE nl_siafe(numero, ug_emitente, exercicio INTEGER, status, valor, data_emissao, credor);
INSERT INTO nl_siafe VALUES
  ('2025NL1','010100',2025,'Contabilizado',1000,'05/03/2025','22222222000100'),
  ('2025NL2','010100',2025,'Contabilizado',1000,'05/03/2025','22222222000100'),
  ('2025NL3','010100',2025,'Contabilizado',100,'05/03/2025','33333333000100'),
  ('2025NL4','010100',2025,'Contabilizado',100,'05/03/2025','CG0007060');
INSERT INTO ob_orcamentaria_siafe VALUES
  -- NL1: duas OB pagas somam 1.100 > 1.000 liquidado; a OB1 é de ANTES da NL (01/03 < 05/03)
  ('2025OB1','010100',2025,'01/03/2025','2025NL1','22222222000199',600,'Contabilizado','',''),
  ('2025OB2','010100',2025,'10/03/2025','2025NL1','22222222000100',500,'Contabilizado','',''),
  -- anulada e complementar não são pagamento (invariante 1)
  ('2025OB3','010100',2025,'10/03/2025','2025NL2','22222222000100',5000,'Anulado','',''),
  ('2025OB4','010100',2025,'10/03/2025','2025NL2','22222222000100',5000,'Contabilizado','','Pagamento Complementar'),
  -- NL2: dentro da folga de R$ 0,02
  ('2025OB5','010100',2025,'10/03/2025','2025NL2','22222222000100',1000.01,'Contabilizado','',''),
  -- NL3 de OUTRO credor: identidade não resolvida, não é indício
  ('2025OB6','010100',2025,'01/03/2025','2025NL3','22222222000100',900,'Contabilizado','',''),
  -- NL fora da base e OB sem NL: INDISPONÍVEL contado
  ('2025OB7','010100',2025,'10/03/2025','2025NL99','22222222000100',70,'Contabilizado','',''),
  ('2025OB8','010100',2025,'10/03/2025','','22222222000100',30,'Contabilizado','',''),
  -- inscrição genérica do SIAFE ("diversos beneficiários") não identifica credor: nunca casa OB × NL
  ('2025OB9','010100',2025,'01/03/2025','2025NL4','CG0007060',2000,'Contabilizado','','');
"""


@pytest.fixture()
def con(tmp_path):
    p = tmp_path / "c.db"
    c = sqlite3.connect(p)
    c.executescript(_DDL)
    c.commit()
    c.close()
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def _anotar(itens, e9=None):
    for c in itens:
        c["e9"] = (e9 or {}).get(c["numero_ob"], "E")
    return itens


def test_carga_usa_a_ob_paga_canonica_e_conta_o_indisponivel(con):
    carga = PAGO_ACIMA.carregar(con)
    assert sorted(c["numero_ob"] for c in carga.itens) == ["2025OB1", "2025OB2", "2025OB5", "2025OB6", "2025OB9"]
    ctx = carga.contexto
    assert (ctx["ob_nl_fora_da_base"], ctx["ob_nl_fora_da_base_valor"]) == (1, 70.0)
    assert (ctx["ob_sem_nl_citada"], ctx["ob_sem_nl_citada_valor"]) == (1, 30.0)
    assert ctx["ob_pagas"] == 7                               # anulada e complementar fora


def test_positivo_pago_acima_do_liquidado(con):
    ds = PAGO_ACIMA.detectar(_anotar(PAGO_ACIMA.carregar(con).itens))
    assert [d.chave for d in ds] == ["2025NL1|010100"]
    assert ds[0].valores == {"pago": 1100.0, "liquidado": 1000.0, "excedente": 100.0, "n_ob": 2}
    assert ds[0].estado == "INDICIO" and {f.tipo for f in ds[0].evidencias} == {"nl", "ob"}
    assert "credor_raiz" in ds[0].entradas["obs"][0]          # raiz do CNPJ (8 dígitos); CPF nunca vai às entradas


def test_negativo_pago_dentro_do_liquidado_ou_nl_ausente(con):
    itens = _anotar(PAGO_ACIMA.carregar(con).itens)
    chaves = {d.chave for d in PAGO_ACIMA.detectar(itens)}
    assert "2025NL2|010100" not in chaves                     # 1.000,01 × 1.000,00: dentro da folga
    assert "2025NL3|010100" not in chaves                     # credor da OB ≠ credor da NL
    assert "2025NL4|010100" not in chaves                     # inscrição genérica (CG…): identidade não resolvida
    assert "2025NL99|010100" not in chaves                    # NL fora da base: não avaliada
    # uma OB inelegível (ou indeterminada) na NL tira a NL inteira da régua (invariante 3)
    for v in ("I:TRANSFERENCIA", "?:SEM_NE"):
        assert PAGO_ACIMA.detectar(_anotar(PAGO_ACIMA.carregar(con).itens, {"2025OB2": v})) == []


def test_positivo_ob_antes_da_nl(con):
    ds = OB_ANTES.detectar(_anotar(OB_ANTES.carregar(con).itens))
    assert [d.chave for d in ds] == ["010100|2025OB1|2025"]
    assert ds[0].valores["dias_antes"] == 4 and ds[0].grupo == "2025NL1|010100"


def test_negativo_ob_depois_da_nl_ou_inelegivel(con):
    itens = _anotar(OB_ANTES.carregar(con).itens, {"2025OB1": "?:SEM_NE"})
    assert OB_ANTES.detectar(itens) == []                     # OB6 é anterior, mas de outro credor; OB1 indeterminada


def test_carregar_grupo_reproduz_o_disparo(con):
    tudo = PAGO_ACIMA.detectar(_anotar(PAGO_ACIMA.carregar(con).itens))
    grupo = PAGO_ACIMA.detectar(_anotar(PAGO_ACIMA.carregar_grupo(con, "2025NL1|010100").itens))
    assert [d.entradas for d in grupo] == [d.entradas for d in tudo]
    resumo = PAGO_ACIMA.resumo(_anotar(PAGO_ACIMA.carregar(con).itens), tudo)
    assert resumo["ob_credor_diferente_da_nl"] == 2 and resumo["disparos"] == 1 and resumo["soma_disparos"] == 100.0
