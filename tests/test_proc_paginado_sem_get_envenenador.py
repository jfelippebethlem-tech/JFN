"""sei_proc_paginado não pode usar o GET-direto que envenena a sessão cross-unit.

Mesmo mecanismo provado em sei_integra_completa (2026-07-23): o
`ctx.request.get(_url_conteudo_doc(...))` a `documento_visualizar` com o infra_hash
invalidado faz o SEI resetar o contexto server-side e devolve a login shell para
documento de outra unidade → OCR de HTML → texto vazio. sei_proc_paginado já carrega
a árvore viva (abrir_processo + arvore_do_fonte) e deve LER por ela (_conteudo_doc),
não pelo GET-direto que ignora a árvore que ele mesmo montou.

Verificação AO VIVO fica pendente (browser ocupado pela recaptura); este guarda
trava o padrão até lá.
"""
import ast
from pathlib import Path

FONTE = Path(__file__).resolve().parents[1] / "tools" / "sei_proc_paginado.py"


def test_nao_usa_get_direto_de_conteudo():
    src = FONTE.read_text(encoding="utf-8")
    assert "_url_conteudo_doc" not in src, (
        "sei_proc_paginado voltou ao GET-direto que envenena a sessão cross-unit; "
        "leia pela árvore viva (SR._conteudo_doc), que ele já carregou"
    )


def test_le_pela_arvore_viva():
    src = FONTE.read_text(encoding="utf-8")
    assert "_conteudo_doc" in src, "deve ler o conteúdo pela árvore viva"
