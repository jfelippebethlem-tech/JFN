"""
Memória persistente + aprendizado contínuo do agente.

O agente NÃO esquece nada entre execuções. A cada ciclo ele:
  1. Lembra (recall) o contexto relevante do banco
  2. Aprende (learn) fatos novos — confiança só sobe com fonte primária INDEPENDENTE (O6.7, 24/11/2026)
  3. Reflete (reflect) com o Hermes-3 405B sobre o que viu, gerando lições (hipóteses `nao_confirmado`)

Categorias de memória:
  contexto_admin  — fatos sobre a administração pública do RJ
  padrao_fraude   — padrões de irregularidade (confiança cresce só com fonte primária independente)
  observacao      — conclusão/observação de LLM sobre entidade (nunca fato de entidade)
  entidade        — perfil acumulado de empresa/pessoa
  selector        — seletores de navegação que funcionaram
  licao           — lições do Hermes sobre erros/acertos

Tudo persiste na tabela memoria_aprendizado (SQLite).
"""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from compliance_agent.database.models import MemoriaAprendizado, get_session


# ─── Conhecimento-base inicial sobre a administração pública do RJ ────────────

CONTEXTO_INICIAL = [
    # Sem número aqui de propósito: estes verbetes vão para dentro do prompt, e o teto do art. 75
    # muda por exercício (decreto anual). Os valores que estavam escritos eram os de 2024 e
    # envelheceram calados — quem resolve o teto é `compliance_agent/limites_dispensa.py`.
    ("limite_dispensa_obras",
     "Lei 14.133/21 art. 75 I: dispensa de licitação para obras/serviços de engenharia até o "
     "teto DO EXERCÍCIO (resolvido pelo sistema). Fracionamento para fugir disso é ilegal."),
    ("limite_dispensa_compras",
     "Lei 14.133/21 art. 75 II: dispensa para compras e outros serviços até o teto DO EXERCÍCIO "
     "(resolvido pelo sistema). Múltiplas compras ao mesmo fornecedor somando acima disso = "
     "fracionamento."),
    ("limite_convite_antigo",
     "Lei 8.666/93 art. 23 (ainda aplicável a contratos antigos), valores do Decreto 9.412/2018: convite "
     "até R$ 330.000 para obras/serviços de engenharia e R$ 176.000 para compras e demais serviços "
     "(antes de 19/07/2018: R$ 150.000 e R$ 80.000)."),
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
    # ── Conhecimento da pesquisa 2026-06-06 (docs/PESQUISA-DIREITO-ADMIN-CGE.md) ──
    ("improbidade_dolo_especifico",
     "Improbidade pós Lei 14.230/2021: exige DOLO ESPECÍFICO (art. 1º §2º — vontade livre e consciente de "
     "alcançar o resultado ilícito); o mero exercício da função sem ato doloso com fim ilícito AFASTA a "
     "improbidade (§3º). Acabou a modalidade culposa do art. 10. Apontar SEMPRE como indício, nunca afirmar dolo."),
    ("improbidade_dano_efetivo",
     "Fim do dano presumido: STJ REsp 1.929.685 (1ª Turma) — condenação pelo art. 10 da Lei 8.429 exige PROVA de "
     "dano EFETIVO ao erário; aplica-se a fatos anteriores à reforma se o processo ainda está pendente (Tema 1199/STF)."),
    ("anatomia_achado",
     "Achado de auditoria (TCU/ISSAI/CGU) = CRITÉRIO (o que deveria ser) × CONDIÇÃO (o que é) → CAUSA (razão do "
     "desvio) → EFEITO (consequência), sustentado por EVIDÊNCIA e fechado com CONCLUSÃO + RECOMENDAÇÃO. É o molde "
     "de todo parecer do Lex."),
    ("nota_tecnica_cge",
     "Modelo CGE-RJ (Decreto 47.408/2020): a saída é uma NOTA TÉCNICA 'COM Achado' (há indício) ou 'SEM Achado' "
     "(presunção de regularidade). PLANAT/RANAT = Resolução CGE 70/2020. Controle interno = Decreto 46.873/2019; "
     "integridade = Decreto 46.745/2019."),
    ("tcerj_dados_abertos",
     "dados.tcerj.tc.br (API pública) traz contratos/compras diretas do Estado com o nº do processo SEI e o "
     "EnquadramentoLegal das dispensas — fonte oficial que CONTORNA o WAF do sei.rj.gov.br. Usar p/ objeto, "
     "critério e contrato-vs-pago por CNPJ."),
    ("crimes_contratacao",
     "Crimes: peculato (CP 312), concussão (316), corrupção passiva (317)/ativa (333) — reclusão 2-12 anos; "
     "crimes licitatórios na Lei 14.133 (CP arts. 337-E a 337-P: contratação direta indevida, frustração do "
     "caráter competitivo etc.). Improbidade ≠ crime ≠ ilícito administrativo — separar as esferas."),
]


