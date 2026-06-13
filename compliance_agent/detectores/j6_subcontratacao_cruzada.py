# -*- coding: utf-8 -*-
"""J6 · SUBCONTRATAÇÃO CRUZADA E CONSÓRCIO ANÔMALO (spec V2 do dono, §4/J6).

Mecanismo: o vencedor REPARTE o contrato com os 'derrotados' — é o pagamento do cartel pela COBERTURA.
Fornecedores regulares deixam de competir mas reaparecem como SUBCONTRATADOS; ou um CONSÓRCIO reúne empresas que
poderiam competir SOZINHAS (consórcio desnecessário = supressão de concorrência disfarçada de cooperação).

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • Subcontratada cujo CNPJ (ou raiz/QSA) está na LISTA DE LICITANTES do MESMO certame ............... 'critico'
      (subcontratar QUEM DISPUTOU o mesmo certame é a assinatura objetiva do cartel — repartição do butim).
  • Subcontratada na lista de licitantes de CERTAMES ANÁLOGOS do órgão ............................... 'forte'
  • Consorciada que atendia SOZINHA aos mínimos de habilitação (consórcio reunindo concorrentes) ..... 'forte'
      (≥2 consorciadas auto-suficientes = consórcio desnecessário entre quem poderia competir entre si).

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): rubrica fechada da JUSTIFICATIVA da subcontratação
[especialidade_real_nao_detida / sem_justificativa_tecnica]. 'sem_justificativa_tecnica' (o vencedor subcontrata
o PRÓPRIO NÚCLEO do objeto) → forte (0.85+). Evidência exigida: objeto subcontratado × objeto principal.
Sem LLM → o componente subjetivo fica nao_avaliavel (o cruzamento objetivo de conjuntos permanece).

TESTE EXCULPATÓRIO (spec): subcontratação de ESPECIALIDADE REAL não detida pelo vencedor (ex.: fundações dentro
de uma obra civil) é LÍCITA e prevista — o flag crítico é específico: subcontratar quem DISPUTOU o mesmo certame.
Consórcio é LEGÍTIMO quando NENHUMA empresa atende sozinha aos mínimos (verificação objetiva resolve): se nenhuma
consorciada é auto-suficiente, o consórcio é regular e não pontua.

HONESTIDADE JFN: indício ≠ acusação; sem `subcontratadas` E sem `consorcio` → nao_avaliavel (campo essencial
ausente ≠ 0); CPF de sócio do QSA mascarado (LGPD); nunca inventa número.
"""
from __future__ import annotations

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Rubrica fechada da justificativa da subcontratação (spec J6). LLM-opcional; degrada honesto.
_RUBRICA_SUBCONTRATACAO = {
    "especialidade_real_nao_detida": "ausente",  # especialidade que o vencedor não detém — lícito/previsto
    "sem_justificativa_tecnica": "forte",        # vencedor subcontrata o PRÓPRIO núcleo do objeto — agrava
}


def _raiz(cnpj) -> str | None:
    """Raiz do CNPJ = 8 primeiros dígitos (matriz+filiais = uma só PJ; CC 44/985/1.142). Normaliza qualquer
    lixo (pontuação/espaços). CNPJ curto (ex.: '1', '2' nos fixtures) cai em si mesmo só-dígitos — comparação
    ainda consistente. Helper inline simples (sem dependência de reporting, p/ manter o detector leve/VM-safe)."""
    if cnpj is None:
        return None
    d = "".join(ch for ch in str(cnpj) if ch.isdigit())
    if not d:
        return None
    return d[:8] if len(d) >= 8 else d


def _cnpj_de(item) -> str | None:
    """Extrai o CNPJ de um licitante que pode ser string (CNPJ direto) ou dict {cnpj, ...}."""
    if isinstance(item, dict):
        return item.get("cnpj") or item.get("licitante_cnpj") or item.get("cnpj_licitante")
    if isinstance(item, (str, int)):
        return str(item)
    return None


def _raizes_de(lista) -> set[str]:
    """Conjunto de raízes de CNPJ de uma lista de licitantes (strings OU dicts)."""
    out: set[str] = set()
    for it in lista or []:
        r = _raiz(_cnpj_de(it))
        if r:
            out.add(r)
    return out


def _raizes_qsa(sub: dict) -> set[str]:
    """Raízes embutidas no QSA da subcontratada (sócio PJ cujo CNPJ está nos licitantes). CPF de sócio PF é
    ignorado (LGPD: nunca cruza CPF mascarado). Aceita qsa como lista de dicts {cnpj_socio?/documento?} ou de
    strings."""
    out: set[str] = set()
    for s in (sub.get("qsa") or []):
        doc = None
        if isinstance(s, dict):
            doc = s.get("cnpj_socio") or s.get("cnpj") or s.get("documento")
        elif isinstance(s, (str, int)):
            doc = s
        # só cruza documento de 14 dígitos (PJ); CPF (11) é mascarado/ignorado por LGPD
        dd = "".join(ch for ch in str(doc or "") if ch.isdigit())
        if len(dd) == 14:
            r = _raiz(dd)
            if r:
                out.add(r)
    return out


