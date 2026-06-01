"""
Memória persistente + aprendizado contínuo do agente.

O agente NÃO esquece nada entre execuções. A cada ciclo ele:
  1. Lembra (recall) o contexto relevante do banco
  2. Aprende (learn) fatos novos, reforçando confiança com repetição
  3. Reflete (reflect) com o Hermes-3 405B sobre o que viu, gerando lições

Categorias de memória:
  contexto_admin  — fatos sobre a administração pública do RJ
  padrao_fraude   — padrões de irregularidade (confiança cresce com confirmação)
  entidade        — perfil acumulado de empresa/pessoa
  selector        — seletores de navegação que funcionaram
  licao           — lições do Hermes sobre erros/acertos

Tudo persiste na tabela memoria_aprendizado (SQLite).
"""

import json
from datetime import datetime
from typing import Optional

from compliance_agent.database.models import MemoriaAprendizado, get_session


# ─── Conhecimento-base inicial sobre a administração pública do RJ ────────────

CONTEXTO_INICIAL = [
    ("limite_dispensa_obras",
     "Lei 14.133/21 art. 75 I: dispensa de licitação para obras/serviços de "
     "engenharia até R$ 119.812,02 (atualizado). Fracionamento para fugir disso é ilegal."),
    ("limite_dispensa_compras",
     "Lei 14.133/21 art. 75 II: dispensa para compras e outros serviços até "
     "R$ 59.906,02. Múltiplas compras ao mesmo fornecedor somando acima disso = fracionamento."),
    ("limite_convite_antigo",
     "Lei 8.666/93 (ainda aplicável a contratos antigos): convite até R$ 176.000 "
     "para obras, R$ 80.000 para compras."),
    ("vedacao_sancionada",
     "Empresa no CEIS/CNEP não pode receber pagamento público. "
     "Lei 8.666/93 art. 87 e Lei 14.133/21 art. 156."),
    ("processo_sei_obrigatorio",
     "Todo pagamento estadual do RJ deve ter processo SEI associado. "
     "OB sem processo é indício de pagamento irregular."),
    ("ug_principais_rj",
     "UGs comuns no RJ: 300100 (SEFAZ), 200100 (Casa Civil). "
     "Pagamentos concentrados numa UG para um único favorecido merecem atenção."),
    ("rajada_fim_mes",
     "Concentração de OBs nos últimos 3 dias úteis do mês ou exercício pode indicar "
     "execução orçamentária forçada para não perder verba (empenho de fim de ano)."),
    ("valor_redondo",
     "Valores exatos e redondos (R$ 100.000,00) são raros em contratos legítimos. "
     "Costumam indicar estimativa sem cotação real ou direcionamento."),
    ("nepotismo",
     "Súmula Vinculante 13 do STF veda nomeação de parentes até 3º grau. "
     "Cruzar sobrenomes de nomeados com servidores/políticos do mesmo órgão."),
]


def _session(session=None):
    return session or get_session()


# ─── Aprender ─────────────────────────────────────────────────────────────────

def aprender(
    categoria: str,
    chave: str,
    valor: str,
    fonte: str = "regra",
    delta_confianca: float = 0.1,
    session=None,
) -> MemoriaAprendizado:
    """
    Registra ou reforça um fato na memória.
    Se já existe, incrementa confiança e contador de observações.
    """
    own = session is None
    s = _session(session)
    try:
        chave = (chave or "")[:300]
        item = (
            s.query(MemoriaAprendizado)
            .filter_by(categoria=categoria, chave=chave)
            .first()
        )
        if item:
            item.n_observacoes += 1
            item.confianca = min(1.0, (item.confianca or 0.5) + delta_confianca)
            item.ultima_vez = datetime.utcnow()
            # Atualiza valor se o novo for mais longo (mais informação)
            if valor and len(valor) > len(item.valor or ""):
                item.valor = valor
            item.fonte = fonte
        else:
            item = MemoriaAprendizado(
                categoria=categoria,
                chave=chave,
                valor=valor,
                confianca=0.5,
                n_observacoes=1,
                fonte=fonte,
            )
            s.add(item)
        s.commit()
        return item
    finally:
        if own:
            s.close()


# ─── Lembrar ──────────────────────────────────────────────────────────────────

def lembrar(categoria: str, chave: str = "", min_confianca: float = 0.0, session=None) -> list[dict]:
    """Recupera memórias de uma categoria (opcionalmente filtrando por chave)."""
    own = session is None
    s = _session(session)
    try:
        q = s.query(MemoriaAprendizado).filter(
            MemoriaAprendizado.categoria == categoria,
            MemoriaAprendizado.confianca >= min_confianca,
        )
        if chave:
            q = q.filter(MemoriaAprendizado.chave.ilike(f"%{chave}%"))
        q = q.order_by(MemoriaAprendizado.confianca.desc(),
                       MemoriaAprendizado.n_observacoes.desc())
        return [
            {
                "chave": m.chave,
                "valor": m.valor,
                "confianca": round(m.confianca or 0, 2),
                "n_observacoes": m.n_observacoes,
                "fonte": m.fonte,
            }
            for m in q.limit(50).all()
        ]
    finally:
        if own:
            s.close()


