# -*- coding: utf-8 -*-
"""portao — a REGRA DE OURO: IA nunca aprova a própria mudança. Quem aprova é este código, determinístico.

Entra: para cada caso do conjunto de avaliação, o que o campeão e o desafiante disseram (alto ou não) e a verdade
conferida. Sai: PASSA/FALHA por regra, com o motivo. Nenhuma chamada de LLM, nenhuma heurística de texto.

  R1 amostra        casos suficientes
  R2 mensurável     há riscos altos VERDADEIROS no conjunto — sem eles "não derrubou nenhum alto real" não mede nada
  R3 sem regressão  o desafiante não perde risco alto verdadeiro que o campeão pegava
  R4 melhora        derruba falsos altos em proporção mínima E a diferença passa no McNemar exato sobre os casos
                    discordantes (Dietterich 1998: o teste certo quando cada versão roda uma vez nos mesmos casos)
  R5 estabilidade   a melhora aparece nas duas metades do conjunto (partição fixa por processo), não só numa
  R6 travas         kill switch desligado
"""
from __future__ import annotations

import hashlib
from math import comb

from . import config


def mcnemar_exato(b: int, c: int) -> float:
    """p bilateral do teste binomial exato sobre os discordantes (b = só o campeão acerta, c = só o desafiante)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def _metade(numero_sei: str) -> int:
    return int(hashlib.sha1(("metade:" + numero_sei).encode()).hexdigest()[:2], 16) % 2


def medir(casos: list[dict]) -> dict:
    """casos: [{numero_sei, real, campeao, desafiante}] (0/1). Devolve as contagens que o portão julga."""
    m = {"n": len(casos), "altos_verdadeiros": sum(c["real"] for c in casos)}
    for quem in ("campeao", "desafiante"):
        m[f"falsos_altos_{quem}"] = sum(1 for c in casos if c[quem] and not c["real"])
        m[f"altos_pegos_{quem}"] = sum(1 for c in casos if c[quem] and c["real"])
    m["perdidos"] = sum(1 for c in casos if c["real"] and c["campeao"] and not c["desafiante"])
    m["so_campeao_acerta"] = sum(1 for c in casos if (c["campeao"] == c["real"]) and (c["desafiante"] != c["real"]))
    m["so_desafiante_acerta"] = sum(1 for c in casos if (c["desafiante"] == c["real"]) and (c["campeao"] != c["real"]))
    m["p_mcnemar"] = mcnemar_exato(m["so_campeao_acerta"], m["so_desafiante_acerta"])
    return m


# Regras que dizem se o conjunto MEDE (amostra, verdadeiros) ou se o portão pode julgar (travas). Falhar só nelas é
# INCONCLUSIVO: o candidato segue candidato — falta de gabarito não refuta a lição (registro.julgado).
NAO_MEDE = ("R1 amostra", "R2 mensurável", "R6 travas")


def gabarito(casos: list[dict]) -> tuple[list[dict], list[dict]]:
    """(casos com rótulo da FONTE PRIMÁRIA, os demais). O portão julga só os primeiros: rótulo do Opus sobre o resumo
    (nível 1) confirma 31% dos altos na fonte — medir contra ele é medir concordância com o Opus, não acerto.
    Caso sem `nivel_rotulo` é de quem montou o conjunto à mão (testes) e conta como fonte primária."""
    dentro = [c for c in casos if c.get("nivel_rotulo", config.NIVEL_FONTE) >= config.NIVEL_FONTE]
    return dentro, [c for c in casos if c.get("nivel_rotulo", config.NIVEL_FONTE) < config.NIVEL_FONTE]


def julgar(casos: list[dict], regras: dict | None = None) -> dict:
    """{aprovado, regras: [{regra, ok, detalhe}], metricas}. Reprovar é o resultado esperado da maioria das propostas.
    Só os casos rotulados na fonte primária entram nas regras; os outros ficam nas métricas como `fora_do_gabarito`."""
    g = {**config.PORTAO, **(regras or {})}
    casos, fora = gabarito(casos)
    m = medir(casos)
    m["fora_do_gabarito"] = len(fora)
    fa_c, fa_d = m["falsos_altos_campeao"], m["falsos_altos_desafiante"]
    melhora = (fa_c - fa_d) / fa_c if fa_c else 0.0
    estaveis = 0
    for h in (0, 1):
        mm = medir([c for c in casos if _metade(c["numero_sei"]) == h])
        estaveis += int(mm["falsos_altos_desafiante"] < mm["falsos_altos_campeao"] and mm["perdidos"] == 0)
    r = [
        ("R1 amostra", m["n"] >= g["min_casos"], f"{m['n']} casos rotulados na fonte primária (mínimo {g['min_casos']})"
         + (f"; {len(fora)} com rótulo do Opus sobre o resumo não contam" if fora else "")),
        ("R2 mensurável", m["altos_verdadeiros"] >= g["min_altos_verdadeiros"],
         f"{m['altos_verdadeiros']} riscos altos verdadeiros no conjunto (mínimo {g['min_altos_verdadeiros']})"),
        ("R3 sem regressão", m["perdidos"] <= g["regressao_maxima"] * max(1, m["altos_pegos_campeao"]),
         f"{m['perdidos']} risco(s) alto(s) verdadeiro(s) perdido(s) de {m['altos_pegos_campeao']} que o campeão pegava"),
        ("R4 melhora", melhora >= g["melhora_minima"] and m["p_mcnemar"] <= g["p_mcnemar"],
         f"falsos altos {fa_c} → {fa_d} ({melhora * 100:.1f}%; mínimo {g['melhora_minima'] * 100:.0f}%), "
         f"McNemar exato p={m['p_mcnemar']:.4f} (máximo {g['p_mcnemar']})"),
        ("R5 estabilidade", estaveis >= g["min_metades_estaveis"], f"melhora sem perda em {estaveis} de 2 metades"),
        ("R6 travas", not config.morto(), "kill switch desligado" if not config.morto() else "KILL ativo"),
    ]
    return {"aprovado": all(ok for _, ok, _ in r), "regras": [{"regra": a, "ok": bool(b), "detalhe": c} for a, b, c in r],
            "metricas": {**m, "melhora_falsos_altos": round(melhora, 4)}}
