# -*- coding: utf-8 -*-
"""Alertas de emendas com o NOME do parlamentar → segundo cérebro (jfn-brain).

Decisão do dono, 14/11/2026: o autor da emenda é pessoa pública no exercício do mandato — o nome pode ir ao cérebro.
Até então o bloco `triagem_verificada` da propagação deixava `emendas_d2_*` de fora por trazer o nome no título.

O que vai: alerta de emenda cujo detector nomeia o autor (`TIPOS`: D2 concentração autor→destino, D6 empenho sem
pagamento), com triagem VERIFICADA (duas leituras + Opus) em prioridade `aprofundar`/`monitorar` e sem pessoa física
vinculada (`pessoa_id` nulo). D5 (retroalimentação eleitoral) fica fora: nomeia o SÓCIO doador, que é particular.

Cada memória leva o parlamentar, o fato (texto do detector), a FONTE, o ESTADO e a ressalva "indício não é acusação".
CPF nunca sai: é recortado aqui e, se algum escapar, o cliente do cérebro recusa o texto inteiro antes da rede. A
chave é o id do alerta e o texto não leva data de execução: repetir dá 'igual' no registro (nada duplica); mudou o
fato ou a triagem, vai como correção (`supersedes`).

Quem chama: `compliance_agent/propagacao.descobertas_sql`, pelo bloco `emendas_parlamentar` de
`config/propagacao.yaml` (cron */5). Só leitura no compliance.db.
"""
from __future__ import annotations

import json
import re
import sqlite3

TIPOS = ("emendas_d2_concentracao_autor", "emendas_d6_empenho_sem_pagamento")
ROTULO = {"emendas_d2_concentracao_autor": "concentração de emendas autor→destino",
          "emendas_d6_empenho_sem_pagamento": "empenho de emenda sem pagamento"}
FONTE_PADRAO = "API Portal da Transparência, /emendas"
RESSALVA = "Indício não é acusação."
# O cérebro funde memórias com similaridade > 0,96 (medido em 14/11/2026: com o texto inteiro do detector e uma
# ressalva longa, 3 parlamentares diferentes viraram a mesma memória). Por isso o texto é CURTO e o que distingue
# (nome, números, destino) vem primeiro: só a 1ª frase do detector, sem o prefixo "Indício de …:" nem a explicação.

_FONTE = re.compile(r"\s*\(fontes?:\s*([^)]*(?:\([^)]*\)[^)]*)*)\)\s*")
_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\*{3}\.?\d{3}\.?\d{3}-?\*{2}|\b\d{3}\.\*{3}\.\*{3}-\d{2}\b")
_CODIGO = re.compile(r"emenda (\d{6,})")
_AUTOR_DESC = re.compile(r"\bautor ([^,()]+?),")
_PREFIXO = re.compile(r"^Indício de [^:]{3,60}:\s*")
_FIM_FRASE = re.compile(r"(?<=[^\s.]{2}[.)])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])")

_SQL = f"""
SELECT a.id, a.tipo, a.titulo, a.descricao, a.evidencias, t.prioridade, t.nota, substr(t.em, 1, 10) AS em
FROM alertas a JOIN alertas_triagem t ON t.alerta_id = a.id
WHERE a.tipo IN ({",".join("?" * len(TIPOS))}) AND a.pessoa_id IS NULL
  AND t.estado = 'VERIFICADO' AND t.verificado_por IS NOT NULL AND t.prioridade IN ('aprofundar', 'monitorar')
ORDER BY a.id"""


def _limpo(s) -> str:
    return " ".join(_CPF.sub("[dado pessoal omitido]", str(s or "")).split())


def _parlamentar(con: sqlite3.Connection, tipo: str, titulo: str, descricao: str, evidencias: str) -> str | None:
    try:
        ev = json.loads(evidencias or "{}")
    except ValueError:
        ev = {}
    nome = (ev.get("autor") if isinstance(ev, dict) else None) or None
    if not nome and tipo == "emendas_d6_empenho_sem_pagamento":
        m = _CODIGO.search(titulo or "")
        if m:
            try:
                r = con.execute("SELECT autor_norm FROM emendas WHERE codigo = ? LIMIT 1", (m.group(1),)).fetchone()
            except sqlite3.Error:
                r = None
            nome = r[0] if r else None
        if not nome:
            m = _AUTOR_DESC.search(descricao or "")
            nome = m.group(1) if m else None
    nome = " ".join(str(nome or "").split())
    return nome or None


def descobertas(con: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """(chave, texto, assunto) de cada alerta de emenda VERIFICADO com o parlamentar identificado."""
    out = []
    for r in con.execute(_SQL, TIPOS).fetchall():
        aid, tipo, titulo, desc, ev, prio, nota, em = (r[i] for i in range(8))
        nome = _parlamentar(con, tipo, titulo, desc, ev)
        if not nome:
            continue                                 # sem o nome não é "alerta com parlamentar": fica no fluxo geral
        m = _FONTE.search(desc or "")
        fonte = _limpo(m.group(1)) if m else FONTE_PADRAO
        fato = _PREFIXO.sub("", _limpo(_FONTE.sub(" ", desc or "")))
        fato = (_FIM_FRASE.split(fato, maxsplit=1)[0] if fato else _limpo(titulo)).rstrip(".")
        nota_txt = f", nota {nota}/10" if nota is not None else ""
        texto = (f"Parlamentar autor da emenda: {_limpo(nome)} — {fato}. Fonte: {fonte}. Estado: VERIFICADO na triagem "
                 f"do JFN (duas leituras + Opus, {em}; {prio}{nota_txt}); segue indício. {RESSALVA} "
                 f"Alerta JFN #{aid}, {ROTULO[tipo]}; parlamentar é pessoa pública e a emenda, ato do mandato.")
        out.append((f"emenda:{aid}", texto, f"emenda parlamentar — {_limpo(nome)}"))
    return out
