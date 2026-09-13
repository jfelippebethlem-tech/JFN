# -*- coding: utf-8 -*-
"""Os motores DETERMINÍSTICOS leem o documento inteiro — truncar é perder achado em silêncio.

Diretriz do dono (2026-08-03): "tem que ler todos os chars de tudo… analisar tudo com completude
e olhar global sobre cada processo".

Medido: `_texto_de` cortava em 20.000 caracteres por documento, e esse corte alimentava o
acatamento (que roda o `parecer_cumprimento`), a execução (X1-X6) e a triagem. O Parecer 462 do
SEI-270131/000548/2023 tem 54.900 caracteres: dois terços dele — inclusive a CONCLUSÃO, que é
onde o parecerista impõe as condicionantes — ficavam fora da análise. A conclusão de um parecer
mora no fim.

A separação que fica: leitura determinística (regex, disco) sem teto prático; leitura que vai
para LLM continua bounded, porque ali o custo é por token e a janela é finita.
"""
from compliance_agent import processo_360 as P


def test_o_teto_deterministico_e_alto_o_bastante_para_um_parecer_inteiro():
    assert P.TETO_CHARS_DETERMINISTICO >= 200_000


def test_o_teto_do_que_vai_para_LLM_continua_bounded():
    """Sem teto aqui, um processo de 3 milhões de caracteres estoura janela e cota."""
    assert 0 < P.TETO_CHARS_LLM <= 60_000
    assert P.TETO_CHARS_LLM < P.TETO_CHARS_DETERMINISTICO


def test_texto_de_respeita_o_teto_pedido(tmp_path):
    d = tmp_path / "texto"
    d.mkdir()
    (d / "x.txt").write_text("A" * 50_000, encoding="utf-8")
    doc = {"texto": "texto/x.txt"}
    assert len(P._texto_de(tmp_path, doc, teto=1_000)) == 1_000
    assert len(P._texto_de(tmp_path, doc)) == 50_000, "o default voltou a truncar"


def test_acatamento_recebe_o_texto_INTEIRO():
    """É o caminho que alimenta o parecer_cumprimento — o que ele não vê, não cobra."""
    from pathlib import Path as _P
    src = _P(P.__file__).read_text(encoding="utf-8")
    assert 'docs_ac = [{"ref": d["titulo"], "tipo": d["tipo"], "texto": _texto_de(pasta, d)}' in src
