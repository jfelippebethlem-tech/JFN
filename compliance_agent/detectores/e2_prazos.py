# -*- coding: utf-8 -*-
"""E2 · PUBLICIDADE E PRAZOS MINIMIZADOS (spec V2 do dono, §3/E2).

Mecanismo: reduzir a janela entre publicação e abertura ao MÍNIMO legal, escolher DATAS de baixa atenção
(véspera de feriado, sexta à noite) e meios de baixa visibilidade limita o universo de concorrentes a quem foi
avisado "por dentro". O art. 55 da Lei 14.133/2021 fixa os prazos MÍNIMOS por modalidade/critério de julgamento.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • Prazo ÚTIL REAL (dias úteis, descontando feriados informados) entre publicação e abertura vs MÍNIMO do
    art. 55 (tabela `MINIMOS_ART55` no código, por modalidade × critério) ........................... agravante
      – prazo < mínimo legal ........................................... 'forte' (violação objetiva do art. 55)
      – prazo == mínimo legal (no piso, sem folga) ..................... 'fraco' (lícito; agravante, não sustenta sozinho)
  • Data-sombra: abertura/publicação em véspera de feriado ou sexta-feira após as 16h ............. +0.10 (agravante)
  • Ausência no PNCP (canal obrigatório, art. 54) ................................................. 'forte'
  • Retificação que altera substância sem reabrir prazo ........................................... 'forte'

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): para CADA retificação, rubrica fechada 'a alteração afeta a
formulação de propostas?' [afeta_substancialmente / nao_afeta]. 'afeta' sem reabertura de prazo → forte. Sem LLM
→ a retificação fica `nao_avaliavel` (não inventamos o juízo de impacto); o diff bruto permanece registrado.

TESTE EXCULPATÓRIO (spec): PRAZO MÍNIMO ISOLADO é prática comum e LÍCITA — este detector quase nunca sustenta
nada sozinho; serve de AGRAVANTE para E1/J4. Por isso 'no piso' (== mínimo) só dá 'fraco'. Urgência orçamentária
de fim de exercício explica concentração em dezembro — cruzar com X3 antes de pontuar como direcionamento.

HONESTIDADE JFN: indício ≠ acusação; sem datas de publicação/abertura, ou modalidade desconhecida → `nao_avaliavel`
(campo ausente ≠ 0); nunca inventa data nem prazo legal.
"""
from __future__ import annotations

from datetime import date, datetime

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# ───────────────────────────── Mínimos do art. 55 da Lei 14.133/2021 (dias ÚTEIS) ─────────────────────────────
# Prazo mínimo entre a divulgação do edital e a apresentação de propostas/lances, por modalidade × critério de
# julgamento (art. 55, I a III). Em DIAS ÚTEIS (a lei conta em dias úteis). Fonte: Lei 14.133/2021, art. 55.
# Limiar no CÓDIGO (spec §1.3) — jamais no prompt. Confirmar reajustes/regulamento local antes de uso probatório.
MINIMOS_ART55: dict[str, dict[str, int]] = {
    # modalidade: {criterio_de_julgamento: dias_uteis_minimos}
    "pregao":          {"menor_preco": 8, "maior_desconto": 8, "_default": 8},
    "concorrencia":    {"menor_preco": 8, "maior_desconto": 8,         # bens/serviços comuns
                        "tecnica_e_preco": 15, "melhor_tecnica": 15,   # técnica
                        "maior_retorno_economico": 15,
                        "obras_servicos_engenharia": 10,               # obras/serviços comuns de engenharia
                        "obras_servicos_engenharia_especiais": 25,     # regime de contratação integrada/semi-integrada
                        "_default": 8},
    "concurso":        {"_default": 35},
    "leilao":          {"_default": 15},
    "dialogo_competitivo": {"_default": 25},
}
_DEFAULT_CRITERIO = "_default"


