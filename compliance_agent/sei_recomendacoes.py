# -*- coding: utf-8 -*-
"""SEI — recomendações/ressalvas NÃO ATENDIDAS nos processos (despachos de PGE, CGE, jurídico, controle interno).

Pedido do dono: o SEI tem que ser PENSANTE — avaliar se um parecer/despacho de **PGE** (Procuradoria), **CGE**
(Controladoria), **Assessoria Jurídica**, **Auditoria/Controle Interno** apontou uma recomendação/ressalva/
determinação e o processo seguiu **sem atendê-la** (red flag forte: a Administração contrariou o controle/jurídico).

Duas camadas:
  1. **Determinística** (`detectar`): identifica os docs que SÃO de órgão de controle/jurídico e que contêm
     linguagem de recomendação/ressalva + sinais de não-atendimento (reitera, permanece, não sanado…). Testável.
  2. **Pensante** (`avaliar_pensante`): para os candidatos, o **nous** (a IA do volume SEI) lê o despacho e julga
     se a recomendação foi atendida — trabalho NÃO-determinístico. Degrada honesto (sem nous → fica só a camada 1).

Honestidade: é **indício** (a Corte/PGE pode ter sido atendida depois noutro doc; o LLM pode errar). Sempre cita o
trecho/fonte; nunca afirma irregularidade — aponta "recomendação aparentemente não atendida, verificar".
"""
from __future__ import annotations

import json
import re

# órgãos de controle/jurídico cujo parecer/despacho carrega recomendação/ressalva
_EMISSORES = [
    ("PGE", r"\b(procuradoria\s+geral|PGE|procurador(?:ia)?\s+do\s+estado)\b"),
    ("CGE", r"\b(controladoria\s+geral|CGE|auditoria\s+geral\s+do\s+estado|AGE)\b"),
    ("CONTROLE_INTERNO", r"\b(controle\s+interno|auditoria\s+interna|unidade\s+de\s+controle)\b"),
    ("ASSESSORIA_JURIDICA", r"\b(assessoria\s+jur[ií]dica|consultoria\s+jur[ií]dica|parecer\s+jur[ií]dico|ASJUR|nota\s+t[eé]cnica\s+jur[ií]dica)\b"),
    ("TCE", r"\b(tribunal\s+de\s+contas|TCE-?RJ|corte\s+de\s+contas)\b"),
    # esfera MUNICIPAL (PCRJ): procuradoria e controladoria do Município
    ("PGM", r"\b(procuradoria\s+geral\s+do\s+munic[ií]pio|PGM)\b"),
    ("CGM", r"\b(controladoria\s+geral\s+do\s+munic[ií]pio|CGM)\b"),
]
_RE_RECOMENDA = re.compile(
    r"\b(recomenda|recomenda[çc][aã]o|ressalva|determina|determina[çc][aã]o|gloss?a|apontamento|"
    r"exige|condiciona|dever[aá]\s+ser\s+(?:sanad|suprid|corrigid)|sane-?se|suprir|impugna|n[aã]o\s+recomenda|"
    r"opina\s+pelo?\s+n[aã]o|abst[eê]m-se|com\s+ressalvas?)\b", re.I)
_RE_NAO_ATENDIDA = re.compile(
    r"\b(n[aã]o\s+(?:foi\s+)?atendid|n[aã]o\s+(?:foi\s+)?sanad|reiter|permanec\w+\s+a\s+(?:pend|ressalv|recomend|falh)|"
    r"persist\w+\s+a\s+(?:pend|irregular|falh)|descumpr|sem\s+manifesta[çc][aã]o|deixou\s+de\s+(?:atender|cumprir|sanar)|"
    r"n[aã]o\s+(?:foi\s+)?observ\w+\s+(?:o|a)\s+(?:parecer|recomenda|determina)|contrari\w+\s+(?:o|ao)\s+parecer|"
    r"pend[eê]ncia\s+n[aã]o\s+(?:sanad|atendid)|ressalva\s+n[aã]o\s+(?:sanad|atendid))", re.I)


# ── eixo de ACATAMENTO (art. 53 Lei 14.133: parecer jurídico prévio obrigatório; a autoridade só
#    pode divergir MOTIVADAMENTE — LINDB art. 22). Sinais no despacho da autoridade:
_RE_ACOLHIMENTO = re.compile(
    r"\b(acolho|acato|adoto|aprovo\s+(?:o|nos\s+termos\s+do)\s+parecer|nos\s+termos\s+do\s+parecer|"
    r"conforme\s+(?:o\s+)?parecer|em\s+conson[âa]ncia\s+com\s+o\s+parecer|acolhimento\s+(?:integral|do\s+parecer))\b", re.I)
