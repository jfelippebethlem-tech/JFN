# -*- coding: utf-8 -*-
"""Detector X13 — sub-rogação de fato e troca de controle após receita pública relevante.

Fecha a lacuna `sub_rogacao_ilegal` do catálogo, que estava `parcial` com a nota do problema:
*"R6 no Lex — **fora do REGISTRO**"*. A leitura existia; o que faltava era o grau, a escalada e o
painel adversarial, que só alcançam quem passa pelo pipeline de detector.

O QUE A LEI PROÍBE, E O QUE ELA NÃO PROÍBE — a distinção é toda a dificuldade aqui:

  · **Sub-rogação da pessoa do contratado é vedada.** Quem venceu a licitação executa; passar o
    contrato a terceiro burla o certame (Lei 14.133/2021 art. 137 §1º; a jurisprudência do TCU é
    firme desde a 8.666). É o caso GRAVE.
  · **Fusão, cisão e incorporação NÃO são sub-rogação.** São sucessão empresarial, admitida pelo
    art. 137, §2º, III, desde que mantidas as condições de habilitação e o interesse público.
    Tratá-las como vício produziria achado contra reorganização societária lícita.
  · **Troca de sócios também não é sub-rogação** — a pessoa jurídica contratada continua a mesma.
    O que a torna suspeita é o MOMENTO: controle vendido logo depois de a empresa passar a
    receber volume relevante do erário é o desenho clássico de venda de contrato. Isso é
    indício de apuração, não vício por si.

Régua (âncoras no CÓDIGO):
  · subcontratação total ou de parcela principal sem previsão em edital ...... 'critico'
  · cessão/transferência do contrato a terceiro .............................. 'critico'
  · troca de CONTROLE (>50% do capital) em janela curta após receita alta .... 'forte'
  · troca de controle fora da janela, ou sem receita relevante ............... 'medio'
  · sucessão declarada (fusão/cisão/incorporação) com habilitação mantida .... descartado
  · sem QSA histórico ou sem data de alteração .............................. nao_avaliavel

`avaliar(contexto)` espera:
  contexto["processo"], contexto["contratado_cnpj"]
  contexto["alteracoes_controle"]: [{data, fracao_transferida, tipo?, habilitacao_mantida?}]
  contexto["recebido_ate_alteracao"]: float — quanto o erário já pagou (OB) antes da alteração
  contexto["subcontratacao"]: {"fracao": float, "prevista_no_edital": bool, "parcela_principal": bool}
  contexto["cessao_contratual"]: bool
"""
from __future__ import annotations

from datetime import date
from typing import Any

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora

# Janela em que a troca de controle "conversa" com a receita pública recebida. Fora dela, a
# coincidência temporal deixa de ser argumento — e coincidência temporal é o único argumento aqui.
DIAS_JANELA = 365
# Piso de receita para a troca de controle chamar atenção. Abaixo disso, vender a empresa não tem
# relação plausível com o contrato público.
RECEITA_RELEVANTE = 1_000_000.0
CONTROLE = 0.50

# Tipos que NÃO são sub-rogação: sucessão empresarial admitida pelo art. 137, §2º, III.
_SUCESSAO = {"fusao", "fusão", "cisao", "cisão", "incorporacao", "incorporação", "sucessao",
             "sucessão"}


def _dias(a: str, b: str) -> int | None:
    try:
        return (date.fromisoformat(str(b)[:10]) - date.fromisoformat(str(a)[:10])).days
    except (TypeError, ValueError):
        return None


