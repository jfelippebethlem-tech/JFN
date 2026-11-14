# -*- coding: utf-8 -*-
"""estado — o painel de conformidade: por sistema, as regras que valem, as violações abertas e a tendência.

Só LÊ o que os sensores, o juiz e as catracas já gravaram (`data/qualidade_estado.json`,
`data/qualidade_historico.jsonl`, `data/qualidade_juiz.json`, `tests/golden/qualidade_base.json`). Não mede nada
na hora: a rota do painel responde em milissegundos e nunca dispara sensor, modelo ou consulta pesada.

Honestidade do próprio painel: sem fotografia dos sensores o estado é `INDISPONIVEL` (não "0 violações");
sensor cego aparece como cego; regra sem verificador automático aparece como dívida.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from compliance_agent.qualidade import catraca, regras

REPO = Path(__file__).resolve().parents[2]
NOMES = {"painel": "Painel", "detectores": "Detectores", "pericias": "Perícias", "relatorios": "Relatórios e dossiês",
         "lex": "Lex", "yoda": "Yoda / Hermes", "aovivo": "AO VIVO", "vault": "Vault (casos e notas)",
         "coletores": "Coletores", "llm": "Modelos (Claude e cascata)", "infra": "Infraestrutura e repositório"}
_ORDEM_SEV = {"bloqueante": 0, "alta": 1, "media": 2}


def _dados() -> Path:
    return Path(os.environ.get("JFN_DADOS") or REPO / "data")


def _json(arq: Path):
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _tendencia(dados: Path, dias: int = 30) -> dict[str, list[dict]]:
    """Por sistema: a última leitura de cada dia (total de violações abertas)."""
    arq = dados / "qualidade_historico.jsonl"
    por_dia: dict[str, dict] = {}
    try:
        linhas = arq.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for ln in linhas:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        por_dia[d["hora"][:10]] = d                      # a mais recente do dia vence
    out: dict[str, list[dict]] = {"_total": []}
    for dia in sorted(por_dia)[-dias:]:
        d = por_dia[dia]
        out["_total"].append({"dia": dia, "abertas": d.get("total", 0), "bloqueantes": d.get("bloqueantes", 0)})
        for s in NOMES:
            out.setdefault(s, []).append({"dia": dia, "abertas": (d.get("por_sistema") or {}).get(s, 0)})
    return out


def _dividas_catraca() -> list[dict]:
    """A dívida travada em cada catraca (o que já existia e só pode descer)."""
    base = _json(catraca.BASE) or {}
    return [{"catraca": nome, "ocorrencias": sum(itens.values()), "itens": len(itens)} for nome, itens in sorted(base.items())]


def painel(dados: Path | None = None, agora: datetime | None = None) -> dict:
    dados = dados or _dados()
    agora = agora or datetime.now()
    rs = regras.carregar()
    foto = _json(dados / "qualidade_estado.json")
    juiz = _json(dados / "qualidade_juiz.json")
    tend = _tendencia(dados)
    violacoes = (foto or {}).get("violacoes", [])
    sistemas = []
    for s, nome in NOMES.items():
        do_sistema = [r for r in rs if s in r.aplica]
        itens = sorted((a for a in violacoes if a["sistema"] == s),
                       key=lambda a: (_ORDEM_SEV.get(a.get("severidade"), 9), a["regra"], a["chave"]))
        serie = tend.get(s, [])
        sistemas.append({
            "sistema": s, "nome": nome, "regras": len(do_sistema),
            "regras_por_familia": {f: sum(r.familia == f for r in do_sistema) for f in regras.FAMILIAS},
            "sem_verificador_automatico": sorted(r.id for r in do_sistema if not r.automatica),
            "violacoes_abertas": len(itens) if foto else None,
            "bloqueantes": sum(a.get("severidade") == "bloqueante" for a in itens) if foto else None,
            "regras_violadas": sorted({a["regra"] for a in itens}),
            "tendencia": serie,
            "variacao_7d": (serie[-1]["abertas"] - serie[max(0, len(serie) - 8)]["abertas"]) if len(serie) > 1 else None,
            "itens": itens[:60], "itens_total": len(itens),
        })
    res = regras.resumo()
    return {
        "ok": True,
        "estado": "MEDIDO" if foto else "INDISPONIVEL",
        "motivo": "" if foto else "os sensores de qualidade ainda não rodaram nesta máquina (python -m compliance_agent.qualidade sensores)",
        "gerado_em": agora.isoformat(timespec="seconds"),
        "medido_em": (foto or {}).get("em"),
        "documento": "docs/REGRAS-DE-QUALIDADE.md",
        "regras": res | {"familias": {f: regras.bruto()["familias"][f] for f in regras.FAMILIAS}},
        "total_violacoes": (foto or {}).get("total"),
        "total_bloqueantes": (foto or {}).get("bloqueantes"),
        "por_regra": (foto or {}).get("por_regra", {}),
        "sensores_cegos": (foto or {}).get("cegos", {}),
        "sistemas": sistemas,
        "tendencia": tend.get("_total", []),
        "juiz": None if not juiz else {k: juiz.get(k) for k in ("em", "ultima_tentativa", "motivo", "vigentes", "media", "por_criterio",
                                                                 "reprovadas", "a_escalar", "candidatas")}
        | {"avaliacoes": [{k: a.get(k) for k in ("id", "sistema", "rotulo", "veredito", "notas", "motivos", "o_que_falta",
                                                  "escalar", "motivo_escalar", "juiz", "em")} for a in juiz.get("avaliacoes", [])[:40]]},
        "dividas_catraca": _dividas_catraca(),
        "dividas_regra": [{"regra": r.id, "titulo": r.titulo, "falta": r.divida} for r in rs if r.divida],
    }
