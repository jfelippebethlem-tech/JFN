# -*- coding: utf-8 -*-
"""O10.1 (auditoria visual, itens 7, 10 e 6) — o painel não mente por formatação, por cor nem por botão.

Sem navegador: as funções puras do front (`static/js/src/nucleo/formato.js`, `ui/manchete.js`, `nucleo/http.js`)
rodam no Node como módulo ES. Defeitos medidos na auditoria de 25/11/2026 que estes testes travam:
  · "—" no lugar de INDISPONÍVEL em KPI (e_adit, p_adit, p_fant, g_nep, g_acuracia) e `fmtR(null)` = "R$ 0,00";
  · vermelho em contagem, em zero e em valor publicado (e_sobre, g_nep, g_porta, p_sanc, e_tac…);
  · "rules.engine: Tier 2 (ponto=43.3%>15%; …)" cru na aba Alertas;
  · controles de escrita ativos com o painel em manutenção (o servidor devolve 503 a todo POST);
  · "laranja?" em vermelho ao lado de pessoa física.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SRC = RAIZ / "static" / "js" / "src"
NODE = shutil.which("node")


def _node(codigo: str):
    """Roda `codigo` (ESM, top-level await) e devolve o JSON que ele imprime na última linha."""
    if not NODE:
        pytest.fail("node ausente — estes testes exigem Node (VM-1, VM-2 e it-campo têm)")
    r = subprocess.run([NODE, "--experimental-default-type=module", "--input-type=module", "-e", codigo],
                       capture_output=True, text=True, timeout=60, cwd=RAIZ)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _url(rel: str) -> str:
    return (SRC / rel).as_uri()


def test_valor_ausente_e_indisponivel_nunca_traco_nem_zero():
    out = _node(f"""
const f = await import('{_url("nucleo/formato.js")}');
console.log(JSON.stringify({{
  n_null: f.fmtN(null), n_und: f.fmtN(undefined), n_traco: f.fmtN('—'), n_ok: f.fmtN(40411), n_zero: f.fmtN(0),
  d_null: f.fmtD(null, 3), d_ok: f.fmtD(0.4567, 3), pct_null: f.fmtPct(null), pct_ok: f.fmtPct(12),
  r_null: f.fmtR(null), r_zero: f.fmtR(0), r_ok: f.fmtR(1234.5), rc_und: f.fmtRc(undefined), rc_ok: f.fmtRc(10),
  data_vazia: f.fmtData(''),
  kv_traco: f.kpiValor('—'), kv_vazio: f.kpiValor(''), kv_ok: f.kpiValor('302')
}}));""")
    for k in ("n_null", "n_und", "n_traco", "d_null", "pct_null", "r_null", "rc_und", "data_vazia", "kv_traco", "kv_vazio"):
        assert out[k] == "INDISPONÍVEL", (k, out[k])
    assert out["n_ok"] == "40.411" and out["n_zero"] == "0"
    assert out["d_ok"] == "0,457" and out["pct_ok"] == "+12%"
    assert out["r_zero"] == "R$ 0,00", "zero MEDIDO continua zero"
    assert out["r_ok"] == "R$ 1.234,50" and out["rc_ok"] == "R$ 10,00"
    assert out["kv_ok"] == "302"


def test_cor_do_kpi_vermelho_so_explicito_e_nunca_em_zero():
    out = _node(f"""
const f = await import('{_url("nucleo/formato.js")}');
const c = f.corKpi;
console.log(JSON.stringify([
  c('0', 'var(--rose)'), c('R$ 0,00', 'var(--rose)'), c('61.427', 'var(--rose)'), c('R$ 1.843.989.006,38', 'var(--rose)'),
  c('12', 'var(--red)'), c('—', 'var(--rose)'), c('INDISPONÍVEL', 'var(--crit-text)'), c('0', 'var(--crit-text)'),
  c('3', 'var(--crit-text)'), c('5', 'var(--amber)'), c('0', 'var(--amber)'), c('7', null)
]));""")
    assert out[:8] == [None] * 8, out           # contagem, zero, valor publicado, ausente: tinta neutra
    assert out[8] == "var(--crit-text)"         # vermelho assumido na chamada (falha operacional / Tier 1)
    assert out[9] == "var(--amber)" and out[10] is None and out[11] is None


def test_kpi_renderiza_indisponivel_sem_cor_de_alerta():
    out = _node(f"""
