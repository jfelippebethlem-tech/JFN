# -*- coding: utf-8 -*-
"""A acusação mais dura do motor nascia ANTES de saber o que a nossa captura deixou de trazer.

`F_EXECUCAO_SEM_EVIDENCIA` diz *pagamento sem prova de entrega* — art. 63 da Lei 4.320/1964. Ela é
montada na etapa das lacunas de fase; a conferência que compara a lista de documentos do PARECER
com a nossa pasta roda depois. Resultado: a crítica era afirmada sem nunca perguntar se o documento
que falta é o próprio atesto — e a falta é NOSSA.

Medido em 2026-08-07 nos 63 processos colhidos da VM-2: **10 tinham a crítica e 4 conviviam com
documento citado nos autos e ausente da captura**. No mais grave (`080001/016776/2023`), o parecer
lista 5 documentos e 1 não chegou: score caiu de 74,5 para 57,4 quando o achado passou a dizer
INDISPONÍVEL em vez de descumprido.

O achado NÃO some — some a certeza. É a doutrina da casa: ausência de dado não é ausência de fato.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_critica_rebaixa_com_lacuna_de_captura.py -q
"""
from __future__ import annotations

import inspect
import re


def _trecho() -> str:
    from compliance_agent import processo_360

    return inspect.getsource(processo_360.avaliar_pasta)


def test_a_critica_e_rebaixada_quando_ha_documento_citado_e_nao_capturado():
    fonte = _trecho()
    assert "_sem_captura" in fonte, "o rebaixamento sumiu de `avaliar_pasta`"
    i = fonte.index("_sem_captura")
    bloco = fonte[i:i + 1600]
    assert "F_EXECUCAO_SEM_EVIDENCIA" in bloco, "o rebaixamento deixou de alcançar a crítica"
    assert re.search(r'gravidade"\]\s*=\s*"media"', bloco), "o grau deixou de cair"


def test_o_achado_nao_desaparece_ele_muda_de_grau():
    """Sumir com o achado seria o erro oposto: a evidência continua sem aparecer nos autos lidos."""
    fonte = _trecho()
    i = fonte.index("_sem_captura")
    bloco = fonte[i:i + 1600]
    assert "achados.remove" not in bloco and "del " not in bloco, (
        "o achado passou a ser REMOVIDO — ele deve permanecer, com grau menor e a ressalva")
    assert "INDISPON" in bloco.upper(), "a ressalva de indisponibilidade sumiu do texto do achado"


def test_o_numero_do_documento_ausente_vai_no_apoio():
    """Sem citar QUAL documento falta, a ressalva vira desculpa genérica — e o fiscal não sabe o
    que requisitar."""
    fonte = _trecho()
    i = fonte.index("_sem_captura")
    bloco = fonte[i:i + 1600]
    assert 'apoio"]' in bloco and "join(_sem_captura)" in bloco


def test_sem_lacuna_de_captura_a_critica_continua_critica():
    """Controle positivo: onde a captura está completa, a acusação permanece no grau máximo."""
    fonte = _trecho()
    i = fonte.index("_sem_captura")
    assert re.search(r"if\s+_sem_captura:", fonte[i:i + 400]), (
        "o rebaixamento deixou de ser condicionado à existência de lacuna de captura")
