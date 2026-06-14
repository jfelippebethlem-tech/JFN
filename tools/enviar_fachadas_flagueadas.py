#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""enviar_fachadas_flagueadas — manda ao Telegram do dono os SUSPEITOS já FLAGUEADOS pelo classificador visual.

≠ `doubt_sender_fachada` (que parte das DÚVIDAS de `endereco_verificacao` INDISPONÍVEL). AQUI a fonte é o
resultado do `fachada_visual_sweep`: `verificacao_sede.visual_classe` já é um INDÍCIO rente ao chão
(terreno_baldio / area_aberta_rural / construcao_precaria_barraco; opcional residencial). Pega os que ainda
NÃO estão em `fachada_veredito`, ranqueia por R$ recebido (a atenção do dono é escassa → maior valor primeiro),
busca a foto e envia foto+legenda HONESTA (razão, R$, endereço, classe visual+confiança) ao Telegram. O dono
responde real/fachada/indício/pular — capturado pelo fluxo passivo existente (`fachada_doubt.processar_respostas`
via `registrar_vereditos_fachada.py`), que grava o veredito humano em `fachada_veredito`.

FOTO: reusa `fd.foto_rua` (Street View, quota-guarded — degrada honesto se a cota estiver no teto) e, em falta,
cai p/ Mapillary (GRÁTIS, rente ao chão) — NUNCA força requisição paga acima do teto.

VM-safe / atenção-do-dono: `--limite N` (default 10), `--dry-run` (mostra quem enviaria, sem mandar), `--pausa`.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.enviar_fachadas_flagueadas \\
        [--limite 10] [--dry-run] [--incluir-residencial] [--min-recebido 0] [--pausa 1.5] [--chat <id>]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compliance_agent import fachada_doubt as fd  # noqa: E402
from tools import doubt_sender_fachada as ds  # noqa: E402

# Classes que viram INDÍCIO rente ao chão (mesma definição do sweep). Residencial é opcional (--incluir-residencial).
_FLAG_INDICIO = ("terreno_baldio", "area_aberta_rural", "construcao_precaria_barraco")
_FLAG_RESIDENCIAL = ("predio_residencial", "casa_residencial")


def _candidatos(con, limite: int, *, incluir_residencial: bool, min_recebido: float) -> list[dict]:
    """FLAGUEADOS em `verificacao_sede` (visual_classe) ainda NÃO em `fachada_veredito`, maior R$ primeiro.

    Devolve dicts no formato que `fd.legenda`/`fd.registrar_envio` esperam (lat/lon, exato, total_recebido…).
    `exato`: usamos `aproximado_cep`=0 como proxy de coord no nº (≈ exato); legenda já é honesta quanto à fonte.
    """
    fd.garantir_schema(con)
    classes = list(_FLAG_INDICIO) + (list(_FLAG_RESIDENCIAL) if incluir_residencial else [])
    ph = ",".join("?" for _ in classes)
    sql = f"""
        SELECT cnpj, razao, endereco, municipio, uf, cep, geo_lat AS lat, geo_lon AS lon,
               aproximado_cep, total_recebido, visual_classe, visual_conf, visual_fonte
        FROM verificacao_sede
        WHERE visual_classe IN ({ph})
          AND geo_lat IS NOT NULL AND geo_lon IS NOT NULL
          AND total_recebido > ?
          AND cnpj NOT IN (SELECT cnpj FROM fachada_veredito)
        ORDER BY total_recebido DESC
        LIMIT ?
    """
    rows = con.execute(sql, (*classes, float(min_recebido), int(limite))).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["exato"] = 0 if d.get("aproximado_cep") else 1
        out.append(d)
    return out


def _legenda_visual(cand: dict, codigo: str) -> str:
    """Legenda honesta p/ o FLAG visual: parte da legenda-base de dúvida e acrescenta a classe visual+confiança
    (a razão concreta deste alvo) — sem inventar nada além do que o classificador devolveu."""
    classe = (cand.get("visual_classe") or "").replace("_", " ")
    conf = float(cand.get("visual_conf") or 0)
    fonte = cand.get("visual_fonte") or "imagem"
    base = fd.legenda(cand, codigo, fonte, cand.get("_foto_info") or {})
    razao_visual = (f"\n🔎 Classificação visual (automática, {fonte}): "
                    f"**{classe}** (confiança {conf:.0%}) — indício de fachada, confirmar.")
    # injeta a razão visual logo após a linha de recebido (antes da pergunta) — simples: prepende ao bloco
    return base.replace("\n\n", razao_visual + "\n\n", 1)


