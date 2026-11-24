# -*- coding: utf-8 -*-
"""O6.7 — memória do agente sem auto-reforço (auditoria AI-01/AI-02, 24/11/2026).

O defeito: `aprender` somava +delta a CADA repetição (a mesma saída do Hermes repetida 10× chegava a 1,0), trocava
o valor pelo "mais longo" sem histórico, e `contexto_para_prompt` reinjetava por confiança — o modelo relia, como
conhecimento confiável, o que ele mesmo escreveu. Aqui: só fonte primária INDEPENDENTE sobe a confiança; saída de
LLM nunca reforça; estados categóricos com validade; versões guardadas; migração idempotente que não apaga nada.
"""
from __future__ import annotations

import ast
import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compliance_agent.database.models import Base, MemoriaAprendizado
from compliance_agent.llm import memoria as M

RAIZ = Path(__file__).resolve().parents[1]
SEI_A = M.raiz_fonte_primaria("sei", "SEI-270131/000548/2023 doc 12345")
SEI_B = M.raiz_fonte_primaria("sei", "SEI-270131/000548/2023 doc 67890")
OB_C = M.raiz_fonte_primaria("siafe_ob", "2024OB012345")


@pytest.fixture()
def s():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng)()
    yield sess
    sess.close()


def _item(s, cat, chave):
    return s.query(MemoriaAprendizado).filter_by(categoria=cat, chave=chave).one()


# ── independência de fonte ──────────────────────────────────────────────────────────────────────

def test_dez_repeticoes_da_mesma_fonte_nao_sobem(s):
    for _ in range(10):
        M.aprender("padrao_fraude", "frac", "fraciona compras", fonte="regra", source_root_id=SEI_A, session=s)
    it = _item(s, "padrao_fraude", "frac")
    assert it.n_observacoes == 10                       # a repetição é CONTADA…
    assert it.confianca == pytest.approx(M.CONF_INICIAL)  # …mas não reforça
    assert json.loads(it.fontes_raiz) == [SEI_A]
    assert it.estado == "corroborado"


def test_dez_repeticoes_sem_fonte_nao_sobem(s):
    for _ in range(10):
        M.aprender("padrao_fraude", "x", "texto", fonte="regra", delta_confianca=0.3, session=s)
    it = _item(s, "padrao_fraude", "x")
    assert it.confianca == pytest.approx(M.CONF_INICIAL)
    assert M.estado_efetivo(it) == "nao_confirmado"


def test_fonte_independente_sobe(s):
    M.aprender("padrao_fraude", "frac", "fraciona", fonte="regra", source_root_id=SEI_A, session=s)
    M.aprender("padrao_fraude", "frac", "fraciona", fonte="regra", source_root_id=SEI_B, session=s)
    M.aprender("padrao_fraude", "frac", "fraciona", fonte="regra", source_root_id=OB_C, session=s)
    it = _item(s, "padrao_fraude", "frac")
    assert it.confianca == pytest.approx(M.CONF_INICIAL + 0.2)
    assert len(json.loads(it.fontes_raiz)) == 3
    assert M.lembrar("padrao_fraude", session=s)[0]["n_fontes_independentes"] == 3


def test_mesmo_documento_em_grafias_diferentes_e_a_mesma_raiz():
    assert M.raiz_fonte_primaria("sei", "SEI-270131/000548/2023") == M.raiz_fonte_primaria("sei", "sei 270131 000548 2023")
    assert M.raiz_fonte_primaria("url_oficial", "https://www.tcerj.tc.br/x/") == \
        M.raiz_fonte_primaria("url_oficial", "https://www.tcerj.tc.br/x")


@pytest.mark.parametrize("url", ["https://blog.exemplo.com/noticia", "https://gov.br.exemplo.com/a"])
def test_url_fora_de_dominio_oficial_nao_e_fonte_primaria(url):
    with pytest.raises(ValueError):
        M.raiz_fonte_primaria("url_oficial", url)


