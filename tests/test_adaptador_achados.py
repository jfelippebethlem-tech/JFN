# -*- coding: utf-8 -*-
"""O5.2 — adaptador das três gerações → `Achado` (compliance_agent/adaptadores/achados.py), reprodução
(tools/reproduzir_achado.py) e a migração `deploy/vm2/postgres/achados_001.sql`.

Fixtures sintéticas (CPF só mascarado). A parte PG roda SÓ com `JFN_EVIDENCIAS_DSN=postgresql://…` e SEMPRE num
esquema temporário criado e apagado aqui — nunca no `public` nem num esquema de produção."""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import uuid
from pathlib import Path

import pytest

from compliance_agent.adaptadores import achados as A
from compliance_agent.dominio.achado import Papel, StatusAchado
from compliance_agent.dominio.estados import EstadoSaida
from compliance_agent.evidencias import ENV_DSN

REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("reproduzir_achado", REPO / "tools" / "reproduzir_achado.py")
R = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(R)

DSN = os.environ.get(ENV_DSN, "")
precisa_pg = pytest.mark.skipif(not DSN.startswith(("postgresql://", "postgres://")),
                                reason="sem JFN_EVIDENCIAS_DSN (PostgreSQL de teste) — rodar na VM-2 com o DSN")


def _alerta(**kw):
    d = {"id": 7, "tipo": "acumulacao", "severidade": "alta",
         "titulo": "Emprego múltiplo a verificar — FULANA (CPF XX123456XXX)",
         "descricao": "aparece em 2 órgãos na competência 2026-09",
         "evidencias": json.dumps({"cpf": "XX123456XXX", "n_orgaos": 2}), "status": "novo",
         "pessoa_id": None, "empresa_id": None, "contrato_id": None, "processo_sei_id": None,
         "ordem_bancaria_id": None, "data_referencia": None, "created_at": "2026-09-28 12:56:29"}
    d.update(kw)
    return d


# ───────────────────────── geração 1: alertas ─────────────────────────

@pytest.mark.parametrize("tipo, titulo, regra", [
    ("acumulacao", "Emprego múltiplo a verificar — X", "rules.emprego_multiplo_orgaos"),
    ("acumulacao", "Possível acúmulo ilegal — XX1XXX", "rules.acumulo_cargo"),
    ("fracionamento", "Fracionamento OB — EMPRESA / UG 1", "rules.ob_fracionamento"),
    ("direcionamento", "OB para empresa nova (10d) — E", "rules.ob_empresa_nova"),
    ("enriquecimento", "Remuneração acima do teto — X", "rules.remuneracao_acima_teto"),
    ("emendas_d3_favorecido_sancionado", "t", "emendas.D3"),
    ("pcrj_d9_socio_na_folha", "t", "pcrj.d9_socio_na_folha"),
    ("pcrj_d11_aditivo_estourado", "t", "pcrj.d11_aditivo_estourado"),
])
def test_alerta_vai_para_a_regra_do_registro(tipo, titulo, regra):
    a = A.de_alerta(_alerta(tipo=tipo, titulo=titulo))
    assert a.execucao.regra_id == regra
    assert a.execucao.versao.startswith(a.execucao.versao.split("@")[0]) and "@" in a.execucao.versao
    assert a.estado is EstadoSaida.INDICIO and a.evidencias[0].papel is Papel.SUPORTE


def test_titulo_zumbi_vai_ao_agregado_e_e_marcado():
    a = A.de_alerta(_alerta(titulo="Emprego múltiplo suspeito — CPF XX1XXX"))     # nenhuma regra atual produz
    assert a.execucao.regra_id == "rules.acumulacao" and a.execucao.resultado["titulo_sem_regra_atual"] is True


def test_tipo_desconhecido_nao_some():
    assert A.de_alerta(_alerta(tipo="groq_ob")).execucao.regra_id == "nao_registrado.groq_ob"


def test_status_legado_sem_autor_nao_vira_decisao():
    for st in ("descartado", "confirmado"):
        a = A.de_alerta(_alerta(status=st))
        assert a.status is StatusAchado.EM_REVISAO and a.execucao.resultado["status_legado"] == st
    assert A.de_alerta(_alerta()).status is StatusAchado.TRIAGEM


def test_hipoteses_alternativas_vem_do_registro():
    a = A.de_alerta(_alerta(tipo="pcrj_d9_socio_na_folha", titulo="t"))
    assert "homônimo (CPF incompatível)" in a.hipoteses_alternativas


