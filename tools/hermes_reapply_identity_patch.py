# -*- coding: utf-8 -*-
"""
hermes_reapply_identity_patch — re-aplica (idempotente) o "JFN patch" de IDENTIDADE DO REMETENTE no
core do Hermes (`~/hermes-agent/gateway/run.py`), que `hermes update` sobrescreve.

O patch faz o gateway PREPENDER `[Nome id=N]` a TODA mensagem (inclusive DM 1:1), para o Yoda reconhecer
o admin pelo id e tratar convidados pelo nome (a interpretação fica no environment_hint do config.yaml).

Idempotente: se o marcador já existe, não faz nada. Pensado p/ rodar no ExecStartPre do
hermes-gateway.service → auto-cura após qualquer `hermes update`. Sai 0 sempre (não bloquear o boot).

Uso: python -m tools.hermes_reapply_identity_patch   (ou caminho direto via venv)
"""
from __future__ import annotations

import sys
from pathlib import Path

RUN_PY = Path.home() / "hermes-agent" / "gateway" / "run.py"
MARKER = "# JFN patch: marca SEMPRE quem falou"
ANCHOR = "            thread_sessions_per_user=_thread_sessions_per_user,\n        )\n"
PATCH = (
    "        # JFN patch: marca SEMPRE quem falou (nome + id), inclusive em DM, para o\n"
    "        # Yoda tratar cada pessoa pelo nome e reconhecer o admin pelo id.\n"
    "        # (reaplicar apos `hermes update` se sobrescrito)\n"
    "        if source.user_name or source.user_id:\n"
    "            message_text = f\"[{source.user_name or 'desconhecido'} id={source.user_id}] {message_text}\"\n"
    "        elif _is_shared_multi_user and source.user_name:\n"
    "            message_text = f\"[{source.user_name}] {message_text}\"\n"
)


def main() -> int:
    if not RUN_PY.exists():
        print(f"[reapply-patch] run.py não encontrado em {RUN_PY} — nada a fazer.")
        return 0
    src = RUN_PY.read_text(encoding="utf-8")
    if MARKER in src:
        print("[reapply-patch] patch de identidade JÁ presente — ok.")
        return 0
    if ANCHOR not in src:
        print("[reapply-patch] ⚠️ ÂNCORA não encontrada (estrutura do run.py mudou após update). "
              "PATCH NÃO aplicado — revisar manualmente gateway/run.py (bloco is_shared_multi_user_session).")
        return 0
    novo = src.replace(ANCHOR, ANCHOR + PATCH, 1)
    # backup antes de gravar
    try:
        (RUN_PY.with_suffix(".py.bak.jfnpatch")).write_text(src, encoding="utf-8")
    except Exception:
        pass
    RUN_PY.write_text(novo, encoding="utf-8")
    print("[reapply-patch] ✅ patch de identidade RE-APLICADO em gateway/run.py (havia sido sobrescrito).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
