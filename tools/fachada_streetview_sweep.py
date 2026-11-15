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
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

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

# ⚠ FIX (06-14, o dono caçou): só geo_tipo ROOFTOP é PRECISO o bastante p/ renderizar a foto direto. Os demais
# (APPROXIMATE/GEOMETRIC_CENTER/RANGE_INTERPOLATED) vêm de geocode IMPRECISO → a coord guardada pode estar a KM do
# prédio real (IDESI: GEOMETRIC_CENTER ficava 2,8km fora) e a foto sairia do LUGAR ERRADO. Antes de renderizar um
# alvo impreciso, RE-GEOCODIFICA o endereço completo; só renderiza se voltar ROOFTOP (senão pula honesto).
_GEO_PRECISO = {"ROOFTOP"}
_GEO_IMPRECISO = {"APPROXIMATE", "GEOMETRIC_CENTER", "RANGE_INTERPOLATED"}
# Marcador de pulo honesto: endereço impreciso que NÃO re-geocodou p/ ROOFTOP → NUNCA foto de lugar errado.
_FONTE_SEM_FOTO_IMPRECISO = "sem_foto_confiavel:endereco_impreciso"

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
             "coerencia_google": "TEXT", "coerencia_nota": "TEXT",
             "letreiro": "TEXT", "letreiro_nomes": "TEXT"}
    for nome, typ in tipos.items():
        if nome not in cols:
            con.execute(f"ALTER TABLE verificacao_sede ADD COLUMN {nome} {typ}")
    con.commit()


def _mem_livre_mb() -> int:
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1]) // 1024
    except Exception as exc:  # noqa: BLE001
        logger.debug("falha ao ler /proc/meminfo (mem livre desconhecida): %s", exc)
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
    sql = (f"SELECT cnpj, predio_key, razao, endereco, municipio, uf, cep, geo_lat, geo_lon, geo_tipo, "
           f"total_recebido, status, places_achou, places_nome, places_endereco "
           f"FROM verificacao_sede WHERE {' AND '.join(where)} "
           f"ORDER BY total_recebido DESC{lim}")
    return con.execute(sql, params).fetchall()


# ── 1) RENDER Street View Embed (iframe + HTTP local) — subprocesso interno ────
_RENDER_SRC = r'''
import os, sys, tempfile, functools, http.server, socketserver, threading
key = os.environ.get("GOOGLE_MAPS_EMBED_KEY", "").strip()
if not key:
    print("ERRO: GOOGLE_MAPS_EMBED_KEY ausente", file=sys.stderr); raise SystemExit(3)
lat, lon, heading, out = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
pano = sys.argv[5] if len(sys.argv) > 5 else ""
url = (f"https://www.google.com/maps/embed/v1/streetview?key={key}"
       + (f"&pano={pano}" if pano else f"&location={lat},{lon}") + f"&heading={heading}&pitch=0&fov=80")
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
        # METADADOS do panorama (15/11/2026): o link "View on Google Maps" traz a posição EXATA e o id do
        # panorama (!1s<id>!2e0 = Google; !2e10 + link /contrib = foto de USUÁRIO, pode ser interior).
        import json, re as _re
        from playwright.sync_api import Error as PWError
        meta = {}
        try:
            fr = [f for f in pg.frames if "/maps/embed" in f.url]
            if fr:
                hrefs = fr[0].eval_on_selector_all("a", "as=>as.map(a=>a.href)")
                txt = fr[0].inner_text("body")
                for h in hrefs:
                    m = _re.search(r"/maps/@(-?[\d.]+),(-?[\d.]+),[^/]*/data=[^?]*!1s([^!]+)!2e(\d+)", h)
                    if m:
                        meta = {"pano_lat": float(m.group(1)), "pano_lon": float(m.group(2)),
                                "pano": m.group(3), "fonte": int(m.group(4))}
                        break
                meta["contrib"] = any("/maps/contrib/" in h for h in hrefs)
                meta["titulo"] = (txt.split("\n")[0] if txt else "").strip()[:120]
        except (PWError, ValueError, KeyError, TypeError) as e:
            meta["erro"] = str(e)[:80]
        print("META" + json.dumps(meta, ensure_ascii=False), flush=True)
    finally:
        b.close()
raise SystemExit(0)
'''


_RUN_USER = "/run/user"


