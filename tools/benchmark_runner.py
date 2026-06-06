#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Runner do BENCHMARK das IAs do ecossistema (background) — Passo 2/3 do docs/IAS-ECOSSISTEMA-BENCHMARK.md.

Roda cada função/tarefa do gold (Claude = baseline) em VÁRIOS modelos de fallback DISTINTOS (várias Gemini de
versões diferentes via OpenRouter + Llama/Qwen via Groq — sem repetir modelo), pontua e grava:
  - data/benchmark_resultados.json  (saídas cruas + score por modelo×tarefa)
  - data/benchmark_ias.csv          (via benchmark_ias.registrar)
  - data/benchmark_relatorio.md     (tabela comparativa + aprendizados p/ IAs fracas)

Pontuação: T5 (SQL) é DETERMINÍSTICA (roda o SQL e compara nº de grupos com o gold). T1/T2/T6 (juízo) são
pontuadas por um JUIZ-LLM (modelo forte do fallback) contra o `criterio_sucesso` do gold (0–3).

Roda em subprocesso (não consome cota da sessão do Claude; só tokens das APIs de fallback).
    nohup python tools/benchmark_runner.py > data/benchmark_run.log 2>&1 &
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
try:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
except Exception:
    pass

from compliance_agent.llm.free_llm import _openai_compat_chat_sync  # noqa: E402
from compliance_agent import benchmark_ias as BM  # noqa: E402

OPENROUTER = "https://openrouter.ai/api/v1"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"  # Gemini direto (quota própria, OpenAI-compat)
MISTRAL = "https://api.mistral.ai/v1"
K_OR = os.environ.get("OPENROUTER_API_KEY", "")
K_GEM = os.environ.get("GEMINI_API_KEY", "")
K_MIS = os.environ.get("MISTRAL_API_KEY", "")

# Roster de modelos de fallback DISTINTOS — 3 Gemini de versões diferentes (API direta, quota própria) + 3
# Mistral. Sem OpenRouter (sem crédito) e sem repetir versão/modelo.
MODELOS = [
    ("Gemini-2.5-Flash-Lite", GEMINI, K_GEM, "gemini-2.5-flash-lite"),
    ("Gemini-2.5-Flash", GEMINI, K_GEM, "gemini-2.5-flash"),
    ("Gemini-2.0-Flash", GEMINI, K_GEM, "gemini-2.0-flash"),
    ("Mistral-Large", MISTRAL, K_MIS, "mistral-large-latest"),
    ("Mistral-Small", MISTRAL, K_MIS, "mistral-small-latest"),
    ("Mistral-Nemo", MISTRAL, K_MIS, "open-mistral-nemo"),
]
JUIZ = ("Gemini-2.5-Flash-Lite", GEMINI, K_GEM, "gemini-2.5-flash-lite")  # juiz confiável e barato

CTX_YODA = ("Você é o Yoda, maestro do JFN. Ferramentas REAIS = rotas HTTP em 127.0.0.1:8000: "
            "POST /api/relatorio/inteligencia {empresa|cnpj}; POST /api/relatorio/orgao {orgao|ug}; "
            "GET /api/anomalias; GET /api/cartel; GET/POST /api/massare/*. "
            "NÃO invente ferramenta (web_search NÃO existe). Princípio: indício, nunca acusação.")


def _chat(prov, key, model, system, user, max_tokens=1500):  # teto alto: Gemini 2.5/3 "pensam" antes de responder
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    hdr = {"HTTP-Referer": "https://jfn.local", "X-Title": "JFN-Benchmark"} if "openrouter" in prov else None
    err = None
    for tent in range(3):
        try:
            r = _openai_compat_chat_sync(prov, key, model, msgs, max_tokens=max_tokens, extra_headers=hdr)
            return r if r is not None else ""
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2 * (tent + 1))
    return f"__ERRO__ {type(err).__name__}: {str(err)[:140]}"


def _prompt(tarefa: dict) -> tuple[str, str]:
    tid = tarefa["id"]
    ent = tarefa.get("entrada", "")
    if tid == "T1":
        return CTX_YODA, f"Pergunta do usuário: «{ent}». Qual rota você chama e com quais parâmetros? Seja direto."
    if tid == "T2":
        # dá um JSON real do endpoint
        exemplo = json.dumps({"ok": True, "itens": [
            {"ob": "2024OB1", "fornecedor": "EMPRESA X", "valor": 8400000.0, "score": 0.98,
             "regras": "R_VALOR_SIMBOLICO, R_FRACIONAMENTO_SAMEDAY"},
            {"ob": "2024OB2", "fornecedor": "EMPRESA Y", "valor": 0.07, "score": 0.95, "regras": "R_VALOR_SIMBOLICO"},
        ]}, ensure_ascii=False)
        return ("Você interpreta saídas do JFN para o gestor, em PT-BR, curto.",
                f"Interprete este JSON de /api/anomalias e liste os achados com a cláusula de honestidade "
                f"(indício, não acusação):\n{exemplo}")
    if tid == "T5":
        return ("Você escreve SQL SQLite para auditoria. Responda APENAS o SQL.",
                f"Tabela ordens_bancarias(ug_codigo, exercicio, favorecido_cpf, valor). {ent}. Escreva a query.")
    if tid == "T6":
        return ("Você é o Lex (parecer jurídico de indícios). Honesto: indício, nunca acusação.",
                f"Cenário: {ent}. Emita um parecer curto de indícios com fundamento (concentração/valor simbólico).")
    return ("", ent)