def _session(session=None):
    return session or get_session()


# ─── Proveniência (O6.7 do plano Esteira Única; auditoria AI-01/AI-02, 24/11/2026) ─────────────
#
# Antes: cada repetição somava +delta à confiança (a MESMA saída de LLM repetida 10× chegava a 1,0), o valor era
# trocado pelo "mais longo" sem histórico, e o prompt reinjetava por confiança — o modelo lia de volta, como
# conhecimento confiável, o que ele mesmo tinha escrito. Agora:
#   · confiança só SOBE com fonte primária INDEPENDENTE (`source_root_id` novo, de origem não-LLM); a mesma raiz
#     repetida não reforça, e repetição só conta `n_observacoes`;
#   · estado categórico: nao_confirmado | corroborado | refutado | expirado (validade por idade e categoria);
#   · saída de LLM NUNCA reforça — só cria/versiona item `nao_confirmado` com origem 'llm';
#   · valor novo não substitui calado: a versão anterior vai para `historico`; LLM não sobrescreve valor de
#     origem mais forte (a versão dele fica registrada, não vigente).

ORIGENS = ("fonte_primaria", "humano", "regra", "desconhecida", "llm")
ESTADOS = ("nao_confirmado", "corroborado", "refutado", "expirado")
_RANK_ORIGEM = {"fonte_primaria": 4, "humano": 3, "regra": 2, "desconhecida": 1, "llm": 0}
_RANK_ESTADO = {"corroborado": 0, "nao_confirmado": 1, "expirado": 2, "refutado": 3}
CONF_INICIAL = 0.5
TETO_NAO_CONFIRMADO = 0.5     # item sem fonte primária nunca é lido acima disto, seja qual for o histórico
MAX_VERSOES = 30
# validade (dias) por categoria; ausente = não expira (estado operacional: missao, selector, empirico…)
VALIDADE_DIAS = {
    "hipotese": 90, "observacao": 90, "esquema": 180, "entidade_investigada": 180, "entidade": 365,
    "licao": 365, "padrao_fraude": 365, "metodo": 365,
}
TIPOS_FONTE_PRIMARIA = ("sei", "siafe_ob", "url_oficial", "doerj", "pncp", "tcerj")
_SUFIXOS_OFICIAIS = (".gov.br", ".jus.br", ".leg.br", ".mp.br", ".def.br", ".tc.br")
_RX_RAIZ = re.compile(r"^(%s):[0-9a-f]{24}$" % "|".join(TIPOS_FONTE_PRIMARIA))
_FONTES_HUMANAS = {"humano", "usuario", "pesquisa", "auto_melhoria_seed"}   # seed = constante do código
_FONTES_REGRA = {"regra", "empirico", "lexml_fetcher"}
_PREFIXOS_LLM = ("hermes", "groq", "gemini", "claude", "llm", "openrouter", "comotor", "orquestrador",
                 "auto_melhoria", "pericia_aprendizado", "lex_aprendizado", "agente")


