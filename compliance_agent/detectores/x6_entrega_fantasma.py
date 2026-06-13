# -*- coding: utf-8 -*-
"""X6 · ENTREGA FANTASMA / ATESTO DE FACHADA (spec V2 do dono, §X6 — fase de EXECUÇÃO).

Mecanismo: paga-se por bem NÃO entregue ou serviço NÃO prestado, com cumplicidade (ou negligência) do fiscal que
atesta. É a fraude de MAIOR dano unitário e a que mais DEPENDE de evidência de campo — por isso este detector
CULMINA numa DILIGÊNCIA FÍSICA: a IA PREPARA o roteiro do que verificar, não substitui a visita.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • Tríade documental NF × registro de recebimento × pagamento INCOMPLETA (paga sem NF ou sem recebimento) .. 'forte'
  • Volume entregue × CAPACIDADE do fornecedor (sem funcionários/frota para o volume — cruza C2) ........... 'forte'
  • Cadência das medições: valores IDÊNTICOS repetidos / datas suspeitas .................................. indício
  • Baixa ROTAÇÃO de fiscal (sempre o mesmo fiscal designado) ............................................. agrava (+)

PARTE SUBJETIVA (DUAS rubricas fechadas LLM-OPCIONAIS, degradam honesto):
  (1) Especificidade do conteúdo dos atestos [especifico / generico / contraditorio].
      contraditorio (atesta o que outro documento NEGA) → 'forte' (0.85). Evidência: texto × documento conflitante.
  (2) Verossimilhança física da execução [verificavel-em-campo / inverificavel].
      verificavel-em-campo → recomenda DILIGÊNCIA com roteiro do que fotografar (local, bem, quantidade).

TESTE EXCULPATÓRIO (spec): serviços de VALOR FIXO MENSAL (locação, assinatura) têm medições IDÊNTICAS
legitimamente — classificar a NATUREZA do objeto ANTES de pontuar cadência (`tipo_objeto` in {'locacao',
'assinatura'} rebaixa a cadência idêntica). Atesto GENÉRICO é má prática generalizada, não prova de fraude:
0.6 ('medio') e SÓ sobe com CONTRADIÇÃO documental ou tríade incompleta.

PRODUTO FINAL: o ROTEIRO DE DILIGÊNCIA física (lista de pontos a verificar) em `valores["roteiro_diligencia"]`
para os contratos de maior score.

HONESTIDADE JFN: indício ≠ acusação; sem NFs/atestos/pagamentos → nao_avaliavel (campo ausente ≠ 0); nunca
inventa número.
"""
from __future__ import annotations

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# ───────────────────────────── Rubricas fechadas (LLM-opcional; degradam honesto) ─────────────────────────────
# (1) Especificidade do conteúdo dos atestos → nível de âncora.
_RUBRICA_ESPECIFICIDADE = {
    "especifico": "ausente",      # quantidades, locais, datas verificáveis → conteúdo idôneo
    "generico": "medio",          # 'serviços prestados a contento' — má prática, não prova; só sobe com contradição/tríade
    "contraditorio": "forte",     # atesta o que outro documento NEGA → forte (0.85)
}

# (2) Verossimilhança física da execução → nível de âncora.
# 'verificavel_em_campo' NÃO inflama o score sozinho: dispara a recomendação de DILIGÊNCIA (roteiro).
_RUBRICA_VEROSSIMILHANCA = {
    "verificavel_em_campo": "ausente",   # dá para conferir in loco → recomenda diligência (roteiro)
    "inverificavel": "ausente",          # objeto imaterial/consumido → registra, não pontua
}

# Tipos de objeto de VALOR FIXO MENSAL: medições idênticas são legítimas (exculpa cadência).
_TIPOS_VALOR_FIXO = ("locacao", "locação", "assinatura", "aluguel", "mensalidade")

# Palavras-chave de atesto GENÉRICO (má prática) — heurística de fallback quando não há rubrica LLM.
_TERMOS_GENERICOS = (
    "a contento", "satisfatoriamente", "conforme contratado", "regularmente", "serviços prestados",
    "servicos prestados", "de acordo", "sem ressalvas", "atesto os serviços", "atesto os servicos",
)


def _is_valor_fixo(tipo_objeto: str | None) -> bool:
    t = (tipo_objeto or "").strip().lower()
    return any(k in t for k in _TIPOS_VALOR_FIXO)


