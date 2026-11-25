# -*- coding: utf-8 -*-
"""Ouro sem vazamento — conjunto de rótulos de referência separado da calibração (plano mestre v2 §5, O5.4).

Regras (todas por código, cobradas em tests/test_estagio_calibrar.py):
  · SEPARAÇÃO POR BLOCO. Cada item conferido cai num bloco — processo, senão entidade (CPF/CNPJ/favorecido, só o
    hash), senão órgão × período, senão o próprio item —, e blocos que dividem qualquer dessas chaves se fundem num
    componente (união-busca). 1 em cada `OURO_A_CADA` componentes (sorteio determinístico pelo
    hash do bloco) fica RESERVADO ao ouro: a calibração (E13) nunca conta item de bloco reservado, e o ouro nunca
    recebe item de bloco de calibração. Nenhum processo, entidade ou órgão × período fica nos dois ao mesmo tempo;
    `vazamentos()` acusa qualquer cruzamento (inclusive item repetido).
  · RÓTULOS CONGELADOS COM DATA. `congelar()` grava o conjunto (JSONL canônico) com a data e o sha256 num manifesto;
    `ler_congelado()` recusa arquivo alterado e rótulo posterior ao congelamento. Mudar um rótulo = congelar uma
    versão nova (a antiga fica), nunca regravar.
  · NEGATIVOS PRÓXIMOS GUARDADOS. Item que o detector NÃO disparou mas ficou perto do limiar (`negativo_proximo`)
    entra no ouro com rótulo próprio — é o que mede o falso negativo da régua.
  · 2 REVISORES NO TIER 1, COM KAPPA. `estado_revisao_tier1()` exige dois revisores distintos (ao menos um humano),
    `DONO_POR_CANDIDATO` itens pareados e kappa de Cohen ≥ `KAPPA_MIN`. O 2º revisor humano é PENDÊNCIA DO DONO: sem
    ele o estado diz `pendente_2o_revisor` e o candidato não vira Tier 1 pelo ouro.

Módulo puro (sem banco): quem lê e grava é o E13 (`aplicacao/estagios/calibrar.py`).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

OURO_A_CADA = 5            # 1 em cada 5 blocos fica reservado ao ouro (20%)
KAPPA_MIN = 0.60           # concordância substancial (Landis & Koch) entre os 2 revisores
DONO_POR_CANDIDATO = 5     # §5: "o dono confere 5 por candidato a Tier 1"
ROTULOS = ("falso", "verdadeiro")
_CHAVES_ENTIDADE = ("cpf", "favorecido_cpf", "cpf_cnpj", "cnpj", "doc", "favorecido", "fornecedor")
_CHAVES_ORGAO = ("ug_codigo", "ug", "orgao_cnpj", "orgao", "unidade_gestora", "destino")
_CHAVES_PERIODO = ("exercicio", "ano", "ano_emenda", "mes", "data_ini", "data", "data_ob", "data_pagamento")


class ErroOuro(ValueError):
    """Ouro adulterado, rótulo posterior ao congelamento ou conjunto já congelado."""


def _h(txt: str) -> str:
    return hashlib.sha1(str(txt).encode("utf-8", "replace")).hexdigest()[:12]


def periodo_de(valor) -> str | None:
    """Ano (AAAA) de um exercício, data ou mês; None se não há."""
    s = str(valor or "").strip()
    return s[:4] if len(s) >= 4 and s[:4].isdigit() else None


def bloco(item: dict) -> str:
    """Chave de separação do item. A entidade entra só como hash (nunca o CPF/CNPJ cru)."""
    if item.get("processo"):
        return f"processo:{str(item['processo']).strip().upper()}"
    if item.get("entidade"):
        return f"entidade:{_h(item['entidade'])}"
    if item.get("orgao") and item.get("periodo"):
        return f"orgao:{item['orgao']}|{item['periodo']}"
    return f"item:{item.get('detector')}|{item.get('item')}"


def reservado_ouro(chave_bloco: str) -> bool:
    return int(hashlib.sha1(chave_bloco.encode("utf-8", "replace")).hexdigest()[:12], 16) % OURO_A_CADA == 0


def campos_de_separacao(evidencias) -> dict:
    """processo / entidade / órgão / período tirados das evidências de um alerta (dict JSON)."""
    d = evidencias if isinstance(evidencias, dict) else {}
    proc = next((d[k] for k in ("processo", "processo_sei", "numero_processo") if d.get(k)), None)
    ent = next((d[k] for k in _CHAVES_ENTIDADE if d.get(k) and not isinstance(d[k], (list, dict))), None)
    org = next((d[k] for k in _CHAVES_ORGAO if d.get(k) and not isinstance(d[k], (list, dict))), None)
    per = next((p for k in _CHAVES_PERIODO if (p := periodo_de(d.get(k)))), None)
    return {"processo": proc, "entidade": ent, "orgao": None if org is None else str(org), "periodo": per}


def _chaves(item: dict) -> list[str]:
    """Todas as chaves de separação do item (o bloco de precedência e cada dimensão presente)."""
    ks = [bloco(item)]
    if item.get("processo"):
        ks.append(f"processo:{str(item['processo']).strip().upper()}")
    if item.get("entidade"):
        ks.append(f"entidade:{_h(item['entidade'])}")
    if item.get("orgao") and item.get("periodo"):
        ks.append(f"orgao:{item['orgao']}|{item['periodo']}")
    return ks


def separar(itens: list[dict]) -> tuple[list[dict], list[dict]]:
    """(calibração, reservados ao ouro). Itens que dividem QUALQUER chave (processo, entidade, órgão × período) caem
    no mesmo componente — a precedência sozinha vazava: entidade A no ouro e entidade B na calibração com o mesmo
    órgão × período (medido no snapshot de 24/11: 2 vazamentos). O componente inteiro vai para um lado só, pelo hash
    da sua menor chave; cada item ganha `bloco` = essa chave."""
    pai: dict[str, str] = {}

    def raiz(k: str) -> str:
        while pai.setdefault(k, k) != k:
            pai[k] = pai[pai[k]]
            k = pai[k]
        return k

    for it in itens:
        ks = _chaves(it)
        for k in ks[1:]:
            a, b = raiz(ks[0]), raiz(k)
            if a != b:
                pai[max(a, b)] = min(a, b)
    cal, ouro = [], []
    for it in itens:
        it["bloco"] = raiz(_chaves(it)[0])
        (ouro if reservado_ouro(it["bloco"]) else cal).append(it)
    return cal, ouro


def vazamentos(calibracao: list[dict], ouro: list[dict]) -> list[str]:
    """O que aparece nos dois conjuntos: processo, entidade, órgão × período, bloco ou item (detector, item)."""
    out = []
    for nome, f in (("processo", lambda i: i.get("processo") and str(i["processo"]).strip().upper()),
                    ("entidade", lambda i: i.get("entidade") and _h(i["entidade"])),
                    ("orgao_periodo", lambda i: i.get("orgao") and i.get("periodo") and f"{i['orgao']}|{i['periodo']}"),
                    ("bloco", lambda i: i.get("bloco") or bloco(i)),
                    ("item", lambda i: f"{i.get('detector')}|{i.get('item')}")):
        comuns = {f(i) for i in calibracao if f(i)} & {f(i) for i in ouro if f(i)}
        out += [f"{nome}:{c}" for c in sorted(comuns)]
    return out


# ── rótulos congelados ──────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Rotulo:
    detector: str
    item: str
    rotulo: str                      # 'falso' (o detector errou) | 'verdadeiro'
    revisor: str                     # 'dono', 'revisor2', 'claude-opus-…'
    rotulado_em: str                 # AAAA-MM-DD
    processo: str | None = None
    entidade_hash: str | None = None
    orgao: str | None = None
    periodo: str | None = None
    negativo_proximo: bool = False   # o detector NÃO disparou, mas ficou perto do limiar
    grave: bool = False

    def __post_init__(self):
        if self.rotulo not in ROTULOS:
            raise ErroOuro(f"rótulo inválido: {self.rotulo!r}")
        date.fromisoformat(self.rotulado_em)


def _canonico(rotulos: list[Rotulo]) -> str:
    linhas = sorted(json.dumps(asdict(r), ensure_ascii=False, sort_keys=True) for r in rotulos)
    return "\n".join(linhas) + "\n"


def congelar(rotulos: list[Rotulo], pasta: Path, congelado_em: str) -> Path:
    """Grava `ouro-<data>.jsonl` + manifesto com sha256. Recusa sobrescrever e rótulo posterior à data."""
    date.fromisoformat(congelado_em)
    tarde = [r for r in rotulos if r.rotulado_em > congelado_em]
    if tarde:
        raise ErroOuro(f"{len(tarde)} rótulo(s) posterior(es) ao congelamento ({congelado_em})")
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"ouro-{congelado_em}.jsonl"
    if arq.exists():
        raise ErroOuro(f"{arq.name} já congelado — rótulo novo = versão nova, nunca regravar")
    txt = _canonico(rotulos)
    arq.write_text(txt, encoding="utf-8")
    (pasta / f"ouro-{congelado_em}.manifesto.json").write_text(json.dumps(
        {"congelado_em": congelado_em, "n": len(rotulos), "sha256": hashlib.sha256(txt.encode()).hexdigest()}),
        encoding="utf-8")
    return arq


def ler_congelado(arq: Path) -> list[Rotulo]:
    man = json.loads(arq.with_name(arq.name.replace(".jsonl", ".manifesto.json")).read_text(encoding="utf-8"))
    txt = arq.read_text(encoding="utf-8")
    if hashlib.sha256(txt.encode()).hexdigest() != man["sha256"]:
        raise ErroOuro(f"{arq.name}: sha256 não confere com o manifesto — ouro alterado depois de congelado")
    rot = [Rotulo(**json.loads(ln)) for ln in txt.splitlines() if ln.strip()]
    if any(r.rotulado_em > man["congelado_em"] for r in rot):
        raise ErroOuro(f"{arq.name}: rótulo posterior ao congelamento")
    return rot


def negativos_proximos(rotulos: list[Rotulo]) -> list[Rotulo]:
    return [r for r in rotulos if r.negativo_proximo]


# ── 2 revisores + kappa ────────────────────────────────────────────────────────────────────────────────
def kappa_cohen(a: list[str], b: list[str]) -> float | None:
    """Kappa de Cohen entre duas listas pareadas de rótulos; None sem par. Concordância total com uma só classe → 1."""
    if len(a) != len(b):
        raise ValueError("listas de tamanhos diferentes")
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    cats = set(a) | set(b)
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    if pe >= 1.0:
        return 1.0 if po == 1.0 else 0.0
    return round((po - pe) / (1 - pe), 4)


def _humano(revisor: str) -> bool:
    return not str(revisor).lower().startswith(("claude", "gemini", "haiku", "opus", "gpt", "llm"))


def estado_revisao_tier1(rotulos: list[Rotulo], detector: str) -> dict:
    """Estado da dupla revisão de um candidato a Tier 1 (itens rotulados por ≥ 2 revisores)."""
    por_item: dict[str, dict[str, str]] = {}
    for r in rotulos:
        if r.detector == detector:
            por_item.setdefault(r.item, {})[r.revisor] = r.rotulo
    revisores = sorted({rv for v in por_item.values() for rv in v})
    humanos = [rv for rv in revisores if _humano(rv)]
    out = {"detector": detector, "revisores": revisores, "n_pareados": 0, "kappa": None, "pronto": False}
    if len(revisores) < 2 or not humanos:
        out["pendencia"] = "pendente_2o_revisor" if humanos or revisores else "sem_rotulo_no_ouro"
        return out
    a_rev = humanos[0]
    b_rev = next(rv for rv in revisores if rv != a_rev)
    pares = [(v[a_rev], v[b_rev]) for v in por_item.values() if a_rev in v and b_rev in v]
    k = kappa_cohen([x for x, _ in pares], [y for _, y in pares])
    out.update(n_pareados=len(pares), kappa=k, par=[a_rev, b_rev])
    if len(pares) < DONO_POR_CANDIDATO:
        out["pendencia"] = f"n_pareados={len(pares)}<{DONO_POR_CANDIDATO}"
    elif k is None or k < KAPPA_MIN:
        out["pendencia"] = f"kappa={k}<{KAPPA_MIN}"
    else:
        out["pronto"], out["pendencia"] = True, None
    return out
