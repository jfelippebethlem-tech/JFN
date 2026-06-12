# -*- coding: utf-8 -*-
"""Extrai CPF+nome do TEXTO de documentos do SEI (contrato social, procuração, habilitação) — a fonte
AUTORITATIVA de CPF completo de sócio (a contratação pública é aberta; dever de fiscalização do Deputado,
CF art. 70-71; LGPD art. 7º,II/23). Núcleo PURO e testável.

VERDADE CONCLUSIVA (pedido do dono): só retorna CPF com **dígito verificador VÁLIDO** (mod 11) — descarta
sequências de 11 dígitos que não são CPF (nº de processo, protocolo, etc.). Associa o nome mais provável
(o texto próximo, ex.: "Fulano de Tal, ... CPF 123.456.789-09" ou "inscrito no CPF/MF sob o nº ...").
Honesto: cada par vem com o trecho de contexto p/ conferência; é indício a confirmar na fonte.
"""
from __future__ import annotations

import re

# CPF formatado (com pontuação) OU 11 dígitos crus precedidos de marcador de CPF (evita casar nº de processo)
_CPF_FMT = re.compile(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b")
_CPF_CTX = re.compile(r"(?:CPF|C\.P\.F\.?|CPF/MF|inscrit[oa] no CPF)[^\d]{0,15}(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b", re.I)
# nome: 2+ palavras (CAIXA ALTA ou Capitalizadas, com de/da/dos/e), antes do CPF
_NOME = re.compile(r"([A-ZÀ-Ÿ][A-Za-zà-ÿ']+(?:\s+(?:[Dd][AaEeOo]s?|[Ee]|[A-ZÀ-Ÿ][A-Za-zà-ÿ']+)){1,5})")


def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def validar_cpf(cpf) -> bool:
    """Valida o CPF pelos 2 dígitos verificadores (mod 11). Rejeita repetidos (000..., 111...)."""
    d = _digitos(cpf)
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for i in (9, 10):
        soma = sum(int(d[n]) * ((i + 1) - n) for n in range(i))
        dv = (soma * 10) % 11
        dv = 0 if dv == 10 else dv
        if dv != int(d[i]):
            return False
    return True


def extrair_cpfs(texto: str, max_pares: int = 200) -> list[dict]:
    """Extrai pares {cpf, nome, contexto} VÁLIDOS do texto. CPF só com dígito verificador correto.
    Prioriza CPFs marcados ('CPF nº ...'); cai p/ CPFs formatados soltos. Dedup por CPF."""
    if not texto:
        return []
    vistos: set = set()
    out: list[dict] = []
    # 1) CPFs com marcador explícito (mais confiável p/ associar nome)
    candidatos = [(m.start(), m.group(1)) for m in _CPF_CTX.finditer(texto)]
    # 2) CPFs formatados soltos (pontuação garante que é CPF, não nº de processo)
    candidatos += [(m.start(), m.group(1)) for m in _CPF_FMT.finditer(texto)]
    for pos, raw in candidatos:
        cpf = _digitos(raw)
        if len(cpf) != 11 or cpf in vistos or not validar_cpf(cpf):
            continue
        vistos.add(cpf)
        jan = texto[max(0, pos - 120):pos]  # janela antes do CPF p/ achar o nome
        nomes = _NOME.findall(jan)
        nome = nomes[-1].strip() if nomes else ""
        ctx = re.sub(r"\s+", " ", texto[max(0, pos - 80):pos + 30]).strip()
        out.append({"cpf": cpf, "nome": nome, "contexto": ctx})
        if len(out) >= max_pares:
            break
    return out
