# -*- coding: utf-8 -*-
"""O4.8 (plano mestre v2 §4 itens 7–9) — regra temporal, convergência do produto e identidade conservadora.

  · `RegraVersao`: o achado registra a versão NA DATA DO FATO + a esfera (controle externo); nunca crime/dolo;
  · convergência: Tier 3 fora do produto; só fracos juntos chegam no máximo a ATENCAO;
  · identidade: detector que liga pessoas/credores usa `dominio.identidade`; `parcial` nunca sustenta grave.
Fixtures sintéticas (sem banco real)."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import date
from pathlib import Path

import pytest

from compliance_agent.aplicacao import detectores as DET
from compliance_agent.aplicacao.detectores import Disparo
from compliance_agent.dominio import identidade as ID
from compliance_agent.dominio import regra_versao as RV
from compliance_agent.dominio.achado import Fato, Papel

RAIZ = Path(__file__).resolve().parents[1]
FONTES = Path.home() / "vault" / "fontes" / "juridicas"


# ── regra temporal ───────────────────────────────────────────────────────────────────────────────────────────────
def test_todo_detector_do_e10_tem_regra_versao():
    assert set(RV.VERSOES) == set(DET.MODULOS)
    for did, regs in RV.VERSOES.items():
        assert regs and all(r.rule_id == did and r.revisado_por == RV.PENDENTE for r in regs)


@pytest.mark.parametrize("ini, fim, lei, estado, lei_esperada", [
    (date(2019, 5, 2), None, None, "DETERMINADA", "8666"),
    (date(2024, 1, 1), date(2024, 12, 31), None, "DETERMINADA", "14133"),
    (date(2022, 1, 1), date(2022, 12, 31), None, "INDETERMINADA", None),       # transição: decide o contrato
    (date(2022, 1, 1), date(2022, 12, 31), "14133", "DETERMINADA", "14133"),
    (date(2022, 1, 1), date(2022, 12, 31), "8666", "DETERMINADA", "8666"),
    (date(2023, 12, 30), None, "8666", "INDETERMINADA", None),                 # 8.666 revogada em 30/12/2023
    (date(2020, 6, 1), None, "14133", "INDETERMINADA", None),                  # antes da 14.133
    (None, None, None, "INDETERMINADA", None),                                 # sem data: nunca a de hoje
])
def test_versao_na_data_do_fato(ini, fim, lei, estado, lei_esperada):
    v = RV.versao_na_data("e10.p4_fracionamento_objeto", ini, fim, lei=lei)
    assert v.estado == estado and (v.versao.lei if v.versao else None) == lei_esperada and v.motivo


def test_regra_sem_registro_e_sinal_sem_norma():
    assert RV.versao_na_data("x.nao_existe", date(2025, 1, 1)).estado == "SEM_REGISTRO"
    v = RV.versao_na_data("e10.tg_concentracao", date(2026, 5, 1))
    assert v.estado == "DETERMINADA" and v.versao.lei == RV.SEM_NORMA and v.versao.fonte_sha256 is None


def test_regra_versao_recusa_incoerencia():
    with pytest.raises(ValueError):
        RV.RegraVersao("x", "b", date(2024, 1, 1), date(2023, 1, 1), RV.SHA_L14133, "dono", "14133")
    with pytest.raises(ValueError):
        RV.RegraVersao("x", "b", date(2024, 1, 1), None, None, "dono", "14133")       # norma sem fonte
    with pytest.raises(ValueError):
        RV.RegraVersao("x", "b", date(2024, 1, 1), None, RV.SHA_L14133, " ", "14133")


def _plano(txt: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", txt))
    t = unicodedata.normalize("NFC", t)
    return re.sub(r"\s+", " ", t)


@pytest.mark.parametrize("sha, arquivo", sorted(RV.FONTES.items()))
def test_fonte_sha256_e_trecho_verbatim(sha, arquivo):
    p = FONTES / arquivo
    if not p.is_file():
        pytest.skip(f"cópia da norma ausente nesta máquina ({p})")
    bruto = p.read_bytes()
    assert hashlib.sha256(bruto).hexdigest() == sha
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            texto = _plano(bruto.decode(enc))
            break
        except UnicodeDecodeError:
            continue
    trechos = {r.trecho for regs in RV.VERSOES.values() for r in regs if r.fonte_sha256 == sha and r.trecho}
    assert trechos
    for t in trechos:
        assert t in texto, f"trecho não conferido verbatim em {arquivo}: {t[:60]}"


def test_texto_penal_detecta_e_tolera():
    assert RV.texto_penal("indício de crime doloso") == ["crime", "doloso"]
    assert RV.texto_penal("agiu com dolo") == ["dolo"]
    assert RV.texto_penal("dispensas por valor de mesma natureza; somatório acima do teto") == []


@pytest.mark.parametrize("did", sorted(DET.MODULOS))
def test_registro_do_e10_nao_qualifica_crime_nem_dolo(did):
    from compliance_agent.aplicacao.estagios import elegibilidade as E9
    reg = E9.carregar_registro()[did]
    txt = " ".join([str(reg.get("afirma") or "")] + [h.get("hipotese") or "" for h in reg.get("hipoteses_inocentes") or []])
    assert RV.texto_penal(txt) == []


def _disparo(**kw) -> Disparo:
    base = dict(chave="SEC X|2025|compras|ab", grupo="SEC X|2025", estado="INDICIO", observacao="soma acima do teto",
                entradas={"grupo": "SEC X|2025", "cluster": [{"enquadramento": "Lei 14.133/2021, Art. 75, II"}]},
                valores={"soma_cluster": 1.0},
                evidencias=[Fato(papel=Papel.SUPORTE, tipo="contratacao", fonte="t", referencia="1")])
    base.update(kw)
    return Disparo(**base)


def test_achado_registra_versao_na_data_do_fato_e_esfera():
    from compliance_agent.aplicacao.estagios import detectar as D
    a = D.para_achado("e10.p4_fracionamento_objeto", "v", "todos", "r", _disparo())
    rv = a.execucao.resultado["regra_versao"]
    assert rv["estado"] == "DETERMINADA" and rv["regra"]["lei"] == "14133" and rv["precisao_data_fato"] == "exercicio"
    assert rv["data_fato_inicio"] == "2025-01-01" and a.execucao.resultado["esfera"] == "controle_externo"


def test_achado_na_transicao_sem_regime_e_indeterminado():
    from compliance_agent.aplicacao.estagios import detectar as D
    d = _disparo(grupo="SEC X|2022", entradas={"grupo": "SEC X|2022", "cluster": [{"enquadramento": "Art. 75, II"}]})
    rv = D.para_achado("e10.p4_fracionamento_objeto", "v", "todos", "r", d).execucao.resultado["regra_versao"]
    assert rv["estado"] == "INDETERMINADA" and "regra" not in rv


def test_data_do_fato_pelas_entradas():
    from compliance_agent.aplicacao.estagios import detectar as D
    d = _disparo(grupo="NL1|294200", entradas={"obs": [{"data": "2025-03-02"}, {"data": "2025-05-09"}]})
    assert D.data_fato("e10.ob_paga_acima_liquidado", d)[:2] == (date(2025, 3, 2), date(2025, 5, 9))


def test_achado_com_texto_penal_e_recusado():
    from compliance_agent.aplicacao.estagios import ErroPermanente
    from compliance_agent.aplicacao.estagios import detectar as D
    with pytest.raises(ErroPermanente):
        D.para_achado("e10.p4_fracionamento_objeto", "v", "todos", "r", _disparo(observacao="crime de fraude"))


# ── convergência ─────────────────────────────────────────────────────────────────────────────────────────────────
def _r(det, score):
    from compliance_agent.detectores.base import ResultadoDetector
    return ResultadoDetector(detector=det, processo="p", score=score, status="confirmado")


def test_so_fracos_juntos_no_maximo_atencao():
    from compliance_agent.detectores import base
    rs = [_r(f"F{i}", 0.3) for i in range(5)]
    tiers = {f"F{i}": 2 for i in range(5)}
    assert base.score_processo(rs, {f"F{i}": 1.0 for i in range(5)}) > 0.8      # o agregador técnico passaria
    c = base.convergencia(rs, tiers, {f"F{i}": 1.0 for i in range(5)})
    assert c.so_fracos and c.score <= base.TETO_SO_FRACOS and c.nivel == "ATENCAO"


def test_forte_com_fraco_nao_e_tolhido():
    from compliance_agent.detectores import base
    c = base.convergencia([_r("A", 0.85), _r("B", 0.3)], {"A": 1, "B": 2}, {"A": 1.0, "B": 1.0})
    assert not c.so_fracos and c.nivel == "CRITICO" and c.fortes == ("A",) and c.fracos == ("B",)


def test_tier3_e_sem_tier_ficam_fora_do_produto():
    from compliance_agent.detectores import base
    c = base.convergencia([_r("A", 1.0), _r("B", 0.85)], {"A": 3}, {"A": 1.0, "B": 1.0})
    assert c.score == 0.0 and c.nivel == "BAIXO" and set(c.fora_tier) == {"A", "B"}


def test_score_processo_inalterado():
    from compliance_agent.detectores import base
    assert base.score_processo([_r("A", 0.85), _r("B", 0.6)], {"A": 1.0, "B": 0.8}) == pytest.approx(0.922, abs=1e-3)


# ── identidade ───────────────────────────────────────────────────────────────────────────────────────────────────
LIGA_PESSOAS = ("e10.ob_paga_acima_liquidado", "e10.ob_antes_da_liquidacao", "e10.tg_emergencial_incumbente",
                "e10.candidato_p4_siafe")
# Módulos do E10 que comparam documento/nome de PESSOAS de fontes diferentes: todos precisam passar por
# `dominio.identidade`. Os demais agregam pela própria chave do registro (CNPJ do credor da OB, UG, processo).
_RE_LIGA = re.compile(r"norm_nome\(|normalizar_nome\(|normalizar_fornecedor\(|_ident\(|resolver\(")


def test_detector_que_liga_pessoas_usa_dominio_identidade():
    for p in sorted((RAIZ / "compliance_agent/aplicacao/detectores").glob("*.py")):
        src = p.read_text(encoding="utf-8")
        if _RE_LIGA.search(src):
            assert "compliance_agent.dominio.identidade" in src, f"{p.name} liga pessoas sem dominio.identidade"


@pytest.mark.parametrize("nivel, grave", [("forte", True), ("parcial", False), ("probabilistico", False),
                                          ("homonimo", False), ("indeterminado", False)])
def test_parcial_nunca_sustenta_grave_no_achado(nivel, grave):
    from compliance_agent.aplicacao.estagios import detectar as D
    a = D.para_achado("e10.ob_paga_acima_liquidado", "v", "todos", "r",
                      _disparo(grupo="NL1|294200", entradas={"obs": [{"data": "2025-03-02"}]}, identidade=nivel))
    assert a.execucao.resultado["identidade"] == nivel and a.execucao.resultado["sustenta_grave"] is grave


def test_contabil_identidade_pelo_documento():
    from compliance_agent.aplicacao.detectores import contabil_siafe as C
    assert C.identidade([{"credor_doc": PJ, "nl_credor_doc": PJ}]) == "forte"
    assert C.identidade([{"credor_doc": PJ, "nl_credor_doc": PJ[:8] + "000272"}]) != "forte"   # filial: não forte
    assert C.identidade([{"credor_doc": PJ, "nl_credor_doc": PJ},
                         {"credor_doc": PJ, "nl_credor_doc": ""}]) == "indeterminado"             # o mais fraco vence


PJ = "11222333000181"


def test_incumbente_so_pelo_nome_nao_e_incumbente():
    from compliance_agent.aplicacao.detectores import troca_gestao as T
    from compliance_agent import governo_couto_regras as GC
    antes = {PJ, GC.norm_nome("ACME LTDA")}
    assert T._nivel_incumbente(PJ, "X", antes) == "forte"
    assert T._nivel_incumbente(None, "ACME LTDA", antes) == "homonimo"
    assert T._nivel_incumbente("99888777000166", "ACME LTDA", antes) is None


def test_candidato_p4_identidade_da_serie():
    from compliance_agent.aplicacao.detectores import candidato_p4_siafe as CP
    assert CP.identidade(PJ, "ACME") == "forte"
    assert CP.identidade("ACME LTDA", "ACME LTDA") == "homonimo"
    assert CP.identidade("CG0007060", "DIV.BENEFIC") == "indeterminado"


@pytest.mark.parametrize("did", LIGA_PESSOAS)
def test_detector_que_liga_declara_identidade_no_disparo(did):
    src = (RAIZ / DET.MODULOS[did].partition(":")[0].replace(".", "/")).with_suffix(".py").read_text(encoding="utf-8")
    assert "identidade=" in src
    assert ID.sustenta_grave(ID.Resolucao("parcial", "")) is False
