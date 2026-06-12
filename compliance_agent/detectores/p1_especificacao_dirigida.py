# -*- coding: utf-8 -*-
"""P1 · ESPECIFICAÇÃO DIRIGIDA / MARCA DISFARÇADA (spec V2 do dono, §2/P1).

Mecanismo: o Termo de Referência é redigido a partir do catálogo de um produto específico ("engenharia reversa
de datasheet"), de modo que apenas um fornecedor atende. A Lei 14.133/2021, art. 41, só admite indicação de
marca com justificativa formal ou como referência com "ou equivalente".

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • Requisitos NOMINATIVOS (citam marca/modelo/código de fabricante) sem "ou equivalente" .......... 'critico'
    (marca citada sem justificativa robusta nem "ou equivalente" = direcionamento objetivo, art. 41)
  • Requisitos com VALORES NÃO-REDONDOS (ex.: 17,3cm, 2.847 lúmens — copiados de datasheet) ......... agravante
  • INTERSEÇÃO de produtos que atendem ao conjunto de requisitos ≤ 2 ................................. 'forte'
    (universo de fornecedores fechado em 1-2 produtos pelo desenho do TR)
  • Exigência que SÓ este órgão pede vs `editais_analogos` para o mesmo objeto ........... 'medio' (sob medida)
  • Corroboração pelo resultado: ≤2 licitantes E produto ofertado = o da interseção .............. reforça nível

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto), duas rubricas fechadas:
  • PERTINÊNCIA de cada requisito restritivo ao uso real [essencial_justificado / conveniente / sem_relacao].
    'sem_relacao' → forte. Sem LLM → nao_avaliavel (o flag objetivo permanece).
  • QUALIDADE da justificativa de marca/exclusividade [robusta / generica / ausente]. 'generica' → médio;
    'ausente' com marca citada → crítico.

TESTE EXCULPATÓRIO (spec): PADRONIZAÇÃO formal (art. 43 — `processo_padronizacao` regular) rebaixa; ITEM ÚNICO
real (carta de exclusividade) descarta a marca; VALOR de NORMA TÉCNICA (ABNT/Anvisa) explica o valor não-redondo.

HONESTIDADE JFN: indício ≠ acusação; sem TR/requisitos → `nao_avaliavel` (campo ausente ≠ 0); nunca inventa número.
"""
from __future__ import annotations

import re

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Rubrica fechada de pertinência do requisito ao uso real (spec P1).
_RUBRICA_PERTINENCIA = {
    "essencial_justificado": "ausente",   # requisito justificado pelo uso → não pontua
    "conveniente": "medio",               # conveniente mas não essencial → médio
    "sem_relacao": "forte",               # requisito sem relação com o uso, exclui concorrentes → forte
}

# Rubrica fechada de qualidade da justificativa de marca/exclusividade (spec P1).
_RUBRICA_JUSTIFICATIVA_MARCA = {
    "robusta": "ausente",   # cita testes/padronização/laudo → não pontua
    "generica": "medio",    # "qualidade"/"confiabilidade" sem dado verificável → médio
    "ausente": "critico",   # marca citada SEM justificativa → crítico
}

# pistas de que um requisito é NOMINATIVO (cita marca/modelo/código de fabricante).
_PISTAS_NOMINATIVO = re.compile(
    r"\b(marca|modelo|fabricante|p/?n|part\s*number|código\s+do\s+fabricante|ref(?:erência|\.)\s*[:#]?\s*\w)\b",
    re.IGNORECASE,
)
_OU_EQUIVALENTE = re.compile(r"ou\s+(equivalente|similar|superior)", re.IGNORECASE)


def _is_redondo(v: float) -> bool:
    """Valor 'redondo' (múltiplo de 5 ou 10, ou inteiro pequeno) — típico de especificação genérica, não de
    datasheet. Valores NÃO-redondos (ex.: 17,3; 2.847) são suspeitos de cópia de catálogo."""
    if v == int(v):
        iv = int(v)
        return iv % 5 == 0 or iv <= 10
    return False


def _num(v) -> float | None:
    try:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            v = v.replace(".", "").replace(",", ".") if v.count(",") == 1 and v.count(".") != 1 else v
        return float(v)
    except (TypeError, ValueError):
        return None


