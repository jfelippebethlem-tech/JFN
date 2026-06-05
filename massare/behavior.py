# -*- coding: utf-8 -*-
"""
Massare — camada COMPORTAMENTAL (a variável humana).

Mercados não se movem só por fundamentos: movem-se por como **humanos reagem** — medo,
ganância, manada, pânico, euforia. Esta camada agrega proxies GRATUITOS desse comportamento
e os guarda como séries em `macro` (sentiment_*), para o Massare condicionar suas teses ao
"clima emocional" do mercado.

Proxies usados (todos grátis):
  - Crypto Fear & Greed (alternative.me) ........ medo/ganância no risco (0=pânico, 100=euforia)
  - VIX (já no store, ^VIX) ..................... "índice do medo" das ações US; >30 = estresse
  - Curva de juros 10Y-2Y (FRED T10Y2Y) ......... expectativa humana de recessão (invertida = medo)
  - Amplitude/retornos extremos ................. pânico/euforia via |retorno| diário das séries

Princípio (behavioral finance): medo extremo costuma marcar fundos (oportunidade) e ganância
extrema marca topos (risco). É um SINAL de contexto, nunca uma certeza — alimenta o aprendizado
contínuo (ver learning.py), que mede se esses padrões de fato anteciparam o mercado.
"""
import time
import httpx

from massare import store

UA = {"User-Agent": "Mozilla/5.0 (compatible; MassareBot/1.0)"}


def crypto_fear_greed(limit=0):
    """Índice Fear&Greed cripto (alternative.me). Retorna [(date, value 0-100), ...]."""
    url = f"https://api.alternative.me/fng/?limit={limit or 0}"
    r = httpx.get(url, headers=UA, timeout=25).json()
    out = []
    for d in r.get("data", []):
        ts = int(d["timestamp"])
        date = time.strftime("%Y-%m-%d", time.gmtime(ts))
        out.append((date, float(d["value"])))
    return out


def classify(value):
    """Rótulo humano do nível de medo/ganância (0-100)."""
    v = float(value)
    if v < 25:  return "Medo extremo (capitulação — historicamente fundo)"
    if v < 45:  return "Medo"
    if v < 55:  return "Neutro"
    if v < 75:  return "Ganância"
    return "Ganância extrema (euforia — historicamente topo)"


def vix_regime():
    """Lê o último ^VIX do store e classifica o estresse das ações US."""
    with store.connect() as con:
        row = con.execute("SELECT date, close FROM prices WHERE symbol='^VIX' ORDER BY date DESC LIMIT 1").fetchone()
    if not row:
        return None
    date, vix = row
    if vix < 15:   reg = "Complacência (vol baixa)"
    elif vix < 20: reg = "Calmo"
    elif vix < 30: reg = "Cautela"
    elif vix < 45: reg = "Estresse"
    else:          reg = "Pânico"
    return {"date": date, "vix": vix, "regime": reg}


def collect():
    """Atualiza as séries de sentimento no store."""
    n = 0
    try:
        rows = crypto_fear_greed(limit=0)  # histórico completo (~desde 2018)
        n += store.upsert_macro("sentiment_crypto_fng", rows, "alternative.me")
    except Exception as e:
        print("  ✗ fear&greed:", str(e)[:60])
    return n


def snapshot():
    """Retrato atual da 'variável humana' para o briefing do Massare."""
    out = {}
    try:
        fng = crypto_fear_greed(limit=1)
        if fng:
            out["fear_greed"] = {"date": fng[-1][0], "value": fng[-1][1], "label": classify(fng[-1][1])}
    except Exception:
        pass
    vr = vix_regime()
    if vr:
        out["vix"] = vr
    return out


if __name__ == "__main__":
    store.init_db()
    print("coletando sentimento...")
    print("  pontos FNG salvos:", collect())
    import json
    print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
