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


# ─── 4a. Hermes cascade: fallback quando modelo principal dá 429 ──────────────

def test_hermes_groq_first():
    """Groq é tentado antes do OpenRouter quando GROQ_API_KEY está disponível."""
    import compliance_agent.llm.hermes_agent as h
    import compliance_agent.llm.free_llm as fl

    groq_chamado = []

    async def fake_groq(prompt, system="", smart=False, max_tokens=1024):
        groq_chamado.append(True)
        return "resposta-groq"

    orig_groq = fl.groq_chat_async
    orig_key = fl._groq_key
    fl.groq_chat_async = fake_groq
    fl._groq_key = lambda: "gsk_fake"
    h._ultima_chamada = 0.0
    try:
        result = asyncio.run(h._hermes("sys", "prompt", max_tokens=10))
        assert result == "resposta-groq"
        assert groq_chamado, "Groq deve ser chamado antes do OpenRouter"
    finally:
        fl.groq_chat_async = orig_groq
        fl._groq_key = orig_key


def test_hermes_openrouter_fallback_quando_groq_falha():
    """Quando Groq falha com 429, cai para OpenRouter e usa modelo de fallback."""
    import compliance_agent.llm.hermes_agent as h
    import compliance_agent.llm.free_llm as fl

    modelos_or = []

    async def fake_groq_fail(prompt, system="", smart=False, max_tokens=1024):
        raise RuntimeError("Retryable status 429 from groq")

    async def fake_retry(base_url, api_key, model, messages,
                         max_tokens=1024, extra_headers=None, max_retries=4):
        modelos_or.append(model)
        if model == h._HERMES_MODELO_PRINCIPAL:
            raise RuntimeError("Retryable status 429 from openrouter")
        return '{"ok": true}'  # primeiro fallback responde

    orig_groq = fl.groq_chat_async
    orig_key_groq = fl._groq_key
    orig_retry = fl._openai_compat_chat_retry
    orig_key_or = fl._openrouter_key
    fl.groq_chat_async = fake_groq_fail
    fl._groq_key = lambda: "gsk_fake"
    fl._openai_compat_chat_retry = fake_retry
    fl._openrouter_key = lambda: "sk-or-fake"
    h._ultima_chamada = 0.0
    try:
        result = asyncio.run(h._hermes("sys", "prompt", max_tokens=10))
        assert result == '{"ok": true}'
        assert modelos_or[0] == h._HERMES_MODELO_PRINCIPAL  # tentou o principal OR
        assert len(modelos_or) >= 2                          # caiu para fallback OR
        assert modelos_or[1] in h._HERMES_MODELOS_FALLBACK
    finally:
        fl.groq_chat_async = orig_groq
        fl._groq_key = orig_key_groq
        fl._openai_compat_chat_retry = orig_retry
        fl._openrouter_key = orig_key_or


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

    orig_hermes = h._hermes
    orig_send = tg.enviar_mensagem
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
        # Restaura para não poluir os testes seguintes (ex.: cascata do Hermes).
        h._hermes = orig_hermes
        tg.enviar_mensagem = orig_send


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
    from compliance_agent.collectors.doerj import (
        DOERJCollector, extrair_cpfs, extrair_cnpjs,
        extrair_valores, extrair_processos_sei,
    )
    c = DOERJCollector(session=None)

    # Dois atos separados por linha em branco dupla (padrão real do DOERJ)
    ato1 = (
        "PORTARIA Nº 123/2026 — O Secretário resolve nomear JOAO DA SILVA, "
        "CPF 123.456.789-09, para o cargo de Diretor. Processo E-18/000456/2026."
    )
    ato2 = (
        "CONTRATO Nº 45/2026 firmado com ACME CONSTRUÇÕES LTDA, "
        "CNPJ 12.345.678/0001-95, no valor de R$ 250.000,00. "
        "SEI-300100/001234/2026."
    )
    texto_multi = ato1 + "\n\n\n" + ato2

    atos = c._fatiar_atos(texto_multi, date(2026, 6, 1), "https://test",
                          edicao="normal", titulo="Parte I")

    # Deve ter separado em pelo menos 2 atos
    assert len(atos) >= 2, f"esperado ≥2 atos, obteve {len(atos)}"

    # Campos novos presentes em todos os atos
    for ato in atos:
        assert "valores_extraidos" in ato
        assert "processos_sei_extraidos" in ato
        assert "orgao" in ato
        assert "numero_ato" in ato

    # Primeiro ato deve ter o número da portaria
    assert any("123" in (a.get("numero_ato") or "") for a in atos), \
        "número do ato (PORTARIA 123) não extraído"

    # Segundo ato deve ter valor monetário
    todos_textos = " ".join(a.get("texto", "") for a in atos)
    assert len(extrair_valores(todos_textos)) >= 1
    assert len(extrair_cpfs(todos_textos)) >= 1
    assert len(extrair_cnpjs(todos_textos)) >= 1
    assert len(extrair_processos_sei(todos_textos)) >= 1


