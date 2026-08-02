# -*- coding: utf-8 -*-
"""Detector C9 — fornecedor pago majoritariamente FORA de contrato regular (TAC/indenização).

Fecha a lacuna medida no confronto de 2026-08-01: RF-TAC existia como narrativa do Lex
(`reporting/detector_tac.py`) mas nenhum detector do REGISTRO pontuava o sinal — AVIV (97,2%
do valor via TAC), LEFE (81,1%) e o grupo Caneca passavam com todos os detectores de
fornecedor `nao_avaliavel`.

Mecanismo: pagamento por Termo de Ajuste de Contas/indenização/reconhecimento de dívida é
regularização *a posteriori* (art. 59, par. único, Lei 8.666; jurisprudência TCU sobre
emergência fabricada por desídia) — sem certame, sem habilitação, preço sem disputa. Ser pago
assim UMA vez é sanável; ser pago majoritariamente assim, por anos, indica que o vínculo com o
órgão não passa pelo dever de licitar (vício do ÓRGÃO, com o fornecedor como beneficiário).

`avaliar(contexto)` espera (data-driven, como C7):
  contexto["processo"]: id do caso (o CNPJ, no runner de fornecedor).
  contexto["tac"]: dict de `reporting.detector_tac.tac_por_cnpj`/`medir_tac`
      {n, n_tac, total, total_tac, pct, n_sem_obs, cobertura}.

Régua (âncoras no CÓDIGO; espelha `detector_tac._severidade`):
  • pct ≥ 50% — ou pct ≥ 30% com R$ 100M+ de TAC ......... 'critico' (1.0)
  • pct ≥ 30% — ou pct ≥ 10% com R$ 50M+ de TAC .......... 'medio' (0.6)
  • pct < 10% sem reforço absoluto ....................... descartado (ajuste pontual legítimo)
  • sem contexto ou cobertura INDISPONIVEL ............... nao_avaliavel (INDISPONÍVEL ≠ 0)
"""
from __future__ import annotations

from compliance_agent.coerencia_valores import _brl
from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora


class C9TacFornecedor(Detector):
    """Detector C9 — % do valor recebido via TAC/indenização (fora de contrato regular)."""

    id = "C9"
    nome = "Pagamento majoritário por TAC/indenização (fora de contrato)"
    familia = "perfil"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("cnpj") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        tac = contexto.get("tac")
        if not isinstance(tac, dict) or not tac:
            res.motivo_refutacao = ("nao_avaliavel: sem medição de TAC no contexto — preencher "
                                    "com reporting.detector_tac.tac_por_cnpj (INDISPONÍVEL ≠ 0)")
            return res
        cobertura = str(tac.get("cobertura") or "")
        if cobertura.startswith("INDISPONIVEL") or not tac.get("n"):
            res.motivo_refutacao = f"nao_avaliavel: cobertura da observação das OB = {cobertura or 'vazia'}"
            return res

        pct = float(tac.get("pct") or 0.0)
        total_tac = float(tac.get("total_tac") or 0.0)
        res.valores = {"pct": pct, "total_tac": total_tac, "total": tac.get("total"),
                       "n": tac.get("n"), "n_tac": tac.get("n_tac"), "cobertura": cobertura}

        if pct >= 50 or (pct >= 30 and total_tac >= 100_000_000):
            nivel = "critico"
        elif pct >= 30 or (pct >= 10 and total_tac >= 50_000_000):
            nivel = "medio"
        else:
            res.status = "descartado"
            res.motivo_refutacao = (f"TAC {pct:.1f}% do valor (R$ {_brl(total_tac)}) abaixo do limiar — "
                                    "regularização pontual não é padrão")
            return res

        res.score = ancora(nivel)
        res.status = "confirmado"
        res.explicacao_inocente = ("passivo legítimo de serviço prestado sem cobertura contratual por "
                                   "falha administrativa do órgão — verificar atesto e justificativa no SEI")
        res.add_evidencia(
            "ordens_bancarias (observação TFE)",
            f"{pct:.1f}% do valor pago via TAC/indenização/reconhecimento de dívida "
            f"(R$ {_brl(total_tac)} de R$ {_brl(float(tac.get('total') or 0))}; "
            f"{tac.get('n_tac')}/{tac.get('n')} OB; {cobertura})")
        return res