def _tem_campo(d: dict, *chaves: str) -> bool:
    """True se ALGUM dos campos foi informado (não None) — para distinguir 'ausente' de 'False'."""
    return any(d.get(k) is not None for k in chaves)


class X6EntregaFantasma(Detector):
    """Detector X6 — entrega fantasma / atesto de fachada (fase de execução).

    `avaliar(contexto)` espera (pelo menos UM de `pagamentos` OU `atestos` — ESSENCIAL):
      contexto["processo"]: id do contrato/processo.
      contexto["pagamentos"] (list[dict]): {valor, data, tem_nf?: bool, tem_recebimento?: bool} — a tríade
          documental. `tem_nf`/`tem_recebimento` False ⇒ pagou sem NF / sem registro de recebimento (forte).
      contexto["atestos"] (list[dict]): {texto, data} — textos dos atestos/medições (SEI).
      contexto["medicoes"] (opcional, list): valores (ou dicts {valor,data}) das medições — cadência.
      contexto["fiscais"] (opcional, list): designações de fiscais (DO) — para aferir ROTAÇÃO.
      contexto["capacidade_fornecedor"] (opcional, dict): {funcionarios?, frota?} — cruza C2 (volume × estrutura).
      contexto["volume_contratado"] (opcional, número): quantidade/volume a executar (× capacidade).
      contexto["tipo_objeto"] (opcional): 'locacao'/'assinatura'... = valor fixo → exculpa cadência idêntica.
      contexto["documento_conflitante"] (opcional): texto que o atesto contradiz (evidência da rubrica contraditório).
      contexto["_rubrica_especificidade"] / contexto["_rubrica_verossimilhanca"] (opcional, teste): rubricas pré.
      contexto["gerar"] (opcional): callable LLM p/ as 2 rubricas. Ausente → componente subjetivo nao_avaliavel.

    Honesto: sem pagamentos E sem atestos → nao_avaliavel (campo ausente ≠ 0)."""

    id = "X6"
    nome = "Entrega fantasma / atesto de fachada"
    familia = "execucao"  # X6 — peso 0.8 (execução) na convergência §7.2

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        pagamentos = [p for p in (contexto.get("pagamentos") or []) if isinstance(p, dict)]
        atestos = [a for a in (contexto.get("atestos") or []) if isinstance(a, dict)]

        # HONESTIDADE: sem NFs/atestos/pagamentos não há o que avaliar (campo ausente ≠ 0).
        if not pagamentos and not atestos:
            res.motivo_refutacao = (
                "nao_avaliavel: sem pagamentos e sem atestos no contexto — sem a tríade documental nem os textos "
                "de atesto não há como aferir entrega fantasma (campo ausente ≠ 0)")
            res.valores = {"n_pagamentos": 0, "n_atestos": 0}
            return res

        medicoes = list(contexto.get("medicoes") or [])
        fiscais = list(contexto.get("fiscais") or [])
        capacidade = contexto.get("capacidade_fornecedor") or {}
        volume = contexto.get("volume_contratado")
        tipo_objeto = contexto.get("tipo_objeto")
        valor_fixo = _is_valor_fixo(tipo_objeto)

        valores: dict = {
            "n_pagamentos": len(pagamentos),
            "n_atestos": len(atestos),
            "n_medicoes": len(medicoes),
            "tipo_objeto": tipo_objeto,
            "valor_fixo_mensal": valor_fixo,
        }

        score = 0.0
        razoes: list[str] = []

        # ── REGRA 1 (CÓDIGO): tríade documental NF × recebimento × pagamento INCOMPLETA → forte ──
        valores["triade_avaliavel"] = any(_tem_campo(p, "tem_nf", "tem_recebimento") for p in pagamentos)
        pagos_sem_nf = [p for p in pagamentos if p.get("tem_nf") is False]
        pagos_sem_receb = [p for p in pagamentos if p.get("tem_recebimento") is False]
        valores["pagamentos_sem_nf"] = len(pagos_sem_nf)
        valores["pagamentos_sem_recebimento"] = len(pagos_sem_receb)
        if pagos_sem_nf or pagos_sem_receb:
            score = max(score, ancora("forte"))
            razoes.append(
                f"tríade documental INCOMPLETA: {len(pagos_sem_nf)} pagamento(s) sem NF, "
                f"{len(pagos_sem_receb)} sem registro de recebimento (pagou-se sem comprovante de entrega)")
            for p in (pagos_sem_nf + pagos_sem_receb)[:6]:
                res.add_evidencia(
                    fonte="tríade documental (pagamento × NF × recebimento)",
                    trecho=(f"pagamento R$ {float(p.get('valor') or 0):,.2f} data={p.get('data') or '?'} "
                            f"tem_nf={p.get('tem_nf')} tem_recebimento={p.get('tem_recebimento')}"))

        # ── REGRA 2 (CÓDIGO): volume × CAPACIDADE do fornecedor (cruza C2) → forte ──
        funcionarios = capacidade.get("funcionarios")
        frota = capacidade.get("frota")
        if volume is not None and (funcionarios is not None or frota is not None):
            try:
                vol = float(volume)
            except (TypeError, ValueError):
                vol = None
            sem_estrutura = (
                (funcionarios is not None and float(funcionarios) <= 0)
                or (frota is not None and float(frota) <= 0)
            )
            valores["volume_contratado"] = volume
            valores["capacidade_funcionarios"] = funcionarios
            valores["capacidade_frota"] = frota
            if vol is not None and vol > 0 and sem_estrutura:
                score = max(score, ancora("forte"))
                razoes.append(
                    f"volume contratado ({volume}) incompatível com a CAPACIDADE do fornecedor "
                    f"(funcionarios={funcionarios}, frota={frota}) — sem estrutura para executar (cruza C2)")
                res.add_evidencia(
                    fonte="capacidade do fornecedor × volume (cruza C2)",
                    trecho=f"volume={volume} funcionarios={funcionarios} frota={frota}")

        # ── REGRA 3 (CÓDIGO): cadência — valores IDÊNTICOS repetidos → indício (rebaixado se valor fixo) ──
        valores_medicao = []
        for m in medicoes:
            if isinstance(m, dict):
                v = m.get("valor")
            else:
                v = m
            if v is not None:
                try:
                    valores_medicao.append(round(float(v), 2))
                except (TypeError, ValueError):
                    continue
        medicoes_identicas = len(valores_medicao) >= 3 and len(set(valores_medicao)) == 1
        valores["medicoes_identicas"] = medicoes_identicas
        if medicoes_identicas:
            if valor_fixo:
                razoes.append(
                    "medições idênticas, MAS objeto de valor fixo mensal (locação/assinatura) — cadência idêntica "
                    "é legítima (exculpatória do spec); não pontua")
            else:
                score = max(score, ancora("fraco"))
                razoes.append(
                    f"cadência suspeita: {len(valores_medicao)} medições com valor IDÊNTICO repetido "
                    f"(R$ {valores_medicao[0]:,.2f}) sem natureza de valor fixo")

        # ── REGRA 4 (CÓDIGO): baixa ROTAÇÃO de fiscal → AGRAVA (+0.10) ──
        if fiscais:
            distintos = {str(f).strip().lower() for f in fiscais if f}
            valores["n_designacoes_fiscal"] = len(fiscais)
            valores["n_fiscais_distintos"] = len(distintos)
            baixa_rotacao = len(fiscais) >= 3 and len(distintos) == 1
            valores["baixa_rotacao_fiscal"] = baixa_rotacao
            if baixa_rotacao and score > 0:
                score = min(1.0, score + 0.10)
                razoes.append(
                    f"baixa ROTAÇÃO de fiscal: {len(fiscais)} designações sempre o mesmo fiscal "
                    "(captura/cumplicidade potencial) — agrava")

        # ── PARTE SUBJETIVA (LLM-opcional): rubrica (1) especificidade dos atestos ──
        espec = self._avaliar_especificidade(contexto, atestos)
        valores["especificidade_atesto"] = espec["status"]
        if espec["status"] == "contraditorio":
            score = max(score, ancora("forte"))
            razoes.append("rubrica: atesto CONTRADITÓRIO — atesta o que outro documento NEGA")
            trecho = espec.get("trecho") or ""
            res.add_evidencia(
                fonte="atesto × documento conflitante",
                trecho=(f"atesto contradiz documento conflitante: {trecho[:160]}"
                        if trecho else "atesto contradiz documento conflitante (rubrica contraditorio)"))
        elif espec["status"] == "generico":
            # atesto SÓ genérico (má prática, não prova): medio (0.6) e NÃO sobe sozinho
            if score < ancora("medio"):
                score = ancora("medio")
            razoes.append(
                "rubrica: atesto GENÉRICO ('serviços prestados a contento') — má prática generalizada, não prova de "
                "fraude: medio (0.6), só sobe com contradição documental ou tríade incompleta")

        # ── PARTE SUBJETIVA (LLM-opcional): rubrica (2) verossimilhança física → dispara DILIGÊNCIA ──
        veross = self._avaliar_verossimilhanca(contexto, atestos)
        valores["verossimilhanca_fisica"] = veross["status"]

        # ── ROTEIRO DE DILIGÊNCIA: produto final p/ contratos de maior score (ou verificáveis em campo) ──
        recomenda_diligencia = score >= ancora("medio") or veross["status"] == "verificavel_em_campo"
        if recomenda_diligencia:
            roteiro = self._gerar_roteiro_diligencia(contexto, valores, razoes)
            valores["roteiro_diligencia"] = roteiro
            valores["diligencia_recomendada"] = True

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = "; ".join(razoes) or (
                "tríade documental completa, capacidade compatível, cadência sem anomalia — sem indício de entrega fantasma")
            res.valores = valores
            res.explicacao_inocente = (
                "documentação de entrega completa (NF + recebimento), fornecedor com estrutura compatível e medições "
                "legítimas (objeto de valor fixo) — execução regular; presunção de legitimidade")
            return res

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = (
            "FALSO POSITIVO a descartar (spec X6): serviços de valor fixo mensal (locação/assinatura) têm medições "
            "IDÊNTICAS legitimamente; atesto genérico é má prática generalizada, não prova de fraude. Este indício "
            "CULMINA em DILIGÊNCIA FÍSICA — a IA prepara o roteiro, a confirmação exige a visita de campo.")
        return res

    # ───────────────────────────── Rubrica (1): especificidade do atesto ─────────────────────────────
    def _rubrica_especificidade(self, resposta: dict | None) -> dict:
        """Atalho de teste: avalia uma resposta de rubrica já-classificada (sem rede)."""
        nivel, _score, motivo = avaliar_rubrica(resposta, _RUBRICA_ESPECIFICIDADE)
        if nivel is None or not isinstance(resposta, dict):
            return {"status": "nao_avaliavel", "motivo": motivo, "trecho": ""}
        classe = (resposta.get("nivel") or resposta.get("classificacao") or "").strip().lower()
        return {"status": classe, "motivo": motivo, "trecho": (resposta.get("trecho") or resposta.get("citacao") or "")}

    def _avaliar_especificidade(self, contexto: dict, atestos: list[dict]) -> dict:
        """Rubrica fechada (1). Atalho de teste `_rubrica_especificidade` no contexto; senão LLM via `gerar`;
        sem nenhum → fallback heurístico leve (termos genéricos) ou nao_avaliavel honesto."""
        pre = contexto.get("_rubrica_especificidade")
        if pre is not None:
            return self._rubrica_especificidade(pre)

        gerar = contexto.get("gerar")
        if gerar is None:
            # fallback heurístico SEM LLM: se há documento_conflitante, não inventamos contradição (precisa juízo);
            # se o texto é só termo genérico, sinaliza 'generico' (má prática objetivável por palavras-chave).
            textos = " ".join(str(a.get("texto") or "").lower() for a in atestos)
            if textos and any(t in textos for t in _TERMOS_GENERICOS):
                return {"status": "generico", "motivo": "fallback heurístico: termos genéricos no atesto (sem LLM)", "trecho": ""}
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — especificidade do atesto não auditada (honesto)", "trecho": ""}

        texto = "\n".join(str(a.get("texto") or "")[:300] for a in atestos[:5])
        conflito = str(contexto.get("documento_conflitante") or "")[:500]
        sistema = (
            "Você é auditor de controle externo avaliando ATESTO DE EXECUÇÃO. Classifique a ESPECIFICIDADE do "
            "conteúdo do atesto conforme a rubrica fechada. Responda SOMENTE com JSON: "
            '{"nivel":"especifico|generico|contraditorio","trecho":"<citação literal do atesto>"}. '
            "'especifico' = traz quantidades/locais/datas verificáveis; 'generico' = 'serviços prestados a contento' "
            "sem dados; 'contraditorio' = atesta o que o DOCUMENTO CONFLITANTE nega. Sem trecho, não classifique.")
        prompt = (f"ATESTO(S):\n{texto}\n\nDOCUMENTO CONFLITANTE (se houver):\n{conflito or '(nenhum)'}\n\n"
                  "Classifique a especificidade.")
        try:
            raw = gerar(prompt, sistema)
        except Exception as e:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(e)[:50]})", "trecho": ""}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        return self._rubrica_especificidade(dados)

    # ───────────────────────────── Rubrica (2): verossimilhança física ─────────────────────────────
    def _rubrica_verossimilhanca(self, resposta: dict | None) -> dict:
        """Atalho de teste: avalia uma resposta de rubrica já-classificada (sem rede)."""
        nivel, _score, motivo = avaliar_rubrica(resposta, _RUBRICA_VEROSSIMILHANCA)
        if nivel is None or not isinstance(resposta, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        classe = (resposta.get("nivel") or resposta.get("classificacao") or "").strip().lower()
        return {"status": classe, "motivo": motivo}

    def _avaliar_verossimilhanca(self, contexto: dict, atestos: list[dict]) -> dict:
        """Rubrica fechada (2). Atalho de teste `_rubrica_verossimilhanca`; senão LLM via `gerar`; sem nenhum →
        nao_avaliavel honesto (não inventa o juízo de verificabilidade)."""
        pre = contexto.get("_rubrica_verossimilhanca")
        if pre is not None:
            return self._rubrica_verossimilhanca(pre)
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — verossimilhança física não auditada (honesto)"}
        objeto = str(contexto.get("tipo_objeto") or "")
        texto = "\n".join(str(a.get("texto") or "")[:200] for a in atestos[:3])
        sistema = (
            "Você é auditor de controle externo. Dado o OBJETO e o atesto, classifique a VEROSSIMILHANÇA FÍSICA da "
            "execução conforme a rubrica fechada. Responda SOMENTE com JSON: "
            '{"nivel":"verificavel_em_campo|inverificavel","trecho":"<citação literal>"}. '
            "'verificavel_em_campo' = há bem/serviço material conferível in loco (recomenda diligência); "
            "'inverificavel' = objeto imaterial/já consumido. Sem trecho, não classifique.")
        prompt = f"OBJETO: {objeto}\nATESTO(S):\n{texto}\n\nClassifique a verossimilhança física."
        try:
            raw = gerar(prompt, sistema)
        except Exception as e:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(e)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        return self._rubrica_verossimilhanca(dados)

    # ───────────────────────────── PRODUTO FINAL: roteiro de diligência física ─────────────────────────────
    def _gerar_roteiro_diligencia(self, contexto: dict, valores: dict, razoes: list[str]) -> list[str]:
        """Monta a LISTA DE PONTOS A VERIFICAR em campo (local, bem, quantidade). A IA PREPARA o roteiro; a
        confirmação exige a visita física. Determinístico (sem rede) — ancorado nos indícios que acionaram."""
        tipo_objeto = contexto.get("tipo_objeto") or "objeto do contrato"
        volume = contexto.get("volume_contratado")
        roteiro: list[str] = [
            f"Identificar fisicamente o objeto ('{tipo_objeto}') no local de execução declarado nos atestos.",
            "Fotografar com GPS/data o bem entregue ou o serviço executado (estado, etiqueta patrimonial, local).",
        ]
        if volume is not None:
            roteiro.append(
                f"Conferir a QUANTIDADE entregue contra o volume contratado ({volume}) — contar/medir in loco.")
        else:
            roteiro.append("Conferir a QUANTIDADE entregue contra o que os atestos/medições afirmam (contar/medir).")
        if valores.get("pagamentos_sem_nf") or valores.get("pagamentos_sem_recebimento"):
            roteiro.append(
                "Exigir as NOTAS FISCAIS e os registros de RECEBIMENTO ausentes (portaria, almoxarifado, canhoto).")
        if valores.get("medicoes_identicas") and not valores.get("valor_fixo_mensal"):
            roteiro.append(
                "Verificar se as medições de valor idêntico correspondem a entregas REAIS e distintas (não cópia).")
        capacidade = contexto.get("capacidade_fornecedor") or {}
        if capacidade.get("funcionarios") is not None or capacidade.get("frota") is not None:
            roteiro.append(
                "Checar na portaria/almoxarifado o efetivo e a frota do fornecedor compatíveis com o volume entregue.")
        if valores.get("baixa_rotacao_fiscal"):
            roteiro.append(
                "Entrevistar/rotacionar o fiscal designado; cruzar suas atestações com evidências independentes de campo.")
        roteiro.append("Colher declaração do beneficiário final do serviço/bem sobre o efetivo recebimento.")
        return roteiro
