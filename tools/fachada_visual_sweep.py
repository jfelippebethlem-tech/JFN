#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fachada_visual_sweep — classificador VISUAL de fachada em escala sobre os SUSPEITOS de sede.

REUSA o classificador já existente `compliance_agent.verificacao_endereco.classificar_local_por_imagem`
(Mapillary GRÁTIS → satélite Esri GRÁTIS; Street View pago só se `IMG_FONTE_ORDEM` o incluir E houver
cota — este runner NÃO o força). As coords já vêm do sweep Google (`verificacao_sede.geo_lat/geo_lon`),
então NÃO re-geocoda: passa as coords direto ao classificador. Grava `visual_classe/visual_conf/
visual_fonte/visual_em` por CNPJ (INSERT-via-UPDATE, transação curta, busy_timeout=30000).

Alvo padrão: `verificacao_sede WHERE status='INDICIO'` (suspeitos), maior `total_recebido` primeiro.
RESUMÍVEL: pula quem já tem `visual_classe`. VM-safe: load-guard, time-bound, pausa entre alvos.
Honesto: satélite (entorno ±100m) NUNCA acusa (status INDISPONIVEL); só Mapillary/Street View (rente ao
chão) viram INDICIO. Custo: Mapillary token grátis + Gemini pool tier grátis → ZERO cota paga.

CONCORRENTE: `--workers N` (default 5) processa N alvos em paralelo via ThreadPoolExecutor — cada worker
chama `classificar_local_por_imagem` (I/O-bound: Mapillary/Esri/Gemini). O teto real é o rate-limit das APIs
GRÁTIS, não a CPU, então 5-6 é seguro na VM 2-vCPU. Escrita no DB serializada (1 conexão por chamada de
`_grava`, busy_timeout); contadores sob lock; load-guard + time-bound checados entre lotes (resumível).
PRINTS: salva a imagem classificada dos casos FLAGUEADOS em data/fachada_img/<cnpj>.<jpg|png> (reusa os
bytes já baixados, sem re-fetch) e grava o caminho em verificacao_sede.visual_img_path.

Uso:
  PYTHONPATH=. nice -n10 .venv/bin/python -m tools.fachada_visual_sweep \\
      [--status INDICIO] [--limite N] [--max-min 20] [--pausa 0.3] [--workers 5] [--todos]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sqlite3
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ))

_DB = Path(os.environ.get("JFN_DB") or (_RAIZ / "data" / "compliance.db"))
_VISUAIS = ("visual_classe", "visual_conf", "visual_fonte", "visual_em")
_IMG_DIR = _RAIZ / "data" / "fachada_img"

# Classes FLAGUEADAS — salvamos o print só destas (economiza disco; comercial_industrial/galpão não interessa).
_FLAG_PRINT = {"terreno_baldio", "area_aberta_rural", "construcao_precaria_barraco",
               "predio_residencial", "casa_residencial"}


def _carregar_env() -> None:
    """Popula os.environ a partir do .env (igual ao sweep_sede_google): como módulo CLI o .env não está
    carregado e sem MAPILLARY_TOKEN/GEMINI as chamadas viram no-op."""
    for f in (_RAIZ / ".env", Path.home() / ".hermes" / ".env"):
        try:
            for line in Path(f).read_text().splitlines():
                m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$", line)
                if m and not os.environ.get(m.group(1)):
                    os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        except Exception:
            continue


