# -*- coding: utf-8 -*-
"""X9 · SUPRESSÃO ABUSIVA — encolher o contrato até ele deixar de ser o que foi licitado.

O LADO ESQUECIDO DO ART. 125. Toda a atenção da casa estava no acréscimo: X1 mede o quanto o
contrato engorda. A supressão nunca teve card, e ela é o vetor espelhado — e mais discreto,
porque encolher um contrato não dispara alarme de gasto.

O QUE O TEXTO LEGAL DIZ, e há uma assimetria que passa despercebida com facilidade:

    "o contratado será obrigado a aceitar, nas mesmas condições contratuais, acréscimos ou
     supressões de até 25% do valor inicial atualizado do contrato ..., e, no caso de reforma de
     edifício ou de equipamento, o limite para os ACRÉSCIMOS será de 50%"
                                                        — Lei 14.133/2021, art. 125

Os 50% são só do acréscimo. **Supressão continua limitada a 25% em qualquer objeto**, inclusive
reforma. E o art. 126 completa: "as alterações unilaterais ... não poderão transfigurar o objeto
da contratação".

POR QUE SUPRIMIR MUITO É PROBLEMA, e não economia:

  · **desfaz a competição já ocorrida** — o preço foi disputado para um escopo; entregar metade
    dele muda a equação que decidiu quem venceu, e quem perdeu concorreu por outro objeto;
  · **é o par do jogo de planilha** — suprimir os itens de preço BAIXO e manter os de preço alto
    eleva o preço médio do contrato sem tocar no valor global, que é o número que todo mundo olha;
  · **pode transfigurar o objeto** (art. 126), e aí não é alteração: é contratação nova.

TESTES OBJETIVOS (CÓDIGO, nunca no prompt):
  T1 TETO — supressão acumulada acima de 25% do valor inicial atualizado ............... critico
     (entre 20% e 25%, rente ao teto) ................................................. forte
  T2 SEM ACORDO — supressão acima do teto sem registro de anuência do contratado ...... agrava
  T3 ASSIMETRIA DE PREÇO — os itens suprimidos são os mais BARATOS frente à referência . critico
     (é a perna espelhada do jogo de planilha; sem preços unitários, não se afere)
  T4 ESVAZIAMENTO — supressão que consome mais da metade do objeto contratado .......... critico

HONESTIDADE JFN: sem `valor_inicial` ou sem supressões → nao_avaliavel. Supressão dentro do teto
é DIREITO da Administração e não vira achado. A anuência pode existir nos autos e não estar na
base — ausência do campo é lacuna declarada, nunca "sem acordo".
"""
from __future__ import annotations

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora, evidencia
from compliance_agent.limites_aditivo import acrescimo_computavel, ato_normativo, teto_supressao
from compliance_agent.reporting.intel_base import moeda

_FRACAO_RENTE = 0.80        # ≥80% do teto sem estourar → forte
_FRACAO_ESVAZIA = 0.50      # supressão que consome metade do objeto → esvaziamento
_ORDEM = ("ausente", "fraco", "medio", "forte", "critico")


def _sobe(nivel: str) -> str:
    return _ORDEM[min(len(_ORDEM) - 1, _ORDEM.index(nivel) + 1)]