def origem_da_fonte(fonte: Optional[str]) -> str:
    """Origem a partir do rótulo `fonte` dos chamadores. Rótulo desconhecido é 'desconhecida', nunca 'regra'."""
    f = (fonte or "").strip().lower()
    if f in _FONTES_HUMANAS:
        return "humano"
    if f in _FONTES_REGRA:
        return "regra"
    if f.startswith(_PREFIXOS_LLM):
        return "llm"
    return "desconhecida"


def raiz_fonte_primaria(tipo: str, identificador: str) -> str:
    """`source_root_id` de uma fonte primária: documento SEI, OB do SIAFE, URL oficial, DOERJ, PNCP, TCE-RJ.

    Hash do identificador NORMALIZADO — o mesmo documento citado por dois caminhos dá a mesma raiz (não é
    independente). URL só conta se o domínio for oficial (.gov.br, .jus.br, .leg.br, .mp.br, .def.br, .tc.br)."""
    if tipo not in TIPOS_FONTE_PRIMARIA:
        raise ValueError(f"tipo de fonte primária deve ser um de {TIPOS_FONTE_PRIMARIA}")
    ident = " ".join(str(identificador or "").split()).lower()
    if tipo == "url_oficial":
        host = urlparse(ident).hostname or ""
        if not host.endswith(_SUFIXOS_OFICIAIS):
            raise ValueError(f"URL fora de domínio oficial: {host or ident!r}")
        ident = ident.split("#", 1)[0].rstrip("/")
    else:
        ident = re.sub(r"[^0-9a-z]", "", ident)
    if not ident:
        raise ValueError("identificador da fonte primária vazio")
    return f"{tipo}:{hashlib.sha256(f'{tipo}:{ident}'.encode()).hexdigest()[:24]}"


def _raiz_valida(raiz: str) -> bool:
    return bool(_RX_RAIZ.match(raiz or ""))


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _json_lista(texto) -> list:
    try:
        v = json.loads(texto) if texto else []
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


def estado_efetivo(item, agora: Optional[datetime] = None) -> str:
    """Estado lido: o gravado (NULL = nao_confirmado), com a validade da categoria aplicada.
    Idade: corroborado desde `confirmado_em`; LLM desde `primeira_vez` (repetir não renova); demais desde
    `ultima_vez` (dado de regra atualizado é dado novo)."""
    estado = item.estado if item.estado in ESTADOS else "nao_confirmado"
    if estado in ("refutado", "expirado"):
        return estado
    dias = VALIDADE_DIAS.get(item.categoria or "")
    if not dias:
        return estado
    if estado == "corroborado":
        base = item.confirmado_em or item.ultima_vez
    elif (item.origem or origem_da_fonte(item.fonte)) == "llm":
        base = item.primeira_vez
    else:
        base = item.ultima_vez or item.primeira_vez
    if base and (agora or _agora()) - base > timedelta(days=dias):
        return "expirado"
    return estado


def confianca_efetiva(item, agora: Optional[datetime] = None) -> float:
    """Confiança que os leitores usam: refutado/expirado = 0; não corroborado ≤ TETO_NAO_CONFIRMADO."""
    estado = estado_efetivo(item, agora)
    if estado in ("refutado", "expirado"):
        return 0.0
    c = item.confianca if item.confianca is not None else CONF_INICIAL
    return round(c if estado == "corroborado" else min(c, TETO_NAO_CONFIRMADO), 4)


def _registrar_versao(item, registro: dict) -> None:
    hist = _json_lista(item.historico)
    hist.append(registro)
    item.historico = json.dumps(hist[-MAX_VERSOES:], ensure_ascii=False, default=str)


def _versionar(item, valor: str, origem: str, fonte: str, agora: datetime) -> bool:
    """Valor novo: vira vigente se a origem não for mais fraca que a do vigente (a versão antiga vai ao
    histórico); senão fica no histórico como versão não adotada. Devolve True se o vigente mudou."""
    if not valor or valor == item.valor:
        return False
    atual = item.origem or origem_da_fonte(item.fonte)
    if _RANK_ORIGEM.get(origem, 0) >= _RANK_ORIGEM.get(atual, 1):
        if item.valor:
            _registrar_versao(item, {"valor": item.valor, "origem": atual, "fonte": item.fonte,
                                     "substituido_em": agora.isoformat()})
        item.valor = valor
        item.origem = origem
        item.fonte = fonte
        return True
    if any(v.get("valor") == valor and v.get("adotado") is False for v in _json_lista(item.historico)):
        return False                                    # a mesma versão não adotada, repetida, não cresce o histórico
    _registrar_versao(item, {"valor": valor, "origem": origem, "fonte": fonte, "em": agora.isoformat(),
                             "adotado": False})
    return False


