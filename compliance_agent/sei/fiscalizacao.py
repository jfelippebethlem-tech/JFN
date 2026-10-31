# -*- coding: utf-8 -*-
"""
Fiscalização e medição, atesto a atesto — o que o fiscal assinou confere com o calendário?

POR QUE EXISTE. Pedido do dono em 30/10/2026: "análise dos fiscais e das medições, item a item". O 360 só
olhava se HAVIA atestação (X_PAGAMENTO_SEM_ATESTACAO); nunca o que o atesto dizia. Medido no acervo no mesmo
dia (2.450 atestos com assinatura eletrônica lida, 688 com período identificável):

  FZ1 · ATESTO ANTES DO FIM DO PERÍODO — o fiscal declara "executados" os serviços de um mês que ainda não
        acabou. 28 atestos em 24 processos (4%). Ex.: Elevadores Atlas Schindler/UERJ, dezembro/2024 atestado
        em 03/12/2024; Teltronic/SEGOV, outubro/2024 (R$ 284.340,00) atestado em 24/10/2024. A liquidação exige
        verificar o direito adquirido (art. 63 da Lei 4.320/1964) — serviço futuro não é direito adquirido.
  FZ2 · DATA INCOERENTE NO ATESTO — o período atestado termina muito depois da assinatura (> 45 dias): quase
        sempre erro material (CBMERJ/ENGE PRAT: "período de 29/11/2022 até 28/12/2023" assinado em 13/02/2023,
        datado "12 de fevereiro de 2022"). Erro de data em peça que sustenta pagamento é item a corrigir.

CONCESSIONÁRIA FICA FORA: na fatura de gás, luz, água e telefone o "mês" é o do ciclo de leitura, não o do
serviço — 341 atestos assim (CEG/Naturgy atestada no dia 9 do mês) seriam todos falsos positivos.
A data que conta é a da ÚLTIMA assinatura: o atesto da comissão só se completa quando o último membro assina.

Hipóteses medidas e DESCARTADAS (não viraram regra): "atestador não designado" acendia em 53% dos atestos —
a designação mora em página coletiva do D.O. que a captura traz cortada, ou é de outra comissão; "ordenador
que atesta" deu 0 casos reais (os 4 eram publicações de comissão classificadas como atesto).
"""
from __future__ import annotations

import calendar
import re
from datetime import date

from compliance_agent.sei.instrumento_assinatura import _data, _norm, assinaturas

_TITULO_ATESTO = re.compile(
    r"atestado de realiza|relat[oó]rio (t[eé]cnico )?(de|da comiss[aã]o de) fiscaliza|"
    r"parecer t[eé]cnico.{0,5}medi|termo de recebimento", re.I)
_CONCESSIONARIA = re.compile(
    r"\bCEG\b|naturgy|g[aá]s natural|\blight\b|\benel\b|\bampla\b|cedae|[aá]guas do rio|igu[aá] saneamento|"
    r"rio\+saneamento|energia el[eé]trica|telefonia|\bvivo\b|\bclaro\b|\boi\b|\btim\b|embratel|correios|"
    r"fornecimento de [aá]gua|esgot", re.I)
_MESES = {m: i for i, m in enumerate(
    "janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro dezembro".split(), 1)}
_SERVICO_DO_MES = re.compile(
    r"(?:servi[cç]os|fornecimento|presta[cç][aã]o)[^.]{0,40}?(?:do|no|referentes? ao|relativos? ao)\s+m[eê]s\s+de\s+"
    r"(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"
    r"\s*(?:de\s*|/\s*)(\d{4})", re.I)
_PERIODO = re.compile(
    r"per[ií]odo(?:\s+de)?\s*:?\s*(\d{2}/\d{2}/\d{4})\s+(?:a|at[eé])\s+(\d{2}/\d{2}/\d{4})", re.I)
FOLGA_ERRO_MATERIAL = 45          # dias: acima disto a antecipação não é plausível — é data errada
_RESSALVA = ("Indício a verificar, não acusação: presunção de legitimidade do ato administrativo e "
             "possibilidade de captura incompleta dos autos.")


def fim_do_periodo(texto: str) -> tuple[date | None, str]:
    """(último dia do período atestado, trecho que o diz). Período explícito vence o "mês de"."""
    t = re.sub(r"\s+", " ", texto or "")
    m = _PERIODO.search(t)
    if m:
        return _data(m.group(2)), m.group(0)
    m = _SERVICO_DO_MES.search(t)
    if m:
        mes, ano = _MESES.get(_norm(m.group(1)).replace("ç", "c")), int(m.group(2))
        if mes and 2000 < ano < 2100:
            return date(ano, mes, calendar.monthrange(ano, mes)[1]), m.group(0)
    return None, ""


def avaliar_atesto(doc: dict) -> dict | None:
    """Um atesto → um item (achado) ou None. `doc` = {ref, tipo, texto}."""
    ref = str(doc.get("ref") or "")
    if not _TITULO_ATESTO.search(ref) or re.search(r"cancelad", ref, re.I):   # atesto cancelado não sustenta nada
        return None
    texto = doc.get("texto") or ""
    if _CONCESSIONARIA.search(texto):
        return None
    fim, trecho = fim_do_periodo(texto)
    datas = [d for d in (_data(a["data"]) for a in assinaturas(re.sub(r"\s+", " ", texto))) if d]
    if not fim or not datas:
        return None
    assinado = max(datas)
    folga = (fim - assinado).days
    if folga <= 0:
        return None
    base = {"origem": "fiscalizacao", "evidencia": doc.get("ref", ""), "ressalva": _RESSALVA,
            "apoio": f"«{trecho[:140]}» · última assinatura em {assinado:%d/%m/%Y}"}
    if folga > FOLGA_ERRO_MATERIAL:
        return {**base, "codigo": "FZ2_DATA_INCOERENTE_NO_ATESTO", "gravidade": "media",
                "diz": (f"o atesto cobre período que termina em {fim:%d/%m/%Y}, {folga} dias DEPOIS da sua "
                        f"assinatura — provável erro material de data em peça que sustenta pagamento"),
                "fundamento": ("art. 63, § 2º, da Lei 4.320/1964: a liquidação se apoia no comprovante da "
                               "entrega; data errada nele compromete a prova do que foi pago")}
    dezembro = " (fim do exercício: atesto antecipado para liquidar no ano)" if fim.month == 12 else ""
    return {**base, "codigo": "FZ1_ATESTO_ANTES_DO_FIM_DO_PERIODO", "gravidade": "alta",
            "diz": (f"o fiscal declara executados os serviços até {fim:%d/%m/%Y} e assinou em "
                    f"{assinado:%d/%m/%Y} — {folga} dia(s) antes de o período acabar{dezembro}"),
            "fundamento": ("art. 63 da Lei 4.320/1964 e art. 140 da Lei 14.133/2021 (art. 73 da Lei "
                           "8.666/93): só se atesta e liquida o que já foi executado")}


def avaliar(docs: list[dict]) -> list[dict]:
    """Todos os atestos do processo, item a item, no formato de achado do `processo_360`."""
    return [a for a in (avaliar_atesto(d) for d in docs or []) if a]
