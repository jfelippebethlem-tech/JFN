# -*- coding: utf-8 -*-
"""Carrega e valida `config/qualidade_regras.yaml` — a fonte única das regras de qualidade."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
ARQ = REPO / "config" / "qualidade_regras.yaml"

FAMILIAS = ("PAD", "CNF", "COR", "CST", "SUB")
SEVERIDADES = ("bloqueante", "alta", "media")
TIPOS = ("catraca", "sensor", "juiz", "existente", "manual")
SISTEMAS = ("painel", "detectores", "pericias", "relatorios", "lex", "yoda", "aovivo", "vault", "coletores",
            "llm", "infra")
ESTADOS = ("VERIFICADO", "PENDENTE", "INDISPONIVEL", "REFUTADO")
CAMPOS = ("id", "titulo", "enunciado", "porque", "medida", "aplica", "severidade", "acao", "verificadores")


@dataclass(frozen=True)
class Regra:
    id: str
    titulo: str
    enunciado: str
    porque: str
    medida: str
    aplica: tuple
    severidade: str
    acao: str
    verificadores: tuple = field(default_factory=tuple)

    @property
    def familia(self) -> str:
        return self.id.split("-")[0]

    def refs(self, tipo: str) -> list[str]:
        return [v["ref"] for v in self.verificadores if v["tipo"] == tipo]

    @property
    def automatica(self) -> bool:
        """Tem ao menos um verificador que RODA sozinho (catraca, sensor, juiz ou verificação já existente)."""
        return any(v["tipo"] != "manual" for v in self.verificadores)

    @property
    def divida(self) -> list[str]:
        """O que ainda falta automatizar (verificadores `manual`)."""
        return self.refs("manual")


@lru_cache(maxsize=4)
def _bruto(caminho: str) -> dict:
    return yaml.safe_load(Path(caminho).read_text(encoding="utf-8"))


def bruto(arq: Path = ARQ) -> dict:
    return _bruto(str(arq))


def carregar(arq: Path = ARQ) -> list[Regra]:
    return [Regra(**{k: (tuple(r[k]) if k in ("aplica", "verificadores") else str(r[k]).strip()) for k in CAMPOS})
            for r in bruto(arq)["regras"]]


def por_id(arq: Path = ARQ) -> dict[str, Regra]:
    return {r.id: r for r in carregar(arq)}


def rubricas(arq: Path = ARQ) -> dict:
    return bruto(arq)["rubricas"]


def problemas(arq: Path = ARQ, repo: Path = REPO) -> list[str]:
    """Defeitos do próprio registro. Lista vazia = registro íntegro. É o que a catraca do registro cobra."""
    d = bruto(arq)
    out, vistos = [], set()
    for r in d.get("regras", []):
        rid = r.get("id", "?")
        falta = [c for c in CAMPOS if not r.get(c)]
        if falta:
            out.append(f"{rid}: campo(s) vazio(s): {', '.join(falta)}")
            continue
        if rid in vistos:
            out.append(f"{rid}: id repetido")
        vistos.add(rid)
        fam, _, num = rid.partition("-")
        if fam not in FAMILIAS or not num.isdigit():
            out.append(f"{rid}: id fora do padrão FAMÍLIA-NN")
        if r["severidade"] not in SEVERIDADES:
            out.append(f"{rid}: severidade inválida ({r['severidade']})")
        for s in r["aplica"]:
            if s not in SISTEMAS:
                out.append(f"{rid}: sistema desconhecido em `aplica` ({s})")
        for v in r["verificadores"]:
            tipo, ref = v.get("tipo"), str(v.get("ref", ""))
            if tipo not in TIPOS or not ref:
                out.append(f"{rid}: verificador inválido ({v})")
            elif tipo in ("catraca", "existente"):
                arq_ref = ref.split("::")[0]
                if not (repo / arq_ref).exists():
                    out.append(f"{rid}: verificador aponta para arquivo inexistente ({arq_ref})")
                elif "::" in ref and f"def {ref.split('::')[1]}(" not in (repo / arq_ref).read_text(encoding="utf-8"):
                    out.append(f"{rid}: teste inexistente ({ref})")
            elif tipo == "sensor":
                from compliance_agent.qualidade import sensores
                if ref not in sensores.SENSORES:
                    out.append(f"{rid}: sensor inexistente ({ref})")
            elif tipo == "juiz" and ref not in d.get("rubricas", {}):
                out.append(f"{rid}: critério do juiz sem rubrica ({ref})")
        if fam == "SUB" and not any(v.get("tipo") == "juiz" for v in r["verificadores"]):
            out.append(f"{rid}: regra subjetiva sem critério do juiz")
    for nome, rub in d.get("rubricas", {}).items():
        if rub.get("regra") not in vistos:
            out.append(f"rubrica {nome}: aponta para regra inexistente ({rub.get('regra')})")
        for c in ("pergunta", "ancora_ruim", "ancora_boa"):
            if not rub.get(c):
                out.append(f"rubrica {nome}: sem {c}")
    return out


def resumo(arq: Path = ARQ) -> dict:
    rs = carregar(arq)
    por_fam = {f: [r for r in rs if r.familia == f] for f in FAMILIAS}
    return {
        "total": len(rs),
        "por_familia": {f: len(v) for f, v in por_fam.items()},
        "automaticas": sum(r.automatica for r in rs),
        "com_divida": sorted(r.id for r in rs if r.divida),
        "so_manuais": sorted(r.id for r in rs if not r.automatica),
        "por_tipo": {t: sum(bool(r.refs(t)) for r in rs) for t in TIPOS},
    }
