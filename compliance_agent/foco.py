# -*- coding: utf-8 -*-
"""FOCO DAS FILAS — cota do período Couto em todo lote que consome esforço (pedido do dono, 22/11/2026 00h50:
"vamos focar no governo Couto? 50% do esforço destinado ao período dele.").

Uma regra, um lugar: cada fila (perícia integral, Lex execução, conferência do Opus, triagem de alertas, captura
SEI da VM-1/VM-2/it-campo, recaptura, indeterminados, 360, ficha) continua ordenando do jeito dela e chama
`intercalar(itens, chave_data)`. A função separa os itens do período Couto dos demais SEM mudar a ordem dentro de
cada grupo e devolve o lote intercalado: em qualquer prefixo, ⌈n·fração⌉ itens Couto enquanto houver; acabou o
Couto, completa com o resto (nunca deixa a máquina ociosa), e vice-versa.

  · início = `governo_couto.INICIO` (constante única; nada de data copiada aqui). 23/03/2026 é dia de transição:
    as filas tratam OB/execução/contratação, que vão pela DATA — ≥ 23/03/2026 é Couto.
  · fração e liga/desliga = `config/foco.yaml` (ponto único de configuração).
  · processo SEI é "do período" quando tem OB PAGA no SIAFE (régua única `cruzamentos_intel._ob_paga`) emitida a
    partir do início, ou contratação no espelho TCE-RJ a partir do início. Sem fonte ⇒ não é Couto (INDISPONÍVEL
    não vira Couto nem acusação: só muda a ORDEM de uma fila, nunca um veredito).
"""
from __future__ import annotations

import itertools
import json
import logging
import math
import os
import re
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable, TypeVar

from compliance_agent.governo_couto import INICIO

logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[1]
CONFIG = RAIZ / "config" / "foco.yaml"
DB = RAIZ / "data" / "compliance.db"
CACHE_NOME = ".foco_couto_processos.json"     # ao lado do banco lido
CACHE_HORAS = 6          # a varredura do SIAFE custa 10–70 s (medido 22/11, load 1–20); filas rodam de 5 em 5 min
_OB_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"

T = TypeVar("T")
_MEMO: dict = {}


def config(caminho: Path | None = None) -> dict:
    """{"inicio", "fracao", "ligado"} — `inicio` sempre da constante; arquivo ausente/ilegível ⇒ 0,5 ligado."""
    cfg: dict = {}
    try:
        import yaml
        cfg = (yaml.safe_load((caminho or CONFIG).read_text(encoding="utf-8")) or {}).get("periodo_couto") or {}
    except (OSError, ValueError, AttributeError, ImportError) as e:
        logger.warning("foco: %s ilegível (%s) — uso fração 0,5", caminho or CONFIG, type(e).__name__)
    try:
        fracao = min(1.0, max(0.0, float(cfg.get("fracao", 0.5))))
    except (TypeError, ValueError):
        fracao = 0.5
    return {"inicio": INICIO, "fracao": fracao, "ligado": bool(cfg.get("ligado", True))}


def iso(d) -> str | None:
    """'AAAA-MM-DD' de date/datetime, 'AAAA-MM-DD…' ou 'DD/MM/AAAA'; 'AAAA-MM' vira o dia 1. Ilegível ⇒ None."""
    if d is None or isinstance(d, bool):
        return None
    if isinstance(d, (date, datetime)):
        return d.strftime("%Y-%m-%d")
    s = str(d).strip()
    m = re.match(r"(20\d\d)-(\d\d)(?:-(\d\d))?", s)
    if m:
        return f"{m[1]}-{m[2]}-{m[3] or '01'}"
    m = re.match(r"(\d\d)/(\d\d)/(20\d\d)", s)
    return f"{m[3]}-{m[2]}-{m[1]}" if m else None


def eh_couto(d) -> bool:
    """`d` é bool (a fila já decidiu) ou uma data: Couto ⇔ data ≥ INICIO (23/03/2026 inclusive)."""
    if isinstance(d, bool):
        return d
    x = iso(d)
    return bool(x and x >= INICIO)


def intercalar(itens: Iterable[T], chave_data: Callable[[T], object], fracao: float | None = None,
               limite: int | None = None) -> list[T]:
    """O lote intercalado: Couto e resto, cada grupo na ordem de entrada, ⌈n·fração⌉ Couto em todo prefixo n.

    `chave_data(item)` → data (str/date) ou bool. `limite` corta o lote E consome `itens` de forma preguiçosa
    (para assim que as duas metades estão cheias) — serve à fila cujo filtro por item é caro. `fracao=None` lê
    `config/foco.yaml`; desligado lá ⇒ a ordem de entrada, intacta."""
    if fracao is None:
        c = config()
        fracao = c["fracao"] if c["ligado"] else 0.0
    fracao = min(1.0, max(0.0, float(fracao)))
    if fracao <= 0:                                    # foco desligado: a ordem de entrada, sem separar grupos
        return list(itertools.islice(itens, limite))
    couto: list[T] = []
    resto: list[T] = []
    q = math.ceil(limite * fracao - 1e-9) if limite is not None else None
    for x in itens:
        if limite is not None and len(couto) >= q and len(resto) >= limite - q:
            break
        if eh_couto(chave_data(x)):
            if limite is None or len(couto) < limite:
                couto.append(x)
        elif limite is None or len(resto) < limite:
            resto.append(x)
    out: list[T] = []
    ic = ir = 0
    while ic < len(couto) or ir < len(resto):
        if limite is not None and len(out) >= limite:
            break
        quero = math.ceil((len(out) + 1) * fracao - 1e-9)      # Couto desejado depois deste item
        if ic < len(couto) and (ic < quero or ir >= len(resto)):
            out.append(couto[ic]); ic += 1
        else:
            out.append(resto[ir]); ir += 1
    return out


