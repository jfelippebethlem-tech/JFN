# -*- coding: utf-8 -*-
"""A busca do SEI nunca esteve quebrada — estava com o ESCOPO errado e o parser em outro formato.

O item #10 do handoff dizia: *"o formulário submete, o botão é encontrado e clicado, e a página de
resultado não entrega contagem. Não é sessão, não é carga, não é ausência do termo"* — porque nem o
controle positivo "MGS CLEAN" devolvia nada. Diagnosticado ao vivo em 2026-08-11, com a sessão
livre e `load 0,77`:

1. **O índice do SEI é sobre DOCUMENTOS.** Com `Considerar Documentos` DESMARCADO — que era o
   padrão da ferramenta — a busca por texto livre varre só metadado de processo e devolve zero
   para qualquer coisa, inclusive "LIMPEZA". Com a caixa marcada, "LIMPEZA" devolve
   **213.563 documentos**.
2. **A contagem tem outro formato.** O parser procurava `Lista de Processos ... (N registros)`. A
   tela devolve `<div class="pesquisaBarraD">Exibindo 1 - 10 de 213.563</div>`.
3. **"Nenhum resultado encontrado" é TEMPLATE ESCONDIDO.** A string está no HTML mesmo quando há
   213.563 resultados — quem a procurar no texto cru conclui o oposto do que a página mostra. Foi
   por pouco que não caí nisso ao diagnosticar.

A fixture deste teste é um recorte do HTML REAL devolvido pelo SEI-RJ nesse dia.
"""
from __future__ import annotations

from pathlib import Path

from tools.sei_busca_mgs import parse_resultado

_FIX = Path(__file__).resolve().parent / "fixtures" / "sei_busca_resultado.html"


def test_le_a_contagem_no_formato_que_a_tela_usa():
    r = parse_resultado(_FIX.read_text(encoding="utf-8"))
    assert r["total"] == 213563
    assert r["exibindo"] == (1, 10)


def test_extrai_os_processos_pelo_link_de_protocolo():
    r = parse_resultado(_FIX.read_text(encoding="utf-8"))
    assert "SEI-030001/086733/2026" in r["processos"]
    assert len(r["processos"]) == 2, "a fixture tem dois registros"


def test_traz_o_TIPO_do_processo_junto_do_numero():
    """O tipo é o que separa "Prestação de Contas" de "Pagamento" na hora de escolher o que ler."""
    r = parse_resultado(_FIX.read_text(encoding="utf-8"))
    assert "Repasse de Recursos Federais" in r["processos"]["SEI-030001/086733/2026"]


def test_pagina_SEM_resultado_e_distinguida_de_pagina_NAO_LIDA():
    """Zero legítimo e "não consegui ler" são respostas diferentes, e a casa não pode confundi-las
    — foi essa confusão que manteve o #10 aberto por um dia inteiro."""
    vazia = ('<div class="pesquisaBarra"><div class="pesquisaBarraD"></div></div>'
             '<span class="hidden">Nenhum resultado encontrado</span>')
    r = parse_resultado(vazia)
    assert r["estado"] == "sem_resultado" and r["total"] == 0

    r2 = parse_resultado("<html><body>a sessão caiu</body></html>")
    assert r2["estado"] == "nao_parseei" and r2["total"] is None


def test_nenhum_resultado_encontrado_NAO_vence_a_barra_de_contagem():
    """A string vem no HTML mesmo com 213.563 achados: é template. Quem a lê como veredito
    publica ausência que não existe."""
    html = _FIX.read_text(encoding="utf-8") + '<span>Nenhum resultado encontrado</span>'
    r = parse_resultado(html)
    assert r["estado"] == "com_resultado" and r["total"] == 213563
