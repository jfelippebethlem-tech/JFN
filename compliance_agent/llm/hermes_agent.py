"""
Hermes-3 405B — o "cérebro sênior" do JFN Compliance Agent.

Papel do Hermes (diferente do Groq):
  • Groq (llama-3.3-70b) → rápido, analisa OBs individuais em lote
  • Hermes (405B)        → sábio, aprende PADRÕES ao longo do tempo,
    sintetiza conexões entre casos, responde perguntas complexas do Jorge

O Hermes roda em paralelo, continuamente, como um parceiro sênior que:
  1. Lê tudo que o agente encontrou (alertas, OBs, investigações)
  2. Conecta pontos entre achados de dias/semanas diferentes
  3. Gera hipóteses sobre redes de corrupção e esquemas
  4. Aprende padrões específicos do Estado do RJ
  5. Responde perguntas complexas do Jorge com raciocínio profundo
  6. Orienta o orquestrador sobre quais alvos investigar primeiro

Taxa de uso: 1 ciclo a cada 30 min — respeita limite gratuito do OpenRouter.
"""

import logging
import asyncio
import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional

from rich.console import Console

console = Console()

# Intervalo entre ciclos de aprendizado do Hermes
INTERVALO_APRENDIZADO = 1800     # 30 min entre ciclos
INTERVALO_SEM_NOVIDADES = 3600   # 1h se não houver alertas novos
_RATE_LIMIT_SECS = 20            # min entre chamadas ao OpenRouter


# ─── Memória de curto prazo do Hermes ─────────────────────────────────────────
# Evita processar o mesmo alerta duas vezes
_alertas_processados: set[int] = set()
_ultima_chamada: float = 0.0

# Modelos OpenRouter — APENAS :free (regra do dono, anti-cobrança). São último
# recurso atrás de Groq/Cerebras/Gemini; o OpenRouter free anda rate-limited,
# por isso vem por último. Atualizado 2026-07-04.
#
# Uncensored PRIMEIRO (steerable, sem alinhamento pesado — pedido do dono):
#   1. Hermes-3 405B  — o próprio "Hermes", 131k ctx, o mais capaz.
#   2. Dolphin/Venice 24B — uncensored clássico, 32k ctx.
# ATENÇÃO: ambos rodam no provider Venice e COMPARTILHAM o teto :free (429 juntos).
# Por isso mantemos llama-3.3-70b + deepseek como rede NÃO-Venice quando os dois
# uncensored estiverem rate-limited — assim a cascata sempre devolve algo.
_HERMES_MODELO_PRINCIPAL = "nousresearch/hermes-3-llama-3.1-405b:free"
_HERMES_MODELOS_FALLBACK = [
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-r1:free",
    "mistralai/mistral-7b-instruct:free",
]


# Teto de tokens para o "pensamento" do Hermes. O auditor precisa raciocinar
# longamente — não truncar. Configurável por env (HERMES_MAX_TOKENS).
HERMES_MAX_TOKENS = int(os.environ.get("HERMES_MAX_TOKENS", "8000"))


logger = logging.getLogger(__name__)


