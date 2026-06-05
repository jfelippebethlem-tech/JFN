# -*- coding: utf-8 -*-
"""
Massare — ciclo DIÁRIO de aprendizado contínuo (roda 24/7 via systemd-timer).

A cada execução:
  1. Atualiza dados (preços incrementais + sentimento).
  2. AVALIA previsões antigas cujo alvo já venceu (grade_due) — aprende com o que aconteceu.
  3. Gera a previsão de hoje para o universo-núcleo e REGISTRA cada uma (record_forecast).
  4. Imprime o placar (acerto out-of-sample acumulado) e um briefing curto.

Assim o Massare é cobrado pelo que de fato ocorreu: o placar sobe/desce com a realidade, e as
previsões registradas hoje serão avaliadas automaticamente nos próximos dias. Aprendizado real.
"""
import json
import sys
import time

from massare import store, behavior, learning, engine

NUCLEO = ["^GSPC", "^IXIC", "^DJI", "^BVSP", "BTC-USD", "ETH-USD",
          "GC=F", "CL=F", "DX-Y.NYB", "USDBRL=X", "NVDA"]


def run(horizon=5, record=True):
    store.init_db()
    out = {"ts": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}

    # 1) dados incrementais (preços recentes + sentimento)
    try:
        from massare import sources
        upd = 0
        for sym in NUCLEO:
            try:
                upd += store.upsert_prices(sources.yahoo_history(sym, rng="3mo"), "yahoo")
            except Exception:
                pass
        behavior.collect()
        out["dados_atualizados"] = upd
    except Exception as e:
        out["dados_erro"] = str(e)[:80]

    # 2) avalia previsões vencidas (aprende com o passado)
    out["previsoes_avaliadas"] = learning.grade_due()

    # 3) previsão de hoje + registro
    calls = []
    for sym in NUCLEO:
        try:
            p = engine.predict_today(sym, horizon=horizon)
            if not p:
                continue
            if record:
                learning.record_forecast(sym, p["direction"], horizon, p["prob"],
                                         f"ensemble score={p['score']} oos={p['ensemble_oos_hit_rate']}",
                                         model="ensemble_v1", asof=p["asof"])
            calls.append({"symbol": sym, "dir": p["direction"], "prob": p["prob"],
                          "oos": p["ensemble_oos_hit_rate"]})
        except Exception as e:
            calls.append({"symbol": sym, "erro": str(e)[:60]})
    out["previsoes_hoje"] = calls

    # 4) placar + sentimento
    out["placar"] = learning.scoreboard()
    out["sentimento"] = behavior.snapshot()
    # regime de mercado (HMM) dos índices-âncora, p/ condicionar leitura
    try:
        from massare import ml
        out["regimes"] = {s: ml.regime_hmm(s).get("rotulo_atual") for s in ["^GSPC", "^BVSP", "BTC-USD"]}
    except Exception as e:
        out["regimes_erro"] = str(e)[:60]
    store.set_meta("last_daily", out["ts"])
    return out


def briefing(out):
    s = out.get("sentimento", {})
    fg = s.get("fear_greed", {})
    lines = ["📊 Massare — ciclo diário", f"  {out['ts']}"]
    if fg:
        lines.append(f"  Sentimento: {fg.get('value')} ({fg.get('label','')})")
    sb = out.get("placar", {}).get("overall", {})
    if sb.get("n"):
        lines.append(f"  Placar OOS acumulado: {sb['hit_rate']} (n={sb['n']})")
    lines.append(f"  Avaliadas hoje: {out.get('previsoes_avaliadas',0)} | novas: {len([c for c in out.get('previsoes_hoje',[]) if 'dir' in c])}")
    for c in out.get("previsoes_hoje", []):
        if "dir" in c:
            seta = "🟢↑" if c["dir"] == "up" else "🔴↓"
            lines.append(f"   {seta} {c['symbol']:9} prob={c['prob']} (oos={c['oos']})")
    return "\n".join(lines)


if __name__ == "__main__":
    res = run(record="--norecord" not in sys.argv)
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(briefing(res))
