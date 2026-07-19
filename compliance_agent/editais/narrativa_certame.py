# -*- coding: utf-8 -*-
"""Síntese narrativa de nível certame — LLM com rubrica-judge sobre o Índice (Task 4.4 da F4).

Método (docs/BENCHMARKS-EXTERNOS.md §3.4): a regra determinística responde "violou?"
(`indice_certame.calcular`); o LLM responde "quão anômalo NO CONTEXTO?" via rubrica de
6 dimensões 0-4 (âncoras 0/2/4 no prompt). Salvaguardas:
  • CITAÇÃO VERBATIM obrigatória por dimensão — nota sem trecho literal → nota None
    ("não avaliável"; lição do Hermes aterrado: LLM sem âncora textual alucina).
  • Saída JSON ESTRITA; malformado → parse honesto (None) → TEMPLATE DETERMINÍSTICO
    montado dos drivers do índice. A narrativa NUNCA quebra nem depende de LLM vivo;
    o campo `origem` ('llm' | 'template') marca o caminho.
  • α ≤ 0,3 com teto 1,0 sobre o score NORMALIZADO 0-1:
    `score_final = min(1.0, score_det + 0.3 × média_rubrica/4)` — o LLM realça, nunca
    sozinho eleva caso limpo a crítico (auditabilidade perante o TC).
  • Prompt < 8000 chars (payload maior colapsa modelos 8B — lição conhecida); o recorte
    prioriza os DRIVERS do índice e trechos de edital_clausula/ata_documento.
  • Reprodutibilidade: `prompt_versao` + `rubrica_crua` (texto bruto do LLM) no dict.

PERSISTÊNCIA (decisão documentada): coluna `narrativa_json` em `certame_indice` via
ALTER TABLE aditivo NESTE módulo (`narrar_e_persistir`) — não mexe no DDL do 4.3;
segue o padrão de migração aditiva de `editais/db.init_schema` (try/except no ALTER).
"""
from __future__ import annotations

import json
import sqlite3

from compliance_agent.direcionamento_cerebro import _parse_json  # parse tolerante a cercas ```json
from compliance_agent.editais.indice_certame import _conectar_ro, calcular, garantir_tabela
from compliance_agent.emendas.db import conectar

PROMPT_VERSAO = "v1"
ALPHA = 0.3                # §3.4: α ≤ 0,3 — realce máximo do LLM sobre o score determinístico
LIMITE_PROMPT = 8000       # modelos 8B colapsam acima disso (lição instruir-ias-fracas)
TRECHO_MAX = 700           # recorte por trecho de evidência
MAX_TRECHOS = 8

DIMENSOES = ("d1", "d2", "d3", "d4", "d5", "d6")
ROTULOS = {
    "d1": "restritividade contextual",
    "d2": "qualidade da motivação",
    "d3": "coerência objeto-quantidade-preço",
    "d4": "narrativa da disputa",
    "d5": "relação comprador-fornecedor",
    "d6": "integridade documental",
}

# Norma de referência — mesmos referentes dos testes finalísticos executáveis
# (compliance_agent/editais/teste_finalistico.py) e do _PARAMS_AUDITOR do cérebro.
_NORMA = (
    "## NORMA DE REFERÊNCIA (avalie DESVIOS em relação a ela)\n"
    "- Lei 14.133/2021: art. 9º I 'c' (vedado frustrar competitividade com exigência "
    "impertinente); art. 41 I (marca só com justificativa técnica ou 'ou equivalente' — "
    "Súmula TCU 270); art. 58 §1º (garantia de proposta ≤ 1% do estimado); arts. 74/75 "
    "(inexigibilidade/dispensa exigem motivação nos autos); art. 125 (acréscimo contratual ≤ 25%).\n"
    "- Súmula TCU 263: quantitativo de atestado limitado a 50% do objeto; vedação de somatório "
    "de atestados sem justificativa é restritiva.\n"
    "- Súmula TCU 275: capital social/patrimônio líquido mínimo ≤ 10% do valor estimado.\n"
    "- Ausência de motivação técnica nos autos ⇒ o ônus de justificar é da Administração."
)