# ─── Aprender ─────────────────────────────────────────────────────────────────

def aprender(
    categoria: str,
    chave: str,
    valor: str,
    fonte: str = "regra",
    delta_confianca: float = 0.1,
    session=None,
    *,
    source_root_id: Optional[str] = None,
    origem: Optional[str] = None,
) -> MemoriaAprendizado:
    """
    Registra um fato ou uma observação na memória.

    `source_root_id` (de `raiz_fonte_primaria`) = a fonte primária que sustenta o fato. A confiança só sobe
    (`delta_confianca`) quando chega uma raiz NOVA, de origem não-LLM; a primeira raiz corrobora com
    CONF_INICIAL. Sem raiz, a repetição só conta `n_observacoes`. `origem` vem do rótulo `fonte` quando
    omitida; origem 'llm' ignora raiz e delta (o modelo dizer que leu a fonte não é a fonte).
    """
    origem = origem or origem_da_fonte(fonte)
    if origem not in ORIGENS:
        raise ValueError(f"origem deve ser uma de {ORIGENS}")
    if source_root_id is not None and not _raiz_valida(source_root_id):
        raise ValueError("source_root_id inválido — gere com raiz_fonte_primaria(tipo, identificador)")
    raiz = source_root_id if origem != "llm" else None
    if origem == "fonte_primaria" and not raiz:
        raise ValueError("origem 'fonte_primaria' exige source_root_id")
    own = session is None
    s = _session(session)
    try:
        chave = (chave or "")[:300]
        agora = _agora()
        item = (
            s.query(MemoriaAprendizado)
            .filter_by(categoria=categoria, chave=chave)
            .first()
        )
        if item:
            item.n_observacoes = (item.n_observacoes or 0) + 1
            item.ultima_vez = agora
            _versionar(item, valor, origem, fonte, agora)
            raizes = _json_lista(item.fontes_raiz)
            if raiz and raiz not in raizes and item.estado != "refutado":
                raizes.append(raiz)
                item.fontes_raiz = json.dumps(raizes)
                if len(raizes) == 1:
                    item.confianca = CONF_INICIAL
                else:
                    item.confianca = min(1.0, (item.confianca or CONF_INICIAL) + max(0.0, delta_confianca))
                item.estado = "corroborado"
                item.confirmado_em = agora
            elif not item.estado:
                item.estado = "nao_confirmado"
        else:
            item = MemoriaAprendizado(
                categoria=categoria,
                chave=chave,
                valor=valor,
                confianca=CONF_INICIAL,
                n_observacoes=1,
                fonte=fonte,
                origem=origem,
                estado="corroborado" if raiz else "nao_confirmado",
                fontes_raiz=json.dumps([raiz]) if raiz else None,
                confirmado_em=agora if raiz else None,
                primeira_vez=agora,
                ultima_vez=agora,
            )
            s.add(item)
        s.commit()
        return item
    finally:
        if own:
            s.close()


def refutar(categoria: str, chave: str, source_root_id: str, motivo: str = "", session=None):
    """Fonte primária CONTRADIZ o item: estado 'refutado' (fica no banco, com o evento no histórico; leitores
    o excluem). Refutação exige raiz de fonte primária — opinião de LLM não refuta nem confirma."""
    if not _raiz_valida(source_root_id):
        raise ValueError("refutar exige source_root_id de fonte primária")
    own = session is None
    s = _session(session)
    try:
        item = s.query(MemoriaAprendizado).filter_by(categoria=categoria, chave=(chave or "")[:300]).first()
        if item is None:
            return None
        agora = _agora()
        item.estado = "refutado"
        _registrar_versao(item, {"evento": "refutado", "raiz": source_root_id, "motivo": motivo[:300],
                                 "em": agora.isoformat()})
        s.commit()
        return item
    finally:
        if own:
            s.close()


