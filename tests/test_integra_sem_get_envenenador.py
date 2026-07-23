"""baixa_um NÃO pode fazer o GET-direto que envenena a sessão cross-unit.

Causa-raiz provada em 2026-07-23 (SEI-260007/004617/2024, R$ 48,3 mi): o passo
`ctx.request.get(_url_conteudo_doc(...))` em baixa_um mandava um request a
`documento_visualizar` com o infra_hash invalidado. Para documento de OUTRA
unidade o SEI respondia com a tela de login E RESETAVA o contexto server-side de
documento/unidade — a partir daí TODA leitura pela árvore viva voltava vazia.
Resultado medido: 0 de 646 documentos com conteúdo, embora `_conteudo_via_arvore`
sozinho rendesse 2.348 chars por documento.

O caminho canônico (tools/sei_processo_integral.py) já lê SÓ pela árvore viva
(`_conteudo_via_arvore`), que serve nativo e escaneado sem envenenar. Este teste
trava a correção: o GET envenenador não volta ao loop de download da íntegra.
"""
import ast
from pathlib import Path

FONTE = Path(__file__).resolve().parents[1] / "tools" / "sei_integra_completa.py"


def _corpo_baixa_um() -> str:
    arvore = ast.parse(FONTE.read_text(encoding="utf-8"))
    for node in ast.walk(arvore):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "baixa_um":
            seg = ast.get_source_segment(FONTE.read_text(encoding="utf-8"), node)
            return seg or ""
    raise AssertionError("baixa_um não encontrada em sei_integra_completa.py")


def test_baixa_um_nao_usa_get_direto_de_conteudo():
    corpo = _corpo_baixa_um()
    assert "_url_conteudo_doc" not in corpo, (
        "baixa_um voltou a usar o GET-direto que envenena a sessão cross-unit; "
        "leia o conteúdo só pela árvore viva (_conteudo_doc)"
    )


def test_baixa_um_le_pela_arvore_viva():
    corpo = _corpo_baixa_um()
    assert "_conteudo_doc" in corpo, "baixa_um tem de ler pela árvore viva (_conteudo_doc)"


def test_baixa_um_ainda_protege_contra_tela_de_unidade():
    corpo = _corpo_baixa_um()
    assert "parece_pagina_de_unidade" in corpo, (
        "a guarda contra gravar a tela de unidade como teor não pode sumir"
    )