async def _hermes(system: str, prompt: str, max_tokens: int = HERMES_MAX_TOKENS) -> str:
    """
    Cascata de LLMs em ordem de confiabilidade:
      1. Groq llama-3.3-70b   — 100 req/min grátis, chave no .env
      2. Cerebras / 2c. Gemini — rede de segurança JFN (CLAUDE.md)
      3. OpenRouter :free (inclui Qwen) — fallback final (regra do dono)

    (Qwen-primeiro foi REMOVIDO: dependia de chave OpenRouter ausente no JFN →
    1ª tentativa sempre falhava e gastava ciclo. Qwen :free segue alcançável no
    passo 3.)

    max_tokens é repassado a TODOS os provedores — antes o Groq (caminho
    primário) ignorava o limite e truncava em 1024 tokens, encolhendo o
    "pensamento" do Hermes.
    """
    global _ultima_chamada
    import time

    elapsed = time.time() - _ultima_chamada
    if elapsed < _RATE_LIMIT_SECS:
        await asyncio.sleep(_RATE_LIMIT_SECS - elapsed)

    from compliance_agent.llm.free_llm import (
        _openai_compat_chat_retry,
        _openrouter_key,
        OPENROUTER_BASE,
        OPENROUTER_HEADERS,
        groq_available,
        groq_chat_async,
    )

    key = _openrouter_key()

    async def _tentar_openrouter_uncensored():
        """Cascata OpenRouter :free uncensored. Retorna texto, ou None (sem chave / todos 429)."""
        if not key:
            return None
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        for model in [_HERMES_MODELO_PRINCIPAL] + _HERMES_MODELOS_FALLBACK:
            try:
                from compliance_agent.llm.free_llm import _forcar_free
                out = await _openai_compat_chat_retry(
                    OPENROUTER_BASE, key, _forcar_free(model), messages,
                    max_tokens=max_tokens, extra_headers=OPENROUTER_HEADERS, max_retries=1)
                if model != _HERMES_MODELO_PRINCIPAL:
                    console.print(f"[dim]Hermes: usando {model.split('/')[-1]} (fallback uncensored)[/dim]")
                return out
            except Exception:
                await asyncio.sleep(2)
        return None

    # ── 0. Uncensored :free PRIMEIRO (pedido do dono: "uncensored sempre"). Se todos
    #      rate-limitarem (429), cai p/ Groq/Cerebras. Desligável: HERMES_UNCENSORED_FIRST=0.
    if os.environ.get("HERMES_UNCENSORED_FIRST", "1") != "0":
        _unc = await _tentar_openrouter_uncensored()
        if _unc:
            _ultima_chamada = time.time()
            return _unc

    # ── 1. Groq (fallback rápido quando o uncensored :free rate-limita) ──────────
    if groq_available():
        try:
            resultado = await groq_chat_async(prompt, system=system, smart=True,
                                              max_tokens=max_tokens)
            _ultima_chamada = time.time()
            return resultado
        except Exception as e:
            console.print(f"[dim]Hermes: Groq falhou ({e}), tentando Cerebras…[/dim]")

    # ── 2b. Cerebras (rede de segurança JFN: rápido e com saldo — CLAUDE.md) ─────
    try:
        from compliance_agent.llm.free_llm import cerebras_available, cerebras_chat_async
        if cerebras_available():
            resultado = await cerebras_chat_async(prompt, system=system, smart=True,
                                                  max_tokens=max_tokens)
            _ultima_chamada = time.time()
            return resultado
    except Exception as e:
        console.print(f"[dim]Hermes: Cerebras falhou ({e}), tentando Gemini…[/dim]")

    # ── 2c. Gemini (qualidade, free-tier) ───────────────────────────────────────
    try:
        from compliance_agent.llm.free_llm import gemini_chat_async
        resultado = await gemini_chat_async(prompt, system=system, smart=True,
                                            max_tokens=max_tokens)
        _ultima_chamada = time.time()
        return resultado
    except Exception as e:
        console.print(f"[dim]Hermes: Gemini falhou ({e}), tentando OpenRouter :free…[/dim]")

    # ── 3. OpenRouter uncensored :free — retry final (se o passo 0 rate-limitou e
    #      Groq/Cerebras/Gemini também caíram) ────────────────────────────────────
    _unc = await _tentar_openrouter_uncensored()
    if _unc:
        _ultima_chamada = time.time()
        return _unc

    raise RuntimeError(
        "Hermes indisponível: Groq, Cerebras, Gemini e todos os modelos OpenRouter :free "
        "(incl. Qwen) falharam. Verifique chaves/roteamento no código."
    )


# ─── 1. Aprender padrões de alertas novos ────────────────────────────────────

