# -*- coding: utf-8 -*-
"""medir_peso_sonnet — protocolo de MEDIÇÃO do peso do Sonnet na cota da assinatura (O66-P5, decisão delegada D4).

PERGUNTA. Quanto um segundo de Sonnet (`claude -p --model claude-sonnet-5-5`, assinatura) consome da cota semanal
em relação a um segundo de Opus? A simulação da O6.6 (`conferente_sonnet.simular`) usou 1,0 / 0,5 / 0,2 porque o peso
NÃO foi medido; a Anthropic não publica a proporção (docs "Usage limits", lidas em 24/11/2026: o consumo "depende do
modelo"). Este script mede, pelo mesmo contador que o `/usage` do Claude Code lê (`ritmo_assinatura._buscar`).

QUANDO. Só DEPOIS de sábado 28/11/2026 19:00 (-03:00), com a semana nova aberta — antes disso a assinatura está
contida e o script se recusa. Rodar UMA vez, com o dono avisado para NÃO usar sessões interativas na janela (~2 h): a
cota é uma só e uso alheio entra na medida (o desenho ABBA cancela deriva LINEAR, não um pico).

DESENHO (ABBA). Blocos Sonnet → Opus → Opus → Sonnet sobre a MESMA lista de entradas reais (perícias de execução
pendentes na fila do Opus, sorteio determinístico pelo hash, sem a resposta do motor), mesmo sistema, `backend="cli"`.
  · antes e depois de cada bloco: leitura do contador; espera a leitura estabilizar (2 iguais seguidas, até 10 min);
  · um bloco termina quando a SESSÃO (5 h) andou ≥ `MIN_DELTA` pontos ou com `--max-itens` itens;
  · peso = (Δ% Sonnet / s de Sonnet) ÷ (Δ% Opus / s de Opus), pela sessão (resolução maior) E pela semana, com o
    intervalo da resolução de 1 ponto (Δ ± 1); por item também;
  · aborta se a semana passar de início + `TETO_PONTOS` ou o ritmo sair de NORMAL.
Nada é aplicado: o resultado vai a `data/peso_sonnet_medicao.json` e ao dono; o peso entra na simulação à mão.

    python -m tools.medir_peso_sonnet --plano                    # só mostra o plano (padrão; nenhuma chamada)
    python -m tools.medir_peso_sonnet --executar [--max-itens 12]   # depois de 28/11 19h, com o dono avisado
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

ABRE = datetime(2026, 11, 28, 19, 0, tzinfo=timezone(timedelta(hours=-3)))
MIN_DELTA = 3            # pontos percentuais da sessão de 5 h por bloco (resolução do contador = 1 ponto)
TETO_PONTOS = 15         # a medição inteira não gasta mais que 15 pontos da semana
ESTABILIZA_S, ESTABILIZA_MAX_S = 60, 600
ORDEM = ("sonnet", "opus", "opus", "sonnet")
TAREFA = {"sonnet": "conferencia_sonnet", "opus": "conferencia_opus"}
_REPO = Path(__file__).resolve().parents[1]
SAIDA = _REPO / "data" / "peso_sonnet_medicao.json"


def precondicoes(agora: datetime | None = None, nivel=None) -> list[str]:
    """Motivos para NÃO rodar (vazio = pode)."""
    from compliance_agent.llm import ritmo_assinatura as R
    agora = agora or datetime.now(timezone.utc)
    out = []
    if agora < ABRE:
        out.append(f"antes de {ABRE.isoformat()} (assinatura contida até a virada da semana)")
    n = (nivel or R.nivel)()
    if not n.get("medido"):
        out.append("uso da assinatura INDISPONÍVEL (medição ausente/velha) — rode ritmo_assinatura --medir antes")
    elif n.get("nivel") != "normal":
        out.append(f"ritmo da assinatura '{n.get('nivel')}': {n.get('motivo')}")
    return out


def amostra(con: sqlite3.Connection, n: int) -> list[dict]:
    """`n` perícias de execução pendentes com entrada, pelo hash da chave (determinístico)."""
    rows = con.execute("SELECT chave, sistema, entrada FROM fila WHERE tarefa='pericia_execucao' AND "
                       "status IN ('pendente','nao_julgado') AND entrada IS NOT NULL").fetchall()
    rows.sort(key=lambda r: hashlib.sha1(f"peso-sonnet\x00{r[0]}".encode()).hexdigest())
    return [{"chave": c, "sistema": s or "", "entrada": zlib.decompress(b).decode("utf-8", "replace")}
            for c, s, b in rows[:n]]


def leitura(buscar=None) -> dict:
    """Só números do contador da conta (o token do CLI é lido em memória por `ritmo_assinatura`, nunca gravado)."""
    from compliance_agent.llm import ritmo_assinatura as R
    bruto = (buscar or R._buscar)()
    m = R.extrair(bruto)
    extras = {k: v.get("utilization") for k, v in bruto.items() if isinstance(v, dict) and "utilization" in v}
    return {"em": m["em"], "sessao": m["sessao_pct"], "semana": m["semana_pct"], "baldes": extras}


def estavel(buscar=None, dormir=time.sleep) -> dict:
    ant, ini = leitura(buscar), time.monotonic()
    while time.monotonic() - ini < ESTABILIZA_MAX_S:
        dormir(ESTABILIZA_S)
        cur = leitura(buscar)
        if (cur["sessao"], cur["semana"], cur["baldes"]) == (ant["sessao"], ant["semana"], ant["baldes"]):
            return cur
        ant = cur
    return dict(ant, instavel=True)


def peso(blocos: list[dict], campo: str) -> dict:
    """Peso por segundo e por item, com o intervalo da resolução (Δ ± 1 ponto em cada lado)."""
    def soma(modelo, k):
        return sum(b[k] for b in blocos if b["modelo"] == modelo)
    ds, do = soma("sonnet", f"delta_{campo}"), soma("opus", f"delta_{campo}")
    ss, so = soma("sonnet", "segundos"), soma("opus", "segundos")
    ns, no = soma("sonnet", "itens"), soma("opus", "itens")
    nb = sum(1 for b in blocos if b["modelo"] == "sonnet")      # ±1 ponto por bloco
    if not (ds and do and ss and so):
        return {"campo": campo, "peso_por_segundo": None, "motivo": "Δ zero ou sem tempo: INDISPONÍVEL"}

    def r(a, b, sa, sb):
        return round((a / sa) / (b / sb), 3) if a > 0 and b > 0 else None
    return {"campo": campo, "delta_sonnet": ds, "delta_opus": do, "segundos_sonnet": round(ss), "segundos_opus":
            round(so), "peso_por_segundo": r(ds, do, ss, so),
            "intervalo_resolucao": [r(ds - nb, do + nb, ss, so), r(ds + nb, do - nb, ss, so)],
            "peso_por_item": r(ds, do, ns, no)}


def executar(max_itens: int, *, pensar=None, buscar=None, con=None, dormir=time.sleep) -> dict:
    from compliance_agent.llm import claude_motor as CM
    from compliance_agent.llm import conferencia_opus as CO
    pensar = pensar or CM.pensar
    proprio = con is None
    con = con or sqlite3.connect(f"file:{CO.caminho()}?mode=ro", uri=True, timeout=30)
    try:
        itens = amostra(con, max_itens)
    finally:
        if proprio:
            con.close()
    if len(itens) < 3:
        return {"erro": f"só {len(itens)} entrada(s) de perícia de execução com texto na fila — INDISPONÍVEL"}
    inicio = estavel(buscar, dormir)
    blocos = []
    for modelo in ORDEM:
        antes = estavel(buscar, dormir)
        seg, feitos = 0.0, 0
        for it in itens:
            t0 = time.monotonic()
            p = pensar(TAREFA[modelo], it["entrada"], modelo=CM.MODELO_JUIZO if modelo == "opus" else "claude-sonnet-5-5",
                       sistema=it["sistema"], backend="cli", timeout=600.0, espera=420.0)
            if p is None:
                return {"erro": f"assinatura sem resposta no bloco {modelo}: {CM.ultimo_motivo}", "blocos": blocos}
            seg += time.monotonic() - t0
            feitos += 1
            agora = leitura(buscar)
            if (agora["sessao"] or 0) - (antes["sessao"] or 0) >= MIN_DELTA:
                break
            if (agora["semana"] or 0) - (inicio["semana"] or 0) >= TETO_PONTOS:
                return {"erro": f"teto da medição: semana andou ≥ {TETO_PONTOS} pontos", "blocos": blocos}
        depois = estavel(buscar, dormir)
        blocos.append({"modelo": modelo, "itens": feitos, "segundos": round(seg, 1), "antes": antes, "depois": depois,
                       "delta_sessao": (depois["sessao"] or 0) - (antes["sessao"] or 0),
                       "delta_semana": (depois["semana"] or 0) - (antes["semana"] or 0)})
    return {"em": datetime.now().isoformat(timespec="seconds"), "desenho": "ABBA", "itens_por_bloco_max": max_itens,
            "blocos": blocos, "peso_sessao": peso(blocos, "sessao"), "peso_semana": peso(blocos, "semana"),
            "aviso": "medido pelo contador da conta (resolução 1 ponto); uso alheio na janela entra na medida"}


def plano(max_itens: int) -> str:
    return (f"Protocolo D4 (não roda antes de {ABRE.isoformat()}): blocos {' → '.join(ORDEM)} com até {max_itens} "
            f"perícias de execução reais (as mesmas nos 4 blocos), tarefa conferencia_sonnet/conferencia_opus pela "
            f"assinatura; bloco para com Δ sessão ≥ {MIN_DELTA} pontos; aborta com semana +{TETO_PONTOS}. "
            f"Saída: {SAIDA}. Pré-condições agora: {precondicoes() or 'OK'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mede o peso do Sonnet na cota da assinatura (O66-P5 / D4)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--plano", action="store_true", help="só mostra o plano (padrão)")
    g.add_argument("--executar", action="store_true", help="roda a medição (depois de 28/11 19h)")
    ap.add_argument("--max-itens", type=int, default=12)
    a = ap.parse_args(argv)
    if not a.executar:
        print(plano(a.max_itens))
        return 0
    barrado = precondicoes()
    if barrado:
        print("NÃO roda: " + " | ".join(barrado), file=sys.stderr)
        return 2
    res = executar(a.max_itens)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: res.get(k) for k in ("erro", "peso_sessao", "peso_semana")}, ensure_ascii=False, indent=1))
    return 1 if res.get("erro") else 0


if __name__ == "__main__":
    raise SystemExit(main())
