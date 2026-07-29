# -*- coding: utf-8 -*-
"""X8 · ADITIVO RETROATIVO — prorrogar o que já expirou, ou aditar contrato extinto.

O PONTO JURÍDICO. Contrato extinto pela fluência do prazo não se prorroga: não há o que aditar.
A prorrogação tem de ser celebrada **dentro** da vigência — é a orientação consolidada da
Advocacia Pública (ON AGU 3/2009) e a leitura corrente do art. 107 da Lei 14.133/2021. Um termo
assinado depois do fim da vigência não estende o contrato antigo: ou é contratação nova sem
licitação, ou é convalidação de execução que ocorreu sem cobertura contratual.

POR QUE ISSO IMPORTA MAIS DO QUE PARECE. O aditivo retroativo é o disfarce administrativo de dois
problemas diferentes, e o card serve para separá-los:

  · **execução sem cobertura contratual** — o serviço continuou sendo prestado e pago no vácuo
    entre o fim da vigência e a assinatura do termo. Aí o achado é de EXECUÇÃO (pagamento sem
    amparo) e o valor do período descoberto é o que interessa;
  · **contratação nova sem certame** — se o "aditivo" cria obrigação nova sobre contrato morto,
    é dispensa disfarçada, e a família é outra.

O QUE O CARD MEDE (tudo no CÓDIGO; nenhum limiar vai ao prompt):

  T1 RETROATIVO — data de assinatura do termo posterior ao fim da vigência vigente à época ...
     ≤ 30 dias de atraso .......................................................... medio
     31 a 180 dias ................................................................ forte
     > 180 dias, ou termo assinado após o fim de vigência já prorrogado ........... critico
  T2 REITERAÇÃO — dois ou mais termos retroativos no mesmo contrato .............. agrava +1 nível
  T3 VÁCUO PAGO — houve pagamento com data dentro do período descoberto ........... critico

HONESTIDADE JFN: sem data de assinatura do termo OU sem vigência do contrato → nao_avaliavel
(ausência ≠ zero). Atraso de publicação NÃO é atraso de assinatura: quando só a data de
publicação existe, o card declara a limitação e rebaixa, porque publicar tarde é irregularidade
de outra natureza e muito menos grave.
"""
from __future__ import annotations

from datetime import date, datetime

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora, evidencia
from compliance_agent.reporting.intel_base import moeda

# Faixas de atraso, em dias. No CÓDIGO — spec §1.3.
_DIAS_MEDIO = 30
_DIAS_FORTE = 180

_ORDEM = ("ausente", "fraco", "medio", "forte", "critico")


