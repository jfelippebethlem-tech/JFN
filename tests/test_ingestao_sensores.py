# -*- coding: utf-8 -*-
"""Os 6 sensores por fonte e o lote com quarentena (O4.11; doc 2 §40). Fixtures sintéticas.

Cada sensor tem controle POSITIVO (acusa o defeito plantado) e NEGATIVO (não acusa o dado limpo), e todos
declaram INDISPONÍVEL quando não mediram — nunca 100% nem zero no escuro."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from compliance_agent.ingestao import contrato as ct
from compliance_agent.ingestao import quarentena as qt
from compliance_agent.ingestao import sensores as sn

AGORA = datetime(2026, 11, 24, 12, 0, 0)


def _fonte(**kw):
    d = {"nome": "OB", "natureza": "externa", "dono": "frente SIAFE", "coletor": "m", "frequencia": "diaria",
         "tabela": "ob", "coluna_frescor": "coletado_em", "slo_frescor_h": 36,
         "chave_natural": ["numero_ob", "ug", "exercicio"],
         "campos": {"numero_ob": {"tipo": "texto", "obrigatorio": True, "critico": True, "regex": r"\d{4}OB\d{5}"},
                    "ug": {"tipo": "ug", "obrigatorio": True, "critico": True},
                    "exercicio": {"tipo": "ano", "obrigatorio": True},
                    "data_emissao": {"tipo": "data_br", "critico": True},
                    "valor": {"tipo": "real", "critico": True, "minimo": 0},
                    "coletado_em": {"tipo": "datahora_iso"}},
         "consistencia": [{"tipo": "data_no_exercicio", "campos": ["data_emissao", "exercicio"]}]}
    d.update(kw)
    return ct.Fonte.model_validate(d)


def _ob(i, **kw):
    r = {"numero_ob": f"2025OB{i:05d}", "ug": "036100", "exercicio": 2025, "data_emissao": "10/12/2025",
         "valor": 100.0 + i, "coletado_em": "2026-11-24 08:00:00"}
    r.update(kw)
    return r


# ── completude ────────────────────────────────────────────────────────────────────────────────────

def test_completude_acusa_campo_critico_vazio_e_aceita_o_cheio():
    crit = ["numero_ob", "ug", "data_emissao", "valor"]
    assert sn.completude([_ob(i) for i in range(10)], crit)["estado"] == sn.OK
    r = sn.completude([_ob(i, data_emissao="") for i in range(10)], crit)
    assert r["estado"] == sn.ALERTA and r["valor"] == pytest.approx(0.75) and "data_emissao" in r["detalhe"]


def test_completude_sem_dado_e_indisponivel():
    assert sn.completude([], ["a"])["estado"] == sn.INDISPONIVEL
    assert sn.completude([_ob(1)], [])["estado"] == sn.INDISPONIVEL


# ── validade ──────────────────────────────────────────────────────────────────────────────────────

def test_validade_acusa_coluna_deslocada():
    regs = [_ob(i) for i in range(95)] + [_ob(i, numero_ob="2017PD02779") for i in range(5)]
    r = sn.validade(regs, _fonte())
    assert r["estado"] == sn.ALERTA and r["valor"] == pytest.approx(0.95) and "numero_ob=5" in r["detalhe"]
    assert sn.validade([_ob(i) for i in range(10)], _fonte())["estado"] == sn.OK


# ── unicidade ─────────────────────────────────────────────────────────────────────────────────────

def test_unicidade_acusa_chave_repetida():
    regs = [_ob(1), _ob(1), _ob(1), _ob(2)]
    r = sn.unicidade(regs, ["numero_ob", "ug", "exercicio"])
    assert r["estado"] == sn.ALERTA and "1 chave" in r["detalhe"] and "2 linha" in r["detalhe"]
    # o mesmo número em OUTRA UG não é duplicata (67% dos números colidem entre UGs)
    assert sn.unicidade([_ob(1), _ob(1, ug="296100")], ["numero_ob", "ug", "exercicio"])["estado"] == sn.OK


# ── consistência ──────────────────────────────────────────────────────────────────────────────────

def test_consistencia_data_fora_do_exercicio():
    regras = _fonte().consistencia
    r = sn.consistencia([_ob(1), _ob(2, data_emissao="02/01/2026")], regras)
    assert r["estado"] == sn.ALERTA and "1 violação" in r["detalhe"]
    assert sn.consistencia([_ob(1)], regras)["estado"] == sn.OK


def test_consistencia_ordem_de_datas_mistura_formatos_e_nao_julga_vazio():
    regra = [ct.RegraConsistencia(tipo="ordem", campos=["ini", "fim"])]
    assert sn.consistencia([{"ini": "2024-01-01", "fim": "31/12/2023"}], regra)["estado"] == sn.ALERTA
    assert sn.consistencia([{"ini": "01/01/2024", "fim": "2024-12-31"}], regra)["estado"] == sn.OK
    assert sn.consistencia([{"ini": "2024-01-01", "fim": None}], regra)["estado"] == sn.INDISPONIVEL


# ── atualidade ────────────────────────────────────────────────────────────────────────────────────

def test_atualidade_acusa_coleta_parada():
    r = sn.atualidade("2026-08-09T07:44:32", AGORA, 192)
    assert r["estado"] == sn.ALERTA and "ATRASADO" in r["detalhe"] and r["valor"] > 2500
    assert sn.atualidade("2026-11-24 08:00:00", AGORA, 36)["estado"] == sn.OK


def test_atualidade_le_data_br_pelo_ano_e_nao_pelo_dia():
    # '31/08/2026' > '01/11/2026' como texto; como data é mais velho
    assert sn.atualidade("31/08/2026", AGORA, 24, formato="data_br")["estado"] == sn.ALERTA


def test_atualidade_fonte_indisponivel_nao_vira_atrasada():
    r = sn.atualidade("2026-10-01", AGORA, 216, estado_fonte="INDISPONIVEL",
                      motivo_estado="SEFAZ recusa datacenter", formato="data_iso")
    assert r["estado"] == sn.INDISPONIVEL and "recusa" in r["detalhe"]
    assert sn.atualidade(None, AGORA, 36)["estado"] == sn.INDISPONIVEL


# ── reconciliação ─────────────────────────────────────────────────────────────────────────────────

def test_reconciliacao_origem_x_ingestao():
    assert sn.reconciliacao(40_620, 40_620)["estado"] == sn.OK
    r = sn.reconciliacao(13, 2)                       # QuantidadeParticipante 13, coletados 2
    assert r["estado"] == sn.ALERTA and r["valor"] < 0
    assert sn.reconciliacao(None, 100)["estado"] == sn.INDISPONIVEL


# ── lote e quarentena ─────────────────────────────────────────────────────────────────────────────

def test_lote_conta_e_preserva_o_original():
    f = _fonte()
    existentes = {"2025OB00007|036100|2025": qt.sha256(qt.payload_canonico(_ob(7)))}
    regs = [_ob(1), _ob(2), _ob(2),                    # duplicado dentro do lote
            _ob(3, valor=-5),                          # rejeitado (faixa)
            _ob(4, ug=""),                             # rejeitado (chave incompleta)
            _ob(7),                                    # duplicado do banco (mesmo conteúdo)
            _ob(7, valor=999.0),                       # conflito (mesma chave, conteúdo novo)
            {**_ob(5), "coluna_nova": "x"}]            # aceito, com extensão (schema drift)
    r = qt.processar_lote("siafe_ob", f, regs, ja_existentes=existentes, lote="L1", origem_declarada=8)
    c = r.contagem
    assert (c.recebidos, c.aceitos, c.rejeitados, c.duplicados, c.conflitos) == (8, 3, 2, 2, 1)
    assert c.quarentena == 3 and c.fecha and c.extensoes == {"coluna_nova"}
    acoes = sorted(q.acao for q in r.quarentena)
    assert acoes == ["corrigir_parser", "corrigir_parser", "reconciliar"]
    rejeitado = next(q for q in r.quarentena if "mínimo" in q.motivo)
    assert '"valor":-5' in rejeitado.payload                     # payload ORIGINAL, não o normalizado
    assert rejeitado.payload_sha256 == qt.sha256(rejeitado.payload)


def test_defeito_da_fonte_pede_revisao_humana():
    r = qt.processar_lote("x", _fonte(), [_ob(1, valor=-1)], lote="L",
                          motivo_da_fonte=lambda ms: any("mínimo" in m for m in ms))
    assert r.quarentena[0].acao == "revisar_fonte"


def test_gravar_lote_e_idempotente_e_resolver_nao_apaga(tmp_path):
    con = sqlite3.connect(tmp_path / "q.db")
    con.executescript(qt.DDL)
    r = qt.processar_lote("siafe_ob", _fonte(), [_ob(1), _ob(2, valor=-1)], lote="L1", origem_declarada=2)
    for _ in range(2):                                  # reexecutar o mesmo lote não duplica
        qt.gravar_lote(con, r, contrato_versao=1, parser_versao="t")
    assert con.execute("SELECT COUNT(*) FROM ingestao_quarentena").fetchone()[0] == 1
    assert con.execute("SELECT recebidos, aceitos, quarentena, origem_declarada FROM ingestao_lote").fetchone() \
        == (2, 1, 1, 2)
    item = con.execute("SELECT id FROM ingestao_quarentena").fetchone()[0]
    assert qt.resolver(con, item, "parser corrigido; reprocessado no lote L2")
    assert not qt.resolver(con, item, "de novo")       # já resolvido
    assert con.execute("SELECT COUNT(*) FROM ingestao_quarentena WHERE resolvido_em IS NOT NULL").fetchone()[0] == 1


# ── medir_fonte (SQL) ─────────────────────────────────────────────────────────────────────────────

def test_medir_fonte_no_banco(tmp_path):
    con = sqlite3.connect(tmp_path / "m.db")
    con.execute("CREATE TABLE ob (numero_ob, ug, exercicio, data_emissao, valor, coletado_em)")
    linhas = [_ob(i) for i in range(20)] + [_ob(1), _ob(30, data_emissao="05/01/2026")]
    con.executemany("INSERT INTO ob VALUES (?,?,?,?,?,?)", [tuple(r.values()) for r in linhas])
    con.executescript(qt.DDL)
    con.execute("INSERT INTO ingestao_lote (lote, fonte, contrato_versao, iniciado_em, aceitos, duplicados, "
                "origem_declarada) VALUES ('L','siafe_ob',1,'2026-11-24',21,1,25)")
    out = {s["sensor"]: s for s in sn.medir_fonte(con, "siafe_ob", _fonte(), AGORA)["sensores"]}
    assert set(out) == {"completude", "validade", "unicidade", "consistencia", "atualidade", "reconciliacao"}
    assert out["completude"]["estado"] == sn.OK
    assert out["unicidade"]["estado"] == sn.ALERTA          # _ob(1) gravada duas vezes
    assert out["consistencia"]["estado"] == sn.ALERTA       # janeiro/2026 no exercício 2025
    assert out["atualidade"]["estado"] == sn.OK
    assert out["reconciliacao"]["estado"] == sn.ALERTA      # origem 25 × 22 ingeridos


def test_medir_fonte_tabela_ausente_e_indisponivel(tmp_path):
    con = sqlite3.connect(tmp_path / "v.db")
    out = sn.medir_fonte(con, "siafe_ob", _fonte(), AGORA)["sensores"]
    assert {s["estado"] for s in out} == {sn.INDISPONIVEL}


def test_sql_frescor_data_br_nao_ordena_texto_cru():
    f = _fonte(coluna_frescor="data_emissao", formato_frescor="data_br")
    assert "substr" in sn.sql_frescor(f)
