# -*- coding: utf-8 -*-
"""Subsunção auditável — o raciocínio jurídico com as juntas à mostra.

POR QUE ESTE MÓDULO EXISTE. Hoje o veredito do sistema é `{grau, raciocinio (texto livre),
trechos}`. O `raciocinio` é prosa: ninguém consegue verificá-lo item a item, e o que não se
verifica não se corrige. Um parecer que conclui "há indício de direcionamento porque a exigência
é desproporcional" pode estar certo ou pode estar pulando três degraus — e do lado de fora as
duas coisas se parecem.

A subsunção decompõe o juízo nas peças que um tribunal confere separadamente:

    premissa maior   o que a norma exige ou veda, com o texto VERBATIM
    premissa menor   os fatos, cada um com o trecho ancorado no documento e o grau A-E
    subsunção        por que o fato cai (ou não cai) na hipótese normativa
    contra-argumento a melhor tese da defesa — OBRIGATÓRIA, não decorativa
    conclusão        enquadra ou não, com o standard probatório alcançado

AS TRÊS REGRAS DE INTEGRIDADE, e cada uma corrige um modo de falhar:

  1. **Premissa maior só cita o que resolve.** O dispositivo tem de existir em `base_legal`, a
    súmula tem de resolver em `jurisprudencia.obter_sumula`, e o acórdão tem de passar pelo
    `tcu_juris_index`. Sem isso, a fundamentação vira citação plausível — que é exatamente o que
    a auditoria de 2026-07-27 achou dentro da base curada da própria casa.
  2. **Premissa menor sem trecho ancorado é REMOVIDA.** Não rebaixada: removida. Fato sem fonte
    não é premissa, é afirmação. Se sobrarem zero, a subsunção inteira vira `nao_aferivel` —
    nunca "conclusão fraca", que é como um raciocínio vazio se disfarça de cauteloso.
  3. **Contra-argumento é obrigatório.** Uma subsunção que não enfrenta a melhor tese da defesa
    não é raciocínio jurídico; é acusação. E é a primeira coisa que derruba a peça.

QUEM ESCREVE O QUÊ. O LLM preenche os campos; o CÓDIGO verifica cada um e monta o texto final.
É a regra da casa — a IA lê, o código arruma — aplicada ao raciocínio em vez de ao número.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Graus de evidência de `editais/flags` (A CERTO · B FORTE · C SUSPEITO · D NÃO-AFERÍVEL ·
# E EXCULPADO). Só A e B fundamentam peça; a subsunção herda essa régua em vez de criar outra.
_FORCA = {"A": 4, "B": 3, "C": 2, "D": 0, "E": 0}


@dataclass
class Fato:
    """Uma premissa menor: o fato, e de onde ele veio."""

    enunciado: str
    trecho: str = ""
    documento: str = ""
    folha: str = ""
    grau: str = "C"
    ancorado: bool | None = None       # preenchido pela verificação
    similaridade: float | None = None
    motivo_descarte: str = ""


@dataclass
class Subsuncao:
    norma_dispositivo: str
    norma_verbatim: str
    premissa_maior: str
    fatos: list[Fato] = field(default_factory=list)
    subsuncao: str = ""
    contra_argumento: str = ""
    conclusao_enquadra: bool | None = None
    ressalva: str = ""


def _verificar_norma(dispositivo: str) -> dict[str, Any]:
    """A premissa maior aponta para norma que EXISTE nas bases da casa?"""
    d = str(dispositivo or "").strip()
    if not d:
        return {"ok": False, "fonte": None, "motivo": "dispositivo não informado"}

    # 1) súmula (resolve por qualquer grafia; devolve None quando não mapeada — degrada honesto)
    try:
        from compliance_agent.knowledge.jurisprudencia import obter_sumula
        if obter_sumula(d):
            return {"ok": True, "fonte": "sumula", "motivo": "súmula resolvida na base curada"}
    except Exception:  # noqa: BLE001 — base indisponível não vira norma inválida
        pass

    # 2) acórdão — o índice oficial é quem diz se existe
    if "acórdão" in d.lower() or "acordao" in d.lower():
        try:
            from compliance_agent.knowledge.tcu_juris_index import verificar_citacao
            achados = verificar_citacao(d)
            if achados:
                st = achados[0].get("status")
                if st == "confirmado":
                    return {"ok": True, "fonte": "tcu_juris_index", "motivo": "acórdão confirmado"}
                if st == "indice_ausente":
                    return {"ok": True, "fonte": "indice_ausente",
                            "motivo": "índice do TCU indisponível — citação NÃO conferida"}
                return {"ok": False, "fonte": "tcu_juris_index",
                        "motivo": f"acórdão com status {st!r} no acervo oficial"}
        except Exception:  # noqa: BLE001
            pass

    # 3) dispositivo de lei na base legal curada
    try:
        from compliance_agent.knowledge.base_legal import DISPOSITIVOS
        alvo = d.lower().replace(" ", "")
        for disp in DISPOSITIVOS:
            chave = f"{getattr(disp, 'lei', '')}{getattr(disp, 'artigo', '')}".lower().replace(" ", "")
            if chave and (chave in alvo or alvo in chave):
                return {"ok": True, "fonte": "base_legal", "motivo": "dispositivo na base curada"}
    except Exception:  # noqa: BLE001
        pass

    return {"ok": False, "fonte": None,
            "motivo": "dispositivo não resolve em súmula, acórdão confirmado nem base legal — "
                      "fundamentação inverificável"}


def montar(dados: dict, fonte_documental: str = "") -> dict[str, Any]:
    """Constrói e VERIFICA uma subsunção a partir do que o LLM preencheu.

    `dados` no formato `{norma_dispositivo, norma_verbatim, premissa_maior, fatos: [...],
    subsuncao, contra_argumento, conclusao_enquadra}`. `fonte_documental` é o texto contra o qual
    cada trecho é ancorado — sem ele, os fatos entram como NÃO CONFERIDOS e isso fica declarado.
    """
    from compliance_agent.nucleo.grounding import ancorar

    d = dados or {}
    norma = _verificar_norma(d.get("norma_dispositivo"))

    fatos: list[Fato] = []
    descartados: list[dict] = []
    for f in d.get("fatos") or []:
        if not isinstance(f, dict):
            continue
        fato = Fato(enunciado=str(f.get("enunciado") or "").strip(),
                    trecho=str(f.get("trecho") or "").strip(),
                    documento=str(f.get("documento") or "").strip(),
                    folha=str(f.get("folha") or "").strip(),
                    grau=str(f.get("grau") or "C").strip().upper()[:1] or "C")
        if not fato.enunciado:
            continue
        if fonte_documental:
            anc = ancorar(fato.trecho, fonte_documental)
            fato.ancorado, fato.similaridade = anc["ancorado"], anc["similaridade"]
            if not anc["ancorado"]:
                fato.motivo_descarte = anc["motivo"]
                descartados.append({"enunciado": fato.enunciado, "trecho": fato.trecho[:120],
                                    "motivo": anc["motivo"]})
                continue
        fatos.append(fato)

    problemas: list[str] = []
    if not norma["ok"]:
        problemas.append(f"premissa maior: {norma['motivo']}")
    if not str(d.get("norma_verbatim") or "").strip():
        problemas.append("norma sem texto verbatim — paráfrase de norma não fundamenta")
    if not fatos:
        problemas.append("nenhum fato com trecho ancorado — não há premissa menor")
    if not str(d.get("contra_argumento") or "").strip():
        problemas.append("sem contra-argumento — subsunção que não enfrenta a defesa é acusação")
    if not str(d.get("subsuncao") or "").strip():
        problemas.append("sem o passo de subsunção — a ponte entre norma e fato não foi escrita")

    melhor_grau = max((f.grau for f in fatos), key=lambda g: _FORCA.get(g, 0), default="D")
    aferivel = not problemas

    s = Subsuncao(
        norma_dispositivo=str(d.get("norma_dispositivo") or ""),
        norma_verbatim=str(d.get("norma_verbatim") or ""),
        premissa_maior=str(d.get("premissa_maior") or ""),
        fatos=fatos,
        subsuncao=str(d.get("subsuncao") or ""),
        contra_argumento=str(d.get("contra_argumento") or ""),
        conclusao_enquadra=(bool(d.get("conclusao_enquadra")) if aferivel else None),
        ressalva=("Qualificação hipotética para orientar diligência; a tipificação é do órgão "
                  "competente e os elementos não podem ser presumidos "
                  "(Lei 8.429/1992, art. 17-C, I)."),
    )
    return {
        "subsuncao": s,
        "aferivel": aferivel,
        "problemas": problemas,
        "descartados": descartados,
        "norma_verificada": norma,
        "grau_maximo": melhor_grau if fatos else None,
        "n_fatos": len(fatos),
        "conclusao": ("nao_aferivel" if not aferivel else
                      "enquadra" if s.conclusao_enquadra else "nao_enquadra"),
        "fonte_conferida": bool(fonte_documental),
    }


def render_texto(r: dict) -> str:
    """A fundamentação escrita pelo CÓDIGO a partir da estrutura — não pela prosa do modelo."""
    if not r.get("aferivel"):
        return ("**Subsunção não aferível.** " + "; ".join(r.get("problemas") or []) +
                ("\n\nFatos descartados por citação não localizada na fonte: "
                 + "; ".join(f"{x['enunciado']} ({x['motivo']})" for x in r["descartados"])
                 if r.get("descartados") else ""))
    s: Subsuncao = r["subsuncao"]
    linhas = [
        f"**Norma aplicável.** {s.norma_dispositivo} — «{s.norma_verbatim}»",
        f"**O que a norma exige.** {s.premissa_maior}",
        "**Fatos apurados.**",
    ]
    for f in s.fatos:
        origem = f"[{f.documento}" + (f", fl. {f.folha}" if f.folha else "") + "]" if f.documento \
            else "[fonte não identificada]"
        sim = f" (similaridade {f.similaridade:.2f})" if f.similaridade is not None else ""
        linhas.append(f"  · {f.enunciado} — «{f.trecho}» {origem}, grau {f.grau}{sim}")
    linhas += [
        f"**Subsunção.** {s.subsuncao}",
        f"**Contra-argumento considerado.** {s.contra_argumento}",
        f"**Conclusão.** {'A conduta se enquadra' if s.conclusao_enquadra else 'A conduta NÃO se enquadra'} "
        f"na hipótese normativa, no grau máximo de evidência {r['grau_maximo']}.",
        f"_{s.ressalva}_",
    ]
    if r.get("descartados"):
        linhas.append(f"_Nota: {len(r['descartados'])} fato(s) alegado(s) foram descartados por "
                      f"citarem trecho não localizado no documento._")
    if not r.get("fonte_conferida"):
        linhas.append("_Nota: as citações NÃO foram conferidas contra o documento (fonte não "
                      "fornecida) — conferir antes de uso em peça formal._")
    return "\n\n".join(linhas)


SCHEMA_PROMPT = (
    'Responda SOMENTE um objeto JSON com esta estrutura:\n'
    '{"norma_dispositivo":"<lei, artigo, inciso OU súmula/acórdão>",'
    '"norma_verbatim":"<texto LITERAL da norma; não parafraseie>",'
    '"premissa_maior":"<o que a norma exige ou veda, em 1 frase>",'
    '"fatos":[{"enunciado":"<o fato>","trecho":"<citação LITERAL do documento>",'
    '"documento":"<identificação do doc>","folha":"<nº da folha, se houver>",'
    '"grau":"A|B|C"}],'
    '"subsuncao":"<por que o fato cai ou não cai na hipótese>",'
    '"contra_argumento":"<a MELHOR tese da defesa — obrigatório>",'
    '"conclusao_enquadra":true|false}\n'
    'REGRAS: (1) fato sem trecho literal do documento será DESCARTADO; (2) sem '
    'contra-argumento a resposta é inválida; (3) nunca invente norma, número ou citação.'
)
