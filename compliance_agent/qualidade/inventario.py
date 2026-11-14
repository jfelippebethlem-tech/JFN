# -*- coding: utf-8 -*-
"""Inventário vivo — enumera por código tudo que afirma algo ao dono e confronta com o inventário (CST-11).

Fonte declarada: `config/qualidade_inventario.yaml`. Aqui só se LÊ código (regex/YAML): sem rede, sem banco, sem
importar `server`. Todas as funções recebem `repo` para rodar contra um repositório sintético nas provas (COR-15).

  rotas · abas · cards_cockpit · chips_mesa · kpis · motores · capacidades · detectores_registro ·
  funcoes_intel · relatorios_gate   → o que EXISTE no código
  carregar · confrontar · resumo    → o que está DECLARADO e a diferença (as dívidas, em números)
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from compliance_agent.qualidade.catraca import REPO

ARQ = REPO / "config" / "qualidade_inventario.yaml"
A_DECLARAR = "A DECLARAR"
CLASSES_ROTA = ("afirma", "operacional")

FONTES_ROTAS = ("rotas/*.py", "server.py", "compliance_agent/territorio/api.py", "compliance_agent/aovivo/api.py")
_ROTA = re.compile(r'^@(?:router|app)\.(?:get|post|put|delete|patch)\("(/api[^"]*)', re.M)
# `obs_trace.register_trace(app)` instala a rota DENTRO de uma função (decorador indentado): o regex de topo não vê.
_ROTA_INDENTADA = re.compile(r'^\s+@app\.(?:get|post|put|delete|patch)\("(/api[^"]*)', re.M)
_FONTES_INDENTADAS = ("compliance_agent/obs_trace.py",)

# o mesmo bloco que tools/painel_abas.py lê (fonte, nunca o bundle), aqui relativo a `repo`
_FONTES_TABS = ("static/js/src/app/tabs.js", "static/js/src/entrada.js")
_TABS = re.compile(r"const TABS=\{(.*?)\n\};", re.S)
_ESFERA = re.compile(r"^\s{2}(\w+):\[", re.M)
_ABA = re.compile(r"\{id:'([a-z_]+)'[^}\n]*?tl:'([^']*)'")

COCKPIT = "static/js/src/abas/cockpit.js"
CENA = "static/js/src/cena/index.js"
_CKCARD = re.compile(r"ckCard\('(\w+)'")
_CK_FIXOS = ("ck-econ", "ck-ved", "ck-fontes")  # herói, vedada e frescor: fora do ckCard
_NU_NODES = re.compile(r"export const NU_NODES=\[(.*?)\n\];", re.S)
_NU_ID = re.compile(r"\{id:'(\w+)'")
_KPI = re.compile(r"\bkpi\(")

_DETECTOR = re.compile(r"^class (\w+)\(Detector\)", re.M)
_DEF_PUB = re.compile(r"^def ([a-z]\w+)\(", re.M)
_DECOR = re.compile(r'^@router\.\w+\("([^"]+)"', re.M)
_IMPORT_INTEL = re.compile(r"from compliance_agent\.cruzamentos_intel import ([\w, ]+)")
_CACHE_INTEL = re.compile(r'ler_cache_intel\("(\w+)"\)')
_INFRA_INTEL = {"ler_cache_intel", "gerar_cache_intel"}

_GATES = {"neutro": re.compile(r"\bgarantir_neutro(?:_exceto_dados)?\b"),
          "citacoes": re.compile(r"\b(?:gate_citacoes|sanear_parecer)\b"),
          "render_html": re.compile(r"\brender_html\b")}


def _ler(repo: Path, rel: str) -> str:
    p = repo / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def _yaml(repo: Path, rel: str) -> dict:
    texto = _ler(repo, rel)
    return (yaml.safe_load(texto) or {}) if texto else {}


# ───────────────────────────── o que existe no código ─────────────────────────────

def rotas(repo: Path = REPO) -> dict[str, str]:
    """{path /api…: arquivo} de todas as rotas registradas (decorador de topo + as instaladas por função)."""
    out: dict[str, str] = {}
    arqs = [p for pad in FONTES_ROTAS for p in sorted(repo.glob(pad))]
    for arq in arqs:
        for path in _ROTA.findall(arq.read_text(encoding="utf-8", errors="replace")):
            out.setdefault(path, str(arq.relative_to(repo)))
    for rel in _FONTES_INDENTADAS:
        for path in _ROTA_INDENTADA.findall(_ler(repo, rel)):
            out.setdefault(path, rel)
    return dict(sorted(out.items()))


def abas(repo: Path = REPO) -> dict[str, dict]:
    """{id: {esfera, rotulo}} do bloco `const TABS={...}` do fonte do painel (mesma leitura de tools/painel_abas)."""
    for rel in _FONTES_TABS:
        m = _TABS.search(_ler(repo, rel))
        if not m:
            continue
        corpo, out = m.group(1), {}
        marcas = list(_ESFERA.finditer(corpo))
        for i, mk in enumerate(marcas):
            fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(corpo)
            for aid, rot in _ABA.findall(corpo[mk.end():fim]):
                out[aid] = {"esfera": mk.group(1), "rotulo": rot}
        return out
    return {}


def cards_cockpit(repo: Path = REPO) -> list[str]:
    """Ids dos instrumentos do cockpit (`cki-<id>` dos ckCard) e dos números fixos (herói, vedada, frescor)."""
    texto = _ler(repo, COCKPIT)
    cards = [f"cki-{i}" for i in dict.fromkeys(_CKCARD.findall(texto))]
    return cards + [c for c in _CK_FIXOS if f'id="{c}"' in texto]


def chips_mesa(repo: Path = REPO) -> list[str]:
    """Ids dos chips da mesa holográfica (`NU_NODES`); cada um espelha o card `cki-<id>` (ckFill → nuSet)."""
    m = _NU_NODES.search(_ler(repo, CENA))
    return _NU_ID.findall(m.group(1)) if m else []


def kpis(repo: Path = REPO) -> dict[str, int]:
    """Contagem de `kpi(` por arquivo das abas — os números soltos das telas."""
    out = {}
    for p in sorted((repo / "static/js/src/abas").glob("*.js")):
        n = len(_KPI.findall(p.read_text(encoding="utf-8", errors="replace")))
        if n:
            out[str(p.relative_to(repo))] = n
    return out


def motores(repo: Path = REPO) -> list[dict]:
    """Motores do AO VIVO: id, classe e se declaram `efeito` (CST-03)."""
    lista = _yaml(repo, "compliance_agent/aovivo/motores.yaml").get("motores") or []
    return [{"id": m["id"], "classe": m.get("classe"), "tem_efeito": bool(m.get("efeito"))} for m in lista]


def capacidades(repo: Path = REPO) -> list[dict]:
    """Capacidades do registro do Yoda (`capabilities.yaml`) — o registro é a fonte; aqui só os campos que afirmam."""
    lista = _yaml(repo, "capabilities.yaml").get("capacidades") or []
    campos = ("id", "comando", "rota", "agente", "enviar_telegram", "status")
    return [{c: cap.get(c) for c in campos} for cap in lista]


def detectores_registro(repo: Path = REPO) -> list[str]:
    """Classes `Detector` do framework (`compliance_agent/detectores/*.py`), por regex — sem importar."""
    nomes = []
    for p in sorted((repo / "compliance_agent/detectores").glob("*.py")):
        nomes += _DETECTOR.findall(p.read_text(encoding="utf-8", errors="replace"))
    return sorted(set(nomes))


def funcoes_intel(repo: Path = REPO) -> list[str]:
    """Funções públicas de `cruzamentos_intel` servidas por rota `/api/intel/*` (import direto ou cache lido)."""
    publicas = set(_DEF_PUB.findall(_ler(repo, "compliance_agent/cruzamentos_intel.py"))) - _INFRA_INTEL
    texto = _ler(repo, "rotas/investigacao.py")
    marcas = list(_DECOR.finditer(texto))
    servidas = set()
    for i, mk in enumerate(marcas):
        if not mk.group(1).startswith("/api/intel/"):
            continue
        bloco = texto[mk.end(): marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)]
        for nomes in _IMPORT_INTEL.findall(bloco):
            servidas |= {n.strip() for n in nomes.split(",")}
        servidas |= set(_CACHE_INTEL.findall(bloco))
    return sorted(servidas & publicas)


def _fontes_codigo(entrada: dict) -> list[str]:
    fc = entrada.get("fonte_codigo") or []
    return [fc] if isinstance(fc, str) else list(fc)


def relatorios_gate(repo: Path = REPO, inv: dict | None = None) -> dict[str, dict]:
    """Por relatório inventariado: que gates o(s) arquivo(s)-fonte chamam de fato (grep) e quais arquivos sumiram."""
    inv = carregar() if inv is None else inv
    out = {}
    for rid, e in (inv.get("relatorios") or {}).items():
        arqs = _fontes_codigo(e)
        texto = "\n".join(_ler(repo, a) for a in arqs)
        r = {g: bool(rx.search(texto)) for g, rx in _GATES.items()}
        r["faltando"] = [a for a in arqs if not (repo / a).is_file()]
        out[rid] = r
    return out


# ───────────────────────────── o declarado e a diferença ─────────────────────────────

def carregar(arq: Path = ARQ) -> dict:
    return yaml.safe_load(Path(arq).read_text(encoding="utf-8")) or {}


def _a_declarar(secao: dict) -> dict[str, list[str]]:
    out = {}
    for k, e in (secao or {}).items():
        if isinstance(e, dict):
            campos = [c for c, v in e.items() if isinstance(v, str) and v.strip() == A_DECLARAR]
            if campos:
                out[str(k)] = campos
    return out


def fonte_a_declarar(inv: dict) -> dict[str, int]:
    """Rotas de classe `afirma` cuja fonte ainda é "A DECLARAR" — {path: 1} (base da catraca-catraca)."""
    return {p: 1 for p, e in (inv.get("rotas") or {}).items()
            if (e or {}).get("classe") == "afirma" and str((e or {}).get("fonte", "")).strip() == A_DECLARAR}


def sem_gerador(repo: Path, inv: dict) -> dict[str, str]:
    """Arquivos de dados do painel sem gerador versionado existente (COR-13): {arquivo: motivo}."""
    out = {}
    for arq, e in (inv.get("dados_painel") or {}).items():
        g = str((e or {}).get("gerador") or "").strip()
        if not g or g == A_DECLARAR:
            out[arq] = A_DECLARAR
        elif not (repo / g).is_file():
            out[arq] = f"gerador inexistente: {g}"
    return out


def confrontar(repo: Path = REPO, arq: Path = ARQ) -> dict:
    """O código contra o inventário: o que falta declarar, o que morreu, o que está incompleto e as contagens."""
    inv = carregar(arq)
    decl_rotas = inv.get("rotas") or {}
    decl_abas = inv.get("abas") or {}
    manchetes = inv.get("manchetes") or []
    ids_manchete = {m.get("id") for m in manchetes}
    chips_decl = {m.get("chip") for m in manchetes if m.get("chip")}

    cod_rotas, cod_abas = rotas(repo), abas(repo)
    cards, chips = cards_cockpit(repo), [f"nu-{c}" for c in chips_mesa(repo)]
    sem_entrada = {
        "rotas": sorted(set(cod_rotas) - set(decl_rotas)),
        "abas": sorted(set(cod_abas) - set(decl_abas)),
        "manchetes": [c for c in cards if c not in ids_manchete] + [c for c in chips if c not in chips_decl],
    }
    entrada_morta = {
        "rotas": sorted(set(decl_rotas) - set(cod_rotas)),
        "abas": sorted(set(decl_abas) - set(cod_abas)),
        "manchetes": sorted((ids_manchete - set(cards)) | (chips_decl - set(chips))),
        "relatorios": sorted(f"{r}: {', '.join(g['faltando'])}"
                             for r, g in relatorios_gate(repo, inv).items() if g["faltando"]),
        "lex": sorted(k for k in (inv.get("lex") or {}) if not (repo / k).is_file()),
    }
    incompletas = {
        "rotas": sorted(p for p, e in decl_rotas.items()
                        if (e or {}).get("classe") not in CLASSES_ROTA or not str((e or {}).get("afirma", "")).strip()),
        "manchetes": sorted(m.get("id", "?") for m in manchetes
                            if not all(str(m.get(c) or "").strip() for c in ("superficie", "afirma", "rota", "natureza"))),
    }
    a_declarar = {sec: d for sec in ("rotas", "abas", "relatorios", "dados_painel", "lex", "agendamentos")
                  if (d := _a_declarar(inv.get(sec)))}
    a_declarar_manchetes = {m["id"]: [c for c, v in m.items() if v == A_DECLARAR]
                            for m in manchetes if A_DECLARAR in m.values()}
    if a_declarar_manchetes:
        a_declarar["manchetes"] = a_declarar_manchetes
    gates = relatorios_gate(repo, inv)
    mot = motores(repo)
    contagens = {
        "rotas": len(cod_rotas),
        "rotas_por_classe": {c: sum(1 for e in decl_rotas.values() if (e or {}).get("classe") == c)
                             for c in CLASSES_ROTA},
        "abas": len(cod_abas),
        "cards_cockpit": len(cards),
        "chips_mesa": len(chips),
        "manchetes": len(manchetes),
        "kpis": sum(kpis(repo).values()),
        "motores": len(mot),
        "motores_com_efeito": sum(1 for m in mot if m["classe"] == "motor" and m["tem_efeito"]),
        "motores_sem_efeito": sum(1 for m in mot if m["classe"] == "motor" and not m["tem_efeito"]),
        "capacidades": len(capacidades(repo)),
        "detectores_registro": len(detectores_registro(repo)),
        "funcoes_intel": len(funcoes_intel(repo)),
        "relatorios": len(gates),
        "dados_painel": len(inv.get("dados_painel") or {}),
    }
    return {
        "sem_entrada": sem_entrada,
        "entrada_morta": entrada_morta,
        "incompletas": incompletas,
        "a_declarar": a_declarar,
        "fonte_a_declarar": sorted(fonte_a_declarar(inv)),
        "sem_gerador": sem_gerador(repo, inv),
        "relatorio_sem_neutro": sorted(r for r, g in gates.items() if not g["neutro"]),
        "contagens": contagens,
    }


def resumo(repo: Path = REPO, arq: Path = ARQ) -> dict:
    """Pequeno, para o painel de conformidade: o inventário em números e o tamanho de cada dívida."""
    c = confrontar(repo, arq)
    return {
        "contagens": c["contagens"],
        "dividas": {
            "sem_entrada": sum(len(v) for v in c["sem_entrada"].values()),
            "entrada_morta": sum(len(v) for v in c["entrada_morta"].values()),
            "incompletas": sum(len(v) for v in c["incompletas"].values()),
            "fonte_a_declarar": len(c["fonte_a_declarar"]),
            "sem_gerador": len(c["sem_gerador"]),
            "relatorio_sem_neutro": len(c["relatorio_sem_neutro"]),
        },
    }