_RE_REJEICAO_MOTIVADA = re.compile(
    r"\b(deixo\s+de\s+acolher|n[aã]o\s+acolho|divirjo\s+do\s+parecer|em\s+que\s+pese\s+o\s+parecer|"
    r"n[aã]o\s+obstante\s+o\s+parecer|afasto\s+a\s+(?:ressalva|recomenda[çc][aã]o)|"
    r"decido\s+em\s+sentido\s+(?:contr[áa]rio|diverso))\b", re.I)
_RE_DESPACHO_DECISORIO = re.compile(
    r"\b(despacho|homologo|homologa[çc][aã]o|adjudico|autorizo|aprovo|ratifico|decis[aã]o)\b", re.I)


def classificar_emissor(texto: str) -> str | None:
    t = texto or ""
    for nome, pat in _EMISSORES:
        if re.search(pat, t, re.I):
            return nome
    return None


def _trechos(texto: str, rgx: re.Pattern, n: int = 2, janela: int = 140) -> list[str]:
    out = []
    for m in rgx.finditer(texto or ""):
        a, b = max(0, m.start() - janela // 2), min(len(texto), m.end() + janela // 2)
        out.append(re.sub(r"\s+", " ", texto[a:b]).strip())
        if len(out) >= n:
            break
    return out


def detectar(docs: list[dict]) -> list[dict]:
    """Camada determinística. docs: [{ref, tipo, texto}]. Retorna candidatos: doc de controle/jurídico com
    linguagem de recomendação (e, se houver, sinais explícitos de não-atendimento)."""
    achados = []
    for d in docs or []:
        texto = d.get("texto") or ""
        emissor = classificar_emissor(texto) or classificar_emissor(d.get("tipo") or "")
        if not emissor:
            continue
        if not _RE_RECOMENDA.search(texto):
            continue
        nao_at = bool(_RE_NAO_ATENDIDA.search(texto))
        achados.append({
            "ref": d.get("ref"), "tipo": d.get("tipo"), "emissor": emissor,
            "tem_recomendacao": True, "sinal_nao_atendida": nao_at,
            "trechos_recomendacao": _trechos(texto, _RE_RECOMENDA),
            "trechos_nao_atendida": _trechos(texto, _RE_NAO_ATENDIDA) if nao_at else [],
            "status": "INDICIO_NAO_ATENDIDA" if nao_at else "RECOMENDACAO_A_CONFERIR"})
    return achados


def auditar_acatamento(docs: list[dict]) -> dict:
    """Veredito de ACATAMENTO do processo (determinístico): a autoridade acolheu, contrariou
    motivadamente, silenciou ou ignorou os pareceres de controle/jurídico? docs na ORDEM do
    processo: [{ref, tipo, texto}].

    Vereditos: ACOLHIDO · CONTRARIADO_COM_MOTIVACAO (lícito em abstrato — LINDB art. 22; registrar) ·
    IGNORADO_INDICIO (ressalva com sinal de não-atendimento e nenhum despacho de acolhimento/motivação
    posterior — flag forte) · SILENTE (parecer com recomendação e nenhum despacho decisório se
    manifesta) · SEM_PARECER_LOCALIZADO (nenhum doc de emissor jurídico/controle entre os LIDOS —
    art. 53 exige parecer prévio, mas cobertura de leitura ≠ inexistência: indício a confirmar).
    """
    pareceres = detectar(docs)
    despachos = []
    for i, d in enumerate(docs or []):
        texto = d.get("texto") or ""
        rotulo = f"{d.get('tipo') or ''} {texto[:200]}"
        if _RE_DESPACHO_DECISORIO.search(rotulo):
            despachos.append({"i": i, "ref": d.get("ref"),
                              "acolhe": bool(_RE_ACOLHIMENTO.search(texto)),
                              "rejeita_motivado": bool(_RE_REJEICAO_MOTIVADA.search(texto)),
                              "trechos": _trechos(texto, _RE_ACOLHIMENTO) or _trechos(texto, _RE_REJEICAO_MOTIVADA)})
    if not pareceres:
        return {"veredito": "SEM_PARECER_LOCALIZADO", "pareceres": [], "despachos": despachos,
                "leitura": ("Nenhum parecer de PGE/PGM/CGE/CGM/jurídico com recomendação entre os documentos "
                            "LIDOS. O art. 53 da Lei 14.133/2021 exige análise jurídica prévia — mas leitura "
                            "parcial ≠ inexistência (INDISPONÍVEL ≠ 0): conferir a íntegra antes de apontar.")}
    algum_nao_atendida = any(p["sinal_nao_atendida"] for p in pareceres)
    acolheu = any(dp["acolhe"] for dp in despachos)
    rejeitou = any(dp["rejeita_motivado"] for dp in despachos)
    if rejeitou:
        veredito = "CONTRARIADO_COM_MOTIVACAO"
        leitura = ("A autoridade decidiu em sentido diverso do parecer COM motivação expressa — lícito em "
                   "abstrato (LINDB art. 22), mas a motivação merece exame de mérito (registrar no dossiê).")
    elif algum_nao_atendida and not acolheu:
        veredito = "IGNORADO_INDICIO"
        leitura = ("Ressalva/recomendação com sinal explícito de NÃO-atendimento e nenhum despacho de "
                   "acolhimento ou divergência motivada localizado — indício FORTE de instrução viciada "
                   "(art. 53 Lei 14.133; Lei 8.429 art. 11). Confirmar em doc posterior antes de peça.")
    elif acolheu:
        veredito = "ACOLHIDO"
        leitura = "Despacho da autoridade acolhe o parecer (nos termos/acolho/aprovo) — cadeia regular."
    else:
        veredito = "SILENTE"
        leitura = ("Parecer com recomendação e NENHUM despacho decisório manifestando acolhimento ou "
                   "divergência entre os docs lidos — silêncio administrativo sobre o controle prévio "
                   "(indício médio; pode estar em documento não lido).")
    return {"veredito": veredito, "pareceres": pareceres, "despachos": despachos, "leitura": leitura}


_SYS_PENSANTE = (
    "Você é auditor de controle externo (TCE-RJ). Recebe o TEXTO de um despacho/parecer de um órgão de "
    "controle ou jurídico (PGE/CGE/Assessoria Jurídica/Controle Interno) dentro de um processo administrativo. "
    "Responda SOMENTE um JSON: {\"tem_recomendacao\":bool, \"recomendacao\":\"resumo curto da ressalva/recomendação/"
    "determinação, ou ''\", \"atendida\":\"sim|nao|indeterminado\", \"evidencia\":\"trecho que sustenta\", "
    "\"gravidade\":\"baixa|media|alta\"}. Seja CONSERVADOR: 'indeterminado' quando o texto não permite concluir. "
    "NUNCA invente; é indício, não acusação."
)


def avaliar_pensante(texto: str, timeout: float = 60.0) -> dict:
    """Camada PENSANTE (nous, a IA do volume SEI). Julga se a recomendação foi atendida. Degrada honesto."""
    try:
        import asyncio

        from tools.sei_ficha import STEPFUN, _chamar_nous
        prompt = f"DESPACHO/PARECER:\n{(texto or '')[:4000]}\n\nResponda só o JSON."
        raw = asyncio.run(asyncio.wait_for(_chamar_nous(_SYS_PENSANTE + "\n\n" + prompt, STEPFUN), timeout))
        m = re.search(r"\{.*\}", raw or "", re.S)
        return json.loads(m.group(0)) if m else {"_nota": "LLM sem JSON", "atendida": "indeterminado"}
    except Exception as exc:  # noqa: BLE001
        return {"_nota": f"INDISPONÍVEL (nous): {str(exc)[:120]}", "atendida": "indeterminado"}


def analisar(docs: list[dict], usar_llm: bool = True, max_llm: int = 4) -> dict:
    """Orquestra: detecta candidatos (determinístico) e, opcionalmente, avalia os mais relevantes com o nous."""
    candidatos = detectar(docs)
    if usar_llm:
        # prioriza os com sinal explícito de não-atendimento
        candidatos.sort(key=lambda c: (not c["sinal_nao_atendida"],))
        for c in candidatos[:max_llm]:
            texto = next((d.get("texto", "") for d in docs if d.get("ref") == c["ref"]), "")
            c["avaliacao_llm"] = avaliar_pensante(texto)
    n_nao = sum(1 for c in candidatos if c["sinal_nao_atendida"]
                or (c.get("avaliacao_llm", {}).get("atendida") == "nao"))
    return {"ok": True, "n_candidatos": len(candidatos), "n_indicio_nao_atendida": n_nao,
            "achados": candidatos, "leitura": _leitura(candidatos, n_nao)}


def _leitura(candidatos: list, n_nao: int) -> str:
    if not candidatos:
        return ("Nenhum despacho/parecer de controle (PGE/CGE/jurídico/CI) com recomendação detectado nos documentos "
                "lidos (INDISPONÍVEL ≠ ausência — depende do que o sweep SEI já leu do processo).")
    por_emissor = {}
    for c in candidatos:
        por_emissor[c["emissor"]] = por_emissor.get(c["emissor"], 0) + 1
    em = ", ".join(f"{k}: {v}" for k, v in por_emissor.items())
    base = (f"**{len(candidatos)}** parecer(es)/despacho(s) de controle/jurídico com recomendação ({em}).")
    if n_nao:
        base += (f" **{n_nao}** com **indício de recomendação NÃO ATENDIDA** — a Administração aparentemente seguiu o "
                 "processo contrariando a ressalva do controle/jurídico (red flag forte; CF/Lei 8.429 art. 11; "
                 "verificar se foi sanada em doc posterior). Indício, não prova.")
    else:
        base += " Sem sinal explícito de não-atendimento nos trechos lidos (confirmar o desfecho no processo)."
    return base