def test_hash_estavel_e_sensivel_a_entrada():
    h1 = A.de_alerta(_alerta()).execucao.entradas_hash
    assert h1 == A.de_alerta(_alerta(created_at="2027-01-01")).execucao.entradas_hash   # carimbo não é entrada
    assert h1 != A.de_alerta(_alerta(evidencias=json.dumps({"cpf": "XX123456XXX", "n_orgaos": 3}))).execucao.entradas_hash


# ───────────────────────── geração 2: detectores/ ─────────────────────────

def _linha_exec(status="confirmado", **kw):
    d = {"contrato": "C-1", "detector": "X1", "orgao_cnpj": "00000000000191", "fornecedor": "F", "score": 0.9,
         "status": status, "motivo": "acréscimo de 31%", "explicacao_inocente": "reforma tem 50%",
         "valores": json.dumps({"pct": 0.31}), "evidencia": json.dumps([{"fonte": "PNCP", "trecho": "termo 1",
                                                                         "hash": "h", "capturado_em": "t"}]),
         "gerado_em": "2026-11-20"}
    d.update(kw)
    return d


@pytest.mark.parametrize("status, estado", [("confirmado", EstadoSaida.INDICIO), ("descartado", EstadoSaida.AUSENTE),
                                            ("nao_avaliavel", EstadoSaida.INDISPONIVEL)])
def test_status_do_detector_vira_estado_honesto(status, estado):
    a = A.de_achado_db("achado_execucao", _linha_exec(status))
    assert a.execucao.regra_id == "det.X1CrescimentoAditivo" and a.estado is estado
    assert a.status is StatusAchado.TRIAGEM                       # "confirmado" do detector ≠ confirmação humana
    assert a.hipoteses_alternativas[0] == "reforma tem 50%"
    assert a.evidencias[0].trecho_literal == "termo 1"


def test_codigos_de_detector_mapeiam_o_registro():
    from compliance_agent.qualidade import detectores as D
    reg = D.carregar()
    for cod in ("X1", "J8", "P7", "C2", "C3/C5", "EST-VALOR-EXCEDIDO"):
        assert A.regra_do_detector(cod) in reg, cod
    assert A.regra_do_detector("Z9") == "nao_registrado.Z9"


def test_de_resultado_aceita_resultado_detector_vivo():
    from compliance_agent.detectores.base import ResultadoDetector
    r = ResultadoDetector(detector="P4", processo="SEI-1/2/2025", score=0.8, status="confirmado",
                          valores={"soma": 1}).add_evidencia("SIAFE", "OB 2025OB00001")
    a = A.de_resultado(r.to_dict(), origem="memoria:teste")
    assert a.execucao.regra_id == "det.P4Fracionamento" and a.execucao.processo == "SEI-1/2/2025"


# ───────────────────────── geração 3: cruzamentos_intel ─────────────────────────

def test_item_intel_vira_achado():
    cache = {"ok": True, "achados": [{"cnpj": "00000000000191", "nome": "E", "score": 40, "rating": "🟡"}]}
    a = A.de_intel("radar_risco", A.itens_intel(cache)[0])
    assert a.execucao.regra_id == "intel.radar_risco" and a.execucao.origem == "intel:radar_risco:00000000000191"
    assert A.de_intel("ninho_sala", {"sala": "S1"}).execucao.regra_id == "ninho_sala"


# ───────────────────────── reprodução ─────────────────────────

@pytest.fixture()
def bancos(tmp_path):
    comp = tmp_path / "compliance.db"
    c = sqlite3.connect(comp)
    c.execute(f"CREATE TABLE alertas ({', '.join(A.COLS_ALERTA)})")
    linha = _alerta()
    c.execute(f"INSERT INTO alertas VALUES ({','.join('?' * len(A.COLS_ALERTA))})",
              [linha[k] for k in A.COLS_ALERTA])
    c.commit()
    c.close()
    ach = tmp_path / "achados.db"
    c = sqlite3.connect(ach)
    c.execute("CREATE TABLE achado_execucao (contrato, detector, orgao_cnpj, fornecedor, score, status, motivo, "
              "explicacao_inocente, valores, evidencia, gerado_em)")
    le = _linha_exec()
    c.execute("INSERT INTO achado_execucao VALUES (?,?,?,?,?,?,?,?,?,?,?)", list(le.values()))
    c.commit()
    c.close()
    return comp, ach


def _gravado(a):
    e = a.execucao
    return {"regra_id": e.regra_id, "regra_versao": e.versao, "entradas_hash": e.entradas_hash,
            "resultado": e.resultado}


