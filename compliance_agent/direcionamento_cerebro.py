# -*- coding: utf-8 -*-
"""Cérebro de DIRECIONAMENTO — lê EDITAL + ATA DE JULGAMENTO e avalia indícios (LLM + raciocínio).

Direcionamento é mais comum e mais pegável que conluio (decisão do dono 2026-06-08). O sinal-mestre:
exigências restritivas no edital (atestado muito específico, marca, certificação sem essencialidade) que
produzem uma CASCATA de desclassificações/inabilitações — e o vencedor, mal classificado em preço, sobe
após as quedas dos mais baratos. Não é parâmetro numérico: precisa de "cérebro".

Fonte de dados PROVADA: a ata de julgamento vem no PNCP (`collectors/pncp.baixar_documentos`) — caso RJ real
tinha a cascata (atestado/desclassificação/ranking) no texto. Spec: docs/DIRECIONAMENTO-CEREBRO-SPEC.md.

HONESTO (cláusula do JFN): indício a verificar, NUNCA acusação (presunção de legitimidade). Cada achado cita
o TRECHO que o sustenta. Sem ata/sem dado → grau verde + 'dados insuficientes' (nunca inventa). LLM injetável
(`gerar`) p/ teste sem rede/chave; default = Groq.
"""
from __future__ import annotations

import logging
import json
import re

_SYS = (
    "Você é AUDITOR DE CONTROLE EXTERNO (TCU/TCE-RJ) avaliando INDÍCIOS de DIRECIONAMENTO em licitação. "
    "Regras ABSOLUTAS: (1) NUNCA afirme irregularidade ou fraude — fale sempre em 'indício a verificar' "
    "(presunção de legitimidade dos atos administrativos). (2) CADA achado DEVE citar o TRECHO literal que o "
    "sustenta; sem trecho, não afirme. (3) Se a ATA não trouxer ranking/motivos de desclassificação, retorne "
    "grau 'verde' e 'dados insuficientes' — NÃO invente. Procure: exigências restritivas (atestado idêntico ao "
    "objeto/com prazo/local/quantitativo desproporcional; vedação de somatório de atestados sem justificativa "
    "— Súmula TCU 263; marca; certificações sem essencialidade) e a CASCATA (muitas desclassificações/"
    "inabilitações pelo MESMO motivo; vencedor longe do menor preço que sobe após quedas dos mais baratos). "
    "PENSE DE FORMA INTERPRETATIVA — o rol acima é EXEMPLIFICATIVO, NÃO taxativo. Para CADA exigência (e para o "
    "CONJUNTO), aplique o TESTE FINALÍSTICO: ela é (a) INDISPENSÁVEL à execução do objeto, (b) PROPORCIONAL à "
    "dimensão/risco, (c) PERTINENTE (não impertinente — art. 9º,I,'c' Lei 14.133) e (d) atendível por VÁRIOS "
    "fornecedores do mercado? Acenda alerta quando: pede objeto/atestado IDÊNTICO onde 'similar' bastaria; a "
    "descrição copia o catálogo de UM fabricante (marca disfarçada, falta 'ou equivalente' — Súmula TCU 270); "
    "impõe custo prévio indevido — equipe/amostra/vínculo/visita exigidos ANTES da contratação (Súmula TCU 272); "
    "faz recorte geográfico (sede/domicílio local) ou temporal (prazo que só o incumbente cumpre); ou quando "
    "exigências individualmente legais, SOMADAS, afunilam para um fornecedor (efeito sistêmico). REGRA DE OURO: se "
    "uma exigência NÃO está na lista mas FALHA no teste finalístico (não-indispensável + desproporcional + afunila "
    "o mercado + sem motivação técnica nos autos), trate-a como direcionamento e DESCREVA o mecanismo, citando "
    "art. 9º,I / art. 37 Lei 14.133 ainda que sem súmula específica. Ausência de motivação técnica nos autos ⇒ "
    "presunção de irregularidade (o ônus de justificar é da Administração). "
    "Responda SOMENTE com um objeto JSON no schema pedido, sem texto fora do JSON. Seja CONCISO: no "
    "máximo 5 exigências restritivas e 8 itens de cascata; cada 'trecho' literal com no máximo 200 caracteres."
)

_SCHEMA = (
    '{"grau":"verde|amarelo|vermelho","resumo":"1-2 frases (indício, não acusação)",'
    '"raciocinio":"explique PASSO A PASSO como chegou ao grau: o que leu, o que considerou restritivo ou '
    'normal e por quê, o que faltou nos documentos (máx 6 frases — para o auditor entender seu pensamento)",'
    '"exigencias_restritivas":[{"trecho":"literal do edital","por_que_restringe":"","jurisprudencia":""}],'
    '"cascata":[{"licitante":"","ordem_preco":0,"situacao":"classificado|desclassificado|inabilitado",'
    '"motivo":"","trecho":"literal da ata"}],'
    '"vencedor":{"nome":"","ordem_preco_original":0,"subiu_apos_quedas":0},'
    '"dados_suficientes":true,"ressalva":"presunção de legitimidade; indício a apurar, não acusação"}'
)


logger = logging.getLogger(__name__)


