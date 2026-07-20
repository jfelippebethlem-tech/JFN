# -*- coding: utf-8 -*-
"""
UGs canônicas — mapeia o CÓDIGO da Unidade Gestora (UG) para o NOME correto da unidade.

POR QUÊ (aprendizado registrado em 2026-06-06):
  As Ordens Bancárias (`ordens_bancarias.ug_nome`) frequentemente rotulam a UG com o nome do ÓRGÃO
  SUPERIOR, não da unidade real. Caso concreto: **UG 133100 é o ITERJ** (Instituto de Terras e
  Cartografia do ERJ), mas nas OBs ela aparece como "Secretaria de Estado de Infraestrutura e Obras
  Públicas" / "...e Cidades". Resultado: pagamentos do ITERJ "sumiam" dentro da Secretaria.

  A tabela `despesa_execucao` (espelho do SIAFE) traz o nome CORRETO da unidade em `nome_ug`
  (UG 133100 → "INST. DE TERRAS E CARTOGR. DO EST. RJ"). Este módulo usa essa fonte como verdade e
  permite corrigir/normalizar o nome do órgão por código de UG nos relatórios do JFN.

USO:
    from compliance_agent import ugs
    ugs.nome_canonico("133100")            # -> "ITERJ — Instituto de Terras e Cartografia do ERJ"
    ugs.rotulo("133100", "Secretaria...")  # -> nome canônico (com código) p/ exibir no relatório

MANUTENÇÃO:
    cd ~/JFN && .venv/bin/python -m compliance_agent.ugs --reconstruir   # regera data/ug_canonico.json
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DATA = Path(os.environ.get("JFN_DATA_DIR", _ROOT / "data"))
_DB = _DATA / "compliance.db"
_MAPA = _DATA / "ug_canonico.json"

# Correções/curadorias humanas que prevalecem sobre o automático (aprendizado do Mestre Jorge).
# Chave = código de UG (string). Valor = nome canônico já amigável.
OVERRIDES = {
    "133100": "ITERJ — Instituto de Terras e Cartografia do ERJ",
    # Os 3 fundos que se confundem (vault ug-index-siafe-fundos) + DETRAN (nome SIAFE = "Trânsito"):
    # nome canônico carrega a SIGLA que o humano digita, senão o resolvedor não acha.
    "226300": "FSERJ — Fundo Soberano do Estado do Rio de Janeiro",
    "123400": "RIOPREVIDÊNCIA — Fundo Único de Previdência do Estado do RJ",
    "263100": "DETRAN-RJ — Departamento de Trânsito do Estado do Rio de Janeiro",
}

# Aliases conhecidos entre sistemas de numeração de UG (informativo).
# ITERJ no SIAFE-Rio 2 = 270042; no espelho TFE/dados-abertos (compliance.db) = 133100.
ALIASES = {
    "133100": {"siafe_rio2": "270042", "instituicao": "ITERJ", "orgao_superior": "Secretaria de Estado de Infraestrutura e Obras"},
    # nomes por extenso p/ a ponte UG→CNPJ do PNCP (editais/ug_cnpj) — só NOMES (fato público);
    # CNPJ nunca é hardcoded: sai da base PNCP pelo match
    "010100": {"instituicao": "Assembleia Legislativa do Estado do Rio de Janeiro"},
    "020100": {"instituicao": "Tribunal de Contas do Estado do Rio de Janeiro"},
}

_cache: dict | None = None


_CONECTIVOS = {"de", "do", "da", "dos", "das", "e", "di", "du", "em", "no", "na", "nos", "nas", "a", "o"}
_SIGLAS = {"RJ", "ERJ", "TJ", "PGE", "UG", "TCE", "TCU", "CBMERJ", "ITERJ", "INEA", "CEDAE",
           "COMLURB", "FES", "FUNESBOM", "FUNETJ", "S.A.", "SA", "EPP", "ME", "LTDA"}


def _titulo(s: str) -> str:
    """Normaliza CAIXA ALTA dura para Title Case legível: siglas preservadas, conectivos minúsculos."""
    s = (s or "").strip()
    if not s:
        return s
    palavras = []
    for i, w in enumerate(s.split()):
        wl = w.lower().strip(".")
        if w.upper() in _SIGLAS or (len(w) <= 3 and w.isupper() and wl not in _CONECTIVOS):
            palavras.append(w)                          # siglas (RJ, ERJ, TJ, PGE...)
        elif wl in _CONECTIVOS and i > 0:
            palavras.append(wl)                         # de/do/da minúsculo (exceto 1ª palavra)
        else:
            palavras.append(w.capitalize())
    return " ".join(palavras)


def carregar() -> dict:
    """Carrega o mapa {ug_codigo: nome_canonico}. Gera on-the-fly se o arquivo não existir."""
    global _cache
    if _cache is not None:
        return _cache
    if not _MAPA.exists():
        try:
            reconstruir()
        except Exception:
            _cache = dict(OVERRIDES)
            return _cache
    try:
        base = json.loads(_MAPA.read_text(encoding="utf-8"))
    except Exception:
        base = {}
    base.update(OVERRIDES)  # curadoria humana sempre vence
    _cache = base
    return _cache


def nome_canonico(ug_codigo: str, fallback: str = "") -> str:
    """Nome canônico da unidade para um código de UG. `fallback` se não houver mapeamento."""
    if not ug_codigo:
        return fallback
    return carregar().get(str(ug_codigo).strip(), fallback)


def rotulo(ug_codigo: str, ug_nome_ob: str = "") -> str:
    """
    Rótulo para exibir no relatório: nome canônico + código. Se não houver canônico, usa o nome da OB.
    Ex.: ("133100", "Secretaria de Infraestrutura") -> "ITERJ — Instituto de Terras e Cartografia do ERJ (UG 133100)"
    """
    cod = (str(ug_codigo).strip() if ug_codigo else "")
    nome = nome_canonico(cod, "") or _titulo(ug_nome_ob) or "Órgão não identificado"
    return f"{nome} (UG {cod})" if cod else nome


def reconstruir() -> dict:
    """(Re)constrói o mapa a partir de `despesa_execucao` (fonte com o nome correto da unidade)."""
    global _cache
    mapa: dict[str, str] = {}
    if _DB.exists():
        con = sqlite3.connect(_DB)
        try:
            # para cada UG, pega o nome_ug mais frequente (mais registros = mais confiável)
            rows = con.execute(
                "SELECT ug, nome_ug, COUNT(*) n FROM despesa_execucao "
                "WHERE ug IS NOT NULL AND nome_ug IS NOT NULL AND nome_ug != '' "
                "GROUP BY ug, nome_ug"
            ).fetchall()
        finally:
            con.close()
        melhor: dict[str, tuple[int, str]] = {}
        for ug, nome, n in rows:
            ug = str(ug).strip()
            if ug not in melhor or n > melhor[ug][0]:
                melhor[ug] = (n, _titulo(nome))
        mapa = {ug: nome for ug, (n, nome) in melhor.items()}
    mapa.update(OVERRIDES)
    _MAPA.parent.mkdir(parents=True, exist_ok=True)
    _MAPA.write_text(json.dumps(mapa, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    _cache = mapa
    return mapa


if __name__ == "__main__":
    if "--reconstruir" in sys.argv:
        m = reconstruir()
        print(f"ug_canonico.json regerado: {len(m)} UGs em {_MAPA}")
        print("  133100 ->", m.get("133100"))
    else:
        m = carregar()
        cod = next((a for a in sys.argv[1:] if a.isdigit()), "133100")
        print(f"UG {cod}: {nome_canonico(cod, '(sem mapeamento)')}")
        print(f"rótulo: {rotulo(cod, 'Secretaria de Estado de Infraestrutura e Obras')}")
        print(f"alias: {ALIASES.get(cod, {})}")