_ANCORAS = (
    "## RUBRICA — 6 dimensões, nota 0-4 (âncoras 0/2/4)\n"
    "D1 restritividade contextual: 0=exigências usuais e proporcionais ao objeto · "
    "2=exigência atípica sem motivação visível · 4=combinação de exigências que afunila para um fornecedor.\n"
    "D2 qualidade da motivação: 0=motivação específica, com números/estudos · "
    "2=motivação genérica/copiada · 4=ausente ou circular ('justifica-se pela necessidade').\n"
    "D3 coerência objeto-quantidade-preço: 0=quantidades e preços compatíveis entre si · "
    "2=desproporção pontual não explicada · 4=incoerência grave (quantitativo/valor sem lastro no objeto).\n"
    "D4 narrativa da disputa: 0=disputa real (vários proponentes, lances independentes) · "
    "2=disputa protocolar (poucos lances, desistências) · 4=roteiro de cobertura "
    "(desclassificações em cascata, lances coordenados, vencedor que sobe após quedas).\n"
    "D5 relação comprador-fornecedor: 0=sem vínculo relevante · 2=recorrência alta não explicada · "
    "4=indício de captura (mesmo fornecedor sempre, sanção/fantasma ignorados pelo órgão).\n"
    "D6 integridade documental: 0=documentação completa e consistente · 2=lacunas pontuais · "
    "4=documentos ausentes/contraditórios (datas impossíveis, ata sem proponentes, registro PNCP incompleto)."
)

_SAIDA = (
    "## SAÍDA — JSON ESTRITO, sem texto fora do JSON\n"
    '{"d1":{"nota":0,"citacao":"trecho LITERAL copiado das EVIDÊNCIAS acima","justificativa":"1-2 frases"},'
    '..."d6":{...} ou null,"tese":"1-3 frases: o padrão do certame, citando os drivers",'
    '"ressalvas":["..."]}\n'
    "REGRAS: dimensão SEM trecho literal das evidências fornecidas → null (não avaliável) — "
    "NUNCA invente citação nem avalie sem âncora textual. Indício ≠ acusação (presunção de "
    "legitimidade); descreva o MECANISMO do desvio, não conclua fraude."
)


# ───────────────────────────────────── evidências ─────────────────────────────────────
def _q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list:
    """Tabela ausente = fonte não coletada = lista vazia (honesto), nunca crash."""
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def buscar_evidencias(certame: str, db_path=None) -> dict:
    """Trechos de evidência textual do certame (mode=ro): cláusulas do edital e atas."""
    conn = _conectar_ro(db_path)
    try:
        clausulas = [{"subtipo": r[0] or "clausula", "texto": r[1]}
                     for r in _q(conn, "SELECT subtipo, texto FROM edital_clausula "
                                       "WHERE numero_controle_pncp=? AND texto IS NOT NULL",
                                 (certame,)) if (r[1] or "").strip()]
        atas = [{"titulo": r[0] or "ata", "texto": r[1]}
                for r in _q(conn, "SELECT titulo, texto FROM ata_documento "
                                  "WHERE certame=? AND texto IS NOT NULL", (certame,))
                if (r[1] or "").strip()]
    finally:
        conn.close()
    return {"clausulas": clausulas, "atas": atas}


