# -*- coding: utf-8 -*-
"""
Snapshot do relatório de inteligência (render_md) — rede de segurança de REFACTOR.

Mesma receita do Lex (tools/lex_snapshot_check.py): ctx SINTÉTICO fixo + ambiente
offline determinístico → markdown comparado byte a byte com o golden.

Uso:
    PYTHONHASHSEED=0 python tools/inteligencia_snapshot_check.py [--update]
"""
import difflib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
GOLDEN = REPO / "tests" / "golden"
GOLDEN.mkdir(parents=True, exist_ok=True)

os.environ["JFN_DB"] = str(GOLDEN / "snapshot_vazio.db")   # DB isolado (determinismo)
os.environ["JFN_VEREDITO_LLM_DISABLED"] = "1"              # sem LLM vivo
os.environ["JFN_LEX_LER_SEI"] = "0"
os.environ["JFN_LEX_DISCURSIVO"] = "0"

from compliance_agent.reporting import inteligencia as intel  # noqa: E402


def _ctx() -> dict:
    """ctx sintético com o MESMO esquema do montar() (chaves de inteligencia.py:826-838)."""
    linhas_2023 = [
        {"valor": 120000.00, "data": "2023-03-10", "orgao": "SEC ESTADUAL DE OBRAS", "numero_ob": "2023OB00101"},
        {"valor": 0.0, "data": "2023-05-02", "orgao": "SEC ESTADUAL DE OBRAS", "numero_ob": "2023OB00150"},
    ]
    linhas_2025 = [
        {"valor": 2400000.00, "data": "2025-02-15", "orgao": "SEC ESTADUAL DE OBRAS", "numero_ob": "2025OB00007"},
        {"valor": 1800000.00, "data": "2025-08-20", "orgao": "FUNDACAO SAUDE", "numero_ob": "2025OB00930"},
    ]
    pagamentos = {  # esquema fiel ao consultar_pagamentos (docstring inteligencia.py)
        "tem_dados": True, "anos": [2023, 2025], "total_geral": 4320000.00, "n_geral": 4,
        "por_ano": {
            2023: {"n": 2, "total": 120000.00, "linhas": linhas_2023,
                   "por_orgao": {"SEC ESTADUAL DE OBRAS": 120000.00}},
            2025: {"n": 2, "total": 4200000.00, "linhas": linhas_2025,
                   "por_orgao": {"SEC ESTADUAL DE OBRAS": 2400000.00, "FUNDACAO SAUDE": 1800000.00}},
        },
        "por_orgao_geral": {"SEC ESTADUAL DE OBRAS": 2520000.00, "FUNDACAO SAUDE": 1800000.00},
        "hhi": {"indice": 0.51, "nivel": "alto"},
        "raiz": "11222333", "por_estabelecimento": [], "n_estabelecimentos": 1,
        "matriz_mes": [],
        "total": 4320000.00, "n_obs": 4,
    }
    return {
        "cnpj": "11222333000181", "cnpj_fmt": intel.fmt_cnpj("11222333000181"),
        "nome": "SNAPSHOT ENGENHARIA E SERVICOS LTDA",
        "data": "2026-07-06", "risco": "MÉDIO", "score": 42,
        "pagamentos": pagamentos,
        "contratos": {"n": 0, "total": 0.0, "linhas": []},
        "cardinalidade": {"ok": False},
        "enriq": {"_fonte": "INDISPONIVEL", "dados": {"empresa": {
            "razao_social": "SNAPSHOT ENGENHARIA E SERVICOS LTDA",
            "cnae_principal": "Comércio varejista de vestuário",
            "data_abertura": "2022-11-01", "capital_social": 10000.0, "situacao": "ATIVA",
            "socios": [{"nome": "FULANO SNAPSHOT", "entrada": "2024-06-01"}],
        }}},
        "fonte_enriq": "INDISPONIVEL",
        "cruzamento": {}, "conflito_rede": [],
        "anomalias": {"ok": False, "n_obs": 0, "n_anomalas": 0, "itens": []},
        "natureza_sem_fins": {"ok": False, "sem_fins": False},
        "tcerj_itens": [], "contratado_tcerj": 0.0,
        "calibragem": {"risco": "MÉDIO", "score": 42, "motivos": ["snapshot sintético"]},
        "gazetas": {}, "raciocinio": "",
    }


def main() -> int:
    if os.environ.get("PYTHONHASHSEED") != "0":
        print("ERRO: rode com PYTHONHASHSEED=0.")
        return 2
    md = intel.render_md(_ctx())
    resumo = intel._resumo_executivo(_ctx())
    corpo = md + "\n\n===RESUMO-EXECUTIVO===\n" + resumo
    alvo = GOLDEN / "inteligencia_relatorio.md"
    if "--update" in sys.argv or not alvo.exists():
        alvo.write_text(corpo, encoding="utf-8")
        print(f"golden gravado: {alvo} ({len(corpo)} chars)")
        return 0
    esperado = alvo.read_text(encoding="utf-8")
    if corpo == esperado:
        print(f"OK: relatório idêntico ao golden ({len(corpo)} chars)")
        return 0
    diff = list(difflib.unified_diff(esperado.splitlines(), corpo.splitlines(),
                                     fromfile="golden", tofile="atual", lineterm=""))
    print(f"DIVERGÊNCIA ({len(diff)} linhas):")
    print("\n".join(diff[:60]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
