# -*- coding: utf-8 -*-
"""Decodifica a sigla de órgão da folha da Prefeitura do Rio (PCRJ) para nome legível.

A folha usa o siglário oficial: o 1º token (antes de `/` ou espaço) é a Secretaria/entidade;
o resto é a lotação interna (coordenadoria, gerência etc.). Aqui resolvemos SÓ o órgão de topo,
que é o que o relatório precisa ("estava nomeado em qual órgão"). Mapa curado a partir dos
prefixos observados na folha + siglário público da PCRJ. Prefixo desconhecido → devolve a
própria sigla (honesto, nunca inventa nome).
"""
from __future__ import annotations

import re

# Prefixo (1º token da sigla) -> nome legível do órgão.
_ORGAO: dict[str, str] = {
    "GP": "Gabinete do Prefeito",
    "CVL": "Casa Civil",
    "PGM": "Procuradoria-Geral do Município",
    "CGM": "Controladoria-Geral do Município",
    "GM": "Guarda Municipal",
    "COMLURB": "Comlurb (Companhia Municipal de Limpeza Urbana)",
    "COMLUR": "Comlurb (Companhia Municipal de Limpeza Urbana)",
    "FUNPREVI": "Funprevi (Fundo de Previdência do Município)",
    "PREVIRIO": "Previ-Rio (Instituto de Previdência)",
    "RIOSAUDE": "RioSaúde (Empresa Pública de Saúde)",
    "RIOSAÚDE": "RioSaúde (Empresa Pública de Saúde)",
    "RIOTUR": "Riotur (Empresa de Turismo)",
    "RIOLUZ": "Rioluz (Iluminação Pública)",
    "RIOCENTRO": "Riocentro",
    "RIOEDUCA": "MultiRio / RioEduca",
    "MULTIRIO": "MultiRio",
    "IPP": "Instituto Pereira Passos",
    "IRPH": "Instituto Rio Patrimônio da Humanidade",
    "FP": "Fundação Parques e Jardins",
    "FPJ": "Fundação Parques e Jardins",
    "FJG": "Fundação João Goulart",
    "GEORIO": "Fundação GEO-Rio",
    "RIOAGUAS": "Fundação Rio-Águas",
    "RIOÁGUAS": "Fundação Rio-Águas",
    "PCRJ": "Prefeitura da Cidade do Rio de Janeiro (lotação genérica)",
    # Secretarias por letra/sigla de topo
    "E": "Secretaria Municipal de Educação",
    "SME": "Secretaria Municipal de Educação",
    "S": "Secretaria Municipal de Saúde",
    "SMS": "Secretaria Municipal de Saúde",
    "SMSDC": "Secretaria Municipal de Saúde e Defesa Civil",
    "F": "Secretaria Municipal de Fazenda",
    "SMF": "Secretaria Municipal de Fazenda",
    "SMFP": "Secretaria Municipal de Fazenda e Planejamento",
    "O": "Secretaria Municipal de Obras",
    "SMO": "Secretaria Municipal de Obras",
    "SECONSERVA": "Secretaria Municipal de Conservação",
    "SMAC": "Secretaria Municipal de Meio Ambiente e Clima",
    "SMDU": "Secretaria Municipal de Planejamento Urbano",
    "SMDUE": "Secretaria Municipal de Desenvolvimento Urbano e Econômico",
    "SMTR": "Secretaria Municipal de Transportes",
    "SMDMU": "Secretaria Municipal de Desenvolvimento e Mobilidade Urbana",
    "SMAS": "Secretaria Municipal de Assistência Social",
    "SMASDH": "Secretaria Municipal de Assistência Social e Direitos Humanos",
    "AS": "Secretaria Municipal de Assistência Social",
    "SMC": "Secretaria Municipal de Cultura",
    "SMEL": "Secretaria Municipal de Esporte e Lazer",
    "SMTE": "Secretaria Municipal de Trabalho e Renda",
    "SMDEICI": "Secretaria de Ciência, Tecnologia e Inovação",
    "SUBSE": "Subsecretaria",
    "SEMESQV": "Secretaria de Envelhecimento Saudável e Qualidade de Vida",
    "SEOP": "Secretaria de Ordem Pública",
    "MA": "Secretaria Municipal de Meio Ambiente",
    "CID": "Secretaria da Cidade / Cidadania",
    "GI": "Secretaria de Governo e Integridade",
    "GO": "Secretaria de Governo",
    "CG": "Controladoria / Coordenadoria-Geral",
    "QV": "Secretaria de Envelhecimento e Qualidade de Vida",
    "H": "Rede Hospitalar / Saúde",
    "J": "Órgão da Justiça / Jurídico municipal",
    "RS": "RioSaúde",
    # marcadores especiais
    "A": "À disposição de outro órgão (cedido)",
}

# Frases de "à disposição" que aparecem inteiras.
_A_DISP = re.compile(r"^\s*(A\s+DISP|À\s+DISP|A\s+DISPOSI)", re.IGNORECASE)


def decodificar(sigla: str | None) -> str:
    """Sigla de órgão -> nome legível. Mantém a sigla original entre parênteses p/ rastreio."""
    s = (sigla or "").strip()
    if not s:
        return "(órgão não informado)"
    if _A_DISP.match(s):
        return f"À disposição / cedido ({s})"
    token = re.split(r"[/ ]", s)[0].upper()
    nome = _ORGAO.get(token)
    if nome:
        return f"{nome} ({s})" if s.upper() != token else nome
    return s  # desconhecido: devolve como está, sem inventar
