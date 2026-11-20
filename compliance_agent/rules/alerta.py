# -*- coding: utf-8 -*-
"""Identidade do alerta das regras: o TÍTULO (até 300 caracteres).

A dedup e a poda da tabela `alertas` reconhecem um alerta pelo título — por isso ele nunca muda de grafia.
Um alerta só nasce se o título não existe no banco NEM já saiu nesta mesma execução: o motor junta os
alertas numa lista e só os grava no fim, então a consulta ao banco não enxerga os da própria rodada.
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from compliance_agent.database.models import Alerta

TITULO_MAX = 300


class LoteAlertas:
    """Alertas novos de uma execução, sem repetir título (no banco ou na própria execução)."""

    def __init__(self, session: Session, novos: Optional[list[Alerta]] = None):
        self.session = session
        self.novos: list[Alerta] = list(novos or [])
        self._titulos: set[str] = {a.titulo for a in self.novos}

    def criar(self, tipo: str, severidade: str, titulo: str, descricao: str, evidencias: dict,
              pessoa=None, empresa=None, contrato=None, ordem_bancaria=None) -> Optional[Alerta]:
        titulo = titulo[:TITULO_MAX]
        if titulo in self._titulos or self.session.query(Alerta).filter_by(titulo=titulo).first():
            return None
        self._titulos.add(titulo)
        alerta = Alerta(
            tipo=tipo,
            severidade=severidade,
            titulo=titulo,
            descricao=descricao,
            evidencias=json.dumps(evidencias, ensure_ascii=False, default=str),
            pessoa_id=pessoa.id if pessoa else None,
            empresa_id=empresa.id if empresa else None,
            contrato_id=contrato.id if contrato else None,
            ordem_bancaria_id=ordem_bancaria.id if ordem_bancaria else None,
        )
        self.novos.append(alerta)
        return alerta