# ───────────────────────────────────── prompt ─────────────────────────────────────
def montar_prompt(indice: dict, evidencias: dict) -> str:
    """Prompt do judge: norma + índice determinístico (drivers primeiro) + trechos de
    evidência recortados + rubrica com âncoras + schema de saída. Total < 8000 chars."""
    dr = indice.get("drivers") or []
    linhas_drivers = [f"- {d['familia']}/{d['flag']} (valor {d['valor']}): {d['evidencia']}"
                      for d in dr] or ["- (nenhum driver ≥ 0,5 — avalie pelo contexto das evidências)"]
    cabeca = (
        "Você é auditor de controle externo (TCE-RJ). A regra determinística já respondeu "
        "'violou?'; sua tarefa é responder 'QUÃO ANÔMALO no contexto?' — desvios em relação "
        "à norma abaixo, SEMPRE com citação literal das evidências.\n\n"
        + _NORMA + "\n\n"
        "## ÍNDICE DETERMINÍSTICO (calculado por regras; não recalcule)\n"
        f"Certame {indice['certame']} · score {indice['score']}/100 · faixa {indice['faixa']} · "
        f"confiança {indice['confianca']} · valor total R$ {indice.get('valor_total', 0):,.2f}\n"
        "Drivers:\n" + "\n".join(linhas_drivers)
    )
    rodape = "\n\n" + _ANCORAS + "\n\n" + _SAIDA
    # Recorte das evidências no orçamento restante (prioridade: cláusulas, depois atas)
    orcamento = LIMITE_PROMPT - len(cabeca) - len(rodape) - 60  # 60 = título da seção + folga
    trechos: list[str] = []
    fontes = ([(f"CLÁUSULA {c['subtipo']}", c["texto"]) for c in evidencias.get("clausulas") or []]
              + [(f"ATA {a['titulo']}", a["texto"]) for a in evidencias.get("atas") or []])
    for rotulo, texto in fontes[:MAX_TRECHOS]:
        t = f"[{rotulo}] {' '.join(str(texto).split())[:TRECHO_MAX]}"
        if orcamento - len(t) - 1 < 0:
            break
        trechos.append(t)
        orcamento -= len(t) + 1
    corpo = ("\n\n## EVIDÊNCIAS (trechos literais — cite VERBATIM daqui)\n"
             + ("\n".join(trechos) if trechos else "(sem texto de edital/ata coletado — "
                "avalie apenas o que as evidências dos drivers permitirem)"))
    return cabeca + corpo + rodape


# ───────────────────────────────────── parse ─────────────────────────────────────
def parse_rubrica(txt: str) -> dict | None:
    """JSON estrito → {d1..d6: {nota, citacao, justificativa} | None, tese, ressalvas}.
    Malformado/sem tese → None (parse honesto). Nota sem citação NÃO-VAZIA → nota None
    (não avaliável — citação verbatim é obrigatória, §3.4)."""
    js = _parse_json(txt or "")
    if not isinstance(js, dict):
        return None
    tese = js.get("tese")
    if not isinstance(tese, str) or not tese.strip():
        return None
    out: dict = {"tese": tese.strip()}
    for d in DIMENSOES:
        v = js.get(d)
        if not isinstance(v, dict):
            out[d] = None
            continue
        nota = v.get("nota")
        citacao = str(v.get("citacao") or "").strip()
        if not isinstance(nota, (int, float)) or isinstance(nota, bool) or not 0 <= nota <= 4:
            nota = None
        if nota is not None and not citacao:
            nota = None  # nota sem trecho literal = não avaliável, nunca nota
        out[d] = {"nota": nota, "citacao": citacao,
                  "justificativa": str(v.get("justificativa") or "").strip()}
    ressalvas = js.get("ressalvas")
    out["ressalvas"] = [str(r) for r in ressalvas] if isinstance(ressalvas, list) else []
    return out


# ───────────────────────────────────── narrativa ─────────────────────────────────────
def _base(certame: str, indice: dict) -> dict:
    return {"certame": certame, "faixa": indice["faixa"], "confianca": indice["confianca"],
            "score_det": round(indice["score"] / 100.0, 4), "drivers": indice["drivers"],
            "prompt_versao": PROMPT_VERSAO}


def _template(certame: str, indice: dict) -> dict:
    """Fallback determinístico: tese montada dos drivers — nunca quebra, nunca inventa."""
    fams: list[str] = []
    for d in indice["drivers"]:  # já vem ordenado por valor desc
        if d["familia"] not in fams:
            fams.append(d["familia"])
    tese = (f"Certame {certame}: faixa {indice['faixa']} (score {indice['score']}/100, "
            f"confiança {indice['confianca']}) por "
            + (", ".join(fams) if fams else "nenhum driver ≥ 0,5")
            + "; evidências: "
            + ("; ".join(d["evidencia"] for d in indice["drivers"][:4])
               if indice["drivers"] else "sem flag dominante nas famílias apuráveis") + ".")
    paragrafo = (tese + f" Matriz S×V: {indice['matriz_sv']['nivel']} "
                 f"(produto {indice['matriz_sv']['produto']}/25) — {indice['matriz_sv']['acao']}. "
                 "Indício de priorização interna, não acusação (presunção de legitimidade).")
    return {**_base(certame, indice), "tese": tese, "paragrafo": paragrafo, "rubrica": None,
            "rubrica_crua": None, "alpha_aplicado": 0.0,
            "score_final": round(indice["score"] / 100.0, 4), "citacoes": [],
            "origem": "template"}


