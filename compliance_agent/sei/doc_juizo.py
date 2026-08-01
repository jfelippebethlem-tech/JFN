# -*- coding: utf-8 -*-
"""doc_juizo — o juízo de CADA DESPACHO QUE IMPORTA, com rubrica fechada e frota grátis.

Camada 3 do processo_360 (`--com-llm`): seleciona os documentos decisórios do processo
(justificativa de dispensa/emergência > parecer > homologação > despacho > atesto), lê o
texto de cada um e faz UMA pergunta FECHADA por documento — o modelo escolhe um nível
nomeado e CITA o trecho literal; sem trecho verificável no texto, o juízo vira null
(doutrina agregacao.md §1.1: IA fraca acerta com tarefa fechada; o pior caso é
`nao_avaliavel`, nunca invenção).

LLM: `camada_triagem.gerar_triagem()` — a cadeia GRÁTIS da casa (Ollama/Groq/OpenRouter
:free/Cerebras/Gemini/Cloudflare) com kill-switch em arquivo, teto diário e uso auditável.
Grau: `grau_flag` com origem="llm" — teto C, sempre. Cache: `doc_veredito` por hash
(reavaliar processo não re-paga documento inalterado). Rubrica crítica (emergência) tem
SEGUNDO voto independente; divergência >1 nível rebaixa para o menor (adversarial barato).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

from compliance_agent.editais.flags import grau_flag
from compliance_agent.llm.json_resposta import parse_json_llm

TETO_DEFAULT = int(os.environ.get("JFN_360_TETO_DOCS", "25"))
# v2 (2026-08-01): despacho de mero expediente = escala 2 (função legítima), não 3 — a v1
# inflava "74% problemáticos" contando tramitação normal; escala 3 agora é DECISÃO sem
# motivação ou parecer que se ESQUIVA do mérito submetido. Vereditos v1 ficam no banco
# (UNIQUE inclui a versão) para auditoria; re-julgamento é progressivo e grátis.
RUBRICA_VERSAO = "2"
_DB = Path(__file__).resolve().parents[2] / "data" / "compliance.db"

_PRIORIDADE = ("contratacao_direta", "parecer", "homologacao", "adjudicacao",
               "despacho", "aceite", "medicao")

# escala: 1 = regular · 2 = frágil · 3 = viciado (a AUSÊNCIA do elemento pontua MAIS que a
# versão fraca dele — regra P5 do vault). O modelo NUNCA vê número de score, só níveis nomeados.
RUBRICAS: dict[str, str] = {
    "contratacao_direta": (
        "Este documento justifica uma contratação direta (dispensa/inexigibilidade/emergência). "
        "Classifique o NEXO da justificativa: 1 = risco concreto documentado (cita fato, data e "
        "documento que o comprova); 2 = risco genérico apenas alegado (sem fato datado nem prova); "
        "3 = sem nexo — não há justificativa real, ou a 'emergência' decorre de desídia previsível "
        "(vencimento conhecido, demanda sazonal, contrato que se sabia expirar)."),
    "parecer": (
        "Este documento é um parecer/manifestação jurídica. Primeiro identifique O QUE foi "
        "submetido ao parecerista (a consulta). Classifique: 1 = conclusivo sobre o que lhe foi "
        "submetido (favorável OU contrário, com fundamento); 2 = favorável COM ressalva/condição "
        "substantiva (cite-a no trecho); 3 = ESQUIVA-SE do mérito que lhe foi submetido (delega "
        "de volta, responde outra coisa, ou 'não cabe analisar' o próprio objeto da consulta). "
        "Se o documento não é parecer de mérito (certidão, checklist informativo), retorne null."),
    "homologacao": (
        "Este documento homologa/adjudica/ratifica. Classifique a MOTIVAÇÃO: 1 = menciona e "
        "acolhe expressamente o parecer jurídico/etapas anteriores; 2 = decide sem mencionar "
        "o parecer nem enfrentar ressalvas; 3 = decide CONTRARIANDO ressalva/parecer sem motivar."),
    "despacho": (
        "Este é um despacho. Classifique: 1 = decide E motiva (enfrenta o que os autos "
        "apontam); 2 = mero encaminhamento/expediente (função legítima de tramitação — NÃO é "
        "vício); 3 = usa fórmula DECISÓRIA (autorizo/aprovo/homologo/ratifico) SEM motivação, "
        "ou decide contrariando os autos sem enfrentá-los. Encaminhar não é decidir: só é "
        "escala 3 se o despacho DECIDE sem motivar."),
    "aceite": (
        "Este documento atesta recebimento/execução. Classifique a ESPECIFICIDADE do atesto: "
        "1 = específico (diz O QUE foi entregue, quantidade/medição e data); 2 = genérico "
        "('de acordo', 'a contento', sem dizer o quê); 3 = incoerente (data anterior à "
        "medição, objeto diferente do contratado, ou quantidade divergente)."),
}
RUBRICAS["adjudicacao"] = RUBRICAS["homologacao"]
RUBRICAS["medicao"] = RUBRICAS["aceite"]

_SISTEMA = (
    "Você audita documentos de processos administrativos (controle externo, RJ). Responda "
    "SOMENTE JSON: {\"escala\": <int da rubrica ou null>, \"trecho_literal\": \"<cópia EXATA "
    "de um trecho do documento que fundamenta o nível, ou null>\", \"justificativa_curta\": "
    "\"<1-2 frases>\"}. REGRAS: o trecho deve ser cópia literal do texto fornecido; se o "
    "documento não permite classificar, retorne escala null — NUNCA invente.")

_DDL = """
CREATE TABLE IF NOT EXISTS doc_veredito (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  numero_sei TEXT, doc_i INTEGER, tipo_canonico TEXT,
  hash_texto TEXT, rubrica_versao TEXT, modelo TEXT,
  escala INTEGER, trecho_literal TEXT, veredito_json TEXT,
  grau TEXT, avaliado_em TEXT DEFAULT (datetime('now')),
  UNIQUE(numero_sei, doc_i, rubrica_versao, hash_texto)
);
"""


def selecionar(docs: list[dict], teto: int | None = None) -> list[dict]:
    """Os documentos-que-importam, na ordem de prioridade, cortados no teto.

    Rubrica exige PRECISÃO no rótulo: 'parecer' só entra se o TÍTULO confirmar (o tipo por
    conteúdo rotulou 'Documento Trabalhista' como parecer e o veredito 'não-conclusivo'
    contaminava a contagem de problemáticos — debug 080001/018592/2026 doc 2)."""
    from compliance_agent.sei.fases import classificar
    teto = teto or TETO_DEFAULT
    rank = {t: n for n, t in enumerate(_PRIORIDADE)}
    alvo = [d for d in docs if d.get("tipo") in RUBRICAS
            and not (d.get("tipo") == "parecer"
                     and classificar(str(d.get("titulo") or ""))[1] != "parecer")]
    alvo.sort(key=lambda d: (rank.get(d.get("tipo"), 99), d.get("i", 0)))
    return alvo[:teto]


def _norm_txt(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").casefold()
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)


def _trecho_confere(trecho: str | None, texto: str) -> bool:
    t = _norm_txt(trecho or "").strip()
    return bool(t) and len(t) >= 8 and t in _norm_txt(texto)


_DB_PADRAO = object()  # sentinela: default abre o compliance.db; con=None desliga o cache


def _conn(con):
    if con is None:
        return None, False
    if con is not _DB_PADRAO:
        return con, False
    if not _DB.exists():
        return None, False
    return sqlite3.connect(str(_DB), timeout=15), True


def julgar_docs(man: dict, pasta: Path, *, teto: int | None = None,
                gerar=None, con=_DB_PADRAO) -> dict:
    """Julga os docs-chave do processo. `gerar(prompt, sistema)->str` injetável (teste);
    default = cadeia grátis da camada_triagem. `con` sqlite injetável; default compliance.db."""
    if gerar is None:
        from compliance_agent.llm.camada_triagem import gerar_triagem
        gerar = gerar_triagem()
    numero = str(man.get("processo") or pasta.name)
    docs = [d for d in (man.get("docs") or []) if isinstance(d, dict)]
    sel = selecionar(docs, teto=teto)

    c, own = _conn(con)
    if c is not None:
        c.executescript(_DDL)

    vereditos: list[dict] = []
    sem_resposta = cache_hits = 0
    try:
        for d in sel:
            texto = ""
            rel = d.get("texto")
            if rel and (pasta / rel).exists():
                texto = (pasta / rel).read_text(encoding="utf-8", errors="ignore")[:6000]
            if not texto.strip():
                vereditos.append({"i": d.get("i"), "tipo": d.get("tipo"), "escala": None,
                                  "aviso": "sem texto capturado (INDISPONÍVEL ≠ 0)"})
                continue
            h = hashlib.sha256(f"{texto}|{RUBRICA_VERSAO}".encode()).hexdigest()
            if c is not None:
                row = c.execute("select veredito_json from doc_veredito where numero_sei=? "
                                "and doc_i=? and rubrica_versao=? and hash_texto=?",
                                (numero, d.get("i"), RUBRICA_VERSAO, h)).fetchone()
                if row:
                    cache_hits += 1
                    vereditos.append(json.loads(row[0]))
                    continue

            rubrica = RUBRICAS[d["tipo"]]
            prompt = (f"{rubrica}\n\n--- DOCUMENTO ({d.get('titulo')}) ---\n{texto}\n--- FIM ---")
            v = _um_voto(gerar, prompt, texto)
            # rubrica crítica (emergência): 2º voto independente; divergência >1 rebaixa p/ o menor
            if d["tipo"] == "contratacao_direta" and v.get("escala") is not None:
                v2 = _um_voto(gerar, prompt, texto)
                if v2.get("escala") is not None and abs(v2["escala"] - v["escala"]) > 1:
                    v = {**v, "escala": min(v["escala"], v2["escala"]),
                         "aviso": "votos divergentes — rebaixado ao menor (adversarial)"}
            if v.get("escala") is None and not v.get("aviso"):
                sem_resposta += 1

            score = {1: 0.0, 2: 0.6, 3: 0.85}.get(v.get("escala"))
            v.update({"i": d.get("i"), "tipo": d.get("tipo"), "titulo": d.get("titulo"),
                      "grau": grau_flag(origem="llm", score=score)})
            vereditos.append(v)
            if c is not None:
                c.execute("insert or replace into doc_veredito (numero_sei, doc_i, "
                          "tipo_canonico, hash_texto, rubrica_versao, modelo, escala, "
                          "trecho_literal, veredito_json, grau) values (?,?,?,?,?,?,?,?,?,?)",
                          (numero, d.get("i"), d.get("tipo"), h, RUBRICA_VERSAO,
                           "cadeia_gratis", v.get("escala"), v.get("trecho_literal"),
                           json.dumps(v, ensure_ascii=False, default=str),
                           v["grau"]["grau"]))
                c.commit()
    finally:
        if own and c is not None:
            c.close()

    # semântica v2: escala 3 é sempre problema; escala 2 só é problema onde carrega mérito
    # (ressalva de parecer, homologação que não enfrenta, justificativa frágil) — despacho 2
    # é tramitação legítima e não entra na conta.
    _TIPOS_ESCALA2_RELEVANTE = ("parecer", "homologacao", "adjudicacao", "contratacao_direta",
                                "aceite", "medicao")
    problematicos = [v for v in vereditos
                     if (v.get("escala") or 0) >= 3
                     or ((v.get("escala") or 0) == 2
                         and v.get("tipo") in _TIPOS_ESCALA2_RELEVANTE)]
    return {"numero_sei": numero, "n_selecionados": len(sel), "vereditos": vereditos,
            "problematicos": len(problematicos),
            "cobertura": {"cache_hits": cache_hits, "sem_resposta": sem_resposta,
                          "rubrica_versao": RUBRICA_VERSAO}}


def _um_voto(gerar, prompt: str, texto: str) -> dict:
    try:
        bruto = gerar(prompt, _SISTEMA) or ""
    except Exception as e:  # noqa: BLE001
        return {"escala": None, "aviso": f"cadeia LLM indisponível: {str(e)[:80]}"}
    if not bruto.strip():
        return {"escala": None}
    try:
        v = parse_json_llm(bruto)
    except Exception:
        return {"escala": None, "aviso": "resposta não-parseável (schema inválido)"}
    if not isinstance(v, dict):
        return {"escala": None, "aviso": "resposta não-parseável (schema inválido)"}
    esc = v.get("escala")
    if esc is not None:
        try:
            esc = int(esc)
        except (TypeError, ValueError):
            esc = None
        if esc not in (1, 2, 3):
            esc = None
    trecho = v.get("trecho_literal")
    if esc is not None and not _trecho_confere(trecho, texto):
        return {"escala": None, "trecho_literal": None,
                "justificativa_curta": str(v.get("justificativa_curta") or "")[:200],
                "aviso": "trecho literal não confere com o texto — juízo descartado"}
    return {"escala": esc, "trecho_literal": (trecho or None) if esc is not None else None,
            "justificativa_curta": str(v.get("justificativa_curta") or "")[:200]}