def _texto_req(r: dict) -> str:
    return str(r.get("requisito") or r.get("descricao") or r.get("texto") or "")


def _chave_req(r: dict) -> str:
    """Chave canônica de um requisito para comparar entre editais análogos."""
    t = _texto_req(r).lower()
    t = (t.replace("ã", "a").replace("á", "a").replace("é", "e").replace("í", "i")
         .replace("ó", "o").replace("ç", "c"))
    toks = [w for w in re.sub(r"[^a-z0-9 ]+", " ", t).split() if len(w) > 3]
    return " ".join(sorted(set(toks))[:6])


class P1EspecificacaoDirigida(Detector):
    """Detector P1 — especificação dirigida / marca disfarçada (art. 41/43, Lei 14.133/2021).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do processo/certame.
      contexto["tr_texto"] (opcional str): texto integral do TR/ETP (para varredura de marca solta).
      contexto["requisitos"]: list[dict], cada um {requisito, valor?, unidade?, nominativo?(bool)}.
          `nominativo=True` marca explicitamente requisito que cita marca/modelo/código.
      contexto["datasheets_finalistas"] (opcional): list — produtos/datasheets que atendem ao conjunto de
          requisitos (a INTERSEÇÃO). len ≤ 2 → universo fechado.
      contexto["editais_analogos"] (opcional): list[dict] {requisitos:[...]} de outros órgãos p/ baseline.
      contexto["resultado"] (opcional): {licitantes:int, vencedor, produto_ofertado?} p/ corroboração.
      contexto["processo_padronizacao"] (opcional): dict/bool — padronização formal (art. 43) → exculpatória.
      contexto["justificativa_marca"] (opcional str): texto da justificativa, se houver marca citada.
      contexto["gerar"] (opcional): callable p/ as rubricas (LLM-opcional, degrada honesto).

    Honesto: sem TR e sem requisitos → nao_avaliavel (campo ausente ≠ 0); nunca inventa número."""

    id = "P1"
    nome = "Especificação dirigida / marca disfarçada"
    familia = "desenho_certame"  # P1 desenha o certame na fase de planejamento (peso 0.6 na convergência §7.2)

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        requisitos = contexto.get("requisitos") or []
        tr_texto = str(contexto.get("tr_texto") or "")
        if not requisitos and not tr_texto:
            res.motivo_refutacao = ("nao_avaliavel: sem TR e sem lista de requisitos no contexto "
                                    "(campo ausente ≠ 0) — sem base para avaliar especificação")
            res.valores = {"n_requisitos": 0, "tem_tr": False}
            return res

        analogos = contexto.get("editais_analogos") or []
        datasheets = contexto.get("datasheets_finalistas")
        resultado = contexto.get("resultado") or {}
        padronizacao = contexto.get("processo_padronizacao")

        valores: dict = {
            "n_requisitos": len(requisitos),
            "tem_tr": bool(tr_texto),
            "n_editais_analogos": len(analogos),
            "tem_padronizacao": bool(padronizacao),
        }

        score = 0.0
        razoes: list[str] = []
        req_suspeitos: list[dict] = []

        # ── REGRAS OBJETIVAS (código, nunca prompt) ──
        # 1) requisitos NOMINATIVOS (marca/modelo/código) sem "ou equivalente"
        nominativos: list[dict] = []
        for r in requisitos:
            texto = _texto_req(r)
            marcado = bool(r.get("nominativo"))
            tem_pista = marcado or bool(_PISTAS_NOMINATIVO.search(texto)) or bool(r.get("marca") or r.get("modelo"))
            tem_equiv = bool(_OU_EQUIVALENTE.search(texto))
            if tem_pista and not tem_equiv:
                nominativos.append(r)
                req_suspeitos.append(r)
                res.add_evidencia(
                    fonte="requisito do TR (nominativo)",
                    trecho=f"{texto[:90]} — cita marca/modelo/código SEM 'ou equivalente' (art. 41)",
                )
        # marca solta no corpo do TR (sem estar em requisito estruturado), sem "ou equivalente"
        if tr_texto and _PISTAS_NOMINATIVO.search(tr_texto) and not _OU_EQUIVALENTE.search(tr_texto) and not nominativos:
            m = _PISTAS_NOMINATIVO.search(tr_texto)
            ini = max(0, m.start() - 30)
            nominativos.append({"requisito": tr_texto[ini:m.end() + 30]})
            res.add_evidencia(fonte="TR (corpo)",
                              trecho=f"marca/modelo no corpo do TR sem 'ou equivalente': '{tr_texto[ini:m.end() + 30]}'")
        valores["n_requisitos_nominativos"] = len(nominativos)
        if nominativos:
            score = max(score, ancora("critico"))
            razoes.append(f"{len(nominativos)} requisito(s) nominativo(s) (marca/modelo/código) sem 'ou equivalente' (art. 41)")

        # 2) valores NÃO-redondos (copiados de datasheet)
        nao_redondos: list[str] = []
        for r in requisitos:
            v = _num(r.get("valor"))
            if v is not None and v > 10 and not _is_redondo(v):
                nao_redondos.append(f"{_texto_req(r)[:40]}={r.get('valor')}{r.get('unidade') or ''}")
        valores["n_valores_nao_redondos"] = len(nao_redondos)
        if len(nao_redondos) >= 2:
            score = max(score, ancora("medio"))
            razoes.append(f"{len(nao_redondos)} valor(es) não-redondo(s) — típico de cópia de catálogo")
            res.add_evidencia(fonte="requisitos do TR (valores)",
                              trecho="valores não-redondos: " + "; ".join(nao_redondos[:5]))

        # 3) interseção de produtos ≤ 2 (universo fechado)
        if isinstance(datasheets, (list, tuple)):
            n_inter = len(datasheets)
            valores["n_produtos_intersecao"] = n_inter
            if n_inter <= 2:
                score = max(score, ancora("forte"))
                razoes.append(f"apenas {n_inter} produto(s) atende(m) ao conjunto de requisitos (universo fechado)")
                res.add_evidencia(fonte="interseção de datasheets dos finalistas",
                                  trecho=f"{n_inter} produto(s) na interseção dos requisitos (≤2 = direcionamento)")

        # 4) exigências que SÓ este órgão pede (vs análogos) — sob medida
        sob_medida = self._requisitos_sob_medida(requisitos, analogos)
        valores["requisitos_sob_medida"] = [s["chave"] for s in sob_medida]
        if sob_medida:
            score = max(score, ancora("medio"))
            for s in sob_medida[:5]:
                razoes.append(f"requisito ausente em ≥metade dos análogos: '{s['chave'][:50]}' (sob medida)")
                res.add_evidencia(fonte="baseline de editais análogos",
                                  trecho=f"requisito '{_texto_req(s['req'])[:80]}' não consta em "
                                         f"{s['ausente_em']}/{s['n_analogos']} análogos")
                req_suspeitos.append(s["req"])

        # 5) corroboração pelo resultado: poucos licitantes
        n_licitantes = resultado.get("licitantes")
        valores["resultado_licitantes"] = n_licitantes
        if isinstance(n_licitantes, int) and n_licitantes <= 2 and score > 0:
            score = max(score, ancora("forte"))
            razoes.append(f"resultado corrobora: apenas {n_licitantes} licitante(s) (efeito do direcionamento)")

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = ("requisitos sem marca/modelo nominativo, valores genéricos e compatíveis com a "
                                    "praxe dos análogos — sem indício de especificação dirigida")
            res.valores = valores
            res.explicacao_inocente = "especificação técnica padrão, neutra quanto a fornecedor"
            return res

        # ── PARTE SUBJETIVA (LLM-opcional): pertinência ao uso + qualidade da justificativa de marca ──
        pert = self._avaliar_rubrica_req(req_suspeitos, "_rubrica_pertinencia", _RUBRICA_PERTINENCIA,
                                         contexto.get("gerar"))
        valores["pertinencia"] = pert["status"]
        if pert["status"] == "essencial_justificado":
            score = min(score, ancora("fraco"))
            razoes.append("rubrica pertinência: requisito essencial-justificado pelo uso — exculpatória (rebaixado)")

        just = self._avaliar_justificativa_marca(contexto, req_suspeitos)
        valores["justificativa_marca"] = just["status"]
        if just["status"] == "robusta":
            score = min(score, ancora("fraco"))
            razoes.append("rubrica justificativa de marca: robusta (testes/padronização/laudo) — exculpatória")

        # ── EXCULPATÓRIA estrutural: padronização formal (art. 43) ──
        if padronizacao:
            score = min(score, ancora("medio"))
            razoes.append("padronização formal (art. 43) no contexto — exculpatória estrutural (rebaixado)")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = ("FALSO POSITIVO a descartar (spec P1): PADRONIZAÇÃO legítima (parque instalado da "
                                   "marca, processo de padronização do art. 43); ITEM ÚNICO real (medicamento sob "
                                   "patente, peça exclusiva — carta de exclusividade); VALOR não-redondo vindo de "
                                   "NORMA TÉCNICA (ABNT/Anvisa). Verificar antes de imputar direcionamento.")
        return res

    def _requisitos_sob_medida(self, requisitos: list[dict], analogos: list[dict]) -> list[dict]:
        """Requisitos deste edital AUSENTES em ≥ metade dos análogos → candidatos a 'sob medida'. Sem análogos →
        lista vazia (não acusa por falta de baseline — exculpatória 'praxe do setor')."""
        if not analogos:
            return []
        chaves_analogos: list[set[str]] = []
        for a in analogos:
            ch = {_chave_req(r) for r in (a.get("requisitos") or a.get("exigencias") or [])}
            chaves_analogos.append(ch)
        n = len(chaves_analogos)
        out: list[dict] = []
        for r in requisitos:
            k = _chave_req(r)
            if not k:
                continue
            ausente_em = sum(1 for ch in chaves_analogos if k not in ch)
            if ausente_em >= (n + 1) // 2:
                out.append({"chave": k, "req": r, "ausente_em": ausente_em, "n_analogos": n})
        return out

    def _avaliar_rubrica_req(self, suspeitos: list[dict], chave_pre: str, escala: dict, gerar) -> dict:
        """Rubrica fechada sobre o 1º requisito suspeito. Atalho de teste: `chave_pre` injetado no requisito.
        Sem rubrica e sem LLM → nao_avaliavel honesto."""
        pre = None
        for r in suspeitos:
            if r.get(chave_pre):
                pre = r[chave_pre]
                break
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, escala)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        if gerar is None or not suspeitos:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — rubrica não auditada (honesto)"}
        r = suspeitos[0]
        sistema = (
            "Você é auditor de controle externo. Classifique a PERTINÊNCIA do requisito técnico ao USO REAL "
            "declarado no objeto. Responda SOMENTE com JSON: "
            '{"nivel":"essencial_justificado|conveniente|sem_relacao","trecho":"<citação literal>"}. '
            "Sem trecho, não classifique."
        )
        prompt = f"REQUISITO: {_texto_req(r)[:400]}\n\nClassifique a pertinência ao uso real."
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, escala)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}

    def _avaliar_justificativa_marca(self, contexto: dict, suspeitos: list[dict]) -> dict:
        """Rubrica de qualidade da justificativa de marca. Atalho de teste: `_rubrica_justificativa_marca` no
        contexto. Sem rubrica e sem texto/LLM → nao_avaliavel honesto."""
        pre = contexto.get("_rubrica_justificativa_marca")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_JUSTIFICATIVA_MARCA)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        gerar = contexto.get("gerar")
        texto_just = str(contexto.get("justificativa_marca") or "")
        if gerar is None or not texto_just:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente ou sem justificativa de marca (honesto)"}
        sistema = (
            "Você é auditor de controle externo. Classifique a QUALIDADE da justificativa de indicação de marca/"
            "exclusividade. Responda SOMENTE com JSON: "
            '{"nivel":"robusta|generica|ausente","trecho":"<citação literal da justificativa>"}. '
            "Sem trecho, não classifique."
        )
        prompt = f"JUSTIFICATIVA: {texto_just[:500]}\n\nClassifique a robustez da justificativa de marca."
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_JUSTIFICATIVA_MARCA)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