class X13SubRogacao(Detector):
    """Detector X13 — sub-rogação vedada e troca de controle pós-receita."""

    id = "X13"
    nome = "Sub-rogação de fato / troca de controle após receita pública"
    familia = "execucao"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        sub = contexto.get("subcontratacao") or {}
        cessao = contexto.get("cessao_contratual")
        alteracoes = contexto.get("alteracoes_controle")
        recebido = contexto.get("recebido_ate_alteracao")

        if not sub and cessao is None and alteracoes is None:
            res.motivo_refutacao = (
                "nao_avaliavel: sem dado de subcontratação, cessão ou alteração de controle "
                "(INDISPONÍVEL ≠ 0)")
            return res

        res.valores = {"tem_subcontratacao": bool(sub), "cessao_declarada": bool(cessao),
                       "n_alteracoes": len(alteracoes or [])}

        # ── 1. Cessão do contrato: a pessoa do contratado mudou. É o caso grave.
        if cessao:
            res.score = ancora("critico")
            res.status = "confirmado"
            res.valores["teste_objetivo"] = "violado"
            res.evidencia = ["Cessão/transferência do contrato a terceiro — a sub-rogação da "
                             "pessoa do contratado é vedada (Lei 14.133/2021, art. 137, §1º): "
                             "quem venceu a licitação é quem executa."]
            return res

        # ── 2. Subcontratação total ou da parcela principal sem previsão no edital
        fracao = sub.get("fracao")
        if fracao is not None:
            try:
                fracao = float(fracao)
            except (TypeError, ValueError):
                fracao = None
        if fracao is not None and not sub.get("prevista_no_edital"):
            if fracao >= 0.99 or sub.get("parcela_principal"):
                res.score = ancora("critico")
                res.status = "confirmado"
                res.valores["teste_objetivo"] = "violado"
                res.evidencia = [
                    ("Subcontratação total do objeto" if fracao >= 0.99 else
                     "Subcontratação da parcela PRINCIPAL do objeto")
                    + f" ({fracao:.0%}) sem previsão no edital — equivale a sub-rogação de fato "
                      "(Lei 14.133/2021, art. 122 e art. 137, §1º)."]
                return res
            if fracao > 0:
                res.score = ancora("medio")
                res.status = "confirmado"
                res.valores["teste_objetivo"] = "nao_aferivel"
                res.evidencia = [f"Subcontratação de {fracao:.0%} sem previsão no edital — "
                                 "apurar se alcança parcela principal (art. 122)."]
                return res

        # ── 3. Troca de controle: NÃO é sub-rogação; o que informa é o momento.
        candidatas = []
        for a in alteracoes or []:
            tipo = str(a.get("tipo") or "").strip().lower()
            if tipo in _SUCESSAO:
                continue                       # sucessão empresarial é admitida (§2º, III)
            try:
                frac = float(a.get("fracao_transferida") or 0)
            except (TypeError, ValueError):
                frac = 0.0
            if frac > CONTROLE:
                candidatas.append({**a, "fracao_transferida": frac})

        sucessoes = [a for a in (alteracoes or [])
                     if str(a.get("tipo") or "").strip().lower() in _SUCESSAO]
        if sucessoes and not candidatas:
            res.status = "descartado"
            res.motivo_refutacao = (
                "alteração é sucessão empresarial (fusão/cisão/incorporação), admitida pelo "
                "art. 137, §2º, III — apurar apenas a manutenção das condições de habilitação"
                + ("" if all(a.get("habilitacao_mantida") is not False for a in sucessoes)
                   else "; ATENÇÃO: consta habilitação NÃO mantida, o que é outro achado"))
            return res

        if not candidatas:
            res.status = "descartado"
            res.motivo_refutacao = ("sem cessão, sem subcontratação irregular e sem transferência "
                                    "de controle acima de 50%")
            return res

        alvo = max(candidatas, key=lambda a: a["fracao_transferida"])
        res.valores["fracao_transferida"] = alvo["fracao_transferida"]
        res.valores["data_alteracao"] = alvo.get("data")

        try:
            recebido_f = float(recebido) if recebido is not None else None
        except (TypeError, ValueError):
            recebido_f = None

        dias = _dias(str(contexto.get("data_inicio_contrato") or ""), str(alvo.get("data") or ""))
        na_janela = dias is not None and 0 <= dias <= DIAS_JANELA
        relevante = recebido_f is not None and recebido_f >= RECEITA_RELEVANTE

        if na_janela and relevante:
            res.score = ancora("forte")
            res.evidencia = [
                f"Controle societário transferido ({alvo['fracao_transferida']:.0%}) em "
                f"{alvo.get('data')}, {dias} dias após o início do contrato, com R$ "
                f"{recebido_f:,.2f} já recebidos do erário — desenho compatível com venda de "
                "contrato. NÃO é sub-rogação: a pessoa jurídica é a mesma. É indício de apuração."
                .replace(",", "X").replace(".", ",").replace("X", ".")]
        else:
            res.score = ancora("medio")
            faltou = []
            if not na_janela:
                faltou.append("a alteração está fora da janela de 365 dias do início do contrato"
                              if dias is not None else "não há data de início do contrato para medir a janela")
            if not relevante:
                faltou.append("a receita pública anterior à alteração não alcança o piso de "
                              "relevância (ou não foi informada)")
            res.evidencia = [
                f"Controle societário transferido ({alvo['fracao_transferida']:.0%}) em "
                f"{alvo.get('data')} — mas {'; '.join(faltou)}. Troca de sócios não é "
                "sub-rogação; sem a coincidência temporal com a receita, o sinal é fraco."]
        res.status = "confirmado"
        res.valores["teste_objetivo"] = "nao_aferivel"   # nunca é violação objetiva de teto
        return res