def _embed_api_ok(key: str, fetch_status=None) -> bool:
    """A Maps Embed API está HABILITADA no projeto? (não basta a chave existir). Uma
    requisição; 403 = API desabilitada no console → False (aborta antes de 1272 renders
    condenados). Erro de rede = fail-open (True), só o 403 determinístico aborta."""
    url = (f"https://www.google.com/maps/embed/v1/streetview?key={key}"
           "&location=-22.9,-43.2&heading=0")
    if fetch_status is None:
        def fetch_status(u):
            import urllib.request
            try:
                with urllib.request.urlopen(u, timeout=15) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code
    try:
        return int(fetch_status(url)) != 403
    except (OSError, ValueError):
        return True     # rede/transitório → não bloqueia (só 403 determinístico aborta)


def _dbus_bus():
    """Socket D-Bus do usuário se existir. `systemd-run --user` PRECISA dele; sem ele (cron
    sem sessão) falha com 'Failed to connect to bus: No medium found' e o render morre."""
    bus = os.path.join(_RUN_USER, str(os.getuid()), "bus")
    return bus if os.path.exists(bus) else None


def _cmd_env_render(lat: float, lon: float, heading: float, out: Path, pano: str = ""):
    """(cmd, env) do render. COM D-Bus: systemd-run --user (cap de RAM do cgroup) + o env do
    bus explícito (o cron não herda XDG_RUNTIME_DIR/DBUS_SESSION_BUS_ADDRESS → 'No medium found';
    25.478 renders falharam assim). SEM D-Bus: render direto — sem cap de cgroup, mas o gate de
    mem/load + timeout ainda protegem a VM — melhor render sem cap do que 0 fotos."""
    env = dict(os.environ)
    py = [sys.executable, "-c", _RENDER_SRC, str(lat), str(lon), str(heading), str(out)] + ([pano] if pano else [])
    bus = _dbus_bus()
    if bus:
        env["XDG_RUNTIME_DIR"] = os.path.join(_RUN_USER, str(os.getuid()))
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
        cmd = ["timeout", str(_RENDER_TIMEOUT_S),
               "systemd-run", "--user", "--scope", "--quiet",
               "-p", f"MemoryMax={_MEM_MAX}", "-p", "MemorySwapMax=0",
               "nice", f"-n{_NICE}"] + py
    else:
        cmd = ["timeout", str(_RENDER_TIMEOUT_S), "nice", f"-n{_NICE}"] + py
    return cmd, env


def _render_protegido(lat: float, lon: float, heading: float, out: Path,
                      mem_min: int, load_max: float, pano: str = "") -> dict:
    """Gate (mem/load) + render num SUBPROCESSO com cap de RAM REAL do cgroup (systemd-run) + timeout.
    Devolve {ok, rc, antes, depois, stderr, motivo}. NÃO importa playwright no processo-pai (mantém leve)."""
    antes = _snap()
    if not _gate(mem_min, load_max):
        return {"ok": False, "skip": True, "antes": antes, "depois": _snap(),
                "motivo": f"GATE não liberou (mem≥{mem_min}MB/load≤{load_max}); adia (resumível)"}
    cmd, env = _cmd_env_render(lat, lon, heading, out, pano)
    rc, err, sout = None, "", ""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_RENDER_TIMEOUT_S + 12, env=env)
        rc, err, sout = proc.returncode, (proc.stderr or "")[-400:], proc.stdout or ""
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
    meta = {}
    for ln in sout.splitlines():
        if ln.startswith("META"):
            try:
                meta = json.loads(ln[4:])
            except ValueError:
                meta = {}
    res.update(ok=True, motivo="render concluído", meta=meta)
    return res