def medir(itens: Iterable[T], chave_data: Callable[[T], object]) -> dict:
    """{"n", "couto", "pct"} — para comparar a fila antes × depois."""
    n = c = 0
    for x in itens:
        n += 1
        c += eh_couto(chave_data(x))
    return {"n": n, "couto": c, "pct": round(100.0 * c / n, 1) if n else None}


# ── processo SEI → data do período ──────────────────────────────────────────────────────────────────────────
def _canon(numero) -> str | None:
    from compliance_agent.ob_processo import _canonico, chave_processo
    s = re.sub(r"(\d{6})_(\d+)_(\d{4})", r"\1/\2/\3", str(numero or ""))   # nome de pasta do acervo
    k = chave_processo(s)
    return _canonico(k) if k else None


def _levantar(con: sqlite3.Connection) -> dict[str, str]:
    """{SEI-UUUUUU/NNNNNN/AAAA: última data ≥ INICIO} — OB paga do SIAFE e contratação do espelho TCE-RJ."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    out: dict[str, str] = {}
    for proc, d in con.execute(
            f"SELECT processo, MAX({_OB_ISO}) FROM ob_orcamentaria_siafe WHERE {_ob_paga(con)} "
            f"AND exercicio >= ? AND COALESCE(processo,'') <> '' AND length(data_emissao) = 10 AND {_OB_ISO} >= ? "
            "GROUP BY processo", (int(INICIO[:4]), INICIO)):
        c = _canon(proc)
        if c and d:
            out[c] = max(out.get(c, ""), d)
    try:
        for sn, d in con.execute("SELECT sei_norm, MAX(substr(data_contratacao,1,10)) FROM contratos_tcerj "
                                 "WHERE length(sei_norm) = 16 AND substr(data_contratacao,1,10) >= ? GROUP BY 1",
                                 (INICIO,)):
            c = _canon(f"{sn[:6]}/{sn[6:12]}/{sn[12:]}")
            if c and d:
                out[c] = max(out.get(c, ""), d)
    except sqlite3.Error as e:           # espelho TCE-RJ ausente: segue só com o SIAFE (declarado no log)
        logger.warning("foco: contratos_tcerj indisponível (%s)", type(e).__name__)
    return out


def processos_couto(*, recalcular: bool = False) -> dict[str, str]:
    """Mapa processo → data do período (cache em disco de `CACHE_HORAS` h + memória do processo).
    Sem banco (ou sob pytest sem `JFN_FOCO_DB`) ⇒ {} — nenhuma fila muda de ordem por falta de fonte."""
    db = Path(os.environ.get("JFN_FOCO_DB") or DB)
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("JFN_FOCO_DB"):
        return {}
    agora = time.time()
    if not recalcular and _MEMO.get("db") == str(db) and agora - _MEMO.get("ts", 0) < CACHE_HORAS * 3600:
        return _MEMO["mapa"]
    cache = db.parent / CACHE_NOME
    if not recalcular:
        try:
            d = json.loads(cache.read_text(encoding="utf-8"))
            if d.get("inicio") == INICIO and agora - float(d.get("ts") or 0) < CACHE_HORAS * 3600:
                _MEMO.update(db=str(db), ts=float(d["ts"]), mapa=d["processos"])
                return d["processos"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.debug("foco: cache %s ausente/ilegível (%s) — recalculo", cache, type(e).__name__)
    if not db.exists():
        logger.warning("foco: %s ausente — período Couto INDISPONÍVEL, filas na ordem antiga", db)
        return {}
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
        try:
            con.execute("PRAGMA busy_timeout=15000")
            mapa = _levantar(con)
        finally:
            con.close()
    except sqlite3.Error as e:
        logger.warning("foco: levantamento do período falhou (%s) — filas na ordem antiga", e)
        return {}
    _MEMO.update(db=str(db), ts=agora, mapa=mapa)
    try:
        tmp = cache.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(json.dumps({"ts": agora, "inicio": INICIO, "processos": mapa}), encoding="utf-8")
        tmp.replace(cache)
    except OSError as e:
        logger.warning("foco: cache não gravado (%s)", type(e).__name__)
    return mapa


def data_processo(numero) -> str | None:
    """Data do período Couto do processo SEI (qualquer grafia), ou None se ele não tem OB/contratação no período."""
    c = _canon(numero)
    return processos_couto().get(c) if c else None
