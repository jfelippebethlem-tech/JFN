# -*- coding: utf-8 -*-
"""CRI — índice objetivo de risco de corrupção, comparável ENTRE órgãos.

POR QUE ISTO É DIFERENTE DO `indice_certame`. O índice da casa pontua um certame com o que se
sabe dele: cláusulas, propostas, perfil do fornecedor, execução. É rico e é INCOMPARÁVEL entre
órgãos — um órgão com edital capturado pontua diferente de um órgão sem edital capturado, e a
diferença mede a COLETA, não o risco. Para responder "qual secretaria merece auditoria temática?"
é preciso um índice que use só o que existe para todos.

O CRI (linha Fazekas/DIGIWHIST, validado contra medidas independentes de corrupção e preditivo de
sobrepreço) faz exatamente isso: bandeiras binárias de peso igual, computáveis a partir do
registro básico da contratação, normalizadas por mercado. A força dele é a comparabilidade; a
fraqueza é a grosseria — e por isso ele PRIORIZA, não conclui.

AS BANDEIRAS, e a razão de cada uma:

  · **licitante único em mercado competitivo** — a âncora do método. Um proponente onde o mercado
    tem muitos é o sinal mais robusto da literatura. Em mercado naturalmente concentrado, não é
    bandeira nenhuma — daí a normalização.
  · **contratação direta** — dispensa e inexigibilidade concentram discricionariedade; a
    inexigibilidade mais que a dispensa, porque esta tem hipóteses objetivas.
  · **prazo de publicidade curto** — encurtar o aviso restringe quem consegue preparar proposta.
  · **critério de julgamento não-quantificável** — técnica e preço abre espaço para o subjetivo.
  · **ausência de publicação do aviso** — opacidade documental.
  · **tempo de decisão anômalo** — decisão rápida demais sugere resultado pré-definido; lenta
    demais sugere negociação. As duas pontas contam.
  · **valor atípico para o objeto** — desvio grosseiro da faixa do mercado.

O QUE ESTE MÓDULO NÃO FAZ. Não soma bandeiras que medem a mesma coisa (licitante único e "poucos
proponentes" são a mesma janela); não pontua bandeira que o dado não permite aferir — ela sai da
conta E da normalização, e a `confianca` cai. Bandeira indisponível tratada como zero faz um órgão
sem dado parecer limpo, que é o oposto do que um índice de risco deve fazer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

# Prazos mínimos de publicidade, em dias úteis (Lei 14.133/2021, art. 55). O valor aqui é o piso
# a partir do qual NÃO há bandeira; abaixo dele, há.
PRAZO_MINIMO_DIAS = 8
# Mercado é "competitivo" quando outros certames do mesmo objeto atraem mais que isto.
PROPONENTES_MERCADO_COMPETITIVO = 3
# Decisão em menos de 1 dia ou mais de 180 é anômala nas duas pontas.
DIAS_DECISAO_MIN = 1
DIAS_DECISAO_MAX = 180


@dataclass(frozen=True)
class Bandeira:
    id: str
    descricao: str
    fundamento: str


BANDEIRAS: dict[str, Bandeira] = {
    "licitante_unico": Bandeira(
        "licitante_unico", "um único proponente em mercado com histórico competitivo",
        "âncora do método (Fazekas/DIGIWHIST); preditor validado de sobrepreço"),
    "contratacao_direta": Bandeira(
        "contratacao_direta", "dispensa ou inexigibilidade",
        "Lei 14.133/2021, arts. 74 e 75 — concentra discricionariedade"),
    "prazo_curto": Bandeira(
        "prazo_curto", f"publicidade abaixo do mínimo legal ({PRAZO_MINIMO_DIAS} dias úteis)",
        "Lei 14.133/2021, art. 55"),
    "criterio_subjetivo": Bandeira(
        "criterio_subjetivo", "julgamento por técnica (e preço), não puramente quantificável",
        "abre espaço para pontuação dirigida (ver detector E6)"),
    "sem_aviso_publicado": Bandeira(
        "sem_aviso_publicado", "ausência de publicação do aviso no portal",
        "Lei 14.133/2021, art. 54 — publicidade é regra"),
    "decisao_anomala": Bandeira(
        "decisao_anomala", f"tempo até a decisão fora da faixa ({DIAS_DECISAO_MIN}-"
        f"{DIAS_DECISAO_MAX} dias)", "rápido demais sugere resultado pré-definido; lento demais, "
        "negociação"),
    "valor_atipico": Bandeira(
        "valor_atipico", "valor muito fora da faixa do mesmo objeto no mercado",
        "desvio grosseiro da referência"),
}


def _sem_acento(s: Any) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return t.lower()


def _bandeira_licitante_unico(reg: dict) -> bool | None:
    n = reg.get("n_proponentes")
    mercado = reg.get("proponentes_medios_mercado")
    if n is None:
        return None                      # o PNCP típico só traz o vencedor — não é "1 proponente"
    if mercado is None:
        return None                      # sem o mercado, "único" não distingue monopólio de vício
    if float(mercado) < PROPONENTES_MERCADO_COMPETITIVO:
        return False                     # mercado naturalmente concentrado: não é bandeira
    return int(n) <= 1


def _bandeira_prazo(reg: dict) -> bool | None:
    d = reg.get("dias_publicidade")
    return None if d is None else float(d) < PRAZO_MINIMO_DIAS


def _bandeira_decisao(reg: dict) -> bool | None:
    d = reg.get("dias_ate_decisao")
    if d is None:
        return None
    return not (DIAS_DECISAO_MIN <= float(d) <= DIAS_DECISAO_MAX)


def _bandeira_valor(reg: dict) -> bool | None:
    v, mediana = reg.get("valor"), reg.get("valor_mediano_objeto")
    if not v or not mediana or float(mediana) <= 0:
        return None
    razao = float(v) / float(mediana)
    return razao >= 3.0 or razao <= 0.2


_AFERIDORES = {
    "licitante_unico": _bandeira_licitante_unico,
    "contratacao_direta": lambda r: (None if r.get("modalidade") is None
                                     else bool(r.get("contratacao_direta"))),
    "prazo_curto": _bandeira_prazo,
    # `_sem_acento`: o campo vem "técnica e preço" nas bases reais e "tecnica e preco" nas
    # exportações sem acentuação. Comparar cru pega só metade dos casos, silenciosamente.
    "criterio_subjetivo": lambda r: (None if r.get("criterio_julgamento") is None
                                     else "tecnica" in _sem_acento(r["criterio_julgamento"])),
    "sem_aviso_publicado": lambda r: (None if r.get("aviso_publicado") is None
                                      else not bool(r["aviso_publicado"])),
    "decisao_anomala": _bandeira_decisao,
    "valor_atipico": _bandeira_valor,
}


def calcular(registro: dict) -> dict[str, Any]:
    """CRI 0-100 de um certame. Bandeiras de PESO IGUAL sobre as que foram aferíveis.

    Devolve `{cri, confianca, acesas, apagadas, indisponiveis, detalhe}`. `confianca` é a fração
    de bandeiras aferíveis: um certame com 2 de 7 bandeiras medidas pode ter CRI 100 e confiança
    0,29 — e apresentar o primeiro sem o segundo seria mentir com número.
    """
    acesas, apagadas, indisponiveis = [], [], []
    detalhe = {}
    for bid, aferir in _AFERIDORES.items():
        try:
            v = aferir(registro or {})
        except Exception:  # noqa: BLE001 — bandeira quebrada é indisponível, não zero
            v = None
        detalhe[bid] = v
        (acesas if v is True else apagadas if v is False else indisponiveis).append(bid)

    aferiveis = len(acesas) + len(apagadas)
    cri = round(100.0 * len(acesas) / aferiveis, 1) if aferiveis else None
    return {
        "cri": cri,
        "confianca": round(aferiveis / len(_AFERIDORES), 3),
        "acesas": acesas, "apagadas": apagadas, "indisponiveis": indisponiveis,
        "detalhe": detalhe,
        "motivo": ("nenhuma bandeira aferível — CRI INDISPONÍVEL (não é zero)" if not aferiveis
                   else f"{len(acesas)} de {aferiveis} bandeiras aferíveis acesas"),
        "ressalva": ("Índice comparativo de PRIORIZAÇÃO, não conclusão sobre o certame. "
                     "Bandeira acesa é característica do procedimento, não irregularidade."),
    }


def agregar(registros: Sequence[dict], *, minimo_certames: int = 10) -> dict[str, Any]:
    """CRI médio de um conjunto (órgão, unidade, exercício) — o número que ordena a fila.

    `minimo_certames` existe porque média de três certames não distingue órgão de risco de órgão
    de amostra pequena; abaixo do mínimo o resultado sai marcado como não comparável.
    """
    calculados = [calcular(r) for r in (registros or [])]
    validos = [c for c in calculados if c["cri"] is not None]
    if not validos:
        return {"cri_medio": None, "n": 0, "comparavel": False,
                "motivo": "nenhum certame com bandeira aferível"}
    media = sum(c["cri"] for c in validos) / len(validos)
    conf = sum(c["confianca"] for c in validos) / len(validos)
    freq: dict[str, int] = {}
    for c in validos:
        for b in c["acesas"]:
            freq[b] = freq.get(b, 0) + 1
    return {
        "cri_medio": round(media, 1),
        "confianca_media": round(conf, 3),
        "n": len(validos),
        "comparavel": len(validos) >= minimo_certames,
        "bandeiras_mais_frequentes": dict(sorted(freq.items(), key=lambda kv: -kv[1])),
        "motivo": ("comparável com outros órgãos" if len(validos) >= minimo_certames else
                   f"amostra pequena (n={len(validos)} < {minimo_certames}) — o número existe, "
                   f"mas não ordena fila contra órgãos com amostra maior"),
    }