# ── FIX: garante coord PRECISA antes de renderizar (re-geocode de imprecisos) ──
def _atualiza_geo_rooftop(cnpj: str, lat: float, lon: float, formatted: str) -> None:
    """Persiste a coord nova ROOFTOP em verificacao_sede (geo_lat/lon/geo_tipo). Transação curta."""
    con = sqlite3.connect(str(_DB), timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        con.execute(
            "UPDATE verificacao_sede SET geo_lat=?, geo_lon=?, geo_tipo='ROOFTOP', "
            "geo_municipio=COALESCE(NULLIF(?, ''), geo_municipio) WHERE cnpj=?",
            (float(lat), float(lon), formatted, cnpj))
        con.commit()
    finally:
        con.close()


def _coord_precisa(r: sqlite3.Row, sg, stats: Counter) -> dict:
    """Devolve a coord a USAR p/ renderizar este alvo, garantindo precisão (o dono caçou o bug da foto de
    lugar errado). Conta em `stats`. Retorna:
      {ok:True, lat, lon}                  → renderiza nessa coord (ROOFTOP, original ou re-geocodada);
      {ok:False, skip_impreciso:True, motivo} → endereço impreciso e NÃO virou ROOFTOP → marca/pula honesto;
      {ok:False, sem_cota:True, motivo}    → cota de geocoding esgotada → adia (re-geocode no próximo ciclo).
    """
    geo_tipo = (r["geo_tipo"] or "").strip().upper()
    if geo_tipo in _GEO_PRECISO:                       # 1) já é preciso → usa direto
        stats["rooftop_direto"] += 1
        return {"ok": True, "lat": r["geo_lat"], "lon": r["geo_lon"], "geo_tipo": geo_tipo}

    # 2) impreciso (ou vazio) → RE-GEOCODE o endereço completo (reusa sede_google, quota-guarded)
    # 15/11/2026: a chave é restrita SÓ à Maps Embed (grátis); o Geocoding é NEGADO e voltaria "sem resultado",
    # o que marcaria o alvo como impreciso para sempre. Sem Geocoding pago, ADIA (não marca nada).
    if os.environ.get("SV_SEM_GEOCODE") == "1" or sg.cota_restante("geocoding") <= 0:
        stats["sem_cota"] += 1
        return {"ok": False, "sem_cota": True,
                "motivo": "cota de Geocoding esgotada — adia o re-geocode p/ o próximo ciclo (resumível)"}
    end_full = ", ".join(x for x in [r["endereco"], r["municipio"], r["uf"], (r["cep"] or "")] if x)
    g = sg.geocodificar(end_full)                      # consome 1 cota geocoding
    stats["regeocodou"] += 1
    novo_tipo = ((g or {}).get("location_type") or "").strip().upper()
    if g and novo_tipo in _GEO_PRECISO and g.get("lat") is not None:
        _atualiza_geo_rooftop(r["cnpj"], g["lat"], g["lon"], g.get("formatted") or "")
        stats["regeocode_rooftop"] += 1
        return {"ok": True, "lat": g["lat"], "lon": g["lon"], "geo_tipo": "ROOFTOP", "regeocodou": True,
                "antes": geo_tipo or "(vazio)"}
    # continua impreciso → NUNCA renderiza foto de lugar errado
    stats["regeocode_ainda_impreciso"] += 1
    return {"ok": False, "skip_impreciso": True,
            "motivo": f"re-geocode de '{end_full[:60]}' voltou {novo_tipo or '(sem resultado)'} "
                      f"(era {geo_tipo or '(vazio)'}) — endereço impreciso, não renderiza foto de lugar errado"}


def _marca_sem_foto_impreciso(cnpj: str, motivo: str) -> None:
    """Marca o alvo impreciso (que não virou ROOFTOP) como pulado honesto: visual_fonte sentinela + nota.
    NÃO grava imagem. Assim o sweep RESUME (não re-tenta render) mas re-tenta o re-geocode quando houver cota
    nova (o filtro de alvos exclui só visual_fonte=_FONTE_SV, não este sentinela)."""
    con = sqlite3.connect(str(_DB), timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        con.execute(
            "UPDATE verificacao_sede SET visual_fonte=?, visual_em=?, coerencia_nota=? WHERE cnpj=?",
            (_FONTE_SEM_FOTO_IMPRECISO, dt.datetime.now().isoformat(timespec="seconds"),
             "Sem foto de fachada confiável: " + motivo, cnpj))
        con.commit()
    finally:
        con.close()


def _limpar_rendidos_imprecisos(con: sqlite3.Connection) -> int:
    """RE-FAZER os já-rendidos errados: alvos com geo_tipo impreciso que JÁ têm visual_img_b2 (foto do lugar
    ERRADO). Limpa visual_* + coerencia + apaga o objeto do R2/B2 → re-processa com a coord certa no próximo
    sweep. Devolve quantos limpou. (Idempotente: roda 1× ou quantas quiser; o IDESI já foi limpo à mão.)"""
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT cnpj, geo_tipo, visual_img_b2 FROM verificacao_sede "
        "WHERE geo_tipo IN ('APPROXIMATE','GEOMETRIC_CENTER','RANGE_INTERPOLATED') "
        "AND visual_img_b2 IS NOT NULL").fetchall()
    if not rows:
        print("[sv_sweep] limpeza: nenhum já-rendido impreciso a limpar.", flush=True)
        return 0
    n = 0
    for r in rows:
        loc = (r["visual_img_b2"] or "").strip()      # formato 'remote:bucket/objeto'
        if loc:
            try:
                d = subprocess.run([_RCLONE, "delete", loc], capture_output=True, text=True, timeout=60)
                if d.returncode == 0:
                    print(f"  · R2/B2 apagado: {loc}", flush=True)
                else:
                    print(f"  ⚠ rclone delete falhou ({loc}): {d.stderr.strip()[:120]} — segue limpando o banco",
                          flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ erro rclone delete {loc}: {str(e)[:120]} — segue limpando o banco", flush=True)
        con.execute(
            "UPDATE verificacao_sede SET visual_classe=NULL, visual_conf=NULL, visual_fonte=NULL, "
            "visual_em=NULL, visual_img_b2=NULL, visual_img_path=NULL, coerencia_google=NULL, "
            "coerencia_nota=NULL WHERE cnpj=?", (r["cnpj"],))
        con.commit()
        n += 1
        print(f"  ✓ limpo p/ re-render ({r['geo_tipo']}): {r['cnpj']}", flush=True)
    print(f"[sv_sweep] limpeza: {n} já-rendido(s) impreciso(s) limpo(s) (banco + nuvem) — re-processa com a coord "
          "certa no sweep.", flush=True)
    return n


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


# ── 1b) A foto é do ENDEREÇO da sede? ──────────────────────────────────────────
# 15/11/2026, dono: "fotos de lugares que não são a fachada da empresa". A Embed devolve o panorama MAIS PRÓXIMO
# da coordenada — medido no 1º teste: alvo "Alameda Santos, 193" → foto da "R. Teixeira da Silva, 251" (gravou
# 🔴 contradiz falso para quem recebeu R$ 552 mi); alvo "Estr. São Lourenço, 661" → foto do nº 222 (oficina).
# O Google ESCREVE o endereço do panorama no canto da imagem: lê-se por OCR e só aceita mesma rua + número perto.
_GENERICOS = {"rua", "r", "avenida", "av", "estrada", "estr", "est", "alameda", "al", "travessa", "tv", "trav",
              "praca", "pc", "rodovia", "rod", "largo", "lgo", "beco", "via", "do", "da", "de", "dos", "das", "e",
              "sao", "santa", "santo", "quadra", "lote", "qd", "lt", "sn", "km", "br", "rj", "sp"}
_NUM_TOLERANCIA = 60


def _norm_end(t: str) -> list[str]:
    import unicodedata
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z]+|\d+", t)


def _partes_alvo(endereco: str) -> tuple[set[str], int | None]:
    """Rua (palavras não genéricas ANTES do 1º número) e o número do endereço cadastrado."""
    rua, num = set(), None
    for tk in _norm_end(endereco):
        if tk.isdigit():
            num = int(tk) if len(tk) <= 5 else None
            break
        if len(tk) >= 3 and tk not in _GENERICOS:
            rua.add(tk)
    return rua, num


def _partes_foto(linha: str) -> tuple[set[str], int | None]:
    tks = _norm_end(linha)
    num = next((int(t) for t in tks if t.isdigit() and len(t) <= 5), None)
    return {t for t in tks if not t.isdigit() and len(t) >= 3 and t not in _GENERICOS}, num


def mesmo_endereco(linha_foto: str, endereco_alvo: str) -> tuple[bool, str]:
    rua_a, num_a = _partes_alvo(endereco_alvo)
    rua_f, num_f = _partes_foto(linha_foto)
    if not linha_foto.strip() or not rua_f:
        return False, "endereço do panorama ilegível"
    if not rua_a:
        return False, "endereço cadastrado sem nome de rua comparável"
    if not (rua_a & rua_f):
        return False, "rua diferente"
    if num_a is not None and num_f is not None and abs(num_a - num_f) > _NUM_TOLERANCIA:
        return False, f"mesma rua, mas nº {num_f} contra nº {num_a} cadastrado"
    return True, "mesma rua" + ("" if num_a is None or num_f is None else f", nº {num_f} ≈ {num_a}")


def pontos_em_volta(lat: float, lon: float) -> list[tuple[float, float, float]]:
    """(lat, lon, heading) a tentar: o próprio ponto e anéis de 15/30/50 m em 8 direções; a câmera de cada
    ponto aponta para a sede (o panorama devolvido fica perto do ponto pedido)."""
    import math
    pts = [(lat, lon, 0.0)]
    for raio in (15.0, 30.0, 50.0):
        for k in range(8):
            ang = math.radians(45 * k)
            dlat = raio * math.cos(ang) / 111_320.0
            dlon = raio * math.sin(ang) / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
            heading = (45.0 * k + 180.0) % 360.0                                  # de volta para a sede
            pts.append((lat + dlat, lon + dlon, heading))
    return pts


def rumo_graus(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Rumo (0 = norte, 90 = leste) do ponto 1 ao ponto 2."""
    import math
    f1, f2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(f2)
    x = math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


# ── 3b) LETREIRO: a fachada mostra o NOME da empresa? (15/11/2026, "invente uma solução") ─────────────
# O modelo de visão só TRANSCREVE os nomes legíveis; quem compara com a razão social / nome no Google é a regra
# abaixo (modelo barato não decide). Letreiro com o nome = prova forte de existência no endereço; letreiro de
# OUTRA empresa = sinal (a sede declarada abriga outro negócio); sem letreiro = nada se conclui.
_GENERICOS_NOME = {"ltda", "eireli", "me", "epp", "sa", "s", "a", "cia", "comercio", "servicos", "servico", "de",
                   "da", "do", "das", "dos", "e", "em", "industria", "empresa", "grupo", "brasil", "rio", "janeiro",
                   "solucoes", "assessoria", "consultoria", "construcoes", "construtora", "engenharia", "e", "the"}


def _tokens_nome(t: str) -> set[str]:
    return {x for x in _norm_end(t) if not x.isdigit() and len(x) >= 3 and x not in _GENERICOS_NOME}


def letreiro_bate(nomes: list[str], razao: str, outros: list[str]) -> str:
    """'bate' | 'outro_nome' | 'sem_letreiro'. Bate se um nome lido partilha palavra distintiva com a razão social
    ou com o nome que o Google dá ao negócio da sede."""
    nomes = [n for n in (nomes or []) if (n or "").strip()]
    if not nomes:
        return "sem_letreiro"
    ref = _tokens_nome(razao)
    for o in outros:
        ref |= _tokens_nome(o or "")
    lidos = set().union(*(_tokens_nome(n) for n in nomes))
    return "bate" if ref & lidos else "outro_nome"


def ler_letreiros(img: bytes) -> list[str]:
    from compliance_agent.verificacao_endereco import _gemini_vision_sync
    mime = "image/png" if img[:4] == b"\x89PNG" else "image/jpeg"
    prompt = ("Foto de rua. Transcreva, exatamente como escrito, TODO nome de empresa/estabelecimento legível em "
              "placas, letreiros, toldos, portões ou vitrines. Ignore placas de rua, de trânsito, de imóvel à venda e "
              "a marca d'água do Google. Não adivinhe texto ilegível. Responda SOMENTE JSON: {\"nomes\": [\"...\"]}")
    txt = _gemini_vision_sync(img, mime, prompt) or ""
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return [str(x)[:80] for x in (json.loads(m.group(0)).get("nomes") or [])] if m else []
    except ValueError:
        return []


def endereco_da_foto(img: bytes) -> str:
    """1ª linha da caixa que o Google desenha no canto superior esquerdo do Street View (OCR, tesseract)."""
    import io

    from PIL import Image
    try:
        im = Image.open(io.BytesIO(img)).convert("L")
        w, h = im.size
        c = im.crop((4, int(h * 6 / 480), int(w * 0.40), int(h * 32 / 480)))
        c = c.resize((c.width * 4, c.height * 4), Image.LANCZOS).point(lambda p: 0 if p > 150 else 255)
        b = io.BytesIO()
        c.save(b, "PNG")
        r = subprocess.run(["tesseract", "stdin", "stdout", "-l", "por", "--psm", "7"],
                           input=b.getvalue(), capture_output=True, timeout=30)
        return r.stdout.decode("utf-8", "replace").strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


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
            except OSError as exc:
                logger.debug("falha ao remover temp %s (cnpj %s): %s", tmp, cnpj, exc)


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
    ap.add_argument("--limpar-imprecisos", action="store_true",
                    help="manutenção 1×: limpa as fotos já-rendidas de alvos com geo_tipo IMPRECISO (lugar errado) "
                         "do banco E do R2/B2, p/ re-processar com a coord certa. NÃO renderiza.")
    a = ap.parse_args()
    _carregar_env()

    _key = os.environ.get("GOOGLE_MAPS_EMBED_KEY", "").strip()
    if not _key:
        print("[sv_sweep] ⛔ GOOGLE_MAPS_EMBED_KEY ausente (.env/os.environ). Abortando.", flush=True)
        return 2
    if not _embed_api_ok(_key):
        # AUTO-PAUSA APÓS ABORTO REPETIDO. A 'Maps Embed API' está desabilitada no console do dono
        # — condição de CONFIGURAÇÃO que só ele resolve, e que nenhuma rodada deste sweep muda.
        # Medido em 2026-08-08: 20 abortos `rc=3` na auditoria, um alarme que se repete a cada 3 h
        # e dessensibiliza a tabela inteira (foi assim que a recaptura morta passou 4 dias
        # invisível). Depois de 3 abortos idênticos consecutivos, o sweep cria o próprio flag de
        # pausa: para de tentar, deixa o motivo escrito no flag para o dono, e a auditoria volta a
        # significar algo. Reabilitar a API OU apagar o flag retoma. NÃO é "culpar o acesso" — o
        # próprio Google Cloud reporta a API como desabilitada; é config ausente, não fonte negada.
        marca = _RAIZ / "data" / ".streetview_403_seguidos"
        try:
            n = int(marca.read_text().strip()) + 1 if marca.exists() else 1
        except (OSError, ValueError):
            n = 1
        marca.write_text(str(n), encoding="utf-8")
        print("[sv_sweep] ⛔ Maps Embed API 403 (DESABILITADA no projeto Google Cloud). "
              "Todo render sairia tela-de-erro — aborto em vez de disparar renders condenados. "
              f"Habilite a 'Maps Embed API' no console (é grátis). Aborto seguido nº {n}/3.",
              flush=True)
        if n >= 3:
            pausa = _RAIZ / "data" / ".pause_fachada_streetview_sweep"
            pausa.write_text(
                "auto-pausado em 2026-08-08 após 3 abortos por Maps Embed API 403 (desabilitada no "
                "Google Cloud do dono). Habilite a 'Maps Embed API' no console e APAGUE este flag "
                "para retomar. Ver tools/fachada_streetview_sweep.py.\n", encoding="utf-8")
            print("[sv_sweep] auto-pausado: criei data/.pause_fachada_streetview_sweep — "
                  "para de poluir a auditoria até a API ser habilitada.", flush=True)
        return 3
    # a API respondeu: zera o contador de abortos seguidos (uma habilitação posterior limpa a
    # dívida sem intervenção; o flag de pausa, esse, o dono apaga à mão de propósito).
    _marca_403 = _RAIZ / "data" / ".streetview_403_seguidos"
    if _marca_403.exists():
        _marca_403.unlink()
    if not Path(_RCLONE).exists():
        print(f"[sv_sweep] ⛔ rclone não encontrado em {_RCLONE} (defina RCLONE_BIN). Abortando.", flush=True)
        return 2

    from compliance_agent import sede_google as sg  # noqa: E402
    from compliance_agent.verificacao_endereco import _vlm_classificar  # noqa: E402

    con = sqlite3.connect(str(_DB), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    _garante_colunas(con)
    status = a.status or None
    cnpj = (a.cnpj or "").strip() or None

    # --limpar-imprecisos: manutenção 1× — apaga fotos do lugar errado (banco + nuvem) p/ re-processar.
    if a.limpar_imprecisos:
        try:
            _limpar_rendidos_imprecisos(con)
        finally:
            con.close()
        return 0

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
    geo_stats: Counter = Counter()      # FIX: contabilidade de precisão de coord (rooftop/re-geocode/pulos)
    feitos = subidos = sem_img = herdados_tot = pulos_impreciso = 0
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

        # 0) COORD PRECISA (FIX do dono): só renderiza em coord ROOFTOP. Imprecisos re-geocodam o endereço
        #    completo; se voltar ROOFTOP atualiza e usa, senão PULA honesto (nunca foto de lugar errado).
        cp = _coord_precisa(r, sg, geo_stats)
        if not cp.get("ok"):
            if cp.get("sem_cota"):
                # cota de geocoding esgotada → não dá p/ validar a coord deste impreciso; PULA o alvo (re-geocode
                # no próximo ciclo). NÃO marca sentinela (p/ re-tentar quando a cota voltar) e NÃO para o run
                # (alvos ROOFTOP adiante ainda renderizam normalmente — não precisam de geocoding).
                pulos_impreciso += 1
                print(f"  · {r['cnpj']} {r['razao'][:34]}: {cp.get('motivo')} — pula (re-geocode no próximo ciclo).",
                      flush=True)
                if a.pausa:
                    time.sleep(a.pausa)
                continue
            # impreciso que não virou ROOFTOP → marca sentinela e pula (não renderiza, não conta como sem_img)
            pulos_impreciso += 1
            _marca_sem_foto_impreciso(r["cnpj"], cp.get("motivo", ""))
            print(f"  ⨯ {r['cnpj']} {r['razao'][:34]}: {cp.get('motivo')}", flush=True)
            if a.pausa:
                time.sleep(a.pausa)
            continue
        if cp.get("regeocodou"):
            print(f"  · {r['cnpj']} re-geocode {cp.get('antes')}→ROOFTOP "
                  f"({cp['lat']:.5f},{cp['lon']:.5f}) — coord corrigida.", flush=True)
        lat_use, lon_use = cp["lat"], cp["lon"]

        # 1) RENDER (subprocesso capeado) — UM por vez, gate antes
        cnpj_safe = re.sub(r"\D", "", str(r["cnpj"])) or "sem_cnpj"
        out = Path(tempfile.gettempdir()) / f"sv_render_{cnpj_safe}.jpg"
        if out.exists():
            try:
                out.unlink()
            except OSError as exc:
                logger.debug("falha ao remover render antigo %s (cnpj %s): %s", out, r["cnpj"], exc)
        # 1) RENDER + 1b) A FOTO É DA SEDE? — tenta o ponto e os anéis em volta até o panorama ser do endereço
        img, ultima, travou, falhas, tentativas = None, "", False, [], 0
        for plat, plon, phead in pontos_em_volta(lat_use, lon_use):
            tentativas += 1
            if out.exists():
                out.unlink()
            rr = _render_protegido(plat, plon, phead, out, a.mem_min, a.load_teto)
            if rr.get("travou"):
                print(f"  ⚠ {rr.get('motivo')} ({rr.get('antes')} → {rr.get('depois')}) — ABORTA o run por segurança.",
                      flush=True)
                travou = True
                break
            if not rr.get("ok"):
                falhas.append(str(rr.get("motivo"))[:60])
                continue
            val = _validar(out, a.branco_max)
            if not val.get("ok"):
                falhas.append(str(val.get("motivo"))[:60])
                continue
            meta = rr.get("meta") or {}
            if meta.get("contrib") or meta.get("fonte") not in (None, 0):
                ultima = f"panorama de usuário ('{meta.get('titulo', '')[:40]}'), não do Google"
                continue
            linha_foto = meta.get("titulo") or endereco_da_foto(out.read_bytes())
            bate, porque = mesmo_endereco(linha_foto, r["endereco"] or "")
            ultima = f"'{linha_foto[:50]}': {porque}"
            if not bate:
                continue
            # aproxima: entre o panorama achado e a sede pode haver outro panorama da MESMA rua mais perto
            if meta.get("pano") and meta.get("pano_lat") is not None:
                melhor = meta
                for frac in (0.5, 0.75):
                    qlat = meta["pano_lat"] + frac * (lat_use - meta["pano_lat"])
                    qlon = meta["pano_lon"] + frac * (lon_use - meta["pano_lon"])
                    rq = _render_protegido(qlat, qlon, 0.0, out, a.mem_min, a.load_teto)
                    mq = rq.get("meta") or {}
                    if (rq.get("ok") and mq.get("pano_lat") is not None and not mq.get("contrib")
                            and mq.get("fonte") == 0 and mesmo_endereco(mq.get("titulo", ""), r["endereco"] or "")[0]
                            and dist_m(mq["pano_lat"], mq["pano_lon"], lat_use, lon_use)
                            < dist_m(melhor["pano_lat"], melhor["pano_lon"], lat_use, lon_use)):
                        melhor = mq
                meta = melhor
            # câmera DE FRENTE para a sede: rumo do panorama (posição exata) até a coordenada da sede
            if meta.get("pano") and meta.get("pano_lat") is not None:
                rumo = rumo_graus(meta["pano_lat"], meta["pano_lon"], lat_use, lon_use)
                out.unlink(missing_ok=True)
                rr2 = _render_protegido(lat_use, lon_use, rumo, out, a.mem_min, a.load_teto, pano=meta["pano"])
                if rr2.get("travou"):
                    travou = True
                    break
                if not (rr2.get("ok") and _validar(out, a.branco_max).get("ok")):
                    continue
                ultima += f"; câmera a {rumo:.0f}°, panorama a {dist_m(meta['pano_lat'], meta['pano_lon'], lat_use, lon_use):.0f} m da sede"
            img = out.read_bytes()
            break
        if travou:
            break
        try:
            if out.exists():
                out.unlink()
        except OSError as exc:
            logger.debug("falha ao remover render %s: %s", out, exc)
        if img is None:
            sem_img += 1
            if not ultima:      # nenhuma imagem válida: render/validação falharam — reentra (não marca)
                print(f"  · sem imagem p/ {r['cnpj']} {r['razao'][:34]} ({'; '.join(falhas[:2])}) — reentra.",
                      flush=True)
            else:
                _grava(r["cnpj"], {"classe": "indeterminado", "conf": 0.0, "fonte": _FONTE_SV, "img_b2": None,
                                   "coerencia": "indeterminado",
                                   "coerencia_nota": f"INDISPONÍVEL — nenhum Street View num raio de 50 m é do endereço "
                                                     f"cadastrado ({tentativas} pontos; último {ultima}). Sem foto da "
                                                     "sede; não é indício."})
                print(f"  · {r['cnpj']} {r['razao'][:34]}: nenhum panorama do endereço em {tentativas} pontos "
                      f"(último {ultima}) — INDISPONÍVEL.", flush=True)
            if a.pausa:
                time.sleep(a.pausa)
            continue
        print(f"  · {r['cnpj']} panorama do endereço achado na tentativa {tentativas} ({ultima}).", flush=True)

        # 2) SOBE p/ nuvem (R2 → B2)
        img_b2, nb = _subir_foto(img, r["cnpj"], sel)
        try:
            out.unlink()  # nada permanente na VM
        except OSError as exc:
            logger.debug("falha ao remover render local %s (cnpj %s): %s", out, r["cnpj"], exc)
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
        nomes = ler_letreiros(img)
        letr = letreiro_bate(nomes, r["razao"] or "", [r["places_nome"] or ""])
        if letr == "bate":
            nota += f" Letreiro na fachada com o nome da empresa ({'; '.join(nomes)[:120]}) — prova de existência no endereço."
        elif letr == "outro_nome":
            nota += f" Letreiro de OUTRO negócio na fachada ({'; '.join(nomes)[:120]}) — confirmar se a empresa funciona ali."

        dados = {"classe": classe, "conf": conf, "fonte": _FONTE_SV, "img_b2": img_b2,
                 "coerencia": coer, "coerencia_nota": nota}
        _grava(r["cnpj"], dados)
        _con = sqlite3.connect(str(_DB), timeout=30)
        try:
            _con.execute("PRAGMA busy_timeout=30000")
            _con.execute("UPDATE verificacao_sede SET letreiro=?, letreiro_nomes=? WHERE cnpj=?",
                         (letr, json.dumps(nomes, ensure_ascii=False), r["cnpj"]))
            _con.commit()
        finally:
            _con.close()
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
        linha = (f"  ✓ {r['cnpj']} {marca} · classe={classe} (conf {conf:.0%}) · letreiro={letr} · "
                 f"R$ {r['total_recebido']:,.0f} · {r['razao'][:34]} → {img_b2} ({nb/1024:.0f} KB)"
                 + (f" · +{herdou} prédio" if herdou else ""))
        print(linha, flush=True)
        if coer == "contradiz":
            achados.append(linha)
        if a.pausa:
            time.sleep(a.pausa)

    print(f"\n[sv_sweep] CONCLUÍDO {dt.datetime.now().isoformat(timespec='seconds')}: "
          f"{feitos} processado(s) · {subidos} foto(s) Street View na nuvem · {herdados_tot} herdado(s) por prédio · "
          f"{sem_img} sem imagem/inválida · {pulos_impreciso} pulado(s) endereço-impreciso · "
          f"{time.time() - t0:.0f}s · {_snap()}", flush=True)
    print(f"[sv_sweep] coord-precisão: {geo_stats.get('rooftop_direto', 0)} ROOFTOP direto · "
          f"{geo_stats.get('regeocodou', 0)} re-geocode(s) "
          f"(→{geo_stats.get('regeocode_rooftop', 0)} ROOFTOP / "
          f"{geo_stats.get('regeocode_ainda_impreciso', 0)} ainda-impreciso) · "
          f"{geo_stats.get('sem_cota', 0)} sem cota geocoding · "
          f"cota geocoding restante={sg.cota_restante('geocoding')}", flush=True)
    print(f"[sv_sweep] classes (VLM sobre Street View): {dict(dist)}", flush=True)
    print(f"[sv_sweep] coerência foto-vs-Google: {dict(coer_cnt)}", flush=True)
    if achados:
        print(f"[sv_sweep] {len(achados)} CONTRADIÇÃO(ões) foto×Google (indício reforçado):", flush=True)
        for l in achados:
            print(l, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