def test_raiz_forjada_e_recusada(s):
    with pytest.raises(ValueError):
        M.aprender("licao", "k", "v", fonte="regra", source_root_id="sei:qualquer", session=s)


# ── saída de LLM nunca reforça ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fonte", ["hermes", "hermes_loop", "hermes_goal", "hermes_sintese", "hermes_bootstrap",
                                   "groq", "orquestrador", "auto_melhoria", "pericia_aprendizado",
                                   "pericia_aprendizado_llm"])
def test_saida_de_llm_nao_reforca(s, fonte):
    for _ in range(10):
        M.aprender("licao", "l1", "lição do modelo", fonte=fonte, delta_confianca=0.15,
                   source_root_id=SEI_A, session=s)        # o modelo "citar" a fonte não é a fonte
    it = _item(s, "licao", "l1")
    assert it.origem == "llm" and it.estado == "nao_confirmado"
    assert it.confianca == pytest.approx(M.CONF_INICIAL) and not it.fontes_raiz


def test_llm_repetindo_item_corroborado_nao_sobe(s):
    M.aprender("padrao_fraude", "p", "padrão", fonte="regra", source_root_id=SEI_A, session=s)
    M.aprender("padrao_fraude", "p", "padrão", fonte="regra", source_root_id=SEI_B, session=s)
    antes = _item(s, "padrao_fraude", "p").confianca
    for _ in range(10):
        M.aprender("padrao_fraude", "p", "padrão", fonte="hermes_loop", delta_confianca=0.2, session=s)
    assert _item(s, "padrao_fraude", "p").confianca == pytest.approx(antes)


def test_seed_do_codigo_nao_e_llm():
    assert M.origem_da_fonte("auto_melhoria_seed") == "humano"
    assert M.origem_da_fonte("fonte_nova_qualquer") == "desconhecida"   # rótulo desconhecido não vira 'regra'


def test_refletir_com_hermes_grava_hipotese_sem_reforco(s, monkeypatch):
    from compliance_agent.llm import free_llm

    async def _fake(*_a, **_k):
        return json.dumps({"licoes": [{"chave": "lic_x", "licao": "OB de fim de mês merece atenção"}]})

    monkeypatch.setattr(free_llm, "openrouter_available", lambda: True)
    monkeypatch.setattr(free_llm, "openrouter_chat_async", _fake)
    for _ in range(5):
        asyncio.run(M.refletir_com_hermes("resumo", session=s))
    it = _item(s, "licao", "lic_x")
    assert (it.origem, it.estado) == ("llm", "nao_confirmado")
    assert it.confianca == pytest.approx(M.CONF_INICIAL) and it.n_observacoes == 5


def test_pericia_aprendizado_grava_como_llm():
    """Toda chamada a `aprender` em tools/pericia_aprendizado.py declara origem='llm' (catraca de fonte)."""
    arvore = ast.parse((RAIZ / "tools/pericia_aprendizado.py").read_text(encoding="utf-8"))
    chamadas = [n for n in ast.walk(arvore) if isinstance(n, ast.Call)
                and getattr(n.func, "id", getattr(n.func, "attr", "")) == "aprender"]
    assert chamadas
    for c in chamadas:
        kw = {k.arg: k.value for k in c.keywords}
        assert isinstance(kw.get("origem"), ast.Constant) and kw["origem"].value == "llm", ast.dump(c)


def test_entidade_dita_pelo_llm_vira_observacao_nao_perfil(s):
    M.registrar_entidade("FOO LTDA", {"suspeito": True}, session=s, fonte="hermes_sintese")
    assert M.perfil_entidade("FOO LTDA", session=s) is None
    obs = _item(s, "observacao", "entidade:FOO LTDA")
    assert (obs.origem, obs.estado) == ("llm", "nao_confirmado")
    M.registrar_entidade("FOO LTDA", {"n_obs": 1}, session=s)      # regra (código) continua no perfil
    assert M.perfil_entidade("FOO LTDA", session=s)["n_obs"] == 1


