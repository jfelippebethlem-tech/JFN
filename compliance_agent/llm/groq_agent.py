"""
Groq-powered autonomous compliance agent.

Este módulo usa o Groq LLM para três coisas:

1. NAVEGAÇÃO AUTÔNOMA — em vez de seletores CSS fixos que quebram quando o
   ADF muda de layout, o LLM vê o estado real da página e decide o que fazer.
   Se uma ação falha, ele recebe o erro + nova tela e raciocina a recuperação.

2. ANÁLISE DE COMPLIANCE — lê as OBs e publicações do DOERJ coletadas e
   identifica padrões suspeitos com linguagem natural:
   "Esta OB de R$499.900 é suspeita porque fica abaixo do limite de licitação"

3. MEMÓRIA DE APRENDIZADO — salva no banco os seletores e padrões que
   funcionaram, reutiliza no próximo run, só chama o LLM quando necessário.
"""

import asyncio
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

import httpx

GROQ_API_KEY = os.environ.get(
    "GROQ_API_KEY",
    "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",
)
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama3-70b-8192")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MEMORY_FILE = Path("data/groq_memory.json")


# ─── Memória persistente ──────────────────────────────────────────────────────

def _load_memory() -> dict:
    MEMORY_FILE.parent.mkdir(exist_ok=True)
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"selectors": {}, "patterns": [], "failures": []}