def _garante_colunas(con: sqlite3.Connection) -> None:
    """ALTER TABLE ADD COLUMN idempotente — espelha as colunas visuais de endereco_verificacao."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(verificacao_sede)")}
    tipos = {"visual_classe": "TEXT", "visual_conf": "REAL", "visual_fonte": "TEXT", "visual_em": "TEXT",
             "visual_img_path": "TEXT"}
    for nome, typ in tipos.items():
        if nome not in cols:
            con.execute(f"ALTER TABLE verificacao_sede ADD COLUMN {nome} {typ}")
    con.commit()


def _load_ok(teto: float = 4.0) -> bool:
    try:
        return os.getloadavg()[0] < teto
    except Exception:
        return True


def _alvos(con: sqlite3.Connection, status: str | None, limite: int) -> list[sqlite3.Row]:
    """Suspeitos a classificar: têm geo e ainda NÃO têm visual_classe. Maior valor primeiro."""
    where = ["geo_lat IS NOT NULL", "geo_lon IS NOT NULL",
             "(visual_classe IS NULL OR visual_classe = '')"]
    params: list = []
    if status:
        where.append("status = ?")
        params.append(status)
    lim = f" LIMIT {int(limite)}" if limite else ""
    sql = (f"SELECT cnpj, razao, endereco, municipio, uf, geo_lat, geo_lon, total_recebido, status "
           f"FROM verificacao_sede WHERE {' AND '.join(where)} "
           f"ORDER BY total_recebido DESC{lim}")
    return con.execute(sql, params).fetchall()


def _salva_print(cnpj: str, res: dict) -> str:
    """Salva o print da imagem classificada p/ casos FLAGUEADOS em data/fachada_img/<cnpj>.<ext>. REUSA os
    bytes que o classificador devolveu (`_img_bytes`, sem re-fetch → zero requisição/cota extra). Só salva as
    classes em `_FLAG_PRINT` (poupa disco) — salvo se `FACHADA_SAVE_ALL=1` (guarda a foto de TODOS,
    p/ auditar cada 'ok'). Devolve o caminho relativo salvo, ou '' (não salvou)."""
    if os.environ.get("FACHADA_SAVE_ALL") not in ("1", "true", "True") and (res.get("classe") or "") not in _FLAG_PRINT:
        return ""
    img = res.get("_img_bytes")
    if not img:
        return ""
    ext = "png" if img[:4] == b"\x89PNG" else "jpg"
    try:
        _IMG_DIR.mkdir(parents=True, exist_ok=True)
        cnpj_safe = re.sub(r"\D", "", str(cnpj)) or "sem_cnpj"
        caminho = _IMG_DIR / f"{cnpj_safe}.{ext}"
        caminho.write_bytes(img)
        return str(caminho.relative_to(_RAIZ))
    except Exception:
        return ""


def _grava(cnpj: str, res: dict, img_path: str = "") -> None:
    """Transação CURTA: grava o resultado visual de 1 CNPJ. Cada chamada abre sua PRÓPRIA conexão
    (connect(timeout=30)+busy_timeout=30000) → thread-safe sob ThreadPoolExecutor (NÃO compartilha Connection);
    o busy_timeout serializa os writers concorrentes. Persiste sempre (até INDISPONIVEL/indeterminado) p/ ser
    resumível e não retentar à toa."""
    con = sqlite3.connect(str(_DB), timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        con.execute(
            "UPDATE verificacao_sede SET visual_classe=?, visual_conf=?, visual_fonte=?, visual_em=?, "
            "visual_img_path=? WHERE cnpj=?",
            (res.get("classe") or "", float(res.get("confianca") or 0.0), res.get("fonte") or "",
             dt.datetime.now().isoformat(timespec="seconds"), img_path or None, cnpj))
        con.commit()
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Classificador visual de fachada (reusa classificar_local_por_imagem)")
    ap.add_argument("--status", default="INDICIO",
                    help="status alvo em verificacao_sede (default INDICIO; vazio/'' = qualquer)")
    ap.add_argument("--todos", action="store_true", help="qualquer status (ignora --status)")
    ap.add_argument("--limite", type=int, default=0, help="máx. de alvos (0 = todos os pendentes)")
    ap.add_argument("--max-min", type=float, default=20.0, help="time-bound em minutos (default 20)")
    ap.add_argument("--pausa", type=float, default=0.3, help="pausa entre rodadas de submissão (s)")
    ap.add_argument("--load-teto", type=float, default=4.0, help="abortar se load1 ≥ este valor")
    ap.add_argument("--workers", type=int, default=5,
                    help="workers concorrentes (default 5; teto real = rate-limit das APIs grátis, não CPU)")
    a = ap.parse_args()
    _carregar_env()

    # Não forçar o Street View pago: se o dono não definiu IMG_FONTE_ORDEM, fica só Mapillary (grátis).
    # O satélite Esri (grátis) é fallback automático interno. Quem quiser SV define IMG_FONTE_ORDEM e a cota.
    os.environ.setdefault("IMG_FONTE_ORDEM", "mapillary")

    if not os.environ.get("MAPILLARY_TOKEN", "").strip():
        print("[fachada_visual] ⚠ sem MAPILLARY_TOKEN — só satélite (entorno) disponível.", flush=True)

    from compliance_agent.verificacao_endereco import classificar_local_por_imagem  # noqa: E402

    con = sqlite3.connect(str(_DB), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    _garante_colunas(con)
    status = None if a.todos else (a.status or None)
    alvos = _alvos(con, status, a.limite)
    con.close()

    print(f"[fachada_visual] {len(alvos)} alvo(s) pendente(s) "
          f"(status={'qualquer' if status is None else status}, maior R$ primeiro). "
          f"time-bound={a.max_min:.0f}min · workers={a.workers}", flush=True)
    if not alvos:
        print("[fachada_visual] nada a fazer (todos já classificados).", flush=True)
        return 0

    t0 = time.time()
    limite_s = a.max_min * 60.0
    dist: Counter = Counter()
    achados: list[str] = []
    indicio = {"terreno_baldio", "area_aberta_rural", "construcao_precaria_barraco"}
    lock = threading.Lock()       # protege os contadores compartilhados (dist/achados/feitos/salvos)
    parar = threading.Event()     # sinaliza time-bound/load p/ os workers não pegarem novos alvos
    estado = {"feitos": 0, "salvos": 0}

    def _processa(r: sqlite3.Row) -> None:
        """1 alvo: classifica (retornar_imagem=True p/ salvar o print sem re-fetch), salva print FLAGUEADO,
        grava no DB (conexão própria). Roda em thread do pool. O estado de módulo de verificacao_endereco
        no caminho de imagem (Mapillary/Esri/VLM) NÃO toca _backoff/_cache/_ult_nominatim (esses são só do
        geocode/Overpass, fora deste fluxo) → thread-safe sem lock extra."""
        end = ", ".join(x for x in [r["endereco"], r["municipio"], r["uf"]] if x)
        try:
            res = classificar_local_por_imagem(r["geo_lat"], r["geo_lon"], end, retornar_imagem=True)
        except Exception as e:  # noqa: BLE001
            res = {"classe": "", "confianca": 0.0, "fonte": "", "evidencia": f"erro: {str(e)[:60]}"}
        img_path = _salva_print(r["cnpj"], res)
        _grava(r["cnpj"], res, img_path)
        classe = res.get("classe") or "(sem imagem/VLM)"
        with lock:
            estado["feitos"] += 1
            dist[classe] += 1
            if img_path:
                estado["salvos"] += 1
            if res.get("classe") in indicio and res.get("status") == "INDICIO":
                linha = (f"  → {res.get('classe')} (conf {float(res.get('confianca') or 0):.0%}) "
                         f"R$ {r['total_recebido']:,.0f} · {r['razao'][:40]} · {end[:60]}"
                         + (f" · print={img_path}" if img_path else ""))
                achados.append(linha)
                print(linha, flush=True)
            if estado["feitos"] % 25 == 0:
                print(f"  ...{estado['feitos']} feitos · {time.time() - t0:.0f}s · "
                      f"dist={dict(dist)}", flush=True)

    # Submissão por LOTES do tamanho do pool: antes de cada lote checa time-bound + load (parada limpa,
    # resumível — quem ficou sem visual_classe entra no próximo ciclo). Mantém ≤ workers chamadas em voo.
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        it = iter(alvos)
        pendentes = set()
        esgotado = False
        while not esgotado or pendentes:
            if not parar.is_set():
                if time.time() - t0 >= limite_s:
                    print(f"[fachada_visual] time-bound {a.max_min:.0f}min atingido — parada limpa.", flush=True)
                    parar.set()
                elif not _load_ok(a.load_teto):
                    print(f"[fachada_visual] load1 ≥ {a.load_teto} — parada limpa (retoma no próximo ciclo).",
                          flush=True)
                    parar.set()
            # repõe o pool até `workers` em voo (se não estamos parando e ainda há alvos)
            while not parar.is_set() and not esgotado and len(pendentes) < max(1, a.workers):
                try:
                    pendentes.add(ex.submit(_processa, next(it)))
                except StopIteration:
                    esgotado = True
            if not pendentes:
                break
            # espera ao menos um terminar antes de repor (não busy-wait)
            for fut in as_completed(list(pendentes), timeout=None):
                pendentes.discard(fut)
                break
            if parar.is_set():
                # drena o que já está em voo e encerra (não submete mais)
                esgotado = True
            elif a.pausa:
                time.sleep(a.pausa)

    feitos = estado["feitos"]
    print(f"\n[fachada_visual] CONCLUÍDO ciclo: {feitos} classificado(s) em {time.time() - t0:.0f}s "
          f"({estado['salvos']} print(s) salvos em data/fachada_img/)", flush=True)
    print(f"[fachada_visual] distribuição: {dict(dist)}", flush=True)
    if achados:
        print(f"[fachada_visual] {len(achados)} INDÍCIO(s) rente ao chão (baldio/barraco/rural):", flush=True)
        for l in achados:
            print(l, flush=True)
    else:
        print("[fachada_visual] nenhum indício rente ao chão neste ciclo.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