_SYSTEM_APRENDIZADO = (
    "Você é o Hermes, o agente de inteligência sênior do sistema JFN de auditoria "
    "do Estado do Rio de Janeiro. Você tem acesso a alertas de compliance detectados "
    "hoje e ao histórico acumulado de aprendizado.\n\n"
    "Sua função é:\n"
    "  1. Identificar PADRÕES que conectam múltiplos alertas\n"
    "  2. Formular HIPÓTESES sobre esquemas (ex: empresa X fraciona sistematicamente)\n"
    "  3. Apontar PRIORIDADES: qual alvo merece investigação mais urgente?\n"
    "  4. Extrair LIÇÕES acionáveis que o agente pode usar amanhã\n\n"
    "Responda em JSON:\n"
    "{\n"
    '  "padroes": ["padrão identificado 1", "padrão 2"],\n'
    '  "hipoteses": ["hipótese concreta 1", "hipótese 2"],\n'
    '  "prioridade_investigacao": "Nome/CNPJ mais urgente para investigar e por quê",\n'
    '  "licoes": [{"chave": "id_unico", "licao": "texto curto e acionável"}],\n'
    '  "resumo": "Avaliação geral em 2-3 frases"\n'
    "}"
)


async def aprender_com_alertas_novos(session) -> Optional[dict]:
    """
    Hermes lê todos os alertas novos (últimas 2h) e aprende com eles.
    Salva padrões, hipóteses e lições na memória persistente.
    """
    from compliance_agent.database.models import Alerta
    from compliance_agent.llm.memoria import (
        aprender, contexto_para_prompt
    )
    from sqlalchemy import desc

    # Busca alertas ainda não processados
    limite = datetime.utcnow() - timedelta(hours=2)
    alertas = (
        session.query(Alerta)
        .filter(Alerta.created_at >= limite)
        .order_by(desc(Alerta.created_at))
        .limit(30)
        .all()
    )
    novos = [a for a in alertas if a.id not in _alertas_processados]
    if not novos:
        return None

    # Monta resumo compacto
    resumo_alertas = []
    for a in novos:
        resumo_alertas.append({
            "id": a.id,
            "tipo": a.tipo,
            "severidade": a.severidade,
            "titulo": a.titulo[:150],
            "descricao": (a.descricao or "")[:300],
            "data": str(a.data_referencia),
        })

    contexto_mem = contexto_para_prompt(session, max_itens=20)

    prompt = (
        f"{contexto_mem}\n\n"
        f"NOVOS ALERTAS ({len(novos)}) detectados nas últimas 2 horas:\n"
        f"{json.dumps(resumo_alertas, ensure_ascii=False, indent=2)}\n\n"
        "Analise, identifique padrões e extraia lições."
    )

    try:
        raw = await _hermes(_SYSTEM_APRENDIZADO, prompt, max_tokens=1200)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        resultado = json.loads(m.group())

        # Salva lições na memória
        for lic in resultado.get("licoes", []):
            chave = lic.get("chave", "")[:300]
            texto = lic.get("licao", "")
            if chave and texto:
                aprender("licao", chave, texto, fonte="hermes_loop",
                         delta_confianca=0.15, session=session)

        # Salva padrões detectados
        for i, padrao in enumerate(resultado.get("padroes", [])[:5]):
            chave = f"padrao_hermes_{date.today().isoformat()}_{i}"
            aprender("padrao_fraude", chave, padrao, fonte="hermes_loop",
                     delta_confianca=0.1, session=session)

        # Salva hipóteses
        for i, hip in enumerate(resultado.get("hipoteses", [])[:3]):
            chave = f"hipotese_{date.today().isoformat()}_{i}"
            aprender("hipotese", chave, hip, fonte="hermes_loop",
                     delta_confianca=0.1, session=session)

        # Marca os alertas como processados
        for a in novos:
            _alertas_processados.add(a.id)

        return resultado

    except Exception as e:
        console.print(f"[yellow]Hermes aprendizado: {e}[/yellow]")
        return None


# ─── 2. Síntese semanal — conexões entre casos ───────────────────────────────

