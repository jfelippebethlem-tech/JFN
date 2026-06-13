# -*- coding: utf-8 -*-
"""X2 · PRORROGAÇÃO PERPÉTUA (spec V2 do dono, §X2 — FASE DE EXECUÇÃO).

Mecanismo: o MESMO fornecedor é mantido por ANOS no mesmo SERVIÇO por prorrogações automáticas, sem TESTE DE
MERCADO — a competição morre na primeira licitação e nunca mais volta. A unidade aqui é o SERVIÇO (o objeto
continuado), NÃO o número do contrato: um contrato relicitado, ou uma cadeia emergência→prorrogação→
recontratação, mantém o mesmo fornecedor no mesmo objeto.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • TEMPO TOTAL do fornecedor no objeto (anos): muito longo sem relicitar → forte; muito mais longo → crítico.
      > 5 anos no mesmo objeto sem nova licitação ............................................. forte (0.85)
      > 10 anos no mesmo objeto sem nova licitação ............................................ crítico (1.0)
  • Nº de prorrogações sem nova licitação (≥ limiar) ......................................... agrava / forte
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

from datetime import date, datetime

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# ───────────────────────────── Limiares objetivos (CÓDIGO, nunca prompt) ─────────────────────────────
_ANOS_FORTE = 5.0      # > 5 anos no mesmo objeto sem relicitar → forte
_ANOS_CRITICO = 10.0   # > 10 anos → crítico
_PRORROGACOES_FORTE = 3  # ≥ 3 prorrogações sem nova licitação → forte

# Rubrica fechada da qualidade da pesquisa de vantajosidade por renovação (spec X2). LLM-opcional; degrada honesto.
# 'real' → gestão correta (exculpatória); 'pro_forma'/'ausente' → confirma o vício.
_RUBRICA_VANTAJOSIDADE = {
    "real": "ausente",        # pesquisa real (painéis/referências atuais) → teste de mercado feito
    "pro_forma": "forte",     # 3 cotações dos suspeitos de sempre (rodar P2) → vício
    "ausente": "forte",       # sem pesquisa nenhuma → vício
}
_CLASSES_VANTAJOSIDADE = set(_RUBRICA_VANTAJOSIDADE)


def _data(v) -> date | None:
    """Parse tolerante de data (str ISO/BR, date, datetime) → date, ou None."""
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(v[:19] if "T" in v else v[:10], fmt).date()
            except ValueError:
                continue
    return None


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

    ini = _data(contexto.get("vigencia_inicio"))
    fim = _data(contexto.get("vigencia_fim_atual"))
    if ini and fim:
        return _anos_entre(ini, fim), f"vigência {ini.isoformat()} → {fim.isoformat()}"

    # fallback: início + soma dos 'anos' de cada prorrogação (a vigência original costuma ser ~1 ano se ausente)
    prorrogacoes = contexto.get("prorrogacoes") or []
    if ini and prorrogacoes:
        # fim de cada prorrogação por data, se houver; senão soma os 'anos'
        datas_fim = [_data(p.get("data")) for p in prorrogacoes if isinstance(p, dict)]
        datas_fim = [d for d in datas_fim if d]
        if datas_fim:
            return _anos_entre(ini, max(datas_fim)), f"vigência início {ini.isoformat()} → última prorrogação"
        soma_anos = sum(float(p.get("anos") or 0) for p in prorrogacoes if isinstance(p, dict))
        if soma_anos > 0:
            base = float(contexto.get("vigencia_original_anos") or 1.0)
            return round(base + soma_anos, 2), "vigência original + anos das prorrogações"
    return None, ""


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
    familia = "execucao"  # X2 — peso 0.8 (execução) na convergência §7.2

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

        if anos is not None:
            if anos > _ANOS_CRITICO:
                score = max(score, ancora("critico"))
                razoes.append(f"fornecedor há {anos} anos no mesmo objeto sem relicitar (> {_ANOS_CRITICO:g} anos)")
            elif anos > _ANOS_FORTE:
                score = max(score, ancora("forte"))
                razoes.append(f"fornecedor há {anos} anos no mesmo objeto sem relicitar (> {_ANOS_FORTE:g} anos)")
            res.add_evidencia(
                fonte="vigência do contrato/serviço",
                trecho=f"tempo total no objeto = {anos} anos ({fonte_tempo}); {n_prorrogacoes} prorrogação(ões)")

        # nº de prorrogações sem nova licitação
        if n_prorrogacoes >= _PRORROGACOES_FORTE:
            score = max(score, ancora("forte"))
            razoes.append(f"{n_prorrogacoes} prorrogações sem nova licitação (≥ {_PRORROGACOES_FORTE})")

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
                nivel, _score, motivo = avaliar_rubrica(rubricas[i], _RUBRICA_VANTAJOSIDADE)
                classe = (rubricas[i].get("nivel") or rubricas[i].get("classificacao") or "").strip().lower()
                if nivel is None or classe not in _CLASSES_VANTAJOSIDADE:
                    out.append({"idx": i, "classe": "nao_avaliavel", "motivo": motivo})
                else:
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
        try:
            raw = gerar(prompt, sistema)
        except Exception as e:  # noqa: BLE001 — degrada honesto
            return {"idx": idx, "classe": "nao_avaliavel", "motivo": f"LLM indisponível ({str(e)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_VANTAJOSIDADE)
        if nivel is None or not isinstance(dados, dict):
            return {"idx": idx, "classe": "nao_avaliavel", "motivo": motivo}
        classe = (dados.get("nivel") or "").strip().lower()
        if classe not in _CLASSES_VANTAJOSIDADE:
            return {"idx": idx, "classe": "nao_avaliavel", "motivo": motivo}
        return {"idx": idx, "classe": classe, "motivo": motivo}
