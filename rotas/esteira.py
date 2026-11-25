# -*- coding: utf-8 -*-
"""Rotas das LENTES da Esteira Única no painel (O7.2, plano mestre v2 §3.6 e §8 "Lentes no painel").

  /api/esteira/lentes            catálogo das lentes de config/lentes.yaml (nome, descrição, esfera, filtro, paridade)
                                 + o frescor da visão de cada uma — o seletor global do painel lê daqui
  /api/esteira/lente?lente=<x>   o recorte da lente: SÓ a visão materializada `lente_<x>` do E15
                                 (compliance_agent/aplicacao/lentes_resumo.py); sem visão ⇒ INDISPONÍVEL (503), nunca
                                 cálculo em request (benefícios lê 2,3 GB; o painel só lê visão pronta)

Toda resposta que aplicou a lente leva `X-JFN-Lente: <nome>` — é por esse cabeçalho que o painel diz, em cada aba,
quais consultas foram recortadas e quais mostram o universo inteiro.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/esteira/lentes")
def api_esteira_lentes():
    """Lentes declaradas (UGs conferidas contra o índice do SIAFE no carregamento) e o estado da visão de cada uma."""
    from compliance_agent.aplicacao.estagios import materializar as M
    from compliance_agent.fluxo import lentes as L
    try:
        cfg = L.carregar()
    except (OSError, L.ErroLente) as exc:          # configuração inválida ⇒ seletor sem lente, com o motivo
        return JSONResponse({"ok": False, "estado": "INDISPONIVEL", "erro": f"config/lentes.yaml: {exc}"})
    fr = {i["visao"]: i for i in M.frescor()["itens"]}
    lentes = []
    for nome, l in cfg.items():
        f = fr.get(f"lente_{nome}") or {}
        lentes.append({"lente": nome, "descricao": l.descricao, "esfera": l.esfera, "prioridade": l.prioridade,
                       "eixos_extra": list(l.eixos_extra), "paridade": l.paridade,
                       "visao": {"estado": f.get("estado", "INDISPONIVEL"), "gerado_em": f.get("gerado_em"),
                                 "idade_s": f.get("idade_s"), "slo_s": f.get("slo_s"), "universo": f.get("universo")}})
    return JSONResponse({"ok": True, "fonte": "config/lentes.yaml + data/visoes/lente_*.meta.json (E15)",
                         "lentes": lentes})


@router.get("/api/esteira/lente")
def api_esteira_lente(lente: str = ""):
    from compliance_agent.aplicacao.estagios import materializar as M
    nome = f"lente_{lente}"
    if nome not in M.VISOES:
        return JSONResponse({"ok": False, "erro": f"lente desconhecida: {lente!r}",
                             "validas": sorted(v.removeprefix("lente_") for v in M.VISOES if v.startswith("lente_"))},
                            status_code=404)
    pronta = M.resposta(nome)
    if pronta is None:
        return JSONResponse({"ok": False, "estado": "INDISPONIVEL", "lente": lente,
                             "erro": f"a visão da lente {lente} ainda não foi materializada (E15: `materializar rodar "
                                     f"--visao {nome}`) — INDISPONÍVEL não é zero"},
                            status_code=503, headers={"X-JFN-Visao": f"ausente:{nome}"})
    pronta.headers["X-JFN-Lente"] = lente
    return pronta
