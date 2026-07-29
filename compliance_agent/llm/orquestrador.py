"""
Orquestrador autônomo — o "cérebro" que comanda o agente 24/7.

Enquanto o scheduler roda tarefas FIXAS (coletar, analisar, relatório),
o orquestrador é a parte INTELIGENTE: uma IA gratuita (Groq/Hermes) que,
sozinha, decide o que investigar a seguir, usa as ferramentas, aprende com
o resultado e repete — sem ninguém digitar comandos.

Fluxo de cada ciclo:
  1. Escolhe o próximo alvo (OB/empresa/pessoa mais suspeita ainda não investigada)
  2. Manda o ComplianceAgent (22 ferramentas, LLM grátis) investigar a fundo
  3. Cruza com pesquisa na internet (DuckDuckGo + notícias)
  4. Salva o que aprendeu na memória persistente
  5. Se achar algo grave, alerta no Telegram na hora
  6. Respeita o limite de taxa do LLM grátis (pausa entre ciclos)

Roda dentro do loop contínuo do scheduler, em paralelo ao monitoramento.
"""

import asyncio
import logging
from datetime import date, timedelta

from rich.console import Console
from compliance_agent.reporting.intel_base import moeda

logger = logging.getLogger(__name__)

console = Console()

# Intervalo entre investigações (respeita rate limit do LLM grátis).
INTERVALO_INVESTIGACAO = 600   # 10 min entre alvos
PAUSA_SEM_ALVOS        = 1800  # 30 min se não houver nada novo


# ─── Disponibilidade do LLM grátis ────────────────────────────────────────────

def _llm_disponivel() -> bool:
    import os
    return bool(
        os.environ.get("GROQ_API_KEY", "").strip()
        or os.environ.get("OPENROUTER_API_KEY", "").strip()
    )


# ─── Escolha do próximo alvo ──────────────────────────────────────────────────

async def escolher_proximo_alvo(session) -> dict | None:
    """
    Decide o que investigar a seguir. Prioriza:
      1. OBs de alto valor ainda não investigadas
      2. Favorecidos que apareceram em alertas mas sem dossiê completo
      3. Empresas com flags parciais (CNPJ suspeito, sem PNCP, etc.)

    Retorna {tipo, nome, cnpj, motivo, ob} ou None se nada novo.
    """
    from compliance_agent.database.models import OrdemBancaria, Alerta
    from compliance_agent.llm.memoria import perfil_entidade

    # 1. OBs de alto valor recentes (últimos 7 dias) ainda não investigadas
    limite = date.today() - timedelta(days=7)
    obs = (
        session.query(OrdemBancaria)
        .filter(
            OrdemBancaria.data_emissao >= limite,
            OrdemBancaria.favorecido_nome.isnot(None),
            OrdemBancaria.valor.isnot(None),
        )
        .order_by(OrdemBancaria.valor.desc())
        .limit(40)
        .all()
    )
    for ob in obs:
        nome = (ob.favorecido_nome or "").strip()
        if not nome:
            continue
        perfil = perfil_entidade(nome, session=session)
        # Já investigado a fundo? (tem dossiê web) então pula
        if perfil and perfil.get("investigado_orquestrador"):
            continue
        cnpj = "".join(c for c in str(ob.favorecido_cpf or "") if c.isdigit())
        return {
            "tipo": "ob_alto_valor",
            "nome": nome,
            "cnpj": cnpj if len(cnpj) == 14 else "",
            "motivo": f"OB {ob.numero_ob} de R$ {moeda(ob.valor)} em {ob.data_emissao}",
            "ob_id": ob.id,
            "ob_numero": ob.numero_ob,
        }

    # 2. Favorecidos citados em alertas de alta severidade sem dossiê
    alertas = (
        session.query(Alerta)
        .filter(Alerta.severidade == "alta")
        .order_by(Alerta.created_at.desc())
        .limit(20)
        .all()
    )
    for a in alertas:
        # tenta achar um favorecido na OB ligada ao alerta
        if a.ordem_bancaria_id:
            ob = session.query(OrdemBancaria).get(a.ordem_bancaria_id)
            if ob and ob.favorecido_nome:
                perfil = perfil_entidade(ob.favorecido_nome, session=session)
                if not (perfil and perfil.get("investigado_orquestrador")):
                    cnpj = "".join(c for c in str(ob.favorecido_cpf or "") if c.isdigit())
                    return {
                        "tipo": "alerta_alto",
                        "nome": ob.favorecido_nome.strip(),
                        "cnpj": cnpj if len(cnpj) == 14 else "",
                        "motivo": f"Citado no alerta: {a.titulo[:80]}",
                        "ob_id": ob.id,
                        "ob_numero": ob.numero_ob,
                    }
    return None