const d = await import('{_url("nucleo/dom.js")}');
console.log(JSON.stringify([d.kpi('—', 'Pior acréscimo verificado', 'var(--rose)'), d.kpi('0', 'Indícios', 'var(--rose)')]));""")
    for h in out:
        assert "color:" not in h, h
    assert ">INDISPONÍVEL<" in out[0]


def test_motivo_de_tier_vira_frase_sem_codigo():
    out = _node(f"""
const m = await import('{_url("ui/manchete.js")}');
console.log(JSON.stringify([m.motivoHumano('rules.engine'),
  m.motivoHumano('n=40<125; amostra_nao_estratificada; ponto=43.3%>15%; ic95_sup=60.8%>25%; sem_elegibilidade; cobertura_desconhecida'),
  m.motivoHumano('fp_acima_de_50pct_comprovada (Clopper-Pearson inf. 61.2%)')]));""")
    assert out[0] == "motor de regras"
    for t in out[1:]:
        assert not re.search(r"[a-z]_[a-z]|=|>|\d\.\d", t), t
    assert "43,3%" in out[1] and "60,8%" in out[1] and "125" in out[1]


def test_escrita_em_manutencao_nao_vai_a_rede():
    out = _node(f"""
globalThis.document = {{getElementById: id => id === 'jfn-manutencao'
  ? {{textContent: 'Em manutenção — dados congelados em 2026-11-24 12:25'}} : null}};
let rede = 0; globalThis.fetch = async () => {{ rede++; throw new Error('não devia ir à rede'); }};
const h = await import('{_url("nucleo/http.js")}');
const r = await h.J('/api/hermes/missoes', {{method: 'POST', body: '{{}}'}});
console.log(JSON.stringify({{r, rede}}));""")
    assert out["rede"] == 0
    assert out["r"]["manutencao"] is True and out["r"]["ok"] is False
    assert out["r"]["erro"] == "em manutenção — dados congelados em 2026-11-24 12:25"


def test_todo_post_do_front_tem_trava_de_manutencao():
    """Catraca: função do front que faz POST tem de estar coberta pela lista ESCRITA de `nucleo/manutencao.js`.
    (O beacon de limpeza das peças da sessão não é clique do usuário: fica de fora, nomeado.)"""
    isentos = {"limparEfemeros"}
    lista = (SRC / "nucleo" / "manutencao.js").read_text(encoding="utf-8")
    faltam = []
    for f in sorted(SRC.rglob("*.js")):
        if f.name == "manutencao.js" or "galaxia" in f.parts:
            continue
        linhas = f.read_text(encoding="utf-8").splitlines()
        for i, ln in enumerate(linhas):
            if not re.search(r"method\s*:\s*'POST'", ln) or "metodo===" in ln:
                continue
            nome = None
            for j in range(i, -1, -1):
                m = re.search(r"(?:async\s+)?function\s+([A-Za-z_]\w*)", linhas[j])
                if m:
                    nome = m.group(1)
                    break
            if nome and nome not in isentos and f"→ {nome} " not in lista:
                faltam.append(f"{f.relative_to(RAIZ)}:{i + 1} {nome}")
    assert not faltam, "POST sem trava de manutenção: " + ", ".join(faltam)


def test_rotulo_de_pessoa_fisica_sem_acusacao_nem_vermelho():
    src = (SRC / "abas" / "index.js").read_text(encoding="utf-8")
    assert "laranja?" not in src
    i = src.index("export async function renderLaranjas")
    corpo = src[i:src.index("export async function", i + 10)]
    assert 'class="tag rose"' not in corpo and "indício a verificar" in corpo
