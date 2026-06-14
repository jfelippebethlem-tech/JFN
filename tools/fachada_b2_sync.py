#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fachada_b2_sync — guarda a foto de fachada dos FLAGUEADOS no Backblaze B2 (sem peso na VM).

Hoje a foto de fachada é EFÊMERA (baixada, classificada por `fachada_visual_sweep` e descartada;
`data/fachada_img/` fica vazio). O dono quer GUARDAR essas fotos no B2 (acesso da equipe, fora da
VM) e USÁ-las nos relatórios. Este runner fecha a primeira metade:

  Para cada CNPJ de `verificacao_sede` cujo `visual_classe` está numa das classes FLAGUEADAS
  (terreno_baldio / area_aberta_rural / construcao_precaria_barraco / casa_residencial /
  predio_residencial) e que ainda NÃO tem objeto no B2 (`visual_img_b2` vazio):
    1. pega a imagem REUSANDO `verificacao_endereco.classificar_local_por_imagem(..., retornar_imagem=True)`
       — Mapillary (grátis) → satélite Esri (grátis); ZERO cota paga (Street View só se IMG_FONTE_ORDEM
       o incluir e houver cota; este runner NÃO o força);
    2. grava num arquivo TEMPORÁRIO, faz `rclone copy` p/ `b2:<bucket>/fachadas/<cnpj>.<jpg|png>`,
       e REMOVE o temp (o ponto é tirar peso da VM — nada de imagem permanente local);
    3. grava o caminho do objeto na coluna NOVA `visual_img_b2` (ALTER TABLE idempotente).

Maior `total_recebido` primeiro (o tail de alto valor importa mais). RESUMÍVEL: pula quem já tem
`visual_img_b2`. VM-safe: `--limite`, `--max-min` time-bound, load-guard, pausa entre alvos. Honesto:
se o fetch não devolver imagem, NÃO inventa — registra e segue (não marca `visual_img_b2`, reentra
no próximo ciclo). Se o `rclone`/B2 falhar, loga e segue (resumível).

Uso:
  PYTHONPATH=. nice -n10 .venv/bin/python -m tools.fachada_b2_sync \\
      [--limite N] [--max-min 20] [--pausa 0.3] [--cnpj 28470707000180] [--load-teto 4]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ))

_DB = Path(os.environ.get("JFN_DB") or (_RAIZ / "data" / "compliance.db"))

# Remote/bucket/prefixo do B2 (já configurado e testado pelo dono). Override por env, p/ teste/portabilidade.
_RCLONE = os.environ.get("RCLONE_BIN") or str(Path.home() / ".local" / "bin" / "rclone")
_B2_REMOTE = os.environ.get("FACHADA_B2_REMOTE", "b2")
_B2_BUCKET = os.environ.get("FACHADA_B2_BUCKET", "jfn-backup-jorge")
_B2_PREFIXO = os.environ.get("FACHADA_B2_PREFIXO", "fachadas")

# Classes FLAGUEADAS (mesma lista do pedido do dono e do _FLAG_PRINT do fachada_visual_sweep + residenciais).
_FLAG = ("terreno_baldio", "area_aberta_rural", "construcao_precaria_barraco",
         "casa_residencial", "predio_residencial")


def _carregar_env() -> None:
    """Popula os.environ a partir do .env — como módulo CLI o .env não está carregado e sem MAPILLARY_TOKEN
    o fetch vira no-op silencioso (lição §8: todo sweep/CLI novo TEM que carregar o .env)."""
    for f in (_RAIZ / ".env", Path.home() / ".hermes" / ".env"):
        try:
            for line in Path(f).read_text().splitlines():
                m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$", line)
                if m and not os.environ.get(m.group(1)):
                    os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        except Exception:  # noqa: BLE001
            continue


