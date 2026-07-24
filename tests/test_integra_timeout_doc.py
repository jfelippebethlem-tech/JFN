"""O timeout por-documento tem de acomodar o OCR de documento escaneado.

Bug provado ao vivo (2026-07-23): `asyncio.wait_for(baixa_um, timeout=15)` cancelava
o OCR de documentos de obra escaneados — Memória de Cálculo (6pg) leva 47,9s medidos,
Diário de Obra (até MAX_PAGINAS_OCR=15pg a ~8s/pg ≈ 120s). São justamente as PROVAS DE
EXECUÇÃO de obra (diário, memória de cálculo, folhas de ponto) que a auditoria precisa.
O OCR roda em thread pool (não cancelável): a 15s o trabalho JÁ está sendo feito, só o
resultado é descartado — desperdício duplo + doc marcado ok=False.

Este teste trava o piso do timeout: tem de cobrir o OCR de MAX_PAGINAS_OCR páginas.
"""
import os
import re
from pathlib import Path

FONTE = Path(__file__).resolve().parents[1] / "tools" / "sei_integra_completa.py"


def _default_doc_timeout() -> int:
    """Lê o default de SEI_DOC_TIMEOUT no código (sem importar o módulo pesado)."""
    src = FONTE.read_text(encoding="utf-8")
    m = re.search(r'os\.environ\.get\("SEI_DOC_TIMEOUT",\s*"(\d+)"\)', src)
    assert m, "não achei o default de SEI_DOC_TIMEOUT"
    return int(m.group(1))


def test_timeout_e_rede_de_seguranca_acima_do_orcamento_ocr():
    # O OCR se auto-limita por OCR_BUDGET_S (300s) e declara parcial. Este timeout é só a
    # REDE DE SEGURANÇA acima disso — tem de ficar acima do orçamento + overhead, senão
    # cortaria o OCR que já se limita sozinho. NÃO é mais acoplado a nº de páginas.
    from compliance_agent.sei.ocr_docs import OCR_BUDGET_S
    assert _default_doc_timeout() > OCR_BUDGET_S, (
        "SEI_DOC_TIMEOUT (rede de segurança) tem de ficar ACIMA do OCR_BUDGET_S — senão "
        "cortaria o OCR que já para sozinho no orçamento"
    )


def test_respeita_override_de_ambiente():
    """Quem quiser mais/menos ainda controla por env — o default só sobe o piso."""
    src = FONTE.read_text(encoding="utf-8")
    assert 'os.environ.get("SEI_DOC_TIMEOUT"' in src, "o override por env não pode sumir"
