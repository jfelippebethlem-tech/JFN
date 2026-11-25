# -*- coding: utf-8 -*-
"""X2 · PRORROGAÇÃO PERPÉTUA (spec V2 do dono, §X2 — FASE DE EXECUÇÃO).

Mecanismo: o MESMO fornecedor é mantido por ANOS no mesmo SERVIÇO por prorrogações automáticas, sem TESTE DE
MERCADO — a competição morre na primeira licitação e nunca mais volta. A unidade aqui é o SERVIÇO (o objeto
continuado), NÃO o número do contrato: um contrato relicitado, ou uma cadeia emergência→prorrogação→
recontratação, mantém o mesmo fornecedor no mesmo objeto.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • TEMPO TOTAL do fornecedor no objeto (anos), medido contra o prazo máximo DO REGIME DO CONTRATO (O4.9, 24/11/2026 —
    `contexto["regime"]`, de `dominio.regime.regime_contrato`; nunca pelo ano corrente):
      L8666   > 5 anos (60 meses, art. 57 II) ........ forte (0.85) · > 6 anos (60 + 12 do §4º) ... crítico (1.0)
      L14133  > 10 anos (vigência máxima decenal, art. 107) ......................................... crítico (1.0)
              5–10 anos é prazo LÍCITO (arts. 106–107): o tempo sozinho não pontua.
      L13303  > 5 anos (art. 71) ... médio (0.6): o art. 71 I/II admite prazo maior; nada de crítico pelo tempo.
      sem regime (INDETERMINADO/OUTRO/ausente) > 10 anos ... crítico (ilegal nos dois regimes) ·
              > 5 anos ... médio (ilegal na 8.666, lícito na 14.133 — o regime decide; declarado na saída).
    Texto conferido VERBATIM (~/vault/fontes/juridicas, 24/11/2026):
      L8666cons.htm (md5 26a008466a58e90b5a2f6cc36e17b050) art. 57 II (red. Lei 9.648/1998): "que poderão ter a sua
        duração prorrogada por iguais e sucessivos períodos com vistas à obtenção de preços e condições mais vantajosas
        para a administração, limitada a sessenta meses"; §4º "Em caráter excepcional, devidamente justificado e
        mediante autorização da autoridade superior, o prazo de que trata o inciso II do caput deste artigo poderá ser
        prorrogado por até doze meses."
      L14133.htm (md5 5107e213168afb4c15a36665e6695c58) art. 106 "contratos com prazo de até 5 (cinco) anos nas
        hipóteses de serviços e fornecimentos contínuos"; art. 107 "poderão ser prorrogados sucessivamente, respeitada
        a vigência máxima decenal, desde que haja previsão em edital e que a autoridade competente ateste que as
        condições e os preços permanecem vantajosos para a Administração".
      L13303.htm (md5 326f5390c34ff235a3aeafa9529d98de) art. 71 "não excederá a 5 (cinco) anos, contados a partir de
        sua celebração, exceto: I - [...] plano de negócios e investimentos [...]; II - [...] prática rotineira de
        mercado".
  • Nº de prorrogações sem nova licitação (≥ limiar) ......................................... sinal / medio (O4.9)
  • Cadeia emergência → prorrogação/recontratação (detectar) ................................. agrava (+0.10)

PARTE SUBJETIVA (rubrica fechada LLM-OPCIONAL, degrada honesto): "Qualidade da pesquisa de vantajosidade" POR
renovação: [pesquisa-real (painéis e referências atuais) / pesquisa-pro-forma (3 cotações dos suspeitos de
sempre — rodar P2 nela) / ausente]. 'ausente' ou 'pro_forma' → CONFIRMA o vício (forte). Se a classificação já
vier no próprio contexto (`pesquisa_vantajosidade` no dict da prorrogação), o CÓDIGO usa direto, SEM LLM. Sem
classificação e sem LLM → a qualidade fica `nao_avaliavel` (o achado de TEMPO objetivo permanece).

TESTE EXCULPATÓRIO (spec): prorrogar com vantajosidade REAL e DOCUMENTADA é gestão correta (evita custo de
transição) — o detector pune a AUSÊNCIA de teste de mercado, NÃO a prorrogação em si. TODAS as prorrogações com
vantajosidade 'real' documentada → exculpatória (rebaixa/descarta).

HONESTIDADE JFN: indício ≠ acusação; sem `vigencia_inicio`/`vigencia_fim_atual`/`tempo_total_anos` E sem
`prorrogacoes` → nao_avaliavel (campo ausente ≠ 0); nunca inventa número (anos/contagem).
"""
from __future__ import annotations