# ─── Investigação profunda de um alvo ─────────────────────────────────────────

def _tarefa_template(nome: str, cnpj: str, motivo: str) -> str:
    """Monta o prompt de investigação com contexto jurídico injetado."""
    base = (
        "Investigue de forma autônoma o favorecido de recurso público abaixo e "
        "conclua se há risco de irregularidade. Use suas ferramentas: consulte o "
        "CNPJ, busque contratos, doações eleitorais, decisões do TCE, processos SEI, "
        "conexões na rede e múltiplos empregos. Seja objetivo.\n\n"
        f"ALVO: {nome}\n"
        f"CNPJ/CPF: {cnpj}\n"
        f"MOTIVO DA INVESTIGAÇÃO: {motivo}\n\n"
    )
    try:
        from compliance_agent.knowledge.base_legal import contexto_legal_para_prompt
        from compliance_agent.knowledge.jurisprudencia import contexto_jurisprudencial_para_prompt
        base += contexto_legal_para_prompt() + "\n\n"
        base += contexto_jurisprudencial_para_prompt() + "\n\n"
    except Exception as exc:
        logger.warning("base legal/jurisprudência indisponível no prompt de investigação: %s", exc)
    base += (
        "Ao final, responda em 1 parágrafo: há indícios de irregularidade? Quais? "
        "Que nível de risco (baixo/médio/alto)? Cite os dispositivos legais e acórdãos aplicáveis."
    )
    return base


async def investigar_alvo(alvo: dict, session) -> dict:
    """
    Investiga um alvo a fundo: agente com ferramentas + pesquisa web.
    Salva o resultado na memória e alerta se for grave.
    """
    from compliance_agent.llm.memoria import registrar_entidade, aprender
    from compliance_agent.collectors.web_research import investigar as investigar_web

    nome = alvo["nome"]
    resultado = {"alvo": nome, "conclusao_agente": "", "dossie_web": None, "risco": "baixo"}

    # 1. Agente com ferramentas (LLM grátis decide quais usar)
    try:
        from compliance_agent.agent import ComplianceAgent
        agente = ComplianceAgent()
        tarefa = _tarefa_template(
            nome=nome,
            cnpj=alvo.get("cnpj") or "não informado",
            motivo=alvo.get("motivo", ""),
        )
        agente._conversation = []  # zera contexto para não acumular
        conclusao = await agente.chat(tarefa)
        resultado["conclusao_agente"] = conclusao or ""
        try:
            agente._session.close()
        except Exception as exc:
            logger.debug("falha ao fechar sessão do ComplianceAgent: %s", exc)
    except Exception as e:
        resultado["conclusao_agente"] = f"(agente indisponível: {e})"

    # 2. Pesquisa na internet
    try:
        dossie = await investigar_web(nome, alvo.get("cnpj", ""))
        resultado["dossie_web"] = {
            "riscos": dossie.get("riscos_detectados", []),
            "resumo": dossie.get("resumo", ""),
        }
    except Exception as e:
        resultado["dossie_web"] = {"erro": str(e)}

    # 3. Determina nível de risco
    riscos_web = (resultado.get("dossie_web") or {}).get("riscos", [])
    veredito = _classificar_risco(resultado["conclusao_agente"], riscos_web)
    resultado["risco"] = veredito["risco"]
    resultado["risco_fonte"] = veredito["fonte"]
    resultado["risco_citacao"] = veredito.get("citacao", "")

    # 4. Salva na memória (aprende)
    try:
        registrar_entidade(nome, {
            "investigado_orquestrador": True,
            "risco": resultado["risco"],
            "riscos_web": riscos_web,
            "investigado_em": [date.today().isoformat()],
        }, session=session)
        aprender("entidade_investigada", nome,
                 resultado["conclusao_agente"][:500] or "investigado",
                 fonte="orquestrador", session=session)
    except Exception as exc:
        logger.warning("falha ao salvar investigação de '%s' na memória: %s", nome, exc)

    # 5. Alerta se grave
    if resultado["risco"] == "alto":
        await _alertar_investigacao(alvo, resultado, session)

    return resultado