def presinais(ata_txt: str) -> dict:
    """Sinais OBJETIVOS (determinísticos) da ata — corroboram o cérebro, não dependem de LLM."""
    t = (ata_txt or "").lower()
    return {
        "n_desclassificacoes": len(re.findall(r"desclassific", t)),
        "n_inabilitacoes": len(re.findall(r"inabilit", t)),
        "mencoes_atestado": len(re.findall(r"atestado", t)),
        "mencoes_recurso": len(re.findall(r"recurso", t)),
        "tem_ata": bool(re.search(r"desclassific|inabilit|habilitad|classificad", t)) and len(t) > 1500,
    }


_KW_EDITAL = ("atestado", "qualificac", "habilitac", "capacidade tecnica", "capacidade técnica",
              "comprovac", "exigenc", "exigênc", "marca", "modelo", "certificac", "certificad",
              "visita tecnica", "vistoria", "amostra", "prazo de", "experiencia", "quantitativo")
_KW_ATA = ("desclassific", "inabilit", "habilitad", "classificad", "vencedor", "recurso", "lance",
           "proposta", "menor preco", "menor preço")


def _trechos_relevantes(texto: str, keywords: tuple, budget: int, janela: int = 600) -> str:
    """Extrai janelas ao redor das keywords (onde moram as exigências/decisões) — em vez de cortar o
    começo do doc. Garante que o LLM veja a qualificação técnica/julgamento mesmo em editais longos."""
    t = texto or ""
    if len(t) <= budget:
        return t
    low = t.lower()
    marcas = sorted({m.start() for kw in keywords for m in re.finditer(re.escape(kw), low)})
    if not marcas:
        return t[:budget]
    # funde janelas próximas e concatena até o budget
    trechos, ult_fim = [], -1
    total = 0
    for p in marcas:
        ini, fim = max(0, p - janela // 3), min(len(t), p + janela)
        if ini <= ult_fim:  # sobrepõe: estende
            trechos[-1] = (trechos[-1][0], fim)
        else:
            trechos.append((ini, fim))
        ult_fim = fim
    out = []
    for ini, fim in trechos:
        seg = t[ini:fim]
        if total + len(seg) > budget:
            seg = seg[: budget - total]
        out.append(seg); total += len(seg)
        if total >= budget:
            break
    return " […] ".join(out)


def _montar_user(edital_txt: str, ata_txt: str, contexto: dict | None) -> str:
    ed = _trechos_relevantes(edital_txt, _KW_EDITAL, 11000)
    at = _trechos_relevantes(ata_txt, _KW_ATA, 12000)   # a ata é o mais importante (cascata)
    ctx_d = dict(contexto or {})
    # 'padroes_ligados' (aprendizado cross-fornecedor) sai do JSON truncado e vira SEÇÃO própria, p/ não
    # ser cortado pelos 400 chars. Anti-viés: contexto p/ corroborar/contrastar, JAMAIS culpa por associação.
    padroes = str(ctx_d.pop("padroes_ligados", "") or "").strip()
    ctx = json.dumps(ctx_d, ensure_ascii=False)[:400]
    sec_pad = (f"=== PADRÕES EM FORNECEDORES LIGADOS (mesmos sócios/veículos) — corrobore/contraste, NÃO "
               f"copie; presunção de legitimidade ===\n{padroes[:1200]}\n\n" if padroes else "")
    return (f"CONTEXTO: {ctx}\n\n{sec_pad}=== EDITAL (trechos relevantes) ===\n{ed or '(não fornecido)'}\n\n"
            f"=== ATA DE JULGAMENTO (trechos relevantes) ===\n{at or '(não fornecida)'}\n\n"
            f"Avalie o direcionamento e responda SOMENTE com este JSON:\n{_SCHEMA}")


async def _groq_gerar(messages: list[dict]) -> str:
    from compliance_agent.llm.groq_agent import _groq
    return await _groq(messages, max_tokens=2000, temperature=0.1)


ultimo_provedor: str = ""  # provedor que respondeu a ÚLTIMA chamada — proveniência real p/ quem persiste 'modelo'


async def _gerar_default(messages: list[dict]) -> str:
    """LLM padrão: tenta Gemini; se cair (chave/limite/erro), cai para o Hermes/Groq (pedido do dono).
    Honesto: se NENHUM responder, propaga o erro (o cérebro reporta 'indisponível', não fabrica)."""
    # cooldown por TIPO de erro (mesma lógica do free_llm.best_free_chat — não re-bater provedor morto)
    global ultimo_provedor
    from compliance_agent.llm.free_llm import _em_cooldown, _marcar_cooldown, _limpar_cooldown
    erros = []
    if _gemini_keys() and not _em_cooldown("gemini"):
        try:
            r = await gerar_gemini(messages)
            if r and r.strip():
                _limpar_cooldown("gemini")
                ultimo_provedor = "gemini"
                return r
            erros.append("gemini: vazio")
        except Exception as e:  # noqa: BLE001
            _marcar_cooldown("gemini", e)
            erros.append(f"gemini: {str(e)[:50]}")
    if not _em_cooldown("groq"):
        try:
            r = await _groq_gerar(messages)  # Hermes usa Groq/OpenRouter
            _limpar_cooldown("groq")
            ultimo_provedor = "groq"
            return r
        except Exception as e:  # noqa: BLE001
            _marcar_cooldown("groq", e)
            erros.append(f"groq: {str(e)[:50]}")
    # FALLBACK aditivo (pedido do dono): groq → cerebras → nvidia → resto do _EXTRA. Só roda quando
    # gemini+groq falham/cooldown — o caminho de sucesso atual fica intacto. O cap mensal (§4.1) protege
    # os provedores _EXTRA de cobrança (extra_available já checa cap + chave).
    try:
        from compliance_agent.llm.free_llm import (
            cerebras_available, cerebras_chat_async, extra_available, extra_chat_async, _EXTRA,
        )
        sys_txt = " ".join(m["content"] for m in messages if m.get("role") == "system")
        usr_txt = "\n".join(m["content"] for m in messages if m.get("role") != "system")
        provedores = []
        if cerebras_available():
            provedores.append(("cerebras", lambda: cerebras_chat_async(usr_txt, sys_txt, smart=True, max_tokens=2000)))
        for prov in (["nvidia"] + [p for p in _EXTRA if p != "nvidia"]):
            if extra_available(prov):
                provedores.append((prov, lambda p=prov: extra_chat_async(p, usr_txt, sys_txt, max_tokens=2000)))
        for nome, chamada in provedores:
            if _em_cooldown(nome):
                continue
            try:
                r = await chamada()
                if r and r.strip():
                    _limpar_cooldown(nome)
                    ultimo_provedor = nome
                    return r
                erros.append(f"{nome}: vazio")
            except Exception as e:  # noqa: BLE001
                _marcar_cooldown(nome, e)
                erros.append(f"{nome}: {str(e)[:50]}")
    except Exception as e:  # noqa: BLE001 — import/setup do fallback falhou: cai no raise honesto
        erros.append(f"fallback-extra indisponível: {str(e)[:50]}")
    # Parênteses obrigatórios: `+` liga antes de `or`, então sem eles o fallback era
    # código morto e o log saía com a cauda vazia ("… — ") justamente no caso em que
    # não havia erro a contar (todos em cooldown) — a mensagem mais informativa sumia.
    raise RuntimeError("nenhum LLM respondeu (ou em cooldown) — "
                       + (" | ".join(erros) or "todos em cooldown"))


import threading as _threading

_BG_LOOP = None
_BG_LOCK = _threading.Lock()


def _bg_loop():
    """Event loop asyncio DEDICADO (thread daemon) — UM loop estável para chamar o LLM async de contexto
    SÍNCRONO (ex.: lex.gerar) sem o churn de asyncio.run (que causava 'fileobj is not registered')."""
    global _BG_LOOP
    if _BG_LOOP is None or _BG_LOOP.is_closed():
        with _BG_LOCK:
            if _BG_LOOP is None or _BG_LOOP.is_closed():
                import asyncio
                loop = asyncio.new_event_loop()
                _threading.Thread(target=loop.run_forever, daemon=True, name="jfn-llm-loop").start()
                _BG_LOOP = loop
    return _BG_LOOP


def gerar_sync(prompt: str, sistema: str = "", timeout: float = 45.0) -> str:
    """Chamada LLM SÍNCRONA robusta (de qualquer contexto, sync ou async) via loop dedicado persistente.
    Reusa _gerar_default (Gemini rotacionado). Em teste, injete um mock — não chame isto."""
    import asyncio
    msgs = [{"role": "system", "content": sistema or "Você é auditor de controle externo do JFN."},
            {"role": "user", "content": prompt}]
    fut = asyncio.run_coroutine_threadsafe(_gerar_default(msgs), _bg_loop())
    return fut.result(timeout=timeout)


def _ler_env_file(caminho) -> dict:
    """Lê KEY=VALUE de um .env (p/ puxar as chaves válidas do ~/.hermes/.env). Nunca loga valores."""
    from pathlib import Path
    d: dict = {}
    try:
        for ln in Path(caminho).read_text(encoding="utf-8", errors="ignore").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as exc:
        logger.debug(".env ilegível (segue com ambiente atual): %s", exc)
    return d


_GEMINI_KEYS_CACHE: list | None = None


def _gemini_keys() -> list:
    """POOL de chaves Gemini deduplicado: GEMINI_API_KEYS (pool) + GEMINI_API_KEY do JFN, MAIS o pool
    VÁLIDO do Yoda em ~/.hermes/.env (as do JFN/.env podem estar esgotadas/erradas). POR QUÊ: o motor com
    1 chave morta dava 429 e derrubava TODO recurso-LLM (parecer/direção)."""
    import os
    # KILL-SWITCH (pedido do dono 2026-06-25): GEMINI_DISABLED desliga o Gemini em TODO o JFN num ponto só
    # — pool free_llm (gemini_available), Yoda (_gerar_default), hermes 2c (gerar_gemini) caem p/
    # Cerebras/Groq/OpenRouter:free. Motivo: chaves AI Studio com billing ativo cobravam fora do free tier.
    # Reverter: tirar GEMINI_DISABLED do .env — as chaves seguem preservadas (tarefa "repor billing Gemini").
    # FURO corrigido 2026-07-07: processo standalone sem `set -a; . .env` não tinha a flag no os.environ,
    # mas achava as CHAVES nos arquivos → bypass do kill-switch (cobrança). A flag agora é lida dos MESMOS
    # arquivos onde as chaves são buscadas.
    from pathlib import Path
    _flag = (os.environ.get("GEMINI_DISABLED", "")
             or _ler_env_file(Path(__file__).resolve().parents[1] / ".env").get("GEMINI_DISABLED", "")
             or _ler_env_file(Path.home() / ".hermes" / ".env").get("GEMINI_DISABLED", ""))
    if _flag.strip().lower() in ("1", "true", "yes", "on"):
        return []
    global _GEMINI_KEYS_CACHE
    if _GEMINI_KEYS_CACHE is not None:
        return _GEMINI_KEYS_CACHE
    import os
    import re
    from pathlib import Path
    hm = _ler_env_file(Path.home() / ".hermes" / ".env")
    fontes = [os.environ.get("GEMINI_API_KEYS", ""), os.environ.get("GEMINI_API_KEY", ""),
              hm.get("GEMINI_API_KEYS", ""), hm.get("GEMINI_API_KEY", "")]
    keys: list = []
    vistos: set = set()
    for f in fontes:
        for k in re.split(r"[,\s]+", f or ""):
            k = k.strip()
            if k and k not in vistos:
                vistos.add(k)
                keys.append(k)
    _GEMINI_KEYS_CACHE = keys
    return keys


_GEMINI_RR = 0


async def gerar_gemini(messages: list[dict], model: str | None = None,
                       max_tokens: int | None = None) -> str:
    """Gemini robusto: ROTAÇÃO do pool de chaves (round-robin) × MODELOS em cascata (buckets de RPM
    distintos no free tier) × backoff. Adapta messages OpenAI→Gemini (system → systemInstruction)."""
    global _GEMINI_RR
    import asyncio as _aio
    import os
    import httpx
    keys = _gemini_keys()
    if not keys:
        raise RuntimeError("nenhuma chave Gemini (JFN/.env nem ~/.hermes/.env)")
    modelos = [model] if model else [
        os.environ.get("DIRECIONAMENTO_GEMINI_MODEL", "gemini-2.5-flash"),
        "gemini-2.0-flash", "gemini-2.5-flash-lite",
    ]
    sys_txt = "\n".join(m["content"] for m in messages if m["role"] == "system")
    user_txt = "\n".join(m["content"] for m in messages if m["role"] != "system")
    body: dict = {"contents": [{"role": "user", "parts": [{"text": user_txt}]}],
                  "generationConfig": {"temperature": 0.1, "maxOutputTokens": max_tokens or 4096,
                                       "responseMimeType": "application/json"}}
    if sys_txt:
        body["systemInstruction"] = {"parts": [{"text": sys_txt}]}
    n = len(keys)
    erros = []
    async with httpx.AsyncClient(timeout=60) as client:
        for mi, mdl in enumerate(modelos):
            for tentativa in range(2 if mi == 0 else 1):
                so_rate = True
                for off in range(n):
                    key = keys[(_GEMINI_RR + off) % n]
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={key}"
                    try:
                        r = await client.post(url, json=body)
                        if r.status_code in (429, 403, 401):
                            erros.append(f"{mdl}:{r.status_code}")
                            continue
                        if r.status_code == 404:
                            erros.append(f"{mdl}:404")
                            so_rate = False
                            break
                        r.raise_for_status()
                        j = r.json()
                        txt = j.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        _GEMINI_RR = (_GEMINI_RR + off + 1) % n
                        return txt
                    except httpx.HTTPStatusError as e:
                        erros.append(str(e.response.status_code))
                        so_rate = False
                    except Exception as e:  # noqa: BLE001
                        erros.append(str(e)[:20])
                        so_rate = False
                if mi == 0 and tentativa == 0 and so_rate:
                    await _aio.sleep(3.0)
                else:
                    break
    # Rede de segurança de QUALIDADE: se TODAS as chaves/modelos Gemini falharem, cai p/ Cerebras
    # (gpt-oss-120b, ultrarrápido, com saldo) — os produtos nunca ficam sem IA. Gemini continua o 1º (qualidade).
    try:
        from compliance_agent.llm.free_llm import cerebras_available, cerebras_chat_async
        if cerebras_available():
            return await cerebras_chat_async(
                user_txt, system=(sys_txt + "\n\nResponda APENAS com JSON válido."), max_tokens=4096)
    except Exception as e:  # noqa: BLE001
        erros.append(f"cerebras:{str(e)[:24]}")
    raise RuntimeError(f"Gemini+Cerebras: {len(modelos)} modelos × {n} chaves falharam ({','.join(erros[:14])})")


# ──────────────────────────────────────────────────────────────────────────────
# FUSÃO determinístico × subjetivo — concilia as duas camadas num único veredito.
# Doutrina (dono 2026-07-24): "não só deterministicamente, mas subjetivamente também". NENHUM alarme é
# silenciado: o grau final é o MAIOR dos dois quando ambos são conclusivos; se um é inconclusivo
# (indeterminado/indisponível), vale o outro; a DIVERGÊNCIA entre camadas conclusivas é sinalizada para a
# análise crítica do auditor (o LLM pode subestimar um sinal literal; ou ver direcionamento sistêmico que o
# regex não capta). Puro, sem rede — testável isoladamente.
_ORDEM_GRAU = {"verde": 1, "amarelo": 2, "vermelho": 3}


def _nivel(grau) -> int | None:
    """Nível conclusivo do grau (1/2/3); None para inconclusivo (indeterminado/indisponivel/vazio)."""
    return _ORDEM_GRAU.get((grau or "").strip().lower())


def fundir_graus(grau_llm, grau_det) -> dict:
    """Concilia o grau subjetivo (LLM) e o objetivo (determinístico) num veredito único.

    Retorna {grau, fonte_grau, divergencia}. `fonte_grau` diz qual camada DRIVOU o final:
    'subjetivo' | 'objetivo' | 'subjetivo+objetivo' (concordância) | 'nenhum'. `divergencia` só existe
    quando AMBAS as camadas são conclusivas e discordam (≥1 nível) — carrega qual foi mais severa e por quê.
    """
    n_llm, n_det = _nivel(grau_llm), _nivel(grau_det)
    if n_llm is None and n_det is None:
        return {"grau": "indeterminado", "fonte_grau": "nenhum", "divergencia": None}
    if n_llm is None:
        return {"grau": grau_det.strip().lower(), "fonte_grau": "objetivo", "divergencia": None}
    if n_det is None:
        return {"grau": grau_llm.strip().lower(), "fonte_grau": "subjetivo", "divergencia": None}
    g_llm, g_det = grau_llm.strip().lower(), grau_det.strip().lower()
    if n_llm == n_det:
        return {"grau": g_llm, "fonte_grau": "subjetivo+objetivo", "divergencia": None}
    if n_det > n_llm:
        grau, fonte, severa = g_det, "objetivo", "objetivo"
        nota = ("Camada objetiva (regex/jurisprudência sobre trechos literais) mais severa que o LLM — o "
                "modelo pode ter subestimado cláusula restritiva/cascata literal; revisar sinais_deterministicos.")
    else:
        grau, fonte, severa = g_llm, "subjetivo", "subjetivo"
        nota = ("Camada subjetiva (LLM) mais severa que o determinístico — possível direcionamento "
                "interpretativo/sistêmico não captável por regex; revisar exigencias_restritivas do parecer.")
    return {"grau": grau, "fonte_grau": fonte,
            "divergencia": {"grau_llm": g_llm, "grau_det": g_det, "delta": abs(n_llm - n_det),
                            "camada_mais_severa": severa, "nota": nota}}


def _com_fusao(base: dict, grau_llm, grau_det) -> dict:
    """Aplica a fusão sobre um dict de retorno: define grau (conciliado), grau_llm, grau_det e divergencia."""
    fus = fundir_graus(grau_llm, grau_det)
    base["grau"] = fus["grau"]
    base["grau_llm"] = (grau_llm or None)
    base["grau_det"] = (grau_det or None)
    base["fonte_grau"] = fus["fonte_grau"]
    base["divergencia"] = fus["divergencia"]
    return base


async def avaliar_direcionamento(edital_txt: str = "", ata_txt: str = "", *, contexto: dict | None = None,
                                 gerar=None) -> dict:
    """Avalia indícios de direcionamento (LLM sobre edital+ata). `gerar`: callable async(messages)->str
    (default Groq; injete um fake no teste). Retorna o JSON do schema + `presinais` + proveniência."""
    sig = presinais(ata_txt)
    # ADITIVO: camada DETERMINÍSTICA (regex/keyword, SEM LLM) — surge MESMO com a IA offline (Gemini
    # desligado, §4.1). Reaproveita a doutrina (cláusulas restritivas + cascata) sobre edital+ata.
    from compliance_agent.direcionamento_sinais import analisar_direcionamento_det
    sinais_det = analisar_direcionamento_det(((edital_txt or "") + "\n\n" + (ata_txt or "")).strip())
    grau_det = sinais_det.get("grau_det")  # vermelho|amarelo|verde|indeterminado (camada objetiva/offline)
    # PRESENÇA de sinal objetivo (amarelo/vermelho) ≠ ausência (verde). Só a PRESENÇA resgata um veredito
    # quando o LLM cai: "verde" determinístico com LLM offline seria falso conforto (ausência de red flag
    # ≠ regularidade — a camada interpretativa nem rodou). Honestidade: absence of evidence ≠ evidence of absence.
    det_presenca = grau_det if (grau_det or "").lower() in ("amarelo", "vermelho") else None
    base = {"presinais": sig, "sinais_deterministicos": sinais_det, "fonte": "direcionamento_cerebro"}
    # dados suficientes = tem ATA (cascata) OU o texto realmente PARECE um edital de licitação (marcadores
    # de habilitação/qualificação). Evita "analisar" menu do SEI ou contrato de execução como se fosse edital.
    ed_low = (edital_txt or "").lower()
    edital_de_licitacao = (len(ed_low) > 1500 and sum(
        ed_low.count(k) for k in ("edital", "atestado", "qualificac", "habilitac", "pregao", "pregão",
                                  "termo de referencia", "termo de referência", "licitac", "proposta")) >= 3)
    if not sig["tem_ata"] and not edital_de_licitacao:
        # O cérebro não vê edital/ata. Se a camada objetiva achou PRESENÇA de sinal (gate próprio), o grau
        # surge dela (não fica cego); senão, indeterminado honesto (não invento juízo).
        if det_presenca:
            return _com_fusao({**base, "dados_suficientes": True,
                    "resumo": f"O LLM não viu edital/ata claros, mas a camada determinística achou sinal "
                              f"objetivo (grau {det_presenca}) — indício a verificar.",
                    "ressalva": "veredito objetivo; buscar o edital/ata para o parecer interpretativo completo"},
                    None, grau_det)
        # RESOLVIDO (não 'indeterminado'): classifica o QUE o documento é e diz o que buscar. Acionável.
        from compliance_agent.sei.classificador_doc import classificar_doc
        tipo = classificar_doc("", ((edital_txt or "") + " " + (ata_txt or "")).strip())
        return {**base, "grau": "nao_aplicavel", "dados_suficientes": False,
                "tipo_documento": tipo, "grau_llm": None, "grau_det": grau_det,
                "fonte_grau": "nenhum", "divergencia": None,
                "resumo": f"Documento classificado como '{tipo}': não é edital de licitação nem ata de "
                          "julgamento — direcionamento não se avalia sobre esta peça. Para avaliar, buscar o "
                          "PROCESSO LICITATÓRIO (edital + ata de julgamento) que originou esta contratação.",
                "ressalva": "veredito resolvido: peça licitatória ausente; presunção de legitimidade"}
    gerar = gerar or _gerar_default
    messages = [{"role": "system", "content": _SYS}, {"role": "user", "content": _montar_user(edital_txt, ata_txt, contexto)}]
    try:
        raw = await gerar(messages)
    except Exception as e:  # noqa: BLE001 — LLM indisponível: honesto, não fabrica. Mas o SINAL objetivo VALE.
        if det_presenca:
            return _com_fusao({**base, "dados_suficientes": True,
                    "resumo": f"LLM indisponível ({str(e)[:50]}) — veredito pela camada determinística "
                              f"(grau {det_presenca}): sinal objetivo achado; indício a verificar.",
                    "ressalva": "veredito objetivo (LLM offline); indício a apurar, não acusação"},
                    None, grau_det)
        return {**base, "grau": "pendente_reprocessar", "dados_suficientes": False,
                "grau_llm": None, "grau_det": grau_det, "fonte_grau": "deterministico_parcial",
                "divergencia": None,
                "resumo": ("A camada DETERMINÍSTICA varreu o texto e não achou cláusula restritiva nem cascata; "
                           f"o parecer interpretativo (IA) não pôde ser gerado agora ({str(e)[:40]}). "
                           "REPROCESSAR com a IA para o veredito completo — não é 'verde' (a análise "
                           "interpretativa está pendente)."),
                "ressalva": "veredito resolvido: pendente de reprocessamento; ausência de red flag "
                            "determinístico ≠ regularidade"}
    dados = _parse_json(raw)
    if not isinstance(dados, dict):
        if det_presenca:
            return _com_fusao({**base, "dados_suficientes": True,
                    "resumo": f"Resposta do LLM não-parseável — veredito pela camada determinística "
                              f"(grau {det_presenca}); indício a verificar.",
                    "ressalva": "veredito objetivo (LLM não-parseável); indício a apurar, não acusação"},
                    None, grau_det)
        return {**base, "grau": "pendente_reprocessar", "dados_suficientes": False,
                "grau_llm": None, "grau_det": grau_det, "fonte_grau": "deterministico_parcial",
                "divergencia": None,
                "resumo": ("A camada DETERMINÍSTICA varreu o texto e não achou cláusula restritiva nem cascata; "
                           "a IA respondeu em formato inválido (não-parseável). REPROCESSAR com a IA para o "
                           "veredito completo — não é 'verde' (a análise interpretativa está pendente)."),
                "ressalva": "veredito resolvido: pendente de reprocessamento; ausência de red flag "
                            "determinístico ≠ regularidade"}
    dados.setdefault("ressalva", "presunção de legitimidade; indício a apurar, não acusação")
    # Fusão do grau do LLM com o determinístico: nenhum alarme silenciado + divergência sinalizada.
    return _com_fusao({**base, **dados}, dados.get("grau"), grau_det)


# ──────────────────────────────────────────────────────────────────────────────
# OBTENÇÃO do edital+ata — "se vira pra conseguir" (dono 2026-07-24)
# Direcionamento EXIGE edital e ata. Um processo de execução/pagamento não os traz, mas CITA o certame-
# lastro (Pregão/ARP). Em vez de fingir veredito sobre a peça errada, o sistema VAI BUSCAR o edital+ata do
# certame e reavalia sobre os documentos reais. Honesto: só reporta lacuna quando a busca genuinamente falha.
# ──────────────────────────────────────────────────────────────────────────────
# tipos (classificador_doc) que compõem a ATA de julgamento (onde mora a cascata) vs. o material do EDITAL.
_TIPOS_ATA = {"ata_rp", "mapa_lances", "homologacao"}


async def obter_edital_ata(texto: str, *, buscar_docs, contexto: dict | None = None) -> dict:
    """Obtém o edital+ata do certame-lastro citado no texto. `buscar_docs`: async(refs, contexto) -> lista
    de docs [{titulo,tipo,texto}] (prod = `_buscar_docs_pncp`; fake no teste). Classifica cada doc e separa
    material de EDITAL de ATA de julgamento. Retorna {obtido, edital_txt, ata_txt, refs, fontes, n_docs}.
    Honesto: obtido=False quando a busca nada retorna (não fabrica)."""
    from compliance_agent.direcionamento_sinais import extrair_certames
    from compliance_agent.sei.classificador_doc import classificar_doc
    refs = extrair_certames(texto or "")
    try:
        docs = await buscar_docs(refs, contexto or {}) or []
    except Exception as e:  # noqa: BLE001 — fetcher injetado pode falhar de qualquer forma: degrada honesto
        logger.debug("obter_edital_ata: busca falhou (refs=%s): %s", refs, e)
        return {"obtido": False, "edital_txt": "", "ata_txt": "", "refs": refs, "erro": str(e)[:80],
                "fontes": [], "n_docs": 0}
    ed_parts, at_parts, fontes = [], [], []
    for d in docs:
        txt = (d.get("texto") or "").strip()
        if not txt:
            continue
        tipo = classificar_doc(d.get("titulo") or d.get("tipo") or "", txt)
        fontes.append({"titulo": d.get("titulo"), "tipo_classificado": tipo})
        (at_parts if tipo in _TIPOS_ATA else ed_parts).append(txt)
    edital_txt, ata_txt = "\n\n".join(ed_parts), "\n\n".join(at_parts)
    return {"obtido": bool(edital_txt.strip() or ata_txt.strip()), "edital_txt": edital_txt,
            "ata_txt": ata_txt, "refs": refs, "fontes": fontes, "n_docs": len(fontes)}


async def _buscar_docs_pncp(refs: dict, contexto: dict) -> list[dict]:
    """Fetcher REAL (default): resolve o certame no PNCP e baixa os documentos (edital/TR/ata). Best-effort e
    honesto (retorna [] quando não acha). Usa `id_pncp` do contexto se houver; senão busca por órgão/UF e
    casa pelo nº do pregão referenciado. Sem login (API pública)."""
    from compliance_agent.collectors import pncp
    id_pncp = (contexto or {}).get("id_pncp")
    if id_pncp:
        return await pncp.baixar_documentos(id_pncp, max_arquivos=6)
    # sem id direto: busca contratações do órgão/UF e casa pelo nº do pregão citado
    pregoes = (refs or {}).get("pregoes") or []
    if not pregoes:
        return []
    from datetime import date, timedelta
    uf = (contexto or {}).get("uf", "RJ")
    orgao = (contexto or {}).get("orgao_cnpj") or (contexto or {}).get("cnpj_orgao")
    hoje = date.today()
    # buscar_contratacoes degrada internamente (retorna [] em erro de rede) — sem except redundante aqui.
    cs = await pncp.buscar_contratacoes(uf=uf, data_ini=hoje - timedelta(days=1460), data_fim=hoje,
                                        orgao_cnpj=orgao, max_paginas=2)
    alvos = {re.sub(r"\D", "", p) for p in pregoes if p}
    for c in cs or []:
        num = re.sub(r"\D", "", str(c.get("numero") or c.get("objeto") or ""))
        if any(a and a in num for a in alvos) and c.get("id_pncp"):
            docs = await pncp.baixar_documentos(c["id_pncp"], max_arquivos=6)
            if docs:
                return docs
    return []


async def avaliar_direcionamento_resolvido(texto: str = "", *, contexto: dict | None = None, gerar=None,
                                           buscar_docs=None) -> dict:
    """Avalia direcionamento e, se o texto NÃO for edital/ata, VAI BUSCAR o edital+ata do certame-lastro e
    reavalia sobre os documentos reais — em vez de dar um veredito sobre a peça errada. `buscar_docs`
    injetável (default = PNCP). Só reporta lacuna ('edital_ata_nao_obtido') quando a obtenção falha de
    verdade, dizendo o que tentou. Honesto: sem edital+ata não se afirma direcionamento."""
    from compliance_agent.direcionamento_sinais import extrair_certames
    sig = presinais(texto)
    refs = extrair_certames(texto or "")
    # gatilho de busca: NÃO temos a ata (sem cascata visível) MAS o texto CITA um certame → obter o real.
    precisa_buscar = (not sig["tem_ata"]) and refs.get("n_refs", 0) >= 1
    if not precisa_buscar:
        return await avaliar_direcionamento(edital_txt=texto, contexto=contexto, gerar=gerar)
    fetch = buscar_docs or _buscar_docs_pncp
    obt = await obter_edital_ata(texto, buscar_docs=fetch, contexto=contexto)
    if obt.get("obtido"):
        res2 = await avaliar_direcionamento(edital_txt=obt["edital_txt"], ata_txt=obt["ata_txt"],
                                            contexto=contexto, gerar=gerar)
        res2["obtencao"] = {k: obt.get(k) for k in ("refs", "fontes", "n_docs")}
        res2["_nota_obtencao"] = ("edital/ata OBTIDOS do certame-lastro citado no processo e analisados "
                                  "sobre os documentos reais")
        return res2
    # honesto: tentou obter e não conseguiu — reporta a lacuna, não maquia (mantém o scan do que existe)
    base_res = await avaliar_direcionamento(edital_txt=texto, contexto=contexto, gerar=gerar)
    return {**base_res, "grau": "edital_ata_nao_obtido", "dados_suficientes": False,
            "obtencao": {"refs": refs, "erro": obt.get("erro"), "n_docs": obt.get("n_docs", 0)},
            "resumo": ("Falta a ATA de julgamento (a cascata) e o veredito de direcionamento a exige. Tentei "
                       f"obter o edital+ata do certame-lastro citado (refs: {refs}), mas a busca não retornou "
                       "os documentos. Sem eles NÃO há veredito honesto — coletar o processo licitatório "
                       "(PNCP/SEI) e reavaliar."),
            "ressalva": "honesto: sem edital+ata não se afirma nem se descarta direcionamento (a peça é indispensável)"}


def _parse_json(raw: str):
    """Extrai o 1º objeto JSON do texto do LLM (tolera cercas/lixo ao redor)."""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):  # tira cercas markdown (```json ... ```)
        s = re.sub(r"^```[a-z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.debug("resposta do LLM não é JSON válido: %s", exc)
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None


_PARAMS_AUDITOR = (
    "*Parâmetros de direcionamento (TCU/TCE-RJ/ACFE):*\n"
    "• Atestado de capacidade técnica restritivo (idêntico ao objeto; prazo/local específico; quantitativo "
    "desproporcional; *vedação de somatório* sem justificativa — Súmula TCU 263).\n"
    "• Exigência de marca/modelo ou certificações sem comprovar essencialidade.\n"
    "• Cascata: muitas desclassificações/inabilitações pelo MESMO motivo; vencedor longe do menor preço que "
    "sobe após quedas dos mais baratos por tecnicalidade.\n"
    "• Contrato grande + poucas empresas habilitadas = sinal."
)


def montar_pacote_claude(contratacao: dict, resultado: dict, trecho_doc: str = "", max_trecho: int = 1500) -> str:
    """Pacote MASTIGADO p/ o Mestre Jorge enviar ao Claude do celular: contratação + parâmetros + os
    TRECHOS do documento + o parecer do GEMINI + a pergunta para o Claude PENSAR EM CIMA do Gemini.
    Markdown pronto para copiar/encaminhar. Honesto: tudo indício a verificar, não acusação."""
    obj = (contratacao.get("objeto") or "")[:160]
    val = contratacao.get("valor")
    org = contratacao.get("orgao") or contratacao.get("unidade") or "?"
    link = contratacao.get("link") or f"https://pncp.gov.br/app/editais?q={contratacao.get('id_pncp','')}"
    ex = resultado.get("exigencias_restritivas") or []
    casc = resultado.get("cascata") or []
    sig = resultado.get("presinais") or {}
    linhas = [
        "🧠 *AVALIAÇÃO DE DIRECIONAMENTO — peça ao Claude pensar em cima do Gemini*",
        f"*Contratação:* {obj}",
        f"*Órgão:* {org} · *Valor:* {('R$ %s' % f'{val:,.2f}'.replace(',','.')) if val else '?'}",
        f"*PNCP:* {link}",
        f"*Id:* `{contratacao.get('id_pncp','?')}`",
        "",
        _PARAMS_AUDITOR,
        "",
        f"*Sinais objetivos (contagem na ata):* desclass={sig.get('n_desclassificacoes',0)} · "
        f"inabilit={sig.get('n_inabilitacoes',0)} · atestado={sig.get('mencoes_atestado',0)} · "
        f"ata_presente={sig.get('tem_ata',False)}",
        "",
        "📄 *Trecho do documento (fonte para conferir):*",
        "```",
        (trecho_doc or "(não anexado — ver link PNCP)")[:max_trecho],
        "```",
        "",
        "🤖 *PARECER DO GEMINI:*",
        f"*Grau CONCILIADO (objetivo+subjetivo):* {str(resultado.get('grau','?')).upper()} · "
        f"dados_suficientes: {resultado.get('dados_suficientes')}",
        f"*Resumo:* {resultado.get('resumo','')}",
        f"*Raciocínio do Gemini:* {resultado.get('raciocinio','(não informado)')}",
    ]
    # DIVERGÊNCIA entre a camada subjetiva (LLM) e a objetiva (determinística) — gatilho de análise
    # crítica: quando discordam, o auditor precisa saber qual foi mais severa e por quê.
    div = resultado.get("divergencia")
    if div:
        linhas += [
            "",
            f"⚠️ *DIVERGÊNCIA entre camadas* — LLM disse *{str(resultado.get('grau_llm','?')).upper()}*, "
            f"determinístico *{str(resultado.get('grau_det','?')).upper()}*; "
            f"prevaleceu a camada *{div.get('camada_mais_severa','?')}* (mais severa, não silenciar alarme).",
            f"  {div.get('nota','')}",
        ]
    if ex:
        linhas.append("*Exigências que o Gemini achou restritivas:*")
        for e in ex[:5]:
            linhas.append(f"  • {(e.get('por_que_restringe') or '')[:120]} _(juris: {e.get('jurisprudencia','—')})_")
            linhas.append(f"    trecho: “{(e.get('trecho') or '')[:120]}”")
    if casc:
        linhas.append("*Cascata que o Gemini leu:*")
        for x in casc[:6]:
            linhas.append(f"  • {x.get('situacao','?')} (ordem preço {x.get('ordem_preco','?')}): {(x.get('motivo') or '')[:80]}")
    linhas += [
        "",
        "❓ *PERGUNTA PARA VOCÊ, CLAUDE (julgue o Gemini):*",
        "1. Você concorda com o GRAU do Gemini? Por quê? "
        "2. O raciocínio dele está correto/honesto, ou ele errou/exagerou/passou batido em algo? "
        "3. Olhando os trechos e os parâmetros, há red flag de direcionamento que o Gemini PERDEU? "
        "4. Dê o SEU parecer (grau + justificativa + o que pediria de diligência). "
        "Regra: indício a verificar, NUNCA acusação (presunção de legitimidade).",
    ]
    return "\n".join(linhas)


def avaliar_sync(edital_txt: str = "", ata_txt: str = "", *, contexto: dict | None = None, gerar=None) -> dict:
    """Wrapper síncrono (p/ chamadores não-async)."""
    import asyncio
    return asyncio.run(avaliar_direcionamento(edital_txt, ata_txt, contexto=contexto, gerar=gerar))