def expirar_memoria(session=None, agora: Optional[datetime] = None) -> int:
    """Grava 'expirado' onde a validade da categoria venceu (os leitores já aplicam sozinhos; isto só
    materializa o estado). Nada é apagado. Devolve quantos itens mudaram."""
    own = session is None
    s = _session(session)
    try:
        n = 0
        q = s.query(MemoriaAprendizado).filter(MemoriaAprendizado.categoria.in_(list(VALIDADE_DIAS)))
        for item in q.all():
            if estado_efetivo(item, agora) == "expirado" and item.estado != "expirado":
                item.estado = "expirado"
                n += 1
        s.commit()
        return n
    finally:
        if own:
            s.close()


def _ordem_leitura(item, agora):
    return (_RANK_ESTADO.get(estado_efetivo(item, agora), 1),
            -_RANK_ORIGEM.get(item.origem or origem_da_fonte(item.fonte), 1),
            -confianca_efetiva(item, agora),
            -(item.ultima_vez.timestamp() if item.ultima_vez else 0.0))


# ─── Lembrar ──────────────────────────────────────────────────────────────────

def lembrar(categoria: str, chave: str = "", min_confianca: float = 0.0, session=None,
            incluir_inativos: bool = False) -> list[dict]:
    """Recupera memórias de uma categoria (opcionalmente filtrando por chave).

    `confianca` devolvida é a EFETIVA (não corroborado ≤ 0,5); refutado/expirado só com `incluir_inativos`.
    Ordem: corroborado antes de não confirmado; origem mais forte primeiro; LLM por último."""
    own = session is None
    s = _session(session)
    try:
        agora = _agora()
        q = s.query(MemoriaAprendizado).filter(MemoriaAprendizado.categoria == categoria)
        if chave:
            q = q.filter(MemoriaAprendizado.chave.ilike(f"%{chave}%"))
        itens = []
        for m in q.order_by(MemoriaAprendizado.confianca.desc()).limit(1000).all():
            estado = estado_efetivo(m, agora)
            if not incluir_inativos and estado in ("refutado", "expirado"):
                continue
            if confianca_efetiva(m, agora) < min_confianca:
                continue
            itens.append(m)
        itens.sort(key=lambda m: _ordem_leitura(m, agora))
        return [
            {
                "chave": m.chave,
                "valor": m.valor,
                "confianca": round(confianca_efetiva(m, agora), 2),
                "confianca_registrada": round(m.confianca or 0, 2),
                "n_observacoes": m.n_observacoes,
                "fonte": m.fonte,
                "origem": m.origem or origem_da_fonte(m.fonte),
                "estado": estado_efetivo(m, agora),
                "n_fontes_independentes": len(_json_lista(m.fontes_raiz)),
            }
            for m in itens[:50]
        ]
    finally:
        if own:
            s.close()


