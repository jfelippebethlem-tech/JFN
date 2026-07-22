# -*- coding: utf-8 -*-
"""Detector C7 — sancionada contratada (sanção vigente NA DATA do certame/contrato).

Fecha o vício `sancionada_contratada` do catálogo canônico (era `parcial`: a checagem vivia
espalhada em lex_sancoes/cruzamentos_intel e na família fraude_cadastral do índice, fora do
REGISTRO — sem grau de flag nem escalada padronizados).

Mecanismo: contratar quem está impedido/inidôneo/suspenso é vedação OBJETIVA (Lei 14.133/2021
art. 156 §§4º-5º; art. 14; Lei 8.666/93 art. 87 III-IV para sanções da era anterior). O teste é
determinístico — sanção IMPEDITIVA com vigência cobrindo a data de referência → violação de teto
legal (pode fundamentar flag A via editais/flags.grau_flag, origem 'deterministico').
CNEP-Multa e afins NÃO impedem contratar → indício 'medio' (empresa punida recontratada merece
verificação de alcance da sanção, não acusação).

`avaliar(contexto)` espera (data-driven, como os demais):
  contexto["processo"]: id do caso.
  contexto["contratado_cnpj"]: CNPJ (com ou sem máscara).
  contexto["data_referencia"]: "YYYY-MM-DD" da publicação/assinatura.
  contexto["sancoes"]: list[dict] {cadastro, categoria, data_inicio, data_fim, orgao?, uf?}
      — as sanções do CNPJ (o chamador consulta; use `montar_ctx_sancoes` p/ preencher da base).

Régua (âncoras no CÓDIGO):
  • sanção IMPEDITIVA vigente na data ............ 'critico' (1.0), teste_objetivo='violado'
  • sanção NÃO-impeditiva (multa etc.) vigente ... 'medio' (0.6)
  • sanções existem mas nenhuma vigente na data .. descartado (histórico ≠ vedação atual)
  • sem data de referência ou lista ausente ...... nao_avaliavel (INDISPONÍVEL ≠ 0)
"""
from __future__ import annotations

import sqlite3

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora

# categorias CEIS/CNEP que VEDAM contratar (art. 156 §§4º-5º; art. 87 III-IV da 8.666)
_IMPEDITIVAS = ("impedimento", "proibicao de contratar", "proibição de contratar",
                "inidoneidade", "suspensão", "suspensao")
# multa/publicação extraordinária/demissão/incentivos: punição sem vedação de contratar
_SO_DIGITOS = str.maketrans("", "", "./- ")


def _limpa(cnpj: str) -> str:
    return (cnpj or "").translate(_SO_DIGITOS)


def _eh_impeditiva(categoria: str) -> bool:
    c = (categoria or "").lower()
    # "suspensão/interdição das atividades" é sanção operacional, não vedação de contratar
    if "interdição" in c or "interdicao" in c:
        return False
    return any(t in c for t in _IMPEDITIVAS)


def montar_ctx_sancoes(con: sqlite3.Connection, cnpj: str) -> list[dict]:
    """Sanções federais do CNPJ (CEIS+CNEP) no formato que o C7 consome."""
    rows = con.execute(
        "SELECT cadastro, categoria, data_inicio, data_fim, orgao, uf FROM sancoes_federais "
        "WHERE REPLACE(REPLACE(REPLACE(cpf_cnpj,'.',''),'/',''),'-','')=?",
        (_limpa(cnpj),)).fetchall()
    return [{"cadastro": r[0], "categoria": r[1], "data_inicio": r[2], "data_fim": r[3],
             "orgao": r[4], "uf": r[5]} for r in rows]


class C7SancionadaContratada(Detector):
    """Detector C7 — sanção vigente à época da contratação (vedação objetiva)."""

    id = "C7"
    nome = "Sancionada contratada (sanção vigente à época)"
    familia = "violacao_legal"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        data = (contexto.get("data_referencia") or "").strip()[:10]
        sancoes = contexto.get("sancoes")
        if not data or sancoes is None:
            res.motivo_refutacao = ("nao_avaliavel: sem data_referencia ou lista de sanções "
                                    "(INDISPONÍVEL ≠ 0) — consultar sancoes_federais antes")
            return res

        vigentes = [s for s in sancoes
                    if (s.get("data_inicio") or "9999") <= data
                    and (not s.get("data_fim") or s["data_fim"] >= data)]
        impeditivas = [s for s in vigentes if _eh_impeditiva(s.get("categoria"))]
        res.valores = {
            "data_referencia": data,
            "n_sancoes": len(sancoes),
            "n_vigentes": len(vigentes),
            "n_impeditivas": len(impeditivas),
            "categorias_vigentes": sorted({s.get("categoria") or "?" for s in vigentes})[:6],
        }

        if not sancoes or not vigentes:
            res.status = "descartado"
            res.motivo_refutacao = ("sem sanção vigente na data de referência "
                                    f"({len(sancoes)} histórica(s) fora da vigência)"
                                    if sancoes else "CNPJ sem registro no CEIS/CNEP")
            return res

        if impeditivas:
            s = impeditivas[0]
            res.score = ancora("critico")
            res.status = "confirmado"
            res.valores["teste_objetivo"] = "violado"  # vedação legal objetiva → flag A possível
            res.evidencia = [(
                f"{s.get('cadastro')}: '{s.get('categoria')}' vigente em {data} "
                f"({s.get('data_inicio')} → {s.get('data_fim') or 'sem prazo'}; "
                f"órgão sancionador: {s.get('orgao') or '?'}) — Lei 14.133/2021 art. 156 §§4º-5º"
            )]
            return res

        s = vigentes[0]
        res.score = ancora("medio")
        res.status = "confirmado"
        res.valores["teste_objetivo"] = "nao_aferivel"  # punição sem vedação de contratar
        res.evidencia = [(
            f"{s.get('cadastro')}: '{s.get('categoria')}' vigente em {data} — sanção NÃO "
            "impeditiva de contratar; verificar alcance/condições no processo sancionador"
        )]
        return res
