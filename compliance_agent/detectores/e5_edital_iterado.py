# -*- coding: utf-8 -*-
"""E5 · EDITAL ITERADO (republicações dirigidas) (spec V2 do dono, §3/E5).

Mecanismo: o edital é REPUBLICADO sucessivamente com ajustes pontuais até 'encaixar' o vencedor desejado — ou
até neutralizar impugnações de concorrentes indesejados com mudanças que os EXCLUEM. O ciclo pode terminar em
DISPENSA por deserção/fracasso recorrente (o certame "fracassa" até virar contratação direta com o pretendido).

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • Nº de REPUBLICAÇÕES/retificações:
      – ≥ 3 republicações (sucessão de ajustes) ......................... 'medio' (candidato a iteração dirigida)
      – ≥ 4 republicações .............................................. 'forte'
  • CICLO que termina em DISPENSA após deserção/fracasso recorrente ..... agrava → 'forte' (motivação fabricada)
  • CORRELAÇÃO impugnação ↔ mudança que EXCLUI o impugnante ............. 'forte' (resposta dirigida à exclusão)

EXCULPATÓRIO (spec — verificar a ORIGEM da retificação nos autos ANTES de pontuar):
  • Retificação por DETERMINAÇÃO do TCE ou por ERRO MATERIAL é LEGÍTIMA → NÃO pontua (origem 'tce'/'erro_material').
  • Mudanças que AMPLIAM competição (relaxam exigências) pós-impugnação são o comportamento CORRETO → ZERAM o
    detector para aquela rodada (impugnação atendida que amplia, não exclui).

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): POR ALTERAÇÃO relevante (origem não-legítima), rubrica fechada do
'beneficiário provável da alteração' [neutra / amplia_competicao / restringe_ou_beneficia_perfil_especifico]. Se
'restringe_ou_beneficia_perfil_especifico' E o perfil COINCIDE com o VENCEDOR FINAL → confirma 'forte' (alteração
desenhada para o vencedor). Sem LLM/sem rubrica → o componente subjetivo fica nao_avaliavel (não inventamos o
juízo); o flag objetivo de nº de republicações permanece. Evidência: trecho antes × depois + característica do
vencedor que casa.

HONESTIDADE JFN: indício ≠ acusação; sem ≥2 versões/retificações no contexto → `nao_avaliavel` (campo ausente ≠ 0
— não dá para falar em "iteração" com uma única versão); nunca inventa número de republicações.
"""
from __future__ import annotations

import re

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Origens de retificação que são LEGÍTIMAS por construção (spec): não pontuam.
_ORIGENS_LEGITIMAS = {"tce", "erro_material"}

# Rubrica fechada do beneficiário provável de UMA alteração (spec E5).
_RUBRICA_BENEFICIARIO = {
    "neutra": "ausente",                                   # alteração sem efeito competitivo
    "amplia_competicao": "ausente",                        # relaxa exigências → comportamento CORRETO
    "restringe_ou_beneficia_perfil_especifico": "forte",   # estreita o perfil → confirma se casa c/ vencedor
}


def _norm(s) -> str:
    return str(s or "").strip().lower()


