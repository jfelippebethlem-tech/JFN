# -*- coding: utf-8 -*-
"""X4 · CARONA ABUSIVA EM ATA DE REGISTRO DE PREÇOS (spec V2 do dono, §X4).

Mecanismo: a 'indústria da carona'. Uma ata com preço ruim (ou direcionada) vira VEÍCULO para dezenas de adesões
país afora, multiplicando o dano SEM novo certame. O art. 86 da Lei 14.133/2021 impõe limites OBJETIVOS por item:
  • §4º — cada ÓRGÃO/ENTIDADE aderente (carona) pode adquirir até 50% do quantitativo REGISTRADO de cada item.
  • §5º — o total de adesões a uma ata NÃO pode exceder o DOBRO (2×) do quantitativo de cada item registrado.
Ambos os limites se medem sobre o QUANTITATIVO ORIGINAL registrado na ata, por ITEM.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • (a) adesão INDIVIDUAL > 50% do registrado do item (§4º) ................................ 'critico' (violação legal)
  • (b) SOMA das adesões > 2× (dobro) do quantitativo do item (§5º) ........................ 'critico' (violação legal)
  • Razão adesões/origem alta e curva temporal das adesões (sinal de contexto, registrado em `valores`).

PARTE SUBJETIVA (DUAS rubricas fechadas, LLM-OPCIONAL, degrada honesto):
  (1) Justificativa de vantagem da adesão (art.86 §2º I):
      [demonstra_vantagem_com_numeros / texto_padrao / ausente]. 'texto_padrao' (justificativas de aderentes
      DISTINTOS ~idênticas, similaridade ≥95%) → rede coordenada (forte). 'ausente' → forte. Evidência: trechos
      das justificativas comparadas. A similaridade é computada no CÓDIGO; a rubrica só CLASSIFICA.
  (2) Padrão geográfico/político da rede de aderentes:
      [dispersao_natural / concentracao_anomala]. 'concentracao_anomala' (aderentes concentrados em municípios com
      vínculo identificável entre si ou com o fornecedor) → forte e vetor de investigação (cruzar C6). Evidência:
      mapa de aderentes.

TESTE EXCULPATÓRIO (spec — o DISCRIMINADOR é o PREÇO): atas de compras centralizadas BEM PRECIFICADAS atraem
adesões legítimas por serem realmente vantajosas. Carona de ata BARATA/justa é gestão; carona de ata CARA é o
esquema. Se `preco_ata_vs_mercado` indica ata barata/justa (≤ ~1.0) E não há violação de limite → DESCARTAR.

HONESTIDADE JFN: indício ≠ acusação; sem `ata` (quantitativos) ou sem `adesoes` → nao_avaliavel (campo ausente ≠ 0);
nunca inventa número.
"""
from __future__ import annotations

import difflib

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# ───────────────────────────── Limites OBJETIVOS do art. 86 (Lei 14.133/2021) ─────────────────────────────
LIMITE_ADESAO_INDIVIDUAL = 0.50   # §4º — cada aderente até 50% do quantitativo registrado do item
LIMITE_TOTAL_ADESOES = 2.0        # §5º — total de adesões até o DOBRO do quantitativo do item

# Discriminador de preço (spec): ata cara = esquema; ata barata/justa = gestão.
_PRECO_ATA_JUSTA = 1.0  # razão preço_ata/mercado ≤ 1.0 → ata barata/justa

# Similaridade de justificativas: ≥95% entre aderentes distintos → texto-padrão (rede coordenada).
_SIM_TEXTO_PADRAO = 0.95

# Rubrica (1): justificativa de vantagem da adesão (art.86 §2º I). LLM-opcional; degrada honesto.
_RUBRICA_JUSTIFICATIVA = {
    "demonstra_vantagem_com_numeros": "ausente",  # justificativa robusta, com números → não agrava
    "texto_padrao": "forte",                      # boilerplate idêntico entre aderentes → rede coordenada
    "ausente": "forte",                           # sem demonstração de vantagem (viola §2º I) → agrava
}

# Rubrica (2): padrão geográfico/político da rede de aderentes. LLM-opcional; degrada honesto.
_RUBRICA_REDE = {
    "dispersao_natural": "ausente",     # aderentes dispersos → adesão legítima
    "concentracao_anomala": "forte",    # concentração com vínculo → vetor de investigação (cruzar C6)
}


