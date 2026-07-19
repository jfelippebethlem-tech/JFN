# -*- coding: utf-8 -*-
"""FICHA de fiscalização de 7 seções — GENÉRICA por superfície (editais|contratos|emendas|pcrj).

Generaliza o formato-representação do relatorio_direcionamento (antes exclusivo de editais):

    I.   Identificação          IV. Fundamentação jurídica     VI.  Beneficiário
    II.  Objeto do achado       V.  Parecer do colegiado       VII. Conclusão (matriz S×V)
    III. Análise comparativa

Cada superfície ADAPTA seus achados para o dict normalizado `d` (ver ficha_html) e, quando
couber, convoca o colegiado de 5 lentes via `deliberar_achados` (enxame — o mesmo motor que
contratos já usa). Honestidade em toda parte: comparativa inexistente ≠ zero; colegiado não
convocado é declarado; sem votos a verossimilhança da matriz fica no teto 3.

Custo de LLM SOB CONTROLE (regra §4.1): o colegiado só é convocado para achados com
risco ≥ `limiar` e no máximo `cap` por corrida; a memória do enxame evita re-acusar refutado.
"""
from __future__ import annotations

import html as _h

from compliance_agent.knowledge.jurisprudencia import buscar_acordaos, obter_sumula

_LENTES_ORDEM = ["proporcionalidade", "jurisprudencia", "competicao", "refutador", "beneficiario"]
_LENTE_ROTULO = {
    "proporcionalidade": "Proporcionalidade",
    "jurisprudencia": "Jurisprudência",
    "competicao": "Impacto na competição/economicidade",
    "beneficiario": "Beneficiário / captura",
}
_REFUTADOR_ROTULO = {"editais": "Defesa do edital (refutador)", "contratos": "Defesa do contrato (refutador)",
                     "emendas": "Defesa da emenda (refutador)", "pcrj": "Defesa do ato (refutador)"}


def _esc(s) -> str:
    return _h.escape(str(s if s is not None else ""))


# ── V. colegiado ─────────────────────────────────────────────────────────────

def painel_votos(votos: dict, superficie: str) -> str:
    if not votos:
        return ("<p class='ind'>Colegiado não convocado para este achado (abaixo do limiar de "
                "deliberação ou fora do teto de custo da corrida) — o risco exibido é o do "
                "detector determinístico. INDISPONÍVEL ≠ 0.</p>")
    linhas = []
    for lente in _LENTES_ORDEM:
        v = votos.get(lente) or {}
        voto = v.get("voto")
        if voto is None:
            badge = "<span class='ind'>INDISPONÍVEL</span>"
        else:
            cls = "alto" if voto >= 7 else "medio" if voto >= 4 else "baixo"
            badge = f"<span class='voto {cls}'>{voto}/10</span>"
        rotulo = (_REFUTADOR_ROTULO.get(superficie, "Refutador") if lente == "refutador"
                  else _LENTE_ROTULO[lente])
        gate = " <span class='gate'>· voto-gate</span>" if lente == "refutador" else ""
        cit = f"<div class='cit'>{_esc(v.get('citacao') or '')}</div>" if v.get("citacao") else ""
        linhas.append(f"<tr><td class='lente'>{_esc(rotulo)}{gate}</td><td class='vc'>{badge}</td>"
                      f"<td>{_esc(v.get('justificativa') or '')}{cit}</td></tr>")
    nota = ("<p class='nota'>O <b>refutador</b> é voto-gate: se defende o ato (voto ≤3), o colegiado "
            "rebaixa o escore (presunção de legitimidade). Voto INDISPONÍVEL não conta (≠ 0). "
            "Escore final = mediana dos votos válidos.</p>")
    return ("<table class='colegiado'><tr><th>Lente</th><th>Voto</th><th>Fundamento</th></tr>"
            f"{''.join(linhas)}</table>{nota}")


# ── VII. matriz S×V genérica ─────────────────────────────────────────────────