from datetime import date

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    nivel_rubrica,
    para_data,
    perguntar_rubrica,
)

# ───────────────────────────── Limiares objetivos (CÓDIGO, nunca prompt) ─────────────────────────────
_ANOS_FORTE = 5.0      # 8.666 art. 57 II: sessenta meses
_ANOS_CRITICO = 10.0   # 14.133 art. 107: vigência máxima decenal (teto também quando o regime é desconhecido)
_ANOS_CRITICO_8666 = 6.0   # 8.666 art. 57 §4º: 60 meses + até 12 em caráter excepcional
_ANOS_IMPLAUSIVEL = 15.0
"""Acima disto não há hipótese legal que sustente: é erro de data na fonte, não contrato eterno.
Número impossível é leitura quebrada, não achado (família 13 do catálogo de falhas)."""
_PRORROGACOES_FORTE = 3  # ≥ 3 prorrogações sem nova licitação → forte

# Rubrica fechada da qualidade da pesquisa de vantajosidade por renovação (spec X2). LLM-opcional; degrada honesto.
# 'real' → gestão correta (exculpatória); 'pro_forma'/'ausente' → confirma o vício.
_RUBRICA_VANTAJOSIDADE = {
    "real": "ausente",        # pesquisa real (painéis/referências atuais) → teste de mercado feito
    "pro_forma": "forte",     # 3 cotações dos suspeitos de sempre (rodar P2) → vício
    "ausente": "forte",       # sem pesquisa nenhuma → vício
}
_CLASSES_VANTAJOSIDADE = set(_RUBRICA_VANTAJOSIDADE)


def _anos_entre(inicio: date, fim: date) -> float:
    """Diferença em anos (decimais) entre duas datas."""
    return round((fim - inicio).days / 365.25, 2)


def _tempo_total_anos(contexto: dict) -> tuple[float | None, str]:
    """Calcula o TEMPO TOTAL do fornecedor no objeto (anos), em ordem de preferência:
      1) `tempo_total_anos` explícito no contexto (float);
      2) parse de `vigencia_inicio`→`vigencia_fim_atual` (datas);
      3) parse de `vigencia_inicio` + soma de `anos` das prorrogações.
    Retorna (anos|None, fonte_textual). None → sem dado de tempo (nao_avaliavel honesto)."""
    tt = contexto.get("tempo_total_anos")
    if tt is not None:
        try:
            return round(float(tt), 2), "tempo_total_anos informado"
        except (TypeError, ValueError):
            pass

    ini = para_data(contexto.get("vigencia_inicio"))
    fim = para_data(contexto.get("vigencia_fim_atual"))
    if ini and fim:
        return _anos_entre(ini, fim), f"vigência {ini.isoformat()} → {fim.isoformat()}"

    # fallback: início + soma dos 'anos' de cada prorrogação (a vigência original costuma ser ~1 ano se ausente)
    prorrogacoes = contexto.get("prorrogacoes") or []
    if ini and prorrogacoes:
        # fim de cada prorrogação por data, se houver; senão soma os 'anos'
        datas_fim = [para_data(p.get("data")) for p in prorrogacoes if isinstance(p, dict)]
        datas_fim = [d for d in datas_fim if d]
        if datas_fim:
            return _anos_entre(ini, max(datas_fim)), f"vigência início {ini.isoformat()} → última prorrogação"
        soma_anos = sum(float(p.get("anos") or 0) for p in prorrogacoes if isinstance(p, dict))
        if soma_anos > 0:
            base = float(contexto.get("vigencia_original_anos") or 1.0)
            return round(base + soma_anos, 2), "vigência original + anos das prorrogações"
    return None, ""