def _save_memory(mem: dict):
    MEMORY_FILE.write_text(
        json.dumps(mem, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


# ─── Chamada ao Groq ──────────────────────────────────────────────────────────

async def _groq(messages: list[dict], max_tokens: int = 800, temperature: float = 0.1) -> str:
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GROQ_URL, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _parse_json(raw: str) -> dict | list | None:
    """Extrai JSON de uma resposta do LLM (ignora texto ao redor)."""
    raw = raw.strip()
    # Remove markdown code fences
    raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    # Find first { or [
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        idx = raw.find(start_char)
        if idx >= 0:
            # find matching close
            depth = 0
            for i, c in enumerate(raw[idx:], idx):
                if c == start_char:
                    depth += 1
                elif c == end_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(raw[idx:i+1])
                        except Exception:
                            break
    return None


# ─── 1. Navegação autônoma no browser ────────────────────────────────────────

_NAV_SYSTEM = """
Você é um agente especialista em navegar o SIAFE2 (sistema ADF Oracle do governo do RJ).

REGRAS CRÍTICAS:
- NUNCA use page.goto() diretamente em URLs de OB — causa crash BeanELResolver
- Para chegar na tela de OB Orçamentária: clique em a.xgg 'OB Orçamentária'
- ADF usa PPR (Partial Page Refresh) — sempre aguarde após cliques
- Seletores CSS do ADF: a.xgg (menu), a.xyp (abas), a.x12k (botões ação)

Responda APENAS com JSON válido, sem texto fora do JSON:
{
  "action": "click" | "fill" | "wait" | "read" | "done" | "error",
  "selector": "seletor CSS",
  "text": "texto exato do elemento (para click)",
  "value": "valor a preencher (para fill)",
  "read_target": "seletor do que ler (para read)",
  "reason": "por que esta ação avança a tarefa",
  "learned_selector": "seletor que funcionou (salvar na memória)",
  "task_complete": false,
  "extracted_data": {}
}
"""


async def navigate_autonomous(page, task: str, max_steps: int = 20) -> dict:
    """
    Usa o Groq para navegar autonomamente no SIAFE2.
    Aprende seletores que funcionam e os salva para reutilizar.
    """
    memory = _load_memory()
    messages = [{"role": "system", "content": _NAV_SYSTEM}]
    actions_taken = []
    extracted = {}

    for step in range(max_steps):
        # Captura estado da página
        state = await _capture_page_state(page)

        # Inclui seletores aprendidos anteriormente
        known = memory.get("selectors", {})
        known_str = json.dumps(known, ensure_ascii=False)[:500] if known else "nenhum ainda"

        user_msg = (
            f"TAREFA: {task}\n\n"
            f"ESTADO ATUAL (passo {step+1}/{max_steps}):\n"
            f"URL: {state['url']}\n"
            f"Elementos clicáveis: {json.dumps(state['elements'][:30], ensure_ascii=False)}\n"
            f"Campos de entrada: {json.dumps(state['inputs'][:15], ensure_ascii=False)}\n"
            f"Texto visível: {state['text'][:600]}\n\n"
            f"Seletores já aprendidos: {known_str}\n\n"
            "Qual é a próxima ação?"
        )
        messages.append({"role": "user", "content": user_msg})

        try:
            raw = await _groq(messages, max_tokens=500)
        except Exception as e:
            return {"success": False, "error": f"Groq API: {e}", "actions": actions_taken}

        messages.append({"role": "assistant", "content": raw})

        action = _parse_json(raw)
        if not action or not isinstance(action, dict):
            messages.append({"role": "user", "content": "JSON inválido. Tente novamente."})
            continue

        act_type = action.get("action", "")
        result = await _execute_nav_action(page, action)

        # Aprende seletores que funcionaram
        if result.get("success") and action.get("learned_selector"):
            sel_key = action.get("text", act_type)
            memory["selectors"][sel_key] = action["learned_selector"]
            _save_memory(memory)

        # Coleta dados extraídos
        if action.get("extracted_data"):
            extracted.update(action["extracted_data"])

        actions_taken.append({
            "step": step + 1,
            "action": action,
            "result": result,
        })

        if action.get("task_complete") or act_type == "done":
            return {
                "success": True,
                "steps": step + 1,
                "actions": actions_taken,
                "extracted": extracted,
            }

        if act_type == "error":
            return {
                "success": False,
                "error": action.get("reason", "agente reportou erro"),
                "actions": actions_taken,
                "extracted": extracted,
            }

        # Passa resultado de volta como contexto
        messages.append({
            "role": "user",
            "content": f"Resultado da ação: {json.dumps(result, ensure_ascii=False)}"
        })

    return {"success": False, "error": "max_steps atingido", "actions": actions_taken, "extracted": extracted}


async def _capture_page_state(page) -> dict:
    url = page.url
    try:
        text = (await page.inner_text("body"))[:1500]
    except Exception:
        text = ""

    elements = await page.evaluate("""
        () => {
            const sels = ['a.xgg','a.xyp','a.x12k','a.x7j','a.xg2','button','a.xg8'];
            const out = [];
            for (const s of sels) {
                for (const el of document.querySelectorAll(s)) {
                    const r = el.getBoundingClientRect();
                    if (r.width <= 0) continue;
                    const t = el.textContent.trim();
                    if (!t || t.length > 80) continue;
                    out.push({sel: s, text: t,
                        disabled: el.className.includes('p_AFDisabled')});
                }
            }
            return out;
        }
    """)

    inputs = await page.evaluate("""
        () => {
            const out = [];
            for (const el of document.querySelectorAll('input,select,textarea')) {
                const r = el.getBoundingClientRect();
                if (r.width <= 0) continue;
                out.push({tag: el.tagName, id: el.id||'',
                    type: el.type||'', value: (el.value||'').slice(0,40)});
            }
            return out;
        }
    """)

    return {"url": url, "text": text, "elements": elements, "inputs": inputs}


async def _execute_nav_action(page, action: dict) -> dict:
    act = action.get("action", "")
    sel = action.get("selector", "")
    text = action.get("text", "")
    value = action.get("value", "")

    if act == "wait":
        await asyncio.sleep(3)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        return {"success": True, "msg": "waited"}

    if act in ("done", "error", "read"):
        return {"success": True, "msg": act}

    if act == "click":
        sel_js = sel.replace("'", "\\'")
        text_js = text.replace("'", "\\'")[:30]
        result = await page.evaluate(f"""
            () => {{
                const els = document.querySelectorAll('{sel_js}');
                for (const el of els) {{
                    const t = el.textContent.trim();
                    const r = el.getBoundingClientRect();
                    if (('{text_js}' === '' || t.includes('{text_js}'))
                        && r.width > 0
                        && !el.className.includes('p_AFDisabled')) {{
                        el.click();
                        return 'clicked: ' + t.slice(0,40);
                    }}
                }}
                return null;
            }}
        """)
        if result:
            await asyncio.sleep(2)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            await asyncio.sleep(1)
            return {"success": True, "msg": result}
        return {"success": False, "msg": f"elemento não encontrado: {sel} / {text}"}

    if act == "fill":
        sel_js = sel.replace("'", "\\'")
        val_js = value.replace("'", "\\'")
        result = await page.evaluate(f"""
            () => {{
                const el = document.querySelector('{sel_js}');
                if (el && el.getBoundingClientRect().width > 0) {{
                    el.value = '{val_js}';
                    el.dispatchEvent(new Event('change', {{bubbles:true}}));
                    el.dispatchEvent(new Event('blur', {{bubbles:true}}));
                    return 'filled: ' + el.id;
                }}
                return null;
            }}
        """)
        await asyncio.sleep(0.5)
        return {"success": bool(result), "msg": result or f"input não encontrado: {sel}"}

    return {"success": False, "msg": f"ação desconhecida: {act}"}


# ─── 2. Análise de compliance com Groq ───────────────────────────────────────

_ANALYSIS_SYSTEM = """
Você é um auditor de compliance experiente do governo do Estado do Rio de Janeiro.
Analisa Ordens Bancárias (OBs) do SIAFE2 e publicações do DOERJ em busca de
irregularidades, corrupção e fraudes.

Padrões a identificar:
- Fracionamento: múltiplas OBs para o mesmo favorecido abaixo do limite de licitação (R$50.000)
- Superfaturamento: valores muito acima do mercado para o serviço descrito
- Nepotismo: favorecidos com sobrenomes iguais a servidores nomeados no DOERJ
- Direcionamento: contratos sem licitação para empresas recém-abertas
- OBs sem processo SEI: pagamentos sem respaldo documental
- Valores redondos suspeitos: OBs de R$100.000 exatos são raras na prática
- Concentração: 80% do valor pago para 1-2 fornecedores

Responda com JSON:
{
  "alertas": [
    {
      "tipo": "fracionamento|nepotismo|superfaturamento|sem_processo|valor_suspeito|concentracao",
      "severidade": "alta|media|baixa",
      "titulo": "Resumo de 1 linha",
      "descricao": "Explicação detalhada com os valores e nomes envolvidos",
      "evidencias": ["lista", "de", "fatos"],
      "favorecidos_envolvidos": ["Nome1", "Nome2"]
    }
  ],
  "resumo_geral": "Avaliação geral do conjunto de OBs analisadas"
}
"""


async def analisar_obs_com_groq(obs: list[dict]) -> dict:
    """
    Envia lista de OBs para o Groq analisar e retorna alertas de compliance.
    """
    if not obs:
        return {"alertas": [], "resumo_geral": "Sem OBs para analisar."}

    # Prepara resumo compacto para o LLM (evita context overflow)
    resumo_obs = []
    for ob in obs[:80]:  # limita para não estourar o contexto
        resumo_obs.append({
            "numero": ob.get("numero_ob", ""),
            "data": str(ob.get("data_emissao", "")),
            "favorecido": ob.get("favorecido_nome", "sem nome"),
            "cpf_cnpj": ob.get("favorecido_cpf", ""),
            "valor": ob.get("valor"),
            "processo_sei": ob.get("numero_processo", ""),
            "ug": ob.get("ug_codigo", ""),
            "status": ob.get("status", ""),
        })

    total_valor = sum(o.get("valor") or 0 for o in obs)
    sem_processo = sum(1 for o in obs if not o.get("numero_processo"))
    sem_valor = sum(1 for o in obs if not o.get("valor"))

    prompt = (
        f"Analise {len(obs)} Ordens Bancárias do Estado do RJ.\n"
        f"Total em valores: R$ {total_valor:,.2f}\n"
        f"OBs sem processo SEI: {sem_processo}\n"
        f"OBs sem valor registrado: {sem_valor}\n\n"
        f"Dados das OBs:\n{json.dumps(resumo_obs, ensure_ascii=False, indent=2)}\n\n"
        "Identifique todos os alertas de compliance. "
        "Seja específico com nomes, valores e números de OB."
    )

    try:
        raw = await _groq(
            [
                {"role": "system", "content": _ANALYSIS_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2000,
            temperature=0.2,
        )
        result = _parse_json(raw)
        if isinstance(result, dict):
            return result
        return {"alertas": [], "resumo_geral": raw[:500], "parse_error": True}
    except Exception as e:
        return {"alertas": [], "resumo_geral": f"Erro Groq: {e}"}


# ─── 3. Análise do DOERJ com Groq ────────────────────────────────────────────

_DOERJ_SYSTEM = """
Você é um auditor especializado em publicações do Diário Oficial do Estado do RJ (DOERJ).
Identifica irregularidades em nomeações, contratos e licitações publicados.

Alertas a identificar:
- Nomeação suspeita: cargo comissionado para pessoa com mesmo sobrenome de político
- Contrato emergencial: dispensa de licitação repetida para mesma empresa
- Alteração contratual: aditivo que dobra o valor original
- Exoneração em massa: muitas exonerações/nomeações no mesmo órgão num dia
- Licitação direcionada: edital com especificações muito específicas (marca única)

Responda com JSON:
{
  "alertas": [
    {
      "tipo": "nomeacao_suspeita|contrato_emergencial|aditivo_suspeito|licitacao_direcionada",
      "severidade": "alta|media|baixa",
      "titulo": "Resumo de 1 linha",
      "descricao": "Explicação com nomes, valores e órgãos",
      "evidencias": ["fato 1", "fato 2"],
      "ato_referencia": "Portaria 123/2026 ou similar"
    }
  ],
  "resumo_geral": "Avaliação geral das publicações do dia"
}
"""


async def analisar_doerj_com_groq(publicacoes: list[dict]) -> dict:
    """
    Analisa publicações do DOERJ com Groq e retorna alertas.
    """
    if not publicacoes:
        return {"alertas": [], "resumo_geral": "Sem publicações para analisar."}

    resumo = []
    for p in publicacoes[:60]:
        resumo.append({
            "tipo_ato": p.get("tipo_ato", ""),
            "orgao": p.get("orgao", "")[:60],
            "titulo": p.get("titulo", "")[:120],
            "texto": (p.get("texto") or "")[:300],
        })

    prompt = (
        f"Analise {len(publicacoes)} publicações do DOERJ de hoje.\n\n"
        f"Publicações:\n{json.dumps(resumo, ensure_ascii=False, indent=2)}\n\n"
        "Identifique todos os alertas de compliance."
    )

    try:
        raw = await _groq(
            [
                {"role": "system", "content": _DOERJ_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2000,
            temperature=0.2,
        )
        result = _parse_json(raw)
        if isinstance(result, dict):
            return result
        return {"alertas": [], "resumo_geral": raw[:500], "parse_error": True}
    except Exception as e:
        return {"alertas": [], "resumo_geral": f"Erro Groq: {e}"}


# ─── 4. Pipeline completo: coleta + análise + alertas ────────────────────────

async def rodar_analise_groq(session) -> list[dict]:
    """
    Lê OBs e publicações DOERJ do banco, analisa com Groq,
    salva alertas e retorna lista de alertas gerados.
    """
    from compliance_agent.database.models import (
        OrdemBancaria, PublicacaoDOERJ, Alerta
    )
    from sqlalchemy import desc

    hoje = date.today()

    # Busca OBs do dia
    obs_db = session.query(OrdemBancaria).filter(
        OrdemBancaria.data_emissao == hoje
    ).all()
    obs = [
        {
            "numero_ob": o.numero_ob,
            "data_emissao": o.data_emissao,
            "favorecido_nome": o.favorecido_nome,
            "favorecido_cpf": o.favorecido_cpf,
            "valor": o.valor,
            "numero_processo": o.numero_processo,
            "ug_codigo": o.ug_codigo,
            "status": o.status,
        }
        for o in obs_db
    ]

    # Busca publicações DOERJ do dia
    pubs_db = session.query(PublicacaoDOERJ).filter(
        PublicacaoDOERJ.data_publicacao == hoje
    ).all()
    pubs = [
        {
            "tipo_ato": p.tipo_ato,
            "orgao": p.orgao,
            "titulo": p.titulo,
            "texto": p.texto,
        }
        for p in pubs_db
    ]

    alertas_gerados = []

    # Analisa OBs
    if obs:
        resultado_obs = await analisar_obs_com_groq(obs)
        for alerta in resultado_obs.get("alertas", []):
            a = Alerta(
                tipo=alerta.get("tipo", "groq_ob"),
                severidade=alerta.get("severidade", "media"),
                titulo=alerta.get("titulo", "")[:300],
                descricao=alerta.get("descricao", ""),
                evidencias=json.dumps(alerta.get("evidencias", []), ensure_ascii=False),
                data_referencia=hoje,
            )
            session.add(a)
            alertas_gerados.append({
                "tipo": a.tipo,
                "severidade": a.severidade,
                "titulo": a.titulo,
                "descricao": a.descricao,
            })
    else:
        resultado_obs = {"resumo_geral": "Sem OBs coletadas hoje."}

    # Analisa DOERJ
    if pubs:
        resultado_doerj = await analisar_doerj_com_groq(pubs)
        for alerta in resultado_doerj.get("alertas", []):
            a = Alerta(
                tipo=alerta.get("tipo", "groq_doerj"),
                severidade=alerta.get("severidade", "media"),
                titulo=alerta.get("titulo", "")[:300],
                descricao=alerta.get("descricao", ""),
                evidencias=json.dumps(alerta.get("evidencias", []), ensure_ascii=False),
                data_referencia=hoje,
            )
            session.add(a)
            alertas_gerados.append({
                "tipo": a.tipo,
                "severidade": a.severidade,
                "titulo": a.titulo,
                "descricao": a.descricao,
            })
    else:
        resultado_doerj = {"resumo_geral": "Sem publicações DOERJ hoje."}

    session.commit()

    # Manda resumo para o Telegram
    if alertas_gerados:
        from compliance_agent.notifications.telegram import enviar_mensagem
        alta = sum(1 for a in alertas_gerados if a["severidade"] == "alta")
        media = sum(1 for a in alertas_gerados if a["severidade"] == "media")
        linhas = [
            f"🤖 *Análise Groq — {hoje}*",
            f"",
            f"🔴 Alta: {alta} | 🟡 Média: {media}",
            f"",
            "*Top alertas:*",
        ]
        for a in alertas_gerados[:5]:
            e = "🔴" if a["severidade"] == "alta" else "🟡"
            linhas.append(f"{e} {a['titulo'][:80]}")
        linhas.append(f"")
        linhas.append(f"_{resultado_obs.get('resumo_geral','')[:200]}_")
        await enviar_mensagem("\n".join(linhas))

    return alertas_gerados