class E5EditalIterado(Detector):
    """Detector E5 — edital iterado / republicações dirigidas (Lei 14.133/2021; presunção de regularidade).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame/processo.
      contexto["versoes"] (ESSENCIAL): list[dict] das versões do edital, cada {versao, data?, resultado?
          ('deserto'|'fracassado'|'revogado'|'homologado'|...)}. Menos de 2 → nao_avaliavel (não há iteração).
      contexto["retificacoes"] (opcional): list[dict] de avisos de retificação, cada
          {secao, antes, depois, origem? ('tce'|'erro_material'|'oficio'|None),
           tipo? ('esclarecimento' fica fora do contador de volume), nova_versao? (bool),
           reabriu_prazo? (bool), _rubrica_beneficiario? (atalho de teste)}.
      contexto["impugnacoes"] (opcional): list[dict] {licitante, pedido, atendida(bool)?,
          mudanca_exclui_impugnante(bool)?}.
      contexto["vencedor"] (opcional): {cnpj, caracteristicas?: [str,...]} — perfil do vencedor final.
      contexto["resultados_rodadas"] (opcional): list[str] dos resultados por rodada (deserto/fracassado/...),
          quando não vierem embutidos nas versões.
      contexto["resultado_final"] (opcional str): desfecho do ciclo ('dispensa'|'homologado'|...).
      contexto["gerar"] (opcional): callable p/ a rubrica de beneficiário — LLM-opcional.
      contexto["_rubricas_alteracoes"] (opcional): list[dict] de respostas pré-classificadas (teste), na ordem
          das retificações relevantes (origem não-legítima).

    Honesto: < 2 versões/retificações → nao_avaliavel (campo ausente ≠ 0); origem 'tce'/'erro_material' é
    exculpatória e não pontua; ampliar competição zera a rodada."""

    id = "E5"
    nome = "Edital iterado (republicações dirigidas)"
    familia = "desenho_certame"  # E1–E6 (peso 0.6 na convergência §7.2)

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        versoes = contexto.get("versoes") or []
        retificacoes = contexto.get("retificacoes") or []

        # ── HONESTIDADE: sem ≥2 versões E sem retificações não há "iteração" para avaliar ──
        n_versoes = len(versoes)
        n_retif = len(retificacoes)
        if n_versoes < 2 and n_retif == 0:
            res.motivo_refutacao = ("nao_avaliavel: menos de 2 versões do edital e nenhuma retificação "
                                    "(campo ausente ≠ 0) — sem base para avaliar iteração/republicação")
            res.valores = {"n_versoes": n_versoes, "n_retificacoes": n_retif}
            return res

        # ── EXCULPATÓRIO objetivo (ANTES de contar): retificações de origem LEGÍTIMA não contam como iteração ──
        retif_relevantes, n_legitimas = self._filtrar_retificacoes_legitimas(retificacoes, res)
        n_retif_relevantes = len(retif_relevantes)

        # ── nº efetivo de republicações DIRIGIDAS (limiar objetivo) ──
        # cada versão nova após a 1ª é uma republicação, MENOS as que decorrem de origem legítima (TCE/erro
        # material são republicações devidas). No contador por retificação só entra quem MATERIALIZOU
        # republicação (nova versão publicada ou reabertura de prazo) — errata/esclarecimento trivial fica no
        # diff/rubrica, não no volume. Não contamos abaixo de zero.
        republicacoes_por_versao = max(n_versoes - 1 - n_legitimas, 0)
        n_retif_volume = sum(1 for r in retif_relevantes if self._conta_no_volume(r))
        n_republicacoes = max(republicacoes_por_versao, n_retif_volume)

        valores: dict = {
            "n_versoes": n_versoes,
            "n_retificacoes": n_retif,
            "n_retificacoes_legitimas": n_legitimas,
            "n_retificacoes_relevantes": n_retif_relevantes,
            "n_retificacoes_no_volume": n_retif_volume,
            "n_republicacoes": n_republicacoes,
        }
        score = 0.0
        razoes: list[str] = []

        # ── REGRA OBJETIVA 1: volume de republicações ──
        if n_republicacoes >= 4:
            score = max(score, ancora("forte"))
            razoes.append(f"{n_republicacoes} republicações/retificações sucessivas (volume alto — iteração dirigida)")
        elif n_republicacoes >= 3:
            score = max(score, ancora("medio"))
            razoes.append(f"{n_republicacoes} republicações/retificações (sucessão de ajustes — candidato a iteração)")
        if n_republicacoes >= 3:
            res.add_evidencia(
                fonte="histórico de versões/retificações do edital",
                trecho=f"{n_versoes} versões e {n_retif} retificações — {n_republicacoes} republicações sucessivas",
            )

        # ── REGRA OBJETIVA 2: ciclo que termina em DISPENSA após deserção/fracasso recorrente ──
        rodadas = self._resultados_rodadas(contexto, versoes)
        valores["resultados_rodadas"] = rodadas
        n_fracassos = sum(1 for r in rodadas if _norm(r) in ("deserto", "fracassado", "revogado"))
        valores["n_rodadas_fracassadas"] = n_fracassos
        resultado_final = _norm(contexto.get("resultado_final"))
        valores["resultado_final"] = resultado_final or None
        ciclo_para_dispensa = resultado_final == "dispensa" and n_fracassos >= 1
        # também detecta dispensa embutida como resultado da última versão
        if not ciclo_para_dispensa and rodadas and _norm(rodadas[-1]) == "dispensa" and n_fracassos >= 1:
            ciclo_para_dispensa = True
        if ciclo_para_dispensa:
            score = max(score, ancora("forte"))
            razoes.append(f"ciclo encerra em DISPENSA após {n_fracassos} rodada(s) deserta/fracassada (motivação fabricada)")
            res.add_evidencia(
                fonte="resultados das rodadas",
                trecho=f"sequência de rodadas: {rodadas} → desfecho DISPENSA (deserção/fracasso recorrente)",
            )

        # ── REGRA OBJETIVA 3: correlação impugnação ↔ mudança que EXCLUI o impugnante ──
        impugnacoes = contexto.get("impugnacoes") or []
        excl = self._impugnacao_exclui(impugnacoes)
        valores["impugnacao_exclui_impugnante"] = excl["ocorreu"]
        valores["impugnacoes_que_ampliam"] = excl["ampliam"]
        if excl["ocorreu"]:
            score = max(score, ancora("forte"))
            razoes.append("impugnação de licitante seguida de mudança que o EXCLUI (resposta dirigida à exclusão)")
            for ev in excl["evidencias"]:
                res.add_evidencia(fonte=ev["fonte"], trecho=ev["trecho"])

        # ── PARTE SUBJETIVA (LLM-opcional): beneficiário provável por alteração relevante ──
        venc_caract = self._caracteristicas_vencedor(contexto.get("vencedor") or {})
        valores["vencedor_caracteristicas"] = venc_caract or None
        subj = self._avaliar_rubricas_alteracoes(retif_relevantes, contexto, venc_caract, res)
        valores["beneficiario_alteracoes"] = subj["status_por_alteracao"]
        valores["confirma_perfil_vencedor"] = subj["confirma_perfil_vencedor"]
        if subj["confirma_perfil_vencedor"]:
            score = max(score, ancora("forte"))
            razoes.append("alteração que restringe/beneficia perfil específico que COINCIDE com o vencedor final (forte)")
        elif subj["amplia_zera_rodada"] and score > 0 and not (ciclo_para_dispensa or excl["ocorreu"]):
            # mudança que AMPLIA competição é o comportamento CORRETO → zera o detector para aquela rodada,
            # desde que não haja outro indício objetivo independente (ciclo→dispensa / impugnação→exclusão)
            score = min(score, ancora("fraco"))
            razoes.append("alteração AMPLIA competição (relaxa exigências) pós-impugnação — comportamento correto (rebaixado)")

        # ── desfecho ──
        if score <= 0:
            res.status = "descartado"
            res.valores = valores
            if n_legitimas and not retif_relevantes:
                res.motivo_refutacao = ("todas as retificações têm origem legítima (TCE/erro material) — "
                                        "republicação devida, sem indício de iteração dirigida")
                res.explicacao_inocente = ("retificações por determinação do TCE ou correção de erro material são "
                                           "republicações LEGÍTIMAS (verificada a origem nos autos).")
            elif subj["amplia_zera_rodada"]:
                res.motivo_refutacao = ("alterações pós-impugnação AMPLIAM competição (relaxam exigências) — "
                                        "comportamento correto, sem indício de direcionamento")
                res.explicacao_inocente = "mudanças que ampliam a competição pós-impugnação são o comportamento esperado."
            else:
                res.motivo_refutacao = ("poucas republicações, sem ciclo→dispensa, sem impugnação→exclusão e sem "
                                        "alteração restritiva que case com o vencedor — sem indício de iteração dirigida")
                res.explicacao_inocente = "ajustes pontuais legítimos do edital, sem padrão de direcionamento."
            return res

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = ("FALSO POSITIVO a descartar (spec E5): republicação por DETERMINAÇÃO do TCE ou por "
                                   "ERRO MATERIAL é legítima (verificar a origem da retificação nos autos antes de "
                                   "pontuar); mudanças que AMPLIAM a competição (relaxam exigências) pós-impugnação são "
                                   "o comportamento CORRETO e zeram o detector para aquela rodada.")
        return res

    # ───────────────────────────── helpers ─────────────────────────────
    @staticmethod
    def _conta_no_volume(r: dict) -> bool:
        """Uma retificação só conta no CONTADOR de volume se materializou REPUBLICAÇÃO: nova versão publicada
        ou reabertura de prazo. Errata/esclarecimento trivial entra no diff/rubrica, não no contador."""
        if _norm(r.get("tipo")) == "esclarecimento":
            return False
        return bool(r.get("nova_versao") or r.get("reabriu_prazo"))

    @staticmethod
    def _resultados_rodadas(contexto: dict, versoes: list[dict]) -> list[str]:
        """Lista os resultados por rodada: usa `resultados_rodadas` se vier, senão extrai de cada versão."""
        rr = contexto.get("resultados_rodadas")
        if isinstance(rr, list) and rr:
            return [str(x) for x in rr]
        out: list[str] = []
        for v in versoes:
            r = v.get("resultado")
            if r:
                out.append(str(r))
        return out

    @staticmethod
    def _impugnacao_exclui(impugnacoes: list[dict]) -> dict:
        """Detecta correlação impugnação → mudança que EXCLUI o impugnante. Honesto: mudança que ATENDE a
        impugnação ampliando competição NÃO conta (é o comportamento correto)."""
        evidencias: list[dict] = []
        ocorreu = False
        ampliam = 0
        for i, imp in enumerate(impugnacoes):
            exclui = bool(imp.get("mudanca_exclui_impugnante"))
            atendida = imp.get("atendida")
            licitante = imp.get("licitante") or f"impugnante #{i + 1}"
            if exclui:
                ocorreu = True
                evidencias.append({
                    "fonte": f"impugnação de {licitante}",
                    "trecho": (f"pedido='{str(imp.get('pedido') or '')[:80]}' → mudança que EXCLUI o impugnante "
                               f"(atendida={atendida})"),
                })
            elif atendida is True:
                # impugnação atendida sem exclusão → tipicamente ampliação (comportamento correto)
                ampliam += 1
        return {"ocorreu": ocorreu, "evidencias": evidencias, "ampliam": ampliam}

    @staticmethod
    def _filtrar_retificacoes_legitimas(retificacoes: list[dict], res: ResultadoDetector) -> tuple[list[dict], int]:
        """Separa retificações de origem LEGÍTIMA (tce/erro_material) — que não pontuam e viram evidência
        exculpatória — das relevantes (origem 'oficio'/None) que seguem para a rubrica subjetiva."""
        relevantes: list[dict] = []
        n_legitimas = 0
        for r in retificacoes:
            origem = _norm(r.get("origem"))
            if origem in _ORIGENS_LEGITIMAS:
                n_legitimas += 1
                res.add_evidencia(
                    fonte=f"retificação (seção {r.get('secao') or '?'})",
                    trecho=f"origem LEGÍTIMA '{origem}' — republicação devida (exculpatória, não pontua)",
                )
            else:
                relevantes.append(r)
        return relevantes, n_legitimas

    @staticmethod
    def _caracteristicas_vencedor(vencedor: dict) -> list[str]:
        caract = vencedor.get("caracteristicas") or vencedor.get("características") or []
        if isinstance(caract, str):
            caract = [caract]
        return [_norm(c) for c in caract if _norm(c)]

    def _avaliar_rubricas_alteracoes(self, retif_relevantes: list[dict], contexto: dict,
                                     venc_caract: list[str], res: ResultadoDetector) -> dict:
        """Para CADA alteração relevante, classifica o beneficiário provável (rubrica fechada LLM-opcional).
        'restringe_ou_beneficia_perfil_especifico' QUE CASA com o vencedor final → confirma 'forte'.
        'amplia_competicao' → marca rodada como comportamento correto. Sem LLM/sem rubricas → nao_avaliavel."""
        status_por_alteracao: list[str] = []
        confirma_perfil_vencedor = False
        amplia_zera_rodada = False

        # atalho de teste: lista de respostas pré-classificadas na ordem das retificações relevantes
        rubricas_teste = contexto.get("_rubricas_alteracoes")
        gerar = contexto.get("gerar")

        if not retif_relevantes:
            return {"status_por_alteracao": [], "confirma_perfil_vencedor": False, "amplia_zera_rodada": False}

        if rubricas_teste is None and gerar is None:
            # sem motor de rubrica: componente subjetivo nao_avaliavel (honesto) — não inventamos o juízo
            return {"status_por_alteracao": ["nao_avaliavel"] * len(retif_relevantes),
                    "confirma_perfil_vencedor": False, "amplia_zera_rodada": False}

        for i, r in enumerate(retif_relevantes):
            resposta = None
            if rubricas_teste is not None:
                resposta = rubricas_teste[i] if i < len(rubricas_teste) else None
            else:
                resposta = self._chamar_rubrica_llm(r, gerar)

            nivel, _score, _motivo = avaliar_rubrica(resposta, _RUBRICA_BENEFICIARIO)
            if nivel is None or not isinstance(resposta, dict):
                status_por_alteracao.append("nao_avaliavel")
                continue
            classe = _norm(resposta.get("nivel") or resposta.get("classificacao"))
            status_por_alteracao.append(classe)

            if classe == "amplia_competicao":
                amplia_zera_rodada = True
            elif classe == "restringe_ou_beneficia_perfil_especifico":
                trecho_rubrica = _norm(resposta.get("trecho") or resposta.get("citacao"))
                perfil_alvo = _norm(resposta.get("perfil_beneficiado"))
                # casa com o vencedor se alguma característica do vencedor aparece na citação ou no perfil alvo
                casa = self._casa_com_vencedor(venc_caract, trecho_rubrica, perfil_alvo)
                if casa:
                    confirma_perfil_vencedor = True
                    car = casa
                    res.add_evidencia(
                        fonte=f"retificação relevante #{i + 1} (seção {r.get('secao') or '?'})",
                        trecho=(f"ANTES='{str(r.get('antes') or '')[:80]}' DEPOIS='{str(r.get('depois') or '')[:80]}' "
                                f"→ restringe/beneficia perfil que CASA com vencedor (característica: '{car}')"),
                    )
                else:
                    res.add_evidencia(
                        fonte=f"retificação relevante #{i + 1} (seção {r.get('secao') or '?'})",
                        trecho=(f"ANTES='{str(r.get('antes') or '')[:80]}' DEPOIS='{str(r.get('depois') or '')[:80]}' "
                                "→ restringe/beneficia perfil específico (sem casamento confirmado com o vencedor)"),
                    )

        return {"status_por_alteracao": status_por_alteracao,
                "confirma_perfil_vencedor": confirma_perfil_vencedor,
                "amplia_zera_rodada": amplia_zera_rodada}

    @staticmethod
    def _casa_com_vencedor(venc_caract: list[str], trecho_rubrica: str, perfil_alvo: str) -> str | None:
        """Retorna a característica do vencedor que casa com a alteração (trecho da rubrica ou perfil alvo),
        ou None. Guarda anti-FP: característica curta ("me", "rj") casaria qualquer texto por substring —
        exige len≥4 e fronteira de palavra. Sem características do vencedor → não confirma (honesto)."""
        if not venc_caract:
            return None
        alvo = f"{trecho_rubrica} {perfil_alvo}".strip()
        for c in venc_caract:
            if len(c) >= 4 and re.search(r"\b" + re.escape(c) + r"\b", alvo):
                return c
        return None

    @staticmethod
    def _chamar_rubrica_llm(r: dict, gerar) -> dict | None:
        """Chama o LLM (rubrica fechada) p/ classificar o beneficiário provável de UMA alteração. Degrada
        honesto: qualquer falha → None (vira nao_avaliavel na agregação)."""
        sistema = (
            "Você é auditor de controle externo. Classifique o BENEFICIÁRIO PROVÁVEL desta ALTERAÇÃO de edital "
            "(comparando o trecho ANTES × DEPOIS). Responda SOMENTE com JSON: "
            '{"nivel":"neutra|amplia_competicao|restringe_ou_beneficia_perfil_especifico",'
            '"trecho":"<citação literal do trecho alterado>","perfil_beneficiado":"<perfil que a mudança favorece>"}. '
            "Sem trecho, não classifique."
        )
        prompt = (f"SEÇÃO: {r.get('secao')}\nANTES: {str(r.get('antes') or '')[:400]}\n"
                  f"DEPOIS: {str(r.get('depois') or '')[:400]}\n\nQuem é o beneficiário provável da alteração?")
        try:
            raw = gerar(prompt, sistema)
        except Exception:  # noqa: BLE001 — degrada honesto
            return None
        from compliance_agent.detectores.base import _parse_json
        return _parse_json(raw)
