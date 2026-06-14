#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fachada_streetview_sweep — fachada das sedes SUSPEITAS via **Google Street View (Maps Embed API)**.

A fonte de imagem foi MIGRADA de Mapillary/Esri (aposentados: cobertura ruim, fotos efêmeras apagadas)
para o **Google Street View servido pela Maps Embed API** — GRÁTIS/ilimitada e que NÃO consome a cota
Static/Geocode (que estão no teto). Provado: renderizar a Embed NUM IFRAME servido por um servidor HTTP
local (navegação DIRETA dá "must be used in an iframe") + `referrerpolicy=no-referrer-when-downgrade`,
e screenshotar o elemento iframe. Validador rejeita imagem >60% branca (= tela de erro/API-off).

PIPELINE por alvo (`verificacao_sede status='INDICIO'` com geo, maior `total_recebido` primeiro):
  1. RENDER Street View Embed (VM-safe, ver abaixo) → valida (rejeita branca/cinza/pequena);
  2. SOBE p/ nuvem via `compliance_agent.fachada_remotes` (R2 primário → B2 transbordo, teto 9,5GB) e grava
     a localização completa (`remote:bucket/objeto`) em `visual_img_b2` — NÃO deixa imagem na VM;
  3. RECLASSIFICA com o VLM (Gemini pool, grátis) a foto NOVA → `visual_classe`/`visual_conf`/
     `visual_fonte='street_view_embed'` (SUBSTITUI a classe antiga do Mapillary, agora confiável);
  4. CRUZA a foto com o negócio do Google (`places_achou`/`places_nome`): a foto CONFIRMA o comércio ou
     CONTRADIZ (baldio/residência/rural)? Grava `coerencia_google` ('confirma'/'contradiz'/'indeterminado')
     + `coerencia_nota`. Contradição = indício reforçado.

DEDUP por PRÉDIO (`predio_key`): renderiza 1× por prédio; os co-localizados herdam o mesmo resultado
(NÃO re-renderiza o mesmo lugar). RESUMÍVEL: pula quem já tem `visual_fonte='street_view_embed'`.

⚠ PROTEÇÃO MÁXIMA DA VM (2 vCPU · 7,8GB · SEM SWAP — render WebGL já travou esta VM antes):
  - UM render por vez (serial). Gate ANTES de cada: mem livre ≥1,5GB E load1 ≤3 → senão espera/aborta.
  - Render em SUBPROCESSO: `timeout 30` + `systemd-run --user --scope -p MemoryMax=2G -p MemorySwapMax=0
    nice -n10 ...` (cap de RAM REAL via cgroup-v2; `ulimit -v` NÃO serve — Chromium reserva GBs virtuais).
  - headless `--use-gl=swiftshader`. Mede load/mem antes e depois.

Uso:
  PYTHONPATH=. nice -n10 .venv/bin/python -m tools.fachada_streetview_sweep \\
      [--status INDICIO] [--limite N] [--max-min 20] [--pausa 1.0] [--cnpj 28470707000180] \\
      [--load-teto 3] [--mem-min 1500] [--so-coerencia]
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

# Política de storage SOMADO (R2 primário + B2 transbordo, cada foto em 1 bucket, teto 9,5GB). Fonte única.
from compliance_agent import fachada_remotes as fr  # noqa: E402

_RCLONE = fr.rclone_bin()

# ── Proteção da VM (mesmos parâmetros do protótipo streetview_embed_proto) ──
_MEM_LIVRE_MIN_MB = int(os.environ.get("SV_MEM_MIN_MB", "1500"))
_LOAD_MAX = float(os.environ.get("SV_LOAD_MAX", "3.0"))
_MEM_MAX = os.environ.get("SV_MEM_MAX", "2G")        # cap de RAM REAL do cgroup
_RENDER_TIMEOUT_S = int(os.environ.get("SV_RENDER_TIMEOUT", "30"))
_NICE = 10

# Marcador da nova fonte (substitui o Mapillary/Esri) — usado p/ resumir (pula quem já foi).
_FONTE_SV = "street_view_embed"

