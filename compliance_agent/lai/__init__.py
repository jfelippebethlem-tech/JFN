# -*- coding: utf-8 -*-
"""LAI automatizada — do alvo (processo, contrato, CNPJ) ao requerimento pronto para protocolar.

Um botão → `gerar(alvo)` reúne o que a casa já sabe (catálogo do SEI municipal, ContasRio/CCON,
D.O., documentos já obtidos), monta o requerimento com fundamento (Lei 12.527/2011; Lei Municipal
5.394/2012 ou Decreto Estadual 46.475/2018), lista NOMINALMENTE os documentos pedidos (nº SEI dos
documentos que a busca livre enxergou), grava .docx/.md em reports/ e registra o pedido com prazo
(20 dias + 10) em data/lai.db para cobrança. A submissão no e-SIC continua humana (gov.br do
requerente); o texto sai pronto para colar.
"""
from compliance_agent.lai.gerar import gerar  # noqa: F401
from compliance_agent.lai.registro import atualizar, listar, vencendo  # noqa: F401
