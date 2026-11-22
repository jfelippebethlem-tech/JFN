"""FOCO no período Couto (22/11/2026): a cota única de `compliance_agent/foco.py` e as filas que a chamam."""
import ast
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from compliance_agent import foco
from compliance_agent.governo_couto import INICIO

RAIZ = Path(__file__).resolve().parents[1]


def _c(i):            # item Couto
    return {"id": f"c{i}", "d": "2026-06-01"}


def _r(i):            # item fora do período
    return {"id": f"r{i}", "d": "2025-06-01"}


def _ids(xs):
    return [x["id"] for x in xs]


# ── controle positivo / negativo da intercalação ─────────────────────────────────────────────────────────
def test_50_50_alterna_e_preserva_a_ordem_de_cada_grupo():
    itens = [_r(1), _r(2), _r(3), _c(1), _c(2), _c(3)]          # a fila antiga punha o Couto no fim
    out = foco.intercalar(itens, lambda x: x["d"], fracao=0.5)
    assert _ids(out) == ["c1", "r1", "c2", "r2", "c3", "r3"]
    for n in range(1, 7):                                        # em TODO prefixo, metade (arredondada p/ cima)
        assert sum(x["id"][0] == "c" for x in out[:n]) == -(-n // 2)


def test_falta_couto_completa_com_o_resto_sem_ociosidade():
    out = foco.intercalar([_r(1), _r(2), _c(1), _r(3), _r(4)], lambda x: x["d"], fracao=0.5, limite=4)
    assert _ids(out) == ["c1", "r1", "r2", "r3"]


def test_falta_resto_completa_com_couto():
    out = foco.intercalar([_c(1), _c(2), _c(3), _r(1)], lambda x: x["d"], fracao=0.5, limite=4)
    assert _ids(out) == ["c1", "r1", "c2", "c3"]


def test_so_couto_e_so_resto_mantem_a_ordem():
    assert _ids(foco.intercalar([_c(3), _c(1), _c(2)], lambda x: x["d"], fracao=0.5)) == ["c3", "c1", "c2"]
    assert _ids(foco.intercalar([_r(3), _r(1)], lambda x: x["d"], fracao=0.5)) == ["r3", "r1"]
    assert foco.intercalar([], lambda x: x["d"], fracao=0.5, limite=3) == []


def test_dia_de_transicao_23_03_e_couto_22_03_nao():
    assert INICIO == "2026-03-23"
    assert foco.eh_couto("2026-03-23") and foco.eh_couto("23/03/2026") and foco.eh_couto(date(2026, 3, 23))
    assert foco.eh_couto("2026-03-23T00:00:00.000")
    assert not foco.eh_couto("2026-03-22") and not foco.eh_couto("22/03/2026")
    assert not foco.eh_couto(None) and not foco.eh_couto("") and not foco.eh_couto("sem data")
    assert foco.eh_couto(True) and not foco.eh_couto(False)
    assert foco.eh_couto("2026-04") and not foco.eh_couto("2026-02")


def test_limite_consome_a_fila_preguicosamente():
    lidos = []

    def gerar():
        for i in range(1000):
            lidos.append(i)
            yield _c(i) if i % 2 else _r(i)
    out = foco.intercalar(gerar(), lambda x: x["d"], fracao=0.5, limite=4)
    assert len(out) == 4 and sum(x["id"][0] == "c" for x in out) == 2
    assert len(lidos) <= 6                                       # o filtro caro de cada fila não roda à toa


def test_fracao_zero_e_desligado_devolvem_a_ordem_antiga(tmp_path, monkeypatch):
    itens = [_r(1), _c(1), _r(2)]
    assert _ids(foco.intercalar(itens, lambda x: x["d"], fracao=0.0)) == ["r1", "c1", "r2"]
    cfg = tmp_path / "foco.yaml"
    cfg.write_text("periodo_couto:\n  ligado: false\n  fracao: 0.5\n", encoding="utf-8")
    monkeypatch.setattr(foco, "CONFIG", cfg)
    assert _ids(foco.intercalar(itens, lambda x: x["d"])) == ["r1", "c1", "r2"]
    cfg.write_text("periodo_couto:\n  ligado: true\n  fracao: 0.5\n", encoding="utf-8")
    assert _ids(foco.intercalar(itens, lambda x: x["d"])) == ["c1", "r1", "r2"]


def test_configuracao_unica_e_inicio_da_constante():
    c = foco.config(RAIZ / "config" / "foco.yaml")
    assert c == {"inicio": INICIO, "fracao": 0.5, "ligado": True}
    # a data NÃO é copiada no módulo nem no yaml (constante duplicada vira falso positivo)
    assert INICIO not in (RAIZ / "compliance_agent" / "foco.py").read_text(encoding="utf-8")
    assert "inicio:" not in (RAIZ / "config" / "foco.yaml").read_text(encoding="utf-8").split("periodo_couto:")[1]


def test_medir():
    assert foco.medir([_c(1), _r(1), _r(2), _r(3)], lambda x: x["d"]) == {"n": 4, "couto": 1, "pct": 25.0}
    assert foco.medir([], lambda x: x["d"])["pct"] is None


# ── processo SEI → período (OB paga do SIAFE + contratação TCE-RJ) ───────────────────────────────────────
@pytest.fixture
def base(tmp_path, monkeypatch):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ob_orcamentaria_siafe(numero_ob TEXT, data_emissao TEXT, status TEXT, "
                "status_envio TEXT, tipo_regularizacao TEXT, processo TEXT, valor REAL, exercicio INTEGER)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES(?,?,?,?,?,?,?,?)", [
        ("2026OB00001", "23/03/2026", "Contabilizado", "", "", "SEI-080001/000001/2025", 10.0, 2026),   # transição
        ("2026OB00002", "22/03/2026", "Contabilizado", "", "", "SEI-080001/000002/2025", 10.0, 2026),   # véspera
        ("2026OB00003", "10/05/2026", "Anulado", "", "", "SEI-080001/000003/2025", 10.0, 2026),         # não pago
        ("2026OB00004", "10/05/2026", "Contabilizado", "Erro no Pagamento", "", "SEI-080001/000004/2025", 1, 2026),
        ("2026OB00005", "10/05/2026", "Contabilizado", "", "", "080001/5/2025", 10.0, 2026),           # grafia
    ])
    con.execute("CREATE TABLE contratos_tcerj(sei_norm TEXT, data_contratacao TEXT)")
    con.executemany("INSERT INTO contratos_tcerj VALUES(?,?)", [("0800010000062026", "2026-04-01T00:00:00.000"),
                                                                 ("0800010000072026", "2026-03-20T00:00:00.000")])
    con.commit()
    con.close()
    monkeypatch.setenv("JFN_FOCO_DB", str(db))
    foco._MEMO.clear()
    yield db
    foco._MEMO.clear()


def test_processo_do_periodo_pela_ob_paga_e_pela_contratacao(base):
    assert foco.data_processo("SEI-080001/000001/2025") == "2026-03-23"
    assert foco.data_processo("080001_000001_2025") == "2026-03-23"          # nome de pasta do acervo
    assert foco.data_processo("SEI-080001/000002/2025") is None              # 22/03: governo anterior
    assert foco.data_processo("SEI-080001/000003/2025") is None              # OB anulada não é pagamento
    assert foco.data_processo("SEI-080001/000004/2025") is None              # devolvida pelo banco
    assert foco.data_processo("SEI-080001/000006/2026") == "2026-04-01"      # contratação TCE-RJ
    assert foco.data_processo("SEI-080001/000007/2026") is None              # contratado antes do período
    assert foco.data_processo("SEI-080001/000005/2025") == "2026-05-10"      # grafia irregular do SIAFE
    assert (base.parent / foco.CACHE_NOME).exists()
    assert json.loads((base.parent / foco.CACHE_NOME).read_text())["inicio"] == INICIO


def test_sem_banco_nao_vira_couto(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_FOCO_DB", str(tmp_path / "nao_existe.db"))
    foco._MEMO.clear()
    assert foco.processos_couto() == {} and foco.data_processo("SEI-080001/000001/2025") is None


def test_sob_pytest_sem_db_explicito_nao_toca_o_banco_real(monkeypatch):
    monkeypatch.delenv("JFN_FOCO_DB", raising=False)
    foco._MEMO.clear()
    assert foco.processos_couto() == {}


# ── cada fila chama a função única ───────────────────────────────────────────────────────────────────────
FILAS = [
    ("compliance_agent/pericia_integral.py", "fila"),                 # perícia integral (assinatura + cascata)
    ("tools/lex_execucao.py", "_alvos"),                               # Lex execução
    ("compliance_agent/llm/conferencia_opus.py", "conferir"),          # fila de conferência do Opus
    ("compliance_agent/indeterminados.py", "alvos_de_captura"),        # reperícia/recaptura dos indeterminados
    ("tools/sweep_recaptura_integral.py", "fila"),                     # recaptura integral
    ("tools/sei_integra_fila.py", "main"),                             # captura de íntegras VM-1
    ("tools/sei_integra_vm2.py", "montar_fila"),                       # VM-2 ~/JFN-worker e it-campo (exportar)
    ("tools/sei_sweep.py", "_fila"),                                   # sweep SEI (VM-1, VM-2, it-campo varredura)
    ("tools/sei_fila_por_dinheiro.py", "main"),                        # fila por dinheiro (entra na VM-2)
    ("compliance_agent/triagem_alertas.py", "selecionar"),             # triagem de alertas (API/assinatura)
    ("compliance_agent/triagem_alertas.py", "verificar_com_opus"),     # triagem — Opus
    ("tools/processo_360.py", "_lote_por_rodizio"),                    # processo_360 (lote)
    ("tools/sei_ficha_acervo.py", "fila"),                             # ficha do acervo (Haiku Batch)
    ("compliance_agent/qualidade/juiz.py", "fila"),                    # juiz de qualidade
]


@pytest.mark.parametrize("arq,funcao", FILAS)
def test_fila_chama_foco_intercalar(arq, funcao):
    arvore = ast.parse((RAIZ / arq).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(arvore) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == funcao)
    importa = any(isinstance(n, ast.ImportFrom) and n.module == "compliance_agent.foco"
                  and "intercalar" in {a.name for a in n.names} for n in ast.walk(fn))
    chama = any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "intercalar" for n in ast.walk(fn))
    assert importa and chama, f"{arq}:{funcao} não usa compliance_agent.foco.intercalar"


def test_juizo_do_360_no_shell_chama_foco():
    s = (RAIZ / "tools" / "sweep_360.sh").read_text(encoding="utf-8")
    assert "from compliance_agent.foco import data_processo, intercalar" in s and "fila = intercalar(fila" in s


def test_nenhuma_fila_copia_a_regra():
    """A cota mora só em foco.py: nenhuma fila reimplementa a data do período."""
    for arq, _ in FILAS:
        assert INICIO not in (RAIZ / arq).read_text(encoding="utf-8"), arq


# ── comportamento nas filas (com o mapa do período injetado) ─────────────────────────────────────────────
@pytest.fixture
def couto(monkeypatch):
    mapa = {"SEI-080001/000001/2026": "2026-05-01", "SEI-080001/000002/2026": "2026-06-01"}
    monkeypatch.setattr(foco, "processos_couto", lambda **k: mapa)
    return mapa


def test_conferencia_opus_lote_metade_couto(tmp_path, monkeypatch, couto):
    monkeypatch.setenv("JFN_CONFERENCIA_DB", str(tmp_path / "conf.db"))
    from compliance_agent.llm import conferencia_opus as Q
    from compliance_agent.llm.claude_motor import Pensamento
    for item, valor in (("sei:SEI-070001/000009/2024", 9e6), ("sei:SEI-070001/000008/2024", 8e6),
                        ("sei:SEI-080001/000001/2026", 1.0), ("sei:SEI-080001/000002/2026", 2.0)):
        Q.enfileirar("pericia_execucao", item, f"prompt {item}", motor="groq:x", resposta='{"nota": 5}', valor=valor)
    vistos = []
    Q.conferir(2, pensar=lambda t, p, **k: vistos.append(p) or Pensamento(texto='{"nota": 5}', modelo="claude-opus-5-5",
                                                                          segundos=1, tarefa=t))
    # por valor viriam os dois de 2024; com a cota, o Couto de maior valor primeiro e o maior valor do resto
    assert vistos == ["prompt sei:SEI-080001/000002/2026", "prompt sei:SEI-070001/000009/2024"]


def test_indeterminados_fila_metade_couto(couto):
    from compliance_agent import indeterminados as I
    diag = [{"sei": s, "ob_total": v, "causas": [next(iter(I.CAUSAS_DE_CAPTURA))], "relacionados": [],
             "relacionados_fora": []}
            for s, v in (("SEI-070001/000009/2024", 9e6), ("SEI-070001/000008/2024", 8e6),
                         ("SEI-080001/000001/2026", 1.0))]
    _, ordem = I.alvos_de_captura(diag)
    assert [x["sei"] for x in ordem] == ["SEI-080001/000001/2026", "SEI-070001/000009/2024", "SEI-070001/000008/2024"]


def test_triagem_data_do_fato_e_prefeitura_fora():
    from compliance_agent.triagem_alertas import data_do_alerta
    assert data_do_alerta({"tipo": "direcionamento", "evidencias": json.dumps({"data_ob": "2026-06-16"})}) == "2026-06-16"
    assert data_do_alerta({"tipo": "fracionamento", "evidencias": json.dumps({"data_ini": "2026-01-02",
                                                                              "data_fim": "2026-07-30"})}) == "2026-07-30"
    assert data_do_alerta({"tipo": "pcrj_d7_fracionamento", "evidencias": json.dumps({"data": "2026-06-16"})}) is None
    assert data_do_alerta({"tipo": "x", "evidencias": json.dumps({"data": "2026-06-16", "esfera": "municipal-rio"})}) is None
    assert data_do_alerta({"tipo": "acumulacao", "evidencias": json.dumps({"total_bruto": 1.0})}) is None
    assert data_do_alerta({"tipo": "x", "evidencias": "{json torto"}) is None


def test_juiz_metade_afirmacoes_da_gestao():
    from compliance_agent.qualidade import juiz
    from datetime import datetime
    A = juiz.Afirmacao
    cands = [A(f"painel:{x}", "painel", x, "t", "", v) for x, v in (("a", 900.0), ("b", 800.0), ("c", 700.0))]
    cands += [A(f"painel:gestao:T{i}", "painel", "g", "t", "", 1.0 / i) for i in (1, 2)]
    ordem = juiz.fila(cands, {}, datetime(2026, 11, 22))
    # vaga reservada de cada grupo primeiro (a, T1); sem a cota viria b, c, T2
    assert [a.id for a in ordem] == ["painel:a", "painel:gestao:T1", "painel:gestao:T2", "painel:b", "painel:c"]
