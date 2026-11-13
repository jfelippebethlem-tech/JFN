# -*- coding: utf-8 -*-
"""triagem_alertas — juízo sobre os alertas "novo" que a Ronda acumula sem ninguém olhar.

Medido em 13/11/2026: 62.241 alertas em `alertas` com status `novo` (58.253 de acumulação de cargos),
2 confirmados e 5 descartados. Fila sem triagem é fila invisível. Este módulo pega um LOTE PEQUENO por vez,
priorizado pelo VALOR em jogo (lido das evidências de cada tipo), e pede ao co-motor (Claude × cascata,
`llm/comotor`) um juízo em RUBRICA FECHADA:

    aprofundar · monitorar · provavel_falso_positivo · nao_avaliavel

com nota 0–10, justificativa ancorada num campo da evidência e o próximo passo. O resultado vai para a
tabela `alertas_triagem` (uma linha por alerta, com o motor que respondeu). O STATUS do alerta NÃO muda:
confirmar ou descartar é ato humano — a triagem só ordena a fila.

Honestidade: indício ≠ acusação; INDISPONÍVEL ≠ irregular; CPF vai MASCARADO no prompt (LGPD).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[1]
DB = _REPO / "data" / "compliance.db"
PRIORIDADES = ("aprofundar", "monitorar", "provavel_falso_positivo", "nao_avaliavel")
# chaves de valor por ordem de preferência — cada detector grava o seu (medido nas evidências reais)
CHAVES_VALOR = ("valor", "soma", "total", "total_bruto", "empenhado", "total_autor", "excesso", "remuneracao")
_RE_CPF = re.compile(r"(?<!\d)(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?!\d)")

_SYS = (
    "Você é auditor de controle externo (TCE-RJ) fazendo TRIAGEM de alertas automáticos do sistema JFN. "
    "Não é parecer: é decidir para onde o alerta vai na fila. Regras: indício não é acusação; dado ausente é "
    "INDISPONÍVEL, não irregularidade; presunção de legitimidade; nunca invente fato fora da evidência. "
    "Classifique em UMA prioridade: 'aprofundar' (sinal material e verificável que justifica abrir apuração), "
    "'monitorar' (sinal fraco ou dependente de dado que falta), 'provavel_falso_positivo' (a própria evidência "
    "explica o alerta de forma inocente ou o detector disparou por artefato), 'nao_avaliavel' (evidência "
    "insuficiente para qualquer juízo). A justificativa cita o CAMPO da evidência em que se apoia."
)
_SCHEMA = ('{"prioridade":"aprofundar|monitorar|provavel_falso_positivo|nao_avaliavel","nota":0-10,'
           '"justificativa":"1-2 frases citando o campo da evidência","proximo_passo":"o que verificar"}')

_DDL = """CREATE TABLE IF NOT EXISTS alertas_triagem(
  alerta_id INTEGER PRIMARY KEY, prioridade TEXT, nota INTEGER, justificativa TEXT, proximo_passo TEXT,
  valor REAL, motor TEXT, em TEXT)"""


def mascarar_cpf(texto: str) -> str:
    return _RE_CPF.sub(lambda m: f"***.{m.group(2)}.{m.group(3)}-**", texto or "")


def valor_do_alerta(evid: dict) -> float | None:
    for k in CHAVES_VALOR:
        v = evid.get(k) if isinstance(evid, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


_COALESCE = "COALESCE(" + ",".join(
    f"CAST(json_extract(a.evidencias,'$.{k}') AS REAL)" for k in CHAVES_VALOR) + ",0)"


def selecionar(con: sqlite3.Connection, n: int) -> list[dict]:
    """Os `n` alertas `novo` ainda não triados, do MAIOR valor em jogo para o menor."""
    con.execute(_DDL)
    sql = (f"SELECT a.id, a.tipo, a.severidade, a.titulo, a.descricao, a.evidencias, "
           f"CASE WHEN json_valid(a.evidencias) THEN {_COALESCE} ELSE 0 END AS v "
           "FROM alertas a LEFT JOIN alertas_triagem t ON t.alerta_id = a.id "
           "WHERE a.status = 'novo' AND t.alerta_id IS NULL ORDER BY v DESC, a.id LIMIT ?")
    cols = ("id", "tipo", "severidade", "titulo", "descricao", "evidencias", "valor")
    return [dict(zip(cols, r)) for r in con.execute(sql, (n,)).fetchall()]


def montar_prompt(a: dict) -> str:
    evid = a.get("evidencias") or ""
    try:
        evid = json.dumps(json.loads(evid), ensure_ascii=False)
    except (TypeError, ValueError):
        logger.debug("triagem: evidências do alerta %s não são JSON — vão como texto", a.get("id"))
    return mascarar_cpf(
        f"ALERTA #{a['id']} — tipo {a.get('tipo')} · severidade do detector {a.get('severidade')}\n"
        f"TÍTULO: {(a.get('titulo') or '')[:300]}\n"
        f"DESCRIÇÃO: {(a.get('descricao') or '')[:1500]}\n"
        f"EVIDÊNCIAS (JSON do detector): {evid[:2500]}\n\n"
        f"Faça a triagem. Responda SOMENTE com o JSON: {_SCHEMA}")


def interpretar(txt: str) -> dict:
    from compliance_agent.llm.json_resposta import parse_json_llm
    d = parse_json_llm(txt or "")
    d = d if isinstance(d, dict) else {}
    p = str(d.get("prioridade") or "").strip().lower()
    try:
        nota = int(round(float(d.get("nota"))))
        nota = nota if 0 <= nota <= 10 else None
    except (TypeError, ValueError):
        nota = None
    if p not in PRIORIDADES:
        return {"prioridade": "nao_avaliavel", "nota": None,
                "justificativa": "resposta fora da rubrica — descartada", "proximo_passo": ""}
    return {"prioridade": p, "nota": nota, "justificativa": str(d.get("justificativa") or "")[:600],
            "proximo_passo": str(d.get("proximo_passo") or "")[:300]}


def triar_lote(con: sqlite3.Connection, n: int = 8, *, gerar=None) -> list[dict]:
    """Tria até `n` alertas. Falha do motor num alerta não aborta o lote (esse fica para a próxima)."""
    if gerar is None:
        from compliance_agent.llm.comotor import juizo
        gerar = juizo("triagem_alertas")
    from compliance_agent.llm.comotor import ultima_chamada
    feitos = []
    for a in selecionar(con, n):
        try:
            bruto = gerar(montar_prompt(a), _SYS, 60.0, True, item=f"alerta:{a['id']}")
        except TypeError:          # gerar dublê/antigo sem `item`
            bruto = gerar(montar_prompt(a), _SYS)
        except (RuntimeError, OSError, ValueError) as e:  # motor fora: o alerta volta no próximo lote
            logger.warning("triagem: alerta %s sem juízo (%s)", a["id"], type(e).__name__)
            continue
        r = interpretar(bruto)
        motor = ultima_chamada().get("exibido") or "desconhecido"
        con.execute("INSERT OR REPLACE INTO alertas_triagem(alerta_id,prioridade,nota,justificativa,proximo_passo,"
                    "valor,motor,em) VALUES(?,?,?,?,?,?,?,?)",
                    (a["id"], r["prioridade"], r["nota"], r["justificativa"], r["proximo_passo"], a["valor"],
                     motor, datetime.now().isoformat(timespec="seconds")))
        con.commit()                # transação curta por alerta: o painel lê o mesmo banco
        feitos.append({"id": a["id"], **r, "motor": motor})
    return feitos


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Triagem (co-motor Claude × cascata) dos alertas 'novo' da Ronda")
    ap.add_argument("--lote", type=int, default=8)
    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args(argv)
    con = sqlite3.connect(a.db, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        feitos = triar_lote(con, a.lote)
    finally:
        con.close()
    for f in feitos:
        print(f"  alerta {f['id']}: {f['prioridade']} nota={f['nota']} motor={f['motor']}")
    print(f"[triagem_alertas] triados nesta passada: {len(feitos)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