def minimo_art55(modalidade: str | None, criterio: str | None = None) -> int | None:
    """Prazo mínimo (dias úteis) do art. 55 para a modalidade × critério. Modalidade desconhecida → None
    (→ detector marca nao_avaliavel, honesto — não inventamos o piso legal)."""
    m = (modalidade or "").strip().lower().replace("ã", "a").replace("á", "a").replace("é", "e").replace("ó", "o")
    m = m.replace("pregão", "pregao").replace("concorrência", "concorrencia").replace("leilão", "leilao")
    tabela = MINIMOS_ART55.get(m)
    if tabela is None:
        return None
    c = (criterio or "").strip().lower().replace(" ", "_").replace("-", "_")
    return tabela.get(c, tabela.get(_DEFAULT_CRITERIO))


# ───────────────────────────── parse de data/datetime ─────────────────────────────
def _to_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
            try:
                return datetime.strptime(v.strip()[:len(fmt) + 2], fmt).date()
            except ValueError:
                continue
        # último recurso: só a parte de data
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(v.strip()[:10], fmt).date()
            except ValueError:
                continue
    return None


def _to_datetime(v) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    if isinstance(v, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(v.strip()[:len(fmt) + 2], fmt)
            except ValueError:
                continue
    return None


def _feriados_set(feriados) -> set[date]:
    out: set[date] = set()
    for f in (feriados or []):
        d = _to_date(f)
        if d:
            out.add(d)
    return out


def dias_uteis(inicio: date, fim: date, feriados: set[date]) -> int:
    """Conta dias ÚTEIS entre `inicio` (exclusive) e `fim` (inclusive), descontando sábados/domingos e
    feriados informados. Determinístico, leve (sem dependência externa). Retorna 0 se fim <= inicio."""
    if fim <= inicio:
        return 0
    from datetime import timedelta
    n = 0
    d = inicio + timedelta(days=1)
    while d <= fim:
        if d.weekday() < 5 and d not in feriados:
            n += 1
        d += timedelta(days=1)
    return n


def _is_data_sombra(dt: datetime | None, feriados: set[date]) -> tuple[bool, str]:
    """Data de baixa atenção: véspera de feriado, ou sexta-feira após as 16h. Retorna (é_sombra, motivo)."""
    if dt is None:
        return False, ""
    from datetime import timedelta
    d = dt.date()
    if (d + timedelta(days=1)) in feriados:
        return True, "véspera de feriado"
    if d.weekday() == 4 and dt.hour >= 16:  # sexta após 16h
        return True, "sexta-feira após as 16h"
    if d.weekday() == 4 and dt.hour == 0 and dt.minute == 0:
        # sexta sem hora informada: sinal fraco, não marca sombra sozinho
        return False, ""
    return False, ""


# ───────────────────────────── Rubrica de impacto de retificação ─────────────────────────────
_RUBRICA_IMPACTO = {
    "afeta_substancialmente": "forte",   # especificação/quantitativo/habilitação mudaram → reabrir prazo
    "nao_afeta": "ausente",              # erro material → não exige reabertura
}


class E2Prazos(Detector):
    """Detector E2 — publicidade e prazos minimizados (art. 54/55, Lei 14.133/2021).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame/processo.
      contexto["data_publicacao"]: data/hora da divulgação do edital (str ISO/BR, date ou datetime).
      contexto["data_abertura"]: data/hora da sessão de abertura/apresentação de propostas.
      contexto["modalidade"]: 'pregao'|'concorrencia'|'concurso'|'leilao'|'dialogo_competitivo'.
      contexto["criterio"] (opcional): critério de julgamento ('menor_preco','tecnica_e_preco',...).
      contexto["feriados"] (opcional): lista de feriados (nacional/estadual RJ/municipal) p/ o prazo útil real.
      contexto["no_pncp"] (opcional bool): edital presente no PNCP? None/ausente → não pontua (campo ausente).
      contexto["versoes"] (opcional): lista de retificações [{secao, antes, depois, reabriu_prazo(bool),
          _rubrica_impacto(opcional p/ teste)}]. contexto["gerar"] (opcional): callable p/ a rubrica de impacto.

    Honesto: sem data de publicação OU abertura, ou modalidade desconhecida → nao_avaliavel (campo ausente ≠ 0)."""

    id = "E2"
    nome = "Publicidade e prazos minimizados"
    familia = "desenho_certame"  # E1–E6 (peso 0.6 na convergência §7.2) — E2 é tipicamente AGRAVANTE

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        dt_pub = _to_datetime(contexto.get("data_publicacao"))
        dt_abe = _to_datetime(contexto.get("data_abertura"))
        modalidade = contexto.get("modalidade")
        criterio = contexto.get("criterio")
        feriados = _feriados_set(contexto.get("feriados"))

        if dt_pub is None or dt_abe is None:
            res.motivo_refutacao = ("nao_avaliavel: faltam datas de publicação e/ou abertura "
                                    "(campo ausente ≠ 0) — sem base para o prazo útil")
            res.valores = {"tem_publicacao": dt_pub is not None, "tem_abertura": dt_abe is not None}
            return res

        if dt_abe < dt_pub:
            # dado sujo: abertura ANTES da publicação não fabrica violação 'forte' — sem base honesta
            res.motivo_refutacao = ("nao_avaliavel: datas inconsistentes (abertura anterior à publicação) — "
                                    "dado sujo, sem base para o prazo útil")
            res.valores = {"data_publicacao": dt_pub.date().isoformat(),
                           "data_abertura": dt_abe.date().isoformat()}
            return res

        minimo = minimo_art55(modalidade, criterio)
        if minimo is None:
            res.motivo_refutacao = (f"nao_avaliavel: modalidade {modalidade!r} desconhecida — sem mínimo "
                                    "legal do art. 55 aplicável (não inventamos o piso)")
            res.valores = {"modalidade": modalidade}
            return res

        prazo = dias_uteis(dt_pub.date(), dt_abe.date(), feriados)

        valores: dict = {
            "modalidade": str(modalidade).lower(),
            "criterio": (criterio or "_default"),
            "data_publicacao": dt_pub.date().isoformat(),
            "data_abertura": dt_abe.date().isoformat(),
            "prazo_util_dias": prazo,
            "minimo_art55_dias": minimo,
            "n_feriados_considerados": len(feriados),
        }

        score = 0.0
        razoes: list[str] = []

        # 1) prazo útil vs mínimo legal
        if prazo < minimo:
            score = max(score, ancora("forte"))
            razoes.append(f"prazo útil ({prazo} dias úteis) ABAIXO do mínimo do art. 55 ({minimo}) — violação objetiva")
            res.add_evidencia(
                fonte=f"datas do edital ({modalidade})",
                trecho=(f"publicação {dt_pub.isoformat(sep=' ')} → abertura {dt_abe.isoformat(sep=' ')}: "
                        f"{prazo} dias úteis < mínimo art.55={minimo}"),
            )
        elif prazo == minimo:
            score = max(score, ancora("fraco"))
            razoes.append(f"prazo no PISO legal ({prazo}=={minimo} dias úteis) — lícito; agravante, não sustenta sozinho")
            res.add_evidencia(
                fonte=f"datas do edital ({modalidade})",
                trecho=(f"publicação {dt_pub.isoformat(sep=' ')} → abertura {dt_abe.isoformat(sep=' ')}: "
                        f"prazo no piso ({prazo} dias úteis == mínimo art.55)"),
            )

        # 2) data-sombra (véspera de feriado / sexta à noite)
        sombra_pub, motivo_pub = _is_data_sombra(dt_pub, feriados)
        sombra_abe, motivo_abe = _is_data_sombra(dt_abe, feriados)
        valores["data_sombra_publicacao"] = motivo_pub or None
        valores["data_sombra_abertura"] = motivo_abe or None
        if (sombra_pub or sombra_abe) and score > 0:
            score = min(1.0, score + 0.10)
            qual = motivo_abe or motivo_pub
            razoes.append(f"data de baixa atenção ({qual}) — agravante de visibilidade")

        # 3) ausência no PNCP (canal obrigatório art. 54) — só pontua se o campo foi informado como False
        no_pncp = contexto.get("no_pncp")
        if no_pncp is False:
            score = max(score, ancora("forte"))
            razoes.append("edital AUSENTE do PNCP (canal de publicidade obrigatório, art. 54)")
            res.add_evidencia(fonte="PNCP", trecho="edital não localizado no PNCP (publicidade obrigatória art. 54)")
        valores["no_pncp"] = no_pncp

        # 4) retificações: diff + impacto (rubrica LLM-opcional) + reabertura de prazo
        ret = self._avaliar_retificacoes(contexto.get("versoes") or [], gerar=contexto.get("gerar"))
        valores["retificacoes"] = ret["resumo"]
        for ev in ret["evidencias"]:
            res.add_evidencia(fonte=ev["fonte"], trecho=ev["trecho"])
        if ret["impacta_sem_reabertura"]:
            score = max(score, ancora("forte"))
            razoes.append("retificação que AFETA a formulação de propostas SEM reabertura de prazo")

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = ("prazo útil acima do mínimo legal, sem data-sombra/ausência no PNCP/retificação "
                                    "impactante — sem indício de minimização de prazo/publicidade")
            res.valores = valores
            res.explicacao_inocente = "janela de propostas folgada e publicidade regular"
            return res

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = ("FALSO POSITIVO a descartar (spec E2): prazo mínimo ISOLADO é prática comum e "
                                   "lícita — este detector quase nunca sustenta sozinho, serve de AGRAVANTE para "
                                   "E1/J4. Urgência orçamentária de fim de exercício explica datas apertadas em "
                                   "dezembro (cruzar com X3 antes de imputar direcionamento).")
        return res

    def _avaliar_retificacoes(self, versoes: list[dict], *, gerar=None) -> dict:
        """Para cada retificação: diff bruto (sempre registrado) + impacto (rubrica fechada LLM-opcional) +
        reabertura. 'afeta_substancialmente' SEM reabertura → flag. Sem LLM/sem rubrica → impacto nao_avaliavel
        (não inventamos o juízo); o diff permanece como evidência."""
        evidencias: list[dict] = []
        resumo: list[dict] = []
        impacta_sem_reabertura = False
        for i, v in enumerate(versoes):
            secao = str(v.get("secao") or v.get("secção") or "?")
            antes = str(v.get("antes") or "")
            depois = str(v.get("depois") or "")
            reabriu = bool(v.get("reabriu_prazo"))
            impacto_status, impacto_motivo = self._impacto(v, gerar=gerar)
            resumo.append({"secao": secao, "impacto": impacto_status, "reabriu_prazo": reabriu})
            evidencias.append({
                "fonte": f"retificação #{i + 1} (seção {secao})",
                "trecho": f"ANTES='{antes[:80]}' DEPOIS='{depois[:80]}' reabriu_prazo={reabriu} impacto={impacto_status}",
            })
            if impacto_status == "afeta_substancialmente" and not reabriu:
                impacta_sem_reabertura = True
        return {"evidencias": evidencias, "resumo": resumo, "impacta_sem_reabertura": impacta_sem_reabertura}

    def _impacto(self, v: dict, *, gerar=None) -> tuple[str, str]:
        """Rubrica fechada de impacto de UMA retificação. Atalho de teste: `_rubrica_impacto` injetado no item.
        Sem rubrica e sem LLM → ('nao_avaliavel', motivo) honesto."""
        pre = v.get("_rubrica_impacto")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_IMPACTO)
            if nivel is None:
                return "nao_avaliavel", motivo
            return (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), motivo
        if gerar is None:
            return "nao_avaliavel", "LLM ausente — impacto da retificação não auditado (honesto)"
        sistema = (
            "Você é auditor de controle externo. Classifique se a ALTERAÇÃO do edital AFETA a formulação de "
            "propostas. Responda SOMENTE com JSON: "
            '{"nivel":"afeta_substancialmente|nao_afeta","trecho":"<citação literal do trecho alterado>"}. '
            "Sem trecho, não classifique."
        )
        prompt = (f"SEÇÃO: {v.get('secao')}\nANTES: {str(v.get('antes') or '')[:400]}\n"
                  f"DEPOIS: {str(v.get('depois') or '')[:400]}\n\nA alteração afeta a formulação de propostas?")
        try:
            raw = gerar(prompt, sistema)
        except Exception as e:  # noqa: BLE001 — degrada honesto
            return "nao_avaliavel", f"LLM indisponível ({str(e)[:50]})"
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_IMPACTO)
        if nivel is None or not isinstance(dados, dict):
            return "nao_avaliavel", motivo
        return (dados.get("nivel") or "").strip().lower(), motivo
