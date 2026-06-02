"""
Suíte de testes OFFLINE do JFN — roda sem internet e sem Chrome.

Valida toda a lógica que não depende de rede:
  - carregamento de credenciais (.env / .env.txt)
  - resolução dinâmica de chaves + retry no free_llm
  - memória persistente (aprender / lembrar / perfil de entidade)
  - bootstrap do Hermes (com LLM simulado) salvando padrões/hipóteses
  - análise automática de OB + fundamentação jurídica
  - base legal e jurisprudência
  - reconhecimento de links do DOERJ contra a estrutura real
  - fatiador de atos do DOERJ

Como rodar:
    python -m pytest tests/test_offline.py -v
ou, sem pytest instalado:
    python tests/test_offline.py
"""

import asyncio
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path (rodando standalone ou via pytest).
_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

# Banco temporário isolado para todos os testes deste módulo.
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mktemp(suffix='.db')}")


# ─── 1. Carregador de credenciais ────────────────────────────────────────────

def test_envfile_carrega_env():
    from compliance_agent.envfile import carregar_env
    lidos = carregar_env()
    # Deve carregar pelo menos um arquivo (.env ou .env.txt) no ambiente de dev.
    assert isinstance(lidos, list)


# ─── 2. free_llm: chave dinâmica + retry ──────────────────────────────────────

def test_free_llm_chave_dinamica():
    os.environ.pop("GROQ_API_KEY", None)
    import compliance_agent.llm.free_llm as f
    assert f.groq_available() is False
    os.environ["GROQ_API_KEY"] = "gsk_teste"
    assert f.groq_available() is True
    os.environ.pop("GROQ_API_KEY", None)


def test_free_llm_groq_tem_retry():
    import compliance_agent.llm.free_llm as f
    assert "_retry" in inspect.getsource(f.groq_chat_async)
    assert "_retry" in inspect.getsource(f.openrouter_chat_async)


# ─── 3. Memória persistente ───────────────────────────────────────────────────

def test_memoria_aprender_e_reforcar():
    from compliance_agent.database.models import init_db, get_session
    from compliance_agent.llm import memoria as mem
    init_db()
    s = get_session()
    try:
        mem.aprender("padrao_fraude", "frac_x", "Empresa X fraciona", session=s)
        primeiro = mem.lembrar("padrao_fraude", chave="frac_x", session=s)[0]["n_observacoes"]
        mem.aprender("padrao_fraude", "frac_x", "Empresa X fraciona", session=s)
        segundo = mem.lembrar("padrao_fraude", chave="frac_x", session=s)[0]["n_observacoes"]
        assert segundo == primeiro + 1
    finally:
        s.close()


def test_memoria_perfil_entidade():
    from compliance_agent.database.models import init_db, get_session
    from compliance_agent.llm import memoria as mem
    init_db()
    s = get_session()
    try:
        mem.registrar_entidade("FOO LTDA", {"suspeito": True, "total": 1000}, session=s)
        p = mem.perfil_entidade("FOO LTDA", session=s)
        assert p and p.get("suspeito") is True
    finally:
        s.close()


# ─── 4. Bootstrap do Hermes (LLM simulado) ────────────────────────────────────

def test_hermes_bootstrap_salva_hipoteses():
    from compliance_agent.database.models import init_db, get_session, MemoriaAprendizado
    import compliance_agent.llm.hermes_agent as h
    import compliance_agent.notifications.telegram as tg

    canned = json.dumps({
        "padroes_prioritarios": [{"tipo": "fracionamento", "sinais": ["a", "b"], "lei_aplicavel": "Lei 14.133"}],
        "regras_numericas_rj": [{"regra": "Dispensa <= R$ 57.208", "alerta_se": "soma > 57208"}],
        "hipoteses_iniciais": [{"chave": "hip1", "hipotese": "Fornecedores recorrentes fracionam"}],
        "mensagem_telegram": "Hermes ativo.",
    })

    async def fake_hermes(system, prompt, max_tokens=1500):
        return canned

    async def fake_send(*a, **k):
        return {"ok": True}

    h._hermes = fake_hermes
    tg.enviar_mensagem = fake_send

    init_db()
    s = get_session()
    try:
        asyncio.run(h._bootstrap_hermes(s))
        assert s.query(MemoriaAprendizado).filter_by(categoria="hipotese").count() >= 1
        assert s.query(MemoriaAprendizado).filter_by(categoria="padrao_fraude").count() >= 1
    finally:
        s.close()


# ─── 5. Análise automática de OB + fundamentação ──────────────────────────────

def test_analise_ob_gera_alertas_com_fundamentacao():
    from datetime import date
    from compliance_agent.database.models import init_db, get_session, OrdemBancaria, Alerta
    from compliance_agent.scheduler import _analisar_ob_rapida
    init_db()
    s = get_session()
    try:
        ob = OrdemBancaria(
            numero_ob="2026OBTEST", data_emissao=date.today(),
            favorecido_nome="TESTE LTDA", favorecido_cpf="",
            valor=80000.0, numero_processo=None, ug_codigo="300100",
        )
        s.add(ob); s.commit()
        alertas = asyncio.run(_analisar_ob_rapida(ob, s))
        tipos = {a["tipo"] for a in alertas}
        assert "sem_processo" in tipos
        assert "valor_suspeito" in tipos
        salvos = s.query(Alerta).filter_by(ordem_bancaria_id=ob.id).all()
        assert all(
            ("Lei" in (a.descricao or "")) or ("Acórdão" in (a.descricao or ""))
            for a in salvos
        )
    finally:
        s.close()


