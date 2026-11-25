#!/usr/bin/env bash
# pre_commit_v2.sh — o pre-commit só com CHECAGENS; a manutenção pesada sai do caminho do commit (O2.5, Esteira Única).
#
# POR QUE EXISTE. Perfil medido em 24/11 na VM-1 (2 vCPU, load 5,8–7,8), passo a passo do .git/hooks/pre-commit:
#     graphify update ............ 410 s, 2,7 GB RSS   ← rodava síncrono sempre que o load de 1 min era ≤ 4 no início
#     compressão de snapshot ...... 98 s (zstd -19 de 54 MB, 1×/dia, no primeiro commit do dia seguinte)
#     codegraph sync .............. — (não instalado na VM-1; `command -v` pula)
#     capabilities (3 geradores) .. 1,5 s · ruff ...... 0,01 s · scan_pii ... 0,13 s · gitnexus_enxugar ... 0,01 s
#     gate do painel (só static/) . ~25 s estático (8,7 s é o painel_modulo_livre); as checagens VIVAS já pulam com load > 3
# Os dois primeiros não são checagem — não bloqueiam nada, só atualizam o índice que agentes consultam — e são >99% do
# tempo. Saem para tools/grafo_pos_commit.sh (2º plano, depois do commit, no it-campo quando ele responde).
#
# CHECAGENS — antes (hook v1) × depois (este):
#     capabilities.yaml válido + derivados regenerados e no commit ... igual
#     AGENTS.md devolvido ao ponteiro (gitnexus_enxugar) .............. igual
#     ruff nos .py staged (BLOQUEIA) .................................. igual
#     gate do painel quando static/*.{html,js,css} staged (BLOQUEIA) .. igual
#     scan_pii nas linhas staged (BLOQUEIA) ........................... igual
#     graphify update / codegraph sync / compressão de snapshot ....... → tools/grafo_pos_commit.sh (post-commit)
#
# Ligado por `.git/hooks/pre-commit` só com JFN_PORTAO_V2=1 (ou `git config jfn.portaov2 1`); senão o hook v1 segue.
set -u
root="$(git rev-parse --show-toplevel)"
py="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)/.venv/bin/python"   # worktree de agente não tem .venv (22/11)

# JFN 2.0: valida capabilities.yaml e regenera derivados (jfn_tools.json, CAPACIDADES.md, prompt)
if [ -f "$root/capabilities.yaml" ]; then
  ( cd "$root" && PYTHONPATH=. "$py" -m tools.validate_capabilities >/dev/null 2>&1 \
    && "$py" -m tools.gen_router_tools >/dev/null 2>&1 \
    && "$py" -m tools.gen_capabilities_md >/dev/null 2>&1 \
    && git add data/jfn_tools.json data/yoda_capabilities_prompt.txt docs/CAPACIDADES.md 2>/dev/null ) \
    || echo "[pre-commit] validate/gen capabilities falhou"
fi

[ -x "$root/tools/gitnexus_enxugar.sh" ] && bash "$root/tools/gitnexus_enxugar.sh"

if [ -x "$root/tools/precommit_ruff.sh" ]; then
  bash "$root/tools/precommit_ruff.sh" || exit 1
fi

if git diff --cached --name-only --diff-filter=ACM | grep -qE '^static/.*\.(html|js|css)$'; then
  if [ -x "$root/tools/precommit_painel.sh" ]; then
    bash "$root/tools/precommit_painel.sh" || exit 1
  fi
fi

# O0.5 (Esteira Única, 24/11): repo PÚBLICO — CPF íntegro novo nunca entra. Bloqueia o commit.
( cd "$root" && "$py" -m tools.scan_pii --staged ) || { echo "[pre-commit] ⛔ CPF com DV válido nas linhas adicionadas — mascare antes"; exit 1; }
exit 0
