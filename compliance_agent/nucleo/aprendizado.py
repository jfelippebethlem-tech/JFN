"""
Aprendizado progressivo — a inteligência que MELHORA com o uso.

"Inteligência progressiva" aqui não é a IA ficar mais esperta sozinha (isso é
promessa vazia com modelo fraco). É o SISTEMA acumular evidência sobre a
qualidade de cada indicador e calibrar os parâmetros com base em decisões reais
do perito. O ganho é auditável e reversível — nunca uma caixa-preta.

Ciclo:
  1. A cada achado, o perito (ou a instrução do executivo/TCE) marca:
     confirmado (procede) | descartado (falso positivo) | inconclusivo.
  2. Guardamos isso por indicador em ``data/nucleo_feedback.json``.
  3. ``precisao_por_indicador`` mostra quais indicadores acertam e quais geram
     ruído — o perito para de perder tempo com indicador barulhento.
  4. ``sugerir_calibracao`` propõe endurecer/afrouxar parâmetros ligados a
     indicadores com precisão ruim, dentro da faixa sã de ``parametros.py``.
     A aplicação é explícita (o perito decide), via ``parametros.definir_override``.

Sem IA. É estatística simples sobre o histórico de decisões.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from compliance_agent.nucleo import parametros as P

ARQUIVO_FEEDBACK = Path(
    os.environ.get("NUCLEO_FEEDBACK_FILE", "data/nucleo_feedback.json")
)

# Indicador → parâmetros que, se ajustados, mudam sua taxa de disparo.
# (mesma lista que cada indicador declara em parametros_usados)
_IND_PARAMS = {
    "IND-FRAC-01": ["fracionamento_janela_dias", "fracionamento_min_contratos"],
    "IND-EMP-01": ["empresa_nova_dias", "capital_social_min_frac"],
    "IND-ADT-01": ["aditivo_max_qtd"],
    "IND-SUP-01": ["superfat_desvios_padrao", "superfat_delta_min_frac", "superfat_sobrepreco_frac"],
    "IND-DIR-01": ["propostas_min_competicao"],
    "IND-DIR-02": ["prazo_edital_min_dias"],
    "IND-QPQ-01": ["quid_pro_quo_janela_meses", "quid_pro_quo_roi_min"],
    "IND-LIM-01": ["valor_redondo_tolerancia"],
}


def _carregar() -> dict:
    if ARQUIVO_FEEDBACK.exists():
        try:
            return json.loads(ARQUIVO_FEEDBACK.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _salvar(dados: dict) -> None:
    ARQUIVO_FEEDBACK.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO_FEEDBACK.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def registrar_feedback(indicador_id: str, veredito: str, referencia: str = "") -> None:
    """
    Registra a decisão do perito sobre um achado.

    veredito: "confirmado" | "descartado" | "inconclusivo"
    referencia: nº do processo/OB/contrato a que se refere (rastreabilidade).
    """
    veredito = veredito.strip().lower()
    if veredito not in ("confirmado", "descartado", "inconclusivo"):
        raise ValueError("veredito deve ser confirmado|descartado|inconclusivo")
    dados = _carregar()
    reg = dados.setdefault(indicador_id, {
        "confirmado": 0, "descartado": 0, "inconclusivo": 0, "refs": []
    })
    reg[veredito] += 1
    if referencia:
        reg["refs"] = (reg.get("refs", []) + [referencia])[-50:]  # mantém últimas 50
    _salvar(dados)


@dataclass
class PrecisaoIndicador:
    indicador_id: str
    confirmados: int
    descartados: int
    inconclusivos: int
    precisao: float | None    # confirmados / (confirmados+descartados)
    amostra: int


def precisao_por_indicador() -> list[PrecisaoIndicador]:
    """Precisão observada de cada indicador (quanto do que dispara procede)."""
    dados = _carregar()
    saida: list[PrecisaoIndicador] = []
    for ind_id, reg in dados.items():
        c = reg.get("confirmado", 0)
        d = reg.get("descartado", 0)
        i = reg.get("inconclusivo", 0)
        decididos = c + d
        prec = round(c / decididos, 3) if decididos else None
        saida.append(PrecisaoIndicador(ind_id, c, d, i, prec, c + d + i))
    saida.sort(key=lambda p: (p.precisao if p.precisao is not None else 1.0))
    return saida


@dataclass
class SugestaoCalibracao:
    indicador_id: str
    parametro_id: str
    valor_atual: float
    valor_sugerido: float
    direcao: str              # "endurecer" | "afrouxar"
    justificativa: str


def sugerir_calibracao(
    min_amostra: int = 8,
    piso_precisao: float = 0.5,
    teto_precisao: float = 0.95,
) -> list[SugestaoCalibracao]:
    """
    Sugere ajustes de parâmetros com base na precisão observada.

    - Precisão baixa (muito falso-positivo) → ENDURECER o limiar (dispara menos).
    - Precisão altíssima com amostra grande → pode AFROUXAR um pouco (talvez esteja
      deixando passar casos limítrofes).

    Só sugere; a aplicação é decisão explícita do perito. Respeita as faixas sãs.
    """
    sugestoes: list[SugestaoCalibracao] = []
    for prec in precisao_por_indicador():
        if prec.precisao is None or (prec.confirmados + prec.descartados) < min_amostra:
            continue
        params = _IND_PARAMS.get(prec.indicador_id, [])
        if not params:
            continue
        if prec.precisao < piso_precisao:
            direcao, fator = "endurecer", 1.20
            just = (f"Precisão {prec.precisao:.0%} (n={prec.confirmados+prec.descartados}): "
                    f"muitos falsos positivos; endurecer para disparar menos.")
        elif prec.precisao >= teto_precisao and prec.confirmados >= min_amostra * 2:
            direcao, fator = "afrouxar", 0.90
            just = (f"Precisão {prec.precisao:.0%} (n={prec.confirmados+prec.descartados}): "
                    f"muito assertivo; afrouxar pode capturar casos limítrofes.")
        else:
            continue
        for pid in params:
            try:
                atual = P.valor(pid)
            except KeyError:
                continue
            # "endurecer" = subir contagens/limiares que reduzem disparo;
            # para parâmetros onde MENOR = mais rígido, o perito ajusta o sinal.
            sugerido = round(atual * fator, 4)
            par = P.obter(pid)
            if par.minimo is not None:
                sugerido = max(par.minimo, sugerido)
            if par.maximo is not None:
                sugerido = min(par.maximo, sugerido)
            if sugerido != atual:
                sugestoes.append(SugestaoCalibracao(
                    prec.indicador_id, pid, atual, sugerido, direcao, just))
    return sugestoes