_ESCALA_RISCO = ("baixo", "médio", "alto")

_SYS_RISCO = (
    "Você é AUDITOR DE CONTROLE EXTERNO classificando o RISCO de uma entidade a partir da "
    "conclusão de uma investigação preliminar. Regras ABSOLUTAS: (1) indício ≠ acusação — "
    "presunção de legitimidade; (2) classifique APENAS o que o texto AFIRMA: texto que NEGA "
    "irregularidade ('não há indício de fraude') é risco BAIXO, jamais alto; (3) toda "
    "classificação diferente de 'baixo' DEVE vir com o TRECHO LITERAL do texto que a sustenta — "
    "sem trecho, responda 'baixo'; (4) não invente fato que não esteja no texto. "
    'Responda SOMENTE um objeto JSON: {"risco":"baixo|médio|alto",'
    '"citacao":"trecho LITERAL copiado do texto","justificativa":"1 frase"}'
)


_GERAR_PADRAO = object()  # sentinela: resolver a cascata de produção. `gerar=None` = sem LLM.


def _classificar_risco(conclusao: str, riscos_web: list | None, *, gerar=_GERAR_PADRAO) -> dict:
    """Classifica o risco de uma investigação autônoma. NUNCA por substring.

    A versão anterior fazia `"fraude" in texto` sobre a conclusão do agente concatenada ao dossiê
    web. Como a forma mais comum de a palavra aparecer num parecer honesto é a NEGAÇÃO, um texto
    concluindo "não há indício de fraude" virava risco ALTO — `Alerta` de severidade alta no banco
    e mensagem no Telegram. "alto" era pior: casava dentro de "Planalto", "altos", "alterado".

    Hierarquia nova:

    1. **Sinal estruturado** (`riscos_web`, que o coletor já devolve como lista de achados) decide
       sozinho — é dado, não prosa.
    2. **Texto livre** só é julgado por rubrica fechada, com escala nomeada e citação literal
       CONFERIDA contra o próprio texto (o trecho tem de existir na fonte, no molde de
       `editais/motivo_inabilitacao`). Sem citação ancorada, o juízo é descartado.
    3. **Sem LLM ou resposta inválida** ⇒ ``indeterminado`` — nunca ``baixo``. Ausência de juízo
       não é declaração de regularidade (INDISPONÍVEL ≠ 0).

    `gerar` é injetável para teste; em produção usa a cascata free (Gemini primeiro).
    """
    from compliance_agent.llm.json_resposta import parse_json_llm

    if riscos_web:
        return {"risco": "alto", "fonte": "estruturado", "riscos_web": list(riscos_web),
                "citacao": "", "justificativa": "achado estruturado da pesquisa web"}

    texto = (conclusao or "").strip()
    if not texto:
        return {"risco": "indeterminado", "fonte": "indisponivel", "citacao": "",
                "justificativa": "sem conclusão do agente"}

    if gerar is _GERAR_PADRAO:
        try:
            from compliance_agent.direcionamento_cerebro import gerar_sync as gerar
        except ImportError:  # sem a camada de LLM o veredito é indeterminado, não baixo
            gerar = None
    if gerar is None:
        return {"risco": "indeterminado", "fonte": "indisponivel", "citacao": "",
                "justificativa": "camada de juízo indisponível"}

    try:
        bruto = gerar(f"TEXTO A CLASSIFICAR:\n{texto[:4000]}\n\nResponda só o JSON.", _SYS_RISCO)
    except Exception as exc:  # noqa: BLE001
        logger.warning("classificação de risco indisponível: %s", exc)
        return {"risco": "indeterminado", "fonte": "indisponivel", "citacao": "",
                "justificativa": f"provedor indisponível: {exc}"}

    j = parse_json_llm(bruto) or {}
    risco = str(j.get("risco") or "").strip().lower()
    citacao = str(j.get("citacao") or "").strip()
    if risco not in _ESCALA_RISCO:
        return {"risco": "indeterminado", "fonte": "rubrica_invalida", "citacao": citacao,
                "justificativa": f"nível fora da escala: {risco!r}"}
    if risco == "baixo":
        return {"risco": "baixo", "fonte": "rubrica_llm", "citacao": citacao,
                "justificativa": str(j.get("justificativa") or "")}
    # Acima de 'baixo' a citação é obrigatória E precisa existir mesmo no texto.
    if not citacao or citacao[:40].lower() not in texto.lower():
        return {"risco": "indeterminado", "fonte": "citacao_nao_ancorada", "citacao": citacao,
                "justificativa": "trecho citado não localizado no texto de origem"}
    return {"risco": risco, "fonte": "rubrica_llm", "citacao": citacao,
            "justificativa": str(j.get("justificativa") or "")}


