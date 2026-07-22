# -*- coding: utf-8 -*-
"""Detector P6 — contratação direta acima do limite legal de dispensa.

Fecha (parcialmente) o vício `contratacao_direta_indevida` do catálogo canônico (era `parcial`:
os limites viviam em compliance_agent/limites_dispensa.py como ferramenta transversal, fora do
REGISTRO — sem grau de flag nem escalada). Este detector cobre o ramo OBJETIVO do vício: dispensa
por VALOR (art. 75 I-II) acima do teto do exercício. Os ramos subjetivos (inexigibilidade sem
exclusividade real, emergência fabricada) seguem com R5/P5.

Mecanismo: dispensa "por valor" só cabe até o limite anual (Decretos de atualização IPCA-E,
art. 182). Valor acima do teto SEM outro amparo declarado (emergência art. 75 VIII, deserto
art. 75 III, etc.) = teste determinístico de teto legal → pode fundamentar flag A.

`avaliar(contexto)` espera:
  contexto["processo"]: id.
  contexto["modalidade_id"]: código PNCP (8=dispensa, 9=inexigibilidade) — só dispensa testa teto.
  contexto["valor_total"]: R$ da contratação.
  contexto["ano"]: exercício (da publicação).
  contexto["tipo_objeto"] (opcional): 'obras' | 'compras' (default 'compras' — teto MENOR, e o
      resultado só é 'violado' se estourar TAMBÉM o teto de obras: acima de qualquer amparo por
      valor; entre os dois tetos → 'medio' com a dúvida declarada).
  contexto["amparo_declarado"] (opcional): inciso citado no processo (ex.: "art. 75 III").
      Amparo ≠ valor declarado → exculpa o teste de teto (não é dispensa por valor).

Régua (âncoras no CÓDIGO):
  • dispensa, valor > teto de OBRAS do ano, sem outro amparo ......... 'critico' (1.0), violado
  • dispensa, valor > teto do tipo informado (ou 'compras') mas ≤ teto
    de obras, sem outro amparo ....................................... 'medio' (0.6) — pode ser
    engenharia; a dúvida é declarada, não presumida contra o gestor
  • amparo declarado ≠ por-valor (III, VIII, etc.) .................. descartado (outro instituto)
  • inexigibilidade (art. 74 não tem teto) ........................... nao_avaliavel p/ teto
  • sem valor/ano .................................................... nao_avaliavel (INDISP ≠ 0)
"""
from __future__ import annotations

import re

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora
from compliance_agent.limites_dispensa import ato_normativo, limite_dispensa

MODALIDADE_DISPENSA = 8
MODALIDADE_INEXIGIBILIDADE = 9

# amparos do art. 75 que NÃO são "por valor" (I-II): se declarados, o teto não se aplica
_RX_AMPARO_NAO_VALOR = re.compile(r"\b(iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv|xvi)\b", re.I)


class P6DiretaIndevida(Detector):
    """Detector P6 — dispensa por valor acima do limite do exercício (art. 75 I-II c/c art. 182)."""

    id = "P6"
    nome = "Contratação direta acima do limite de dispensa"
    familia = "violacao_legal"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        modalidade = contexto.get("modalidade_id")
        if modalidade == MODALIDADE_INEXIGIBILIDADE:
            res.motivo_refutacao = ("nao_avaliavel: inexigibilidade (art. 74) não tem teto de "
                                    "valor — o pressuposto é inviabilidade de competição (R5)")
            return res
        if modalidade != MODALIDADE_DISPENSA:
            res.motivo_refutacao = "nao_avaliavel: não é contratação direta (modalidade competitiva)"
            return res

        valor = contexto.get("valor_total")
        ano = contexto.get("ano")
        if not valor or not ano:
            res.motivo_refutacao = ("nao_avaliavel: dispensa sem valor_total/ano apuráveis "
                                    "(INDISPONÍVEL ≠ 0)")
            return res

        amparo = str(contexto.get("amparo_declarado") or "")
        if amparo and _RX_AMPARO_NAO_VALOR.search(amparo):
            res.status = "descartado"
            res.valores = {"amparo_declarado": amparo}
            res.motivo_refutacao = (f"amparo declarado '{amparo}' não é dispensa por valor "
                                    "(art. 75 I-II) — teto não se aplica a este instituto")
            return res

        tipo = (contexto.get("tipo_objeto") or "compras").strip().lower()
        teto_tipo = limite_dispensa(int(ano), "obras" if tipo.startswith("obra") else "compras")
        teto_obras = limite_dispensa(int(ano), "obras")
        res.valores = {
            "valor_total": float(valor), "ano": int(ano), "tipo_objeto": tipo,
            "teto_tipo": teto_tipo, "teto_obras": teto_obras, "ato": ato_normativo(int(ano)),
        }

        if float(valor) <= teto_tipo:
            res.status = "descartado"
            res.motivo_refutacao = (f"R$ {float(valor):,.2f} dentro do limite de dispensa "
                                    f"do exercício ({ato_normativo(int(ano))})")
            return res

        if float(valor) > teto_obras:
            res.score = ancora("critico")
            res.status = "confirmado"
            res.valores["teste_objetivo"] = "violado"  # acima de QUALQUER teto por valor → flag A
            res.evidencia = [(
                f"dispensa de R$ {float(valor):,.2f} em {ano} — acima até do teto de OBRAS "
                f"(R$ {teto_obras:,.2f}; {ato_normativo(int(ano))}) sem outro amparo declarado "
                "(Lei 14.133/2021 art. 75 I-II c/c art. 182)"
            )]
            return res

        res.score = ancora("medio")
        res.status = "confirmado"
        res.valores["teste_objetivo"] = "nao_aferivel"  # pode ser engenharia (teto maior) — dúvida declarada
        res.evidencia = [(
            f"dispensa de R$ {float(valor):,.2f} em {ano} — acima do teto de "
            f"'{tipo}' (R$ {teto_tipo:,.2f}) mas dentro do de obras (R$ {teto_obras:,.2f}); "
            "verificar se o objeto é engenharia antes de qualquer conclusão"
        )]
        return res
