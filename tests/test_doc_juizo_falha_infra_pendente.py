# -*- coding: utf-8 -*-
"""Falha da cadeia de LLM é PENDÊNCIA, não veredito — e pendência volta à fila (com teto e espaçamento).

Medido em 11/11/2026: 2.462 linhas de `doc_veredito` (rubrica v3) com `aviso = "cadeia LLM indisponível"`
(ago 540 · set 1.030 · out 877 · nov 15). O cache por hash(texto|rubrica) devolvia QUALQUER linha, inclusive a
de falha de infraestrutura, e o `sweep_360.sh` contava todo `doc_i` presente como "feito" — nenhum dos dois
caminhos refazia. É a doença que o `lex_execucao` curou em 29/10 ("vazio volta à fila"); aqui não fora aplicada.
"""
from __future__ import annotations

import json
import sqlite3

from compliance_agent.sei import doc_juizo as J


def _man():
    return {"processo": "SEI-1", "docs": [
        {"i": 1, "titulo": "Parecer PGE (2)", "fase": "controle", "tipo": "parecer", "texto": "texto/001.txt"}]}


def _pasta(tmp_path):
    (tmp_path / "texto").mkdir()
    (tmp_path / "texto/001.txt").write_text("Parecer favorável. Opina-se pela regularidade do certame.",
                                            encoding="utf-8")
    return tmp_path


def _cai(p, s=""):
    raise RuntimeError("nenhum LLM respondeu")


_OK = json.dumps({"escala": 1, "trecho_literal": "Opina-se pela regularidade", "justificativa_curta": "ok"})


def _linhas(con):
    return [json.loads(r[0]) for r in con.execute("select veredito_json from doc_veredito")]


def _envelhecer(con, horas):
    con.execute(f"update doc_veredito set avaliado_em = datetime('now', '-{horas} hours')")
    con.commit()


def test_falha_de_infra_grava_pendente_nunca_veredito(tmp_path):
    con = sqlite3.connect(":memory:")
    out = J.julgar_docs(_man(), _pasta(tmp_path), gerar=_cai, con=con)
    v = out["vereditos"][0]
    assert v["escala"] is None and v["pendente"] is True and v["tentativas"] == 1
    assert out["cobertura"]["pendentes"] == 1
    [g] = _linhas(con)
    assert g["pendente"] is True, "a linha gravada tem de dizer que é pendência, não juízo"


def test_pendente_recente_nao_rebate_o_llm(tmp_path):
    """Espaçamento: a cadeia acabou de cair — rebater no mesmo slot só queima cota."""
    con = sqlite3.connect(":memory:")
    pasta = _pasta(tmp_path)
    J.julgar_docs(_man(), pasta, gerar=_cai, con=con)
    chamadas = []
    out = J.julgar_docs(_man(), pasta, gerar=lambda p, s="": chamadas.append(1) or _OK, con=con)
    assert chamadas == [] and out["vereditos"][0]["pendente"] is True


def test_pendente_espacado_e_rejulgado_e_vira_veredito(tmp_path):
    con = sqlite3.connect(":memory:")
    pasta = _pasta(tmp_path)
    J.julgar_docs(_man(), pasta, gerar=_cai, con=con)
    _envelhecer(con, J.RETENTATIVA_HORAS + 1)
    out = J.julgar_docs(_man(), pasta, gerar=lambda p, s="": _OK, con=con)
    assert out["vereditos"][0]["escala"] == 1 and not out["vereditos"][0].get("pendente")
    [g] = _linhas(con)
    assert g["escala"] == 1, "o re-julgamento substitui a pendência (mesma chave)"


def test_teto_de_tentativas(tmp_path):
    con = sqlite3.connect(":memory:")
    pasta = _pasta(tmp_path)
    for _ in range(J.RETENTATIVA_TETO + 2):
        J.julgar_docs(_man(), pasta, gerar=_cai, con=con)
        _envelhecer(con, J.RETENTATIVA_HORAS + 1)
    [g] = _linhas(con)
    assert g["tentativas"] == J.RETENTATIVA_TETO, "teto: não re-tenta para sempre"
    chamadas = []
    J.julgar_docs(_man(), pasta, gerar=lambda p, s="": chamadas.append(1) or _OK, con=con)
    assert chamadas == []


def test_linha_antiga_sem_marca_e_tratada_como_pendencia(tmp_path):
    """As 2.462 linhas de ago–nov não têm `pendente` nem `tentativas`: valem como 1ª tentativa."""
    con = sqlite3.connect(":memory:")
    pasta = _pasta(tmp_path)
    J.julgar_docs(_man(), pasta, gerar=_cai, con=con)
    velho = {"escala": None, "aviso": "cadeia LLM indisponível: Gemini+Cerebras: 4 modelos", "i": 1}
    con.execute("update doc_veredito set veredito_json=?, avaliado_em=datetime('now','-30 days')",
                (json.dumps(velho),))
    con.commit()
    out = J.julgar_docs(_man(), pasta, gerar=lambda p, s="": _OK, con=con)
    assert out["vereditos"][0]["escala"] == 1


def test_sql_da_fila_do_sweep_reabre_so_a_pendencia_madura(tmp_path):
    """O `sweep_360.sh` usa `SQL_FEITO` para decidir o que é "feito" — pendência madura NÃO é feita."""
    con = sqlite3.connect(":memory:")
    pasta = _pasta(tmp_path)
    J.julgar_docs(_man(), pasta, gerar=_cai, con=con)
    q = f"select count(*) from doc_veredito where {J.SQL_FEITO}"
    assert con.execute(q).fetchone()[0] == 1, "recém-falhada: espera o espaçamento"
    _envelhecer(con, J.RETENTATIVA_HORAS + 1)
    assert con.execute(q).fetchone()[0] == 0, "madura: volta à fila"
    from pathlib import Path
    sh = (Path(__file__).resolve().parents[1] / "tools" / "sweep_360.sh").read_text(encoding="utf-8")
    assert "SQL_FEITO" in sh


def test_sql_feito_nao_reabre_null_sem_aviso(tmp_path):
    """NULL do SQL: `json_extract(aviso)` nulo fazia o NOT(...) virar NULL e tirava do "feito" as 1.643 linhas
    v3 sem escala e sem aviso (medido 11/11/2026: 4.102 reabertas em vez de 2.462)."""
    con = sqlite3.connect(":memory:")
    J.julgar_docs(_man(), _pasta(tmp_path), gerar=lambda p, s="": "", con=con)   # resposta vazia: sem aviso
    _envelhecer(con, J.RETENTATIVA_HORAS + 1)
    assert con.execute(f"select count(*) from doc_veredito where {J.SQL_FEITO}").fetchone()[0] == 1
