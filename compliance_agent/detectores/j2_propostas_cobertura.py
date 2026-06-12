# -*- coding: utf-8 -*-
"""J2 · PROPOSTAS DE COBERTURA (screens de preço) (spec V2 do dono, §4/J2).

Mecanismo: concorrentes do cartel apresentam propostas deliberadamente perdedoras ('pro forma', de COBERTURA)
para simular competição. Isso deixa ASSINATURA ESTATÍSTICA nos preços: dispersão baixa demais entre perdedoras e
distância artificial entre o vencedor e o resto (os screens de Huber & Imhof, 2019). Em séries, o mesmo PAR
vencedor-perdedor se repete e a 'cobertura' (o quanto o perdedor fica acima do vencedor) é quase CONSTANTE.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • COBERTURA = (valor_perdedor − valor_vencedor) / valor_vencedor, por perdedor.
  • Dispersão das coberturas (CV das coberturas dos perdedores): muito baixa ⇒ percentuais CONSTANTES ......... 'forte'
      (perdedores como função quase-linear do vencedor — assinatura de cobertura calculada).
      – CV das coberturas ≥ limiar competitivo ⇒ dispersão irregular natural ............................ 'descartado'.
  • RECORRÊNCIA de pares vencedor↔perdedor em `certames_relacionados` (mesmos pares, cobertura estável) ...... reforça
      → quando há série, mesmos pares com cobertura estável sobe o teto para 'forte'/'critico'.

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): rubrica fechada do PADRÃO de cobertura
  [dispersao_irregular_competitiva / cobertura_suspeita_percentuais_constantes]. 'percentuais_constantes' → forte.
  Sem LLM → o componente subjetivo fica nao_avaliavel (o screen objetivo permanece).

TESTE EXCULPATÓRIO (spec): MERCADO com poucos players e custos similares → dispersão baixa NATURAL (margem fina,
estrutura de custo homogênea). Por isso nunca limiar absoluto sem contexto; commodity/insumo transparente tem CV
naturalmente baixo. `mercado_homogeneo=True` rebaixa o screen (não sustenta sozinho).

HONESTIDADE JFN (CLÁUSULA CRÍTICA DESTE DETECTOR): o PNCP só expõe o VENCEDOR. Sem a LISTA de propostas dos
perdedores (≥2 propostas com valor + classificação) NÃO HÁ COMO calcular screen de cobertura — o caso vira
`nao_avaliavel` + motivo EXPLÍCITO. NUNCA se pontua conluio de cobertura sem os dados das propostas. Indício ≠
acusação; campo ausente ≠ 0; nunca inventa número.
"""
from __future__ import annotations

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Rubrica fechada do padrão de cobertura (spec J2). LLM-opcional; degrada honesto.
_RUBRICA_COBERTURA = {
    "dispersao_irregular_competitiva": "ausente",       # dispersão natural de competição real
    "cobertura_suspeita_percentuais_constantes": "forte",  # perdedores quase-lineares ao vencedor
}

# Limiar (CÓDIGO, nunca no prompt — spec §1.3): CV das COBERTURAS abaixo disto ⇒ percentuais constantes suspeitos.
_CV_COBERTURA_SUSPEITO = 0.05
# Mínimo de propostas para um screen ter sentido (1 vencedor + ≥2 perdedores).
_MIN_PROPOSTAS = 3


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _cv(valores: list[float]) -> float | None:
    """Coeficiente de variação (desvio padrão populacional / média). None se < 2 valores ou média 0."""
    vs = [v for v in valores if isinstance(v, (int, float))]
    if len(vs) < 2:
        return None
    media = sum(vs) / len(vs)
    if media == 0:
        return None
    var = sum((v - media) ** 2 for v in vs) / len(vs)
    return (var ** 0.5) / abs(media)


def _vencedor_e_perdedores(propostas: list[dict]) -> tuple[dict | None, list[dict]]:
    """Separa o vencedor (classificacao==1 / 'vencedor', ou menor valor) dos perdedores. Cada proposta precisa
    de `valor` numérico para entrar. Retorna (vencedor|None, perdedores)."""
    validas = []
    for p in propostas:
        if not isinstance(p, dict):
            continue
        val = _num(p.get("valor"))
        if val is None:
            continue
        validas.append({**p, "_valor": val})
    if not validas:
        return None, []

    def _classif(p: dict):
        c = p.get("classificacao")
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            return int(c)
        s = str(c or "").strip().lower()
        if s in ("vencedor", "1o", "1º", "primeiro", "classificado_1", "homologado"):
            return 1
        return None

    venc = next((p for p in validas if _classif(p) == 1), None)
    if venc is None:
        venc = min(validas, key=lambda p: p["_valor"])  # menor valor = vencedor presumido
    perdedores = [p for p in validas if p is not venc]
    return venc, perdedores


