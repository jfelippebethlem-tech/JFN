# -*- coding: utf-8 -*-
"""C6 · VÍNCULO POLÍTICO-FINANCEIRO (doações eleitorais) — PERFIL DO CONTRATADO (spec V2 do dono, §5/C6).

Mecanismo (manual C6): como doação de PJ é VEDADA desde 2015, o financiamento aparece nas doações PESSOAIS dos
sócios. Padrão suspeito: sócios DOAM à campanha do gestor; a empresa recebe contratos no mandato seguinte. O
detector cruza o QSA do contratado (CPFs dos sócios) × doações declaradas ao TSE (divulgacandcontas), filtra os
beneficiários COM PODER sobre o órgão contratante e monta a linha do tempo doação → posse → contratos, nos 2
ciclos eleitorais anteriores ao contrato.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • sócio do QSA que DOOU a beneficiário COM PODER sobre o órgão, nos 2 ciclos anteriores ao contrato → indício.
  • cruzamento por CPF quando houver (TSE publica parcial); senão por nome normalizado + município (homonímia).
  • agregados: valor doado pelos sócios, valor contratado, razão retorno/doação, sequência temporal.

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): rubrica fechada do PODER DECISÓRIO real do beneficiário sobre a
contratação [decisor-direto (ordenador, secretário da pasta) / influencia-indireta (chefe do executivo sobre pasta
autônoma) / sem-poder-sobre-o-contrato]. SÓ os dois primeiros pontuam. Se `beneficiarios_com_poder` vier no
contexto, o código já sabe quem tem poder e dispensa a rubrica; senão, a rubrica LLM classifica (sem LLM → o
componente de poder fica nao_avaliavel e o detector não pontua aquele beneficiário). Evidência: cargo do
beneficiário × órgão contratante.

EXCULPATÓRIO CRÍTICO (cláusula do dono): doar é LÍCITO e contratar com o poder público também. O C6 NUNCA produz
achado SOZINHO — é MULTIPLICADOR DE PRIORIDADE quando combinado com sobrepreço (P3), direcionamento (P1/E1) ou
dispensa (P5). Sem irregularidade no certame (`irregularidade_no_certame` ausente/False), doação + contrato =
coincidência protegida por lei. Por isso o score é CONSERVADOR: no MÁXIMO 'medio' (0.6), marcado explicitamente
como multiplicador/contexto, NUNCA crítico isolado. Homonímia de doador: validar por CPF + município antes de
atribuir. REGISTRAR o resultado MESMO quando 0 (status 'descartado'): a ausência de vínculo também é informação
de dossiê.

HONESTIDADE JFN: sem QSA (CPFs dos sócios) OU sem doações → nao_avaliavel (campo ausente ≠ 0). CPF de sócio
mascarado (LGPD) — trabalha com o que vier, valida por município quando houver. Nunca inventa número.

Família "perfil" (peso 0.8, §7.2)."""
from __future__ import annotations

import re
import unicodedata

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Rubrica fechada do PODER DECISÓRIO do beneficiário sobre a contratação (spec C6). LLM-opcional; degrada honesto.
# Só 'decisor-direto' e 'influencia-indireta' pontuam; 'sem-poder' não. Score-teto do C6 é 'medio' (conservador):
# tanto poder direto quanto indireto mapeiam para 'medio' aqui — o C6 jamais ultrapassa 0.6 isolado.
_RUBRICA_PODER = {
    "decisor-direto": "medio",        # ordenador de despesa / secretário da pasta contratante
    "influencia-indireta": "medio",   # chefe do executivo sobre pasta autônoma (pondera, mas continua só multiplicador)
    "sem-poder-sobre-o-contrato": "ausente",  # beneficiário sem ingerência → não pontua
}

# Ciclos eleitorais: doações relevantes só nos 2 ciclos (8 anos) anteriores ao contrato (spec C6).
_ANOS_2_CICLOS = 8

# Agregado mínimo de doação dos sócios para virar indício 'medio' (spec C6: ≥ R$ 10 mil → 0.6).
_LIMIAR_DOACAO_MEDIO = 10_000.0