class J6SubcontratacaoCruzada(Detector):
    """Detector J6 — subcontratação cruzada / consórcio anômalo (repartição do butim do cartel pela cobertura).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame/processo.
      contexto["licitantes"]: list de CNPJ (str) OU de dicts {cnpj, ...} — quem DISPUTOU o certame.
      contexto["subcontratadas"]: list[dict] {cnpj, objeto?, qsa?} — quem o vencedor subcontratou (ESSENCIAL¹).
      contexto["consorcio"]: list[dict] {cnpj, atende_habilitacao_sozinha: bool?} — composição do consórcio (ESSENCIAL¹).
      contexto["certames_relacionados"] (opcional): list de listas de licitantes (certames análogos do órgão).
      contexto["objeto_principal"] (opcional str): objeto do contrato (p/ a rubrica objeto-sub × objeto-principal).
      contexto["_rubrica_subcontratacao"] (opcional, teste) / contexto["gerar"] (opcional): rubrica LLM da justificativa.

    ¹ Honesto: sem `subcontratadas` E sem `consorcio` → nao_avaliavel (campo essencial ausente ≠ 0). O cruzamento
    é por RAIZ de CNPJ (8 dígitos): filial subcontratada de matriz que disputou também conta."""

    id = "J6"
    nome = "Subcontratação cruzada / consórcio anômalo"
    familia = "conluio"  # J6 — peso 0.9 (conluio) na convergência §7.2

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        subcontratadas = [x for x in (contexto.get("subcontratadas") or []) if isinstance(x, dict)]
        consorcio = [x for x in (contexto.get("consorcio") or []) if isinstance(x, dict)]

        if not subcontratadas and not consorcio:
            res.motivo_refutacao = (
                "nao_avaliavel: sem `subcontratadas` e sem `consorcio` — sem autorizações de subcontratação nem "
                "composição do consórcio não há como aferir repartição cruzada/consórcio anômalo (campo ausente ≠ 0)")
            res.valores = {"tem_subcontratadas": False, "tem_consorcio": False}
            return res

        licitantes_raizes = _raizes_de(contexto.get("licitantes"))
        # raízes dos certames análogos do órgão (lista de listas)
        analogos_raizes: set[str] = set()
        for certame in (contexto.get("certames_relacionados") or []):
            analogos_raizes |= _raizes_de(certame)
        analogos_raizes -= licitantes_raizes  # só o que NÃO está já no certame em apreço

        valores: dict = {
            "n_licitantes": len(licitantes_raizes),
            "n_subcontratadas": len(subcontratadas),
            "n_consorciadas": len(consorcio),
            "tem_certames_analogos": bool(analogos_raizes),
        }

        score = 0.0
        razoes: list[str] = []

        # ── REGRA OBJETIVA 1: subcontratada que DISPUTOU o mesmo certame (ou análogo) ──
        cruzou_mesmo: list[str] = []
        cruzou_analogo: list[str] = []
        for sub in subcontratadas:
            cnpj = _cnpj_de(sub)
            raizes_sub = {_raiz(cnpj)} if _raiz(cnpj) else set()
            raizes_sub |= _raizes_qsa(sub)
            raizes_sub.discard(None)
            if raizes_sub & licitantes_raizes:
                cruzou_mesmo.append(str(cnpj or "?"))
                res.add_evidencia(
                    fonte="autorização de subcontratação × lista de licitantes (mesmo certame)",
                    trecho=(f"subcontratada {cnpj} (raiz {','.join(sorted(r for r in raizes_sub if r))}) consta como "
                            f"LICITANTE do mesmo certame — repartição do contrato com quem 'perdeu'"))
            elif raizes_sub & analogos_raizes:
                cruzou_analogo.append(str(cnpj or "?"))
                res.add_evidencia(
                    fonte="autorização de subcontratação × licitantes de certames análogos do órgão",
                    trecho=(f"subcontratada {cnpj} (raiz {','.join(sorted(r for r in raizes_sub if r))}) consta como "
                            f"licitante de certame ANÁLOGO do órgão"))

        valores["subcontratadas_que_disputaram"] = cruzou_mesmo
        valores["subcontratadas_em_certames_analogos"] = cruzou_analogo

        if cruzou_mesmo:
            score = max(score, ancora("critico"))
            razoes.append(
                f"{len(cruzou_mesmo)} subcontratada(s) DISPUTARAM o mesmo certame (CNPJ/raiz na lista de licitantes): "
                f"{', '.join(cruzou_mesmo[:5])} — repartição do butim pela cobertura (flag crítico)")
        elif cruzou_analogo:
            score = max(score, ancora("forte"))
            razoes.append(
                f"{len(cruzou_analogo)} subcontratada(s) disputaram certames ANÁLOGOS do órgão: "
                f"{', '.join(cruzou_analogo[:5])} — possível repartição recorrente (forte)")

        # ── REGRA OBJETIVA 2: consórcio anômalo (≥2 consorciadas auto-suficientes) ──
        autossuficientes = [
            str(_cnpj_de(c) or "?") for c in consorcio
            if c.get("atende_habilitacao_sozinha") is True
        ]
        info_consorcio = any(("atende_habilitacao_sozinha" in c) for c in consorcio)
        valores["consorciadas_autossuficientes"] = autossuficientes
        if len(autossuficientes) >= 2:
            score = max(score, ancora("forte"))
            razoes.append(
                f"{len(autossuficientes)} consorciadas atendiam SOZINHAS aos mínimos de habilitação "
                f"({', '.join(autossuficientes[:5])}) — consórcio desnecessário reunindo quem poderia competir entre si")
            res.add_evidencia(
                fonte="composição do consórcio × capacidade individual de habilitação",
                trecho=(f"{len(autossuficientes)} consorciadas auto-suficientes ⇒ consórcio reúne concorrentes "
                        f"(supressão de disputa disfarçada de cooperação): {', '.join(autossuficientes[:5])}"))
        elif consorcio and info_consorcio and not autossuficientes:
            razoes.append(
                "consórcio: NENHUMA consorciada atende sozinha aos mínimos — cooperação legítima (verificação "
                "objetiva resolve); não pontua")

        # ── nada objetivo confirmou ──
        if score <= 0:
            res.status = "descartado"
            res.valores = valores
            partes = []
            if subcontratadas:
                partes.append("subcontratação(ões) de especialidade fora da lista de licitantes (lícita/prevista)")
            if consorcio:
                partes.append("consórcio sem consorciada auto-suficiente (cooperação legítima)")
            res.motivo_refutacao = (
                "sem cruzamento anômalo: " + "; ".join(partes) if partes else
                "sem cruzamento anômalo entre subcontratadas/consorciadas e licitantes")
            res.explicacao_inocente = (
                "subcontratação de ESPECIALIDADE REAL não detida pelo vencedor (ex.: fundações em obra civil) é "
                "lícita e prevista; consórcio é legítimo quando nenhuma empresa atende sozinha aos mínimos de "
                "habilitação. O flag crítico é específico: subcontratar quem DISPUTOU o mesmo certame.")
            return res

        # ── PARTE SUBJETIVA (LLM-opcional): justificativa da subcontratação (objeto-sub × objeto-principal) ──
        if subcontratadas:
            sub = self._avaliar_rubrica(contexto)
            valores["justificativa_subcontratacao"] = sub["status"]
            if sub["status"] == "sem_justificativa_tecnica":
                score = max(score, ancora("forte"))
                razoes.append(
                    "rubrica: subcontratação SEM justificativa técnica — vencedor subcontrata o PRÓPRIO núcleo do "
                    "objeto (objeto subcontratado ≈ objeto principal)")
            elif sub["status"] == "especialidade_real_nao_detida":
                razoes.append(
                    "rubrica: subcontratação de especialidade real não detida pelo vencedor (registra; o cruzamento "
                    "objetivo com licitantes permanece)")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = (
            "FALSO POSITIVO a descartar (spec J6): subcontratação de ESPECIALIDADE REAL não detida pelo vencedor "
            "(ex.: fundações dentro de obra civil) é LÍCITA e prevista — o flag crítico é específico: subcontratar "
            "quem DISPUTOU o mesmo certame. Consórcio é legítimo quando NENHUMA empresa atende sozinha aos mínimos "
            "de habilitação. Cruzar com J1 (rodízio) e C4 (QSA compartilhado) p/ confirmar o cartel.")
        return res

    def _avaliar_rubrica(self, contexto: dict) -> dict:
        """Rubrica fechada da justificativa da subcontratação (objeto subcontratado × objeto principal). Atalho de
        teste: `_rubrica_subcontratacao` injetado no contexto. Sem rubrica e sem LLM → nao_avaliavel honesto."""
        pre = contexto.get("_rubrica_subcontratacao")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_SUBCONTRATACAO)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel",
                    "motivo": "LLM ausente — justificativa da subcontratação não auditada (honesto)"}
        sistema = (
            "Você é auditor de controle externo. Classifique a JUSTIFICATIVA da subcontratação conforme a rubrica "
            "fechada: o objeto subcontratado é uma ESPECIALIDADE que o vencedor não detém, ou é o PRÓPRIO NÚCLEO do "
            "objeto principal (sem justificativa técnica)? Responda SOMENTE com JSON: "
            '{"nivel":"especialidade_real_nao_detida|sem_justificativa_tecnica","trecho":"<citação literal>"}. '
            "Sem trecho, não classifique.")
        objeto_principal = str(contexto.get("objeto_principal") or "")
        objetos_sub = "; ".join(
            str(s.get("objeto") or "")[:120] for s in (contexto.get("subcontratadas") or []) if isinstance(s, dict))
        prompt = (
            f"Objeto principal do contrato: {objeto_principal[:600]}\n"
            f"Objeto(s) subcontratado(s): {objetos_sub[:1000]}\n\n"
            "A subcontratação é de especialidade real não detida pelo vencedor, ou recai sobre o núcleo do objeto?")
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_SUBCONTRATACAO)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