class J2PropostasCobertura(Detector):
    """Detector J2 — propostas de cobertura (screens de preço; Huber & Imhof / OECD / CADE).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame/processo.
      contexto["propostas"]: list[dict] {licitante_cnpj, valor (num), classificacao?}. PRECISA de ≥3 propostas
          com valor (1 vencedor + ≥2 perdedores) — SEM a LISTA de propostas (PNCP só dá o vencedor) → nao_avaliavel.
      contexto["valor_estimado"] (opcional): teto do certame (contexto/transparência).
      contexto["certames_relacionados"] (opcional): list[dict] de certames da mesma categoria, cada um com
          {propostas:[...]} — p/ testar RECORRÊNCIA de pares vencedor↔perdedor e estabilidade da cobertura.
      contexto["mercado_homogeneo"] (opcional bool): poucos players/custos similares → exculpatória (rebaixa).
      contexto["_rubrica_cobertura"] (opcional, teste) / contexto["gerar"] (opcional): rubrica LLM do padrão.

    Honesto: < 3 propostas com valor (a lista de propostas não está disponível) → nao_avaliavel (campo ausente ≠ 0)."""

    id = "J2"
    nome = "Propostas de cobertura (screens de preço)"
    familia = "conluio"  # J2 — peso 0.85 (conluio) na convergência §7.2

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        propostas = [p for p in (contexto.get("propostas") or []) if isinstance(p, dict)]
        venc, perdedores = _vencedor_e_perdedores(propostas)
        n_com_valor = (1 if venc else 0) + len(perdedores)

        # ── CLÁUSULA CRÍTICA DE HONESTIDADE: sem a LISTA de propostas, não há screen ──
        if venc is None or n_com_valor < _MIN_PROPOSTAS:
            res.motivo_refutacao = (
                "nao_avaliavel: lista de propostas dos perdedores indisponível "
                f"({n_com_valor} proposta(s) com valor < {_MIN_PROPOSTAS} necessárias). O PNCP só expõe o VENCEDOR; "
                "sem os valores dos licitantes perdedores NÃO há como calcular o screen de cobertura. "
                "Conluio NÃO é pontuado sem os dados das propostas (campo ausente ≠ 0)."
            )
            res.valores = {"n_propostas_com_valor": n_com_valor, "tem_vencedor": venc is not None,
                           "gap_pncp": "lista de propostas/licitantes ausente"}
            return res

        venc_val = venc["_valor"]
        mercado_homogeneo = bool(contexto.get("mercado_homogeneo"))

        # ── REGRA OBJETIVA: coberturas dos perdedores e sua dispersão ──
        coberturas = [(p["_valor"] - venc_val) / venc_val for p in perdedores if venc_val > 0]
        cv_cob = _cv(coberturas)
        cob_media = sum(coberturas) / len(coberturas) if coberturas else None

        valores: dict = {
            "n_propostas_com_valor": n_com_valor,
            "vencedor_cnpj": str(venc.get("licitante_cnpj") or venc.get("cnpj") or "") or None,
            "vencedor_valor": round(venc_val, 4),
            "n_perdedores": len(perdedores),
            "cobertura_media": round(cob_media, 4) if cob_media is not None else None,
            "cv_coberturas": round(cv_cob, 4) if cv_cob is not None else None,
            "mercado_homogeneo": mercado_homogeneo,
        }

        score = 0.0
        razoes: list[str] = []

        if cv_cob is not None and cv_cob < _CV_COBERTURA_SUSPEITO and not mercado_homogeneo:
            score = max(score, ancora("forte"))
            razoes.append(
                f"coberturas com dispersão baixíssima (CV={cv_cob:.3f} < {_CV_COBERTURA_SUSPEITO}) — perdedores como "
                f"função quase-linear do vencedor (percentuais de cobertura ~constantes em ~{cob_media:.0%})")
            res.add_evidencia(
                fonte="propostas do certame (screen de cobertura)",
                trecho=(f"vencedor={venc_val:,.2f}; coberturas dos {len(perdedores)} perdedores com "
                        f"CV={cv_cob:.4f} (< {_CV_COBERTURA_SUSPEITO}), média {cob_media:.4f}"))
        elif cv_cob is not None and cv_cob < _CV_COBERTURA_SUSPEITO and mercado_homogeneo:
            razoes.append(
                f"CV das coberturas baixo ({cv_cob:.3f}) MAS mercado homogêneo (poucos players/custos similares) — "
                "exculpatória: dispersão baixa natural (não pontua sozinho)")

        # ── RECORRÊNCIA de pares vencedor↔perdedor na série (reforço) ──
        rec = self._recorrencia_pares(contexto.get("certames_relacionados") or [],
                                      str(venc.get("licitante_cnpj") or venc.get("cnpj") or ""))
        valores["recorrencia_pares"] = rec["resumo"]
        if rec["pares_recorrentes"] and score > 0:
            score = max(score, ancora("critico"))
            razoes.append(rec["motivo"])
            res.add_evidencia(fonte="série de certames relacionados", trecho=rec["motivo"])
        elif rec["pares_recorrentes"] and score <= 0:
            # sem screen no certame atual, mas pares recorrentes na série: anomalia clara a confirmar
            score = max(score, ancora("medio"))
            razoes.append(rec["motivo"] + " (sem screen no certame atual — médio, a confirmar)")
            res.add_evidencia(fonte="série de certames relacionados", trecho=rec["motivo"])

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = (
                "dispersão de preços irregular/competitiva entre as propostas; sem padrão de cobertura "
                "(percentuais constantes) nem pares vencedor↔perdedor recorrentes — competição aparente")
            res.valores = valores
            res.explicacao_inocente = "propostas com dispersão de preços natural de competição real"
            return res

        # ── PARTE SUBJETIVA (LLM-opcional): padrão de cobertura ──
        sub = self._avaliar_rubrica(contexto)
        valores["padrao_cobertura"] = sub["status"]
        if sub["status"] == "cobertura_suspeita_percentuais_constantes":
            score = max(score, ancora("forte"))
            razoes.append("rubrica: padrão de cobertura com percentuais constantes (cobertura calculada)")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = (
            "FALSO POSITIVO a descartar (spec J2): MERCADO com poucos players e custos similares gera dispersão "
            "baixa NATURAL (margem fina, estrutura de custo homogênea); commodity/insumo transparente tem CV "
            "naturalmente baixo — usar baseline por categoria, nunca limiar absoluto. Cruzar com J1 (rodízio) "
            "antes de imputar cartel.")
        return res

    def _recorrencia_pares(self, certames_relacionados: list[dict], venc_cnpj: str) -> dict:
        """Conta quantas vezes o MESMO par (vencedor, perdedor) reaparece na série de certames relacionados,
        com cobertura estável. ≥2 ocorrências do mesmo par ⇒ pares recorrentes (assinatura de cobertura)."""
        venc_cnpj = (venc_cnpj or "").strip()
        contagem: dict[str, int] = {}
        for cert in certames_relacionados:
            if not isinstance(cert, dict):
                continue
            v, perd = _vencedor_e_perdedores([p for p in (cert.get("propostas") or []) if isinstance(p, dict)])
            if v is None:
                continue
            v_cnpj = str(v.get("licitante_cnpj") or v.get("cnpj") or "").strip()
            if not v_cnpj:
                continue
            for p in perd:
                p_cnpj = str(p.get("licitante_cnpj") or p.get("cnpj") or "").strip()
                if p_cnpj:
                    contagem[f"{v_cnpj}->{p_cnpj}"] = contagem.get(f"{v_cnpj}->{p_cnpj}", 0) + 1
        # se o vencedor atual está nos pares, conte só os dele; senão, qualquer par recorrente
        recorrentes = {k: n for k, n in contagem.items() if n >= 2 and (not venc_cnpj or k.startswith(venc_cnpj + "->"))}
        pares = bool(recorrentes)
        motivo = ""
        if pares:
            top = max(recorrentes.items(), key=lambda kv: kv[1])
            motivo = (f"par vencedor↔perdedor recorrente na série: {top[0]} reaparece {top[1]}x "
                      f"({len(recorrentes)} par(es) recorrente(s)) — mesmos pares vencedor-perdedor (cobertura)")
        return {"pares_recorrentes": pares, "resumo": {"n_pares_recorrentes": len(recorrentes),
                "n_certames_serie": len(certames_relacionados)}, "motivo": motivo}

    def _avaliar_rubrica(self, contexto: dict) -> dict:
        """Rubrica fechada do padrão de cobertura. Atalho de teste: `_rubrica_cobertura` injetado no contexto.
        Sem rubrica e sem LLM → nao_avaliavel honesto (o screen objetivo permanece)."""
        pre = contexto.get("_rubrica_cobertura")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_COBERTURA)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — padrão de cobertura não auditado (honesto)"}
        sistema = (
            "Você é auditor de controle externo. Classifique o PADRÃO de cobertura das propostas perdedoras conforme "
            "a rubrica fechada. Responda SOMENTE com JSON: "
            '{"nivel":"dispersao_irregular_competitiva|cobertura_suspeita_percentuais_constantes",'
            '"trecho":"<citação literal>"}. Sem trecho, não classifique.')
        prompt = ("As propostas perdedoras ficam a percentuais ~constantes acima do vencedor (cobertura calculada) "
                  "ou com dispersão irregular de competição real?")
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_COBERTURA)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