# ── valor versionado, não "o mais longo" ────────────────────────────────────────────────────────

def test_llm_nao_troca_valor_de_origem_mais_forte(s):
    M.aprender("contexto_admin", "teto", "curto", fonte="humano", session=s)
    M.aprender("contexto_admin", "teto", "versão MUITO mais longa e inventada pelo modelo", fonte="hermes", session=s)
    it = _item(s, "contexto_admin", "teto")
    assert it.valor == "curto"
    hist = json.loads(it.historico)
    assert hist[-1]["adotado"] is False and hist[-1]["origem"] == "llm"


def test_valor_novo_de_regra_guarda_a_versao_anterior(s):
    M.aprender("entidade", "E", '{"a": 1, "b": 2, "c": 3}', fonte="regra", session=s)
    M.aprender("entidade", "E", '{"a": 1}', fonte="regra", session=s)   # mais CURTO e mais novo: vale
    it = _item(s, "entidade", "E")
    assert it.valor == '{"a": 1}'
    assert json.loads(it.historico)[-1]["valor"] == '{"a": 1, "b": 2, "c": 3}'


def test_historico_tem_teto(s):
    for i in range(M.MAX_VERSOES + 10):
        M.aprender("entidade", "E", f"v{i}", fonte="regra", session=s)
    assert len(json.loads(_item(s, "entidade", "E").historico)) == M.MAX_VERSOES


# ── estados: expiração e refutação ──────────────────────────────────────────────────────────────

def test_expiracao_por_idade_e_tipo(s):
    M.aprender("hipotese", "h", "hipótese velha", fonte="hermes_loop", session=s)
    M.aprender("missao", "atual", "missão", fonte="usuario", session=s)
    velho = datetime.utcnow() - timedelta(days=M.VALIDADE_DIAS["hipotese"] + 1)
    for it in s.query(MemoriaAprendizado).all():
        it.primeira_vez = it.ultima_vez = velho
    s.commit()
    M.aprender("hipotese", "h", "hipótese velha", fonte="hermes_loop", session=s)   # repetir não renova
    h = _item(s, "hipotese", "h")
    assert M.estado_efetivo(h) == "expirado" and M.confianca_efetiva(h) == 0.0
    assert M.lembrar("hipotese", session=s) == []
    assert M.lembrar("hipotese", session=s, incluir_inativos=True)[0]["estado"] == "expirado"
    assert M.lembrar("missao", chave="atual", session=s)[0]["valor"] == "missão"   # estado operacional não expira
    assert M.expirar_memoria(session=s) == 1 and _item(s, "hipotese", "h").estado == "expirado"


def test_corroboracao_renova_a_validade(s):
    M.aprender("padrao_fraude", "p", "padrão", fonte="regra", source_root_id=SEI_A, session=s)
    it = _item(s, "padrao_fraude", "p")
    it.primeira_vez = it.ultima_vez = it.confirmado_em = datetime.utcnow() - timedelta(days=400)
    s.commit()
    assert M.estado_efetivo(it) == "expirado"
    M.aprender("padrao_fraude", "p", "padrão", fonte="regra", source_root_id=SEI_B, session=s)
    assert M.estado_efetivo(_item(s, "padrao_fraude", "p")) == "corroborado"


def test_refutado_sai_da_leitura_e_llm_nao_ressuscita(s):
    M.aprender("padrao_fraude", "p", "padrão", fonte="regra", session=s)
    M.refutar("padrao_fraude", "p", OB_C, motivo="OB mostra pagamento regular", session=s)
    for _ in range(5):
        M.aprender("padrao_fraude", "p", "padrão", fonte="hermes", session=s)
    assert M.lembrar("padrao_fraude", session=s) == []
    assert _item(s, "padrao_fraude", "p").estado == "refutado"
    with pytest.raises(ValueError):
        M.refutar("padrao_fraude", "p", "achismo", session=s)


