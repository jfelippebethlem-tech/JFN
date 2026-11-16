# -*- coding: utf-8 -*-
"""ritmo_assinatura — a assinatura do Claude tem de durar até a virada da semana (sábado 19:00).

Pedido do dono (16/11/2026): "vamos organizar o sistema jfn de modo que a assinatura não acabe antes do sábado 19:00".
Medido no mesmo dia, 18h: janela semanal aberta no sábado 14/11 19:00, 45% gastos em 47 h (~23%/dia) — no ritmo,
a conta acabaria na quarta à noite.

COMO MEDE: o mesmo endpoint da conta que o `/usage` do Claude Code lê (`api/oauth/usage`), com o token OAuth que o
próprio CLI mantém em `~/.claude/.credentials.json` (lido em memória, nunca gravado nem logado). Grava só números em
`data/claude_assinatura_uso.json` (último) e `data/claude_assinatura_uso.jsonl` (histórico, para ver o ritmo).

LINHA DE RITMO: o gasto semanal permitido cresce em linha reta até `ALVO_SEMANA` (90%) na virada; os 10% finais são
folga para o dono (sessões interativas, Claude Desktop) — a conta é UMA para tudo.
  linha(t) = PISO + (ALVO_SEMANA − PISO) × fração da semana decorrida
  · uso ≥ linha  ou  uso ≥ TETO_DURO  → CONTIDO: o motor do JFN não chama o Claude (só o canário); tudo segue pela
    cascata de outros modelos e vai à fila de conferência do Opus (`llm/contingencia`, regra do dono de 14/11);
  · linha − FOLGA ≤ uso < linha        → ECONOMIA: só as tarefas do Opus que CONFEREM (verificação/conferência);
    o volume (perícia integral, perícia de execução, triagem) vai à cascata;
  · abaixo disso                        → NORMAL.
O secretário do WhatsApp lê o mesmo arquivo e, fora do NORMAL, faz as sugestões de rascunho com o Sonnet (os comandos
do dono, os lotes e a saúde continuam no Opus).

Medição velha (> 2 h) ou ilegível ⇒ NORMAL com `medido=False` (INDISPONÍVEL não vira restrição inventada; os tetos
diários do motor continuam valendo).

  python -m compliance_agent.llm.ritmo_assinatura --medir     # cron a cada 10 min
  python -m compliance_agent.llm.ritmo_assinatura --status
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
URL = "https://api.anthropic.com/api/oauth/usage"
SEMANA_S = 7 * 86400
PISO = 5.0            # % liberado logo na abertura da janela (sem isso a linha começa em 0 e trava tudo)
ALVO_SEMANA = 90.0    # % previsto na virada; o resto é do dono
TETO_DURO = 85.0      # daqui para cima o motor só volta na semana seguinte
FOLGA = 5.0           # faixa de ECONOMIA abaixo da linha
VALIDADE_S = 2 * 3600
REAVALIAR_S = 15 * 60


def _dados() -> Path:
    return Path(os.environ.get("JFN_CLAUDE_DADOS") or _REPO / "data")


def arquivo() -> Path:
    return _dados() / "claude_assinatura_uso.json"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def _ts(iso: str | None) -> float | None:
    try:
        return datetime.fromisoformat(iso).timestamp() if iso else None
    except (TypeError, ValueError):
        return None


def _token() -> str | None:
    try:
        c = json.loads((Path.home() / ".claude" / ".credentials.json").read_text())
        return (c.get("claudeAiOauth") or {}).get("accessToken")
    except (OSError, ValueError):
        return None


def _buscar() -> dict:
    tok = _token()
    if not tok:
        raise RuntimeError("sem credencial do CLI")
    req = urllib.request.Request(URL, headers={"Authorization": f"Bearer {tok}",
                                               "anthropic-beta": "oauth-2025-04-20", "User-Agent": "claude-code"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def extrair(bruto: dict, agora: float | None = None) -> dict:
    """Só números: % da sessão (5 h) e da semana, com as viradas. Formato inesperado ⇒ ValueError."""
    agora = time.time() if agora is None else agora
    s, w = bruto.get("five_hour") or {}, bruto.get("seven_day") or {}
    if w.get("utilization") is None or not w.get("resets_at"):
        raise ValueError("resposta sem seven_day")
    return {"em": _iso(agora), "medido_ts": agora,
            "sessao_pct": s.get("utilization"), "sessao_volta": _iso(_ts(s.get("resets_at"))) if s.get("resets_at") else None,
            "semana_pct": float(w["utilization"]), "semana_volta": _iso(_ts(w["resets_at"]))}


def linha(volta_ts: float, agora: float) -> float:
    frac = min(1.0, max(0.0, 1 - (volta_ts - agora) / SEMANA_S))
    return PISO + (ALVO_SEMANA - PISO) * frac


def classificar(m: dict | None, agora: float | None = None) -> dict:
    agora = time.time() if agora is None else agora
    base = {"nivel": "normal", "medido": False, "semana_pct": None, "linha_pct": None, "semana_volta": None,
            "reavaliar_em": _iso(agora + REAVALIAR_S), "motivo": None}
    if not m or agora - float(m.get("medido_ts") or 0) > VALIDADE_S:
        return dict(base, motivo="uso da assinatura INDISPONÍVEL (medição ausente ou velha) — sem restrição de ritmo")
    volta = _ts(m.get("semana_volta"))
    pct = m.get("semana_pct")
    if volta is None or pct is None:
        return dict(base, motivo="medição sem a virada da semana — sem restrição de ritmo")
    ln = round(linha(volta, agora), 1)
    out = dict(base, medido=True, semana_pct=pct, linha_pct=ln, semana_volta=m.get("semana_volta"))
    if pct >= TETO_DURO:
        return dict(out, nivel="contido", motivo=f"assinatura em {pct:.0f}% da semana (teto {TETO_DURO:.0f}%) — o resto é "
                                                 f"do dono até {m['semana_volta'][:16]}")
    if pct >= ln:
        return dict(out, nivel="contido", motivo=f"assinatura em {pct:.0f}% da semana, acima do ritmo ({ln:.0f}%) que a "
                                                 f"faz durar até {m['semana_volta'][:16]}")
    if pct >= ln - FOLGA:
        return dict(out, nivel="economia", motivo=f"assinatura em {pct:.0f}% da semana, perto do ritmo ({ln:.0f}%) — "
                                                  f"só o Opus que confere")
    return dict(out, motivo=f"assinatura em {pct:.0f}% da semana, abaixo do ritmo ({ln:.0f}%)")


def ler() -> dict | None:
    try:
        return json.loads(arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def nivel(agora: float | None = None) -> dict:
    """Leitura barata (só arquivo) para o motor, a contingência, o secretário e o painel."""
    return classificar(ler(), agora)


def medir(buscar=None) -> dict:
    """Mede, grava o último + histórico e devolve a classificação. Falha de rede ⇒ mantém o último (e diz)."""
    agora = time.time()
    try:
        m = extrair((buscar or _buscar)(), agora)
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as e:
        return dict(nivel(agora), erro=type(e).__name__)
    c = classificar(m, agora)
    m = dict(m, nivel=c["nivel"], linha_pct=c["linha_pct"])
    d = _dados()
    d.mkdir(parents=True, exist_ok=True)
    tmp = arquivo().with_suffix(".tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(arquivo())
    with (d / "claude_assinatura_uso.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({k: m[k] for k in ("em", "sessao_pct", "semana_pct", "linha_pct", "nivel")}) + "\n")
    return c


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ritmo semanal da assinatura do Claude")
    ap.add_argument("--medir", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    r = medir() if a.medir else nivel()
    print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
