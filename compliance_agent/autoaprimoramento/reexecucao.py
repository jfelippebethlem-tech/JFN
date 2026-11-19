# -*- coding: utf-8 -*-
"""reexecucao — o "backtest" da perícia: rodar uma versão da rubrica sobre a verdade de chão e comparar com o campeão.

Dois caminhos, ambos devolvendo a lista de casos que o portão julga ({numero_sei, real, campeao, desafiante}):
  por_filtros   determinístico, sem LLM: aplica os filtros de armadilha ao laudo fraco JÁ gravado no ledger;
  por_prompt    reexecuta `lex_execucao.avaliar_processo` com as lições do campeão E do desafiante, com o mesmo
                gerador, num banco EM MEMÓRIA (sombra: nada é gravado em compliance.db, nada entra na fila do Opus),
                com o `gerar` que o chamador injeta e teto de casos. Sem `gerar` não roda — o ciclo --dry-run nunca
                chama LLM.
"""
from __future__ import annotations

import hashlib
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


def _nivel(r: dict) -> int:
    return r.get("nivel_rotulo", config.NIVEL_FONTE)


def por_filtros(rotulos: list[dict], campeao: dict, desafiante: dict) -> list[dict]:
    return [{"numero_sei": r["numero_sei"], "real": int(bool(r["alto_verificado"])), "nivel_rotulo": _nivel(r),
             "campeao": alto_com_filtros(r["nota"], r["indicios"], campeao.get("filtros") or []),
             "desafiante": alto_com_filtros(r["nota"], r["indicios"], desafiante.get("filtros") or [])}
            for r in rotulos if r.get("indicios") is not None]


def ordem_reexecucao(rotulos: list[dict]) -> list[dict]:
    """Ordem FIXA em que a reexecução percorre o conjunto até o teto de casos: os riscos altos verdadeiros primeiro
    (sem eles a R2 e a R3 do portão não medem nada), depois os rotulados na FONTE PRIMÁRIA (o único gabarito que o
    portão julga — portao.gabarito) e o resto pelo hash do número. O corte por ordem alfabética
    (`rotulos[:40]`) pegava os primeiros órgãos e só 2 dos 4 altos verdadeiros da validação de 18/11/2026 — a R2
    reprovava qualquer lição antes de olhar o efeito dela. A ordem não depende do que campeão ou desafiante dizem."""
    return sorted(rotulos, key=lambda r: (not r["alto_verificado"], _nivel(r) < config.NIVEL_FONTE,
                                          hashlib.sha1(("reexec:" + r["numero_sei"]).encode()).hexdigest()))


def por_prompt(rotulos: list[dict], desafiante: dict, gerar, compliance_db: Path | None = None,
               max_casos: int | None = None, campeao: dict | None = None) -> list[dict]:
    """Reexecuta UM desafiante contra o campeão (ver `por_prompt_pareado`)."""
    return por_prompt_pareado(rotulos, campeao or {"licoes": [], "filtros": []}, {"_": desafiante}, gerar,
                              compliance_db, max_casos)["_"]


def por_prompt_pareado(rotulos: list[dict], campeao: dict, desafiantes: dict[str, dict], gerar,
                       compliance_db: Path | None = None, max_casos: int | None = None) -> dict[str, list[dict]]:
    """Reexecuta o CAMPEÃO e cada desafiante com o MESMO gerador, sobre a MESMA entrada de hoje, caso a caso e em
    seguida (o mesmo provedor da cascata tende a responder os dois). Comparar o desafiante com o laudo gravado
    meses antes media o motor e a captura de hoje, não a lição: o laudo gravado é de outro modelo (gemini 2.5,
    openrouter, haiku) e de outra versão da ficha. Ele segue no caso como `nota_gravada`, só para leitura.

    Percorre `ordem_reexecucao` até cada desafiante ter `max_casos` casos respondidos (caso sem resposta do campeão
    ou do desafiante não conta e o seguinte entra no lugar). Banco EM MEMÓRIA: nada vai a compliance.db, à fila do
    Opus (sem `item`) nem ao ledger (a linha de sombra é apagada antes da próxima versão regravar o processo)."""
    if gerar is None:
        raise ValueError("reexecução por prompt exige um gerador (LLM) injetado — o dry-run não reexecuta")
    from tools import lex_execucao as LX
    db = compliance_db or config.REPO / "data" / "compliance.db"
    teto = max_casos or config.ORCAMENTO["max_casos_reexecucao"]
    ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    sombra = sqlite3.connect(":memory:")
    out: dict[str, list[dict]] = {k: [] for k in desafiantes}
    anterior = LX._LICOES_SOMBRA

    def rodar(versao: dict, ns: str, f, obs) -> tuple[int | None, list, str | None]:
        LX._LICOES_SOMBRA = [armadilhas.POR_ID[i]["licao"] for i in versao.get("licoes") or []]
        # sem `item`: o laudo de sombra não pode entrar na fila de conferência do Opus (ele regravaria a produção)
        res = LX.avaliar_processo(sombra, ns, f[0] or "", f[1] or "", json.loads(f[2] or "[]"), json.loads(f[3] or "[]"),
                                  lambda p, s, t, item=None: gerar(p, s, t), obs_siafe=obs)
        m = sombra.execute("SELECT modelo FROM lex_execucao WHERE numero_sei=?", (ns,)).fetchone()
        sombra.execute("DELETE FROM lex_execucao WHERE numero_sei=?", (ns,))
        sombra.commit()
        v = (res or {}).get("verdict") or {}
        return v.get("nota_risco_execucao"), v.get("indicios") or [], m and m[0]

    try:
        sombra.execute(ro.execute("SELECT sql FROM sqlite_master WHERE name='lex_execucao'").fetchone()[0])
        ordem = ordem_reexecucao(rotulos)
        obs = LX.mapa_obs_siafe(ro, [r["numero_sei"] for r in ordem])
        for r in ordem:
            faltam = [k for k in desafiantes if len(out[k]) < teto]
            if not faltam:
                break
            ns = r["numero_sei"]
            f = ro.execute("SELECT objeto, valores, documentos, red_flags FROM sei_ficha WHERE numero_sei=?",
                           (ns,)).fetchone()
            if not f:
                continue
            nota_c, ind_c, motor_c = rodar(campeao, ns, f, obs)
            if nota_c is None:
                continue
            for k in faltam:
                nota_d, ind_d, motor_d = rodar(desafiantes[k], ns, f, obs)
                if nota_d is None:
                    continue
                out[k].append({"numero_sei": ns, "real": int(bool(r["alto_verificado"])), "nivel_rotulo": _nivel(r),
                               "campeao": alto_com_filtros(nota_c, ind_c, campeao.get("filtros") or []),
                               "desafiante": alto_com_filtros(nota_d, ind_d, desafiantes[k].get("filtros") or []),
                               "nota_campeao": nota_c, "nota_desafiante": nota_d, "nota_gravada": r.get("nota"),
                               "motor_campeao": motor_c, "motor_desafiante": motor_d})
    finally:
        LX._LICOES_SOMBRA = anterior
        ro.close()
        sombra.close()
    return out