def matriz_risco(risco_det: int, score_colegiado: int | None, comparativa_ok: bool,
                 teste_violado: bool = False) -> str:
    """Severidade = dano potencial (risco do detector determinístico; +1 se teste objetivo
    confirmou violação). Verossimilhança = robustez do indício (escore do colegiado; sem
    colegiado ou sem base comparativa, teto 3 — honestidade sobre o que não foi corroborado)."""
    sev = 2 + (1 if risco_det >= 5 else 0) + (1 if risco_det >= 8 else 0)
    if teste_violado:
        sev = min(5, sev + 1)
    if score_colegiado is not None:
        ver = 5 if score_colegiado >= 9 else 4 if score_colegiado >= 7 else 3 if score_colegiado >= 4 else 2
    else:
        ver = 3 if risco_det >= 8 else 2
    if not comparativa_ok:
        ver = min(ver, 3)
    prod = sev * ver
    nivel, acao = (("CRÍTICO 🔴", "representação com pedido de medida cautelar") if prod >= 16 else
                   ("ALTO 🟠", "diligência prioritária; minuta de representação preparada") if prod >= 10 else
                   ("MÉDIO 🟡", "diligência ordinária; reavaliar com a resposta do órgão") if prod >= 5 else
                   ("BAIXO 🟢", "monitoramento; sem medida imediata"))
    origem_ver = "colegiado" if score_colegiado is not None else "detector (colegiado não convocado)"
    return ("<div class='matriz'><b>Matriz de risco (Severidade × Verossimilhança, escala 1–5 cada; "
            f"produto 1–25):</b> severidade <b>{sev}/5</b> × verossimilhança <b>{ver}/5</b> "
            f"(fonte: {origem_ver}) = <b>{prod}/25 — {nivel}</b>. Ação recomendada: {acao}. "
            "<span class='nota'>Régua: 1–4 baixo · 5–9 médio · 10–15 alto · 16–25 crítico.</span></div>")


# ── IV. fundamentação genérica ───────────────────────────────────────────────

def fundamentacao_html(dispositivos: list[str] | None = None, sumulas: list[str] | None = None,
                       irregularidade: str = "", rag: str = "", teste_exec: dict | None = None,
                       redline: str = "") -> str:
    partes = []
    if teste_exec and teste_exec.get("status") != "nao_aferivel":
        cls = "violado" if teste_exec["status"] == "violado" else "conforme"
        rot = ("Aferição objetiva: exigência EXCEDE o teto legal" if cls == "violado"
               else "Aferição objetiva: dentro do teto legal")
        partes.append(f"<p class='teste-exec {cls}'><b>{rot}.</b> {_esc(teste_exec['motivo'])}.</p>")
    for nome in (sumulas or []):
        s = obter_sumula(nome)
        if s:
            partes.append(f"<div class='sumula'><b>{_esc(s['numero'])} ({_esc(s['orgao'])}) — "
                          f"{_esc(s['tema'])}.</b> <i>“{_esc(s['texto'])}”</i></div>")
        else:
            partes.append(f"<div class='sumula'><b>{_esc(nome)}.</b></div>")
    if irregularidade:
        for ac in buscar_acordaos(tipo_irregularidade=irregularidade)[:2]:
            partes.append(f"<div class='acordao'><b>{_esc(ac.orgao)} — {_esc(ac.numero)}.</b> "
                          f"{_esc(ac.tema)}. <i>{_esc(ac.ementa)}</i></div>")
    if dispositivos:
        partes.append(f"<p><b>Dispositivos legais:</b> {_esc('; '.join(dispositivos))}.</p>")
    if rag:
        partes.append(f"<div class='acordao'><b>Jurisprudência (RAG):</b> <i>{_esc(rag[:400])}</i></div>")
    if redline:
        partes.append("<div class='redline'><b>Redação/conduta conforme sugerida</b> (parâmetro para a "
                      f"diligência): <i>“{_esc(redline)}”</i></div>")
    return "".join(partes) or ("<p class='ind'>Sem âncora jurisprudencial mapeada — a análise repousa "
                               "no colegiado e nos princípios do art. 5º da Lei 14.133/2021.</p>")


# ── a ficha ──────────────────────────────────────────────────────────────────

