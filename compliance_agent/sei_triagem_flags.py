"""Separa o que ACUSA o processo do que acusa a NOSSA captura.

Medido no acervo em 25/07/2026, sobre as 3.762 fichas do sweep SEI:

    red flags no total ................. 9.863
      queixa de captura ("ausência de") . 5.818  (59,0%)
      achado substantivo ................ 4.045  (41,0%)
    processos cujas flags são TODAS lacuna .. 874  (25,8% dos que têm flag)
      ...e 19 deles receberam nível de risco ALTO

Ou seja: mais da metade da fila de apuração dizia **"o documento não veio"**, não
"o processo tem vício". A causa está no dado de entrada — `modalidade` chega vazia em
78,5% das fichas e `fundamento_legal` em 74,6% —, então o modelo, ao ler um texto sem
esses campos, honestamente aponta "ausência de informação sobre a modalidade". A frase
está certa; o que está errado é ela contar como indício contra o órgão.

É a regra da casa em forma de código: **INDISPONÍVEL ≠ irregular**. Um processo em que
não achamos nada além de lacuna não é um processo suspeito — é um processo **mal
capturado**, e o encaminhamento dele não é o fiscal, é o coletor.

Aqui não há LLM: é classificação determinística sobre o texto que o sweep já gravou,
custo zero, e reprodutível.
"""
from __future__ import annotations

import json
import re

# A queixa de captura tem gramática própria: ela nega a EXISTÊNCIA de um elemento no que
# foi lido ("ausência de", "não consta", "sem informação sobre"). Um achado substantivo
# afirma um FATO do processo ("valor elevado sem pesquisa de preços", "pagamento em
# exercício seguinte"). O corte é por essa negação de presença.
_LACUNA = re.compile(
    r"aus[êe]ncia|n[ãa]o (?:consta|foi|h[áa]|est[áa]|identific|localiz|apresent|inform|especific)"
    r"|falta de|sem (?:informa|document|detalh|especifica|indica|men[çc])|n[ãa]o dispon[íi]vel"
    r"|indisponi|n[ãa]o (?:se )?verific|impossibilidade de|n[ãa]o foi poss",
    re.I,
)


def classificar_flag(texto) -> str:
    """`'lacuna'` (a captura não trouxe) ou `'achado'` (o processo tem)."""
    return "lacuna" if _LACUNA.search(str(texto or "")) else "achado"


def _lista(red_flags) -> list[str]:
    """Aceita a lista já decodificada OU o JSON cru como está no banco."""
    if isinstance(red_flags, str):
        try:
            red_flags = json.loads(red_flags or "[]")
        except (ValueError, TypeError):
            return []
    return [str(x) for x in (red_flags or []) if str(x).strip()]


def triar(red_flags) -> dict:
    """Conta lacuna × achado e diz se o processo só tem lacuna.

    `so_lacuna` é o que importa: processo com flags, mas **nenhuma** substantiva.
    Ele não é suspeito — é mal capturado, e recontá-lo como risco polui a fila.
    Processo SEM flag nenhuma não é `so_lacuna` (não há o que triar).
    """
    fl = _lista(red_flags)
    achados = [f for f in fl if classificar_flag(f) == "achado"]
    lacunas = [f for f in fl if classificar_flag(f) == "lacuna"]
    return {"n_achado": len(achados), "n_lacuna": len(lacunas),
            "achados": achados, "lacunas": lacunas,
            "so_lacuna": bool(fl) and not achados}


def encaminhamento(red_flags) -> str:
    """Para onde o processo deve ir — que é a pergunta que o fiscal faz.

    `apurar`   — há achado substantivo: é fila de fiscalização.
    `recapturar` — só lacuna: o destino é o COLETOR, não o auditor.
    `sem_sinal` — nenhuma flag.
    """
    t = triar(red_flags)
    if t["n_achado"]:
        return "apurar"
    return "recapturar" if t["so_lacuna"] else "sem_sinal"


def risco_sustentado(nivel_risco, red_flags) -> tuple[str, str | None]:
    """O nível de risco só se sustenta se houver achado substantivo por trás.

    Devolve `(nivel, ressalva)`. Um `alto` sem nenhum achado substantivo é rebaixado e a
    razão fica registrada — nunca silenciosamente. Medido: **19 processos** estavam
    exatamente nessa situação. Rebaixar sem dizer por quê seria trocar um erro por outro.
    """
    nivel = str(nivel_risco or "").strip().lower()
    if nivel in ("alto", "medio") and triar(red_flags)["so_lacuna"]:
        return "indisponivel", ("nível não sustentado: todas as red flags são de "
                                "captura ausente, nenhuma é achado sobre o processo — "
                                "o encaminhamento é recapturar, não apurar")
    return nivel, None
