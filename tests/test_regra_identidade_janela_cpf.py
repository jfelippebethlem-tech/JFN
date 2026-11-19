# -*- coding: utf-8 -*-
"""Catraca: casar CPF mascarado de FOLHA com o do QSA só pela régua única (`identidade_pessoa`).

A janela que a folha publica VARIA POR FONTE (GESPERJ 4–9, DPRJ 3–8 — controle positivo 13/11 e
19/11/2026). A casa errou isto três vezes com o mesmo atalho: fatiar strings como se toda folha
tivesse a mesma janela (`frag_qsa[0:5] == frag_folha[1:6]`, `d[1:6]`). No sócio-na-folha o atalho
produziu 911 "homônimos" e 0 casamento no Executivo. Esta catraca barra o atalho de volta: comparação
de fragmento de CPF entre bases passa por `posicoes_qsa`/`posicoes_folha`/`comparar_cpf`.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ATALHOS = [
    re.compile(r"\[0:5\]\s*==\s*[\w\"'\]\[]+\[1:6\]"),     # frag_qsa[0:5] == frag_folha[1:6]
    re.compile(r"\[1:6\]\s*==\s*[\w\"'\]\[]+\[0:5\]"),
    re.compile(r"return d\[1:6\] if len\(d\) == 6"),        # 'posições 4-8 da folha' presumindo 3-8
]
PASTAS = ["compliance_agent", "tools", "rotas"]


def test_ninguem_compara_fragmento_de_cpf_fatiando_string():
    achados = []
    for pasta in PASTAS:
        for f in (RAIZ / pasta).rglob("*.py"):
            txt = f.read_text(encoding="utf-8", errors="ignore")
            for rx in ATALHOS:
                for m in rx.finditer(txt):
                    linha = txt.count("\n", 0, m.start()) + 1
                    achados.append(f"{f.relative_to(RAIZ)}:{linha}: {m.group(0)}")
    assert not achados, ("comparação de CPF mascarado presumindo UMA janela para toda folha — use "
                         "compliance_agent.identidade_pessoa (posicoes_qsa/posicoes_folha/comparar_cpf):\n"
                         + "\n".join(achados))


# ── 2ª rodada (19/11/2026): módulos que casavam pessoa SÓ PELO NOME e passaram para a régua ──────────────
# Cada função listada aqui foi tratada; a catraca impede que volte a casar só pelo nome: tem de usar
# `identidade_pessoa` e não pode agrupar pessoa por coluna de nome sem o documento.
TRATADOS = {
    "compliance_agent.cruzamentos_intel": ["socio_oculto", "nepotismo", "nepotismo_cruzado", "grafo_familias",
                                           "porta_giratoria"],
    "compliance_agent.lex_conflito": ["conflito", "_identidade_socio_folha"],
    "compliance_agent.rede_societaria": ["rede_por_socio"],
    "compliance_agent.grafo_cartel": ["socios_compartilhados"],
    "compliance_agent.emendas.pericia": ["d5_retroalimentacao_eleitoral"],
    "tools.agente_publico_reverso": ["fila"],
    "compliance_agent.investigacao_dd": ["_coletar_beneficios_pep"],
}
# função que delega a identidade a um auxiliar tratado acima: o auxiliar é o marcador exigido
DELEGA = {("compliance_agent.lex_conflito", "socios_agentes_publicos"): "_identidade_socio_folha",
          # folha municipal sem CPF: a identidade fica INDETERMINADA e a faixa FORTE é vedada
          ("compliance_agent.pcrj.fantasma_servidor", "detectar"): "FALTA_IDENTIDADE"}
# parentesco por sobrenome: a saída tem de separar hipótese de achado
PARENTESCO = {"compliance_agent.cruzamentos_intel": ["nepotismo", "nepotismo_cruzado", "grafo_familias"]}
_AGRUPA_SO_NOME = re.compile(r"GROUP BY\s+[\w.]*(?:socio_nome|nome_socio|nome_norm|\bnome)\b(?![^\"']*doc)", re.I)


def _fonte(mod: str, fn: str) -> str:
    import importlib
    import inspect
    return inspect.getsource(getattr(importlib.import_module(mod), fn))


def test_modulos_tratados_casam_pessoa_pela_regua_e_nao_so_pelo_nome():
    erros = []
    for mod, fns in TRATADOS.items():
        for fn in fns:
            src = _fonte(mod, fn)
            corpo = src.split('"""', 2)[-1] if src.count('"""') >= 2 else src   # ignora a docstring
            if "identidade_pessoa" not in corpo:
                erros.append(f"{mod}.{fn}: não usa compliance_agent.identidade_pessoa")
            m = _AGRUPA_SO_NOME.search(corpo)
            if m:
                erros.append(f"{mod}.{fn}: agrupa pessoa só pelo nome ({m.group(0)!r}) — use identidade_pessoa.chave_qsa")
    for (mod, fn), marcador in DELEGA.items():
        if marcador not in _fonte(mod, fn).split('"""', 2)[-1]:
            erros.append(f"{mod}.{fn}: deixou de passar pela régua ({marcador})")
    for mod, fns in PARENTESCO.items():
        for fn in fns:
            corpo = _fonte(mod, fn).split('"""', 2)[-1]
            if "selo_parentesco" not in corpo:
                erros.append(f"{mod}.{fn}: parentesco por sobrenome sem `selo_parentesco` (hipótese ≠ achado)")
    assert not erros, "\n".join(erros)
