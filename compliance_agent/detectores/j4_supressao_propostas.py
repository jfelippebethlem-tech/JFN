# -*- coding: utf-8 -*-
"""J4 · SUPRESSÃO DE PROPOSTAS E LICITANTE ÚNICO (spec V2 do dono, §4/J4).

Mecanismo: concorrentes 'somem': não aparecem, DESISTEM após habilitação, ou entregam documentação com ERROS
GROSSEIROS que garantem inabilitação — deixando o caminho livre para o preferido. A OCDE destaca retiradas
inesperadas e o grupo consistente de licitantes que entrega propostas incompletas/inabilitáveis.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • MUITOS inscritos, mas restou 1 só HABILITADO/classificado ........................................ 'forte'
      (afunilamento de N inscritos → 1 classificado é a assinatura objetiva).
  • Inabilitações por motivo de "erro grosseiro"/documentação primária (palavras-chave) ............. agrava
  • DESISTÊNCIAS em massa → restou único ............................................................. 'forte'
  • restou 1 classificado com ≥1 inabilitado/desistente, mas poucos inscritos ........................ 'medio'

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): rubrica fechada da GRAVIDADE/UNIFORMIDADE dos motivos de
inabilitação [fundada_proporcional / rigor_seletivo_desproporcional]. 'rigor_seletivo_desproporcional' → forte.
Sem LLM → o componente subjetivo fica nao_avaliavel (o afunilamento objetivo permanece).

TESTE EXCULPATÓRIO (spec): inabilitação tecnicamente FUNDADA e aplicada a TODOS igualmente NÃO é supressão —
diligência/saneamento (art. 64) não é favorecimento. Desistência por incapacidade real superveniente acontece
UMA vez; a recorrência é que condena. Órgãos de municípios remotos têm taxa de licitante único naturalmente alta.
`inabilitacao_fundada_uniforme=True` rebaixa.

HONESTIDADE JFN: indício ≠ acusação; sem `licitantes_classificados` → nao_avaliavel (campo ausente ≠ 0); nunca
inventa número.
"""
from __future__ import annotations

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Rubrica fechada da gravidade/uniformidade dos motivos de inabilitação (spec J4). LLM-opcional; degrada honesto.
_RUBRICA_INABILITACAO = {
    "fundada_proporcional": "ausente",          # inabilitação técnica fundada, aplicada a todos
    "rigor_seletivo_desproporcional": "forte",  # dois pesos: rigor para uns, tolerância para o preferido
}

# Palavras-chave de motivos de inabilitação por falha PRIMÁRIA (erro grosseiro de empresa experiente).
_MOTIVOS_GROSSEIROS = (
    "erro grosseiro", "documentação", "documentacao", "assinatura", "certidão vencida", "certidao vencida",
    "sem proposta", "proposta em branco", "rasura", "fora do prazo", "ausência de", "ausencia de", "faltou",
    "não anexou", "nao anexou", "índice", "indice", "atestado",
)

# Limiar (CÓDIGO): "muitos inscritos" para afunilamento → 1 classificado.
_MUITOS_INSCRITOS = 3


