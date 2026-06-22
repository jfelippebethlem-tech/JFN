# -*- coding: utf-8 -*-
"""Re-FICHADOR: re-extrai a ficha dos processos SEI JÁ em cache (cdp_*.json) com o schema ATUAL
(ex.: novo campo `documentos`), SEM re-scrape — só relê o conteúdo cacheado e chama o nous stepfun:free
(ilimitado/grátis, regra do sweep). Idempotente: pula quem já tem o campo novo. Resumível (cada cache é
independente). Uso: cd ~/JFN && PYTHONPATH=. .venv/bin/python -m tools.sei_refichar [--max N] [--força]
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env", override=False)  # CEREBRAS_API_KEY etc.
except Exception:
    pass

from tools.sei_ficha import STEPFUN, _refresh_nous_se_preciso, conteudo_real, extrair_ficha

CACHE = _ROOT / "data" / "sei_cache"
# marcador do schema atual (versão da ficha). v2 = "pericia": ficha agora inclui perícia contábil+jurídica.
# Bumpar este valor faz o re-fichador re-extrair TODO o acervo com o schema novo (auto-cura via cron, bounded).
CAMPO_NOVO = "pericia"


def _precisa(d: dict, forca: bool) -> bool:
    f = d.get("ficha")
    if not isinstance(f, dict) or f.get("_erro"):
        return bool(conteudo_real(d))  # sem ficha mas com conteúdo → fichar
    if forca:
        return bool(conteudo_real(d))
    # Idempotência pelo MARCADOR DE SCHEMA que NÓS gravamos (_ficha_schema), não pelas chaves
    # que o LLM emite (CAMPO_NOVO pode ser omitido pelo modelo → re-ficharia eternamente).
    return d.get("_ficha_schema") != CAMPO_NOVO and bool(conteudo_real(d))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=10_000)
    ap.add_argument("--forca", action="store_true", help="re-ficha mesmo quem já tem o campo novo")
    a = ap.parse_args()
    arquivos = sorted(glob.glob(str(CACHE / "cdp_*.json")))
    feitos = pulados = erros = 0
    for caminho in arquivos:
        if feitos >= a.max:
            break
        try:
            d = json.loads(Path(caminho).read_text(encoding="utf-8"))
        except Exception:
            continue
        if not _precisa(d, a.forca):
            pulados += 1
            continue
        cont = conteudo_real(d)
        t0 = time.time()
        # SWEEP = SÓ nous stepfun:free (ilimitado/grátis — diretriz do dono; cerebras NÃO é ilimitado, fica
        # fora do volume do sweep). _refresh corrigido p/ funcionar standalone (refaz token se vazio).
        _refresh_nous_se_preciso()
        f = await extrair_ficha(cont, STEPFUN, provider="nous")
        if f.get("_erro"):
            erros += 1
            print(f"  ERRO {Path(caminho).name}: {f['_erro'][:60]}", flush=True)
            continue
        d["ficha"] = f
        d["_ficha_modelo"] = "stepfun:free"
        d["_ficha_schema"] = CAMPO_NOVO
        Path(caminho).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        feitos += 1
        # reporta presença da perícia (o schema v2) + a situação, robusto ao tipo.
        tem_per = "perícia✓" if isinstance(f.get("pericia_contabil"), dict) else "perícia—"
        sit = f.get("situacao") or "—"
        print(f"  [{feitos}] {Path(caminho).name} → {tem_per} situacao={sit} ({time.time()-t0:.0f}s)", flush=True)
    print(f"FIM re-ficha: {feitos} refichados, {pulados} já no schema novo, {erros} erros.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