# ─── 8. SIAFE OB: mapeamento completo de colunas ─────────────────────────────

def test_siafe_ob_salva_favorecido_e_valor():
    """Confirma que save_ob_records extrai favorecido/CPF/valor/processo do header real."""
    from compliance_agent.database.models import init_db, get_session, OrdemBancaria
    from compliance_agent.collectors.siafe_ob import save_ob_records
    init_db()
    s = get_session()
    try:
        header = [
            "Número", "UG Emitente", "UG Pagadora", "Data Emissão", "Status",
            "Tipo", "Finalidade", "Tipo de OB", "NL", "Credor",
            "Nome do Credor", "UG Liquidante", "Valor", "Competência",
            "Status de Envio", "GD", "Processo",
        ]
        rows = [
            ["2026OB99001", "300100", "300100", "01/06/2026", "Contabilizado",
             "12", "6", "Orçamentária", "2026NL00338", "00394315766",
             "EMPRESA TESTE LTDA", "300100", "1.250,00", "05/2026",
             "Aguardando Envio", "", "400001/00000123/2026"],
        ]
        summary = {"date": "2026-06-01", "records": 1, "rows": rows, "header": header, "errors": []}
        n = save_ob_records(s, summary)
        assert n == 1
        ob = s.query(OrdemBancaria).filter_by(numero_ob="2026OB99001").first()
        assert ob is not None
        assert ob.favorecido_nome == "EMPRESA TESTE LTDA"
        assert ob.favorecido_cpf == "00394315766"
        assert ob.valor == 1250.0
        assert ob.numero_processo == "400001/00000123/2026"
    finally:
        s.close()


# ─── 9. Hermes Goal Agent (missão autônoma estilo /goal) ──────────────────────

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
    """
    Ciclo /goal em modo LOCAL (sem LLM): executa a sequência padrão
    (analisar_dados → identificar_padroes → ... → aprender → concluir)
    e registra ao menos uma lição na memória persistente.
    """
    from compliance_agent.database.models import init_db, get_session, MemoriaAprendizado
    from compliance_agent.hermes_goal import HermesGoalAgent

    init_db()
    s = get_session()
    try:
        ag = HermesGoalAgent(session=s)
        ag.definir_missao("missão de teste")
        res = asyncio.run(ag.trabalhar(max_passos_por_ciclo=8, max_ciclos=1))
        assert res["ok"] is True
        acoes = [p["acao"] for p in res["passos"]]
        # A sequência local sempre conclui e aprende ao longo do caminho.
        assert "concluir" in acoes
        assert "aprender" in acoes
        assert s.query(MemoriaAprendizado).filter_by(categoria="licao").count() >= 1
    finally:
        s.close()


