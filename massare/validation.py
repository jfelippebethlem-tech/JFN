# -*- coding: utf-8 -*-
"""Validação honesta de estratégia — JFN 2.0, Onda 9 (López de Prado).

Métricas que separam edge real de overfitting: Sharpe DEFLACIONADO (DSR/PSR), custos/slippage
SEMPRE no retorno, max drawdown, e uma estimativa de PBO (probabilidade de overfit do backtest).
numpy puro (sem vectorbt). Invariante de mercado: reportar OOS + custos; nunca prometer certeza.
"""
from __future__ import annotations

import math


def _mean(x): return sum(x) / len(x) if x else 0.0


def _std(x):
    if len(x) < 2:
        return 0.0
    m = _mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))


def _phi(z: float) -> float:
    """CDF normal padrão."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def sharpe(retornos: list[float], periodos_ano: int = 252) -> float:
    """Sharpe anualizado de uma série de retornos por período."""
    s = _std(retornos)
    if s == 0:
        return 0.0
    return _mean(retornos) / s * math.sqrt(periodos_ano)


def aplicar_custos(retornos: list[float], custo_por_trade: float = 0.0005,
                   turnover: float = 1.0) -> list[float]:
    """Desconta custo/slippage de cada retorno (custo × turnover). SEMPRE aplicar antes de avaliar."""
    c = custo_por_trade * turnover
    return [r - c for r in retornos]


def max_drawdown(retornos: list[float]) -> float:
    """Máximo drawdown da curva de capital (composta)."""
    eq = 1.0
    pico = 1.0
    mdd = 0.0
    for r in retornos:
        eq *= (1 + r)
        pico = max(pico, eq)
        mdd = min(mdd, eq / pico - 1)
    return round(mdd, 4)


def deflated_sharpe(retornos: list[float], n_tentativas: int = 1, periodos_ano: int = 252) -> dict:
    """Sharpe deflacionado (DSR de López de Prado): probabilidade de o Sharpe ser real,
    PENALIZANDO o nº de tentativas (multiple testing) e os momentos da distribuição.

    Retorna {sharpe, dsr, n_obs, n_tentativas, significativo}. dsr→1 = edge robusto; ~0.5 = ruído.
    """
    n = len(retornos)
    if n < 10:
        return {"ok": False, "_nota": "INDISPONÍVEL: amostra < 10 períodos"}
    sr = _mean(retornos) / _std(retornos) if _std(retornos) else 0.0  # por período (não anualizado)
    m = _mean(retornos)
    s = _std(retornos) or 1e-9
    skew = sum(((r - m) / s) ** 3 for r in retornos) / n
    kurt = sum(((r - m) / s) ** 4 for r in retornos) / n
    # Sharpe esperado sob o nulo dado n_tentativas (López de Prado, aproximação)
    e = math.e
    z1 = _phi_inv(1 - 1.0 / max(n_tentativas, 1))
    z2 = _phi_inv(1 - 1.0 / (max(n_tentativas, 1) * e))
    sr0 = 0.5 * ((1 - 0.5772) * z1 + 0.5772 * z2) / math.sqrt(n)  # var(SR)≈1/n sob o nulo
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-9))
    dsr = _phi((sr - sr0) * math.sqrt(n - 1) / denom)
    return {
        "ok": True, "sharpe_anualizado": round(sr * math.sqrt(periodos_ano), 3),
        "dsr": round(dsr, 3), "n_obs": n, "n_tentativas": n_tentativas,
        "significativo": dsr > 0.95,
        "_nota": "DSR penaliza multiple-testing e momentos; >0.95 = edge robusto, ~0.5 = ruído. "
                 "Custos já devem estar no retorno (aplicar_custos).",
    }


def _phi_inv(p: float) -> float:
    """Inversa da CDF normal (aprox. de Acklam) — para o cálculo do Sharpe esperado sob o nulo."""
    p = min(max(p, 1e-9), 1 - 1e-9)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= 1 - pl:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
