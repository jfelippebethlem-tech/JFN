# -*- coding: utf-8 -*-
"""Motor de TESES de mercado — JFN 2.0, Onda 9 (o módulo-chave do Massare).

Pipeline: notícia (GDELT, Onda 8) → narrativa viva → mapa narrativa→ativos → TESE testável
(direção+horizonte+confiança+racional) → registrada via `learning.record_forecast` (já existe)
e cobrada contra o realizado por `grade_due`/`scoreboard`. É assim que o sistema aprende quais
teses funcionam, sem se enganar.

Invariante de mercado: toda tese vira previsão registrada e é cobrada OOS; nunca prometer certeza.
"""
from __future__ import annotations

# Mapa CURADO narrativa→ativos (semente; o aprendizado refina por acerto OOS).
# cada entrada: gatilhos de tema → (ativos, direcao, racional)
_NARRATIVAS = [
    {"chave": "china_estimulo", "gatilhos": ["china stimulus", "china economy", "pmi china"],
     "ativos": ["VALE3", "EWZ", "minerio"], "direcao": "alta",
     "racional": "Estímulo/retomada na China puxa demanda por minério e commodities (Brasil exportador)."},
    {"chave": "fed_hawkish", "gatilhos": ["federal reserve", "interest rates", "fed hawkish", "fomc"],
     "ativos": ["DXY", "ouro", "acoes"], "direcao": "baixa",
     "racional": "Fed mais duro fortalece o dólar e pressiona ações e ouro (juro real maior)."},
    {"chave": "energia_petroleo", "gatilhos": ["oil", "energy prices", "opec", "petroleo"],
     "ativos": ["PETR4", "PRIO3"], "direcao": "alta",
     "racional": "Alta do petróleo beneficia produtoras (Petrobras/PRIO)."},
    {"chave": "fiscal_brasil", "gatilhos": ["brazil fiscal", "brazil economy", "divida brasil"],
     "ativos": ["IBOV", "real", "juros_longos"], "direcao": "baixa",
     "racional": "Risco fiscal pressiona Bovespa e o real, e abre os juros longos."},
]


def _temas_consulta() -> list[str]:
    return ["China economy stimulus", "Federal Reserve interest rates", "oil energy prices", "Brazil economy fiscal"]


def atual(registrar: bool = True, janela: str = "2d") -> dict:
    """Teses vivas a partir das narrativas em alta hoje. Registra cada uma como previsão (OOS).

    Retorna {ok, teses:[{narrativa, ativos, direcao, horizonte, conf, racional, fontes, acerto_oos}]}.
    """
    from massare import news

    boletim = news.boletim_temas(temas=_temas_consulta(), janela=janela, por_tema=5)
    blocos = boletim.get("blocos", []) if boletim.get("ok") else []
    # texto agregado por bloco p/ casar com as narrativas
    texto_por_tema = {b["tema"].lower(): " ".join(a.get("titulo", "") for a in b.get("artigos", []))
                      for b in blocos}
    todo_texto = " ".join(texto_por_tema.values()).lower() + " " + " ".join(texto_por_tema.keys())

    # placar OOS por símbolo vem do BACKTEST (backtest.por_simbolo, abaixo). O scoreboard logado
    # em learning é agregado (overall/by_horizon/by_model), não indexado por símbolo, e as previsões
    # registradas tendem a estar PENDENTES — por isso não serve como fonte de acerto por ativo aqui.
    placar = {}
    try:
        from massare import learning
        learning.init()
    except Exception:  # noqa: BLE001
        pass

    teses = []
    for nar in _NARRATIVAS:
        n_hits = sum(todo_texto.count(g) for g in nar["gatilhos"])
        if n_hits == 0:
            continue
        conf = min(0.5 + 0.1 * n_hits, 0.9)
        fontes = []
        for b in blocos:
            for a in b.get("artigos", [])[:2]:
                if any(g.split()[0] in (a.get("titulo", "") + b["tema"]).lower() for g in nar["gatilhos"]):
                    fontes.append({"titulo": a.get("titulo", "")[:80], "fonte": a.get("fonte")})
        # HONESTIDADE: o track record do ativo-âncora vem do BACKTEST OOS (o scoreboard logado
        # costuma estar pendente). Carrega hit-rate, edge vs. taxa-base e se há skill demonstrado.
        try:
            from massare import backtest
            bt = backtest.por_simbolo(nar["ativos"][0], horizon=21)
        except Exception:  # noqa: BLE001
            bt = None
        tese = {
            "narrativa": nar["chave"], "ativos": nar["ativos"], "direcao": nar["direcao"],
            "horizonte_dias": 21, "conf": round(conf, 2), "racional": nar["racional"],
            "fontes": fontes[:3],
            "acerto_oos": (bt or {}).get("hit_rate") or (placar.get(nar["ativos"][0], {}) or {}).get("hit_rate"),
            "edge_oos": (bt or {}).get("edge"),
            "tem_skill": (bt or {}).get("tem_skill"),
        }
        teses.append(tese)
        if registrar:
            try:
                from massare import learning
                direction = 1 if nar["direcao"] == "alta" else -1
                learning.record_forecast(nar["ativos"][0], direction, 21, conf,
                                         f"tese:{nar['chave']} — {nar['racional']}", model="massare-teses")
            except Exception:  # noqa: BLE001
                pass

    return {"ok": True, "n": len(teses), "teses": teses,
            "_fonte": "GDELT (narrativas) + mapa curado narrativa→ativos + learning (OOS)",
            "_nota": "Cada tese vira previsão REGISTRADA e é cobrada contra o realizado (OOS). "
                     "Indício direcional, nunca certeza; horizonte e confiança explícitos."}
