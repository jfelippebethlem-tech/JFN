# -*- coding: utf-8 -*-
"""E15 `materializar:<visao>` — visões do painel materializadas quando a fonte suja (plano mestre v2 §3.2 E15, §8
"Dados e visões"; O7.1).

Antes: o painel CALCULAVA em request (conflito 24–200 s, certames 6–60 s, panorama 19–32 s) e escondia o custo com TTL
de 1 h + o `tools/prewarm_painel.sh` (52 URLs a cada 30 min). Agora cada visão migrada é um ARQUIVO pronto:

  data/visoes/<visao>.json        o corpo EXATO que a rota devolvia (bytes; a paridade é por construção e o teste
                                  confere byte a byte)
  data/visoes/<visao>.meta.json   gerado_em, fonte, universo, cobertura, slo_s, sha256 do corpo, segundos, versão

e a rota só LÊ (`resposta`). Quem escreve é este estágio, num processo-filho do fluxo (nunca o painel): chama a função
LEGADA da rota (`_api_*_legado`, o corpo de antes, intocado) com os caches em memória do processo ZERADOS — o cálculo
é sempre fresco, nunca um TTL velho — e grava o corpo + metadados (troca atômica: corpo e meta por `replace`).

handler(payload, ctx) — chave do job = a visão (`payload.visao` ou o sufixo de `materializar:<visao>`); idempotente:
recalcular a mesma fonte regrava o mesmo corpo (sha256 igual), com `gerado_em` novo.
efeito(payload, ctx, resultado) — em OUTRO processo relê o disco: meta presente, sha256 do corpo no disco = meta =
declarado, `gerado_em` = declarado, corpo é JSON sem erro (`ok` ≠ False) e o universo recontado do corpo = meta.

Frescor (sensor da E18, grupo `visoes` em fluxo/sensores.py): `g_visoes` mede a idade de cada visão contra o SLO dela
(`visoes.idade_s`, detalhe) e o agregado `visoes.atrasadas` (atrasada + nunca materializada; SLO `visoes_frescor` em
config/slos.yaml). Visão ausente NÃO é fresca nem zero: é INDISPONÍVEL e entra na conta das atrasadas.

Rota cuja visão não existe (ainda não materializada, ou teste com RAIZ redirecionado) cai no caminho LEGADO — o mesmo
código de antes, com o TTL dele — e responde com `X-JFN-Visao: ausente`: degradado declarado, nunca quebra.

CLI:
    python -m compliance_agent.aplicacao.estagios.materializar rodar --visao conflito [--visao siafe_stats ...]
    python -m compliance_agent.aplicacao.estagios.materializar rodar --todas
    python -m compliance_agent.aplicacao.estagios.materializar estado                 # frescor por visão, JSON
    python -m compliance_agent.aplicacao.estagios.materializar paridade --visao conflito [--base http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import inspect
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.fluxo.fila import Resultado

RAIZ = Path(__file__).resolve().parents[3]
ENV_DIR = "JFN_VISOES_DIR"
VERSAO = "e15.v1"


@dataclass(frozen=True)
class Visao:
    """Uma visão materializada = UMA chamada da rota, com os parâmetros que o painel pede."""
    nome: str
    rota: str                       # caminho + query exatamente como o painel (e o prewarm) pedia
    legado: str                     # "modulo:funcao" — o corpo antigo da rota, que devolve Response
    kwargs: dict = field(default_factory=dict)
    caches: tuple[str, ...] = ("rotas.investigacao:_cache",)   # dicts em memória zerados antes do cálculo
    fontes: tuple[str, ...] = ()    # eventos do config/fluxo.yaml que sujam a visão
    dados: str = ""                 # tabelas/bancos lidos (proveniência no meta)
    universo: str | None = None     # campo do corpo que conta o universo ("n", "len:rede", "resumo.total")
    cobertura: str | None = None    # campo do corpo com a cobertura declarada pela própria rota
    slo_s: int = 7200               # idade máxima aceitável (frescor)


_INV = "rotas.investigacao"
_TODAS = ("codigo_commit",)         # código novo da rota/detector muda a visão em qualquer caso

VISOES: dict[str, Visao] = {v.nome: v for v in (
    Visao("conflito", "/api/conflito", f"{_INV}:_api_conflito_legado",
          {"cnpj": "", "candidato": "", "limite": 200},
          fontes=("siafe_ob", "siafe_status", "contratos_tcerj") + _TODAS,
          dados="doacoes_eleitorais (TSE) × socios_fornecedor (QSA) × OB (compliance.db)",
          universo="len:rede", slo_s=21600),
    Visao("compliance_painel", "/api/compliance/painel", f"{_INV}:_api_painel_legado",
          fontes=("siafe_ob", "siafe_status", "triagem", "revisao_humana", "memoria_claude") + _TODAS,
          dados="ob_orcamentaria_siafe (régua _ob_paga) + ordens_bancarias (TFE, só confronto) + alertas + memória",
          universo="obs.total", slo_s=3600),
    Visao("compliance_graph", "/api/compliance/graph", f"{_INV}:_api_compliance_graph_legado",
          fontes=("siafe_ob", "siafe_status") + _TODAS,
          dados="ob_orcamentaria_siafe (régua _ob_paga, 2021+) + verificacao_sede",
          universo="len:nodes", slo_s=7200),
    Visao("certames_prefeitura", "/api/certames/lista?esfera=prefeitura&limite=600",
          f"{_INV}:_api_certames_lista_legado", {"esfera": "prefeitura", "limite": 600, "q": ""}, caches=(),
          fontes=("contratos_tcerj", "pcrj_base", "regra_detectores") + _TODAS,
          dados="edital_documento × certame_indice × orgao_esfera (compliance.db)",
          universo="resumo.total", cobertura="resumo.analisados", slo_s=21600),
    Visao("certames_estado", "/api/certames/lista?esfera=estado&limite=600",
          f"{_INV}:_api_certames_lista_legado", {"esfera": "estado", "limite": 600, "q": ""}, caches=(),
          fontes=("contratos_tcerj", "regra_detectores") + _TODAS,
          dados="edital_documento × certame_indice × orgao_esfera (compliance.db)",
          universo="resumo.total", cobertura="resumo.analisados", slo_s=21600),
    Visao("fontes_frescor", "/api/fontes/frescor", f"{_INV}:_api_fontes_frescor_legado",
          fontes=("siafe_ob", "sancoes", "pcrj_base", "contratos_tcerj") + _TODAS,
          dados="MAX(coletado_em) de cada fonte (compliance.db, pcrj.db) + folhas",
          universo="len:fontes", slo_s=3600),
    Visao("coendereco_clusters", "/api/coendereco/clusters", f"{_INV}:_api_coendereco_clusters_legado",
          {"min_forn": 2, "top": 50}, caches=(),
          fontes=("siafe_ob",) + _TODAS,
          dados="endereços ingeridos dos fornecedores × OB (compliance.db)",
          universo="dados.n_clusters", slo_s=21600),
    Visao("siafe_stats", "/api/siafe/stats", "rotas.sistema:_calc_siafe_stats", caches=("rotas.sistema:_stats_cache",),
          fontes=("siafe_ob", "siafe_status", "siafe_gd") + _TODAS,
          dados="ob_orcamentaria_siafe (contagens e régua _ob_paga)",
          universo="total", slo_s=3600),
    Visao("pncp_conluio_estado", "/api/pncp/conluio?esfera=estado", f"{_INV}:_api_pncp_conluio_legado",
          {"min_certames": 4, "esfera": "estado"},
          fontes=("contratos_tcerj", "tcerj_licitante") + _TODAS,
          dados="pncp_resultado × pncp_ente (esfera oficial)",
          universo="n_orgaos", cobertura="cobertura", slo_s=21600),
    Visao("acervo_estatisticas", "/api/acervo/estatisticas", "rotas.acervo:_api_acervo_estatisticas_legado",
          caches=("rotas.acervo:_EST",),
          fontes=("siafe_ob", "sei_arquivado", "sei_lote", "sei_ficha") + _TODAS,
          dados="acervo SEI + compliance.db (count DISTINCT no SIAFE)",
          universo=None, slo_s=7200),
)}


def _visoes_de_lente() -> dict[str, Visao]:
    """O7.2: uma visão por lente de config/lentes.yaml (`lente_<nome>`, rota `/api/esteira/lente?lente=<nome>`). Só os
    NOMES saem do YAML aqui (a validação completa é do cálculo, `lentes.carregar`): lente nova = visão nova."""
    import yaml
    nomes = (yaml.safe_load((RAIZ / "config" / "lentes.yaml").read_text(encoding="utf-8")) or {}).get("lentes") or {}
    return {f"lente_{n}": Visao(f"lente_{n}", f"/api/esteira/lente?lente={n}",
                                "compliance_agent.aplicacao.lentes_resumo:resposta", {"lente": n}, caches=(),
                                fontes=("siafe_ob", "siafe_status", "contratos_tcerj", "pcrj_base") + _TODAS,
                                dados="ob_orcamentaria_siafe (_ob_paga) | contasrio_contrato | emendas, recortados "
                                      "pela lente (config/lentes.yaml) + achados.db",
                                universo="universo.n", slo_s=21600) for n in nomes}


VISOES.update(_visoes_de_lente())


# ── armazenamento (o que a rota lê) ─────────────────────────────────────────────────────────────────────────────────
def diretorio(raiz: Path | str | None = None) -> Path:
    """`JFN_VISOES_DIR` ou `<raiz>/data/visoes`. A rota passa o SEU `RAIZ` (lido na chamada): teste que redireciona a
    raiz não enxerga as visões de produção."""
    if os.environ.get(ENV_DIR):
        return Path(os.environ[ENV_DIR])
    return Path(raiz or RAIZ) / "data" / "visoes"


def _arquivos(nome: str, raiz=None) -> tuple[Path, Path]:
    d = diretorio(raiz)
    return d / f"{nome}.json", d / f"{nome}.meta.json"


def sha256(corpo: bytes) -> str:
    return hashlib.sha256(corpo).hexdigest()


def _campo(payload, caminho: str | None):
    """`len:x.y` = tamanho da lista; `x.y` = valor numérico. Ausente → None (INDISPONÍVEL, nunca 0)."""
    if not caminho or not isinstance(payload, dict):
        return None
    conta = caminho.startswith("len:")
    v = payload
    for parte in caminho.removeprefix("len:").split("."):
        if not isinstance(v, dict) or parte not in v:
            return None
        v = v[parte]
    if conta:
        return len(v) if isinstance(v, (list, dict)) else None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def gravar(v: Visao, corpo: bytes, payload, segundos: float, raiz=None) -> dict:
    """Corpo e meta por troca atômica (tmp + replace). O meta vai DEPOIS: quem lê meta novo acha o corpo novo."""
    arq, arq_meta = _arquivos(v.nome, raiz)
    arq.parent.mkdir(parents=True, exist_ok=True)
    agora = time.time()
    meta = {"visao": v.nome, "rota": v.rota, "versao": VERSAO, "gerado_em": _iso(agora), "gerado_em_epoch": agora,
            "fonte": v.dados, "fontes_evento": list(v.fontes),
            "universo": _campo(payload, v.universo), "universo_campo": v.universo,
            "cobertura": _campo(payload, v.cobertura) if v.cobertura else None, "cobertura_campo": v.cobertura,
            "slo_s": v.slo_s, "sha256": sha256(corpo), "bytes": len(corpo), "segundos": round(segundos, 2)}
    if meta["universo"] is None:
        meta["universo_estado"] = "INDISPONIVEL" if v.universo else "NAO_DECLARADO"
    tmp = arq.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(corpo)
    tmp.replace(arq)
    tmpm = arq_meta.with_suffix(f".{os.getpid()}.tmp")
    tmpm.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    tmpm.replace(arq_meta)
    return meta


def ler_meta(nome: str, raiz=None) -> dict | None:
    _, arq_meta = _arquivos(nome, raiz)
    try:
        return json.loads(arq_meta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def ler(nome: str, raiz=None) -> tuple[bytes, dict] | None:
    """(corpo, meta) com o sha256 conferido. Corrida com a gravação (meta de um, corpo de outro): relê uma vez; se ainda
    divergir, devolve None e a rota cai no legado (melhor lento que número de outra geração)."""
    arq, _ = _arquivos(nome, raiz)
    for _tentativa in range(2):
        meta = ler_meta(nome, raiz)
        if meta is None:
            return None
        try:
            corpo = arq.read_bytes()
        except FileNotFoundError:
            return None
        if sha256(corpo) == meta.get("sha256"):
            return corpo, meta
    return None


def resposta(nome: str, raiz=None):
    """Response pronta da visão (bytes exatos + cabeçalhos de frescor) ou None (visão ausente → a rota usa o legado)."""
    lido = ler(nome, raiz)
    if lido is None:
        return None
    from starlette.responses import Response
    corpo, meta = lido
    return Response(content=corpo, media_type="application/json",
                    headers={"X-JFN-Visao": nome, "X-JFN-Visao-Gerado-Em": str(meta.get("gerado_em")),
                             "X-JFN-Visao-SLO-S": str(meta.get("slo_s"))})


def marcar_ausente(resp, nome: str):
    """Cabeçalho do caminho legado: a visão não existe e a rota calculou (degradado declarado)."""
    resp.headers["X-JFN-Visao"] = f"ausente:{nome}"
    return resp


# ── cálculo (só no processo-filho, nunca no painel) ────────────────────────────────────────────────────────────────
def _resolver(alvo: str):
    mod, nome = alvo.split(":", 1)
    return getattr(importlib.import_module(mod), nome)


def _isolar_caches() -> None:
    """O processo do materializador não escreve no cache de disco do painel (data/cache_painel): o `_cache_put` dos
    legados cai numa pasta própria — senão dois processos disputariam o mesmo arquivo temporário."""
    inv = importlib.import_module(_INV)
    inv._CACHE_DIR = diretorio() / "_cache_materializador"


def calcular(v: Visao) -> tuple[bytes, object, float]:
    """(corpo, payload, segundos) da função legada, com os caches em memória zerados (cálculo fresco). Resposta que
    não é 200 ou que declara erro NÃO vira visão: levanta e o fluxo tenta de novo — a visão anterior fica."""
    _isolar_caches()
    for alvo in v.caches:
        _resolver(alvo).clear()
    fn = _resolver(v.legado)
    t0 = time.monotonic()
    resp = fn(**v.kwargs)
    if inspect.iscoroutine(resp):
        resp = asyncio.run(resp)
    seg = time.monotonic() - t0
    status = getattr(resp, "status_code", None)
    if status != 200:
        raise RuntimeError(f"{v.nome}: a rota legada devolveu HTTP {status} — visão anterior mantida")
    corpo = bytes(resp.body)
    payload = json.loads(corpo)
    if isinstance(payload, dict) and (payload.get("ok") is False or "error" in payload):
        raise RuntimeError(f"{v.nome}: a rota legada declarou erro ({str(payload.get('erro') or payload.get('error'))[:200]})")
    return corpo, payload, seg


# ── estágio (contrato do §3.2) ──────────────────────────────────────────────────────────────────────────────────────
def _visao(payload: dict, ctx: Contexto | None = None) -> Visao:
    nome = payload.get("visao") or (ctx.tipo.split(":", 1)[1] if ctx and ":" in ctx.tipo else "")
    if nome not in VISOES:
        raise ErroPermanente(f"visão E15 inválida: {nome!r} (válidas: {', '.join(sorted(VISOES))})")
    return VISOES[nome]


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    v = _visao(payload, ctx)
    corpo, conteudo, seg = calcular(v)
    meta = gravar(v, corpo, conteudo, seg)
    return Resultado(efeito={"visao": v.nome, "sha256": meta["sha256"], "gerado_em": meta["gerado_em"],
                             "universo": meta["universo"], "bytes": meta["bytes"], "segundos": meta["segundos"]},
                     eventos=[{"fonte": "materializar", "tipo": "visao", "chave": v.nome}])


def conferir(nome: str, declarado: dict, raiz=None) -> dict:
    """Relê o disco, sem confiar no handler. Devolve {ok, motivos}."""
    motivos = []
    meta = ler_meta(nome, raiz)
    arq, _ = _arquivos(nome, raiz)
    if meta is None or not arq.exists():
        return {"ok": False, "motivos": ["visão ausente no disco"]}
    corpo = arq.read_bytes()
    h = sha256(corpo)
    if h != meta.get("sha256") or h != declarado.get("sha256"):
        motivos.append("sha256 do corpo no disco ≠ meta/declarado")
    if meta.get("gerado_em") != declarado.get("gerado_em"):
        motivos.append("gerado_em do disco ≠ declarado (outra gravação passou por cima)")
    try:
        conteudo = json.loads(corpo)
    except ValueError:
        return {"ok": False, "motivos": motivos + ["corpo não é JSON"]}
    if isinstance(conteudo, dict) and (conteudo.get("ok") is False or "error" in conteudo):
        motivos.append("corpo declara erro")
    v = VISOES.get(nome)
    if v is not None and _campo(conteudo, v.universo) != meta.get("universo"):
        motivos.append("universo recontado do corpo ≠ meta")
    return {"ok": not motivos, "motivos": motivos}


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    v = _visao(payload, ctx)
    ef = resultado.efeito or {}
    if ef.get("visao") != v.nome:
        return False
    c = conferir(v.nome, ef)
    ef["conferencia"] = c
    return c["ok"]


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["materializar"], prioridade=20, volta={"nos": ["vm2"]})


# ── frescor (sensor da E18: grupo `visoes` em compliance_agent/fluxo/sensores.py) ───────────────────────────────────
def frescor(raiz=None, agora: float | None = None) -> dict:
    """Idade × SLO de cada visão. Ausente = INDISPONIVEL (não é fresca, não é zero)."""
    agora = time.time() if agora is None else agora
    itens = []
    for nome, v in VISOES.items():
        meta = ler_meta(nome, raiz)
        if meta is None:
            itens.append({"visao": nome, "estado": "INDISPONIVEL", "idade_s": None, "slo_s": v.slo_s,
                          "motivo": "nunca materializada"})
            continue
        idade = agora - float(meta["gerado_em_epoch"])
        itens.append({"visao": nome, "estado": "FRESCA" if idade <= v.slo_s else "ATRASADA",
                      "idade_s": round(idade), "slo_s": v.slo_s, "gerado_em": meta.get("gerado_em"),
                      "universo": meta.get("universo")})
    frescas = [i["visao"] for i in itens if i["estado"] == "FRESCA"]
    return {"total": len(itens), "frescas": len(frescas),
            "atrasadas": [i["visao"] for i in itens if i["estado"] == "ATRASADA"],
            "ausentes": [i["visao"] for i in itens if i["estado"] == "INDISPONIVEL"], "itens": itens}


def g_visoes(ctx) -> list:
    """Leituras do grupo `visoes`: `visoes.idade_s` por visão (detalhe) + `visoes.atrasadas` (atrasada + ausente)."""
    from compliance_agent.fluxo.sensores import Leitura, nao_mediu
    f = frescor(raiz=ctx.raiz, agora=ctx.agora.timestamp())
    out = []
    for i in f["itens"]:
        rot = {"detalhe_de": "visoes.atrasadas", "visao": i["visao"], "slo_s": i["slo_s"], "sensor": i["estado"]}
        if i["idade_s"] is None:
            out.append(nao_mediu("visoes.idade_s", i["motivo"], **rot))
        else:
            out.append(Leitura("visoes.idade_s", float(i["idade_s"]), rotulos=rot))
    ruins = f["atrasadas"] + f["ausentes"]
    motivo = (f"{f['frescas']}/{f['total']} frescas" + (f"; atrasadas: {', '.join(f['atrasadas'])}" if f["atrasadas"]
              else "") + (f"; nunca materializadas: {', '.join(f['ausentes'])}" if f["ausentes"] else ""))
    out.insert(0, Leitura("visoes.atrasadas", float(len(ruins)), motivo=motivo,
                          rotulos={"frescas": f["frescas"], "total": f["total"], "atrasadas": f["atrasadas"],
                                   "ausentes": f["ausentes"]}))
    return out


# ── paridade com a rota viva (antes de trocar a rota) ───────────────────────────────────────────────────────────────
VOLATEIS = frozenset({"gerado", "gerado_em", "atualizado", "_gerado", "data_ref"})   # só carimbos de hora


def normalizar(x):
    """Tira só carimbos de hora (o instante do cálculo), nada de número."""
    if isinstance(x, dict):
        return {k: normalizar(v) for k, v in x.items() if k not in VOLATEIS}
    if isinstance(x, list):
        return [normalizar(v) for v in x]
    return x


def diferencas(a, b, caminho: str = "", limite: int = 20) -> list[str]:
    out: list[str] = []
    if type(a) is not type(b):
        return [f"{caminho or '/'}: tipo {type(a).__name__} ≠ {type(b).__name__}"]
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{caminho}/{k}: só em {'antes' if k in a else 'depois'}")
            else:
                out += diferencas(a[k], b[k], f"{caminho}/{k}", limite)
            if len(out) >= limite:
                break
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{caminho}: {len(a)} ≠ {len(b)} itens")
        for i, (x, y) in enumerate(zip(a, b)):
            out += diferencas(x, y, f"{caminho}[{i}]", limite)
            if len(out) >= limite:
                break
    elif a != b:
        out.append(f"{caminho}: {str(a)[:60]!r} ≠ {str(b)[:60]!r}")
    return out[:limite]


def paridade_viva(nome: str, base: str = "http://127.0.0.1:8000", timeout: float = 900.0) -> dict:
    """Resposta da rota VIVA (antes da troca) × corpo materializado, sem os carimbos de hora."""
    import urllib.request
    lido = ler(nome)
    if lido is None:
        return {"visao": nome, "ok": False, "motivo": "visão ausente — rode `materializar rodar` antes"}
    with urllib.request.urlopen(base.rstrip("/") + VISOES[nome].rota, timeout=timeout) as r:
        cabec = r.headers.get("X-JFN-Visao")
        viva = json.loads(r.read())
    dif = diferencas(normalizar(viva), normalizar(json.loads(lido[0])))
    return {"visao": nome, "ok": not dif, "diferencas": dif, "servido_por": cabec or "rota viva (legado)",
            "gerado_em": lido[1].get("gerado_em")}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds")


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E15 materializar visões do painel (O7.1)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rodar")
    r.add_argument("--visao", action="append", choices=sorted(VISOES))
    r.add_argument("--todas", action="store_true")
    sub.add_parser("estado")
    p = sub.add_parser("paridade")
    p.add_argument("--visao", action="append", choices=sorted(VISOES))
    p.add_argument("--base", default="http://127.0.0.1:8000")
    a = ap.parse_args(argv)
    if a.cmd == "estado":
        print(json.dumps(frescor(), ensure_ascii=False, indent=1))
        return 0
    nomes = sorted(VISOES) if getattr(a, "todas", False) or not a.visao else a.visao
    if a.cmd == "paridade":
        res = [paridade_viva(n, a.base) for n in nomes]
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if all(x["ok"] for x in res) else 1
    rc = 0
    for n in nomes:
        payload = {"visao": n}
        ctx = Contexto(no=os.environ.get("JFN_NO", "cli"), tipo=f"materializar:{n}", chave=f"materializar:{n}",
                       ficha=0, tentativa=1)
        res = _handler(payload, ctx)
        ok = _efeito(payload, ctx, res)
        print(json.dumps(res.efeito, ensure_ascii=False, default=str))
        if ok:
            print(f"materializar: {n} sha256 {res.efeito['sha256'][:16]} conferido ({res.efeito['segundos']} s)")
        else:
            print(f"materializar: {n} EFEITO NÃO CONFERIDO", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
