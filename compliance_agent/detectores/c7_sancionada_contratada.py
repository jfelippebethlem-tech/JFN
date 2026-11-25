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

ABRANGÊNCIA POR ENTE (O4.9). A sanção só VEDA o contrato se alcança o COMPRADOR. Lei 14.133/2021 — VERBATIM em
L14133.htm (md5 5107e213168afb4c15a36665e6695c58): art. 156 §4º, o impedimento "impedirá o responsável de licitar ou
contratar no âmbito da Administração Pública direta e indireta do ente federativo que tiver aplicado a sanção"; §5º,
a inidoneidade, "no âmbito da Administração Pública direta e indireta de todos os entes federativos". A régua de
alcance é a única da casa (`sancao_abrangencia.veda_comprador_rj`; `contexto["casa_compradora"]`, padrão "estado" —
a varredura por UG é do Estado do RJ). Impeditiva vigente que NÃO alcança o comprador (impedimento de outro ente,
suspensão de outro órgão) é risco reputacional: 'medio', teste_objetivo='fora_da_abrangencia', nunca 'violado'.

Régua (âncoras no CÓDIGO):
  • sanção IMPEDITIVA vigente na data e que ALCANÇA o comprador ... 'critico' (1.0), teste_objetivo='violado'
  • sanção IMPEDITIVA vigente que NÃO alcança o comprador ......... 'medio' (0.6), teste_objetivo='fora_da_abrangencia'
  • sanção NÃO-impeditiva (multa etc.) vigente ... 'medio' (0.6)
  • sanções existem mas nenhuma vigente na data .. descartado (histórico ≠ vedação atual)
  • sem data de referência ou lista ausente ...... nao_avaliavel (INDISPONÍVEL ≠ 0)