def _n(v) -> int | None:
    """Conta: aceita int direto ou comprimento de lista."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, (list, tuple, set)):
        return len(v)
    return None


class J4SupressaoPropostas(Detector):
    """Detector J4 — supressão de propostas / licitante único (OECD bid-rigging; CADE).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame/processo.
      contexto["licitantes_inscritos"] (opcional): int ou lista — quantos se inscreveram/baixaram o edital.
      contexto["licitantes_classificados"]: int ou lista — quantos restaram habilitados/classificados (ESSENCIAL).
      contexto["inabilitados"] (opcional): list[dict] {cnpj, motivo} — quem foi inabilitado e por quê.
      contexto["desistencias"] (opcional): list (cnpj/dict) — quem desistiu após inscrição/habilitação.
      contexto["inabilitacao_fundada_uniforme"] (opcional bool): inabilitação técnica fundada aplicada a todos
          igualmente → exculpatória (rebaixa).
      contexto["_rubrica_inabilitacao"] (opcional, teste) / contexto["gerar"] (opcional): rubrica LLM da gravidade.

    Honesto: sem licitantes_classificados → nao_avaliavel (campo ausente ≠ 0)."""

    id = "J4"
    nome = "Supressão de propostas / licitante único"
    familia = "conluio"  # J4 — peso 0.85 (conluio) na convergência §7.2

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        classificados = _n(contexto.get("licitantes_classificados"))
        if classificados is None:
            res.motivo_refutacao = (
                "nao_avaliavel: licitantes_classificados ausente — sem a contagem de quem restou habilitado não há "
                "como aferir supressão/afunilamento (campo ausente ≠ 0)")
            res.valores = {"tem_classificados": False}
            return res

        inscritos = _n(contexto.get("licitantes_inscritos"))
        inabilitados = [x for x in (contexto.get("inabilitados") or []) if isinstance(x, dict)]
        desistencias = list(contexto.get("desistencias") or [])
        fundada_uniforme = bool(contexto.get("inabilitacao_fundada_uniforme"))

        n_inab = len(inabilitados)
        n_desist = len(desistencias)
        # se inscritos não informado, estima pelo que se sabe (classificados + inabilitados + desistências)
        inscritos_efetivo = inscritos if inscritos is not None else (classificados + n_inab + n_desist)

        valores: dict = {
            "licitantes_inscritos": inscritos,
            "inscritos_efetivo": inscritos_efetivo,
            "licitantes_classificados": classificados,
            "n_inabilitados": n_inab,
            "n_desistencias": n_desist,
            "inabilitacao_fundada_uniforme": fundada_uniforme,
        }

        score = 0.0
        razoes: list[str] = []

        afunilou = inscritos_efetivo >= _MUITOS_INSCRITOS and classificados <= 1
        # motivos grosseiros entre os inabilitados?
        motivos_grosseiros = []
        for x in inabilitados:
            m = str(x.get("motivo") or "").strip().lower()
            if any(k in m for k in _MOTIVOS_GROSSEIROS):
                motivos_grosseiros.append((str(x.get("cnpj") or "?"), m))

        if afunilou and not fundada_uniforme:
            score = max(score, ancora("forte"))
            razoes.append(
                f"afunilamento: {inscritos_efetivo} inscritos → {classificados} classificado(s) "
                f"({n_inab} inabilitado(s), {n_desist} desistência(s)) — caminho livre para licitante único")
            res.add_evidencia(
                fonte="ata de julgamento (inscritos × classificados)",
                trecho=(f"{inscritos_efetivo} inscritos, {n_inab} inabilitados, {n_desist} desistências ⇒ "
                        f"{classificados} classificado(s)"))
        elif afunilou and fundada_uniforme:
            razoes.append(
                f"afunilamento ({inscritos_efetivo}→{classificados}) MAS inabilitação técnica fundada e uniforme — "
                "exculpatória (saneamento/art.64 não é favorecimento); não pontua sozinho")
        elif classificados <= 1 and (n_inab + n_desist) >= 1:
            score = max(score, ancora("medio"))
            razoes.append(
                f"restou {classificados} classificado(s) com {n_inab} inabilitado(s)/{n_desist} desistência(s), "
                "mas poucos inscritos — anomalia a confirmar")

        if motivos_grosseiros and score > 0 and not fundada_uniforme:
            score = min(1.0, score + 0.10)
            razoes.append(f"{len(motivos_grosseiros)} inabilitação(ões) por falha PRIMÁRIA/erro grosseiro "
                          "(empresa experiente que erra documentação básica)")
            for cnpj, m in motivos_grosseiros[:4]:
                res.add_evidencia(fonte="motivo de inabilitação", trecho=f"{cnpj}: {m[:120]}")

        if n_desist >= _MUITOS_INSCRITOS and classificados <= 1 and not fundada_uniforme:
            score = max(score, ancora("forte"))
            razoes.append(f"desistências em massa ({n_desist}) deixando licitante único")

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = (
                "sem afunilamento anômalo: competição preservada ou inabilitação técnica fundada/uniforme "
                "(saneamento legítimo, art.64) — sem indício de supressão")
            res.valores = valores
            res.explicacao_inocente = ("inabilitação tecnicamente fundada aplicada a todos igualmente, ou competição "
                                       "real preservada")
            return res

        # ── PARTE SUBJETIVA (LLM-opcional): gravidade/uniformidade dos motivos ──
        sub = self._avaliar_rubrica(contexto)
        valores["gravidade_inabilitacao"] = sub["status"]
        if sub["status"] == "rigor_seletivo_desproporcional":
            score = max(score, ancora("forte"))
            razoes.append("rubrica: rigor seletivo desproporcional nos motivos de inabilitação (dois pesos)")
        elif sub["status"] == "fundada_proporcional":
            razoes.append("rubrica: motivos de inabilitação fundados/proporcionais (registra; afunilamento objetivo permanece)")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = (
            "FALSO POSITIVO a descartar (spec J4): inabilitação tecnicamente FUNDADA e aplicada a TODOS igualmente "
            "NÃO é supressão — saneamento/diligência (art.64) não é favorecimento. Desistência por incapacidade real "
            "superveniente acontece UMA vez (a recorrência é que condena); municípios remotos têm taxa de licitante "
            "único naturalmente alta (baseline por porte/região). Cruzar com J1/J2 (perdedores profissionais).")
        return res

    def _avaliar_rubrica(self, contexto: dict) -> dict:
        """Rubrica fechada da gravidade/uniformidade dos motivos de inabilitação. Atalho de teste:
        `_rubrica_inabilitacao` injetado no contexto. Sem rubrica e sem LLM → nao_avaliavel honesto."""
        pre = contexto.get("_rubrica_inabilitacao")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_INABILITACAO)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — gravidade da inabilitação não auditada (honesto)"}
        sistema = (
            "Você é auditor de controle externo. Classifique a GRAVIDADE/UNIFORMIDADE dos motivos de inabilitação "
            "conforme a rubrica fechada (o mesmo rigor foi aplicado a todos?). Responda SOMENTE com JSON: "
            '{"nivel":"fundada_proporcional|rigor_seletivo_desproporcional","trecho":"<citação literal>"}. '
            "Sem trecho, não classifique.")
        motivos = "; ".join(str(x.get("motivo") or "")[:80] for x in (contexto.get("inabilitados") or []) if isinstance(x, dict))
        prompt = (f"Motivos de inabilitação na ata: {motivos[:1000]}\n\n"
                  "O rigor foi fundado e proporcional (mesma régua para todos) ou seletivo/desproporcional?")
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_INABILITACAO)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
