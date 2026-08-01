# -*- coding: utf-8 -*-
"""O teto de 55% era artefato do jeito de pedir: `codCargo` particiona e a janela deixa de morder.

MEDIDO (31/07/2026, competência 2026-06). A varredura global bate no teto de janela do backend na
página 10.000 (ver `test_folha_estado_teto_de_pagina`) e alcança 500.000 de 909.916 — 55%. O que
estava escrito como limite de FONTE ("não há filtro de partição") era limite do PARÂMETRO testado:
`orgao`, `orgaoId`, `vinculo`, `funcaoCargo`, `cargo`, `lotacao`, `folhaRef` são todos ignorados
(total continua 909.916), mas **`codCargo` filtra**:

    codCargo=403 (1º SARGENTO PM) → totalElements 17.000, totalPages 340, só aquele cargo
    codCargo=405 (1º TENENTE BM)  → totalElements    639
    páginas 0 · 100 · 200 · 339 dentro da partição → conteúdo distinto; 340 → vazio (fim real)

Como toda partição cabe muito abaixo de 10.000 páginas, a janela nunca é atingida e o universo
inteiro fica alcançável. Os códigos vêm de `/remuneracoes/cargos` (1.778 na competência medida).

O que estes testes travam: pedir por partição, retomar do cargo onde parou, e não declarar
`completa` antes do ÚLTIMO cargo — senão a competência congela parcial, que foi o defeito original.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.collectors import folha_estado as F


@pytest.fixture(autouse=True)
def lock_isolado(tmp_path, monkeypatch):
    """O lock de instância única mora num caminho fixo: sem isolar, um run de verdade em curso
    faz o teste sair por 'já em execução' e passar/falhar por motivo alheio ao que ele mede."""
    monkeypatch.setattr(F, "_LOCK", tmp_path / "folha_estado.lock")


@pytest.fixture()
def db(tmp_path):
    """Banco de teste com o mínimo que o coletor escreve — nunca o compliance.db real."""
    p = tmp_path / "t.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE registros_folha (id INTEGER PRIMARY KEY, pessoa_id INTEGER, "
                "cpf TEXT, nome TEXT, orgao_codigo TEXT, orgao_nome TEXT, cargo TEXT, "
                "vinculo TEXT, competencia TEXT, remuneracao_bruta REAL, remuneracao_liquida REAL, "
                "abonos REAL, descontos REAL, fonte TEXT, created_at TEXT, matricula VARCHAR(30))")
    con.commit()
    con.close()
    return str(p)


@pytest.fixture()
def api_falsa(monkeypatch):
    """API de mentira: 3 cargos, 2 páginas de 1 registro cada, e registra o que foi pedido."""
    pedidos: list[dict] = []

    def _get_falso(_client, params):
        pedidos.append(dict(params))
        pagina = params["page"]
        if pagina >= 2:
            return {"totalPages": 2, "remuneracoes": []}
        return {"totalPages": 2, "remuneracoes": [{
            "nomeServidor": f"FULANO {params['codCargo']}-{pagina}", "funcaoCargo": "CARGO",
            "orgao": "ORGAO", "matriculaServidor": f"{params['codCargo']}{pagina}",
            "cpf": "***.889.157-**", "vinculo": "CONCURSO PUBLICO",
            "totalVantagens": 1, "valorLiquido": 1, "totalDescontos": 0}]}

    monkeypatch.setattr(F, "_get", _get_falso)
    monkeypatch.setattr(F, "_cargos", lambda _client: [10, 20, 30])
    return pedidos


def _sem_banco(monkeypatch, progresso: dict):
    """Isola do disco: progresso controlado e escrita capturada."""
    salvos: list[dict] = []
    monkeypatch.setattr(F, "_carregar_progresso", lambda: dict(progresso))
    monkeypatch.setattr(F, "_salvar_progresso",
                        lambda comp, pagina, completa=False, cargo=None: salvos.append(
                            {"competencia": comp, "pagina": pagina, "completa": completa,
                             "cargo": cargo}))
    return salvos


def test_toda_pagina_pedida_traz_codcargo(api_falsa, monkeypatch, db):
    """Sem `codCargo` a consulta volta a ser a varredura global de 909.916 que morre em 55%."""
    _sem_banco(monkeypatch, {"competencia": "2026-06", "pagina": 0, "completa": False})

    F.coletar(paginas_por_run=50, pausa=0, db_path=db)

    assert api_falsa, "nenhuma página pedida"
    assert all("codCargo" in p for p in api_falsa), (
        f"pediu sem partição: {[p for p in api_falsa if 'codCargo' not in p][:2]}")


def test_percorre_todos_os_cargos(api_falsa, monkeypatch, db):
    """Pular cargo é perder gente — o universo é a UNIÃO das partições."""
    _sem_banco(monkeypatch, {"competencia": "2026-06", "pagina": 0, "completa": False})

    F.coletar(paginas_por_run=50, pausa=0, db_path=db)

    assert {p["codCargo"] for p in api_falsa} == {10, 20, 30}


def test_retoma_do_cargo_e_pagina_do_progresso(api_falsa, monkeypatch, db):
    """Retomada tem de continuar de onde parou; recomeçar do cargo 0 a cada run nunca termina."""
    _sem_banco(monkeypatch,
               {"competencia": "2026-06", "cargo": 20, "pagina": 1, "completa": False})

    F.coletar(paginas_por_run=50, pausa=0, db_path=db)

    assert api_falsa[0]["codCargo"] == 20 and api_falsa[0]["page"] == 1, api_falsa[0]
    assert 10 not in {p["codCargo"] for p in api_falsa}, "refez um cargo já concluído"


def test_so_marca_completa_no_ultimo_cargo(api_falsa, monkeypatch, db):
    """`completa` cedo congela a competência parcial — foi exatamente o defeito de 31/07."""
    salvos = _sem_banco(monkeypatch,
                        {"competencia": "2026-06", "pagina": 0, "completa": False})

    r = F.coletar(paginas_por_run=50, pausa=0, db_path=db)

    marcados = [s for s in salvos if s["completa"]]
    assert marcados, "varreu os 3 cargos e nunca marcou completa"
    assert all(s["cargo"] == 30 for s in marcados), (
        f"marcou completa antes do último cargo: {marcados}")
    assert r.get("completa") is True


def test_run_curto_para_no_meio_sem_mentir(api_falsa, monkeypatch, db):
    """Teto de páginas por run é para caber no cron — não pode virar 'competência completa'."""
    salvos = _sem_banco(monkeypatch,
                        {"competencia": "2026-06", "pagina": 0, "completa": False})

    r = F.coletar(paginas_por_run=2, pausa=0, db_path=db)

    assert not r.get("completa")
    assert salvos and not salvos[-1]["completa"], salvos[-1]
    assert salvos[-1]["cargo"] == 10, "perdeu o lugar: a retomada precisa do cargo corrente"


def test_banco_ocupado_nao_perde_o_lugar(api_falsa, monkeypatch, db):
    """`sweep_sei` (cron */30) escreve no mesmo compliance.db e segura o lock além do busy_timeout.

    Estourar ali perderia o lote E o progresso do run — a varredura de horas recomeçaria do zero.
    O contrato: para limpo, sem avançar o progresso, e diz o motivo."""
    salvos = _sem_banco(monkeypatch, {"competencia": "2026-06", "pagina": 0, "completa": False})
    monkeypatch.setattr(F, "_ESPERAS_BANCO", 2)
    monkeypatch.setattr(F.time, "sleep", lambda *_: None)

    class _ConOcupado(sqlite3.Connection):
        def executemany(self, *a, **k):
            raise sqlite3.OperationalError("database is locked")

    real = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect",
                        lambda *a, **k: real(*a, **{**k, "factory": _ConOcupado}))

    r = F.coletar(paginas_por_run=50, pausa=0, db_path=db)

    assert "ocupado" in (r.get("erro") or ""), f"não disse por que parou: {r}"
    assert not r.get("completa")
    assert not any(s["completa"] for s in salvos), "declarou completa sem ter gravado"


def test_sem_lista_de_cargos_nao_varre_global(monkeypatch, db):
    """Se `/cargos` cair, a alternativa não é a varredura de 55% disfarçada de coleta boa."""
    monkeypatch.setattr(F, "_cargos", lambda _client: [])
    monkeypatch.setattr(F, "_get", lambda *a, **k: pytest.fail("pediu página sem lista de cargos"))
    _sem_banco(monkeypatch, {"competencia": "2026-06", "pagina": 0, "completa": False})

    r = F.coletar(paginas_por_run=10, pausa=0, db_path=db)

    assert r.get("erro"), "silenciou a falta da lista de cargos"
    assert not r.get("completa")
