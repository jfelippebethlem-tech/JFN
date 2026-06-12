# -*- coding: utf-8 -*-
"""P2 · COTAÇÕES COMBINADAS (orçamentos de fachada) (spec V2 do dono, §2/P2).

Mecanismo: a pesquisa de preços que define o valor de referência é montada com cotações de empresas COORDENADAS
(mesmo grupo, mesmo contador, ou simplesmente solicitadas pelo futuro vencedor), inflando o teto do certame. A
IN SEGES 65/2021 manda priorizar painéis e contratações similares; pesquisa só com fornecedores já é desvio.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • VÍNCULO entre cotantes: sócio comum (QSA), endereço, telefone ou e-mail compartilhado entre cotantes ... 'forte'
      – um único vínculo de CONTADOR isolado (sem outro) ........................................ 'fraco' (exculpatória regional)
      – vínculo entre cotante e o VENCEDOR ......................................................... 'forte'
  • METADADOS PDF idênticos (Author/Producer/CreateDate iguais entre cotações distintas) ............. agravante
      – Author/CreateDate idênticos (não só Producer) .......................................... 'forte'
      – só Producer idêntico (template de ERP) ................................................. 'fraco' (exculpatória)
  • VENCEDOR ∈ cotantes (quem cotou venceu o próprio teto que ajudou a formar) ..................... 'forte'
  • CV (coef. de variação) dos valores muito baixo (< 0,05) entre cotações independentes .......... agravante
  • Cotações ≥ 25% acima da referência PNCP/painel ................................................ +0.10 (soma c/ P3)

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto), duas rubricas fechadas:
  • SIMILARIDADE visual/textual das cotações [independentes / formato_similar / praticamente_identicas].
    'praticamente_identicas' → forte. Sem LLM → nao_avaliavel (o vínculo objetivo permanece).
  • PLAUSIBILIDADE comercial do cotante (CNAE × item) [fornecedor_real / sem_historico / incompativel].
    'incompativel' → médio.

TESTE EXCULPATÓRIO (spec): MERCADO REGIONAL pequeno (contador comum ISOLADO = 0.3, não sobe sozinho); TEMPLATE
de ERP (Producer idêntico ≠ conluio — confirmar com CreateDate e conteúdo); COMMODITY com preço tabelado (CV
baixo natural — checar se o item tem preço regulado antes de pontuar).

HONESTIDADE JFN: indício ≠ acusação; sem cotações → `nao_avaliavel` (campo ausente ≠ 0); CPF de sócio mascarado;
nunca inventa número.
"""
from __future__ import annotations

import re

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# Rubrica fechada de similaridade das cotações (spec P2).
_RUBRICA_SIMILARIDADE = {
    "independentes": "ausente",
    "formato_similar": "medio",
    "praticamente_identicas": "forte",   # mesmo layout/frases/erros → forte
}

# Rubrica fechada de plausibilidade comercial do cotante (spec P2).
_RUBRICA_PLAUSIBILIDADE = {
    "fornecedor_real": "ausente",
    "sem_historico": "fraco",
    "incompativel": "medio",   # CNAE incompatível com o item → médio
}


def _norm_tel(t) -> str:
    return re.sub(r"\D+", "", str(t or ""))


def _norm_email(e) -> str:
    return str(e or "").strip().lower()


