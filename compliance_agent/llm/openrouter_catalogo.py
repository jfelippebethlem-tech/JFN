# -*- coding: utf-8 -*-
"""openrouter_catalogo — descobre os modelos `:free` VIVOS em vez de confiar em literal.

POR QUE ESTE MÓDULO EXISTE. O OpenRouter aposenta e substitui os modelos `:free` o tempo todo.
Medido em 2026-07-28: dos 6 ids fixados no código, **5 estavam mortos** —
`meta-llama/llama-3.3-70b-instruct:free` (o FAST), `nousresearch/hermes-3-llama-3.1-405b:free`
(o SMART), `qwen/qwen3-coder:free`, `qwen/qwen3-next-80b-a3b-instruct:free` e
`deepseek/deepseek-r1:free`. O sintoma era um 404 que o retry tratava como erro transitório:
33 segundos de backoff por chamada, e o degrau simplesmente não existia mais na cadeia.

Trocar o literal por outro literal só reinicia o cronômetro da mesma falha. Aqui a escolha
passa a vir do catálogo vivo, por CAPACIDADE, e o código não conhece nome de modelo nenhum.

DESENHO
  · `catalogo()` busca `/models`, filtra `:free` e guarda em `data/openrouter_free.json`.
  · TTL curto (6 h) porque a lista muda rápido; o refresh é um GET barato.
  · Catálogo inalcançável ⇒ usa o cache ANTIGO. Um catálogo velho é muito melhor que nenhum;
    o que não se faz é voltar ao literal, que é justamente o que apodrece.
  · Sem cache e sem rede ⇒ devolve `None`, e quem chama pula o provedor. `None` aqui é
    "não sei", não "não existe" — o provedor não é declarado morto por falta de informação.
  · `marcar_morto()` registra o id que respondeu 404 para a próxima escolha já o evitar,
    sem esperar o TTL. É o feedback do mundo real para dentro do catálogo.

A escolha é por PERFIL, não por nome:
  fast      — resposta curta e limpa, para rubrica fechada em volume;
  documento — LEITURA E ANÁLISE de peça processual; exige modelo forte (ver abaixo);
  smart     — maior capacidade, para síntese;
  coder     — geração de código;
  visao     — aceita imagem na entrada.

CAPACIDADE ≠ CONTEXTO. Esta é a lição que separa `fast` de `documento`. Um modelo de 26B com
262k de contexto lê o processo inteiro e o interpreta mal; janela grande diz quanto texto cabe,
não quanto o modelo entende. Por isso a nota de capacidade vem do **tamanho de parâmetros
lido do próprio id** (`550b`, `120b`, `31b`…), com o contexto entrando só como desempate — e
`documento` impõe um PISO de parâmetros, abaixo do qual o modelo é inelegível por mais folgada
que seja a janela. Onde houver medição real disponível (`data/modelos_ranking.json`, produzido
por `tools/bench_modelos.py`), ela tem precedência sobre qualquer heurística: nota medida no
nosso próprio domínio vale mais que tamanho declarado.

Modelos que expõem cadeia de raciocínio (`reasoning` no id) ficam fora de `fast`: medido em
2026-07-28, `nvidia/nemotron-3-nano-30b-a3b:free` respondeu à pergunta "responda somente OK"
com o próprio monólogo interno, o que quebra rubrica fechada. Em `documento` eles são
aceitos — ali o raciocínio ajuda e a saída é prosa, não rótulo de escala.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import time

logger = logging.getLogger(__name__)

URL = "https://openrouter.ai/api/v1/models"
CACHE = pathlib.Path(os.environ.get(
    "JFN_OPENROUTER_CACHE",
    str(pathlib.Path(__file__).resolve().parents[2] / "data" / "openrouter_free.json")))
TTL_S = int(os.environ.get("JFN_OPENROUTER_TTL", str(6 * 3600)))
RANKING = pathlib.Path(os.environ.get(
    "JFN_MODELOS_RANKING",
    str(pathlib.Path(__file__).resolve().parents[2] / "data" / "modelos_ranking.json")))

# Nunca servem como modelo de chat, mesmo sendo `:free`.
_NUNCA = ("content-safety", "embed", "whisper", "moderation", "rerank")


def _agora() -> float:
    return time.time()


def _ler_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _gravar_cache(dados: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(dados, ensure_ascii=False))
    except OSError as e:  # noqa: BLE001 — cache é otimização, nunca derruba a cadeia
        logger.warning("catálogo OpenRouter: não gravei o cache (%s)", e)


def _buscar() -> list[dict] | None:
    """GET no catálogo. `None` = não deu para saber (sem chave, sem rede, erro)."""
    chave = os.environ.get("OPENROUTER_API_KEY", "")
    if not chave:
        return None
    try:
        import httpx
        r = httpx.get(URL, headers={"Authorization": f"Bearer {chave}"}, timeout=30)
        r.raise_for_status()
        dados = r.json().get("data") or []
    except Exception as e:  # noqa: BLE001 — catálogo fora do ar não pode quebrar quem chama
        logger.warning("catálogo OpenRouter indisponível (%s)", str(e)[:100])
        return None
    return [
        {
            "id": m.get("id", ""),
            "ctx": int(m.get("context_length") or 0),
            "modalidades": list((m.get("architecture") or {}).get("input_modalities") or []),
        }
        for m in dados
        if str(m.get("id", "")).endswith(":free")
    ]


def catalogo(*, forcar: bool = False) -> list[dict]:
    """Modelos `:free` vivos. Cache com TTL; catálogo fora do ar cai no cache antigo."""
    cache = _ler_cache()
    fresco = (not forcar
              and cache.get("modelos")
              and (_agora() - float(cache.get("ts") or 0)) < TTL_S)
    if fresco:
        return list(cache["modelos"])

    novos = _buscar()
    if novos is None:
        if cache.get("modelos"):
            idade_h = (_agora() - float(cache.get("ts") or 0)) / 3600
            logger.info("catálogo OpenRouter: usando cache de %.1f h atrás", idade_h)
            return list(cache["modelos"])
        return []
    _gravar_cache({"ts": _agora(), "modelos": novos, "mortos": cache.get("mortos", {})})
    return novos


def marcar_morto(model_id: str, *, motivo: str = "404") -> None:
    """Um 404 no uso real é a informação mais confiável que existe — registra e evita."""
    cache = _ler_cache()
    mortos = cache.get("mortos") or {}
    mortos[model_id] = {"ts": _agora(), "motivo": motivo}
    cache["mortos"] = mortos
    _gravar_cache(cache)
    logger.warning("modelo %s marcado como morto (%s)", model_id, motivo)


def _mortos_recentes() -> set[str]:
    """Esquece o óbito depois de um TTL: modelo pode voltar, e não queremos banir para sempre."""
    mortos = (_ler_cache().get("mortos") or {})
    return {mid for mid, d in mortos.items()
            if (_agora() - float(d.get("ts") or 0)) < TTL_S}


_RE_PARAMS = re.compile(r"(?<![a-z0-9.])(\d{1,4}(?:\.\d)?)\s*b(?![a-z0-9])")

# Piso de parâmetros para análise de peça processual. Abaixo disto o modelo lê o documento e
# erra a leitura — é a diferença entre "coube na janela" e "entendeu o que leu".
PISO_PARAMS_DOCUMENTO = 100.0

PERFIS = ("fast", "documento", "smart", "coder", "visao")


def _params_b(model_id: str) -> float:
    """Bilhões de parâmetros lidos do id. 0.0 quando o id não declara.

    Em MoE (`nemotron-3-ultra-550b-a55b`) o primeiro número é o total e o segundo os ativos;
    fica-se com o TOTAL, que é o que se correlaciona com conhecimento armazenado.
    """
    achados = [float(x) for x in _RE_PARAMS.findall(model_id.lower())]
    return max(achados) if achados else 0.0


# Cada perfil se importa com provas diferentes. Medido em 2026-07-28 e é o ponto todo:
# `cohere/north-mini-code` tira 100 nas provas curtas e **0** em documento longo; o
# `nemotron-3-super-120b` faz o mesmo. Uma nota agregada os promoveria para `documento` (onde
# falham) ou os eliminaria de `fast` (onde são bons). A pergunta "qual o melhor modelo" não tem
# resposta única — tem uma por tarefa.
_PROVAS_DO_PERFIL = {
    "documento": ("documento_longo",),
    "smart": ("documento_longo", "vicio", "ausencia"),
    "fast": ("rubrica", "ausencia", "extracao"),
    "coder": ("extracao", "rubrica"),
    "visao": ("extracao", "ausencia"),
}


def _nota_medida(model_id: str, perfil: str = "") -> float | None:
    """Nota do banco de provas para o PERFIL pedido. `None` quando não há medição aplicável.

    Sem perfil (ou perfil desconhecido), devolve a nota agregada — compatível com quem já
    chamava assim.
    """
    provas = _PROVAS_DO_PERFIL.get(perfil)
    if not provas:
        return (_ranking() or {}).get(model_id)
    det = (_detalhe() or {}).get(model_id) or {}
    notas = [det[p]["nota"] for p in provas
             if isinstance(det.get(p), dict) and det[p].get("nota") is not None]
    return round(sum(notas) / len(notas), 1) if notas else None


def _detalhe() -> dict:
    try:
        return json.loads(RANKING.read_text()).get("detalhe") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _ranking() -> dict:
    try:
        dados = json.loads(RANKING.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: float(v) for k, v in (dados.get("notas") or {}).items()}


def _pontuar(m: dict, perfil: str) -> float | None:
    """Nota do modelo para o perfil. `None` = inelegível."""
    mid = m["id"].lower()
    if any(t in mid for t in _NUNCA):
        return None
    modalidades = [x.lower() for x in m.get("modalidades") or []]
    ctx = float(m.get("ctx") or 0)
    params = _params_b(mid)

    if perfil == "visao":
        if "image" not in modalidades:
            return None
        return params * 1000 + ctx

    if perfil == "fast" and "reasoning" in mid:
        return None                       # vaza monólogo interno; quebra rubrica fechada

    if perfil == "coder":
        # Prefere modelo declaradamente de código; um generalista grande serve de reserva.
        return (params * 1000 + ctx) * (10.0 if "code" in mid else 1.0)

    if perfil == "documento":
        if params and params < PISO_PARAMS_DOCUMENTO:
            return None                   # capacidade insuficiente para ler peça processual
        if not params:
            return None                   # id que não declara tamanho não entra por suposição
        medida = _nota_medida(m["id"])
        if medida is not None:
            return 1_000_000 + medida     # medido supera qualquer estimativa de tamanho
        return params * 1000 + ctx / 1000

    if perfil == "smart":
        medida = _nota_medida(m["id"], perfil)
        if medida is not None:
            return 1_000_000 + medida
        return params * 1000 + ctx / 1000

    # fast: rubrica fechada em volume. Como toda a lista é grátis, não há motivo para preferir
    # o modelo mais fraco — o que se exige é saída limpa (daí a exclusão dos `reasoning`).
    # A medição, quando existir, decide; sem ela, tamanho com o contexto de desempate.
    medida = _nota_medida(m["id"], perfil)
    if medida is not None:
        return 1_000_000 + medida
    return params * 1000 + ctx / 1000


def escolher(perfil: str = "fast", *, forcar: bool = False) -> str | None:
    """Melhor id `:free` vivo para o perfil, ou `None` quando não dá para saber.

    `None` nunca significa "não existe modelo" — significa "não consegui o catálogo". Quem
    chama deve pular o provedor, não declará-lo morto.
    """
    if perfil not in PERFIS:
        raise ValueError(f"perfil inválido: {perfil!r}")
    mortos = _mortos_recentes()
    candidatos = []
    for m in catalogo(forcar=forcar):
        if m["id"] in mortos:
            continue
        nota = _pontuar(m, perfil)
        if nota is not None:
            candidatos.append((nota, m["id"]))
    if not candidatos:
        return None
    # Desempate pelo id para a escolha ser estável entre execuções (log comparável).
    return sorted(candidatos, key=lambda x: (-x[0], x[1]))[0][1]


def resumo() -> dict:
    """Diagnóstico para o operador."""
    cache = _ler_cache()
    modelos = catalogo()
    return {
        "n_free": len(modelos),
        "cache": str(CACHE),
        "idade_h": round((_agora() - float(cache.get("ts") or 0)) / 3600, 2)
        if cache.get("ts") else None,
        "mortos_lembrados": sorted(_mortos_recentes()),
        "escolha": {p: escolher(p) for p in PERFIS},
        "notas_medidas": _ranking(),
    }
