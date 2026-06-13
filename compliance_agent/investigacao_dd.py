# -*- coding: utf-8 -*-
"""
Investigação de Due Diligence — detecção de EMPRESA DE FACHADA / LARANJA (interposição de pessoas).

Motor único e HONESTO que, dado um fornecedor (CNPJ) + seu cadastro + sua pegada de pagamentos,
roda uma bateria de HIPÓTESES investigativas e devolve um quadro estruturado. Cada hipótese carrega:
  {codigo, titulo, status, nivel, evidencia, fonte, base_legal, peso}

`status` (regra-mãe de honestidade — INDISPONÍVEL ≠ 0, indício ≠ acusação):
  • CONFIRMADO  — fato verificável na fonte (ex.: situação cadastral BAIXADA na Receita).
  • INDICIO     — sinal que MERECE APURAÇÃO; nunca conclusivo isolado (exige corroboração ≥2).
  • AFASTADO    — verificado e NÃO se confirma (registra a leitura correta; evita falso achado).
  • INDISPONIVEL— não foi possível verificar (sem dado/sem acesso) — NÃO é "limpo".

Quem consome: o **Lex (parecer jurídico)** chama `investigar()` e apresenta a investigação na sua
seção dedicada; os achados CONFIRMADO/INDICIO entram no grau e alimentam a análise raciocinada (gemini).

Base legal (controle externo, fiscalização legítima — Dep. Estadual no dever de fiscalizar):
  CF art. 58 §3º / 70-71; LGPD art. 7º,II e art. 23 (cumprimento de obrigação legal / atribuição do
  Poder Público — NÃO legítimo interesse). CPF de pessoa física mascarado (LGPD).

Indícios de fachada/laranja (literatura: TCU; OECD Bid Rigging 2025; ACFE; osint.industries shells):
  endereço residencial/terreno baldio · co-endereço · capital ínfimo vs. recebido · empresa recém-aberta
  · situação cadastral irregular · sócio único + sinais · porte incompatível com o recebido · sócio
  recebendo benefício social de subsistência (H-BENEFICIO, laranja) · sócio politicamente exposto
  (H-PEP, relação política) — ambos via Portal da Transparência/CGU (collectors/beneficios_sociais).
"""
from __future__ import annotations

import datetime as dt
import re

# ───────────────────────── helpers ─────────────────────────