def _narrativa_llm(certame: str, indice: dict, rubrica: dict, crua: str) -> dict:
    notas = [rubrica[d]["nota"] for d in DIMENSOES
             if rubrica[d] is not None and rubrica[d]["nota"] is not None]
    media = sum(notas) / len(notas) if notas else None
    score_det = indice["score"] / 100.0
    alpha = ALPHA if notas else 0.0
    score_final = min(1.0, score_det + alpha * (media / 4.0)) if notas else score_det
    # tese ATERRADA: se o LLM não citar nenhum driver determinístico, ancoramos nós
    tese = rubrica["tese"]
    fams = []
    for d in indice["drivers"]:
        if d["familia"] not in fams:
            fams.append(d["familia"])
    if fams and not any(f in tese.lower() for f in fams):
        tese += f" [Drivers determinísticos: {', '.join(fams)}.]"
    citacoes = [{"dimensao": d, "citacao": rubrica[d]["citacao"]} for d in DIMENSOES
                if rubrica[d] is not None and rubrica[d]["nota"] is not None]
    partes = [tese]
    for d in DIMENSOES:
        v = rubrica[d]
        if v is None or v["nota"] is None:
            continue
        partes.append(f"D{d[1]} ({ROTULOS[d]}): nota {v['nota']}/4 — {v['justificativa']} "
                      f"(trecho: “{v['citacao'][:200]}”)")
    if rubrica["ressalvas"]:
        partes.append("Ressalvas: " + "; ".join(rubrica["ressalvas"]))
    return {**_base(certame, indice), "tese": tese, "paragrafo": " ".join(partes),
            "rubrica": rubrica, "rubrica_crua": crua, "alpha_aplicado": alpha,
            "score_final": round(score_final, 4), "citacoes": citacoes, "origem": "llm"}


def narrar(certame: str, db_path=None, gerar=None) -> dict:
    """Índice (calcular) + evidências (ro) + LLM judge → narrativa. `gerar` injetável
    (callable prompt→str); default = direcionamento_cerebro.gerar_sync (resolvido no
    momento da chamada, para monkeypatch/teste). LLM indisponível ou parse falho →
    template determinístico — NUNCA levanta exceção por causa do LLM."""
    indice = calcular(certame, db_path)
    evidencias = buscar_evidencias(certame, db_path)
    prompt = montar_prompt(indice, evidencias)
    fn = gerar
    if fn is None:
        try:
            from compliance_agent import direcionamento_cerebro as _dc
            fn = _dc.gerar_sync
        except Exception:  # noqa: BLE001 — cérebro indisponível: fallback honesto
            fn = None
    crua = None
    if fn is not None:
        try:
            crua = fn(prompt)
        except Exception:  # noqa: BLE001 — LLM offline/cooldown/timeout: fallback
            crua = None
    rubrica = parse_rubrica(crua) if crua else None
    if rubrica is None:
        return _template(certame, indice)
    return _narrativa_llm(certame, indice, rubrica, crua)


# ───────────────────────────────────── persistência ─────────────────────────────────────
def garantir_coluna(conn: sqlite3.Connection) -> None:
    """`certame_indice.narrativa_json` — ALTER aditivo idempotente (padrão db.init_schema)."""
    garantir_tabela(conn)
    try:
        conn.execute("ALTER TABLE certame_indice ADD COLUMN narrativa_json TEXT")
    except sqlite3.OperationalError:
        pass  # coluna já existe


def narrar_e_persistir(certame: str, db_path=None, gerar=None) -> dict:
    """narrar() + UPDATE de `narrativa_json` no certame (só a narrativa; o score do índice
    é persistido por `indice_certame.calcular_e_persistir`, não aqui — não clobber)."""
    r = narrar(certame, db_path, gerar=gerar)
    conn = conectar(db_path)
    try:
        garantir_coluna(conn)
        conn.execute("INSERT OR IGNORE INTO certame_indice (certame) VALUES (?)", (certame,))
        conn.execute("UPDATE certame_indice SET narrativa_json=? WHERE certame=?",
                     (json.dumps(r, ensure_ascii=False), certame))
        conn.commit()
    finally:
        conn.close()
    return r
