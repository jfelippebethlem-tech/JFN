# -*- coding: utf-8 -*-
"""reexecucao — o "backtest" da perícia: rodar uma versão da rubrica sobre a verdade de chão e comparar com o campeão.

Dois caminhos, ambos devolvendo a lista de casos que o portão julga ({numero_sei, real, campeao, desafiante}):
  por_filtros   determinístico, sem LLM: aplica os filtros de armadilha ao laudo fraco JÁ gravado no ledger;
  por_prompt    reexecuta `lex_execucao.avaliar_processo` com as lições da versão, num banco EM MEMÓRIA (sombra: nada
                é gravado em compliance.db, nada entra na fila do Opus), com o `gerar` que o chamador injeta e teto de
                casos. Sem `gerar` não roda — o ciclo --dry-run nunca chama LLM.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import armadilhas, config


def alto_com_filtros(nota: int | None, indicios: list[str] | None, filtros: list[str]) -> int:
    """Laudo fraco segue 'risco alto' depois dos filtros? Só cai se TODOS os indícios casam armadilha ativa — um
    único indício que nenhum filtro explica mantém o laudo alto (o filtro nunca decide contra indício material)."""
    if nota is None or nota < config.ALTO:
        return 0
    if not filtros or not indicios:
        return 1
    return int(not all(armadilhas.do_indicio(i, tuple(filtros)) for i in indicios))


def por_filtros(rotulos: list[dict], campeao: dict, desafiante: dict) -> list[dict]:
    return [{"numero_sei": r["numero_sei"], "real": int(bool(r["alto_verificado"])),
             "campeao": alto_com_filtros(r["nota"], r["indicios"], campeao.get("filtros") or []),
             "desafiante": alto_com_filtros(r["nota"], r["indicios"], desafiante.get("filtros") or [])}
            for r in rotulos if r.get("indicios") is not None]


def por_prompt(rotulos: list[dict], desafiante: dict, gerar, compliance_db: Path | None = None,
               max_casos: int | None = None) -> list[dict]:
    """Reexecuta o desafiante nos casos rotulados. O campeão é o laudo fraco que já estava gravado (mesma entrada,
    rubrica de partida). Devolve só os casos que o motor respondeu."""
    if gerar is None:
        raise ValueError("reexecução por prompt exige um gerador (LLM) injetado — o dry-run não reexecuta")
    from tools import lex_execucao as LX
    db = compliance_db or config.REPO / "data" / "compliance.db"
    ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    sombra = sqlite3.connect(":memory:")
    casos = []
    licoes = [armadilhas.POR_ID[i]["licao"] for i in desafiante.get("licoes") or []]
    alvo = rotulos[:max_casos or config.ORCAMENTO["max_casos_reexecucao"]]
    anterior = LX._LICOES_SOMBRA
    try:
        sombra.execute(ro.execute("SELECT sql FROM sqlite_master WHERE name='lex_execucao'").fetchone()[0])
        obs = LX.mapa_obs_siafe(ro, [r["numero_sei"] for r in alvo])
        LX._LICOES_SOMBRA = licoes
        for r in alvo:
            f = ro.execute("SELECT objeto, valores, documentos, red_flags FROM sei_ficha WHERE numero_sei=?",
                           (r["numero_sei"],)).fetchone()
            if not f:
                continue
            # sem `item`: o laudo de sombra não pode entrar na fila de conferência do Opus (ele regravaria a produção)
            res = LX.avaliar_processo(sombra, r["numero_sei"], f[0] or "", f[1] or "", json.loads(f[2] or "[]"),
                                      json.loads(f[3] or "[]"), lambda p, s, t, item=None: gerar(p, s, t), obs_siafe=obs)
            nota = ((res or {}).get("verdict") or {}).get("nota_risco_execucao")
            if nota is None:
                continue
            casos.append({"numero_sei": r["numero_sei"], "real": int(bool(r["alto_verificado"])),
                          "campeao": int(r["nota"] >= config.ALTO),
                          "desafiante": alto_com_filtros(nota, (res["verdict"].get("indicios") or []),
                                                         desafiante.get("filtros") or []),
                          "nota_desafiante": nota})
    finally:
        LX._LICOES_SOMBRA = anterior
        ro.close()
        sombra.close()
    return casos
