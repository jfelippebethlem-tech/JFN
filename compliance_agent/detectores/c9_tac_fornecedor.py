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

        # PREVALÊNCIA DECIDE O EIXO. O limiar é absoluto, e numa unidade que paga 27% do total por
        # TAC um fornecedor com 29,8% é a NORMA, não a exceção. Medido em 2026-08-04: 24 dos 41
        # disparos do acervo estavam a menos de 2× a taxa da própria unidade, nove deles a 1,1×.
        # O achado não some — ele passa a apontar para quem de direito: a docstring deste detector
        # sempre disse que o vício é do ÓRGÃO, com o fornecedor como beneficiário.
        base = contexto.get("tac_unidade") or {}
        pct_unidade = base.get("pct")
        na_norma = (isinstance(pct_unidade, (int, float)) and pct_unidade > 0
                    and pct < 2 * float(pct_unidade))
        if na_norma:
            nivel = "medio" if nivel == "critico" else "fraco"
            res.valores["pct_da_unidade"] = pct_unidade
            res.valores["razao_sobre_a_unidade"] = round(pct / float(pct_unidade), 2)
            res.valores["padrao_e_do_orgao"] = True
        res.score = ancora(nivel)
        res.status = "confirmado"
        res.explicacao_inocente = ("passivo legítimo de serviço prestado sem cobertura contratual por "
                                   "falha administrativa do órgão — verificar atesto e justificativa no SEI")
        # A COMPARAÇÃO COM A UNIDADE VAI EM EVIDÊNCIA PRÓPRIA. Ela é o que muda o eixo do
        # achado, e emendada no fim da primeira frase morria no corte de 220 caracteres do
        # `achados_de_fornecedor` — o mesmo defeito de truncamento corrigido nesta casa hoje de
        # manhã, um nível adiante. Verificado no dado: nenhum dos 42 achados gravados exibia a
        # frase, embora o rebaixamento de grau já tivesse acontecido.
        if isinstance(pct_unidade, (int, float)) and pct_unidade:
            razao = pct / float(pct_unidade)
            res.add_evidencia(
                "tac_ranking_ugs (taxa da unidade)",
                (f"a unidade onde mais recebeu ({base.get('ug_nome') or base.get('ug')}) paga "
                 f"{pct_unidade:.1f}% por essa via — o fornecedor está a {razao:.1f}× a norma "
                 + ("local: o padrão é do ÓRGÃO e o contratado é beneficiário; investigar a "
                    "prática da unidade, não só a empresa" if na_norma
                    else "local, acima do que a unidade pratica")))
        res.add_evidencia(
            "ordens_bancarias (observação TFE)",
            f"{pct:.1f}% do valor pago via TAC/indenização/reconhecimento de dívida "
            f"(R$ {_brl(total_tac)} de R$ {_brl(float(tac.get('total') or 0))}; "
            f"{tac.get('n_tac')}/{tac.get('n')} OB; {cobertura})")
        return res