def _regua_tempo(anos: float, regime: str | None) -> tuple[str, str]:
    """(nível, razão) do TEMPO contra o prazo máximo do regime do contrato. 'ausente' = o tempo não pontua."""
    r = str(regime or "").strip().upper()
    if r == "L8666":
        if anos > _ANOS_CRITICO_8666:
            return "critico", (f"{anos} anos no mesmo objeto: acima dos 60 meses do art. 57 II mais os 12 excepcionais "
                               "do §4º (Lei 8.666/1993)")
        if anos > _ANOS_FORTE:
            return "forte", (f"{anos} anos no mesmo objeto: acima dos 60 meses do art. 57 II (Lei 8.666/1993) — só "
                             "cabe pelo §4º (excepcional, justificado e autorizado pela autoridade superior)")
        return "ausente", ""
    if r == "L14133":
        if anos > _ANOS_CRITICO:
            return "critico", f"{anos} anos no mesmo objeto: acima da vigência máxima decenal (Lei 14.133/2021, art. 107)"
        return "ausente", ""
    if r == "L13303":
        if anos > _ANOS_FORTE:
            return "medio", (f"{anos} anos no mesmo objeto: acima dos 5 anos do art. 71 da Lei 13.303/2016 — o próprio "
                             "art. 71 (I e II) admite prazo maior; conferir a exceção invocada")
        return "ausente", ""
    if anos > _ANOS_CRITICO:
        return "critico", (f"{anos} anos no mesmo objeto: acima do prazo máximo nos dois regimes (Lei 8.666 art. 57 II "
                           "e §4º; Lei 14.133 art. 107)")
    if anos > _ANOS_FORTE:
        return "medio", (f"{anos} anos no mesmo objeto com regime do contrato NÃO determinado: ilegal se Lei 8.666 "
                         "(art. 57 II: 60 meses), lícito se Lei 14.133 (art. 107: até 10 anos) — ler o instrumento")
    return "ausente", ""


def _tem_cadeia_emergencia(contexto: dict) -> bool:
    """Detecta a cadeia emergência→prorrogação/recontratação. Aceita `cadeia_emergencia` (bool ou lista
    não-vazia) OU o fundamento de alguma prorrogação citando 'emergência'/'emergencial'/'dispensa'."""
    ce = contexto.get("cadeia_emergencia")
    if isinstance(ce, bool):
        if ce:
            return True
    elif isinstance(ce, (list, tuple, set)) and len(ce) > 0:
        return True
    for p in (contexto.get("prorrogacoes") or []):
        if not isinstance(p, dict):
            continue
        fund = str(p.get("fundamento") or "").lower()
        if "emerg" in fund or "calamidade" in fund:
            return True
    return False