class X9SupressaoAbusiva(Detector):
    """Detector X9 — supressão contratual acima do teto do art. 125 ou que esvazia o objeto.

    `avaliar(contexto)` espera:
      contexto["processo"]: id do contrato.
      contexto["valor_inicial"]: float (ESSENCIAL).
      contexto["aditivos"]: list[dict] no formato de `limites_aditivo` — a supressão é
          reconhecida pelo objeto ("supressão", "suprimir") e sai com valor NEGATIVO.
      contexto["tipo_objeto"]: opcional — NÃO altera o teto de supressão (o 50% da reforma é só
          do acréscimo), mas entra no texto do achado.
      contexto["itens_suprimidos"]: opcional list[dict] {preco_contratado, referencial} — alimenta
          o T3 (assimetria de preço).
      contexto["houve_anuencia"]: opcional bool — T2. Ausente é LACUNA, não 'sem acordo'.

    Honesto: sem valor inicial ou sem supressão → nao_avaliavel (ausência ≠ 0)."""

    id = "X9"
    nome = "Supressão abusiva (art. 125 e art. 126)"
    familia = "execucao"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        try:
            valor_inicial = float(contexto.get("valor_inicial") or 0)
        except (TypeError, ValueError):
            valor_inicial = 0.0
        if valor_inicial <= 0:
            res.motivo_refutacao = ("nao_avaliavel: valor_inicial ausente — sem base não há teto "
                                    "de supressão a aferir (campo ausente ≠ 0)")
            res.valores = {"tem_valor_inicial": False}
            return res

        comp = acrescimo_computavel(contexto.get("aditivos"))
        supressao = comp["supressao"]
        if supressao <= 0:
            res.status = "descartado"
            res.score = 0.0
            res.valores = {"tem_valor_inicial": True, "supressao": 0.0,
                           "n_aditivos": comp["n"], "lacunas": comp["lacunas"]}
            res.motivo_refutacao = ("nenhuma supressão apurada entre os termos — X9 não se aplica"
                                    + (f". Não classificados: {', '.join(comp['lacunas'])}."
                                       if comp["lacunas"] else ""))
            return res

        # O 50% da reforma é SÓ do acréscimo; a supressão fica nos 25% em qualquer objeto.
        teto = teto_supressao(contexto.get("tipo_objeto"))
        pct = supressao / valor_inicial
        valores = {
            "tem_valor_inicial": True, "valor_inicial": round(valor_inicial, 2),
            "supressao": round(supressao, 2), "pct_supressao": round(pct, 4),
            "teto_supressao": teto, "acrescimo": round(comp["acrescimo"], 2),
            "tipo_objeto": contexto.get("tipo_objeto"), "ato": ato_normativo(),
            "n_aditivos": comp["n"], "lacunas": list(comp["lacunas"]),
        }
        achados: list[str] = []
        nivel = "ausente"

        # T1 · teto
        if pct > teto:
            nivel = "critico"
            achados.append(
                f"SUPRESSÃO ACIMA DO TETO: {pct:.1%} do valor inicial (R$ {moeda(supressao)} "
                f"sobre R$ {moeda(valor_inicial)}), acima dos {teto:.0%} do {ato_normativo()}"
                + (" — o limite de 50% da reforma vale só para ACRÉSCIMOS"
                   if str(contexto.get("tipo_objeto") or "").lower().startswith("reforma") else ""))
        elif pct >= teto * _FRACAO_RENTE:
            nivel = "forte"
            achados.append(
                f"supressão de {pct:.1%} do valor inicial — rente ao teto de {teto:.0%} do "
                f"{ato_normativo()}")

        # T2 · sem acordo
        anuencia = contexto.get("houve_anuencia")
        if nivel != "ausente":
            if anuencia is False:
                nivel = _sobe(nivel)
                achados.append(
                    "SEM ANUÊNCIA registrada: o art. 125 obriga o contratado a aceitar até o "
                    "teto; acima dele, a alteração depende de acordo entre as partes")
            elif anuencia is None:
                valores["lacunas"].append("anuencia_nao_consta")

        # T3 · assimetria de preço — a perna espelhada do jogo de planilha
        itens = [i for i in (contexto.get("itens_suprimidos") or []) if isinstance(i, dict)]
        baratos = 0
        comparaveis = 0
        for i in itens:
            try:
                p, ref = float(i.get("preco_contratado")), float(i.get("referencial"))
            except (TypeError, ValueError):
                continue
            if ref <= 0:
                continue
            comparaveis += 1
            if p < ref:
                baratos += 1
        if comparaveis >= 3:
            frac = baratos / comparaveis
            valores["itens_suprimidos_comparaveis"] = comparaveis
            valores["frac_suprimidos_abaixo_da_referencia"] = round(frac, 3)
            if frac >= 0.8:
                nivel = "critico"
                achados.append(
                    f"ASSIMETRIA DE PREÇO: {baratos} de {comparaveis} itens suprimidos estavam "
                    f"ABAIXO da referência — suprimir o barato e manter o caro eleva o preço "
                    f"médio do contrato sem mexer no valor global, que é o número que se olha. "
                    f"É a perna espelhada do jogo de planilha")
        elif itens:
            valores["lacunas"].append("itens_suprimidos_sem_referencial_suficiente")

        # T4 · esvaziamento do objeto
        if pct >= _FRACAO_ESVAZIA:
            nivel = "critico"
            achados.append(
                f"ESVAZIAMENTO: a supressão consome {pct:.0%} do objeto contratado — alteração "
                f"unilateral não pode transfigurar o objeto (Lei 14.133/2021, art. 126); acima "
                f"disso não é alteração, é contratação nova")

        if nivel == "ausente":
            res.status = "descartado"
            res.score = 0.0
            res.valores = valores
            res.motivo_refutacao = (
                f"supressão de {pct:.1%}, dentro do teto de {teto:.0%} — supressão nesse limite é "
                f"direito da Administração e não constitui indício")
            return res

        res.status = "confirmado"
        res.score = ancora(nivel)
        res.valores = valores
        res.evidencia = [evidencia("contrato_aditivo / autos do processo", t) for t in achados]
        res.motivo_refutacao = ""
        res.explicacao_inocente = (
            "Supressão pode ser legítima e até desejável: demanda que caiu, item que se mostrou "
            "desnecessário, solução técnica melhor. O que informa é a MAGNITUDE (o preço foi "
            "disputado para outro escopo) e a SELEÇÃO dos itens suprimidos. A apuração pede a "
            "justificativa do termo e a planilha com os itens retirados.")
        return res