def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _norm(s: str) -> str:
    import unicodedata
    s = (s or "").upper()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _parse_data(s) -> dt.date | None:
    s = str(s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(s[:len(fmt) + 2] if "T" in fmt else s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _moeda(v: float) -> str:
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ 0,00"


# ───────────────────────── marcadores de endereço residencial ─────────────────────────
# Conservador e ponderado: marcador FORTE = indício direto; marcador FRACO sozinho não basta.
# (Contabilidades/condomínios comerciais hospedam centenas de CNPJs — ver ressalva de honestidade.)
_MARC_FORTE = [
    "CASA", "APARTAMENTO", "APTO", "APTO.", "AP ", "APT ", "KITNET", "KITINETE", "QUITINETE",
    "FUNDOS", "SOBRADO", "EDICULA", "RESIDENCIAL", "RESID ", "RESID.", "CHACARA", "SITIO",
]
_MARC_FRACO = ["BLOCO", "CONDOMINIO", "COND ", "COND.", "VILA", "QUADRA", "LOTE", "CASA "]


def _marcadores_residenciais(*partes: str) -> list[str]:
    """Marcadores residenciais encontrados no endereço/complemento (texto livre)."""
    txt = " " + _norm(" ".join(p for p in partes if p)) + " "
    achados = []
    for m in _MARC_FORTE:
        if m.strip() and (m if m.endswith(" ") else m + " ") in txt or m.strip() in txt.split():
            achados.append(m.strip())
    # dedup preservando ordem
    vis = []
    for a in achados:
        if a not in vis:
            vis.append(a)
    return vis


# ───────────────────────── tetos de faturamento (porte) ─────────────────────────
# Limites legais de receita bruta anual (LC 123/2006 + Res. CGSN): sinal de incompatibilidade quando o
# PAGO pelo Estado já supera o teto do porte declarado. Indício (o teto é anual e plurianual aqui) — apura.
_TETO_PORTE = {
    "MEI": 81_000.0,
    "MICRO EMPRESA": 360_000.0,
    "ME": 360_000.0,
    "EMPRESA DE PEQUENO PORTE": 4_800_000.0,
    "EPP": 4_800_000.0,
}


def _teto_do_porte(porte: str) -> tuple[str, float] | None:
    p = _norm(porte).strip()
    for chave, teto in _TETO_PORTE.items():
        if chave in p:
            return chave, teto
    return None


# ───────────────────────── motor ─────────────────────────

def _hip(codigo, titulo, status, nivel, evidencia, fonte, base_legal, peso) -> dict:
    return {"codigo": codigo, "titulo": titulo, "status": status, "nivel": nivel,
            "evidencia": evidencia, "fonte": fonte, "base_legal": base_legal, "peso": peso}


def investigar(cnpj: str, *, cadastral: dict | None = None, pagamentos: dict | None = None,
               usar_rede: bool = True, geocode: bool = False, usar_beneficios: bool = True) -> dict:
    """Roda a bateria de hipóteses de fachada/laranja para um CNPJ.

    Args:
      cnpj: o fornecedor investigado (14 dígitos; PF de 11 também é aceita, com menos hipóteses).
      cadastral: dict do cadastro (situacao, abertura, capital, porte, cnae, complemento, logradouro,
                 numero, bairro, socios[…]). Se None, busca via providers registry (best-effort).
      pagamentos: {total_pago, n_obs, primeira_data?} — a pegada nas OBs (verdade de pagamento).
      usar_rede: cruza co-endereço/empresas-irmãs na base ingerida (cruzamento.py).
      geocode: se True, consulta o Nominatim p/ checar existência/tipo do endereço (rate-limit 1 req/s).
      usar_beneficios: consulta Portal da Transparência/CGU (PEP por nome do sócio = relação política;
                 benefício social por CPF completo = laranja). Bounded+cacheado; sem chave → INDISPONÍVEL.

    Retorna {cnpj, hipoteses:[…], score, grau, n_indicios, n_confirmados, resumo, cobertura}.
    """
    cnpj = _digitos(cnpj)
    cad = dict(cadastral or {})
    pag = dict(pagamentos or {})
    total_pago = float(pag.get("total_pago") or 0.0)

    # cadastro best-effort se NÃO foi fornecido (cadastral is None). Um dict vazio explícito
    # significa "não tenho cadastro" e NÃO dispara rede — preserva a honestidade do INDISPONÍVEL.
    if cadastral is None and len(cnpj) == 14:
        try:
            from compliance_agent.providers import lookup
            r = lookup("registry", cnpj=cnpj)
            if r.ok and isinstance(r.dados, dict):
                cad = r.dados
        except Exception:
            cad = {}

    hipoteses: list[dict] = []
    cobertura: dict[str, str] = {}

    endereco_txt = " ".join(str(cad.get(k) or "") for k in ("logradouro", "numero", "complemento", "bairro"))
    complemento = str(cad.get("complemento") or "")

    # H-END-HUMANO — veredito HUMANO do dono sobre a foto de rua (doubt-sender) PRECEDE o automático:
    # quando a verificação ficou em dúvida, o dono olhou o Street View e decidiu. Verdade > inferência.
    try:
        from compliance_agent.fachada_doubt import veredito_humano
        vh = veredito_humano(cnpj) if len(cnpj) == 14 else None
    except Exception:
        vh = None
    if vh and vh.get("status") == "fachada":
        nivel = "ALTO" if total_pago > 500_000 else "MEDIO"
        hipoteses.append(_hip(
            "H-END-HUMANO", "Sede confirmada como FACHADA por inspeção visual (veredito do auditor)",
            "CONFIRMADO", nivel,
            f"Inspeção visual da sede (Street View) julgada FACHADA/inexistente pelo auditor em "
            f"{vh.get('em', '—')}. Empresa recebeu {_moeda(total_pago)} do Estado em endereço sem operação "
            "real — confirmação direta, não inferência.",
            "Inspeção visual (Street View) + veredito humano", "art. 337-F CP; art. 11 Lei 8.429/92", 24))
        cobertura["veredito_humano"] = "CONFIRMADO fachada"
    elif vh and vh.get("status") == "indicio":
        hipoteses.append(_hip(
            "H-END-HUMANO", "Sede em endereço residencial confirmada por inspeção visual (veredito do auditor)",
            "INDICIO", "MEDIO",
            f"Inspeção visual da sede (Street View) pelo auditor em {vh.get('em', '—')}: endereço de natureza "
            f"residencial — indício de fachada/laranja a apurar (não conclui sede inexistente). Empresa recebeu "
            f"{_moeda(total_pago)} do Estado.",
            "Inspeção visual (Street View) + veredito humano", "art. 337-F CP; art. 11 Lei 8.429/92", 10))
        cobertura["veredito_humano"] = "INDÍCIO residencial (auditor)"
    elif vh and vh.get("status") == "real":
        cobertura["veredito_humano"] = "sede AFASTADA pelo auditor (foto = sede real)"

    # H-END-RESID — endereço com marcador residencial
    marcs = _marcadores_residenciais(complemento, str(cad.get("logradouro") or ""))
    if marcs:
        nivel = "ALTO" if (total_pago > 1_000_000 or len(marcs) >= 2) else "MEDIO"
        hipoteses.append(_hip(
            "H-END-RESID", "Sede em endereço de natureza residencial", "INDICIO", nivel,
            f"Endereço/complemento sugere imóvel residencial (marcadores: {', '.join(marcs)}; "
            f"endereço: {endereco_txt.strip() or '—'}). Empresa que movimenta recursos públicos "
            f"({_moeda(total_pago)} recebidos) sediada em residência é indício clássico de fachada — "
            "verificar operação física real (estoque, funcionários, instalações).",
            "Receita Federal (cadastro CNPJ)", "art. 337-F CP; art. 11 Lei 8.429/92", 18 if nivel == "ALTO" else 10))
        cobertura["endereco_residencial"] = "verificado"
    elif endereco_txt.strip():
        cobertura["endereco_residencial"] = "verificado (sem marcador)"
    else:
        cobertura["endereco_residencial"] = "INDISPONIVEL (endereço não ingerido)"

    # H-END-EXISTE — existência/tipo do endereço via Nominatim (proxy honesto p/ 'terreno baldio')
    if geocode and endereco_txt.strip():
        g = _checar_endereco_geocode(endereco_txt, cad.get("municipio"), cad.get("uf"), cad.get("cep"))
        cobertura["geocode"] = g.get("estado", "INDISPONIVEL")
        if g.get("status") in ("INDICIO", "CONFIRMADO"):
            hipoteses.append(_hip(
                "H-END-EXISTE", "Sede não confirmada fisicamente (terreno/baldio/inexistência)",
                g["status"], g["nivel"], g["evidencia"],
                "Nominatim + Overpass/OpenStreetMap", "art. 337-F CP", g["peso"]))
    else:
        cobertura["geocode"] = "não solicitado" if endereco_txt.strip() else "INDISPONIVEL"

    # H-COEND — outros fornecedores recebendo do Estado na MESMA sede
    if usar_rede:
        try:
            from compliance_agent import cruzamento as cz
            from compliance_agent import rede_societaria as rs
            e = rs.endereco_de(cnpj)
            coend = cz.fornecedores_no_mesmo_endereco(e.get("endereco_norm", ""), cnpj_excluir=cnpj) if e else []
            coend_pagos = [c for c in coend if c.get("total_pago", 0) > 0]
            if coend:
                nivel = "ALTO" if coend_pagos else "MEDIO"
                exemplos = "; ".join(f"{(c.get('razao') or c['cnpj'])[:34]} ({_moeda(c.get('total_pago', 0))})"
                                     for c in coend[:3])
                hipoteses.append(_hip(
                    "H-COEND", "Outros fornecedores do Estado na mesma sede", "INDICIO", nivel,
                    f"{len(coend)} outro(s) fornecedor(es) com sede no MESMO endereço, "
                    f"{len(coend_pagos)} também recebendo do Estado (ex.: {exemplos}). Co-localização de "
                    "fornecedores sem sócio declarado em comum é red flag de fachada/laranja/direcionamento.",
                    "Base JFN (endereço × OBs)", "art. 337-F CP; art. 11 Lei 8.429/92",
                    16 if coend_pagos else 8))
                cobertura["coendereco"] = f"verificado ({len(coend)} co-localizados)"
            else:
                cobertura["coendereco"] = "verificado (nenhum)"
        except Exception:
            cobertura["coendereco"] = "INDISPONIVEL"

    # H-CAPITAL — capital social ínfimo frente ao volume recebido
    capital = _num(cad.get("capital"))
    if capital is not None and total_pago > 0:
        if capital <= 0:
            pass
        elif total_pago >= 50 * capital and total_pago > 500_000:
            razao = total_pago / capital if capital else 0
            hipoteses.append(_hip(
                "H-CAPITAL", "Capital social ínfimo frente ao recebido", "INDICIO",
                "ALTO" if razao >= 200 else "MEDIO",
                f"Capital social declarado de {_moeda(capital)} contra {_moeda(total_pago)} recebidos do "
                f"Estado ({razao:,.0f}× o capital). Capital irrisório frente a contratos vultosos é indício "
                "de subcapitalização típica de empresa de fachada — verificar capacidade econômico-financeira.",
                "Receita Federal (cadastro CNPJ)", "art. 11 Lei 8.429/92; Lei 14.133/21 art. 69",
                14 if razao >= 200 else 8))
        cobertura["capital"] = "verificado"
    else:
        cobertura["capital"] = "INDISPONIVEL"

    # H-RECENTE — empresa aberta pouco antes de receber do Estado
    abertura = _parse_data(cad.get("abertura"))
    primeira = _parse_data(pag.get("primeira_data"))
    if abertura:
        ref = primeira or dt.date.today()
        dias = (ref - abertura).days
        if primeira and 0 <= dias < 180:
            hipoteses.append(_hip(
                "H-RECENTE", "Empresa recém-aberta antes do 1º recebimento", "INDICIO",
                "ALTO" if dias < 90 else "MEDIO",
                f"Empresa aberta em {abertura:%d/%m/%Y} e já recebendo do Estado {dias} dias depois "
                f"({primeira:%d/%m/%Y}). Constituição imediatamente anterior à receita pública é indício de "
                "empresa criada sob medida para o contrato — verificar histórico operacional prévio.",
                "Receita Federal (cadastro CNPJ)", "art. 337-F CP", 12 if dias < 90 else 7))
        cobertura["recencia"] = "verificado"
    else:
        cobertura["recencia"] = "INDISPONIVEL"

    # H-SITUACAO — situação cadastral irregular (CONFIRMADO, sinal forte)
    sit = _norm(cad.get("situacao") or "")
    if sit:
        irregular = any(t in sit for t in ("BAIXAD", "INAPT", "SUSPENS", "NULA"))
        if irregular:
            hipoteses.append(_hip(
                "H-SITUACAO", "Situação cadastral irregular na Receita", "CONFIRMADO", "ALTO",
                f"Situação cadastral '{cad.get('situacao')}' na Receita Federal. Pagamento/contratação de "
                "empresa não-ativa é vedado e pode indicar fachada ou descontrole do contratante.",
                "Receita Federal (cadastro CNPJ)", "Lei 14.133/21 art. 14; Lei 8.666/93 art. 87", 20))
        cobertura["situacao_cadastral"] = "verificado"
    else:
        cobertura["situacao_cadastral"] = "INDISPONIVEL"

    # H-PORTE — porte declarado incompatível com o volume recebido
    tp = _teto_do_porte(cad.get("porte") or "")
    if tp and total_pago > 0:
        chave, teto = tp
        if total_pago > teto:
            hipoteses.append(_hip(
                "H-PORTE", "Volume recebido acima do teto do porte declarado", "INDICIO", "MEDIO",
                f"Porte declarado '{cad.get('porte')}' (teto de receita ≈ {_moeda(teto)}/ano) contra "
                f"{_moeda(total_pago)} recebidos do Estado. Volume acima do teto do enquadramento merece "
                "apuração de enquadramento indevido (benefício de ME/EPP) ou de pulverização entre CNPJs.",
                "Receita Federal (porte) × OBs", "LC 123/2006; Lei 14.133/21 art. 4º", 8))
        cobertura["porte"] = "verificado"
    else:
        cobertura["porte"] = "INDISPONIVEL" if not tp else "verificado"

    # H-SOCIO-UNICO — composição mínima + sinais (composite; só dispara com corroboração)
    socios = cad.get("socios") or []
    if len(socios) == 1 and (marcs or (capital is not None and 0 < capital <= 10_000)):
        corrobora = []
        if marcs:
            corrobora.append("endereço residencial")
        if capital is not None and 0 < capital <= 10_000:
            corrobora.append(f"capital {_moeda(capital)}")
        hipoteses.append(_hip(
            "H-SOCIO-UNICO", "Sócio único com sinais de fachada", "INDICIO", "MEDIO",
            f"Quadro societário com 1 único sócio, somado a {' e '.join(corrobora)}. A combinação de sócio "
            "único, baixo capital e endereço residencial é o perfil típico de empresa de fachada/laranja — "
            "verificar a pessoa do sócio (capacidade econômica, vínculos, interposição).",
            "Receita Federal (QSA)", "art. 337-F CP; art. 11 Lei 8.429/92", 8))

    # H-SOCIO-SERVIDOR — fusão de máscaras folha×QSA: sócio que também é servidor público do RJ (nome na
    # folha + dígitos do CPF consistentes). Vínculo servidor↔fornecedora do Estado é indício de conflito de
    # interesse/laranja (apurar impedimento/período). Precomputado em socios_fornecedor (leve).
    if len(cnpj) == 14:
        try:
            from compliance_agent.resolucao_cpf import socios_servidores
            servs = socios_servidores(cnpj)
        except Exception:
            servs = []
        if servs:
            nomes = ", ".join(s["nome"] for s in servs if s.get("nome"))[:200]
            nivel = "ALTO" if total_pago > 1_000_000 else "MEDIO"
            hipoteses.append(_hip(
                "H-SOCIO-SERVIDOR", "Sócio é servidor público do Estado (fusão de máscaras folha×QSA)",
                "INDICIO", nivel,
                f"Sócio(s) com nome na folha de pagamento do RJ e dígitos de CPF consistentes com a máscara "
                f"do QSA ({nomes}). Servidor público sócio de fornecedora que recebe do Estado "
                f"({_moeda(total_pago)}) é indício de conflito de interesse/interposição (laranja) — apurar "
                "vínculo formal, lotação, período e eventual impedimento. Indício, não acusação.",
                "Folha de pagamento (transparência RJ) + QSA público (fusão de máscaras)",
                "art. 9º/11 Lei 8.429/92; art. 117 Lei 8.112/90 (impedimento)", 16 if nivel == "ALTO" else 10))
            cobertura["socio_servidor"] = f"{len(servs)} sócio(s) servidor(es) (fusão folha×QSA)"

    # H-PEP / H-BENEFICIO — Portal da Transparência/CGU. PEP por NOME do sócio (QSA desmascarado) =
    # relação política; benefício social de subsistência por CPF COMPLETO = indício de laranja. Bounded,
    # cacheado (7d) e honesto: sem chave/CPF mascarado → INDISPONÍVEL (≠ "limpo"). Degrada em try/except.
    if usar_beneficios:
        _wire_beneficios_pep(cnpj, total_pago, socios, hipoteses, cobertura)

    # ───── consolidação honesta ─────
    confirmados = [h for h in hipoteses if h["status"] == "CONFIRMADO"]
    indicios = [h for h in hipoteses if h["status"] == "INDICIO"]
    score = min(100, sum(h["peso"] for h in hipoteses if h["status"] in ("CONFIRMADO", "INDICIO")))
    # corroboração: grau exige ≥2 sinais OU ≥1 confirmado forte (ACFE/OSINT: 1 sinal fraco não conclui)
    if confirmados and score >= 30:
        grau = "🔴"
    elif score >= 30 or len(indicios) >= 2:
        grau = "🟡"
    else:
        grau = "🟢"

    return {
        "cnpj": cnpj, "hipoteses": hipoteses, "score": score, "grau": grau,
        "n_indicios": len(indicios), "n_confirmados": len(confirmados),
        "resumo": _resumo(grau, confirmados, indicios), "cobertura": cobertura,
    }


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if isinstance(v, str) and "," in str(v) else float(v)
    except (TypeError, ValueError):
        return None


def _resumo(grau: str, confirmados: list, indicios: list) -> str:
    if not confirmados and not indicios:
        return ("Nenhum indício de fachada/laranja identificado nas hipóteses verificáveis (não exclui "
                "achados em fontes não disponíveis nesta varredura).")
    partes = []
    if confirmados:
        partes.append(f"{len(confirmados)} fato(s) confirmado(s)")
    if indicios:
        partes.append(f"{len(indicios)} indício(s) a apurar")
    return ("Investigação de fachada/laranja: " + " e ".join(partes) +
            ". Indício merece apuração — não constitui acusação (presunção de regularidade).")


# ─────────── PEP (relação política) + benefício social (laranja) — Portal da Transparência/CGU ───────────

def _run_coro(factory):
    """Roda uma corrotina com segurança, mesmo dentro de um event loop (FastAPI/Lex)."""
    import asyncio
    import concurrent.futures
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            return ex.submit(lambda: asyncio.run(factory())).result()
    return asyncio.run(factory())


def _cpf_completo(doc) -> str:
    """CPF completo (11 dígitos, NÃO mascarado) ou '' — o QSA público traz o CPF mascarado (LGPD)."""
    s = str(doc or "")
    if "*" in s or "x" in s.lower():
        return ""
    d = _digitos(s)
    return d if len(d) == 11 else ""


def _socio_eh_pf(s: dict) -> bool:
    """Sócio é pessoa física? doc com 14 dígitos limpos = sócio PJ (não buscar PEP/benefício nele)."""
    return len(_digitos((s or {}).get("doc"))) != 14


def _resolver_cpf(nome: str, doc: str) -> dict:
    """Ponte CPF mascarado → completo (nome+middle6, técnica br-acc). Degrada honesto."""
    try:
        from compliance_agent.resolucao_cpf import resolver
        return resolver(nome, doc)
    except Exception:  # noqa: BLE001
        return {"resolvido": False, "cpf": "", "confianca": 0.0}


def _wire_beneficios_pep(cnpj: str, total_pago: float, socios: list, hipoteses: list, cobertura: dict) -> None:
    """Conecta o coletor de benefícios/PEP ao motor de DD (degrada honesto: sem chave → INDISPONÍVEL)."""
    try:
        from compliance_agent.collectors.beneficios_sociais import _chave
    except Exception:
        cobertura["pep"] = cobertura["beneficio_social"] = "INDISPONIVEL (coletor ausente)"
        return
    if not _chave():
        cobertura["pep"] = "INDISPONIVEL (sem chave PORTAL_TRANSPARENCIA_KEY)"
        cobertura["beneficio_social"] = "INDISPONIVEL (sem chave PORTAL_TRANSPARENCIA_KEY)"
        return
    try:
        res = _run_coro(lambda: _coletar_beneficios_pep(cnpj, total_pago, socios or []))
    except Exception as e:  # noqa: BLE001
        cobertura["pep"] = cobertura["beneficio_social"] = f"INDISPONIVEL ({str(e)[:40]})"
        return
    hipoteses.extend(res["hipoteses"])
    cobertura.update(res["cobertura"])


async def _coletar_beneficios_pep(cnpj: str, total_pago: float, socios: list, max_socios: int = 6,
                                  budget_s: float = 30.0) -> dict:
    """Consulta PEP (por nome) + benefício (por CPF completo) p/ a entidade e seus sócios. Bounded por tempo."""
    import time
    from compliance_agent.collectors.beneficios_sociais import verificar_beneficios, verificar_pep
    inicio = time.monotonic()
    hip: list[dict] = []
    cob: dict[str, str] = {}
    pep_matches: list[tuple[str, str]] = []
    benef_matches: list[tuple[str, list]] = []
    n_pep = n_benef = n_resolvidos = 0
    socio_mascarado = False

    def _tipos(b: dict) -> list:
        return sorted({x.get("tipo") for x in (b.get("beneficios") or []) if x.get("tipo")})

    # (1) a própria entidade investigada é PF (CPF favorecido)? → benefício de subsistência direto
    if len(_digitos(cnpj)) == 11:
        n_benef += 1
        b = await verificar_beneficios(cnpj)
        if b.get("verificado") and b.get("recebe_beneficio"):
            benef_matches.append(("o próprio favorecido (CPF)", _tipos(b)))

    # (2) sócios pessoa física: PEP por NOME (desmascarado) + benefício se houver CPF completo
    pf_socios = [s for s in (socios or []) if _socio_eh_pf(s)][:max_socios]
    for s in pf_socios:
        if time.monotonic() - inicio > budget_s:
            cob["pep_truncado"] = f"orçamento de tempo ({budget_s:.0f}s) atingido — consulta parcial"
            break
        nome = (s.get("nome") or "").strip()
        cpf_full = _cpf_completo(s.get("doc"))
        nota_resolv = ""
        # CPF mascarado? tenta a ponte nome+middle6 (br-acc) p/ destravar a consulta de benefício
        if not cpf_full and len(nome) >= 6:
            rr = _resolver_cpf(nome, s.get("doc"))
            if rr.get("resolvido") and rr.get("cpf"):
                cpf_full = rr["cpf"]
                n_resolvidos += 1
                nota_resolv = " (identidade resolvida por nome + 6 díg do meio — confirmar)"
        if len(nome) >= 6:
            n_pep += 1
            p = await verificar_pep(nome=nome)
            if p.get("verificado") and p.get("eh_pep"):
                detalhes = []
                for x in (p.get("peps") or [])[:2]:
                    parte = " — ".join(z for z in (x.get("funcao"), x.get("orgao")) if z)
                    if parte:
                        detalhes.append(parte)
                descr = "; ".join(detalhes) if detalhes else "função/órgão não detalhados na base PEP"
                pep_matches.append((nome, descr))
        if cpf_full:
            n_benef += 1
            b = await verificar_beneficios(cpf_full)
            if b.get("verificado") and b.get("recebe_beneficio"):
                benef_matches.append((f"sócio {nome or cpf_full}{nota_resolv}", _tipos(b)))
        else:
            socio_mascarado = True

    # ── H-PEP (relação política) ──
    if pep_matches:
        lista = "; ".join(f"{nm} ({d})" for nm, d in pep_matches[:4])
        hip.append(_hip(
            "H-PEP", "Sócio politicamente exposto (PEP) — relação política", "INDICIO", "MEDIO",
            f"{len(pep_matches)} sócio(s) com correspondência na base de Pessoas Expostas Politicamente "
            f"(PEP/CGU): {lista}. Vínculo político de sócio de empresa que contrata com o Estado é indício de "
            "risco de conflito de interesses/favorecimento. A correspondência é por NOME e pode envolver "
            "homônimo (o CPF do QSA é mascarado por LGPD) — confirmar identidade antes de qualquer conclusão.",
            "Portal da Transparência/CGU (PEP)",
            "art. 9º Lei 14.133/21 (impedimento); Lei 12.813/13 (conflito de interesses); art. 11 Lei 8.429/92", 8))
    if n_pep:
        cob["pep"] = f"verificado ({n_pep} sócio(s) consultado(s); {len(pep_matches)} correspondência(s) por nome)"
    else:
        cob["pep"] = "INDISPONIVEL (sem sócio pessoa física com nome no QSA)"

    # ── H-BENEFICIO (laranja) ──
    if benef_matches:
        det = "; ".join(f"{quem}: {', '.join(t) or 'benefício social'}" for quem, t in benef_matches[:4])
        hip.append(_hip(
            "H-BENEFICIO", "Beneficiário de programa social de subsistência (indício de laranja)",
            "INDICIO", "ALTO",
            f"Vínculo com programa(s) social(is) de subsistência (CGU): {det}. Titular/sócio de empresa que "
            f"recebe recursos públicos ({_moeda(total_pago)}) e que figura como beneficiário de transferência "
            "de subsistência é indício clássico de interposição de pessoa (laranja) — apurar a capacidade "
            "econômica real e a efetiva titularidade do negócio.",
            "Portal da Transparência/CGU (PETI/Garantia-Safra/Seguro-Defeso)",
            "art. 337-F CP; art. 11 Lei 8.429/92", 14))
    if n_benef:
        resolv = f"; {n_resolvidos} via ponte nome+6díg" if n_resolvidos else ""
        cob["beneficio_social"] = (f"verificado ({n_benef} CPF(s) consultado(s){resolv}; "
                                   f"{len(benef_matches)} positivo(s))")
    elif socio_mascarado:
        cob["beneficio_social"] = ("INDISPONIVEL (CPF dos sócios mascarado — LGPD; sem par único "
                                   "nome+6díg no corpus de favorecidos p/ resolver)")
    else:
        cob["beneficio_social"] = "INDISPONIVEL (sem CPF completo p/ consultar)"
    return {"hipoteses": hip, "cobertura": cob}


# ───────────────────────── geocode (Nominatim) — proxy honesto de 'terreno baldio' ─────────────────────────

def _checar_endereco_geocode(endereco: str, municipio: str | None, uf: str | None,
                             cep: str | None) -> dict:
    """Verifica a REALIDADE da sede: geocode-match + edificação/baldio (Nominatim + Overpass).

    Delega ao módulo `verificacao_endereco` (geocode resolve? bate o município? há edificação no ponto ou
    é terreno não edificado/baldio?). Honesto: cobertura do OSM é incompleta → ausência ≠ prova; nunca
    CONFIRMADO só por OSM. Retorna {status,nivel,evidencia,peso,estado,sinais}.
    """
    try:
        from compliance_agent.verificacao_endereco import analisar_endereco
        return analisar_endereco(endereco, municipio, uf, cep, usar_overpass=True)
    except Exception as e:  # noqa: BLE001 — degrada honesto
        return {"status": "INDISPONIVEL", "estado": f"INDISPONIVEL ({str(e)[:40]})"}


# ───────────────────────── CLI ─────────────────────────

if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Investigação de fachada/laranja para um CNPJ")
    ap.add_argument("cnpj")
    ap.add_argument("--geocode", action="store_true", help="consulta Nominatim (rate-limit 1 req/s)")
    ap.add_argument("--total", type=float, default=0.0, help="total pago pelo Estado (p/ as hipóteses de volume)")
    a = ap.parse_args()
    out = investigar(a.cnpj, pagamentos={"total_pago": a.total}, geocode=a.geocode)
    print(json.dumps(out, ensure_ascii=False, indent=2))
