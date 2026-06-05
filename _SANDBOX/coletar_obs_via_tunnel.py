#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COLETAR OBs VIA TUNNEL — Dispara coleta pelo Windows conectado

Roda no servidor cloud (ou localmente) para acionar a coleta
de OBs pelo Windows que tem acesso ao SIAFE.

USO:
    # Verificar se Windows está conectado:
    python _SANDBOX/coletar_obs_via_tunnel.py --status

    # Disparar coleta de todos os anos:
    python _SANDBOX/coletar_obs_via_tunnel.py

    # Disparar coleta de ano específico:
    python _SANDBOX/coletar_obs_via_tunnel.py --anos 2025 2026

FLUXO COMPLETO:
    1. No Windows: python _SANDBOX/tunnel_windows.py --server ws://IP:8000/tunnel
    2. No servidor: python _SANDBOX/coletar_obs_via_tunnel.py
    3. Aguardar coleta (~20 min para 4 anos)
    4. OBs são salvas no DB e em data/sei_cache/mgsclean_obs_todas.json
    5. Git push automático ao final
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ── Carregar .env ──────────────────────────────────────────────────────────────
import os
for _ep in [
    Path.home() / ".hermes" / ".env",
    Path(__file__).parents[1] / ".env",
]:
    if _ep.exists():
        for _ln in _ep.read_text(encoding="utf-8", errors="replace").splitlines():
            _ln = _ln.strip()
            if _ln and not _ln.startswith("#") and "=" in _ln:
                k, v = _ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

SERVER_BASE = os.environ.get("JFN_SERVER_HTTP", "http://localhost:8000")


def _api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    url  = SERVER_BASE.rstrip("/") + path
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"erro": f"{e.code} {e.reason}", "body": e.read().decode()[:200]}
    except Exception as e:
        return {"erro": str(e)}


def check_status() -> dict:
    return _api("/api/tunnel/status")


def trigger_collect(anos: list[int]) -> dict:
    return _api("/api/tunnel/collect", method="POST", body={"anos": anos})


def wait_for_completion(poll_sec: int = 10, max_minutes: int = 30) -> bool:
    """Aguarda coleta completar, exibindo progresso a cada poll_sec."""
    deadline = time.time() + max_minutes * 60
    last_count = -1
    print(f"\n  Aguardando coleta (máx {max_minutes} min)...")
    while time.time() < deadline:
        st = check_status()
        count = st.get("obs_recebidas", 0)
        if count != last_count:
            print(f"  [{datetime.now().strftime('%H:%M:%S')}] OBs recebidas: {count}")
            last_count = count
        # Coleta termina quando o Windows envia "done" e o server faz git push.
        # Verificamos se o arquivo JSON foi gerado.
        json_path = Path(__file__).parents[1] / "data" / "sei_cache" / "mgsclean_obs_todas.json"
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if data.get("fonte") == "SIAFE via tunnel" and data.get("total_obs", 0) > 0:
                print(f"\n  Coleta concluída! {data['total_obs']} OBs salvas.")
                return True
        if not st.get("connected"):
            print("  Windows desconectou — coleta pode ter terminado")
            if count > 0:
                return True
            break
        time.sleep(poll_sec)
    return False


def show_results():
    """Exibe resumo das OBs coletadas."""
    json_path = Path(__file__).parents[1] / "data" / "sei_cache" / "mgsclean_obs_todas.json"
    if not json_path.exists():
        print("  Arquivo de OBs não encontrado.")
        return
    data = json.loads(json_path.read_text(encoding="utf-8"))
    print(f"\n{'='*60}")
    print(f"  RESULTADO DA COLETA — {data.get('empresa', '')}")
    print(f"{'='*60}")
    print(f"  Total OBs:   {data.get('total_obs', 0)}")
    print(f"  Valor total: R$ {data.get('total_valor', 0):,.2f}")
    print(f"  Coleta em:   {data.get('coleta', '-')}")
    print(f"\n  Por ano:")
    for ano, d in sorted((data.get("por_ano") or {}).items()):
        print(f"    {ano}: {d['count']} OBs / R$ {d['valor']:,.2f}")
    print(f"\n  Arquivo: {json_path}")


def main():
    parser = argparse.ArgumentParser(description="Dispara coleta de OBs via tunnel Windows")
    parser.add_argument("--status", action="store_true", help="Verificar status do tunnel")
    parser.add_argument("--anos", nargs="+", type=int, default=[2023, 2024, 2025, 2026])
    parser.add_argument("--server", default=SERVER_BASE, help="URL do servidor (padrão: http://localhost:8000)")
    args = parser.parse_args()

    global SERVER_BASE
    SERVER_BASE = args.server.rstrip("/")

    print(f"\n  JFN Tunnel Trigger — {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"  Servidor: {SERVER_BASE}")

    st = check_status()
    print(f"  Tunnel: {'CONECTADO' if st.get('connected') else 'DESCONECTADO'}")
    print(f"  OBs no servidor: {st.get('obs_recebidas', 0)}")

    if args.status:
        return

    if not st.get("connected"):
        print("""
  AÇÃO NECESSÁRIA: inicie o tunnel no Windows:
  ─────────────────────────────────────────────────────
  python _SANDBOX/tunnel_windows.py --server ws://IP:8000/tunnel
  ─────────────────────────────────────────────────────
  Depois execute este script novamente.
""")
        sys.exit(1)

    print(f"\n  Disparando coleta para anos: {args.anos}")
    resp = trigger_collect(args.anos)
    print(f"  Resposta: {resp}")

    if resp.get("ok"):
        ok = wait_for_completion(poll_sec=15, max_minutes=35)
        if ok:
            show_results()
        else:
            print("  Timeout ou erro na coleta. Verifique o Windows.")
            sys.exit(2)
    else:
        print(f"  Erro: {resp.get('erro', resp)}")
        sys.exit(3)


if __name__ == "__main__":
    main()
