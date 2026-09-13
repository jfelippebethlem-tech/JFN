# -*- coding: utf-8 -*-
"""Re-FICHADOR: re-extrai a ficha dos processos SEI JÁ em cache (cdp_*.json) com o schema ATUAL
(ex.: novo campo `documentos`), SEM re-scrape — só relê o conteúdo cacheado e chama o nous stepfun:free
(ilimitado/grátis, regra do sweep). Idempotente: pula quem já tem o campo novo. Resumível (cada cache é
independente). Uso: cd ~/JFN && PYTHONPATH=. .venv/bin/python -m tools.sei_refichar [--max N] [--força]
"""
from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env", override=False)  # CEREBRAS_API_KEY etc.
except Exception:
    pass

from compliance_agent.sei.cache_arquivo import escrever_json, glob_cache, ler_json, nome_logico
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
    # ORÇAMENTO PRÓPRIO, para o código de saída voltar a significar alguma coisa. Medido em
    # 2026-08-07 na auditoria dos 32 passos agendados: `sei_refichar rc=124` em **407 de 474
    # execuções (86%)** — e 124 é o `timeout` do shell, não erro da ferramenta. Ela trabalha ~60 s
    # por documento (chamada de LLM), cabem 9 ou 10 no slot de 600 s, e o resto morre no relógio.
    # Um passo que termina "em falha" toda vez é um alarme permanente, e alarme permanente é
    # alarme desligado — foi por isso que o aborto crônico da recaptura passou quatro dias
    # invisível na mesma tabela. Parando por conta própria dentro do orçamento, `rc != 0` volta a
    # querer dizer defeito.
    ap.add_argument("--orcamento-s", type=int, default=0,
                    help="para sozinho ao atingir este tempo (0 = sem limite)")
    a = ap.parse_args()
    t_inicio = time.time()
    # `glob_cache` (não `glob.glob`) porque 5.741 dos 5.973 blobs do acervo estão em `.json.zst`:
    # com o glob cru esta ferramenta enxergava 3,9% do que deveria refichar.
    arquivos = glob_cache(CACHE, "cdp_*.json")
    feitos = pulados = erros = 0
    parou_por_tempo = False
    for caminho in arquivos:
        if feitos >= a.max:
            break
        if a.orcamento_s and (time.time() - t_inicio) >= a.orcamento_s:
            parou_por_tempo = True
            break
        d = ler_json(caminho)
        if not isinstance(d, dict):
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
            print(f"  ERRO {nome_logico(caminho)}: {f['_erro'][:90]}", flush=True)
            continue
        d["ficha"] = f
        d["_ficha_modelo"] = "stepfun:free"
        d["_ficha_schema"] = CAMPO_NOVO
        escrever_json(caminho, d)  # preserva `.zst` — `write_text` corromperia o blob comprimido
        feitos += 1
        # reporta presença da perícia (o schema v2) + a situação, robusto ao tipo.
        tem_per = "perícia✓" if isinstance(f.get("pericia_contabil"), dict) else "perícia—"
        sit = f.get("situacao") or "—"
        print(f"  [{feitos}] {Path(caminho).name} → {tem_per} situacao={sit} ({time.time()-t0:.0f}s)", flush=True)
    print(f"FIM re-ficha: {feitos} refichados, {pulados} já no schema novo, {erros} erros"
          + (f" — parei no orçamento de {a.orcamento_s}s (não é falha: a fila continua na próxima "
             f"passada)" if parou_por_tempo else "") + ".", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