def ficha_html(n: int, d: dict) -> str:
    """Renderiza a ficha de 7 seções a partir do dict normalizado:
    {titulo, superficie, ident:[(rotulo, html)], objeto_html, comparativa_html|None,
     fundamentacao_html, votos:{}, score_colegiado|None, risco_det, beneficiario_html,
     conclusao_extra_html?, teste_violado?}  — chaves ausentes degradam honesto."""
    ident = "".join(f"<tr><th class='k'>{_esc(k)}</th><td>{v}</td></tr>" for k, v in d.get("ident", []))
    comparativa = d.get("comparativa_html") or (
        "<p class='ind'>Base de pares indisponível para este tipo de achado — a comparação é a "
        "régua determinística do detector (limiares explícitos na metodologia). INDISPONÍVEL ≠ 0.</p>")
    beneficiario = d.get("beneficiario_html") or (
        "<p class='ind'>Beneficiário não identificável nesta base para este achado — o indício "
        "repousa no ato, não no favorecimento a pessoa determinada.</p>")
    score = d.get("score_colegiado")
    verd = d.get("veredito") or ("—" if score is None else str(score))
    concl = (matriz_risco(d.get("risco_det", 0), score, bool(d.get("comparativa_html")),
                          bool(d.get("teste_violado")))
             + f"<p class='conclusao {'extremo' if (score or d.get('risco_det', 0)) >= 9 else 'alto' if (score or d.get('risco_det', 0)) >= 7 else 'medio'}'>"
               f"<b>{'Veredito do colegiado: ' + _esc(verd) + f' — escore {score}/10.' if score is not None else 'Risco do detector determinístico: ' + str(d.get('risco_det', 0)) + '/10.'}</b> "
               "<i>Indício não é acusação; presume-se a legitimidade do ato administrativo até prova em contrário.</i></p>"
             + (d.get("conclusao_extra_html") or ""))
    return "".join([
        "<div class='ficha'>",
        f"<h3>Achado nº {n} — {_esc(d.get('titulo', ''))}</h3>",
        "<h4>I. Identificação</h4>", f"<table class='ident'>{ident}</table>",
        "<h4>II. Objeto do achado (íntegra)</h4>", d.get("objeto_html", ""),
        "<h4>III. Análise comparativa</h4>", comparativa,
        "<h4>IV. Fundamentação jurídica</h4>", d.get("fundamentacao_html", fundamentacao_html()),
        "<h4>V. Parecer do colegiado (5 lentes)</h4>", painel_votos(d.get("votos") or {}, d.get("superficie", "")),
        "<h4>VI. Beneficiário</h4>", beneficiario,
        "<h4>VII. Conclusão</h4>", concl,
        "</div>",
    ])


# ── convocação do colegiado por superfície (gate de custo) ───────────────────

def _avaliar(dossie: dict, gerar=None) -> dict:  # indireção p/ teste (monkeypatch)
    from compliance_agent.enxame import orquestrador
    return orquestrador.avaliar(dossie, gerar=gerar)


def deliberar_achados(con, achados: list[dict], superficie: str,
                      limiar: int = 7, cap: int = 8, gerar=None) -> int:
    """Convoca o colegiado para os `cap` achados de maior risco com risco ≥ limiar, anotando
    IN PLACE: votos / score_colegiado / veredito. Retorna quantos foram deliberados.
    Reusa a memória do enxame (não re-acusar refutado) e registra o veredito de volta."""
    from compliance_agent.enxame import memoria
    candidatos = sorted((a for a in achados if (a.get("risco") or 0) >= limiar),
                        key=lambda a: -(a.get("risco") or 0))[:cap]
    n = 0
    for a in candidatos:
        ev = a.get("evidencias") or {}
        alvo = str(ev.get("cnpj") or ev.get("doc") or ev.get("fornecedor") or ev.get("credor") or "")
        dossie = {
            "objeto": a.get("titulo", ""),
            "clausula": {"subtipo": a.get("detector", ""), "texto": a.get("descricao", ""),
                         "sumula": ""},
            "irmaos_sem_clausula": [],
            "vencedor_doc": alvo,
            "sinais_beneficiario": ev.get("sinais") or [],
            "memoria_ctx": memoria.contexto_memoria(con, f"{superficie}_{a.get('detector', '')}", alvo),
        }
        try:
            r = _avaliar(dossie, gerar=gerar)
        except Exception:  # noqa: BLE001 — LLM fora do ar: ficha sai honesta, sem votos
            continue
        if r.get("veredito") == "nao_avaliavel":
            continue
        a["votos"] = r.get("votos", {})
        a["score_colegiado"] = r.get("score_final")
        a["veredito"] = r.get("veredito")
        try:
            memoria.registrar_veredito(con, f"{superficie}_{a.get('detector', '')}", alvo[:60],
                                       r.get("veredito", ""), r.get("score_final") or 0)
        except Exception:  # noqa: BLE001 — memória é best-effort
            pass
        n += 1
    return n
