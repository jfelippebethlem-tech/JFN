# -*- coding: utf-8 -*-
"""Decodificadores de ORIGEM geográfica a partir de identificadores oficiais.

Dois sinais determinísticos e públicos de "de onde a pessoa é":

1. TÍTULO DE ELEITOR (12 dígitos): os dígitos 9-10 codificam a **UF de alistamento**
   (onde a pessoa tirou/renovou o título). Não muda com naturalidade; muda só se a pessoa
   transferiu o domicílio e recebeu novo título. Sinal de ORIGEM ELEITORAL.
   Disponível no TSE consulta_cand em anos que não redigem (ex.: 2016, 2020).

2. CPF (9º dígito): a Região Fiscal da Receita onde o CPF foi cadastrado pela 1ª vez.
   Região 7 = RJ/ES. Sinal PROBABILÍSTICO de origem (reflete o endereço no 1º cadastro),
   pronto para quando o CPF do servidor for obtido (hoje as folhas PCRJ não trazem CPF).

Honesto: ambos são INDÍCIO de origem, não prova de residência atual. Título transferido e
CPF cadastrado fora do estado de nascimento existem — por isso nunca decidem sozinhos.
"""
from __future__ import annotations

import re

# título dígitos 9-10 → UF (tabela oficial TSE)
_TITULO_UF = {
    "01": "SP", "02": "MG", "03": "RJ", "04": "RS", "05": "BA", "06": "PE",
    "07": "PR", "08": "CE", "09": "SC", "10": "GO", "11": "MA", "12": "PA",
    "13": "ES", "14": "PB", "15": "RN", "16": "AL", "17": "MT", "18": "MS",
    "19": "PI", "20": "DF", "21": "SE", "22": "AM", "23": "RO", "24": "AC",
    "25": "AP", "26": "RR", "27": "TO",
}

# CPF 9º dígito → estados da Região Fiscal
_CPF_REGIAO = {
    "0": ["RS"], "1": ["DF", "GO", "MS", "MT", "TO"],
    "2": ["AC", "AM", "AP", "PA", "RO", "RR"], "3": ["CE", "MA", "PI"],
    "4": ["AL", "PB", "PE", "RN"], "5": ["BA", "SE"], "6": ["MG"],
    "7": ["ES", "RJ"], "8": ["SP"], "9": ["PR", "SC"],
}


def uf_do_titulo(titulo: str) -> str:
    """UF de alistamento a partir do nº do título (12 dígitos). '' se inválido/redigido."""
    d = re.sub(r"\D", "", titulo or "")
    if len(d) != 12:
        return ""
    return _TITULO_UF.get(d[8:10], "")


def regiao_do_cpf(cpf: str) -> list[str]:
    """Estados da Região Fiscal do CPF (pelo 9º dígito). [] se inválido/mascarado."""
    d = re.sub(r"\D", "", cpf or "")
    if len(d) != 11:
        return []
    return _CPF_REGIAO.get(d[8], [])


def origem_fora_do_rj(*, titulo: str = "", cpf: str = "", uf_nascimento: str = "") -> tuple[bool, str]:
    """Combina os sinais disponíveis → (fora_do_rj, motivo). Conservador: só afirma 'fora'
    quando um sinal EXCLUI RJ/ES; ausência de dado nunca vira 'fora' (INDISPONÍVEL ≠ fora)."""
    uf_tit = uf_do_titulo(titulo)
    if uf_tit and uf_tit != "RJ":
        return True, f"título alistado em {uf_tit}"
    regiao = regiao_do_cpf(cpf)
    if regiao and "RJ" not in regiao:
        return True, f"CPF da região fiscal {'/'.join(regiao)}"
    nasc = (uf_nascimento or "").strip().upper()
    if nasc and nasc not in ("RJ", ""):
        return True, f"naturalidade {nasc}"
    return False, ""