def test_confianca_efetiva_limita_item_nao_confirmado(s):
    s.add(MemoriaAprendizado(categoria="padrao_fraude", chave="inflado", valor="v", confianca=1.0,
                             fonte="hermes_loop"))                       # linha antiga inflada por repetição
    s.commit()
    r = M.lembrar("padrao_fraude", session=s)[0]
    assert r["confianca"] == 0.5 and r["confianca_registrada"] == 1.0 and r["estado"] == "nao_confirmado"
    assert M.lembrar("padrao_fraude", min_confianca=0.6, session=s) == []


def test_contexto_para_prompt_marca_estado_e_poe_llm_por_ultimo(s):
    M.aprender("licao", "l_llm", "lição do modelo", fonte="hermes", session=s)
    M.aprender("padrao_fraude", "p_ok", "padrão corroborado", fonte="regra", source_root_id=SEI_A, session=s)
    M.aprender("contexto_admin", "c", "base legal", fonte="humano", session=s)
    txt = M.contexto_para_prompt(session=s)
    linhas = txt.splitlines()
    assert "NÃO é prova" in linhas[0]
    assert "[corroborado · regra" in linhas[1]
    assert "[nao_confirmado · llm" in linhas[-1]


# ── migração (Alembic 0004): idempotente, retrocompatível, não apaga nada ──────────────────────

_DDL_ANTIGO = """CREATE TABLE memoria_aprendizado (id INTEGER PRIMARY KEY, categoria VARCHAR(40), chave VARCHAR(300),
  valor TEXT, confianca FLOAT, n_observacoes INTEGER, fonte VARCHAR(60), primeira_vez DATETIME, ultima_vez DATETIME)"""


def test_migracao_0004_marca_existentes_sem_apagar(tmp_path):
    pytest.importorskip("alembic")
    from compliance_agent.database import migrar
    db = tmp_path / "antigo.db"
    con = sqlite3.connect(db)
    con.execute(_DDL_ANTIGO)
    con.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
    con.execute("INSERT INTO alembic_version VALUES ('0003_ingestao_quarentena')")
    linhas = [("licao", "a", "lição", 1.0, 9, "hermes_loop"), ("contexto_admin", "b", "base", 0.9, 1, "humano"),
              ("empirico", "c", "dado", 0.7, 3, "empirico")]
    con.executemany("INSERT INTO memoria_aprendizado (categoria, chave, valor, confianca, n_observacoes, fonte) "
                    "VALUES (?,?,?,?,?,?)", linhas)
    con.commit()
    con.close()

    for _ in range(2):                                   # reaplicar é no-op
        assert migrar.atualizar(db)["atual"] == "0004_memoria_proveniencia"
    con = sqlite3.connect(db)
    got = con.execute("SELECT categoria, chave, valor, confianca, n_observacoes, fonte, origem, estado "
                      "FROM memoria_aprendizado ORDER BY chave").fetchall()
    # escritor em SQL cru (enxame/lex_base_empirica) segue funcionando sem as colunas novas
    con.execute("INSERT INTO memoria_aprendizado (categoria, chave, valor, confianca, n_observacoes, fonte) "
                "VALUES ('empirico','d','x',0.9,1,'empirico')")
    con.commit()
    con.close()
    assert [g[:6] for g in got] == linhas                # nada apagado, nada reescrito
    assert [(g[6], g[7]) for g in got] == [("llm", "nao_confirmado"), ("desconhecida", "nao_confirmado"),
                                           ("desconhecida", "nao_confirmado")]
    from compliance_agent.database.models import get_session
    sess = get_session(create_engine(f"sqlite:///{db}"))
    try:
        assert M.lembrar("empirico", chave="d", session=sess)[0]["estado"] == "nao_confirmado"   # NULL lido honesto
    finally:
        sess.close()
