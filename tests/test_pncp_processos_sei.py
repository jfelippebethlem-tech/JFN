"""Regex de processo SEI.RIO no texto das íntegras — largura MEDIDA, não escolhida.

Em 316 contratos íntegros do Município, exigir o dígito verificador achava 150 (47,5%);
tolerar a ausência do DV e o órgão de 5 dígitos acha 162 (51,3%). Os 12 a mais são reais:
o cabeçalho do contrato cita o processo sem DV.
"""
from compliance_agent.collectors.pncp import processos_sei_no_texto


def test_casa_formato_completo():
    assert processos_sei_no_texto("Processo nº 005500.001796/2026-48") == ["005500.001796/2026-48"]


def test_casa_sem_digito_verificador():
    """O cabeçalho do contrato cita assim — era o que a regex antiga perdia."""
    assert processos_sei_no_texto("SEI.RIO: 002200.000007/2025") == ["002200.000007/2025"]


def test_casa_orgao_de_cinco_digitos():
    assert processos_sei_no_texto("proc 00700.000789/2025-78") == ["00700.000789/2025-78"]


def test_nao_casa_pedaco_de_numero_maior():
    """Sem as âncoras \\b, um número maior seria fatiado num protocolo que não existe."""
    assert processos_sei_no_texto("9000700.000789/2025781") == []


def test_dedup_e_ordem_estavel():
    t = "005500.001796/2026-48 ... 000184.000040/2026-98 ... 005500.001796/2026-48"
    assert processos_sei_no_texto(t) == ["000184.000040/2026-98", "005500.001796/2026-48"]


def test_texto_vazio():
    assert processos_sei_no_texto("") == []