class X2ProrrogacaoPerpetua(Detector):
    """Detector X2 — prorrogação perpétua (fase de execução; spec V2 §X2).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do processo/contrato/serviço.
      ESSENCIAL (um dos dois): `tempo_total_anos` (float) OU o par `vigencia_inicio`/`vigencia_fim_atual`
          (datas str/date) para o CÓDIGO calcular o tempo total do fornecedor no objeto.
      contexto["prorrogacoes"] (opcional): list[dict], cada uma podendo trazer
          {data?, anos?, fundamento?, pesquisa_vantajosidade? ('real'|'pro_forma'|'ausente'), preco?, ref_mercado?}.
          Se `pesquisa_vantajosidade` vier classificada, o CÓDIGO usa direto (sem LLM).
      contexto["cadeia_emergencia"] (opcional bool|list): cadeia emergência→prorrogação/recontratação → agrava.
      contexto["fornecedor_cnpj"] (opcional): identifica o fornecedor mantido no objeto.
      contexto["_rubricas_vantajosidade"] (opcional, teste) / contexto["gerar"] (opcional): rubrica LLM da
          qualidade da pesquisa de vantajosidade por renovação.

    Honesto: sem tempo total apurável E sem prorrogações → nao_avaliavel (campo ausente ≠ 0)."""

    id = "X2"
    nome = "Prorrogação perpétua"
    familia = "execucao"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        prorrogacoes = [p for p in (contexto.get("prorrogacoes") or []) if isinstance(p, dict)]
        anos, fonte_tempo = _tempo_total_anos(contexto)

        # honestidade: sem QUALQUER base de tempo e sem prorrogações, não há o que avaliar.
        if anos is None and not prorrogacoes:
            res.motivo_refutacao = (
                "nao_avaliavel: sem vigencia_inicio/vigencia_fim_atual nem tempo_total_anos, e sem prorrogacoes — "
                "não é possível aferir o tempo do fornecedor no objeto (campo ausente ≠ 0)")
            res.valores = {"tem_tempo": False, "n_prorrogacoes": len(prorrogacoes)}
            return res

        n_prorrogacoes = len(prorrogacoes)
        tem_cadeia = _tem_cadeia_emergencia(contexto)

        valores: dict = {
            "tempo_total_anos": anos,
            "fonte_tempo": fonte_tempo,
            "n_prorrogacoes": n_prorrogacoes,
            "cadeia_emergencia": tem_cadeia,
            "fornecedor_cnpj": contexto.get("fornecedor_cnpj"),
        }

        # ── REGRAS OBJETIVAS (código, nunca prompt) ──
        score = 0.0
        razoes: list[str] = []

        # INVARIANTE DE PLAUSIBILIDADE. Prazo além de qualquer hipótese legal não é violação
        # maior — é DADO ERRADO. Medido em 2026-08-04, no primeiro processo em que este detector
        # conseguiu avaliar depois de ligarem a vigência: SEI-260007/009935/2024, "AQUISIÇÃO DO
        # MEDICAMENTO CIPROFLOXACINO" por R$ 58.608,00, com `vig_inicio` de 08/06/2002 no registro
        # do TCE-RJ — **23,01 anos** para uma compra pontual de remédio. O detector devolvia
        # `critico` 1,0 e levava o processo a EXTREMO.
        # A lei admite 5 anos, e 10 nas hipóteses excepcionais; acima de `_ANOS_IMPLAUSIVEL` não há
        # hipótese que sustente, então a saída honesta é nao_avaliavel dizendo o que não fecha —
        # mesma doutrina do X9 ("não se suprime mais do que existe").
        if anos is not None and anos > _ANOS_IMPLAUSIVEL:
            res.status = "nao_avaliavel"
            res.score = 0.0
            res.valores = {**valores, "anos": anos, "prazo_implausivel": True}
            res.motivo_refutacao = (
                f"nao_avaliavel: vigência apurada de {anos:.1f} anos excede qualquer hipótese "
                f"legal (a lei admite 5, e 10 nas excepcionais) — acima de "
                f"{_ANOS_IMPLAUSIVEL:g} anos o que está errado é a DATA, não o contrato. "
                "Conferir `vig_inicio` na fonte antes de afirmar prorrogação perpétua.")
            return res

        regime = contexto.get("regime")
        valores["regime"] = regime or "INDETERMINADO"
        if anos is not None:
            nivel_tempo, razao_tempo = _regua_tempo(anos, regime)
            valores["nivel_tempo"] = nivel_tempo
            if nivel_tempo != "ausente":
                score = max(score, ancora(nivel_tempo))
                razoes.append(razao_tempo)
            res.add_evidencia(
                fonte="vigência do contrato/serviço",
                trecho=f"tempo total no objeto = {anos} anos ({fonte_tempo}); {n_prorrogacoes} prorrogação(ões)")

        # nº de prorrogações sem nova licitação — O4.9 (decisão conservadora delegada pelo dono): prorrogar "por iguais
        # e sucessivos períodos" é o que a lei prevê (8.666 art. 57 II; 14.133 art. 107 "sucessivamente"; TCU Ac.
        # 5.820/2011-2ª Câmara recomenda prever a prorrogação até 60 meses). A CONTAGEM sozinha é sinal ('medio');
        # o vício é o TEMPO acima do prazo do regime ou a vantajosidade ausente.
        if n_prorrogacoes >= _PRORROGACOES_FORTE:
            score = max(score, ancora("medio"))
            razoes.append(f"{n_prorrogacoes} prorrogações sem nova licitação (≥ {_PRORROGACOES_FORTE}) — sinal: prorrogar "
                          "sucessivamente é lícito dentro do prazo do regime")

        # cadeia emergência → prorrogação/recontratação → agrava
        if tem_cadeia and score > 0:
            score = min(1.0, score + 0.10)
            razoes.append("cadeia emergência→prorrogação/recontratação detectada (mantém o fornecedor sem certame)")
        elif tem_cadeia and score == 0:
            # a cadeia emergencial sozinha já é anomalia clara a confirmar
            score = max(score, ancora("medio"))
            razoes.append("cadeia emergência→prorrogação/recontratação detectada (anomalia a confirmar)")

        # ── PARTE SUBJETIVA (LLM-opcional): qualidade da pesquisa de vantajosidade POR renovação ──
        # 'real' em todas → exculpatória; 'ausente'/'pro_forma' em alguma → confirma o vício (forte).
        vant = self._avaliar_vantajosidade(prorrogacoes, contexto=contexto)
        valores["vantajosidade"] = vant
        n_viciada = sum(1 for v in vant if v["classe"] in ("ausente", "pro_forma"))
        n_real = sum(1 for v in vant if v["classe"] == "real")
        n_classificada = sum(1 for v in vant if v["classe"] in _CLASSES_VANTAJOSIDADE)
        valores["n_vantajosidade_viciada"] = n_viciada
        valores["n_vantajosidade_real"] = n_real

        if n_viciada > 0:
            score = max(score, ancora("forte"))
            razoes.append(f"{n_viciada} renovação(ões) com pesquisa de vantajosidade ausente/pró-forma "
                          "(sem teste de mercado real)")
            for v in vant:
                if v["classe"] in ("ausente", "pro_forma"):
                    res.add_evidencia(
                        fonte=f"pesquisa de vantajosidade (prorrogação #{v['idx']})",
                        trecho=f"qualidade={v['classe']}: {v['motivo']}")

        # ── EXCULPATÓRIA do spec: prorrogar com vantajosidade REAL documentada é gestão correta ──
        # TODAS as prorrogações classificadas como 'real' e NENHUMA viciada → rebaixa/descarta.
        # NÃO se aplica à cadeia emergência→prorrogação: burlar o certame por emergência não se sana com
        # pesquisa de preço (o vício é a AUSÊNCIA de licitação, não o preço).
        if (n_prorrogacoes > 0 and n_classificada == n_prorrogacoes and n_viciada == 0
                and n_real == n_prorrogacoes and not tem_cadeia):
            if anos is not None and anos > _ANOS_CRITICO:
                # tempo extremo: a vantajosidade real rebaixa, não zera (transição custa, mas década é demais)
                score = min(score, ancora("medio"))
                razoes.append("todas as renovações com vantajosidade REAL documentada — exculpatória rebaixa "
                              "(tempo extremo ainda merece atenção)")
            else:
                res.status = "descartado"
                res.score = 0.0
                res.valores = valores
                res.motivo_refutacao = ("todas as prorrogações com pesquisa de vantajosidade REAL e documentada — "
                                        "teste de mercado feito a cada renovação (gestão correta, não vício)")
                res.explicacao_inocente = ("prorrogar com vantajosidade real documentada evita custo de transição; "
                                           "o detector pune a AUSÊNCIA de teste de mercado, não a prorrogação em si")
                return res

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = (
                "tempo dentro do razoável, poucas prorrogações e sem cadeia emergencial — sem indício de "
                "prorrogação perpétua")
            res.valores = valores
            res.explicacao_inocente = ("prorrogação curta/normal de contrato com vantajosidade demonstrada — "
                                       "gestão regular, não perpetuação sem teste de mercado")
            return res

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = (
            "EXCULPATÓRIA a verificar (spec X2): prorrogar com vantajosidade REAL e DOCUMENTADA é gestão correta "
            "(evita custo de transição) — o detector pune a AUSÊNCIA de teste de mercado, NÃO a prorrogação em si. "
            "Verificar a pesquisa de vantajosidade de cada renovação (real × pró-forma × ausente); pró-forma → rodar P2.")
        return res

    def _avaliar_vantajosidade(self, prorrogacoes: list[dict], *, contexto: dict) -> list[dict]:
        """Avalia a qualidade da pesquisa de vantajosidade POR prorrogação. Ordem de preferência:
          1) `pesquisa_vantajosidade` já classificada no dict da prorrogação → CÓDIGO usa direto (sem LLM);
          2) rubrica pré-injetada em `contexto['_rubricas_vantajosidade']` (lista alinhada às prorrogações, teste);
          3) LLM (`contexto['gerar']`) — rubrica fechada + citação obrigatória, degrada honesto;
          4) sem nada → 'nao_avaliavel' (o achado de tempo objetivo permanece).
        Retorna lista de {idx, classe('real'|'pro_forma'|'ausente'|'nao_avaliavel'), motivo}."""
        rubricas = contexto.get("_rubricas_vantajosidade")
        gerar = contexto.get("gerar")
        out: list[dict] = []
        for i, p in enumerate(prorrogacoes):
            # 1) classificação direta no próprio dict
            direta = str(p.get("pesquisa_vantajosidade") or "").strip().lower()
            if direta in _CLASSES_VANTAJOSIDADE:
                out.append({"idx": i, "classe": direta, "motivo": "classificada no contexto da prorrogação"})
                continue
            # 2) rubrica pré-injetada (teste determinístico, sem rede)
            if isinstance(rubricas, (list, tuple)) and i < len(rubricas) and rubricas[i] is not None:
                classe, motivo = nivel_rubrica(rubricas[i], _RUBRICA_VANTAJOSIDADE)
                out.append({"idx": i, "classe": classe, "motivo": motivo})
                continue
            # 3) LLM
            if gerar is not None:
                out.append(self._vantajosidade_llm(i, p, gerar))
                continue
            # 4) honesto: sem juízo
            out.append({"idx": i, "classe": "nao_avaliavel",
                        "motivo": "sem classificação no contexto e sem LLM — qualidade não auditada (honesto)"})
        return out

    def _vantajosidade_llm(self, idx: int, p: dict, gerar) -> dict:
        """Caminho LLM (rubrica fechada + citação obrigatória) para UMA prorrogação. Degrada honesto."""
        sistema = (
            "Você é auditor de controle externo avaliando uma PRORROGAÇÃO contratual. Classifique a QUALIDADE da "
            "PESQUISA DE VANTAJOSIDADE que a fundamentou, conforme a rubrica fechada. Responda SOMENTE com JSON: "
            '{"nivel":"real|pro_forma|ausente","trecho":"<citação literal da fonte das referências usadas>"}. '
            "real = painéis/referências de mercado atuais; pro_forma = 3 cotações dos suspeitos de sempre; "
            "ausente = sem pesquisa. Sem trecho, não classifique.")
        prompt = (f"Prorrogação #{idx}: fundamento='{str(p.get('fundamento') or '')[:200]}' "
                  f"preço={p.get('preco')} ref_mercado={p.get('ref_mercado')}.\n\n"
                  "Classifique a qualidade da pesquisa de vantajosidade.")
        classe, motivo, _ = perguntar_rubrica(gerar, prompt, sistema, _RUBRICA_VANTAJOSIDADE)
        return {"idx": idx, "classe": classe, "motivo": motivo}