# ─── 6. Base legal e jurisprudência ───────────────────────────────────────────

def test_base_legal_e_jurisprudencia():
    from compliance_agent.knowledge.base_legal import contexto_legal_para_prompt, fundamentacao_texto
    from compliance_agent.knowledge.jurisprudencia import (
        contexto_jurisprudencial_para_prompt, fundamentacao_jurisprudencial, buscar_acordaos,
    )
    assert len(contexto_legal_para_prompt()) > 100
    assert len(contexto_jurisprudencial_para_prompt()) > 100
    assert len(fundamentacao_texto("fracionamento", "x")) > 50
    assert len(fundamentacao_jurisprudencial("fracionamento", "x")) > 50
    assert len(buscar_acordaos("fracionamento")) >= 1


# ─── 7. DOERJ: reconhecimento de links e fatiador de atos ─────────────────────

def test_doerj_reconhece_links_reais():
    from compliance_agent.collectors.doerj import DOERJCollector
    c = DOERJCollector(session=None)
    # Links reais capturados da página de edição do IOERJ.
    links = [
        {"text": "Parte I (Poder Executivo)", "href": "mostra_edicao.php?session=ABC"},
        {"text": "Login", "href": "http://www.ioerj.com.br/portal/modules/profile/user.php"},
        {"text": "Portal", "href": "https://portal.ioerj.com.br"},
    ]
    edicoes = c._filtrar_links_edicao(links)
    hrefs = [e["href"] for e in edicoes]
    assert any("mostra_edicao.php" in h for h in hrefs), "link de edição real não reconhecido"
    assert not any("user.php" in h for h in hrefs), "link de login deveria ser descartado"


def test_doerj_fatiador_de_atos():
    from datetime import date
    from compliance_agent.collectors.doerj import DOERJCollector, extrair_cpfs, extrair_cnpjs
    c = DOERJCollector(session=None)
    texto = (
        "PORTARIA Nº 123 - O Secretário resolve nomear JOAO DA SILVA, CPF 123.456.789-09, "
        "para o cargo. CONTRATO Nº 45/2026 firmado com ACME LTDA, CNPJ 12.345.678/0001-95, "
        "no valor de R$ 250.000,00. Processo SEI-123456/2026."
    )
    atos = c._fatiar_atos(texto, date(2026, 6, 1), "https://test", edicao="normal", titulo="Parte I")
    assert len(atos) >= 1
    assert len(extrair_cpfs(texto)) == 1
    assert len(extrair_cnpjs(texto)) == 1


# ─── 8. Hermes Goal Agent (missão autônoma estilo /goal) ──────────────────────

def test_goal_agent_missao_persistente():
    from compliance_agent.database.models import init_db, get_session
    from compliance_agent.hermes_goal import HermesGoalAgent
    init_db()
    s = get_session()
    try:
        ag = HermesGoalAgent(session=s)
        ag.definir_missao("Auditar OBs altas de hoje")
        assert ag.missao_atual() == "Auditar OBs altas de hoje"
        ag.limpar_missao()
        assert ag.missao_atual() == ""
    finally:
        s.close()


def test_goal_agent_ciclo_autonomo():
    from compliance_agent.database.models import init_db, get_session, MemoriaAprendizado
    from compliance_agent.hermes_goal import HermesGoalAgent
    import compliance_agent.llm.hermes_agent as ha

    plano = [
        {"pensamento": "ver alertas", "acao": "listar_alertas", "args": {}},
        {"pensamento": "aprender", "acao": "aprender", "args": {"chave": "k", "licao": "lição teste"}},
        {"pensamento": "fim", "acao": "concluir", "resumo": "ok"},
    ]
    estado = {"i": 0}

    async def fake_hermes(system, prompt, max_tokens=600):
        d = plano[min(estado["i"], len(plano) - 1)]
        estado["i"] += 1
        return json.dumps(d)

    ha._hermes = fake_hermes
    init_db()
    s = get_session()
    try:
        ag = HermesGoalAgent(session=s)
        ag.definir_missao("missão de teste")
        res = asyncio.run(ag.trabalhar(max_passos=5))
        acoes = [p["acao"] for p in res["passos"]]
        assert "listar_alertas" in acoes
        assert "concluir" in acoes
        assert s.query(MemoriaAprendizado).filter_by(categoria="licao").count() >= 1
    finally:
        s.close()


# ─── Runner standalone (sem pytest) ───────────────────────────────────────────

if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for t in testes:
        try:
            t()
            print(f"  [OK] {t.__name__}")
            ok += 1
        except Exception as e:
            print(f"  [FALHOU] {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(testes)} testes passaram.")
    raise SystemExit(0 if ok == len(testes) else 1)
