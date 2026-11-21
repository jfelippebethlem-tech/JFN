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
import tempfile
from pathlib import Path

os.environ["JFN_LEX_LER_SEI"] = "0"       # não abrir browser/SEI
os.environ["JFN_LEX_DISCURSIVO"] = "0"    # não chamar LLM
os.environ["JFN_LEX_SUBJETIVA"] = "0"     # camada subjetiva desligada: degradação declarada no golden

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
GOLDEN = REPO / "tests" / "golden"

# DB ISOLADO e SINTÉTICO (determinismo): sem isto o snapshot flutua com o estado do compliance.db de produção
# E com o JFN_DB temporário que o conftest injeta quando rodando sob pytest. 20/11/2026: o Lex passou a ler o
# pago do SIAFE (ob_orcamentaria_siafe, régua _ob_paga) e as NE/NL do credor — o banco do snapshot traz essas
# três tabelas com linhas sintéticas que exercitam OB paga, OB de valor zero, OB devolvida, OB excluída,
# cadeia OB→NL→NE, pago acima da NL e OB anterior à NL (controle positivo das réguas novas).
GOLDEN.mkdir(parents=True, exist_ok=True)
_DIR_SNAP = Path(os.environ.get("JFN_DATA_DIR") or tempfile.mkdtemp(prefix="lex_snapshot_"))
_DIR_SNAP.mkdir(parents=True, exist_ok=True)
os.environ["JFN_DATA_DIR"] = str(_DIR_SNAP)
os.environ["JFN_DB"] = str(_DIR_SNAP / "snapshot_siafe.db")


def _banco_sintetico(caminho: str) -> None:
    import sqlite3
    if os.path.exists(caminho):
        os.remove(caminho)
    con = sqlite3.connect(caminho)
    con.executescript(
        "CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, ug_pagadora TEXT, data_emissao TEXT,"
        " status TEXT, tipo TEXT, finalidade TEXT, tipo_ob TEXT, nl TEXT, credor TEXT, nome_credor TEXT,"
        " ug_liquidante TEXT, competencia TEXT, status_envio TEXT, gd TEXT, processo TEXT, re TEXT, pd TEXT,"
        " tipo_regularizacao TEXT, qtd_impressoes TEXT, assinatura_digital TEXT, vinculacao_pagamento TEXT,"
        " valor REAL, exercicio INTEGER, coletado_em TEXT, PRIMARY KEY (numero_ob, ug_emitente, exercicio));"
        "CREATE TABLE ne_siafe (numero TEXT, ug_emitente TEXT, exercicio INTEGER, data_emissao TEXT, doc_alt TEXT,"
        " tipo_alt TEXT, status TEXT, credor TEXT, nome_credor TEXT, fonte TEXT, natureza TEXT, precatorio TEXT,"
        " processo TEXT, tipo_reconhecimento_passivo TEXT, assinatura_eletronica TEXT, valor REAL, coletado_em TEXT,"
        " ano_ne INTEGER);"
        "CREATE TABLE nl_siafe (numero TEXT, ug_emitente TEXT, exercicio INTEGER, ano_nl INTEGER, data_emissao TEXT,"
        " doc_alt TEXT, tipo_alt TEXT, status TEXT, ne TEXT, nl_rec TEXT, status_comp TEXT, credor TEXT,"
        " nome_credor TEXT, gd TEXT, precatorio TEXT, processo TEXT, valor_retido REAL, assinatura_eletronica TEXT,"
        " valor REAL, coletado_em TEXT);")
    forn, nome = "11222333000181", "SNAPSHOT ENGENHARIA E SERVICOS LTDA"
    col = "2026-07-05 10:00:00"
    obs = [  # (numero_ob, ug, data, status, status_envio, nl, credor, nome, valor, exercicio)
        ("2023OB00101", "133100", "10/03/2023", "Contabilizado", "Processado e Pago", "2023NL00050", forn, nome, 120000.00, 2023),
        ("2023OB00150", "133100", "02/05/2023", "Contabilizado", "Processado e Pago", "", forn, nome, 0.0, 2023),
        ("2023OB00151", "133100", "02/06/2023", "Contabilizado", "Processado e Pago", "", forn, nome, 0.0, 2023),
        ("2023OB00152", "133100", "02/07/2023", "Contabilizado", "Processado e Pago", "", forn, nome, 0.0, 2023),
        ("2024OB00300", "133100", "05/04/2024", "Excluído", "Aguardando Geração RE", "", forn, nome, 50000.00, 2024),
        ("2025OB00006", "133100", "10/02/2025", "Contabilizado", "Erro no Pagamento", "2025NL00010", forn, nome, 2400000.00, 2025),
        ("2025OB00007", "133100", "15/02/2025", "Contabilizado", "Processado e Pago", "2025NL00010", forn, nome, 2400000.00, 2025),
        ("2025OB00930", "263100", "20/08/2025", "Contabilizado", "Processado e Pago", "2025NL00200", forn, nome, 1800000.00, 2025),
        ("2024OB00410", "133100", "12/06/2024", "Contabilizado", "Processado e Pago", "", forn, nome, 300000.00, 2024),
        # órgão do snapshot (UG 999999): três OBs de R$ 3 mi, duas ao mesmo favorecido
        ("2025OB00001", "999999", "10/01/2025", "Contabilizado", "Processado e Pago", "", "22333444000155", "EMPRESA A LTDA", 3000000.00, 2025),
        ("2025OB00002", "999999", "10/02/2025", "Contabilizado", "Processado e Pago", "", "22333444000155", "EMPRESA A LTDA", 3000000.00, 2025),
        ("2025OB00003", "999999", "10/03/2025", "Contabilizado", "Processado e Pago", "", "33444555000177", "EMPRESA B LTDA", 3000000.00, 2025),
    ]
    con.executemany(
        "INSERT INTO ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, status_envio, nl, credor,"
        " nome_credor, valor, exercicio, coletado_em, tipo_regularizacao) VALUES (?,?,?,?,?,?,?,?,?,?,?,'')",
        [o + (col,) for o in obs])
    con.executemany(
        "INSERT INTO ne_siafe (numero, ug_emitente, exercicio, data_emissao, status, credor, nome_credor, natureza,"
        " processo, valor, coletado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [("2023NE00020", "133100", 2023, "01/03/2023", "Contabilizado", forn, nome, "449051",
          "SEI-330020/000123/2023", 150000.00, col),
         ("2025NE00005", "133100", 2025, "05/02/2025", "Contabilizado", forn, nome, "449051",
          "SEI-330020/000123/2023", 2500000.00, col)])
    con.executemany(
        "INSERT INTO nl_siafe (numero, ug_emitente, exercicio, data_emissao, status, ne, credor, nome_credor,"
        " valor, valor_retido, coletado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [("2023NL00050", "133100", 2023, "05/03/2023", "Contabilizado", "2023NE00020", forn, nome, 120000.00, 6000.00, col),
         ("2025NL00010", "133100", 2025, "20/02/2025", "Contabilizado", "2025NE00005", forn, nome, 2300000.00, 115000.00, col)])
    con.commit()
    con.close()