# Classes do VLM que indicam fachada/inexistência operacional (rente ao chão = pode ACUSAR).
_CLASSE_INDICIO = {"terreno_baldio", "area_aberta_rural", "construcao_precaria_barraco"}
_CLASSE_RESID = {"casa_residencial", "predio_residencial"}
_CLASSE_COMERCIAL = {"comercial_industrial", "galpao_logistico"}


def _carregar_env() -> None:
    """Popula os.environ a partir do .env — como módulo CLI o .env não está carregado e sem GOOGLE_MAPS_KEY/
    Gemini as chamadas viram no-op silencioso (lição §8: todo sweep/CLI novo TEM que carregar o .env)."""
    for f in (_RAIZ / ".env", Path.home() / ".hermes" / ".env"):
        try:
            for line in Path(f).read_text().splitlines():
                m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$", line)
                if m and not os.environ.get(m.group(1)):
                    os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        except Exception:  # noqa: BLE001
            continue


def _garante_colunas(con: sqlite3.Connection) -> None:
    """ALTER TABLE ADD COLUMN idempotente — colunas visuais + coerência foto-vs-Google."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(verificacao_sede)")}
    tipos = {"visual_classe": "TEXT", "visual_conf": "REAL", "visual_fonte": "TEXT", "visual_em": "TEXT",
             "visual_img_path": "TEXT", "visual_img_b2": "TEXT",
             "coerencia_google": "TEXT", "coerencia_nota": "TEXT"}
    for nome, typ in tipos.items():
        if nome not in cols:
            con.execute(f"ALTER TABLE verificacao_sede ADD COLUMN {nome} {typ}")
    con.commit()


def _mem_livre_mb() -> int:
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1]) // 1024
    except Exception:  # noqa: BLE001
        pass
    return -1


def _load1() -> float:
    try:
        return os.getloadavg()[0]
    except Exception:  # noqa: BLE001
        return 0.0


def _snap() -> str:
    return f"load1={_load1():.2f} mem_livre={_mem_livre_mb()}MB"


def _gate(mem_min: int, load_max: float, esperas: int = 6, pausa_s: float = 10.0) -> bool:
    """Espera até mem livre ≥ mem_min E load1 ≤ load_max (até `esperas` tentativas). True se liberou."""
    for _ in range(max(1, esperas)):
        livre, load = _mem_livre_mb(), _load1()
        if (livre < 0 or livre >= mem_min) and load <= load_max:
            return True
        print(f"  · GATE aguardando ({_snap()}; precisa mem≥{mem_min}MB, load≤{load_max}) — pausa {pausa_s:.0f}s",
              flush=True)
        time.sleep(pausa_s)
    return False


# ── Alvos: suspeitos com geo, dedup por prédio, maior R$ primeiro ──────────────
def _alvos(con: sqlite3.Connection, status: str | None, limite: int, cnpj: str | None) -> list[sqlite3.Row]:
    """Suspeitos a renderizar: têm geo e ainda NÃO têm a foto Street View Embed (visual_fonte != marcador).
    `--cnpj` foca 1 alvo (re-render explícito; ignora o filtro de 'já feito'). Maior R$ primeiro."""
    where = ["geo_lat IS NOT NULL", "geo_lon IS NOT NULL"]
    params: list = []
    if cnpj:
        where.append("cnpj = ?")
        params.append(cnpj)
    else:
        where.append("(visual_fonte IS NULL OR visual_fonte <> ?)")
        params.append(_FONTE_SV)
        if status:
            where.append("status = ?")
            params.append(status)
    lim = f" LIMIT {int(limite)}" if limite else ""
    sql = (f"SELECT cnpj, predio_key, razao, endereco, municipio, uf, geo_lat, geo_lon, total_recebido, "
           f"status, places_achou, places_nome, places_endereco "
           f"FROM verificacao_sede WHERE {' AND '.join(where)} "
           f"ORDER BY total_recebido DESC{lim}")
    return con.execute(sql, params).fetchall()


# ── 1) RENDER Street View Embed (iframe + HTTP local) — subprocesso interno ────
_RENDER_SRC = r'''
import os, sys, tempfile, functools, http.server, socketserver, threading
key = os.environ.get("GOOGLE_MAPS_KEY", "").strip()
if not key:
    print("ERRO: GOOGLE_MAPS_KEY ausente", file=sys.stderr); raise SystemExit(3)
lat, lon, heading, out = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
url = (f"https://www.google.com/maps/embed/v1/streetview?key={key}"
       f"&location={lat},{lon}&heading={heading}&pitch=0&fov=80")
d = tempfile.mkdtemp()
open(os.path.join(d, "index.html"), "w").write(
    '<!doctype html><html><head><meta charset="utf-8">'
    '<style>html,body{margin:0}#f{border:0;width:640px;height:480px}</style></head>'
    '<body><iframe id="f" referrerpolicy="no-referrer-when-downgrade" src="' + url + '"></iframe></body></html>')
H = functools.partial(http.server.SimpleHTTPRequestHandler, directory=d)
srv = socketserver.TCPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
try:
    from playwright.sync_api import sync_playwright
except Exception as e:
    print(f"ERRO: playwright indisponivel: {e}", file=sys.stderr); raise SystemExit(4)
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=[
        "--no-sandbox", "--disable-dev-shm-usage", "--use-gl=swiftshader",
        "--disable-extensions", "--js-flags=--max-old-space-size=512"])
    try:
        pg = b.new_page(viewport={"width": 680, "height": 520})
        pg.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle", timeout=25000)
        pg.wait_for_timeout(6000)   # deixa o panorama desenhar (swiftshader)
        el = pg.query_selector("#f")
        if el is None:
            print("ERRO: iframe ausente", file=sys.stderr); raise SystemExit(5)
        el.screenshot(path=out)
    finally:
        b.close()
raise SystemExit(0)
'''


def _render_protegido(lat: float, lon: float, heading: float, out: Path,
                      mem_min: int, load_max: float) -> dict:
    """Gate (mem/load) + render num SUBPROCESSO com cap de RAM REAL do cgroup (systemd-run) + timeout.
    Devolve {ok, rc, antes, depois, stderr, motivo}. NÃO importa playwright no processo-pai (mantém leve)."""
    antes = _snap()
    if not _gate(mem_min, load_max):
        return {"ok": False, "skip": True, "antes": antes, "depois": _snap(),
                "motivo": f"GATE não liberou (mem≥{mem_min}MB/load≤{load_max}); adia (resumível)"}
    cmd = ["timeout", str(_RENDER_TIMEOUT_S),
           "systemd-run", "--user", "--scope", "--quiet",
           "-p", f"MemoryMax={_MEM_MAX}", "-p", "MemorySwapMax=0",
           "nice", f"-n{_NICE}",
           sys.executable, "-c", _RENDER_SRC, str(lat), str(lon), str(heading), str(out)]
    rc, err = None, ""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_RENDER_TIMEOUT_S + 12)
        rc, err = proc.returncode, (proc.stderr or "")[-400:]
    except subprocess.TimeoutExpired:
        rc, err = 124, "subprocess.run estourou (teardown lento)"
    depois = _snap()
    res = {"antes": antes, "depois": depois, "rc": rc, "stderr": err.strip()}
    if rc == 124:
        res.update(ok=False, travou=True, motivo="RENDER MATADO pelo `timeout` — PROTEÇÃO ATUOU")
        return res
    if rc != 0:
        oom = " (provável OOM do cgroup → morto)" if rc in (137, 139) else ""
        res.update(ok=False, oom=rc in (137, 139), motivo=f"render rc={rc}{oom}")
        return res
    res.update(ok=True, motivo="render concluído")
    return res


# ── Validação: rejeita imagem >60% branca (tela de erro/API-off) ───────────────
def _validar(path: Path, branco_max: float = 0.60) -> dict:
    """Rejeita branca (>branco_max), monocromática/cinza, ou muito pequena. Pillow se disponível."""
    if not path.exists():
        return {"ok": False, "motivo": "arquivo não gerado"}
    n = path.stat().st_size
    if n < 4096:
        return {"ok": False, "bytes": n, "motivo": f"muito pequeno ({n} B) — tela de erro/vazia"}
    head = path.read_bytes()[:8]
    if head[:3] != b"\xff\xd8\xff" and head[:4] != b"\x89PNG":
        return {"ok": False, "bytes": n, "motivo": "não é JPEG/PNG válido"}
    try:
        import io

        from PIL import Image
        im = Image.open(io.BytesIO(path.read_bytes())).convert("RGB").resize((64, 64))
        px = list(im.getdata())  # 64x64=4096 px; suficiente p/ a heurística de branco/variância
        media = tuple(sum(c[i] for c in px) / len(px) for i in range(3))
        var = sum((c[0] - media[0]) ** 2 + (c[1] - media[1]) ** 2 + (c[2] - media[2]) ** 2
                  for c in px) / len(px)
        branco = sum(1 for c in px if c[0] > 240 and c[1] > 240 and c[2] > 240) / len(px)
        cinza = abs(media[0] - media[1]) < 8 and abs(media[1] - media[2]) < 8
        if branco > branco_max:
            return {"ok": False, "bytes": n, "var": round(var, 1), "branco": round(branco, 2),
                    "motivo": f"{branco:.0%} de pixels brancos (> {branco_max:.0%}) — tela de ERRO, não Street View"}
        if var < 120 or (cinza and var < 400):
            return {"ok": False, "bytes": n, "var": round(var, 1), "branco": round(branco, 2),
                    "motivo": f"imagem monocromática/cinza (var={var:.0f}) — provável tela de erro"}
        return {"ok": True, "bytes": n, "var": round(var, 1), "branco": round(branco, 2),
                "motivo": "Street View plausível (colorido, não-branco)"}
    except Exception:  # noqa: BLE001
        return {"ok": n > 30000, "bytes": n, "motivo": f"sem Pillow; só tamanho ({n} B)"}


# ── 2) Sobe p/ nuvem (R2→B2) ──────────────────────────────────────────────────
def _subir_foto(img: bytes, cnpj: str, sel: "fr.SelecionadorRemote") -> tuple[str, int]:
    """Escolhe o remote sob o teto (R2 primário → transbordo B2), grava num TEMP, `rclone copyto`, remove o
    temp. Devolve (localizacao_completa 'remote:bucket/objeto', bytes) ou ('', 0). Nada permanente na VM."""
    destino_rb = sel.escolher(len(img))
    if not destino_rb:
        print(f"  ⛔ R2 e B2 sob o teto — sem espaço p/ {cnpj} ({len(img)/1024:.0f} KB).", flush=True)
        return "", 0
    cnpj_safe = re.sub(r"\D", "", str(cnpj)) or "sem_cnpj"
    ext = "png" if img[:4] == b"\x89PNG" else "jpg"
    destino = f"{destino_rb}/{fr.objeto_de(cnpj_safe, ext)}"
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f"sv_{cnpj_safe}_", suffix=f".{ext}", delete=False) as fh:
            fh.write(img)
            tmp = fh.name
        r = subprocess.run([_RCLONE, "copyto", tmp, destino], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"  ⚠ rclone copyto falhou (rc={r.returncode}) {cnpj} → {destino}: "
                  f"{r.stderr.strip()[:160]}", flush=True)
            return "", 0
        sel.confirmar(destino, len(img))
        return destino, len(img)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ erro ao subir {cnpj} → {destino}: {str(e)[:160]}", flush=True)
        return "", 0
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ── 4) Coerência foto-vs-Google (avaliada por regra sobre a classe do VLM) ─────
def coerencia_foto_google(classe: str, places_achou, places_nome: str) -> tuple[str, str]:
    """Cruza a CLASSE visual (Street View, foto nova) com o que o Google diz do negócio na sede.

    - Se o Google ACHOU empresa operando (places_achou=1, places_nome) e a foto mostra COMÉRCIO/edificação
      compatível → 'confirma'. Se a foto mostra baldio/rural/residência → 'contradiz' (indício reforçado:
      o Google diz que há empresa, mas a sede física não condiz).
    - Se o Google NÃO achou negócio: foto comercial não confirma nem contradiz (Places tem buracos) →
      'indeterminado'; foto baldio/rural reforça a ausência de operação → 'contradiz' (fraco).
    Devolve (coerencia, nota). coerencia ∈ {'confirma','contradiz','indeterminado'}."""
    classe = (classe or "").strip().lower()
    tem_negocio = bool(places_achou) and bool((places_nome or "").strip())
    nome = (places_nome or "").strip()
    if classe in _CLASSE_INDICIO or classe in _CLASSE_RESID:
        humano = classe.replace("_", " ")
        if tem_negocio:
            return ("contradiz",
                    f"O Google registra negócio operando na sede ('{nome}'), mas a foto de rua (Street View) "
                    f"mostra **{humano}** — incompatível com operação empresarial. Contradição reforça o indício "
                    "de fachada/inexistência operacional (confirmar in loco).")
        return ("contradiz",
                f"A foto de rua (Street View) mostra **{humano}** e o Google não registra negócio operando na "
                "sede — ambos apontam ausência de operação empresarial no endereço (indício; confirmar in loco).")
    if classe in _CLASSE_COMERCIAL:
        if tem_negocio:
            return ("confirma",
                    f"A foto de rua (Street View) mostra área comercial/edificada compatível com a operação, "
                    f"e o Google registra negócio na sede ('{nome}') — coerente com sede real.")
        return ("indeterminado",
                "A foto de rua mostra área comercial/edificada (compatível com sede real), mas o Google não "
                "registra negócio na sede — Places tem cobertura incompleta; não conclui contradição.")
    # indeterminado/sem classe
    return ("indeterminado",
            "Classificação visual inconclusiva (imagem ambígua) — não dá p/ confirmar nem contradizer o "
            "registro do Google na sede.")


# ── Persistência (transação curta, busy_timeout) ───────────────────────────────
def _grava(cnpj: str, dados: dict) -> None:
    con = sqlite3.connect(str(_DB), timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        con.execute(
            "UPDATE verificacao_sede SET visual_classe=?, visual_conf=?, visual_fonte=?, visual_em=?, "
            "visual_img_b2=?, coerencia_google=?, coerencia_nota=? WHERE cnpj=?",
            (dados.get("classe") or "", float(dados.get("conf") or 0.0), dados.get("fonte") or "",
             dt.datetime.now().isoformat(timespec="seconds"), dados.get("img_b2") or None,
             dados.get("coerencia") or None, dados.get("coerencia_nota") or None, cnpj))
        con.commit()
    finally:
        con.close()


def _herda_predio(predio_key: str, dados: dict, cnpj_origem: str) -> int:
    """Replica o resultado da foto p/ os CO-LOCALIZADOS no mesmo prédio (mesma foto serve; NÃO re-renderiza).
    Só herda quem ainda não tem a foto Street View (resumível). Devolve quantos herdaram."""
    if not predio_key:
        return 0
    con = sqlite3.connect(str(_DB), timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        cur = con.execute(
            "UPDATE verificacao_sede SET visual_classe=?, visual_conf=?, visual_fonte=?, visual_em=?, "
            "visual_img_b2=?, coerencia_google=?, coerencia_nota=? "
            "WHERE predio_key=? AND cnpj<>? AND (visual_fonte IS NULL OR visual_fonte <> ?)",
            (dados.get("classe") or "", float(dados.get("conf") or 0.0), _FONTE_SV,
             dt.datetime.now().isoformat(timespec="seconds"), dados.get("img_b2") or None,
             dados.get("coerencia") or None,
             (dados.get("coerencia_nota") or "") + " [herdado do mesmo prédio]",
             predio_key, cnpj_origem, _FONTE_SV))
        con.commit()
        return cur.rowcount or 0
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Sweep de fachada via Google Street View Embed (VM-safe, resumível, dedup por prédio).")
    ap.add_argument("--status", default="INDICIO", help="status alvo em verificacao_sede (default INDICIO)")
    ap.add_argument("--limite", type=int, default=0, help="máx. de alvos (0 = todos os pendentes)")
    ap.add_argument("--max-min", type=float, default=20.0, help="time-bound em minutos (default 20)")
    ap.add_argument("--pausa", type=float, default=1.0, help="pausa entre alvos (s)")
    ap.add_argument("--load-teto", type=float, default=_LOAD_MAX, help="adia se load1 > este valor")
    ap.add_argument("--mem-min", type=int, default=_MEM_LIVRE_MIN_MB, help="adia se mem livre < este (MB)")
    ap.add_argument("--cnpj", default="", help="focar 1 CNPJ (re-render explícito, ex.: IDESI)")
    ap.add_argument("--branco-max", type=float, default=0.60, help="rejeita imagem com mais branco que isto")
    ap.add_argument("--so-coerencia", action="store_true",
                    help="NÃO renderiza: só (re)calcula coerencia_google p/ quem já tem foto SV (manutenção)")
    a = ap.parse_args()
    _carregar_env()

    if not os.environ.get("GOOGLE_MAPS_KEY", "").strip():
        print("[sv_sweep] ⛔ GOOGLE_MAPS_KEY ausente (.env/os.environ). Abortando.", flush=True)
        return 2
    if not Path(_RCLONE).exists():
        print(f"[sv_sweep] ⛔ rclone não encontrado em {_RCLONE} (defina RCLONE_BIN). Abortando.", flush=True)
        return 2

    from compliance_agent.verificacao_endereco import _vlm_classificar  # noqa: E402

    con = sqlite3.connect(str(_DB), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    _garante_colunas(con)
    status = a.status or None
    cnpj = (a.cnpj or "").strip() or None

    # --so-coerencia: recalcula coerencia_google p/ quem já tem foto SV (sem render). Manutenção/backfill.
    if a.so_coerencia:
        rows = con.execute(
            "SELECT cnpj, visual_classe, places_achou, places_nome FROM verificacao_sede "
            "WHERE visual_fonte = ?", (_FONTE_SV,)).fetchall()
        con.close()
        n = 0
        for r in rows:
            coer, nota = coerencia_foto_google(r["visual_classe"], r["places_achou"], r["places_nome"])
            con2 = sqlite3.connect(str(_DB), timeout=30)
            con2.execute("PRAGMA busy_timeout=30000")
            con2.execute("UPDATE verificacao_sede SET coerencia_google=?, coerencia_nota=? WHERE cnpj=?",
                         (coer, nota, r["cnpj"]))
            con2.commit()
            con2.close()
            n += 1
        print(f"[sv_sweep] coerência recalculada p/ {n} sede(s) com foto Street View.", flush=True)
        return 0

    alvos = _alvos(con, status, a.limite, cnpj)
    con.close()

    print(f"[sv_sweep] {len(alvos)} alvo(s) pendente(s) (status={status or 'qualquer'}, maior R$ primeiro). "
          f"Fonte: Google Street View Embed (grátis). time-bound={a.max_min:.0f}min · {_snap()} "
          f"(gate: mem≥{a.mem_min}MB, load≤{a.load_teto})", flush=True)
    if not alvos:
        print("[sv_sweep] nada a fazer (todos já têm a foto Street View).", flush=True)
        return 0

    t0 = time.time()
    limite_s = a.max_min * 60.0
    dist: Counter = Counter()
    coer_cnt: Counter = Counter()
    feitos = subidos = sem_img = herdados_tot = 0
    achados: list[str] = []
    vistos_predio: set[str] = set()
    sel = fr.SelecionadorRemote()

    for r in alvos:
        if time.time() - t0 >= limite_s:
            print(f"[sv_sweep] time-bound {a.max_min:.0f}min atingido — parada limpa (resumível).", flush=True)
            break
        pk = (r["predio_key"] or "").strip()
        if pk and pk in vistos_predio:
            continue  # já renderizado neste run (a herança cuidou dos co-localizados)
        feitos += 1
        end = ", ".join(x for x in [r["endereco"], r["municipio"], r["uf"]] if x)

        # 1) RENDER (subprocesso capeado) — UM por vez, gate antes
        cnpj_safe = re.sub(r"\D", "", str(r["cnpj"])) or "sem_cnpj"
        out = Path(tempfile.gettempdir()) / f"sv_render_{cnpj_safe}.jpg"
        if out.exists():
            try:
                out.unlink()
            except OSError:
                pass
        rr = _render_protegido(r["geo_lat"], r["geo_lon"], 0.0, out, a.mem_min, a.load_teto)
        if rr.get("travou"):
            print(f"  ⚠ {rr.get('motivo')} ({rr.get('antes')} → {rr.get('depois')}) — ABORTA o run por segurança.",
                  flush=True)
            break
        if not rr.get("ok"):
            sem_img += 1
            print(f"  · render falhou p/ {r['cnpj']} {r['razao'][:34]}: {rr.get('motivo')} "
                  f"{('| ' + rr['stderr'][:120]) if rr.get('stderr') else ''} — reentra (não marcado).",
                  flush=True)
            if a.pausa:
                time.sleep(a.pausa)
            continue
        val = _validar(out, a.branco_max)
        if not val.get("ok"):
            sem_img += 1
            print(f"  · imagem inválida p/ {r['cnpj']} {r['razao'][:34]}: {val.get('motivo')} "
                  "— reentra (não marcado).", flush=True)
            try:
                out.unlink()
            except OSError:
                pass
            if a.pausa:
                time.sleep(a.pausa)
            continue
        img = out.read_bytes()

        # 2) SOBE p/ nuvem (R2 → B2)
        img_b2, nb = _subir_foto(img, r["cnpj"], sel)
        try:
            out.unlink()  # nada permanente na VM
        except OSError:
            pass
        if not img_b2:
            # ou os buckets estão cheios, ou rclone falhou. Se cheios, para (degrada honesto).
            if sel.escolher(len(img)) is None:
                print("[sv_sweep] R2 e B2 sob o teto — parada limpa (resumível).", flush=True)
                break
            sem_img += 1
            if a.pausa:
                time.sleep(a.pausa)
            continue

        # 3) RECLASSIFICA com o VLM (Gemini grátis) — foto NOVA do Street View
        v = _vlm_classificar(img, "streetview", end)
        classe = v.get("classe", "indeterminado") if v.get("ok") else "indeterminado"
        conf = float(v.get("confianca") or 0.0) if v.get("ok") else 0.0

        # 4) COERÊNCIA foto-vs-Google
        coer, nota = coerencia_foto_google(classe, r["places_achou"], r["places_nome"])

        dados = {"classe": classe, "conf": conf, "fonte": _FONTE_SV, "img_b2": img_b2,
                 "coerencia": coer, "coerencia_nota": nota}
        _grava(r["cnpj"], dados)
        subidos += 1
        dist[classe] += 1
        coer_cnt[coer] += 1
        if pk:
            vistos_predio.add(pk)
            herdou = _herda_predio(pk, dados, r["cnpj"])
            herdados_tot += herdou
        else:
            herdou = 0
        marca = "🔴 CONTRADIZ" if coer == "contradiz" else ("🟢 confirma" if coer == "confirma" else "🟡 indet.")
        linha = (f"  ✓ {r['cnpj']} {marca} · classe={classe} (conf {conf:.0%}) · "
                 f"R$ {r['total_recebido']:,.0f} · {r['razao'][:34]} → {img_b2} ({nb/1024:.0f} KB)"
                 + (f" · +{herdou} prédio" if herdou else ""))
        print(linha, flush=True)
        if coer == "contradiz":
            achados.append(linha)
        if a.pausa:
            time.sleep(a.pausa)

    print(f"\n[sv_sweep] CONCLUÍDO {dt.datetime.now().isoformat(timespec='seconds')}: "
          f"{feitos} processado(s) · {subidos} foto(s) Street View na nuvem · {herdados_tot} herdado(s) por prédio · "
          f"{sem_img} sem imagem/inválida · {time.time() - t0:.0f}s · {_snap()}", flush=True)
    print(f"[sv_sweep] classes (VLM sobre Street View): {dict(dist)}", flush=True)
    print(f"[sv_sweep] coerência foto-vs-Google: {dict(coer_cnt)}", flush=True)
    if achados:
        print(f"[sv_sweep] {len(achados)} CONTRADIÇÃO(ões) foto×Google (indício reforçado):", flush=True)
        for l in achados:
            print(l, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
