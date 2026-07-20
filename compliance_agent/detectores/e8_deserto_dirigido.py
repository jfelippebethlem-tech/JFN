# -*- coding: utf-8 -*-
"""Detector E8 — deserto/fracassado dirigido (certame inviável de propósito → contratação direta).

Mecanismo: o órgão publica edital com exigências que ninguém consegue (ou quer) atender; o certame
dá DESERTO (ninguém aparece) ou FRACASSADO (todos inabilitados/desclassificados) uma ou mais vezes;
em seguida contrata DIRETO o fornecedor pré-escolhido com amparo no art. 75 III da Lei 14.133/2021
(dispensa por licitação deserta/fracassada). O deserto é o meio; a dispensa é o fim.
Origem metodológica: redflags.eu "unsuccessful procedure" + prática TCE; fecha a lacuna
`deserto_fracassado_dirigido` do catálogo canônico (knowledge/catalogo_vicios.py).

`avaliar(contexto)` espera:
  contexto["processo"]: id do caso/órgão+objeto.
  contexto["serie"]: list[dict] — certames do MESMO órgão e objeto comparável, em ordem cronológica:
      {situacao: "deserta"|"fracassada"|"homologada"|..., data?: "YYYY-MM-DD", certame?, objeto?}.
  contexto["desfecho"] (opcional): {tipo: "dispensa"|"contratacao_direta"|"novo_certame"|None,
      amparo?: str (ex.: "art. 75 III"), data?, contratado_cnpj?, valor?}.
  contexto["ajuste_entre_certames"] (opcional bool): houve REPUBLICAÇÃO com flexibilização real das
      exigências entre as tentativas (exculpatória: órgão tentou abrir o mercado e mesmo assim
      deu deserto → mercado raso genuíno, não desenho).

Régua (âncoras no CÓDIGO, nunca no prompt):
  • ≥2 desertos/fracassados consecutivos SEM ajuste + desfecho dispensa/direta ..... 'critico' (1.0)
  • 1 deserto/fracassado + desfecho dispensa/direta ................................ 'forte'  (0.85)
  • ≥2 desertos/fracassados sem desfecho conhecido ................................. 'medio'  (0.6)
  • desertos COM ajuste real entre tentativas → exculpatória (rebaixa 1 nível; se vira 'fraco',
    descarta — órgão diligente não é suspeito por mercado raso)
  • série vazia/sem situação aferível → nao_avaliavel (INDISPONÍVEL ≠ 0)

Honesto: deserto isolado sem dispensa NÃO pontua (mercado raso existe); indício ≠ acusação.
"""
from __future__ import annotations

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora

_SITUACOES_FALHA = ("deserta", "deserto", "fracassada", "fracassado")
_DESFECHOS_DIRETA = ("dispensa", "contratacao_direta", "inexigibilidade")


def _eh_falha(situacao: str | None) -> bool:
    s = (situacao or "").strip().lower()
    return any(s.startswith(f) for f in _SITUACOES_FALHA)


class E8DesertoDirigido(Detector):
    """Detector E8 — deserto/fracassado reincidente convertido em contratação direta."""

    id = "E8"
    nome = "Deserto/fracassado dirigido (edital inviável → dispensa)"
    familia = "desenho_certame"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        serie = [c for c in (contexto.get("serie") or []) if isinstance(c, dict)]
        aferiveis = [c for c in serie if (c.get("situacao") or "").strip()]
        if not aferiveis:
            res.motivo_refutacao = ("nao_avaliavel: série de certames ausente ou sem campo `situacao` "
                                    "aferível (INDISPONÍVEL ≠ 0) — sem base para deserto/fracassado")
            res.valores = {"n_serie": len(serie)}
            return res

        falhas = [c for c in aferiveis if _eh_falha(c.get("situacao"))]
        desfecho = contexto.get("desfecho") or {}
        tipo_desfecho = (desfecho.get("tipo") or "").strip().lower()
        virou_direta = tipo_desfecho in _DESFECHOS_DIRETA
        ajuste = bool(contexto.get("ajuste_entre_certames"))

        valores = {
            "n_serie": len(aferiveis),
            "n_desertos_fracassados": len(falhas),
            "situacoes": [c.get("situacao") for c in aferiveis][:12],
            "desfecho": tipo_desfecho or None,
            "amparo_desfecho": desfecho.get("amparo"),
            "ajuste_entre_certames": ajuste,
        }

        if not falhas:
            res.status = "descartado"
            res.valores = valores
            res.motivo_refutacao = "nenhum certame deserto/fracassado na série — sem o padrão do E8"
            res.explicacao_inocente = "certames da série tiveram competição normal"
            return res

        # régua (docstring): nível base pela combinação reincidência × desfecho
        if len(falhas) >= 2 and virou_direta:
            nivel = "critico"
        elif virou_direta:
            nivel = "forte"
        elif len(falhas) >= 2:
            nivel = "medio"
        else:
            res.status = "descartado"
            res.valores = valores
            res.motivo_refutacao = ("1 deserto/fracassado isolado, sem conversão em contratação direta — "
                                    "mercado raso é explicação inocente suficiente (não pontua)")
            res.explicacao_inocente = "objeto de nicho/mercado raso; órgão pode relicitar com ajustes"
            return res

        if ajuste:
            # exculpatória: o órgão FLEXIBILIZOU entre as tentativas — deserto apesar da diligência
            rebaixo = {"critico": "forte", "forte": "medio", "medio": "fraco"}[nivel]
            if rebaixo == "fraco":
                res.status = "descartado"
                res.valores = valores
                res.motivo_refutacao = ("desertos COM republicação flexibilizada entre tentativas — órgão "
                                        "diligente + mercado raso explicam o padrão (exculpatória)")
                res.explicacao_inocente = "edital foi ajustado e ainda assim não houve interessados"
                return res
            nivel = rebaixo

        res.status = "confirmado"
        res.score = ancora(nivel)
        res.valores = valores
        razoes = [f"{len(falhas)} certame(s) deserto(s)/fracassado(s) na série de {len(aferiveis)}"]
        if virou_direta:
            razoes.append(f"convertido em {tipo_desfecho}"
                          + (f" ({desfecho.get('amparo')})" if desfecho.get("amparo") else
                             " — conferir o amparo (art. 75 III exige licitação REGULAR frustrada)"))
        if ajuste:
            razoes.append("houve ajuste entre tentativas — exculpatória parcial aplicada (1 nível)")
        res.motivo_refutacao = "; ".join(razoes)
        res.add_evidencia(
            fonte="série de certames do órgão/objeto",
            trecho=(f"situações={valores['situacoes']}; desfecho={tipo_desfecho or 'desconhecido'}"))
        res.explicacao_inocente = (
            "FALSO POSITIVO a descartar (spec E8): mercado GENUINAMENTE raso (objeto de nicho, valores "
            "baixos, prazo curto de mercado aquecido) dá deserto sem desenho; a exculpatória correta é a "
            "republicação com flexibilização REAL das exigências. Antes de peça: comparar as exigências "
            "das tentativas (diff E5) e o vínculo do contratado direto com o desenho do edital (E7/C).")
        return res