def contexto_para_prompt(session=None, max_itens: int = 25) -> str:
    """
    Monta um bloco de contexto com o que o agente já aprendeu,
    para injetar no prompt do Groq/Hermes. Prioriza alta confiança.
    """
    own = session is None
    s = _session(session)
    try:
        itens = (
            s.query(MemoriaAprendizado)
            .filter(MemoriaAprendizado.categoria.in_(
                ["contexto_admin", "padrao_fraude", "licao"]))
            .order_by(MemoriaAprendizado.confianca.desc(),
                      MemoriaAprendizado.n_observacoes.desc())
            .limit(max_itens)
            .all()
        )
        if not itens:
            return ""
        linhas = ["CONHECIMENTO ACUMULADO PELO AGENTE (use como base):"]
        for m in itens:
            conf = f"[conf {m.confianca:.1f}]" if m.confianca else ""
            linhas.append(f"- {conf} {m.valor[:300]}")
        return "\n".join(linhas)
    finally:
        if own:
            s.close()


# ─── Inicialização do conhecimento-base ───────────────────────────────────────

def garantir_contexto_inicial(session=None):
    """Carrega o conhecimento-base sobre administração pública (idempotente)."""
    own = session is None
    s = _session(session)
    try:
        for chave, valor in CONTEXTO_INICIAL:
            existe = (
                s.query(MemoriaAprendizado)
                .filter_by(categoria="contexto_admin", chave=chave)
                .first()
            )
            if not existe:
                s.add(MemoriaAprendizado(
                    categoria="contexto_admin",
                    chave=chave,
                    valor=valor,
                    confianca=0.9,   # conhecimento-base tem alta confiança
                    fonte="humano",
                ))
        s.commit()
    finally:
        if own:
            s.close()


# ─── Reflexão com Hermes-3 (aprendizado de alto nível) ────────────────────────

async def refletir_com_hermes(resumo_do_dia: str, session=None) -> Optional[str]:
    """
    Usa o Hermes-3 405B (via OpenRouter) para refletir sobre o dia de auditoria
    e extrair LIÇÕES generalizáveis, que são salvas na memória.

    Roda 1×/dia (no relatório). É o "aprendizado" do agente: ele olha para o
    que encontrou e tira conclusões que aplicará nos próximos dias.
    """
    from compliance_agent.llm.free_llm import openrouter_chat_async, openrouter_available

    if not openrouter_available():
        return None

    contexto = contexto_para_prompt(session)

    system = (
        "Você é o cérebro de aprendizado de um agente auditor da administração "
        "pública do Rio de Janeiro. Sua função é refletir sobre o que foi observado "
        "hoje e extrair LIÇÕES GERAIS e acionáveis para auditorias futuras. "
        "Cada lição deve ser curta (1-2 frases), específica e prática.\n\n"
        "Responda com JSON: {\"licoes\": [{\"chave\": \"id_curto\", \"licao\": \"texto\"}]}"
    )
    prompt = (
        f"{contexto}\n\n"
        f"OBSERVAÇÕES DE HOJE:\n{resumo_do_dia[:3000]}\n\n"
        "Que lições novas você extrai para melhorar a auditoria de amanhã? "
        "Foque em padrões reais, não em obviedades. Máximo 5 lições."
    )

    try:
        raw = await openrouter_chat_async(prompt, system=system, smart=True)
        import re
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        licoes = data.get("licoes", [])
        own = session is None
        s = _session(session)
        try:
            for lic in licoes:
                chave = lic.get("chave", "")[:300]
                texto = lic.get("licao", "")
                if chave and texto:
                    aprender("licao", chave, texto, fonte="hermes",
                             delta_confianca=0.15, session=s)
        finally:
            if own:
                s.close()
        return f"{len(licoes)} lições aprendidas pelo Hermes."
    except Exception as e:
        return f"Reflexão Hermes falhou: {e}"


# ─── Aprendizado de entidades (perfil acumulado) ──────────────────────────────

def registrar_entidade(nome: str, info: dict, session=None):
    """
    Acumula o perfil de uma empresa/pessoa ao longo do tempo.
    info pode conter: total_recebido, n_obs, flags, primeira_aparicao, etc.
    """
    if not nome:
        return
    own = session is None
    s = _session(session)
    try:
        item = (
            s.query(MemoriaAprendizado)
            .filter_by(categoria="entidade", chave=nome[:300])
            .first()
        )
        perfil = {}
        if item and item.valor:
            try:
                perfil = json.loads(item.valor)
            except Exception:
                perfil = {}
        # Mescla: soma valores numéricos, une listas
        for k, v in info.items():
            if isinstance(v, (int, float)) and isinstance(perfil.get(k), (int, float)):
                perfil[k] = perfil[k] + v
            elif isinstance(v, list):
                perfil[k] = list(set(perfil.get(k, []) + v))
            else:
                perfil[k] = v
        perfil["ultima_atualizacao"] = datetime.utcnow().isoformat()
        aprender("entidade", nome, json.dumps(perfil, ensure_ascii=False),
                 fonte="regra", session=s)
    finally:
        if own:
            s.close()


def perfil_entidade(nome: str, session=None) -> Optional[dict]:
    """Retorna o perfil acumulado de uma entidade, se existir."""
    mems = lembrar("entidade", chave=nome, session=session)
    if mems:
        try:
            return json.loads(mems[0]["valor"])
        except Exception:
            return None
    return None