def _data(v) -> date | None:
    if isinstance(v, date):
        return v
    s = str(v or "")[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _sobe(nivel: str, passos: int = 1) -> str:
    i = min(len(_ORDEM) - 1, _ORDEM.index(nivel) + passos)
    return _ORDEM[i]


class X8AditivoRetroativo(Detector):
    """Detector X8 — termo aditivo assinado após o fim da vigência do contrato.

    `avaliar(contexto)` espera:
      contexto["processo"]: id do contrato.
      contexto["vigencia_fim"]: data do fim da vigência ORIGINAL (ESSENCIAL).
      contexto["aditivos"]: list[dict] com {data_assinatura|data, vigencia_fim?, tipo?,
          numero_termo?, data_publicacao?}. A `vigencia_fim` de cada termo estende a vigência
          para os termos seguintes — é assim que se sabe se o 3º termo estava dentro do prazo.
      contexto["pagamentos"]: opcional list[dict] com {data, valor} — alimenta o T3.

    Honesto: sem vigência ou sem aditivos datados → nao_avaliavel."""

    id = "X8"
    nome = "Aditivo retroativo (assinado após o fim da vigência)"
    familia = "execucao"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        vigencia = _data(contexto.get("vigencia_fim"))
        if vigencia is None:
            res.motivo_refutacao = ("nao_avaliavel: vigência do contrato ausente — sem ela não há "
                                    "como saber se o termo é retroativo (campo ausente ≠ 0)")
            res.valores = {"tem_vigencia": False}
            return res

        aditivos = [a for a in (contexto.get("aditivos") or []) if isinstance(a, dict)]
        datados = [a for a in aditivos
                   if _data(a.get("data_assinatura") or a.get("data")) is not None]
        if not datados:
            so_publicacao = [a for a in aditivos if a.get("data_publicacao")]
            res.motivo_refutacao = (
                "nao_avaliavel: nenhum termo com data de ASSINATURA. "
                + ("Há data de publicação, que NÃO serve: publicar tarde é irregularidade de "
                   "outra natureza, e muito menos grave que assinar fora da vigência."
                   if so_publicacao else "Sem datas, nada a aferir."))
            res.valores = {"tem_vigencia": True, "n_aditivos": len(aditivos),
                           "n_datados": 0, "so_publicacao": len(so_publicacao)}
            return res

        # A vigência corrente avança a cada termo que a estende — o 3º termo se afere contra a
        # vigência que os dois primeiros deixaram, não contra a original.
        datados.sort(key=lambda a: _data(a.get("data_assinatura") or a.get("data")))
        corrente = vigencia
        retroativos: list[dict] = []
        for a in datados:
            assinatura = _data(a.get("data_assinatura") or a.get("data"))
            if assinatura > corrente:
                retroativos.append({
                    "numero_termo": a.get("numero_termo") or "",
                    "assinatura": assinatura.isoformat(),
                    "vigencia_expirada_em": corrente.isoformat(),
                    "dias_apos": (assinatura - corrente).days,
                    "ja_prorrogado": corrente != vigencia,
                })
            nova = _data(a.get("vigencia_fim"))
            if nova and nova > corrente:
                corrente = nova

        valores = {
            "tem_vigencia": True, "vigencia_original": vigencia.isoformat(),
            "vigencia_final": corrente.isoformat(), "n_aditivos": len(aditivos),
            "n_datados": len(datados), "n_retroativos": len(retroativos),
            "retroativos": retroativos,
        }

        if not retroativos:
            res.status = "descartado"
            res.score = 0.0
            res.valores = valores
            res.motivo_refutacao = (
                f"os {len(datados)} termo(s) datado(s) foram assinados dentro da vigência "
                f"vigente à época — sem indício de aditamento retroativo")
            return res

        pior = max(retroativos, key=lambda r: r["dias_apos"])
        dias = pior["dias_apos"]
        nivel = ("critico" if (dias > _DIAS_FORTE or pior["ja_prorrogado"])
                 else "forte" if dias > _DIAS_MEDIO else "medio")
        evidencias = [
            f"Termo {r['numero_termo'] or '(s/nº)'} assinado em {r['assinatura']}, "
            f"{r['dias_apos']} dia(s) APÓS o fim da vigência ({r['vigencia_expirada_em']})"
            + (" — e a vigência já era fruto de prorrogação anterior" if r["ja_prorrogado"] else "")
            for r in retroativos
        ]
        if len(retroativos) > 1:
            nivel = _sobe(nivel)
            evidencias.append(
                f"REITERAÇÃO: {len(retroativos)} termos retroativos no mesmo contrato — "
                f"o atraso deixa de ser incidente e passa a ser prática da unidade")

        # T3 — houve pagamento no vácuo entre o fim da vigência e a assinatura?
        pagos_no_vacuo = []
        for p in contexto.get("pagamentos") or []:
            if not isinstance(p, dict):
                continue
            dp = _data(p.get("data"))
            if dp is None:
                continue
            for r in retroativos:
                if _data(r["vigencia_expirada_em"]) < dp < _data(r["assinatura"]):
                    pagos_no_vacuo.append({"data": dp.isoformat(), "valor": p.get("valor")})
                    break
        if pagos_no_vacuo:
            nivel = "critico"
            total = sum(float(p["valor"] or 0) for p in pagos_no_vacuo)
            evidencias.append(
                f"VÁCUO PAGO: {len(pagos_no_vacuo)} pagamento(s) com data dentro do período SEM "
                f"cobertura contratual (total apurado R$ {moeda(total)})")
            valores["pagamentos_no_vacuo"] = pagos_no_vacuo

        res.status = "confirmado"
        res.score = ancora(nivel)
        res.valores = valores
        res.evidencia = [evidencia("contrato_aditivo / autos do processo", t) for t in evidencias]
        res.motivo_refutacao = ""
        res.explicacao_inocente = (
            "Atraso na formalização pode decorrer de tramitação interna: o pedido de prorrogação "
            "foi tempestivo e o termo demorou a ser assinado. Isso não convalida a execução no "
            "período descoberto, mas muda a natureza do achado — de contratação irregular para "
            "falha de instrução. A apuração pede a data do PEDIDO de prorrogação nos autos.")
        return res