def _num(v) -> float | None:
    """Converte para float honesto: None/vazio/não-numérico → None (campo ausente ≠ 0)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _similaridade(a: str, b: str) -> float:
    """Similaridade textual [0,1] entre duas justificativas (Ratcliff/Obershelp via difflib). Leve, sem
    embedding — adequado à VM. Normaliza para minúsculas/sem espaços redundantes."""
    na = " ".join((a or "").lower().split())
    nb = " ".join((b or "").lower().split())
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


class X4CaronaAbusiva(Detector):
    """Detector X4 — carona abusiva em Ata de Registro de Preços (art. 86, §§4º/5º, Lei 14.133/2021).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do processo/ata.
      contexto["ata"] (ESSENCIAL): dict {
            "itens": [{"item": <id>, "quantitativo_registrado": <num>}, ...],
            "orgao_gerenciador"?: str, "vigencia"?: str}.
      contexto["adesoes"] (ESSENCIAL): list[dict] {
            "aderente": str, "item": <id>, "quantidade": <num>,
            "data"?: str, "justificativa"?: str, "municipio"?: str}.
      contexto["preco_ata_vs_mercado"] (opcional, float): razão preço_ata/mercado na data da adesão
            (>1 = ata CARA = esquema; ≤1 = ata barata/justa = gestão — discriminador exculpatório do spec).
      contexto["vinculo_aderentes"] (opcional, bool/dados): sinal de concentração/vínculo entre aderentes.
      contexto["_rubrica_justificativa"] / contexto["_rubrica_rede"] (opcional, teste): rubricas pré-classificadas.
      contexto["gerar"] (opcional): callable LLM síncrono p/ as duas rubricas. Ausente → rubricas nao_avaliavel
            (degrada honesto); a violação OBJETIVA de limite permanece como achado do código.

    Honesto: sem `ata` (quantitativos) OU sem `adesoes` → nao_avaliavel (campo ausente ≠ 0)."""

    id = "X4"
    nome = "Carona abusiva em Ata de Registro de Preços"
    familia = "execucao"  # X4 — fase de execução (peso 0.8 §7.2); a violação de limite é crítica/confirmada

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        ata = contexto.get("ata")
        adesoes = contexto.get("adesoes")

        # ── HONESTIDADE: dados essenciais ausentes → nao_avaliavel (campo ausente ≠ 0) ──
        itens = (ata or {}).get("itens") if isinstance(ata, dict) else None
        if not isinstance(ata, dict) or not itens:
            res.motivo_refutacao = ("nao_avaliavel: ata/quantitativos ausentes — sem o quantitativo registrado por "
                                    "item não há base para os limites do art.86 (campo ausente ≠ 0)")
            res.valores = {"tem_ata": isinstance(ata, dict) and bool(itens)}
            return res
        if not adesoes:
            res.motivo_refutacao = ("nao_avaliavel: sem adesões (PNCP) — não há carona a aferir (campo ausente ≠ 0)")
            res.valores = {"tem_ata": True, "n_adesoes": 0}
            return res

        # quantitativo registrado por item (só itens com número válido entram nos limites)
        registrado: dict = {}
        for it in itens:
            if not isinstance(it, dict):
                continue
            q = _num(it.get("quantitativo_registrado"))
            if q is not None and q > 0:
                registrado[it.get("item")] = q

        # agrega adesões por item e por (item, aderente)
        soma_item: dict = {}
        por_item_aderente: dict = {}
        aderentes: set = set()
        n_adesoes_validas = 0
        for a in adesoes:
            if not isinstance(a, dict):
                continue
            item = a.get("item")
            qtd = _num(a.get("quantidade"))
            aderente = a.get("aderente")
            if item is None or qtd is None:
                continue
            n_adesoes_validas += 1
            aderentes.add(aderente)
            soma_item[item] = soma_item.get(item, 0.0) + qtd
            chave = (item, aderente)
            por_item_aderente[chave] = por_item_aderente.get(chave, 0.0) + qtd

        valores: dict = {
            "orgao_gerenciador": ata.get("orgao_gerenciador"),
            "n_itens_registrados": len(registrado),
            "n_adesoes": n_adesoes_validas,
            "n_aderentes_distintos": len(aderentes),
            "preco_ata_vs_mercado": _num(contexto.get("preco_ata_vs_mercado")),
            "violacoes_individuais_50pct": [],
            "violacoes_total_dobro": [],
        }
        # razão adesões/origem por item (curva/multiplicação do dano) — sinal de contexto
        razao_adesoes_origem: dict = {}
        for item, q_reg in registrado.items():
            if q_reg > 0:
                razao_adesoes_origem[item] = round(soma_item.get(item, 0.0) / q_reg, 4)
        valores["razao_adesoes_origem_por_item"] = razao_adesoes_origem

        score = 0.0
        razoes: list[str] = []

        # ── REGRA OBJETIVA (a) §4º: adesão INDIVIDUAL > 50% do registrado do item → crítico ──
        for (item, aderente), qtd in por_item_aderente.items():
            q_reg = registrado.get(item)
            if q_reg is None:
                continue
            frac = qtd / q_reg
            if frac > LIMITE_ADESAO_INDIVIDUAL:
                score = max(score, ancora("critico"))
                valores["violacoes_individuais_50pct"].append(
                    {"item": item, "aderente": aderente, "quantidade": qtd,
                     "quantitativo_registrado": q_reg, "fracao": round(frac, 4)})
                razoes.append(
                    f"§4º: aderente '{aderente}' no item '{item}' adquiriu {frac:.0%} do registrado "
                    f"(>{LIMITE_ADESAO_INDIVIDUAL:.0%})")
                res.add_evidencia(
                    fonte="adesão (PNCP) × quantitativo registrado da ata",
                    trecho=(f"item={item} aderente='{aderente}' qtd={qtd:g} registrado={q_reg:g} "
                            f"⇒ {frac:.1%} > 50% (viola art.86 §4º)"))

        # ── REGRA OBJETIVA (b) §5º: SOMA das adesões > 2× o quantitativo do item → crítico ──
        for item, soma in soma_item.items():
            q_reg = registrado.get(item)
            if q_reg is None:
                continue
            frac = soma / q_reg
            if frac > LIMITE_TOTAL_ADESOES:
                score = max(score, ancora("critico"))
                valores["violacoes_total_dobro"].append(
                    {"item": item, "soma_adesoes": soma, "quantitativo_registrado": q_reg, "fracao": round(frac, 4)})
                razoes.append(
                    f"§5º: total de adesões do item '{item}' = {frac:.1f}× o registrado (> dobro)")
                res.add_evidencia(
                    fonte="soma das adesões (PNCP) × quantitativo registrado da ata",
                    trecho=(f"item={item} soma_adesoes={soma:g} registrado={q_reg:g} "
                            f"⇒ {frac:.2f}× > 2× (viola art.86 §5º)"))

        violou_limite = bool(valores["violacoes_individuais_50pct"] or valores["violacoes_total_dobro"])

        # ── PARTE SUBJETIVA (LLM-opcional): duas rubricas fechadas ──
        just = self._avaliar_justificativas(contexto, adesoes)
        rede = self._avaliar_rede(contexto)
        valores["rubrica_justificativa"] = just["status"]
        valores["rubrica_rede"] = rede["status"]
        valores["similaridade_justificativas"] = just.get("similaridade")

        # ── DISCRIMINADOR DE PREÇO (exculpatória do spec) ──
        preco = valores["preco_ata_vs_mercado"]
        ata_barata = preco is not None and preco <= _PRECO_ATA_JUSTA

        # Sem violação de limite: o preço decide. Ata barata/justa → DESCARTAR (gestão legítima).
        if not violou_limite:
            # As rubricas subjetivas podem ainda sinalizar rede coordenada mesmo sem estouro de limite.
            sub_score = 0.0
            if just["status"] in ("texto_padrao", "ausente"):
                sub_score = max(sub_score, ancora("forte"))
                razoes.append(f"rubrica justificativa: '{just['status']}' (sem demonstração de vantagem / boilerplate)")
            if rede["status"] == "concentracao_anomala":
                sub_score = max(sub_score, ancora("forte"))
                razoes.append("rubrica rede: concentração geográfica/política anômala (vetor de investigação — cruzar C6)")

            if ata_barata:
                # carona de ata BARATA é gestão: descartar (discriminador do spec)
                res.status = "descartado"
                res.score = 0.0
                res.valores = valores
                res.motivo_refutacao = (
                    f"ata barata/justa (preço {preco:.2f}× mercado ≤ {_PRECO_ATA_JUSTA:.2f}) e sem violação de "
                    "limite — adesões legítimas a uma ata realmente vantajosa (gestão, não esquema)")
                res.explicacao_inocente = (
                    "compra centralizada BEM precificada atrai adesões legítimas por ser realmente vantajosa — "
                    "o teste de preço (P3) é o discriminador: carona de ata barata é gestão")
                return res

            if sub_score <= 0:
                # sem violação, sem rede coordenada e preço desconhecido/justo → descartado (sem indício)
                res.status = "descartado"
                res.score = 0.0
                res.valores = valores
                res.motivo_refutacao = (
                    "adesões dentro dos limites do art.86 e sem padrão de rede coordenada — sem indício de carona abusiva")
                res.explicacao_inocente = (
                    "adesões dentro dos limites legais; ata vantajosa atrai caronas legítimas (verificar preço P3)")
                return res

            # sem violação mas rede coordenada / ata cara → confirma como indício subjetivo
            score = max(score, sub_score)
            res.score = round(score, 4)
            res.status = "confirmado"
            res.valores = valores
            res.motivo_refutacao = "; ".join(razoes)
            res.explicacao_inocente = (
                "atas BEM precificadas atraem adesões legítimas — confirmar o preço (P3 na data da adesão): "
                "carona de ata barata é gestão; carona de ata cara é o esquema")
            return res

        # ── VIOLAÇÃO OBJETIVA DE LIMITE: confirmado/crítico (multiplica o dano sem novo certame) ──
        # As rubricas subjetivas (rede coordenada) só reforçam o achado já crítico; preço cara agrava a narrativa.
        if just["status"] in ("texto_padrao", "ausente"):
            razoes.append(f"rubrica justificativa: '{just['status']}' — reforça coordenação")
        if rede["status"] == "concentracao_anomala":
            razoes.append("rubrica rede: concentração anômala — vetor de investigação (cruzar C6)")
        if preco is not None and preco > _PRECO_ATA_JUSTA:
            razoes.append(f"discriminador de preço: ata CARA ({preco:.2f}× mercado) — carona de ata cara é o esquema")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = (
            "EXCULPATÓRIA a checar (spec X4): compras centralizadas BEM precificadas atraem adesões legítimas — o "
            "teste de PREÇO (P3 na data da adesão) é o discriminador. Porém os LIMITES do art.86 (§4º individual ≤50%; "
            "§5º total ≤ dobro) são OBJETIVOS e foram excedidos: a violação independe da vantagem do preço.")
        return res

    # ───────────────────────────── Rubricas subjetivas (LLM-opcional) ─────────────────────────────
    def _avaliar_justificativas(self, contexto: dict, adesoes: list) -> dict:
        """Rubrica (1): justificativa de vantagem da adesão. O CÓDIGO computa a similaridade máxima entre
        justificativas de aderentes DISTINTOS; a rubrica CLASSIFICA. Atalho de teste: `_rubrica_justificativa`
        injetado. Sem rubrica e sem LLM → nao_avaliavel honesto (a similaridade fica registrada à parte)."""
        # similaridade máxima entre justificativas de aderentes distintos (sinal de boilerplate/rede)
        just = [(a.get("aderente"), str(a.get("justificativa") or "").strip())
                for a in adesoes if isinstance(a, dict) and str(a.get("justificativa") or "").strip()]
        sim_max = 0.0
        par_max = None
        for i in range(len(just)):
            for j in range(i + 1, len(just)):
                if just[i][0] == just[j][0]:
                    continue  # mesmo aderente não conta para "rede coordenada"
                s = _similaridade(just[i][1], just[j][1])
                if s > sim_max:
                    sim_max = s
                    par_max = (just[i], just[j])

        return self._rubrica_justificativa(contexto, sim_max=sim_max, par_max=par_max)

    def _rubrica_justificativa(self, contexto: dict, *, sim_max: float = 0.0, par_max=None) -> dict:
        """Classifica a rubrica (1). Atalho de teste `_rubrica_justificativa`; senão deriva do código
        (similaridade ≥95% entre aderentes distintos → texto_padrao); senão LLM; senão nao_avaliavel."""
        pre = contexto.get("_rubrica_justificativa")
        if pre is not None:
            nivel, _s, motivo = avaliar_rubrica(pre, _RUBRICA_JUSTIFICATIVA)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo, "similaridade": round(sim_max, 4)}
            classe = (pre.get("nivel") or pre.get("classificacao") or "").strip().lower()
            return {"status": classe, "motivo": motivo, "similaridade": round(sim_max, 4)}

        # derivação OBJETIVA: similaridade ≥95% entre aderentes distintos ⇒ texto_padrão (rede coordenada)
        if par_max is not None and sim_max >= _SIM_TEXTO_PADRAO:
            return {"status": "texto_padrao",
                    "motivo": f"justificativas de aderentes distintos com similaridade {sim_max:.0%} (≥95%)",
                    "similaridade": round(sim_max, 4)}

        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel",
                    "motivo": "LLM ausente — qualidade da justificativa não auditada (honesto)",
                    "similaridade": round(sim_max, 4)}
        sistema = (
            "Você é auditor de controle externo avaliando a JUSTIFICATIVA DE VANTAGEM de uma adesão a ata (art.86 §2º I). "
            "Classifique conforme a rubrica fechada. Responda SOMENTE com JSON: "
            '{"nivel":"demonstra_vantagem_com_numeros|texto_padrao|ausente","trecho":"<citação literal>"}. '
            "Sem trecho, não classifique.")
        trechos = []
        if par_max is not None:
            trechos = [par_max[0][1][:200], par_max[1][1][:200]]
        prompt = f"Justificativas de vantagem (aderentes distintos):\n{chr(10).join(trechos)[:1000]}"
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})",
                    "similaridade": round(sim_max, 4)}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _s, motivo = avaliar_rubrica(dados, _RUBRICA_JUSTIFICATIVA)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo, "similaridade": round(sim_max, 4)}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo,
                "similaridade": round(sim_max, 4)}

    def _avaliar_rede(self, contexto: dict) -> dict:
        """Rubrica (2): padrão geográfico/político da rede de aderentes. Delega à classificação."""
        return self._rubrica_rede(contexto)

    def _rubrica_rede(self, contexto: dict) -> dict:
        """Classifica a rubrica (2). Atalho de teste `_rubrica_rede`; senão deriva de `vinculo_aderentes`
        (bool/dados de concentração); senão LLM; senão nao_avaliavel honesto."""
        pre = contexto.get("_rubrica_rede")
        if pre is not None:
            nivel, _s, motivo = avaliar_rubrica(pre, _RUBRICA_REDE)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            classe = (pre.get("nivel") or pre.get("classificacao") or "").strip().lower()
            return {"status": classe, "motivo": motivo}

        # derivação: sinal explícito de vínculo/concentração entre aderentes
        vinc = contexto.get("vinculo_aderentes")
        if vinc:
            return {"status": "concentracao_anomala",
                    "motivo": "vínculo/concentração entre aderentes sinalizado no contexto (vetor de investigação — cruzar C6)"}

        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — padrão da rede não auditado (honesto)"}
        adesoes = contexto.get("adesoes") or []
        municipios = "; ".join(sorted({str(a.get("municipio")) for a in adesoes
                                       if isinstance(a, dict) and a.get("municipio")}))
        sistema = (
            "Você é auditor de controle externo avaliando o PADRÃO GEOGRÁFICO/POLÍTICO da rede de aderentes a uma ata. "
            "Classifique conforme a rubrica fechada. Responda SOMENTE com JSON: "
            '{"nivel":"dispersao_natural|concentracao_anomala","trecho":"<citação literal>"}. Sem trecho, não classifique.')
        prompt = f"Municípios dos aderentes: {municipios[:1000]}\n\nDispersão natural ou concentração anômala?"
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _s, motivo = avaliar_rubrica(dados, _RUBRICA_REDE)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