def _norm_end(e) -> str:
    s = str(e or "").lower()
    s = (s.replace("ã", "a").replace("á", "a").replace("é", "e").replace("í", "i")
         .replace("ó", "o").replace("ç", "c"))
    s = re.sub(r"\b(rua|av|avenida|r\.|al|alameda|trav|travessa|nº|n\.|numero|número|,|-)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _socios(qsa) -> set[str]:
    """Conjunto normalizado de identificadores de sócios (CPF mascarado ou nome) de um QSA."""
    out: set[str] = set()
    for s in (qsa or []):
        if isinstance(s, dict):
            ident = s.get("cpf") or s.get("documento") or s.get("nome") or s.get("nome_socio") or ""
        else:
            ident = s
        ident = str(ident or "").strip().lower()
        if ident:
            out.add(ident)
    return out


def _cv(valores: list[float]) -> float | None:
    """Coeficiente de variação (desvio padrão / média). None se < 2 valores ou média 0."""
    vs = [v for v in valores if isinstance(v, (int, float))]
    if len(vs) < 2:
        return None
    media = sum(vs) / len(vs)
    if media == 0:
        return None
    var = sum((v - media) ** 2 for v in vs) / len(vs)
    return (var ** 0.5) / media


def _total_cotacao(c: dict) -> float | None:
    """Valor total de uma cotação: soma dos itens, ou campo `valor`/`total` direto."""
    valores = c.get("valores")
    if isinstance(valores, (list, tuple)):
        nums = [float(v) for v in valores if isinstance(v, (int, float))]
        if nums:
            return sum(nums)
    for k in ("total", "valor_total", "valor"):
        v = c.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


class P2CotacoesCombinadas(Detector):
    """Detector P2 — cotações combinadas / orçamentos de fachada (IN SEGES 65/2021).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do processo.
      contexto["cotacoes"]: list[dict], cada uma {cnpj, razao?, data?, valores?(list)|total?, itens?, contato?
          {telefone,email,endereco}, metadados_pdf?{Author,Producer,CreateDate,ModDate}}.
      contexto["qsa_por_cnpj"] (opcional): {cnpj: [socios]} p/ cruzar sócios (CPF mascarado/nome).
      contexto["vencedor_cnpj"] (opcional): CNPJ do vencedor do certame (p/ checar vencedor ∈ cotantes / vínculo).
      contexto["ref_pncp"] (opcional float): valor de referência de painel/PNCP p/ o item (cotações ≥25% acima).
      contexto["item_preco_regulado"] (opcional bool): commodity/preço tabelado → exculpatória de CV baixo.
      contexto["gerar"] (opcional): callable p/ as rubricas (LLM-opcional, degrada honesto).

    Honesto: menos de 2 cotações → nao_avaliavel (campo ausente ≠ 0); nunca inventa número."""

    id = "P2"
    nome = "Cotações combinadas (orçamentos de fachada)"
    familia = "preco"  # P2 contamina o preço de referência (peso 0.8 na convergência §7.2)

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        cotacoes = [c for c in (contexto.get("cotacoes") or []) if isinstance(c, dict)]
        if len(cotacoes) < 2:
            res.motivo_refutacao = ("nao_avaliavel: menos de 2 cotações no contexto (campo ausente ≠ 0) — "
                                    "sem base para cruzar vínculos/similaridade")
            res.valores = {"n_cotacoes": len(cotacoes)}
            return res

        qsa_por_cnpj = contexto.get("qsa_por_cnpj") or {}
        vencedor = str(contexto.get("vencedor_cnpj") or "").strip()
        ref_pncp = contexto.get("ref_pncp")
        item_regulado = bool(contexto.get("item_preco_regulado"))

        valores: dict = {"n_cotacoes": len(cotacoes), "vencedor_cnpj": vencedor or None,
                         "item_preco_regulado": item_regulado}

        score = 0.0
        razoes: list[str] = []

        # ── REGRA OBJETIVA 1: vínculos entre cotantes (e com o vencedor) ──
        vinc = self._cruzar_vinculos(cotacoes, qsa_por_cnpj, vencedor)
        valores["vinculos"] = vinc["resumo"]
        for ev in vinc["evidencias"]:
            res.add_evidencia(fonte=ev["fonte"], trecho=ev["trecho"])
        # vínculo forte: sócio/endereço/telefone/email comum, OU qualquer vínculo com o vencedor
        if vinc["forte"]:
            score = max(score, ancora("forte"))
            razoes.append(vinc["motivo_forte"])
        elif vinc["so_contador"]:
            # contador comum ISOLADO = exculpatória regional → fraco, não sobe sozinho
            score = max(score, ancora("fraco"))
            razoes.append("apenas contador comum entre cotantes (vínculo isolado) — fraco (exculpatória regional)")

        # ── REGRA OBJETIVA 2: metadados PDF idênticos ──
        meta = self._cruzar_metadados(cotacoes)
        valores["metadados"] = meta["resumo"]
        if meta["evidencia"]:
            res.add_evidencia(fonte="metadados PDF das cotações", trecho=meta["evidencia"])
        if meta["author_ou_createdate_identicos"]:
            score = max(score, ancora("forte"))
            razoes.append("metadados PDF idênticos (Author/CreateDate) entre cotações distintas — mesma origem")
        elif meta["so_producer_identico"]:
            score = max(score, ancora("fraco"))
            razoes.append("só Producer idêntico (template de ERP) — fraco (exculpatória: confirmar com CreateDate)")

        # ── REGRA OBJETIVA 3: vencedor ∈ cotantes ──
        cnpjs = {str(c.get("cnpj") or "").strip() for c in cotacoes if c.get("cnpj")}
        if vencedor and vencedor in cnpjs:
            score = max(score, ancora("forte"))
            razoes.append("VENCEDOR está entre os cotantes (cotou o próprio teto que ajudou a formar)")
            res.add_evidencia(fonte="resultado × pesquisa de preços",
                              trecho=f"vencedor {vencedor} consta entre os cotantes da pesquisa de preços")
        valores["vencedor_e_cotante"] = bool(vencedor and vencedor in cnpjs)

        # ── REGRA OBJETIVA 4: CV dos valores muito baixo ──
        totais = [t for t in (_total_cotacao(c) for c in cotacoes) if t is not None]
        cv = _cv(totais)
        valores["cv_valores"] = round(cv, 4) if cv is not None else None
        if cv is not None and cv < 0.05 and not item_regulado:
            score = min(1.0, score + 0.10) if score > 0 else ancora("fraco")
            razoes.append(f"CV dos valores muito baixo ({cv:.3f} < 0,05) — cotações suspeitamente alinhadas")
            res.add_evidencia(fonte="valores das cotações",
                              trecho=f"coeficiente de variação = {cv:.4f} (< 0,05) entre {len(totais)} cotações")
        elif cv is not None and cv < 0.05 and item_regulado:
            razoes.append(f"CV baixo ({cv:.3f}) mas item de preço REGULADO — exculpatória (não pontua)")

        # ── REGRA OBJETIVA 5: cotações ≥ 25% acima da referência PNCP ──
        if isinstance(ref_pncp, (int, float)) and ref_pncp > 0 and totais:
            mediana = sorted(totais)[len(totais) // 2]
            sobre = mediana / ref_pncp - 1.0
            valores["sobre_ref_pncp_pct"] = round(sobre, 4)
            if sobre >= 0.25:
                score = min(1.0, score + 0.10) if score > 0 else ancora("medio")
                razoes.append(f"mediana das cotações {sobre:.0%} acima da referência PNCP (≥25% — somar com P3)")
                res.add_evidencia(fonte="cotações × referência PNCP",
                                  trecho=f"mediana cotações = {mediana:,.2f} vs ref PNCP {ref_pncp:,.2f} ({sobre:.0%} acima)")

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = ("cotantes sem vínculo societário/cadastral, metadados distintos, vencedor fora "
                                    "dos cotantes e valores dispersos — pesquisa de preços aparentemente independente")
            res.valores = valores
            res.explicacao_inocente = "pesquisa de preços com fornecedores independentes"
            return res

        # ── PARTE SUBJETIVA (LLM-opcional): similaridade + plausibilidade comercial ──
        sim = self._avaliar_rubrica(contexto, "_rubrica_similaridade", _RUBRICA_SIMILARIDADE,
                                    self._prompt_similaridade(cotacoes))
        valores["similaridade"] = sim["status"]
        if sim["status"] == "praticamente_identicas":
            score = max(score, ancora("forte"))
            razoes.append("rubrica similaridade: cotações praticamente idênticas (layout/frases/erros)")
        elif sim["status"] == "independentes":
            # LLM confirma independência visual → não rebaixa o vínculo objetivo, mas registra
            razoes.append("rubrica similaridade: cotações visualmente independentes (registra; vínculo objetivo permanece)")

        plaus = self._avaliar_rubrica(contexto, "_rubrica_plausibilidade", _RUBRICA_PLAUSIBILIDADE,
                                      "Classifique a plausibilidade comercial (CNAE × item) do cotante.")
        valores["plausibilidade"] = plaus["status"]
        if plaus["status"] == "incompativel":
            score = max(score, ancora("medio"))
            razoes.append("rubrica plausibilidade: cotante com CNAE incompatível com o item")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.motivo_refutacao = "; ".join(razoes)
        res.explicacao_inocente = ("FALSO POSITIVO a descartar (spec P2): MERCADO regional pequeno (3 fornecedores "
                                   "do mesmo bairro podem compartilhar contador sem conluio — contador isolado = 0.3); "
                                   "TEMPLATE de ERP gera Producer idêntico (confirmar com CreateDate e conteúdo); "
                                   "CV baixo em COMMODITY de preço tabelado é natural (checar item regulado).")
        return res

    def _cruzar_vinculos(self, cotacoes: list[dict], qsa_por_cnpj: dict, vencedor: str) -> dict:
        """Cruza sócios (QSA), endereço, telefone, e-mail e contador entre cotantes (e com o vencedor).
        Vínculo de SÓCIO/endereço/telefone/email = forte; vínculo com o VENCEDOR = forte; contador ISOLADO = fraco."""
        evidencias: list[dict] = []
        forte = False
        motivo_forte = ""
        contador_comum = False
        outros_vinculos = False
        n = len(cotacoes)
        for i in range(n):
            ci = cotacoes[i]
            cnpj_i = str(ci.get("cnpj") or "").strip()
            contato_i = ci.get("contato") or {}
            socios_i = _socios(qsa_por_cnpj.get(cnpj_i))
            tel_i, email_i, end_i = (_norm_tel(contato_i.get("telefone")),
                                     _norm_email(contato_i.get("email")), _norm_end(contato_i.get("endereco")))
            contador_i = str(ci.get("contador") or contato_i.get("contador") or "").strip().lower()
            for j in range(i + 1, n):
                cj = cotacoes[j]
                cnpj_j = str(cj.get("cnpj") or "").strip()
                contato_j = cj.get("contato") or {}
                socios_j = _socios(qsa_por_cnpj.get(cnpj_j))
                tel_j, email_j, end_j = (_norm_tel(contato_j.get("telefone")),
                                         _norm_email(contato_j.get("email")), _norm_end(contato_j.get("endereco")))
                contador_j = str(cj.get("contador") or contato_j.get("contador") or "").strip().lower()

                comum_socio = socios_i & socios_j
                if comum_socio:
                    forte = True
                    outros_vinculos = True
                    motivo_forte = motivo_forte or "sócio comum entre cotantes (QSA cruzado)"
                    evidencias.append({"fonte": "QSA cruzado",
                                       "trecho": f"cotantes {cnpj_i} e {cnpj_j} compartilham sócio(s)"})
                if tel_i and tel_i == tel_j:
                    forte = True
                    outros_vinculos = True
                    motivo_forte = motivo_forte or "telefone comum entre cotantes"
                    evidencias.append({"fonte": "contato das cotações",
                                       "trecho": f"telefone idêntico entre {cnpj_i} e {cnpj_j}: {tel_i}"})
                if email_i and email_i == email_j:
                    forte = True
                    outros_vinculos = True
                    motivo_forte = motivo_forte or "e-mail comum entre cotantes"
                    evidencias.append({"fonte": "contato das cotações",
                                       "trecho": f"e-mail idêntico entre {cnpj_i} e {cnpj_j}: {email_i}"})
                if end_i and end_i == end_j:
                    forte = True
                    outros_vinculos = True
                    motivo_forte = motivo_forte or "endereço comum entre cotantes"
                    evidencias.append({"fonte": "contato das cotações",
                                       "trecho": f"endereço idêntico entre {cnpj_i} e {cnpj_j}"})
                if contador_i and contador_i == contador_j:
                    contador_comum = True
                    evidencias.append({"fonte": "contador das cotações",
                                       "trecho": f"mesmo contador entre {cnpj_i} e {cnpj_j}: {contador_i}"})

        # vínculo de qualquer cotante com o VENCEDOR
        if vencedor:
            socios_venc = _socios(qsa_por_cnpj.get(vencedor))
            for c in cotacoes:
                cnpj_c = str(c.get("cnpj") or "").strip()
                if cnpj_c == vencedor:
                    continue
                if socios_venc and (_socios(qsa_por_cnpj.get(cnpj_c)) & socios_venc):
                    forte = True
                    motivo_forte = motivo_forte or "sócio comum entre cotante e o VENCEDOR"
                    evidencias.append({"fonte": "QSA cruzado (vencedor)",
                                       "trecho": f"cotante {cnpj_c} compartilha sócio com o vencedor {vencedor}"})

        so_contador = contador_comum and not outros_vinculos and not forte
        resumo = {"socio_endereco_tel_email": outros_vinculos, "contador_comum": contador_comum,
                  "forte": forte}
        return {"evidencias": evidencias, "resumo": resumo, "forte": forte,
                "motivo_forte": motivo_forte, "so_contador": so_contador}

    def _cruzar_metadados(self, cotacoes: list[dict]) -> dict:
        """Cruza metadados PDF entre cotações. Author/CreateDate idênticos = forte; só Producer idêntico = fraco."""
        authors: dict[str, int] = {}
        createdates: dict[str, int] = {}
        producers: dict[str, int] = {}
        for c in cotacoes:
            m = c.get("metadados_pdf") or {}
            a = str(m.get("Author") or m.get("author") or "").strip()
            cd = str(m.get("CreateDate") or m.get("createdate") or "").strip()
            p = str(m.get("Producer") or m.get("producer") or "").strip()
            if a:
                authors[a] = authors.get(a, 0) + 1
            if cd:
                createdates[cd] = createdates.get(cd, 0) + 1
            if p:
                producers[p] = producers.get(p, 0) + 1
        author_rep = any(v >= 2 for v in authors.values())
        createdate_rep = any(v >= 2 for v in createdates.values())
        producer_rep = any(v >= 2 for v in producers.values())
        evidencia = ""
        if author_rep or createdate_rep:
            evidencia = f"metadados repetidos: Author={author_rep} CreateDate={createdate_rep} entre cotações distintas"
        elif producer_rep:
            evidencia = "apenas Producer idêntico entre cotações (template de ERP — sinal fraco)"
        return {
            "author_ou_createdate_identicos": author_rep or createdate_rep,
            "so_producer_identico": producer_rep and not (author_rep or createdate_rep),
            "resumo": {"author_repetido": author_rep, "createdate_repetido": createdate_rep,
                       "producer_repetido": producer_rep},
            "evidencia": evidencia,
        }

    @staticmethod
    def _prompt_similaridade(cotacoes: list[dict]) -> str:
        return ("Compare visual e textualmente as cotações (layout, frases, erros). "
                f"São {len(cotacoes)} cotações de fornecedores supostamente independentes.")

    def _avaliar_rubrica(self, contexto: dict, chave_pre: str, escala: dict, prompt_user: str) -> dict:
        """Rubrica fechada (similaridade ou plausibilidade). Atalho de teste: `chave_pre` injetado no contexto.
        Sem rubrica e sem LLM → nao_avaliavel honesto."""
        pre = contexto.get(chave_pre)
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, escala)
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": (pre.get("nivel") or pre.get("classificacao") or "").strip().lower(), "motivo": motivo}
        gerar = contexto.get("gerar")
        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — rubrica não auditada (honesto)"}
        sistema = (
            "Você é auditor de controle externo. Classifique conforme a rubrica fechada. Responda SOMENTE com JSON: "
            '{"nivel":"<um nível da escala>","trecho":"<citação literal>"}. Sem trecho, não classifique.'
        )
        try:
            raw = gerar(prompt_user, sistema)
        except Exception as ex:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(ex)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, escala)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        return {"status": (dados.get("nivel") or "").strip().lower(), "motivo": motivo}