_SYSTEM_SINTESE = (
    "Você é o Hermes, auditor sênior do JFN. Você analisa o histórico COMPLETO "
    "de alertas da semana e busca CONEXÕES entre casos aparentemente distintos. "
    "Seu objetivo é identificar ESQUEMAS (não casos isolados) e nomear os principais "
    "suspeitos de operar irregularidades sistemáticas no Estado do RJ.\n\n"
    "Responda em JSON:\n"
    "{\n"
    '  "esquemas_identificados": [\n'
    '    {"nome": "ex: Cartel de Limpeza UG 300100",\n'
    '     "entidades": ["Empresa A", "Empresa B"],\n'
    '     "modus_operandi": "como funciona",\n'
    '     "valor_estimado": "R$ X",\n'
    '     "evidencias": ["alerta 1", "alerta 2"]}\n'
    "  ],\n"
    '  "alvos_prioritarios": ["Entidade mais suspeita → motivo"],\n'
    '  "recomendacoes": ["Ação concreta 1 para o próximo ciclo"],\n'
    '  "resumo_executivo": "3-4 frases sobre o estado geral da auditoria"\n'
    "}"
)


async def sintetizar_semana(session) -> Optional[dict]:
    """
    Síntese semanal do Hermes: conecta alertas da semana, identifica esquemas.
    Roda toda segunda-feira às 08:00 (depois do relatório).
    """
    from compliance_agent.database.models import Alerta, OrdemBancaria
    from compliance_agent.llm.memoria import (
        aprender, contexto_para_prompt, lembrar, registrar_entidade
    )
    import sqlalchemy as sa

    limite = date.today() - timedelta(days=7)

    # Alertas da semana
    alertas = (
        session.query(Alerta)
        .filter(Alerta.data_referencia >= limite)
        .order_by(Alerta.severidade, Alerta.created_at.desc())
        .limit(60)
        .all()
    )

    # Top favorecidos da semana
    top = (
        session.query(
            OrdemBancaria.favorecido_nome,
            sa.func.sum(OrdemBancaria.valor).label("total"),
            sa.func.count(OrdemBancaria.id).label("n"),
        )
        .filter(
            OrdemBancaria.data_emissao >= limite,
            OrdemBancaria.favorecido_nome.isnot(None),
        )
        .group_by(OrdemBancaria.favorecido_nome)
        .order_by(sa.desc("total"))
        .limit(20)
        .all()
    )

    hipoteses = lembrar("hipotese", min_confianca=0.0)
    contexto = contexto_para_prompt(session, max_itens=15)

    resumo_alertas = [
        {"tipo": a.tipo, "sev": a.severidade,
         "titulo": a.titulo[:100], "data": str(a.data_referencia)}
        for a in alertas
    ]
    resumo_top = [
        {"favorecido": r.favorecido_nome, "total": r.total, "obs": r.n}
        for r in top
    ]

    prompt = (
        f"{contexto}\n\n"
        f"HIPÓTESES ACUMULADAS:\n"
        + "\n".join(h["valor"][:150] for h in hipoteses[:5])
        + f"\n\nALERTAS DA SEMANA ({len(alertas)}):\n"
        + json.dumps(resumo_alertas, ensure_ascii=False)
        + "\n\nTOP FAVORECIDOS DA SEMANA:\n"
        + json.dumps(resumo_top, ensure_ascii=False)
        + "\n\nIdentifique esquemas e conexões entre os casos."
    )

    try:
        raw = await _hermes(_SYSTEM_SINTESE, prompt, max_tokens=max(4000, HERMES_MAX_TOKENS // 2))
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        resultado = json.loads(m.group())

        # Registra entidades suspeitas
        for esquema in resultado.get("esquemas_identificados", []):
            for ent in esquema.get("entidades", []):
                registrar_entidade(ent, {
                    "esquema": esquema.get("nome", ""),
                    "modus": esquema.get("modus_operandi", ""),
                    "suspeito": True,
                }, session=session)
            aprender(
                "esquema",
                esquema.get("nome", "esquema")[:300],
                json.dumps(esquema, ensure_ascii=False),
                fonte="hermes_sintese",
                delta_confianca=0.2,
                session=session,
            )

        return resultado

    except Exception as e:
        console.print(f"[yellow]Hermes síntese: {e}[/yellow]")
        return None


# ─── 3. Responder perguntas complexas do Jorge ───────────────────────────────

_SYSTEM_RESPOSTA = (
    "Você é o Hermes, o parceiro sênior de auditoria do Jorge no sistema JFN. "
    "Jorge é um auditor do Estado do RJ que pergunta coisas complexas. "
    "Responda em português, com rigor analítico, citando fatos concretos do banco "
    "de dados fornecido. Jamais invente dados. Se não souber, diga o que falta.\n\n"
    "Quando relevante, cite: artigos de lei, acórdãos do TCE-RJ ou TCU, "
    "e o que o sistema já aprendeu de casos anteriores.\n"
    "Responda com a PROFUNDIDADE que a auditoria exigir — não se limite a "
    "respostas curtas quando o caso pedir análise detalhada. Estruture com "
    "tópicos, fundamentação e próximos passos investigativos."
)


async def responder_hermes(pergunta: str, contexto_db: str, session) -> str:
    """
    Hermes responde a pergunta do Jorge com raciocínio profundo.
    Injeta dados do banco + memória + jurisprudência + esquemas identificados.
    """
    from compliance_agent.llm.memoria import contexto_para_prompt, lembrar
    from compliance_agent.knowledge.base_legal import contexto_legal_para_prompt
    from compliance_agent.knowledge.jurisprudencia import contexto_jurisprudencial_para_prompt

    contexto_mem = contexto_para_prompt(session, max_itens=20)
    esquemas = lembrar("esquema", session=session)
    hipoteses = lembrar("hipotese", session=session)

    try:
        base_legal = contexto_legal_para_prompt()
        jurisprudencia = contexto_jurisprudencial_para_prompt()
    except Exception:
        base_legal = jurisprudencia = ""

    bloco_esquemas = ""
    if esquemas:
        bloco_esquemas = "\nESQUEMAS IDENTIFICADOS PELO HERMES:\n" + "\n".join(
            e["valor"][:200] for e in esquemas[:3]
        )
    bloco_hipoteses = ""
    if hipoteses:
        bloco_hipoteses = "\nHIPÓTESES EM INVESTIGAÇÃO:\n" + "\n".join(
            h["valor"][:150] for h in hipoteses[:4]
        )

    # RAG — "segundo cérebro": trechos relevantes de normas (Lei 14.133, sanções, métodos
    # de fraude) + vault, recuperados por embeddings Cohere. Aditivo e à prova de falha.
    bloco_rag = ""
    try:
        from tools.hermes_rag import contexto as _rag_contexto
        rag = _rag_contexto(pergunta, k=10)  # pool largo; tiers (full+índice) cabem no mesmo teto de chars
        if rag:
            bloco_rag = "\nBASE TÉCNICA CONSULTÁVEL (RAG — normas + conhecimento acumulado):\n" + rag + "\n"
    except Exception:
        bloco_rag = ""

    prompt = (
        f"{contexto_db}\n\n"
        f"{contexto_mem}\n"
        f"{bloco_esquemas}\n"
        f"{bloco_hipoteses}\n\n"
        f"{base_legal}\n\n"
        f"{jurisprudencia}\n\n"
        f"{bloco_rag}\n"
        f"PERGUNTA DO JORGE: {pergunta}\n\n"
        "Responda com rigor analítico e dados concretos."
    )

    try:
        return await _hermes(_SYSTEM_RESPOSTA, prompt, max_tokens=HERMES_MAX_TOKENS)
    except Exception as e:
        return f"Hermes indisponível agora ({e}). Tente /status ou pergunte de forma mais simples."


# ─── 4. Orientar o orquestrador — qual alvo priorizar ────────────────────────

async def recomendar_proximo_alvo(candidatos: list[dict], session) -> Optional[str]:
    """
    Dado uma lista de candidatos a investigar, Hermes recomenda qual deve vir primeiro.
    Retorna o nome/CNPJ do alvo mais urgente ou None.
    """
    from compliance_agent.llm.memoria import lembrar

    if not candidatos:
        return None

    esquemas = lembrar("esquema", session=session)
    hipoteses = lembrar("hipotese", session=session)

    system = (
        "Você é o Hermes, diretor de investigação do JFN. Dado uma lista de candidatos "
        "a investigar e o contexto dos esquemas identificados, escolha QUAL investigar "
        "primeiro. Responda apenas com o nome/CNPJ do alvo escolhido e uma frase "
        "explicando a escolha. Formato: 'ALVO: <nome> | MOTIVO: <frase curta>'"
    )

    prompt = (
        "CANDIDATOS A INVESTIGAR:\n"
        + json.dumps(candidatos[:10], ensure_ascii=False)
        + "\n\nESQUEMAS ATIVOS:\n"
        + "\n".join(e["valor"][:150] for e in esquemas[:3])
        + "\n\nHIPÓTESES:\n"
        + "\n".join(h["valor"][:100] for h in hipoteses[:3])
        + "\n\nQual investigar primeiro?"
    )

    try:
        raw = await _hermes(system, prompt, max_tokens=200)
        m = re.search(r"ALVO:\s*(.+?)(?:\s*\||\n|$)", raw)
        return m.group(1).strip() if m else None
    except Exception:
        return None


# ─── 5. Bootstrap inicial — Hermes estuda antes de haver dados ───────────────

_SYSTEM_BOOTSTRAP = (
    "Você é o Hermes, o auditor sênior de inteligência do sistema JFN que monitora "
    "as finanças do Estado do Rio de Janeiro. Você acabou de ser ativado.\n\n"
    "Com base na legislação e jurisprudência que lhe foi fornecida, sua missão agora é:\n"
    "  1. Listar os 5 TIPOS DE IRREGULARIDADE mais comuns em estados brasileiros\n"
    "     (fracionamento, superfaturamento, nepotismo, empresa fachada, etc.)\n"
    "  2. Para cada tipo: quais SINAIS nas OBs/DOERJ indicariam esse esquema?\n"
    "  3. Quais REGRAS NUMÉRICAS específicas do RJ merecem atenção imediata?\n"
    "  4. Formule 3 HIPÓTESES INICIAIS sobre o que provavelmente encontraremos\n"
    "     quando os dados do SIAFE2 chegarem.\n\n"
    "Responda em JSON:\n"
    "{\n"
    '  "padroes_prioritarios": [\n'
    '    {"tipo": "fracionamento", "sinais": ["OBs iguais no mesmo dia", "..."], '
    '"lei_aplicavel": "Lei 14.133/2021 art. 75"}\n'
    "  ],\n"
    '  "regras_numericas_rj": [\n'
    '    {"regra": "Dispensa compras <= R$ 57.208", "alerta_se": "soma diária > R$ 57.208"}\n'
    "  ],\n"
    '  "hipoteses_iniciais": [\n'
    '    {"chave": "id_curto", "hipotese": "texto da hipótese a verificar nos dados"}\n'
    "  ],\n"
    '  "mensagem_telegram": "Mensagem curta (2-3 linhas) para o usuário saber que o Hermes está ativo e o que vai monitorar"\n'
    "}"
)


async def _bootstrap_hermes(session) -> None:
    """
    Roda UMA VEZ na inicialização: Hermes estuda a base legal + jurisprudência
    e formula hipóteses iniciais ANTES de qualquer dado chegar do SIAFE/DOERJ.
    Assim ele já está "aquecido" quando os primeiros alertas aparecerem.
    """
    from compliance_agent.llm.memoria import (
        aprender, garantir_contexto_inicial, contexto_para_prompt
    )
    from compliance_agent.notifications.telegram import enviar_mensagem

    garantir_contexto_inicial(session)
    contexto_mem = contexto_para_prompt(session, max_itens=30)

    try:
        base_legal = ""
        jurisp = ""
        try:
            from compliance_agent.knowledge.base_legal import contexto_legal_para_prompt
            base_legal = contexto_legal_para_prompt()
        except Exception as exc:
            logger.warning("base legal indisponível p/ o prompt do Hermes: %s", exc)
        try:
            from compliance_agent.knowledge.jurisprudencia import contexto_jurisprudencial_para_prompt
            jurisp = contexto_jurisprudencial_para_prompt()
        except Exception as exc:
            logger.warning("jurisprudência indisponível p/ o prompt do Hermes: %s", exc)

        prompt = (
            f"BASE LEGAL DISPONÍVEL:\n{base_legal}\n\n"
            f"JURISPRUDÊNCIA (TCE-RJ + TCU):\n{jurisp}\n\n"
            f"CONHECIMENTO ACUMULADO:\n{contexto_mem}\n\n"
            "Analise e formule hipóteses iniciais para a auditoria do Estado do RJ."
        )

        console.print("[cyan]🧠 Hermes: estudando base legal e jurisprudência...[/cyan]")
        raw = await _hermes(_SYSTEM_BOOTSTRAP, prompt, max_tokens=2000)

        import re as _re
        m = _re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            console.print("[yellow]Hermes bootstrap: resposta sem JSON válido.[/yellow]")
            return

        dados = json.loads(m.group())

        # Salva padrões prioritários na memória
        for i, p in enumerate(dados.get("padroes_prioritarios", [])[:6]):
            chave = f"bootstrap_padrao_{i}_{p.get('tipo','x')}"[:300]
            valor = (
                f"Tipo: {p.get('tipo','')} | "
                f"Sinais: {', '.join(p.get('sinais', [])[:3])} | "
                f"Lei: {p.get('lei_aplicavel','')}"
            )
            aprender("padrao_fraude", chave, valor[:400],
                     fonte="hermes_bootstrap", delta_confianca=0.15, session=session)

        # Salva regras numéricas
        for i, r in enumerate(dados.get("regras_numericas_rj", [])[:5]):
            chave = f"bootstrap_regra_{i}"
            valor = f"{r.get('regra','')} → alerta se: {r.get('alerta_se','')}"
            aprender("contexto_admin", chave, valor[:400],
                     fonte="hermes_bootstrap", delta_confianca=0.2, session=session)

        # Salva hipóteses iniciais
        for hip in dados.get("hipoteses_iniciais", [])[:4]:
            chave = hip.get("chave", "")[:300]
            texto = hip.get("hipotese", "")
            if chave and texto:
                aprender("hipotese", chave, texto[:400],
                         fonte="hermes_bootstrap", delta_confianca=0.1, session=session)

        n_padroes  = len(dados.get("padroes_prioritarios", []))
        n_regras   = len(dados.get("regras_numericas_rj", []))
        n_hipoteses = len(dados.get("hipoteses_iniciais", []))
        console.print(
            f"[green]🧠 Hermes pronto: {n_padroes} padrões + {n_regras} regras + "
            f"{n_hipoteses} hipóteses iniciais salvas.[/green]"
        )

        # Telegram: avisa que o Hermes está ativo e o que vai monitorar
        msg_base = dados.get("mensagem_telegram", "")
        msg = (
            "🧠 *Hermes-3 ativo e estudando*\n\n"
            + (f"_{msg_base}_\n\n" if msg_base else "")
            + f"Aprendi *{n_padroes}* padrões de irregularidade e formulei "
            f"*{n_hipoteses}* hipóteses para testar nos dados.\n"
            "Quando o SIAFE e DOERJ coletarem, começo a cruzar tudo."
        )
        await enviar_mensagem(msg)

    except Exception as e:
        console.print(f"[yellow]Hermes bootstrap: {e}[/yellow]")


# ─── 6. Loop contínuo do Hermes ──────────────────────────────────────────────

async def loop_hermes_continuo():
    """
    Loop paralelo do Hermes — roda para sempre, aprendendo com tudo que o sistema vê.

    Ciclo:
      - A cada 30 min: lê alertas novos → aprende padrões → salva lições
      - Toda segunda 09h: síntese semanal → identifica esquemas
      - Sempre disponível para responder via _hermes() quando o Telegram pede
    """
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.llm.free_llm import openrouter_available
    from compliance_agent.notifications.telegram import enviar_mensagem

    if not openrouter_available():
        console.print(
            "[yellow]Hermes: OPENROUTER_API_KEY não configurada — "
            "aprendizado contínuo desligado.[/yellow]"
        )
        return

    console.print(
        "[green]🧠 Hermes ativo — uncensored :free primeiro "
        "(Hermes-3 405B → Dolphin/Venice), Groq/Cerebras de fallback — "
        "aprendendo continuamente.[/green]")
    init_db()

    _sintese_feita_na_semana: set[str] = set()

    # ── Bootstrap: Hermes estuda antes dos dados chegarem ────────────────────
    _boot_session = get_session()
    try:
        await _bootstrap_hermes(_boot_session)
    except Exception as _e:
        console.print(f"[yellow]Hermes bootstrap falhou: {_e}[/yellow]")
    finally:
        _boot_session.close()

    while True:
        agora = datetime.now()
        chave_semana = f"{agora.year}-W{agora.isocalendar()[1]}"
        resultado = None

        session = get_session()
        try:
            # ── Aprendizado contínuo (todo ciclo) ─────────────────────────────
            resultado = await aprender_com_alertas_novos(session)
            if resultado:
                n_licoes = len(resultado.get("licoes", []))
                n_padroes = len(resultado.get("padroes", []))
                console.print(
                    f"[green]Hermes: {n_licoes} lições + {n_padroes} padrões aprendidos[/green]"
                )

                # Alerta se Hermes identificou algo urgente
                prioridade = resultado.get("prioridade_investigacao", "")
                if prioridade and any(
                    kw in prioridade.lower()
                    for kw in ["urgente", "imediato", "grave", "alto risco"]
                ):
                    await enviar_mensagem(
                        f"🧠 *Hermes identificou prioridade:*\n_{prioridade[:400]}_"
                    )

            # ── Síntese semanal (segunda-feira às 09h) ────────────────────────
            if agora.weekday() == 0 and agora.hour == 9 and chave_semana not in _sintese_feita_na_semana:
                console.print("[cyan]Hermes: iniciando síntese semanal...[/cyan]")
                sintese = await sintetizar_semana(session)
                if sintese:
                    _sintese_feita_na_semana.add(chave_semana)
                    n_esquemas = len(sintese.get("esquemas_identificados", []))
                    resumo = sintese.get("resumo_executivo", "")[:500]
                    alvos = sintese.get("alvos_prioritarios", [])
                    msg = (
                        f"🧠 *Síntese semanal do Hermes*\n\n"
                        f"Esquemas identificados: *{n_esquemas}*\n"
                        f"_{resumo}_\n\n"
                        + ("*Alvos prioritários:*\n" +
                           "\n".join(f"• {a[:100]}" for a in alvos[:3])
                           if alvos else "")
                    )
                    await enviar_mensagem(msg)

                # ── Auto-melhoria (meta-cognição): logo após a síntese semanal ──
                try:
                    from compliance_agent.llm.auto_melhoria import seed_metodos, auto_melhorar
                    seed_metodos(session)
                    am = await auto_melhorar(session)
                    if am.get("novas_auto_correcoes"):
                        await enviar_mensagem(
                            "🧠 *Hermes — auto-melhoria:* novas regras de método: "
                            + ", ".join(am["novas_auto_correcoes"][:5]))
                except Exception as _e:
                    console.print(f"[yellow]Hermes auto-melhoria: {_e}[/yellow]")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            console.print(f"[yellow]Hermes loop: {e}[/yellow]")
        finally:
            session.close()

        # Espera — se teve novidades fica 30min, senão 1h
        if not resultado:
            console.print(
                "[dim]Hermes vivo, mas sem alertas novos para aprender ainda — "
                "depende da coleta SIAFE/DOERJ gerar dados.[/dim]"
            )
        espera = INTERVALO_APRENDIZADO if resultado else INTERVALO_SEM_NOVIDADES
        await asyncio.sleep(espera)
