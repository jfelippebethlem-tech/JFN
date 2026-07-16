# -*- coding: utf-8 -*-
"""
Snapshot do parecer Lex (fornecedor + órgão) — rede de segurança de REFACTOR.

Gera os pareceres em markdown com contexto SINTÉTICO e ambiente OFFLINE (sem SEI,
sem LLM discursivo) e compara byte a byte com os goldens em tests/golden/.
Qualquer divergência de comportamento do motor aparece como diff no texto.

Uso:
    PYTHONHASHSEED=0 python tools/lex_snapshot_check.py            # verifica
    PYTHONHASHSEED=0 python tools/lex_snapshot_check.py --update   # (re)grava goldens

PYTHONHASHSEED=0 é obrigatório: o parecer itera sets de termos (ordem depende do
hash de str) — o teste pytest chama este script via subprocess com o seed fixo.
"""
import difflib
import re
import os
import sys
from pathlib import Path

os.environ["JFN_LEX_LER_SEI"] = "0"       # não abrir browser/SEI
os.environ["JFN_LEX_DISCURSIVO"] = "0"    # não chamar LLM

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
GOLDEN = REPO / "tests" / "golden"

# DB ISOLADO e vazio (determinismo): sem isto o snapshot flutua com o estado do compliance.db
# de produção E com o JFN_DB temporário que o conftest injeta quando rodando sob pytest.
GOLDEN.mkdir(parents=True, exist_ok=True)
os.environ["JFN_DB"] = str(GOLDEN / "snapshot_vazio.db")

os.environ["JFN_VEREDITO_LLM_DISABLED"] = "1"  # flag oficial (2026-07-06) — sem LLM vivo no snapshot

import compliance_agent.lex as lex  # noqa: E402


def _ctx_fornecedor() -> dict:
    """Contexto sintético RICO (exercita crescimento R12, estornos R10, CNAE R11, contratos, enriq)."""
    linhas_2023 = [
        {"valor": 120000.00, "data": "2023-03-10", "orgao": "SEC ESTADUAL DE OBRAS", "numero_ob": "2023OB00101"},
        {"valor": 0.0, "data": "2023-05-02", "orgao": "SEC ESTADUAL DE OBRAS", "numero_ob": "2023OB00150"},
        {"valor": 0.0, "data": "2023-06-02", "orgao": "SEC ESTADUAL DE OBRAS", "numero_ob": "2023OB00151"},
        {"valor": 0.0, "data": "2023-07-02", "orgao": "SEC ESTADUAL DE OBRAS", "numero_ob": "2023OB00152"},
    ]
    linhas_2025 = [
        {"valor": 2400000.00, "data": "2025-02-15", "orgao": "SEC ESTADUAL DE OBRAS", "numero_ob": "2025OB00007"},
        {"valor": 1800000.00, "data": "2025-08-20", "orgao": "FUNDACAO SAUDE", "numero_ob": "2025OB00930"},
    ]
    return {
        "cnpj": "11222333000181",
        "nome": "SNAPSHOT ENGENHARIA E SERVICOS LTDA",
        "data": "2026-07-06",
        "pagamentos": {
            "total": 4320000.00,
            "n_obs": 6,
            "por_ano": {
                "2023": {"total": 120000.00, "linhas": linhas_2023},
                "2025": {"total": 4200000.00, "linhas": linhas_2025},
            },
        },
        "enriq": {"dados": {"empresa": {
            "razao_social": "SNAPSHOT ENGENHARIA E SERVICOS LTDA",
            "cnae_principal": "Comércio varejista de artigos do vestuário e acessórios",
            "data_abertura": "2022-11-01",
            "capital_social": 10000.0,
            "situacao": "ATIVA",
            "socios": [{"nome": "FULANO SNAPSHOT", "entrada": "2024-06-01"}],
        }}},
    }


def _ctx_orgao() -> dict:
    return {
        "nome": "ORGAO SNAPSHOT DE TESTES",
        "ug": "999999",
        "data": "2026-07-06",
        "pagamentos": {
            "total": 9000000.00,
            "n_obs": 3,
            "por_ano": {"2025": {"total": 9000000.00, "linhas": [
                {"valor": 3000000.00, "data": "2025-01-10", "favorecido": "EMPRESA A LTDA", "numero_ob": "2025OB00001"},
                {"valor": 3000000.00, "data": "2025-02-10", "favorecido": "EMPRESA A LTDA", "numero_ob": "2025OB00002"},
                {"valor": 3000000.00, "data": "2025-03-10", "favorecido": "EMPRESA B LTDA", "numero_ob": "2025OB00003"},
            ]}},
        },
    }


def _gerar() -> dict[str, str]:
    forn = lex.parecer_md(_ctx_fornecedor())
    org = lex.gerar_orgao(_ctx_orgao(), salvar=False)
    # gerar_orgao(salvar=False) não devolve o md — renderiza de novo pelo caminho interno p/ capturar o texto
    achados = lex._achados_orgao(_ctx_orgao())
    emoji, rotulo, just = lex._grau(achados)
    org_md = lex._parecer_orgao_md(_ctx_orgao(), {"achados": achados, "emoji": emoji,
                                                  "rotulo": rotulo, "just": just}, "")
    assert org.get("ok") is True, f"gerar_orgao falhou: {org}"
    return {"lex_parecer_fornecedor.md": forn, "lex_parecer_orgao.md": org_md}


RE_REGUA = re.compile(r"(\*\*Régua empírica \(aprendida da base JFN\):\*\*).*")


def _normalizar(texto: str) -> str:
    """A régua empírica vem da compliance.db VIVA (cresce a cada coleta) — é ambiente, não
    comportamento do motor. Normalizada nos DOIS lados p/ o snapshot não quebrar sozinho."""
    return RE_REGUA.sub(r"\1 [régua viva da base — normalizada p/ snapshot]", texto)


def main() -> int:
    if os.environ.get("PYTHONHASHSEED") != "0":
        print("ERRO: rode com PYTHONHASHSEED=0 (ordem de sets no parecer).")
        return 2
    update = "--update" in sys.argv
    GOLDEN.mkdir(parents=True, exist_ok=True)
    falhas = 0
    for nome, texto in _gerar().items():
        texto = _normalizar(texto)
        alvo = GOLDEN / nome
        if update or not alvo.exists():
            alvo.write_text(texto, encoding="utf-8")
            print(f"golden gravado: {alvo} ({len(texto)} chars)")
            continue
        esperado = _normalizar(alvo.read_text(encoding="utf-8"))
        if texto == esperado:
            print(f"OK: {nome} idêntico ao golden ({len(texto)} chars)")
        else:
            falhas += 1
            diff = list(difflib.unified_diff(esperado.splitlines(), texto.splitlines(),
                                             fromfile=f"golden/{nome}", tofile="atual", lineterm=""))
            print(f"DIVERGÊNCIA em {nome} ({len(diff)} linhas de diff):")
            print("\n".join(diff[:60]))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