def test_reproduz_da_origem(bancos):
    comp, ach = bancos
    for origem in ("alertas:7", "achado_execucao:C-1|X1"):
        a = R.ler_origem(origem, comp, ach)
        assert R.comparar(_gravado(a), a)["veredito"] == "REPRODUZIDO"
    assert R.ler_origem("alertas:999", comp, ach) is None
    assert R.comparar(_gravado(a), None)["veredito"] == "FONTE_AUSENTE"


def test_reproducao_acusa_divergencia_e_versao(bancos):
    comp, ach = bancos
    a = R.ler_origem("alertas:7", comp, ach)
    g = _gravado(a)
    assert R.comparar({**g, "entradas_hash": "0" * 64}, a) == {"veredito": "DIVERGE", "diferencas": ["entradas_hash"]}
    assert R.comparar({**g, "regra_versao": "x@antiga"}, a)["veredito"] == "VERSAO_MUDOU"


def test_amostra_e_estratificada_e_deterministica():
    import tools.achados_sombra as S
    todos = [A.de_alerta(_alerta(id=i)) for i in range(50)] + [A.de_alerta(_alerta(id=100, tipo="groq_ob"))]
    am = S.amostrar(todos, 10)
    assert len(am) == 10 and "nao_registrado.groq_ob" in {x.execucao.regra_id for x in am}    # piso de 1 por regra
    assert [x.execucao.origem for x in am] == [x.execucao.origem for x in S.amostrar(todos, 10)]


# ───────────────────────── PostgreSQL (esquema temporário) ─────────────────────────

@pytest.fixture()
def pg():
    import psycopg
    nome = f"tmp_achados_{uuid.uuid4().hex[:10]}"
    con = psycopg.connect(DSN, autocommit=True)
    try:
        A.aplicar_schema(con, nome)
        yield con, nome
    finally:
        con.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')
        con.close()


@precisa_pg
def test_migracao_idempotente_e_carga_idempotente(pg, bancos):
    con, s = pg
    A.aplicar_schema(con, s)                                       # 2ª aplicação: nada muda, nada quebra
    assert con.execute(f'SELECT count(*) FROM "{s}".migracoes WHERE versao=%s', ("achados_001",)).fetchone()[0] == 1
    comp, ach = bancos
    lote = [R.ler_origem("alertas:7", comp, ach), R.ler_origem("achado_execucao:C-1|X1", comp, ach)]
    assert A.gravar(con, s, lote) == {"recebidos": 2, "gravados": 2}
    assert A.gravar(con, s, lote) == {"recebidos": 2, "gravados": 0}
    n = {t: con.execute(f'SELECT count(*) FROM "{s}".{t}').fetchone()[0]
         for t in ("execucao_regra", "achado", "achado_evidencia", "decisao_humana")}
    assert n == {"execucao_regra": 2, "achado": 2, "achado_evidencia": 3, "decisao_humana": 0}
    aid, origem, rid, ver, h, res = con.execute(
        f'SELECT a.id, e.origem, e.regra_id, e.regra_versao, e.entradas_hash, e.resultado FROM "{s}".achado a '
        f'JOIN "{s}".execucao_regra e ON e.id = a.execucao_regra_id ORDER BY a.id LIMIT 1').fetchone()
    g = {"regra_id": rid, "regra_versao": ver, "entradas_hash": h, "resultado": res}
    assert R.comparar(g, R.ler_origem(origem, comp, ach))["veredito"] == "REPRODUZIDO"


@precisa_pg
def test_banco_recusa_o_que_o_contrato_recusa(pg, bancos):
    import psycopg
    con, s = pg
    comp, ach = bancos
    A.gravar(con, s, [R.ler_origem("alertas:7", comp, ach)])
    aid = con.execute(f'SELECT id FROM "{s}".achado').fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):            # só pessoa conclui
        con.execute(f"UPDATE \"{s}\".achado SET estado='CONCLUSAO_REVISADA' WHERE id=%s", (aid,))
    with pytest.raises(psycopg.errors.CheckViolation):            # ABSTEVE sem motivo
        con.execute(f"UPDATE \"{s}\".achado SET estado='ABSTEVE' WHERE id=%s", (aid,))
    with pytest.raises(psycopg.errors.CheckViolation):            # decisão sem autor
        con.execute(f"INSERT INTO \"{s}\".decisao_humana (achado_id, autor, status, justificativa) "
                    "VALUES (%s, ' ', 'confirmado', 'x')", (aid,))
    con.execute(f"INSERT INTO \"{s}\".decisao_humana (achado_id, autor, status, justificativa) "
                "VALUES (%s, 'fiscal', 'confirmado', 'conferido no SIAFE')", (aid,))
    con.execute(f"UPDATE \"{s}\".achado SET status='confirmado', estado='CONCLUSAO_REVISADA' WHERE id=%s", (aid,))