def _extrai_sql(txt: str) -> str:
    m = re.search(r"```sql\s*(.+?)```", txt, re.S | re.I) or re.search(r"```\s*(SELECT.+?)```", txt, re.S | re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"(SELECT\b.+)", txt, re.S | re.I)
    return m.group(1).strip().rstrip("`").strip() if m else txt.strip()


def _juiz(tarefa: dict, saida: str) -> tuple[float, str]:
    crit = tarefa.get("gold", {}).get("criterio_sucesso", "")
    gold = json.dumps(tarefa.get("gold", {}), ensure_ascii=False)
    sys_j = ("Você é um juiz rigoroso de qualidade de respostas de IA. Compare a RESPOSTA com o CRITÉRIO e o "
             "GABARITO. Responda APENAS UM NÚMERO: 0 (errado), 1 (fraco), 2 (bom), 3 (atende plenamente). "
             "Nada além do número.")
    user_j = f"CRITÉRIO: {crit}\nGABARITO: {gold}\nRESPOSTA: {saida[:1500]}\n\nNota (só o número 0-3):"
    out = _chat(JUIZ[1], JUIZ[2], JUIZ[3], sys_j, user_j, max_tokens=1500)
    # pega o ÚLTIMO dígito 0-3 do texto (após eventual raciocínio, a nota final vem por último)
    digs = re.findall(r"[0-3]", out or "")
    if digs:
        return float(digs[-1]), f"juiz: {(out or '').strip()[-40:]}"
    return 0.0, f"juiz s/ nota: {(out or '')[:60]}"


def main():
    gold = BM.carregar_gold()
    tarefas = [t for t in gold["tarefas"] if t["id"] in ("T1", "T2", "T5", "T6")]
    resultados = []
    for tarefa in tarefas:
        system, user = _prompt(tarefa)
        for nome, prov, key, model in MODELOS:
            if not key:
                continue
            t0 = time.time()
            saida = _chat(prov, key, model, system, user)
            dt = round(time.time() - t0, 1)
            erro = saida.startswith("__ERRO__")
            if erro:
                score, nota = 0.0, saida
            elif tarefa["id"] == "T5":
                v = BM.verificar_sql_concentracao(_extrai_sql(saida))
                score = float(v.get("score", 0.0)) if v.get("ok") else 0.0
                nota = json.dumps(v, ensure_ascii=False)[:160]
            else:
                score, nota = _juiz(tarefa, saida)
            BM.registrar(nome, tarefa["id"], score, nota)
            resultados.append({"tarefa": tarefa["id"], "modelo": nome, "model_id": model,
                               "score": score, "seg": dt, "nota": nota, "saida": saida[:1200]})
            print(f"{tarefa['id']:>3} | {nome:18} | score {score} | {dt}s | {nota[:70]}", flush=True)
            time.sleep(1.5)  # respiro p/ não estourar rate-limit da OpenRouter

    Path(REPO / "data" / "benchmark_resultados.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")

    # relatório markdown: tabela modelo × tarefa
    modelos = [m[0] for m in MODELOS]
    tids = [t["id"] for t in tarefas]
    L = ["# Benchmark das IAs do ecossistema — modelo × tarefa\n",
         "Baseline = Claude Opus 4.8 (gold). Score 0–3 (T5 determinístico; T1/T2/T6 por juiz-LLM).\n",
         "| Modelo | " + " | ".join(tids) + " | Média |", "|---|" + "---|" * (len(tids) + 1)]
    for mnome in modelos:
        linha, soma, n = [], 0.0, 0
        for tid in tids:
            sc = next((r["score"] for r in resultados if r["modelo"] == mnome and r["tarefa"] == tid), None)
            linha.append("—" if sc is None else f"{sc:g}")
            if sc is not None:
                soma += sc; n += 1
        media = f"{soma/n:.2f}" if n else "—"
        L.append(f"| {mnome} | " + " | ".join(linha) + f" | {media} |")
    Path(REPO / "data" / "benchmark_relatorio.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\nOK — data/benchmark_resultados.json + data/benchmark_relatorio.md + data/benchmark_ias.csv")


if __name__ == "__main__":
    main()
