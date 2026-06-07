# -*- coding: utf-8 -*-
"""
siafe_runner — ponto ÚNICO de orquestração da coleta SIAFE (diária + sweep), com LOCKFILE de sessão única.

Filosofia (decisão do Mestre Jorge 2026-06-07):
- A coleta DIÁRIA incremental mantém os dados frescos: a aba OB Orçamentária lista as OBs MAIS NOVAS
  primeiro (DESC); como o volume/dia é pequeno (<1000), uma passada SEM filtro já captura o que entrou.
  Rodando todo dia, NÃO precisa de sweep diário (as OBs ficam atualizadas na aba). Idempotente (PK numero_ob).
- O SWEEP completo (por UG, fura o teto de 1000) é p/ BACKFILL histórico ou quando comandado — não diário.
- SESSÃO ÚNICA do SIAFE: um LOCKFILE impede coletas concorrentes (diária × sweep) que se derrubariam.

CLI:
  python -m compliance_agent.siafe_runner diario [ANO]      # atualização incremental (default: ano corrente)
  python -m compliance_agent.siafe_runner sweep [2|1]       # sweep completo (sistema 2=2024-26, 1=2016-23)
  python -m compliance_agent.siafe_runner ug <UG> [ANO]     # uma UG (fura o teto)
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_LOCK = _REPO / "data" / "sei_cache" / "siafe_lock.json"
_LOG = _REPO / "data" / "siafe_runner.log"
LOCK_TTL = 2 * 3600  # lock vence em 2h (evita travar p/ sempre se um processo morrer)


def _ano_corrente() -> int:
    return datetime.now(timezone.utc).year


def _log(m: str):
    line = f"[{int(time.time())}] {m}"
    print(line, flush=True)
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def lock_status() -> dict:
    try:
        if not _LOCK.exists():
            return {"locked": False}
        d = json.loads(_LOCK.read_text())
        if time.time() - d.get("ts", 0) > LOCK_TTL:
            return {"locked": False, "stale": True, "quem": d.get("quem")}
        return {"locked": True, **d}
    except Exception:
        return {"locked": False}


def _acquire(quem: str) -> bool:
    st = lock_status()
    if st.get("locked"):
        return False
    try:
        _LOCK.parent.mkdir(parents=True, exist_ok=True)
        _LOCK.write_text(json.dumps({"quem": quem, "ts": time.time(),
                                     "iso": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False))
        return True
    except Exception:
        return False


def _release():
    try:
        _LOCK.unlink(missing_ok=True)
    except Exception:
        pass


async def atualizar_diario(exercicio: int | None = None, maxn: int = 1000) -> dict:
    """Coleta incremental: pega as OBs mais novas da aba (sem filtro) do ano corrente e ingere.
    Mantém a base fresca sem sweep. Idempotente (PK numero_ob)."""
    from compliance_agent import siafe_ob_orcamentaria as M
    ano = int(exercicio or _ano_corrente())
    if not _acquire(f"diario:{ano}"):
        return {"ok": False, "erro": "lock", "detail": "Outra coleta SIAFE em andamento", "lock": lock_status()}
    try:
        _log(f"diário {ano}: iniciando (maxn={maxn})")
        res = await M.coletar(ano, maxn=maxn)
        if not res.get("ok"):
            _log(f"diário {ano}: coleta falhou: {res}")
            return {"ok": False, "etapa": "coleta", **res}
        ing = M.ingerir(ano, res.get("header", []), res.get("linhas", []))
        _log(f"diário {ano}: {res.get('n')} colhidas, {ing.get('ingeridas')} ingeridas (total {ing.get('total_tabela')})")
        # VERIFICADOR: o incremental pega as ~1000 OBs mais novas GLOBAIS; se um dia teve >1000 OBs (ex.: dia de
        # FOLHA), as OBs antigas desse dia caem abaixo da posição 1000 e seriam PERDIDAS. Conferimos o dia anterior
        # por Data Emissão; se estourou (>1000), coletar_por_data subdivide por Número e completa o dia.
        from datetime import timedelta
        verif = {}
        for delta in (1, 2):                      # ontem e anteontem (margem)
            d = (datetime.now(timezone.utc) - timedelta(days=delta)).strftime("%d/%m/%Y")
            try:
                r = await M.coletar_por_data(ano, d)
                verif[d] = {"estouro": r.get("estouro"), "ingeridas": r.get("ingeridas")}
                if r.get("estouro"):
                    _log(f"diário {ano}: ⚠️ dia {d} teve >1000 OBs — completado por subdivisão (+{r.get('ingeridas')})")
            except Exception as e:  # noqa: BLE001
                verif[d] = {"erro": f"{type(e).__name__}: {str(e)[:60]}"}
        return {"ok": True, "exercicio": ano, "colhidas": res.get("n"),
                "ingeridas": ing.get("ingeridas"), "total_tabela": ing.get("total_tabela"),
                "verificador_dias": verif}
    finally:
        _release()


async def verificar_dia(data: str, exercicio: int | None = None) -> dict:
    """Verifica/completa um dia específico (DD/MM/AAAA): conta OBs por Data Emissão; se >1000, subdivide."""
    from compliance_agent import siafe_ob_orcamentaria as M
    ano = int(exercicio or _ano_corrente())
    if not _acquire(f"verificar:{data}"):
        return {"ok": False, "erro": "lock", "lock": lock_status()}
    try:
        return await M.coletar_por_data(ano, data)
    finally:
        _release()


async def coletar_ug(ug: str, exercicio: int | None = None) -> dict:
    """Uma UG (fura o teto de 1000). Tenta filtro simples; se capar, usa subdivisão por prefixo."""
    from compliance_agent import siafe_ob_orcamentaria as M
    ano = int(exercicio or _ano_corrente())
    if not _acquire(f"ug:{ug}:{ano}"):
        return {"ok": False, "erro": "lock", "lock": lock_status()}
    try:
        r = await M.coletar_por_ug(ano, ug)
        if r.get("ok") and r.get("colhidas", 0) >= 990:
            r = await M.coletar_por_ug_grande(ano, ug)
        return r
    finally:
        _release()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "diario"
    if cmd == "diario":
        ano = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print(json.dumps(asyncio.run(atualizar_diario(ano)), ensure_ascii=False, indent=1))
    elif cmd == "ug":
        ug = sys.argv[2]; ano = int(sys.argv[3]) if len(sys.argv) > 3 else None
        print(json.dumps(asyncio.run(coletar_ug(ug, ano)), ensure_ascii=False, indent=1))
    elif cmd == "verificar":
        data = sys.argv[2]; ano = int(sys.argv[3]) if len(sys.argv) > 3 else None
        print(json.dumps(asyncio.run(verificar_dia(data, ano)), ensure_ascii=False, indent=1))
    elif cmd == "sweep":
        sistema = sys.argv[2] if len(sys.argv) > 2 else "2"
        if not _acquire(f"sweep:{sistema}"):
            print(json.dumps({"ok": False, "erro": "lock", "lock": lock_status()})); return
        try:
            from tools import siafe_sweep_full
            sys.argv = ["siafe_sweep_full", sistema]
            asyncio.run(siafe_sweep_full.main())
        finally:
            _release()
    else:
        print(json.dumps({"ok": False, "erro": f"comando desconhecido: {cmd}"}))


if __name__ == "__main__":
    main()