def _norm_nome(s: str | None) -> str:
    """Normaliza nome para casamento tolerante (homonímia mitigada DEPOIS por CPF/município): sem acento, caixa
    baixa, espaços colapsados."""
    if not s:
        return ""
    t = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def _so_digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _cpf_match(a: str, b: str) -> bool:
    """Casa CPFs tolerando MASCARAMENTO LGPD (TSE publica parcial: ***123456**). Compara os dígitos visíveis
    comuns; exige pelo menos 6 dígitos coincidentes contíguos para não casar lixo."""
    da, db = _so_digitos(a), _so_digitos(b)
    if not da or not db:
        return False
    if da == db and len(da) >= 6:
        return True
    # mascarado dos dois lados: o TSE expõe o miolo (6 dígitos centrais do CPF de 11)
    if len(da) >= 6 and len(db) >= 6 and (da in db or db in da):
        return True
    return False


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class C6VinculoPolitico(Detector):
    """Detector C6 — vínculo político-financeiro (doações eleitorais dos sócios do contratado).

    `avaliar(contexto)` espera (CONTEXTO já extraído — camada 1):
      contexto["processo"] (ou ["id"]/["cnpj"]): id do contrato/fornecedor investigado.
      contexto["qsa"]: list[dict] {cpf?, nome, municipio?} — SÓCIOS do contratado (ESSENCIAL; ausente → nao_avaliavel).
      contexto["doacoes"]: list[dict] {doador_cpf?, doador_nome, beneficiario, cargo_beneficiario?, valor,
          ano_eleicao, municipio?} — doações declaradas ao TSE (ESSENCIAL; ausente → nao_avaliavel).
      contexto["orgao_contratante"] (opcional): str — órgão que contratou (compõe a evidência cargo × órgão).
      contexto["beneficiarios_com_poder"] (opcional): list de nomes/cargos com poder sobre o órgão. Se presente, o
          código já filtra por poder (dispensa a rubrica). Se ausente, a rubrica LLM classifica o poder.
      contexto["data_contrato"] (opcional): str/int ano — para a janela dos 2 ciclos eleitorais anteriores.
      contexto["irregularidade_no_certame"] (opcional bool): se True, o C6 deixa de ser SÓ multiplicador (há
          irregularidade no certame a combinar); ainda assim o score permanece conservador (máx 'medio').
      contexto["valor_contratado"] (opcional): float — agregado contratado, p/ a razão retorno/doação.
      contexto["_rubrica_poder"] (opcional, teste) / contexto["gerar"] (opcional): rubrica LLM do poder decisório.

    Score CONSERVADOR: no MÁXIMO 'medio' (0.6); é MULTIPLICADOR DE PRIORIDADE, nunca achado autônomo. Sempre
    REGISTRA resultado (mesmo 0: status 'descartado', "ausência de vínculo = informação de dossiê").
    Honesto: sem QSA OU sem doações → nao_avaliavel (campo ausente ≠ 0)."""

    id = "C6"
    nome = "Vínculo político-financeiro (doações eleitorais)"
    familia = "perfil"  # C1–C6 — peso 0.8 (perfil) na convergência §7.2

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or contexto.get("cnpj") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        qsa = [s for s in (contexto.get("qsa") or []) if isinstance(s, dict)]
        doacoes = [d for d in (contexto.get("doacoes") or []) if isinstance(d, dict)]

        # ── HONESTIDADE: sem QSA OU sem doações → nao_avaliavel (campo ausente ≠ 0) ──
        if not qsa or not doacoes:
            falta = []
            if not qsa:
                falta.append("qsa (CPFs/nomes dos sócios)")
            if not doacoes:
                falta.append("doacoes (TSE divulgacandcontas)")
            res.motivo_refutacao = (
                "nao_avaliavel: faltam " + " e ".join(falta) + " — sem o cruzamento sócio×doador não há juízo "
                "possível (campo ausente ≠ 0); CPF de sócio pode vir mascarado (LGPD)")
            res.valores = {"tem_qsa": bool(qsa), "tem_doacoes": bool(doacoes),
                           "papel": "multiplicador_prioridade"}
            return res

        orgao = contexto.get("orgao_contratante")
        ano_contrato = self._ano(contexto.get("data_contrato"))
        irregularidade = bool(contexto.get("irregularidade_no_certame"))
        valor_contratado = _num(contexto.get("valor_contratado"))

        # beneficiários com poder fornecidos pelo contexto (mapa de cargos) — normalizados para casamento.
        bp_set = {_norm_nome(b) for b in (contexto.get("beneficiarios_com_poder") or []) if str(b).strip()}
        tem_mapa_poder = bool(bp_set)

        # ── CÓDIGO: cruza cada sócio do QSA × cada doação (CPF → nome+município) ──
        pares: list[dict] = []   # cada vínculo sócio→doação a beneficiário
        for socio in qsa:
            s_cpf = socio.get("cpf")
            s_nome = _norm_nome(socio.get("nome"))
            s_mun = _norm_nome(socio.get("municipio"))
            for doa in doacoes:
                if not self._mesmo_doador(s_cpf, s_nome, s_mun, doa):
                    continue
                ano_doa = self._ano(doa.get("ano_eleicao"))
                # janela: doação nos 2 ciclos eleitorais anteriores ao contrato (quando há data de contrato).
                if ano_contrato and ano_doa and not (0 <= (ano_contrato - ano_doa) <= _ANOS_2_CICLOS):
                    continue
                pares.append({
                    "socio_nome": socio.get("nome"),
                    "socio_cpf": socio.get("cpf"),
                    "doador_nome": doa.get("doador_nome"),
                    "beneficiario": doa.get("beneficiario"),
                    "cargo_beneficiario": doa.get("cargo_beneficiario"),
                    "valor": _num(doa.get("valor")),
                    "ano_eleicao": ano_doa,
                    "municipio": doa.get("municipio") or socio.get("municipio"),
                    "casou_por": "cpf" if (s_cpf and self._mesmo_doador(s_cpf, "", "", doa) and
                                           _cpf_match(s_cpf, doa.get("doador_cpf"))) else "nome+municipio",
                })

        valores: dict = {
            "papel": "multiplicador_prioridade",
            "tem_qsa": True,
            "tem_doacoes": True,
            "n_socios": len(qsa),
            "n_doacoes": len(doacoes),
            "orgao_contratante": orgao,
            "ano_contrato": ano_contrato,
            "irregularidade_no_certame": irregularidade,
            "n_vinculos_brutos": len(pares),
        }

        # ── nenhum vínculo sócio↔doador: REGISTRA mesmo assim (ausência = informação de dossiê) ──
        if not pares:
            res.status = "descartado"
            res.score = 0.0
            res.valores = valores | {"valor_doado_agregado": 0.0, "beneficiarios_com_poder": [],
                                     "vinculos_com_poder": 0}
            res.motivo_refutacao = ("ausência de vínculo = informação de dossiê: nenhum sócio do QSA consta como "
                                    "doador (por CPF, ou nome+município) nas doações fornecidas — sem indício C6")
            res.explicacao_inocente = self._explicacao_inocente()
            return res

        # ── filtra pares cujo beneficiário tem PODER sobre o órgão (código se há mapa; senão rubrica LLM) ──
        if tem_mapa_poder:
            com_poder = [p for p in pares if self._tem_poder_por_mapa(p, bp_set)]
            fonte_poder = "mapa_de_cargos (beneficiarios_com_poder fornecido)"
            poder_avaliado = True
        else:
            sub = self._avaliar_poder(contexto)
            valores["rubrica_poder"] = sub["status"]
            if sub["status"] in ("decisor-direto", "influencia-indireta"):
                com_poder = list(pares)  # a rubrica afirmou poder do(s) beneficiário(s)
                fonte_poder = f"rubrica_LLM ({sub['status']})"
                poder_avaliado = True
            elif sub["status"] == "sem-poder-sobre-o-contrato":
                com_poder = []
                fonte_poder = "rubrica_LLM (sem-poder-sobre-o-contrato)"
                poder_avaliado = True
            else:  # nao_avaliavel — sem LLM e sem mapa: não dá para afirmar poder (honesto)
                com_poder = []
                fonte_poder = f"poder NÃO auditado ({sub.get('motivo', 'sem mapa nem LLM')})"
                poder_avaliado = False

        valor_doado = round(sum(p["valor"] for p in com_poder), 2)
        valores |= {
            "vinculos_com_poder": len(com_poder),
            "valor_doado_agregado": valor_doado,
            "valor_contratado": valor_contratado or None,
            "razao_retorno_doacao": round(valor_contratado / valor_doado, 2) if (valor_contratado and valor_doado) else None,
            "fonte_poder": fonte_poder,
            "poder_avaliado": poder_avaliado,
        }

        # ── nenhum beneficiário com poder: vínculo existe mas é coincidência protegida (não pontua) ──
        if not com_poder:
            res.status = "descartado"
            res.score = 0.0
            res.valores = valores
            if not poder_avaliado:
                res.motivo_refutacao = (
                    "vínculo sócio↔doador existe, mas o PODER do beneficiário sobre o órgão NÃO foi auditado (sem "
                    "mapa de cargos nem LLM) — sem afirmar poder, não pontua (honesto); registra o vínculo bruto")
            else:
                res.motivo_refutacao = (
                    "vínculo sócio↔doador existe, mas o beneficiário NÃO tem poder sobre o órgão contratante "
                    "(sem-poder-sobre-o-contrato) — doação + contrato = coincidência protegida por lei; não pontua")
            res.explicacao_inocente = self._explicacao_inocente()
            for p in pares[:4]:
                res.add_evidencia(
                    fonte="QSA × doações TSE (vínculo bruto, sem poder)",
                    trecho=(f"sócio {p['socio_nome']} doou R$ {p['valor']:.2f} a {p['beneficiario']} "
                            f"(cargo: {p.get('cargo_beneficiario') or 'n/d'}) — beneficiário sem poder sobre {orgao or 'o órgão'}"))
            return res

        # ── há vínculo COM PODER: indício C6 (CONSERVADOR, máx 'medio' = 0.6) ──
        score = 0.0
        razoes: list[str] = []
        if valor_doado >= _LIMIAR_DOACAO_MEDIO:
            score = ancora("medio")
            razoes.append(f"agregado doado pelos sócios a beneficiário(s) com poder = R$ {valor_doado:,.2f} "
                          f"(≥ R$ {_LIMIAR_DOACAO_MEDIO:,.0f}) — indício 'medio'")
        else:
            score = ancora("fraco")
            razoes.append(f"agregado doado a beneficiário(s) com poder = R$ {valor_doado:,.2f} "
                          f"(< R$ {_LIMIAR_DOACAO_MEDIO:,.0f}) — indício 'fraco' (só vale em convergência)")

        # sequência temporal e razão retorno/doação são MODULADORES de razão — registrados, mas o teto é 0.6.
        if valor_contratado and valor_doado and (valor_contratado / valor_doado) >= 100:
            razoes.append(f"razão retorno/doação = {valor_contratado / valor_doado:.0f}× (doação como 'investimento') "
                          "— modulador de prioridade (não eleva o teto conservador 0.6)")

        # TETO CONSERVADOR (cláusula do dono): C6 jamais ultrapassa 'medio' (0.6) isolado.
        score = min(score, ancora("medio"))

        for p in com_poder[:6]:
            res.add_evidencia(
                fonte=f"QSA × doações TSE (casou por {p['casou_por']})",
                trecho=(f"sócio {p['socio_nome']} (CPF {p.get('socio_cpf') or 'mascarado/LGPD'}, mun "
                        f"{p.get('municipio') or 'n/d'}) doou R$ {p['valor']:.2f} em {p.get('ano_eleicao') or 'n/d'} "
                        f"a {p['beneficiario']} — cargo {p.get('cargo_beneficiario') or 'n/d'} × órgão "
                        f"{orgao or 'contratante'} (beneficiário COM poder)"))

        if irregularidade:
            razoes.append("HÁ irregularidade no certame (P1/E1/P3/P5) — o C6 deixa de ser só multiplicador e passa "
                          "a AGRAVAR o achado convergente (ainda conservador: teto 'medio' isolado)")
        else:
            razoes.append("SEM irregularidade no certame: C6 é APENAS multiplicador de prioridade — doação + contrato "
                          "lícitos = coincidência protegida por lei; NÃO é achado autônomo")

        valores |= {
            "score_ancora": "medio" if score >= ancora("medio") else "fraco",
            "teto_conservador": ancora("medio"),
            "achado_autonomo": False,
        }
        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = self._explicacao_inocente()
        return res

    # ───────────────────────── helpers ─────────────────────────
    def _mesmo_doador(self, socio_cpf, socio_nome_norm: str, socio_mun_norm: str, doa: dict) -> bool:
        """Casa um sócio com uma doação. PRIORIDADE ao CPF (TSE publica parcial). Sem CPF nos dois lados, casa por
        nome normalizado + MUNICÍPIO (mitiga homonímia — nome igual nunca basta; sem município comprovado, não casa)."""
        d_cpf = doa.get("doador_cpf")
        if socio_cpf and d_cpf and _cpf_match(socio_cpf, d_cpf):
            da, db = _so_digitos(socio_cpf), _so_digitos(d_cpf)
            if len(da) == 11 and len(db) == 11:
                return True   # igualdade plena de CPF basta
            # CPF MASCARADO casa por miolo (~6 dígitos): colisão esperada em milhões de
            # doações — exigir também o nome (detector juridicamente sensível)
            return bool(socio_nome_norm) and socio_nome_norm == _norm_nome(doa.get("doador_nome"))
        # fallback nome+município só quando CPF não está disponível para casar
        if socio_cpf and d_cpf:
            return False  # ambos têm CPF e não casaram → é outra pessoa (não cair no nome)
        d_nome = _norm_nome(doa.get("doador_nome"))
        if not socio_nome_norm or socio_nome_norm != d_nome:
            return False
        d_mun = _norm_nome(doa.get("municipio"))
        # nome igual exige município igual e informado dos dois lados (homonímia)
        return bool(socio_mun_norm) and bool(d_mun) and socio_mun_norm == d_mun

    def _tem_poder_por_mapa(self, par: dict, bp_set: set[str]) -> bool:
        """Beneficiário/cargo do par consta no mapa de cargos com poder (beneficiarios_com_poder)?"""
        alvo = {_norm_nome(par.get("beneficiario")), _norm_nome(par.get("cargo_beneficiario"))}
        alvo.discard("")
        return bool(alvo & bp_set)

    @staticmethod
    def _ano(v) -> int | None:
        """Extrai um ano (int) de str/int/data ('2018', 2018, '2018-09-01')."""
        if v is None:
            return None
        m = re.search(r"(19|20)\d{2}", str(v))
        return int(m.group(0)) if m else None

    def _explicacao_inocente(self) -> str:
        return ("FALSO POSITIVO a descartar (spec C6): doar é LÍCITO e contratar com o poder público também — o C6 "
                "NUNCA produz achado SOZINHO; é MULTIPLICADOR DE PRIORIDADE só quando combinado com sobrepreço (P3), "
                "direcionamento (P1/E1) ou dispensa (P5). Sem irregularidade no certame, doação + contrato = "
                "coincidência protegida por lei. Homonímia de doador é a maior fonte de falso positivo: nome igual "
                "nunca basta — validar por CPF (TSE publica parcial) + município. Score teto 'medio' (0.6) por construção.")

    def _avaliar_poder(self, contexto: dict) -> dict:
        """Rubrica fechada do PODER decisório do beneficiário sobre a contratação. Atalho de teste:
        `_rubrica_poder` injetado no contexto. Sem rubrica e sem LLM → nao_avaliavel honesto (não afirma poder)."""
        pre = contexto.get("_rubrica_poder")
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_PODER)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel",
                    "motivo": "LLM ausente e sem mapa de cargos — poder do beneficiário não auditado (honesto)"}
        orgao = contexto.get("orgao_contratante") or "o órgão contratante"
        benefs = "; ".join(
            f"{d.get('beneficiario')} (cargo: {d.get('cargo_beneficiario') or 'n/d'})"
            for d in (contexto.get("doacoes") or []) if isinstance(d, dict)
        )[:1000]
        sistema = (
            "Você é auditor de controle externo. Classifique o PODER DECISÓRIO REAL do beneficiário da doação sobre "
            "a contratação, conforme a rubrica fechada. Responda SOMENTE com JSON: "
            '{"nivel":"decisor-direto|influencia-indireta|sem-poder-sobre-o-contrato","trecho":"<citação literal do '
            'cargo × órgão>"}. Sem trecho, não classifique. decisor-direto = ordenador de despesa/secretário da pasta; '
            "influencia-indireta = chefe do executivo sobre pasta autônoma; sem-poder = beneficiário sem ingerência.")
        prompt = (f"Órgão contratante: {orgao}.\nBeneficiários das doações dos sócios: {benefs}\n\n"
                  "O beneficiário tinha poder decisório real (direto ou indireto) sobre essa contratação?")
        try:
            raw = gerar(prompt, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_PODER)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