_banco_sintetico(os.environ["JFN_DB"])

os.environ["JFN_VEREDITO_LLM_DISABLED"] = "1"  # flag oficial (2026-07-06) — sem LLM vivo no snapshot
# SEM REDE. Faltava: o `investigacao_dd` consultava o provider de cadastro quando `cadastral is
# None`, e esse era o único caminho do módulo que saía para a internet. O snapshot se dizia OFFLINE
# e, quando o provider respondia, o parecer ganhava endereço e porte e o golden divergia — um golden
# que depende de a rede estar fora é uma moeda, não um teste.
os.environ["JFN_SEM_REDE"] = "1"

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
            "socios": [{"nome": "FULANO SNAPSHOT", "data_entrada": "2024-06-01"}],
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
    assert org.get("ok") is True, f"gerar_orgao falhou: {org}"
    return {"lex_parecer_fornecedor.md": forn, "lex_parecer_orgao.md": org["md"]}


# O parêntese é solto de propósito. A versão anterior fixava "(aprendida da base JFN)", o texto do
# parecer passou a dizer "(aprendida da base histórica)", e o normalizador deixou de casar EM
# SILÊNCIO: o snapshot voltou a comparar o número vivo e quebrou sozinho quando o SIAFE ingeriu
# 21.069 OBs a mais (1.138.236 → 1.159.305). Guarda que para de guardar sem avisar é pior que
# guarda nenhuma — a catraca vermelha por ambiente ensina a ignorar a catraca. (2026-08-03)
RE_REGUA = re.compile(r"(\*\*R[ée]gua emp[íi]rica\b[^:]*:\*\*).*")


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
