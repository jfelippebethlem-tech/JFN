# -*- coding: utf-8 -*-
"""verificacao — conferência DETERMINÍSTICA do que um modelo diz ter lido. Sem LLM, sem rede.

Diretriz do dono (13/11/2026): "não pode ter margem pra erro em nada. esse é um projeto de governo." Daí:
toda extração traz a CITAÇÃO LITERAL do trecho da fonte, e o código confere (1) que o trecho existe no
documento e (2) que cada número extraído aparece no trecho. Falhou ⇒ a leitura é DESCARTADA (e o chamador
escala para outro motor) — nunca "corrigida", nunca estimada. Ausência é INDISPONÍVEL.

E a regra da dupla leitura: um item só vira VERIFICADO quando duas leituras independentes concordam; a
divergência vira PENDENTE de verificação humana, nunca é resolvida por palpite a favor de um lado.
"""
from __future__ import annotations

import re
import unicodedata

VERIFICADO = "VERIFICADO"
PENDENTE = "PENDENTE"
INDISPONIVEL = "INDISPONIVEL"
_MIN_CITACAO = 8


def _normal(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[\"'“”‘’`]", "", t)
    return " ".join(t.split())


def citacao_existe(citacao: str, fonte: str) -> bool:
    """O trecho citado está LITERALMENTE na fonte (ignorando caixa, acento, aspas e espaços)."""
    c = _normal(citacao)
    return len(c) >= _MIN_CITACAO and c in _normal(fonte)


def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v))


def numero_no_trecho(valor, trecho: str) -> bool:
    """O número extraído aparece no trecho, em qualquer grafia (1.234,56 · 1234.56 · 1234,56 · 1234).

    Compara pela sequência de DÍGITOS de cada número do trecho; casas decimais zeradas são toleradas
    (R$ 1.200,00 ↔ 1200)."""
    if isinstance(valor, float):
        valor = f"{valor:.2f}"            # 1200.0 → "1200.00": compara com "1.200,00" e com "1200"
    alvo = _digitos(valor)
    if not alvo:
        return False
    for m in re.finditer(r"\d[\d.,]*", trecho or ""):
        d = _digitos(m.group(0))
        if alvo in (d, d + "00") or d == alvo + "00":
            return True
    return False


def conferir_extracao(campos: dict, citacao: str, fonte: str, numericos: tuple = ()) -> tuple[bool, str]:
    """(ok, motivo). Citação tem de existir na fonte e cada campo numérico presente tem de estar na citação."""
    if not citacao_existe(citacao, fonte):
        return False, "citação não encontrada literalmente na fonte"
    for k in numericos:
        v = campos.get(k)
        if v in (None, ""):
            continue                      # ausência = INDISPONÍVEL, não erro — o campo fica vazio
        if not numero_no_trecho(v, citacao):
            return False, f"o número de '{k}' não aparece no trecho citado"
    return True, ""


def estado_dupla_leitura(a, b) -> str:
    """VERIFICADO só quando as duas leituras existem e concordam; uma ausente = PENDENTE; ambas = INDISPONIVEL."""
    if a is None and b is None:
        return INDISPONIVEL
    if a is None or b is None:
        return PENDENTE
    return VERIFICADO if a == b else PENDENTE