def _foto(cand: dict) -> tuple[bytes | None, str, dict]:
    """Foto da sede: 1) `fd.foto_rua` (Street View, quota-guarded — degrada se cota no teto); 2) fallback
    Mapillary (GRÁTIS, rente ao chão). NUNCA força requisição paga acima do teto."""
    end = fd.endereco_completo(cand)
    img, fonte, info = fd.foto_rua(end)
    if img is not None:
        return img, fonte, info
    # fallback grátis: Mapillary no ponto (coord do sweep Google)
    from compliance_agent import verificacao_endereco as ve
    token = os.environ.get("MAPILLARY_TOKEN", "").strip()
    lat, lon = cand.get("lat"), cand.get("lon")
    if token and lat is not None and lon is not None:
        raio = float(os.environ.get("MAPILLARY_RAIO_M", "120") or 120)
        mly = ve._fetch_mapillary(float(lat), float(lon), token, raio_m=raio)
        if mly is not None:
            return mly, "mapillary", {"lat": lat, "lon": lon}
    return None, "sem foto (Street View no teto/sem cobertura · Mapillary sem cobertura)", {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=10, help="máx. a enviar nesta passada (default 10)")
    ap.add_argument("--min-recebido", type=float, default=0.0, help="só empresas com OB acima deste valor")
    ap.add_argument("--incluir-residencial", action="store_true",
                    help="inclui predio_residencial/casa_residencial (default: só baldio/rural/barraco)")
    ap.add_argument("--dry-run", action="store_true", help="seleciona e monta a legenda; NÃO envia")
    ap.add_argument("--chat", default="", help="chat_id destino (default: TELEGRAM_CHAT_ID/.env)")
    ap.add_argument("--pausa", type=float, default=1.5, help="pausa entre envios (s)")
    a = ap.parse_args()

    ds._carregar_env()
    token = ds._env("TELEGRAM_BOT_TOKEN")
    chat = a.chat or ds._env("TELEGRAM_CHAT_ID") or "45338178"
    if not a.dry_run and not token:
        print("ERRO: TELEGRAM_BOT_TOKEN ausente (.env/~/.hermes/.env)"); return 2

    con = fd.conectar()
    cands = _candidatos(con, a.limite, incluir_residencial=a.incluir_residencial,
                        min_recebido=a.min_recebido)
    if not cands:
        print("Nenhum FLAG visual pendente no critério (todos já enviados ou nenhum flagueado).")
        return 0

    print(f"{len(cands)} flag(s) visual(is) selecionado(s) (maior R$ primeiro) — "
          f"{'DRY-RUN' if a.dry_run else 'envio real'}.")

    enviados = sem_foto = 0
    for c in cands:
        codigo = fd.codigo_de(c["cnpj"])
        img, fonte, info = _foto(c)
        c["_foto_info"] = info
        cap = _legenda_visual(c, codigo)
        loc = f"({info.get('lat'):.4f},{info.get('lon'):.4f})" if info.get("lat") else ""
        cab = (f"[{codigo}] {c.get('razao') or c['cnpj']} — {fd._moeda(c.get('total_recebido'))} — "
               f"visual={c.get('visual_classe')} — foto={fonte if img else 'SEM FOTO'} {loc}")
        if img is None:
            sem_foto += 1
            print(f"  ✗ {cab} → não envia (sem foto)")
            continue
        if a.dry_run:
            print(f"  • DRY {cab} ({len(img)} bytes)")
            continue
        mid = ds._enviar_foto(token, chat, img, cap)
        if mid is not None:
            fd.registrar_envio(con, c, codigo, fonte, mid)
            enviados += 1
            print(f"  ✓ {cab}  (msg {mid})")
        import time
        time.sleep(a.pausa)

    print(f"\nFIM: enviados={enviados} sem_foto={sem_foto} dry_run={a.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