async def _alertar_investigacao(alvo: dict, resultado: dict, session):
    """Cria alerta no banco e avisa no Telegram quando a investigação acha risco."""
    from compliance_agent.database.models import Alerta
    from compliance_agent.notifications.telegram import enviar_mensagem

    nome = alvo["nome"]
    titulo = f"[AUTÔNOMO] Investigação encontrou risco — {nome}"[:300]
    existe = session.query(Alerta).filter_by(titulo=titulo).first()
    riscos = (resultado.get("dossie_web") or {}).get("riscos", [])
    desc = (
        f"O agente investigou '{nome}' por iniciativa própria ({alvo.get('motivo','')}). "
        f"Risco: {resultado['risco'].upper()}. "
        f"Termos de risco na web: {', '.join(riscos) or 'nenhum'}. "
        f"Conclusão: {resultado['conclusao_agente'][:400]}"
    )
    if not existe:
        session.add(Alerta(
            tipo="investigacao_autonoma",
            severidade="alta",
            titulo=titulo,
            descricao=desc,
            data_referencia=date.today(),
            ordem_bancaria_id=alvo.get("ob_id"),
        ))
        session.commit()

    try:
        await enviar_mensagem(
            f"🕵️ *Investigação autônoma — risco ALTO*\n\n"
            f"*{nome}*\n"
            f"{alvo.get('motivo','')}\n\n"
            f"Termos de risco: {', '.join(riscos) or '—'}\n"
            f"_{resultado['conclusao_agente'][:300]}_"
        )
    except Exception as exc:
        logger.warning("falha ao enviar alerta Telegram da investigação de '%s': %s", nome, exc)


# ─── Loop autônomo 24/7 ───────────────────────────────────────────────────────

async def loop_investigador_autonomo():
    """
    O diretor autônomo. Roda para sempre, investigando um alvo por vez,
    aprendendo e respeitando o limite de taxa do LLM grátis.
    """
    from compliance_agent.database.models import get_session, init_db

    if not _llm_disponivel():
        console.print("[yellow]Orquestrador: sem GROQ_API_KEY/OPENROUTER — investigação autônoma desligada.[/yellow]")
        return

    console.print("[green]🧠 Orquestrador autônomo ativo — investigando sozinho 24/7.[/green]")
    init_db()

    while True:
        try:
            session = get_session()
            try:
                # Pede ao Hermes para recomendar o alvo mais urgente
                candidatos_raw = []
                for _ in range(1):  # coleta candidatos sem escolher
                    c = await escolher_proximo_alvo(session)
                    if c:
                        candidatos_raw.append(c)

                if not candidatos_raw:
                    console.print("[dim]Orquestrador: nada novo para investigar agora.[/dim]")
                    await asyncio.sleep(PAUSA_SEM_ALVOS)
                    continue

                # Hermes orienta qual priorizar (se disponível)
                alvo = candidatos_raw[0]
                try:
                    from compliance_agent.llm.hermes_agent import recomendar_proximo_alvo
                    recomendado = await recomendar_proximo_alvo(candidatos_raw, session)
                    if recomendado:
                        console.print(f"[dim]Hermes recomendou: {recomendado[:60]}[/dim]")
                        for c in candidatos_raw:
                            if recomendado.lower() in (c.get("nome") or "").lower():
                                alvo = c
                                break
                except Exception as exc:
                    logger.debug("Hermes indisponível para recomendar alvo, usando 1º candidato: %s", exc)

                if not alvo:
                    console.print("[dim]Orquestrador: nada novo para investigar agora.[/dim]")
                    await asyncio.sleep(PAUSA_SEM_ALVOS)
                    continue

                console.print(f"[cyan]🔍 Investigando: {alvo['nome']} ({alvo['motivo']})[/cyan]")
                resultado = await investigar_alvo(alvo, session)
                console.print(f"   → risco: {resultado['risco']}")
            finally:
                session.close()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            console.print(f"[yellow]Orquestrador: erro no ciclo: {e}[/yellow]")

        await asyncio.sleep(INTERVALO_INVESTIGACAO)
