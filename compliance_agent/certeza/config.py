# -*- coding: utf-8 -*-
"""Caminhos, chaves e tetos da certeza. O que MUDA algo fora de `data/certeza/` nasce desligado:

  JFN_CERTEZA_SINCRONIZAR=1  reescreve, nas notas do vault, o número ancorado a um fato quando o fato mudou
  JFN_CERTEZA_CEREBRO=1      registra os fatos vigentes no segundo cérebro (fila de `cerebro_compartilhado`)
  JFN_CERTEZA_GATILHOS=1     permite instalar no compliance.db os gatilhos de faixa dos contratos
  arquivo data/certeza/KILL  (ou JFN_CERTEZA_KILL=1) desliga os três, sem mexer no resto
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NIVEL_ESTIMATIVA, NIVEL_AGREGADO, NIVEL_FONTE = 0, 1, 2
ESTADOS = ("VERIFICADO", "A CONFERIR", "PENDENTE", "INDISPONIVEL", "REFUTADO")
UNIDADES = ("BRL", "contagem", "percentual", "indice")
# Valor monetário plausível: a maior OB contabilizada do SIAFE é de R$ 1,5 bi (medido em 18/11/2026); o orçamento do
# Estado inteiro é da ordem de R$ 1e11. Acima disto é sentinela ou erro de unidade, nunca dado.
BRL_MAX = 9e11
# Base de um fato de natureza "pago" que pode sair VERIFICADO: OB Contabilizada, não devolvida, e com status de
# envio que não é intermediário (`siafe_status_ob.INTERMEDIARIOS`: 'Enviado ao Banco', 'Aguardando Envio'…).
BASE_PAGO_CONFIRMADO = "ob_contabilizada_confirmada"
TETO_CEREBRO_CICLO = 20       # fatos novos/corrigidos enviados à fila do cérebro por ciclo
TETO_BUSCAS_CEREBRO = 12      # consultas ao cérebro por ciclo (verificador de menção)
TETO_ARQUIVOS_TEXTO = 6000    # notas/documentos lidos por ciclo pelo verificador


def dados() -> Path:
    d = Path(os.environ.get("JFN_CERTEZA_DIR") or REPO / "data" / "certeza")
    d.mkdir(parents=True, exist_ok=True)
    return d


def banco() -> Path:
    return dados() / "certeza.db"


def morto() -> bool:
    return os.environ.get("JFN_CERTEZA_KILL") == "1" or (dados() / "KILL").exists()


def ligado(chave: str) -> bool:
    """chave: SINCRONIZAR | CEREBRO | GATILHOS."""
    return os.environ.get(f"JFN_CERTEZA_{chave}") == "1" and not morto()
