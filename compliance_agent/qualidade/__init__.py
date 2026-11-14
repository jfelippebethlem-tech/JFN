# -*- coding: utf-8 -*-
"""qualidade — as regras de padrão, conformidade, correção, constância e as subjetivas do ecossistema JFN.

Fonte única: `config/qualidade_regras.yaml`. O que afirma algo ao dono: `config/qualidade_inventario.yaml`.
Documento canônico (gerado): `docs/REGRAS-DE-QUALIDADE.md`.

  regras.py        carrega e valida as regras; diz que verificador cada uma tem
  catraca.py       linha de base que só desce (o motor das catracas de regra)
  verificadores.py verificações puras de texto e de payload (sem rede, sem banco)
  inventario.py    enumera por código o que existe e confronta com o inventário
  sensores.py      roda em produção sobre o dado real; devolve violações
  juiz.py          juiz subjetivo (Claude pela ASSINATURA) — amostra por valor e risco, nota pela rubrica
  estado.py        consolida por sistema: regras, violações abertas, tendência (painel de conformidade)
  doc.py           gera o documento canônico
"""
