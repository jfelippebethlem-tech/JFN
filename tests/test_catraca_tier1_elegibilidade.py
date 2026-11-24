# -*- coding: utf-8 -*-
"""CATRACA (modo AVISO até a O4.10) — detector Tier 1 não lê tabela BRUTA de OB/contrato sem passar pela E9.

Invariante 3 do plano mestre v2 (§3.10): **sem elegibilidade, não há detector.** Tier 1 = campo `tier: 1` do
`config/qualidade_detectores.yaml` (O5.1) e, por ora, todo detector de MANCHETE declarada (`manchete: true`).

Regra mecânica: o módulo do detector cita `FROM`/`JOIN <tabela bruta>` (as de
`elegibilidade.TABELAS_BRUTAS`) e não cita a E9 (`v_elegibilidade_detector`, `dominio.elegibilidade` ou o módulo
`aplicacao.estagios.elegibilidade`) ⇒ violação (detector, tabela). A granularidade é o MÓDULO: um módulo com várias
regras (governo_couto_regras.py, cruzamentos_intel.py) responde, por detector, só pelas tabelas brutas que ele declara
em `fonte`; módulo de um detector só responde por todas as que lê. Leitura por ORM sem SQL literal (rules/engine.py) não é
medida aqui — aproximação declarada.

MODO AVISO: o que já viola em 24/11/2026 está em `tests/baseline_tier1_sem_elegibilidade.txt` e só gera aviso; a
lista SÓ ENCOLHE (violação nova falha; violação que sumiu tem de sair da lista). Vira bloqueio total na O4.10, quando
os detectores passarem a ler a E9 (troca do aviso por `assert not baseline`).
"""
import re
import warnings
from pathlib import Path

import yaml

from compliance_agent.aplicacao.estagios.elegibilidade import TABELAS_BRUTAS

RAIZ = Path(__file__).resolve().parents[1]
REGISTRO = RAIZ / "config" / "qualidade_detectores.yaml"
BASELINE = Path(__file__).with_name("baseline_tier1_sem_elegibilidade.txt")
_RX_E9 = re.compile(r"v_elegibilidade_detector|dominio\.elegibilidade|aplicacao\.estagios\.elegibilidade")


def _rx_bruta(tabela: str) -> re.Pattern:
    # `FROM m.ob_orcamentaria_siafe` (banco anexado) também é leitura bruta
    return re.compile(rf"\b(?:FROM|JOIN)\s+(?:\w+\.)?[\"`]?{re.escape(tabela)}[\"`]?\b", re.I)


_RX_BRUTAS = {t: _rx_bruta(t) for t in TABELAS_BRUTAS}


def tier1(registro: dict) -> dict[str, dict]:
    """`tier: 1` OU `manchete: true`. A O5.1 (frente paralela, 24/11) já grava `tier` em todo detector — e ninguém
    nasce Tier 1 ("sem medida → Tier 3 no dia 1"): por ora a manchete declarada continua no conjunto."""
    return {k: v for k, v in registro.items() if v.get("tier") == 1 or v.get("manchete") is True}


def violacoes_do_texto(fonte: str) -> set[str]:
    """Tabelas brutas lidas por um texto de módulo que NÃO passa pela E9."""
    if _RX_E9.search(fonte):
        return set()
    return {t for t, rx in _RX_BRUTAS.items() if rx.search(fonte)}


def violacoes() -> set[str]:
    reg = yaml.safe_load(REGISTRO.read_text(encoding="utf-8"))["detectores"]
    out = set()
    por_modulo: dict = {}
    for d in reg.values():
        por_modulo[d.get("modulo")] = por_modulo.get(d.get("modulo"), 0) + 1
    for nome, d in tier1(reg).items():
        mod = RAIZ / str(d.get("modulo") or "")
        if not mod.is_file():
            continue
        lidas = violacoes_do_texto(mod.read_text(encoding="utf-8", errors="replace"))
        # módulo com várias regras: só a interseção com as tabelas que ESTE detector declara em `fonte`
        declaradas = {re.split(r"[\s(]", str(f).strip(), maxsplit=1)[0] for f in (d.get("fonte") or [])}
        if por_modulo[d.get("modulo")] > 1:
            lidas &= declaradas
        out |= {f"{nome} {t}" for t in lidas}
    return out


def _baseline() -> set[str]:
    return {ln.split("#")[0].strip() for ln in BASELINE.read_text(encoding="utf-8").splitlines()
            if ln.split("#")[0].strip()}


def test_controles_da_regra():
    """Controle positivo (lê a bruta sem E9 → viola) e negativo (passa pela visão da E9 → não viola)."""
    assert violacoes_do_texto('con.execute("SELECT valor FROM ordens_bancarias WHERE x")') == \
        {"ordens_bancarias"}
    assert violacoes_do_texto("q = 'SELECT * FROM contratos_tcerj c JOIN ordens_bancarias o ON 1'") == \
        {"contratos_tcerj", "ordens_bancarias"}
    assert not violacoes_do_texto("SELECT * FROM ordens_bancarias o JOIN dominio.v_elegibilidade_detector e")
    assert not violacoes_do_texto("# a tabela ob_orcamentaria_siafe é citada só em comentário, sem FROM")
    assert not violacoes_do_texto("SELECT * FROM contratos_tcerj_extra")            # fronteira de palavra
    assert violacoes_do_texto("FROM m.ob_orcamentaria_siafe o WHERE") == {"ob_orcamentaria_siafe"}  # anexado


def test_tier1_existe_e_le_bruta_hoje():
    """A catraca mede algo: há detector Tier 1 e a baseline de 24/11/2026 não está vazia (senão é catraca morta)."""
    reg = yaml.safe_load(REGISTRO.read_text(encoding="utf-8"))["detectores"]
    assert len(tier1(reg)) >= 10
    assert _baseline(), "baseline vazia: ou a O4.10 chegou (troque o aviso por bloqueio) ou a regra quebrou"


def test_tier1_nao_le_bruta_sem_elegibilidade_aviso():
    atuais = violacoes()
    novas = sorted(atuais - _baseline())
    assert not novas, (
        "Detector Tier 1 (manchete) lendo tabela BRUTA de OB/contrato sem passar pela E9 (invariante 3, §3.10):\n  "
        + "\n  ".join(novas)
        + "\n\nLeia `dominio.v_elegibilidade_detector` (elegivel + motivo por detector) em vez da tabela bruta, ou "
          "tire o detector da manchete. A baseline só encolhe.")
    if atuais:
        warnings.warn(f"[AVISO O4.7] {len(atuais)} leitura(s) bruta(s) de detector Tier 1 sem a E9 (baseline em "
                      f"{BASELINE.name}); bloqueio na O4.10", stacklevel=1)


def test_baseline_so_encolhe():
    sobrando = sorted(_baseline() - violacoes())
    assert not sobrando, ("Já não violam (passaram pela E9, saíram da manchete ou o módulo mudou); tire de "
                          f"{BASELINE.name}:\n  " + "\n  ".join(sobrando))