"""
from __future__ import annotations

import sqlite3

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora
from compliance_agent.sancao_abrangencia import veda_comprador_rj, vigente_em

# categorias CEIS/CNEP que VEDAM contratar (art. 156 §§4º-5º; art. 87 III-IV da 8.666)
_IMPEDITIVAS = ("impedimento", "proibicao de contratar", "proibição de contratar",
                "proibido de contratar",   # grafia do SIGA-RJ (Lei 8.429 art. 12): 31 vigentes
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
    # fundamentação, abrangência declarada e esfera do sancionador alimentam a régua de alcance (O4.9); base antiga sem
    # essas colunas devolve NULL com o mesmo nome (`sql_campos_ceis`)
    from compliance_agent.sancao_abrangencia import sql_campos_ceis
    cols = {r[1] for r in con.execute("PRAGMA table_info(sancoes_federais)")}
    fund = "fundamentacao" if "fundamentacao" in cols else "NULL AS fundamentacao"
    rows = con.execute(
        f"SELECT cadastro, categoria, data_inicio, data_fim, orgao, uf, {fund}, {sql_campos_ceis(con)} "
        "FROM sancoes_federais WHERE REPLACE(REPLACE(REPLACE(cpf_cnpj,'.',''),'/',''),'-','')=?",
        (_limpa(cnpj),)).fetchall()
    return [{"cadastro": r[0], "categoria": r[1], "data_inicio": r[2], "data_fim": r[3],
             "orgao": r[4], "uf": r[5], "fundamentacao": r[6], "abrangencia": r[7],
             "esfera_sancionador": r[8], "data_publicacao": r[9]} for r in rows]


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
        # Data que NÃO é a da assinatura (a varredura por UG usa a 1ª OB do credor): o teste
        # objetivo de vedação fica não aferível e o grau desce um nível — a sanção pode ter
        # começado entre a assinatura e o 1º pagamento.
        origem = str(contexto.get("data_referencia_origem") or "").strip()
        nota_origem = f" [data de referência: {origem}]" if origem else ""

        # régua única da vigência NA DATA DO FATO (O4.11, 24/11/2026): "com prazo determinado" sem data final
        # não se afirma vigente — 682 linhas do CEIS/CNEP no snapshot; o filtro antigo as contava para sempre
        vigentes = [s for s in sancoes if vigente_em(s, data)]
        impeditivas = [s for s in vigentes if _eh_impeditiva(s.get("categoria"))]
        res.valores = {
            "data_referencia": data,
            "n_sancoes": len(sancoes),
            "n_vigentes": len(vigentes),
            "n_impeditivas": len(impeditivas),
            "categorias_vigentes": sorted({s.get("categoria") or "?" for s in vigentes})[:6],
        }

        if not vigentes:
            # Sanção 'Decorrida' no SIGA-RJ sem data de término na base: começou antes da data
            # de referência e não se sabe se ainda valia. Afirmar "sem sanção vigente" seria
            # inventar a data final.
            incertas = [s for s in (contexto.get("sancoes_vigencia_incerta") or [])
                        if (s.get("data_inicio") or "9999") <= data
                        and _eh_impeditiva(s.get("categoria"))]
            if incertas:
                s = incertas[0]
                res.valores["n_vigencia_incerta"] = len(incertas)
                res.motivo_refutacao = (
                    f"nao_avaliavel: {len(incertas)} sanção(ões) impeditiva(s) do "
                    f"{s.get('cadastro') or 'SIGA-RJ'} iniciada(s) antes de {data} (ex.: "
                    f"'{s.get('categoria')}' desde {s.get('data_inicio')}) com status "
                    "'Decorrido' e SEM data de término na base — FALTA: data final da "
                    "penalidade · FONTE: registro da sanção no SIGA-RJ (siga_sancoes guarda "
                    "só a data de efetivação)")
                return res
        if not sancoes or not vigentes:
            res.status = "descartado"
            res.motivo_refutacao = ("sem sanção vigente na data de referência "
                                    f"({len(sancoes)} histórica(s) fora da vigência)"
                                    if sancoes else "CNPJ sem registro no CEIS/CNEP")
            return res

        # ABRANGÊNCIA (art. 156 §§4º–5º): só a impeditiva que ALCANÇA o comprador veda o contrato
        casa = str(contexto.get("casa_compradora") or "estado")
        alcance = [(x, veda_comprador_rj(x, casa)) for x in impeditivas]
        alcancam = [x for x, v in alcance if v.get("veda")]
        res.valores["n_impeditivas_que_alcancam"] = len(alcancam)
        res.valores["casa_compradora"] = casa
        if impeditivas and not alcancam:
            # alcance NÃO DETERMINADO (esfera do sancionador ilegível; suspensão de órgão que não se casa com o
            # comprador) ≠ alcance que comprovadamente NÃO chega ao comprador (outro ente)
            incerto = [(x, v) for x, v in alcance
                       if v.get("esfera_sancionador") == "?" or v.get("abrangencia") == "orgao"]
            s, v = (incerto or alcance)[0]
            res.status = "confirmado"
            if incerto:
                res.score = ancora("forte" if not origem else "medio")
                res.valores["teste_objetivo"] = "nao_aferivel"
                trecho_alcance = "alcance sobre o comprador NÃO determinado — conferir o órgão sancionador"
            else:
                res.score = ancora("medio")
                res.valores["teste_objetivo"] = "fora_da_abrangencia"
                trecho_alcance = ("Lei 14.133/2021 art. 156 §4º: o impedimento alcança só o ente que o aplicou; "
                                  "risco reputacional, não vedação")
            res.evidencia = [(
                f"{s.get('cadastro')}: '{s.get('categoria')}' vigente em {data} "
                f"(órgão sancionador: {s.get('orgao') or '?'}) — {v.get('motivo')}. {trecho_alcance}" + nota_origem
            )]
            return res
        if alcancam:
            impeditivas = alcancam
            s = impeditivas[0]
            res.score = ancora("forte" if origem else "critico")
            res.status = "confirmado"
            # vedação legal objetiva → flag A possível; com data-proxy, só depois de conferir
            # a data de assinatura nos autos
            res.valores["teste_objetivo"] = "nao_aferivel" if origem else "violado"
            res.evidencia = [(
                f"{s.get('cadastro')}: '{s.get('categoria')}' vigente em {data} "
                f"({s.get('data_inicio')} → {s.get('data_fim') or 'sem prazo'}; "
                f"órgão sancionador: {s.get('orgao') or '?'}) — Lei 14.133/2021 art. 156 §§4º-5º"
                + nota_origem
            )]
            return res

        s = vigentes[0]
        res.score = ancora("medio")
        res.status = "confirmado"
        res.valores["teste_objetivo"] = "nao_aferivel"  # punição sem vedação de contratar
        res.evidencia = [(
            f"{s.get('cadastro')}: '{s.get('categoria')}' vigente em {data} — sanção NÃO "
            "impeditiva de contratar; verificar alcance/condições no processo sancionador"
            + nota_origem
        )]
        return res