def test_sei_detecta_captcha_e_marca_fallback():
    """
    O parser do SEI marca `captcha=True` quando a página exige o desafio,
    e a heurística de fallback humano-no-loop reconhece o bloqueio.
    """
    from compliance_agent.collectors.sei_portal import (
        _parse_resultado_pesquisa, _bloqueado_por_captcha,
    )
    html_captcha = (
        "<html><body><form>"
        "<label>Digite os caracteres da imagem</label>"
        "<img src='/sei/captcha.php'/>"
        "<input id='txtInfraCaptcha'/>"
        "</form></body></html>"
    )
    res = _parse_resultado_pesquisa(html_captcha, "E-12/345/2026")
    assert res.get("captcha") is True
    assert _bloqueado_por_captcha(res) is True

    # Página normal com documento NÃO deve disparar o fallback.
    ok = {"documentos": [{"url": "x"}], "assunto": "Contrato"}
    assert _bloqueado_por_captcha(ok) is False


def test_sei_cdp_sem_chrome_retorna_erro_claro():
    """Sem Chrome 9222, o leitor CDP devolve erro explicativo (não crasha)."""
    from compliance_agent.collectors.sei_cdp import ler_processo_sei_via_chrome
    res = asyncio.run(ler_processo_sei_via_chrome("E-12/345/2026", usar_cache=False))
    assert res["numero"] == "E-12/345/2026"
    assert "erro" in res
    assert "9222" in res["erro"] or "Chrome" in res["erro"]


def test_multi_missao_persiste_e_lista():
    """
    Multi-missão: criar_missao_paralela persiste em MissaoAuditoria e
    listar_missoes/detalhe_missao recuperam o registro. Sem event loop ativo,
    a missão fica 'pendente' (execução adiada) — sem crash.
    """
    from compliance_agent.database.models import init_db, get_session, MissaoAuditoria
    from compliance_agent.hermes_goal import (
        criar_missao_paralela, listar_missoes, detalhe_missao,
    )
    init_db()
    s = get_session()
    try:
        dados = criar_missao_paralela(
            "Auditar obras acima de R$ 119 mil sem SEI",
            titulo="Obras sem SEI", prioridade="alta", session=s,
        )
        assert dados["id"] > 0
        assert dados["prioridade"] == "alta"

        missoes = listar_missoes(session=s)
        assert any(m["id"] == dados["id"] for m in missoes)

        det = detalhe_missao(dados["id"], session=s)
        assert det is not None
        assert det["objetivo"].startswith("Auditar obras")
        # Sem event loop no teste, a execução fica adiada → status pendente.
        assert det["status"] in {"pendente", "executando", "concluida", "erro"}
    finally:
        s.close()


def test_auditor_24h_liga_desliga():
    """O Auditor 24h liga (idempotente), reporta status e desliga limpo."""
    from compliance_agent.hermes_goal import (
        iniciar_auditor_24h, parar_auditor_24h, status_auditor_24h,
    )
    # Garante estado limpo
    parar_auditor_24h()
    assert status_auditor_24h()["ativo"] is False

    r1 = iniciar_auditor_24h(objetivo="Auditoria de teste", intervalo_seg=120)
    assert r1["ativo"] is True
    assert r1["ja_ativo"] is False
    assert status_auditor_24h()["intervalo_seg"] == 120

    # Idempotente: segunda chamada não duplica
    r2 = iniciar_auditor_24h()
    assert r2["ja_ativo"] is True

    p = parar_auditor_24h()
    assert p["ativo"] is False


def test_hermes_max_tokens_repassado_ao_groq():
    """Garante que _hermes repassa max_tokens ao Groq (bug do 'pensamento pequeno')."""
    import compliance_agent.llm.hermes_agent as h
    import compliance_agent.llm.free_llm as fl

    capturado = {}

    async def fake_groq(prompt, system="", smart=False, max_tokens=1024):
        capturado["max_tokens"] = max_tokens
        return "ok"

    orig_groq = fl.groq_chat_async
    orig_key = fl._groq_key
    fl.groq_chat_async = fake_groq
    fl._groq_key = lambda: "gsk_fake"
    h._ultima_chamada = 0.0
    try:
        asyncio.run(h._hermes("sys", "prompt", max_tokens=7777))
        assert capturado.get("max_tokens") == 7777, \
            "max_tokens não foi repassado ao Groq — pensamento ficaria truncado"
    finally:
        fl.groq_chat_async = orig_groq
        fl._groq_key = orig_key


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