def _garante_coluna(con: sqlite3.Connection) -> None:
    """ALTER TABLE ADD COLUMN idempotente — adiciona visual_img_b2 (caminho do objeto no B2)."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(verificacao_sede)")}
    if "visual_img_b2" not in cols:
        con.execute("ALTER TABLE verificacao_sede ADD COLUMN visual_img_b2 TEXT")
    con.commit()


def _load_ok(teto: float) -> bool:
    try:
        return os.getloadavg()[0] < teto
    except Exception:  # noqa: BLE001
        return True


def _alvos(con: sqlite3.Connection, limite: int, cnpj: str | None) -> list[sqlite3.Row]:
    """FLAGUEADOS com geo e SEM objeto no B2. Maior R$ primeiro. `--cnpj` foca 1 alvo (ignora o filtro de B2
    p/ permitir re-sync explícito de um caso, ex.: backfill do IDESI)."""
    ph = ",".join("?" * len(_FLAG))
    where = [f"visual_classe IN ({ph})", "geo_lat IS NOT NULL", "geo_lon IS NOT NULL"]
    params: list = list(_FLAG)
    if cnpj:
        where.append("cnpj = ?")
        params.append(cnpj)
    else:
        where.append("(visual_img_b2 IS NULL OR visual_img_b2 = '')")
    lim = f" LIMIT {int(limite)}" if limite else ""
    sql = (f"SELECT cnpj, razao, endereco, municipio, uf, geo_lat, geo_lon, total_recebido, "
           f"visual_classe, visual_img_b2 FROM verificacao_sede WHERE {' AND '.join(where)} "
           f"ORDER BY total_recebido DESC{lim}")
    return con.execute(sql, params).fetchall()


def _subir_b2(img: bytes, cnpj: str) -> tuple[str, int]:
    """Grava a imagem num TEMP, `rclone copy` p/ o B2, REMOVE o temp. Devolve (caminho_objeto, bytes) ou
    ('', 0) se falhar. NÃO deixa nada permanente na VM (o ponto é tirar peso)."""
    cnpj_safe = re.sub(r"\D", "", str(cnpj)) or "sem_cnpj"
    ext = "png" if img[:4] == b"\x89PNG" else "jpg"
    objeto = f"{_B2_PREFIXO}/{cnpj_safe}.{ext}"
    destino = f"{_B2_REMOTE}:{_B2_BUCKET}/{objeto}"
    tmp = None
    try:
        # delete=False p/ fechar o handle antes do rclone ler (Linux ok, mas é o padrão seguro/portável).
        with tempfile.NamedTemporaryFile(prefix=f"fachada_{cnpj_safe}_", suffix=f".{ext}", delete=False) as fh:
            fh.write(img)
            tmp = fh.name
        # rclone copyto: copia o arquivo local p/ o caminho EXATO do objeto (copy copiaria com o basename do temp).
        r = subprocess.run([_RCLONE, "copyto", tmp, destino],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"  ⚠ rclone copyto falhou (rc={r.returncode}) p/ {cnpj}: {r.stderr.strip()[:160]}", flush=True)
            return "", 0
        return objeto, len(img)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ erro ao subir {cnpj} p/ B2: {str(e)[:160]}", flush=True)
        return "", 0
    finally:
        if tmp:
            try:
                os.unlink(tmp)  # tira o peso: nada permanente na VM
            except OSError:
                pass


def _grava(cnpj: str, objeto: str) -> None:
    """Transação CURTA: grava visual_img_b2 do CNPJ. Conexão própria + busy_timeout (sweep_sede grava no
    MESMO DB) — espera o lock, não erra (lição §8)."""
    con = sqlite3.connect(str(_DB), timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("UPDATE verificacao_sede SET visual_img_b2=? WHERE cnpj=?", (objeto, cnpj))
        con.commit()
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync das fotos de fachada FLAGUEADAS p/ o Backblaze B2 (VM-safe).")
    ap.add_argument("--limite", type=int, default=0, help="máx. de alvos (0 = todos os pendentes)")
    ap.add_argument("--max-min", type=float, default=20.0, help="time-bound em minutos (default 20)")
    ap.add_argument("--pausa", type=float, default=0.3, help="pausa entre alvos (s)")
    ap.add_argument("--load-teto", type=float, default=4.0, help="abortar se load1 ≥ este valor")
    ap.add_argument("--cnpj", default="", help="focar 1 CNPJ (re-sync explícito, ex.: backfill do IDESI)")
    a = ap.parse_args()
    _carregar_env()

    # NÃO forçar o Street View pago (igual ao fachada_visual_sweep): default só Mapillary (grátis).
    os.environ.setdefault("IMG_FONTE_ORDEM", "mapillary")

    if not Path(_RCLONE).exists():
        print(f"[fachada_b2] ⛔ rclone não encontrado em {_RCLONE} (defina RCLONE_BIN). Abortando.", flush=True)
        return 2
    if not os.environ.get("MAPILLARY_TOKEN", "").strip():
        print("[fachada_b2] ⚠ sem MAPILLARY_TOKEN — só satélite (entorno); muitos casos não terão imagem.", flush=True)

    from compliance_agent.verificacao_endereco import classificar_local_por_imagem  # noqa: E402

    con = sqlite3.connect(str(_DB), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    _garante_coluna(con)
    alvos = _alvos(con, a.limite, (a.cnpj or "").strip() or None)
    con.close()

    print(f"[fachada_b2] {len(alvos)} alvo(s) FLAGUEADO(s) sem foto no B2 "
          f"(destino {_B2_REMOTE}:{_B2_BUCKET}/{_B2_PREFIXO}/, maior R$ primeiro). "
          f"time-bound={a.max_min:.0f}min", flush=True)
    if not alvos:
        print("[fachada_b2] nada a fazer (todos já sincronizados).", flush=True)
        return 0

    t0 = time.time()
    limite_s = a.max_min * 60.0
    dist: Counter = Counter()
    feitos = subidos = bytes_tot = sem_img = 0

    for r in alvos:
        if time.time() - t0 >= limite_s:
            print(f"[fachada_b2] time-bound {a.max_min:.0f}min atingido — parada limpa (resumível).", flush=True)
            break
        if not _load_ok(a.load_teto):
            print(f"[fachada_b2] load1 ≥ {a.load_teto} — parada limpa (retoma no próximo ciclo).", flush=True)
            break
        feitos += 1
        end = ", ".join(x for x in [r["endereco"], r["municipio"], r["uf"]] if x)
        try:
            res = classificar_local_por_imagem(r["geo_lat"], r["geo_lon"], end, retornar_imagem=True)
        except Exception as e:  # noqa: BLE001
            res = {"_img_bytes": None, "_img_fonte": "", "evidencia": f"erro: {str(e)[:60]}"}
        img = res.get("_img_bytes")
        if not img:
            sem_img += 1
            print(f"  · sem imagem p/ {r['cnpj']} ({r['visual_classe']}) {r['razao'][:40]} — "
                  f"reentra no próximo ciclo (não marcado).", flush=True)
            if a.pausa:
                time.sleep(a.pausa)
            continue
        objeto, nb = _subir_b2(img, r["cnpj"])
        if objeto:
            _grava(r["cnpj"], objeto)
            subidos += 1
            bytes_tot += nb
            dist[res.get("_img_fonte") or "?"] += 1
            print(f"  ✓ {r['cnpj']} ({r['visual_classe']}, {res.get('_img_fonte')}) "
                  f"R$ {r['total_recebido']:,.0f} · {r['razao'][:38]} → b2:{_B2_BUCKET}/{objeto} ({nb/1024:.0f} KB)",
                  flush=True)
        if a.pausa:
            time.sleep(a.pausa)

    print(f"\n[fachada_b2] CONCLUÍDO ciclo {dt.datetime.now().isoformat(timespec='seconds')}: "
          f"{feitos} processado(s) · {subidos} subido(s) ao B2 · {sem_img} sem imagem · "
          f"{bytes_tot/1024/1024:.2f} MB · {time.time() - t0:.0f}s", flush=True)
    if dist:
        print(f"[fachada_b2] fontes: {dict(dist)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