def contexto_para_prompt(session=None, max_itens: int = 25) -> str:
    """
    Bloco de contexto com o que o agente já registrou, para o prompt do Groq/Hermes.

    É REFERÊNCIA, não prova: cada linha leva estado e origem; refutado/expirado não entram; corroborado por
    fonte primária vem antes, e o que o próprio LLM escreveu vem por último e marcado como hipótese.
    """
    own = session is None
    s = _session(session)
    try:
        agora = _agora()
        candidatos = (
            s.query(MemoriaAprendizado)
            .filter(MemoriaAprendizado.categoria.in_(
                ["metodo", "contexto_admin", "padrao_fraude", "licao"]))
            .limit(2000)
            .all()
        )
        itens = [m for m in candidatos if estado_efetivo(m, agora) not in ("refutado", "expirado")]
        itens.sort(key=lambda m: _ordem_leitura(m, agora))
        itens = itens[:max_itens]
        if not itens:
            return ""
        linhas = ["CONHECIMENTO ACUMULADO PELO AGENTE (referência, NÃO é prova; 'nao_confirmado' = hipótese sem "
                  "fonte primária independente — não trate como fato; origem 'llm' = escrito por modelo):"]
        for m in itens:
            origem = m.origem or origem_da_fonte(m.fonte)
            linhas.append(f"- [{estado_efetivo(m, agora)} · {origem} · conf {confianca_efetiva(m, agora):.1f}] "
                          f"{(m.valor or '')[:300]}")
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
            if existe and existe.fonte == "humano" and existe.valor != valor:
                # o conhecimento-base é do CÓDIGO: corrigido aqui, corrige no banco (23/11/2026 — o teto de
                # convite da 8.666 estava errado e o seed idempotente nunca o reescrevia)
                _registrar_versao(existe, {"valor": existe.valor, "origem": existe.origem or "desconhecida",
                                           "fonte": existe.fonte, "substituido_em": _agora().isoformat()})
                existe.valor = valor
            if not existe:
                s.add(MemoriaAprendizado(
                    categoria="contexto_admin",
                    chave=chave,
                    valor=valor,
                    confianca=0.9,   # conhecimento-base tem alta confiança
                    fonte="humano",
                    origem="humano",
                    estado="nao_confirmado",
                ))
        s.commit()
    finally:
        if own:
            s.close()


def podar_memoria(session=None) -> int:
    """Higiene da memória: remove stubs de bootstrap/teste de baixa confiança que poluem o contexto do prompt.
    Conservador — preserva tudo de fonte humano/pesquisa/usuario e qualquer item com confiança/observações reais.
    Retorna o nº de registros removidos."""
    own = session is None
    s = _session(session)
    removidos = 0
    try:
        from sqlalchemy import or_, and_
        q = s.query(MemoriaAprendizado).filter(
            or_(
                MemoriaAprendizado.fonte == "hermes_bootstrap",                      # stubs de bootstrap
                MemoriaAprendizado.fonte == "hermes_goal",                           # lições de ciclo de teste
                and_(MemoriaAprendizado.categoria.in_(["entidade", "hipotese"]),     # entidades/hipóteses de teste
                     MemoriaAprendizado.n_observacoes <= 1,
                     MemoriaAprendizado.confianca < 0.6),
                and_(MemoriaAprendizado.categoria == "padrao_fraude",                # padrões-stub não confirmados
                     MemoriaAprendizado.n_observacoes <= 1,
                     MemoriaAprendizado.confianca <= 0.5),
            )
        )
        for item in q.all():
            s.delete(item)
            removidos += 1
        s.commit()
        return removidos
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
                    # saída do próprio LLM: hipótese não confirmada, sem reforço (AI-01)
                    aprender("licao", chave, texto, fonte="hermes", origem="llm",
                             delta_confianca=0.0, session=s)
        finally:
            if own:
                s.close()
        return f"{len(licoes)} lições aprendidas pelo Hermes."
    except Exception as e:
        return f"Reflexão Hermes falhou: {e}"


# ─── Aprendizado de entidades (perfil acumulado) ──────────────────────────────

def registrar_entidade(nome: str, info: dict, session=None, fonte: str = "regra"):
    """
    Acumula o perfil de uma empresa/pessoa ao longo do tempo.
    info pode conter: total_recebido, n_obs, flags, primeira_aparicao, etc.

    `fonte` de LLM (hermes*, groq, orquestrador…) NÃO entra no perfil: o que o modelo disse sobre a entidade
    vira `observacao` (`entidade:<nome>`, nao_confirmado, origem 'llm') — nunca fato de entidade.
    """
    if not nome:
        return
    if origem_da_fonte(fonte) == "llm":
        aprender("observacao", f"entidade:{nome}"[:300], json.dumps(info, ensure_ascii=False, default=str),
                 fonte=fonte, origem="llm", delta_confianca=0.0, session=session)
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
        perfil["ultima_atualizacao"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        aprender("entidade", nome, json.dumps(perfil, ensure_ascii=False),
                 fonte=fonte, session=s)
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
