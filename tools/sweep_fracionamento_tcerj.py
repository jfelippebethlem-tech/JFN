# -*- coding: utf-8 -*-
"""Sweep GLOBAL de fracionamento de despesa sobre compras_diretas_tcerj (art. 75 §1º, Lei 14.133/2021).

Alimenta o detector P4 (compliance_agent/detectores/p4_fracionamento.py) em LOTE: agrupa as compras
diretas do TCE-RJ por (unidade, exercício) e roda o card em cada grupo — antes deste sweep, o P4 só
recebia contexto injetado pontualmente (bombeiros); as 97 unidades nunca tinham sido varridas.

HONESTIDADE (regras do projeto):
  • Reusa o card P4 inteiro — limiares, âncoras e degradação honesta ficam LÁ, não aqui.
  • Sem LLM (`gerar` ausente): só o flag OBJETIVO — indício, nunca acusação.
  • A tabela não tem data por contratação → sinais temporais do P4 ficam de fora (o card degrada sozinho).
  • Dispensas enquadradas na Lei 8.666 (transição até 2023) são medidas contra o limite MAIOR da 14.133
    (tabela do P4) — critério CONSERVADOR: nunca infla achado, pode subestimar.
  • `valor` repete por linha de item → dedupe por processo (MAX = total; verificado: 1 valor distinto/processo).

Uso:
    .venv/bin/python -m tools.sweep_fracionamento_tcerj [--ano 2024] [--unidade FSERJ] [--min-soma 0]
Saída: tabela no stdout + JSON em output/sweep_fracionamento_tcerj.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from compliance_agent.detectores.p4_fracionamento import P4Fracionamento, limite_dispensa
from compliance_agent.objeto_similaridade import ramo_atividade

DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"
OUT = Path(__file__).resolve().parent.parent / "output" / "sweep_fracionamento_tcerj.json"

# obra/engenharia → limite do art. 75, I (maior); o resto cai em "compras" (II).
# art. 75, I = obras, SERVIÇOS DE ENGENHARIA e manutenção de veículos. Reforma/impermeabilização são serviço de
# engenharia (sweep 19/11/2026: ITERJ 2026 media duas reformas de cisterna contra o teto de COMPRAS); e "obra"
# solta casava "MÃO DE OBRA" de serviço comum.
_RE_OBRAS = re.compile(r"(?<!m[ãa]o de )\bobras?\b|engenharia|reforma|constru[çc][ãa]o|pavimenta|"
                       r"impermeabiliza|manuten[çc][ãa]o\s+predial|manuten[çc][ãa]o\s+(?:de\s+)?ve[íi]culo", re.I)

# quantos clusters extrair por (unidade, exercício): o P4 devolve só o MELHOR cluster; removemos as
# contratações do achado e re-rodamos até descartar/esgotar (cap de segurança).
_MAX_CLUSTERS_POR_GRUPO = 10


# AQUISIÇÃO de material (ainda que "de construção") é COMPRA (art. 75, II), não obra (I): medido no sweep de
# 19/11/2026 — "aquisição de material de construção civil" caía em 'obras' pela palavra "construção".
_RE_AQUISICAO = re.compile(r"^\W*(?:o\s+presente\s+.{0,80}?objeto\s+a\s+)?(?:aquisi[çc][ãa]o|compra|"
                           r"fornecimento\s+de\s+(?:materia|produto|equipamento))", re.I)


def _tipo_obj(objeto: str | None) -> str:
    t = (objeto or "").lower()
    if _RE_AQUISICAO.search(t):
        return "compras"
    return "obras" if _RE_OBRAS.search(t) else "compras"


# Fracionamento por VALOR só faz sentido em dispensa POR VALOR: Lei 14.133 art. 75 I/II ·
# Lei 8.666 art. 24 I/II · Lei 13.303 art. 29 I/II. Dispensa por OUTRO fundamento (emergência
# art. 75 VIII / 24 IV, locação, etc.) não é "fuga do teto" — é matéria do R5 (enquadramento),
# não do P4. Sem esse filtro, o smoke da FSERJ agrupava dispensas emergenciais de R$ 60M+.
_INCISOS_VALOR = {"I", "II", "1", "2"}


def _inciso_valor(enquadramento: str | None) -> bool | None:
    """True se o enquadramento cita inciso de dispensa POR VALOR (75/24/29, I ou II); False se cita
    outro inciso; None se não parseável (texto livre do TCE-RJ é sujo)."""
    t = re.sub(r"[\s.ºo°]+", "", (enquadramento or "").upper())
    if not t:
        return None
    m = re.search(r"INC(?:ISO)?([IVX]+|\d+),?D?O?ART(?:IGO)?(?:75|24|29)", t)
    if not m:
        m = re.search(r"ART(?:IGO)?(?:75|24|29)[^A-Z0-9]{0,3}(?:INC(?:ISO)?)?([IVX]+|\d+)", t)
    if not m:
        return None
    return m.group(1) in _INCISOS_VALOR


# NÃO É CONTRATAÇÃO de objeto (não soma no art. 75 §1º): inscrição em evento/curso, anuidade de associação,
# juros/multas e CREDENCIAMENTO por chamada pública (procedimento auxiliar, art. 79 — vários credenciados é o
# desenho, não a fuga). Medido no sweep de 19/11/2026: FEC 2025/2026 (chamada pública, 9 e 20 credenciados),
# UERJ (inscrições e anuidades) e GSI (juros e multas do INSS) acendiam como "fracionamento".
_RE_NAO_CONTRATACAO = re.compile(
    r"inscri[çc](?:[ãa]o|[õo]es)|anuidade|juros\s+e\s+multas|credenci|chamada\s+p[úu]blica", re.I)


def _dispensa_por_valor(afastamento: str | None, enquadramento: str | None,
                        valor: float, exercicio: int, tipo_obj: str, objeto: str | None = None) -> bool:
    """A contratação conta como DISPENSA por valor p/ o P4? Inexigibilidade → False; 'Pequenas
    Compras' → True (por definição); inciso citado decide; sem inciso parseável, heurística
    conservadora: só é candidata a fuga-de-teto se o valor CABE no teto vigente (dispensa por
    valor acima do próprio teto é impossível — seria outro fundamento)."""
    a = (afastamento or "").lower()
    if "dispensa" not in a:
        return False
    if objeto and _RE_NAO_CONTRATACAO.search(objeto):
        return False
    if "pequenas compras" in a:
        return True
    iv = _inciso_valor(enquadramento)
    if iv is not None:
        return iv
    limite = limite_dispensa(exercicio, tipo_obj)
    return limite is not None and valor <= limite


def _sem_nome_da_unidade(objeto: str | None, unidade: str | None) -> str:
    """Tira do objeto as palavras da SIGLA da unidade (parte antes de " - ") — não identificam objeto."""
    sigla = (unidade or "").split(" - ")[0]
    out = objeto or ""
    for w in re.findall(r"\w{3,}", sigla):
        out = re.sub(rf"\b{re.escape(w)}\b", " ", out, flags=re.I)
    return out


def _norm_processo(p: str | None) -> str:
    """Chave de grafia do processo: só letras/dígitos, sem o prefixo SEI (mantém sufixo A/B)."""
    t = re.sub(r"[^0-9A-Z]", "", (p or "").upper())
    return t[3:] if t.startswith("SEI") else t


def carregar_grupos(db_path: Path = DB, ano: int | None = None,
                    unidade_like: str | None = None) -> dict[tuple[str, int], list[dict]]:
    """Lê compras_diretas_tcerj (read-only), 1 linha por processo, agrupado por (unidade, exercício)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sql = """
        SELECT processo, unidade, ano_processo,
               MAX(valor) AS valor, MIN(objeto) AS objeto,
               MIN(afastamento) AS afastamento, MIN(enquadramento_legal) AS enquadramento,
               MIN(fornecedor) AS fornecedor
        FROM compras_diretas_tcerj
        WHERE processo IS NOT NULL AND unidade IS NOT NULL AND ano_processo IS NOT NULL
        GROUP BY processo, unidade, ano_processo
    """
    grupos: dict[tuple[str, int], list[dict]] = {}
    vistos: set[tuple] = set()
    # MAIOR valor primeiro: entre grafias do mesmo processo fica a linha de valor total
    for r in sorted(con.execute(sql), key=lambda r: -float(r["valor"] or 0)):
        if ano and int(r["ano_processo"]) != ano:
            continue
        if unidade_like and unidade_like.lower() not in (r["unidade"] or "").lower():
            continue
        chave = (r["unidade"], int(r["ano_processo"]))
        # o MESMO processo vem com grafias distintas ("SEI 310001/001411/2024" × "SEI-310001/001411/2024"):
        # contado 2× inflava a soma (sweep 19/11/2026). Sufixo de letra (001570B) é processo distinto.
        k_proc = (chave, _norm_processo(r["processo"]))
        # processo IRMÃO de sufixo (000778 × 000778A) com o MESMO valor e outro fornecedor é o mesmo
        # registro duplicado (só um deles tem OB no SIAFE — medido em SEDSODH 2024, 19/11/2026): somar os
        # dois dobrava a parcela. Valor diferente fica (pode ser outro lote) e a tela avisa do irmão.
        k_irmao = (chave, re.sub(r"\D", "", r["processo"] or ""), round(float(r["valor"] or 0), 2))
        if k_proc in vistos or k_irmao in vistos:
            continue
        vistos.update((k_proc, k_irmao))
        valor = float(r["valor"] or 0)
        tipo_obj = _tipo_obj(r["objeto"])
        grupos.setdefault(chave, []).append({
            "processo": r["processo"],
            # o texto que AGRUPA vai sem o nome da própria unidade ("…necessidades do DEGASE" casava com
            # qualquer objeto que citasse o DEGASE — sweep 19/11/2026); a tela mostra o original
            "objeto": _sem_nome_da_unidade(r["objeto"], r["unidade"]),
            "objeto_original": r["objeto"],
            "valor": valor,
            "modalidade": r["afastamento"],
            # flag EXPLÍCITA p/ o _is_dispensa do P4: só dispensa POR VALOR conta p/ fracionamento
            "dispensa": _dispensa_por_valor(r["afastamento"], r["enquadramento"], valor,
                                            int(r["ano_processo"]), tipo_obj, r["objeto"]),
            "exercicio": int(r["ano_processo"]),
            "fornecedor": r["fornecedor"],
            "tipo_obj": tipo_obj,
        })
    con.close()
    return grupos


def rodar_sweep(grupos: dict[tuple[str, int], list[dict]]) -> list[dict]:
    """Roda o P4 por grupo, extraindo TODOS os clusters confirmados (o card devolve 1 por chamada:
    remove as contratações do achado e re-roda). Retorna achados ordenados por soma do cluster.

    Inciso I (obras/engenharia) e inciso II (compras/serviços) têm LIMITES distintos: cada tipo é
    somado contra o próprio teto. Misturar os dois punha material de construção e obra de incêndio no
    mesmo somatório (NOVO DEGASE 2026, sweep de 19/11/2026)."""
    det = P4Fracionamento()
    achados: list[dict] = []
    for (unidade, exercicio), todas in sorted(grupos.items()):
        for tipo in ("compras", "obras"):
            restantes = [c for c in todas if c.get("tipo_obj", "compras") == tipo]
            for _ in range(_MAX_CLUSTERS_POR_GRUPO):
                if len(restantes) < 2:
                    break
                res = det.avaliar({"processo": f"{unidade} · {exercicio}", "contratacoes": restantes})
                if res.status != "confirmado" or res.score <= 0:
                    break
                d = res.to_dict()
                d["unidade"], d["exercicio"] = unidade, exercicio
                procs = set(d.get("valores", {}).get("processos_cluster") or [])
                d.update(_retrato_do_cluster([c for c in restantes if str(c["processo"]) in procs],
                                             d.get("valores", {})))
                achados.append(d)
                # remove o cluster achado (registrado pelo P4 em valores.processos_cluster) e re-roda
                antes = len(restantes)
                restantes = [c for c in restantes if str(c["processo"]) not in procs]
                if len(restantes) == antes:  # sem processos mapeáveis → não dá p/ iterar com segurança
                    break
    achados.sort(key=lambda d: d.get("valores", {}).get("soma_cluster", 0), reverse=True)
    return achados


def _retrato_do_cluster(cs: list[dict], valores: dict) -> dict:
    """O que a aba mostra: QUAIS contratações, de QUAIS fornecedores, de que NATUREZA, e se a soma do
    exercício passa do teto (o núcleo do art. 75 §1º — o fornecedor NÃO entra no critério)."""
    ramos = sorted({r for r in (ramo_atividade(c.get("objeto_original") or c.get("objeto") or "") for c in cs) if r})
    forn = sorted({(c.get("fornecedor") or "").strip() for c in cs if (c.get("fornecedor") or "").strip()})
    soma, lim = float(valores.get("soma_cluster") or 0), valores.get("limite_dispensa_vigente")
    bases: dict[str, list[str]] = {}
    for c in cs:
        bases.setdefault(re.sub(r"\D", "", c.get("processo") or ""), []).append(c.get("processo"))
    irmaos = [ps for ps in bases.values() if len(ps) > 1]
    return {
        "natureza": ramos[0] if len(ramos) == 1 else (" + ".join(ramos) if ramos else None),
        "criterio_natureza": "ramo_de_atividade" if ramos else "similaridade_do_objeto",
        "fornecedores": forn,
        "n_fornecedores_distintos": len(forn),
        "soma_acima_do_teto": bool(lim) and soma > float(lim),
        # mesma numeração com sufixo (000022 × 000022-A) e valores distintos: conferir nos autos se é uma
        # contratação só (cotações) ou duas — se for uma, a soma cai.
        "processos_irmaos": irmaos,
        "contratacoes": sorted(({"processo": c.get("processo"),
                                 "objeto": (c.get("objeto_original") or c.get("objeto") or "")[:240],
                                 "valor": c.get("valor"), "fornecedor": c.get("fornecedor"),
                                 "modalidade": c.get("modalidade")} for c in cs),
                               key=lambda c: -(c["valor"] or 0)),
    }


def ligar_ob_siafe(achados: list[dict], db_path: Path = DB) -> dict:
    """Valor PAGO (OB do SIAFE, `_ob_paga`) por processo SEI do cluster. Processo sem OB ligável fica
    `ob_pago=None` (INDISPONÍVEL ≠ 0): o SIAFE do JFN não cobre todo o acervo e grafa o processo de
    formas irregulares em parte das OBs. Retorna a cobertura medida."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    procs = sorted({c["processo"] for a in achados for c in a.get("contratacoes", []) if c.get("processo")})
    pagos: dict[str, tuple[float, int]] = {}
    if procs:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            for i in range(0, len(procs), 500):
                lote = procs[i:i + 500]
                q = (f"SELECT processo, SUM(valor), COUNT(*) FROM ob_orcamentaria_siafe "
                     f"WHERE {_ob_paga(con)} AND processo IN ({','.join('?' * len(lote))}) GROUP BY processo")
                for p, v, n in con.execute(q, lote):
                    pagos[p] = (round(float(v or 0), 2), int(n))
        except sqlite3.Error:
            pagos = {}
        finally:
            con.close()
    for a in achados:
        tot, lig = 0.0, 0
        for c in a.get("contratacoes", []):
            pv = pagos.get(c.get("processo"))
            c["ob_pago"], c["n_ob"] = (pv[0], pv[1]) if pv else (None, 0)
            if pv:
                tot, lig = tot + pv[0], lig + 1
        a["ob_pago_total"] = round(tot, 2) if lig else None
        a["ob_processos_ligados"] = lig
    return {"processos": len(procs), "processos_com_ob": len(pagos)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Sweep de fracionamento (P4) sobre compras_diretas_tcerj")
    ap.add_argument("--ano", type=int, default=None, help="filtrar exercício")
    ap.add_argument("--unidade", default=None, help="filtrar unidade (substring, case-insensitive)")
    ap.add_argument("--min-soma", type=float, default=0.0, help="soma mínima do cluster p/ listar")
    ap.add_argument("--top", type=int, default=40, help="máx. de achados na tabela do stdout")
    args = ap.parse_args()

    grupos = carregar_grupos(ano=args.ano, unidade_like=args.unidade)
    n_proc = sum(len(v) for v in grupos.values())
    print(f"Grupos (unidade × exercício): {len(grupos)} · processos únicos: {n_proc:,}".replace(",", "."))

    achados = [a for a in rodar_sweep(grupos)
               if a.get("valores", {}).get("soma_cluster", 0) >= args.min_soma]
    cob = ligar_ob_siafe(achados)
    print(f"OB do SIAFE ligadas pelo processo: {cob['processos_com_ob']} de {cob['processos']} processos")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(achados, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Achados confirmados (indício objetivo, sem juízo LLM): {len(achados)} → {OUT}\n")

    from compliance_agent.reporting.intel_base import reais as fmt_moeda
    for a in achados[: args.top]:
        v = a.get("valores", {})
        print(f"  [{a['score']:.2f}] {a['unidade'][:52]} · {a['exercicio']}"
              f" · {v.get('n_dispensas_cluster')} dispensas · soma {fmt_moeda(v.get('soma_cluster', 0))}"
              f" (limite {fmt_moeda(v.get('limite_dispensa_vigente') or 0)})")
        for c in a.get("contratacoes", [])[:6]:
            print(f"       · {c['processo']} · {(c['fornecedor'] or '')[:30]} · {fmt_moeda(c['valor'] or 0)}")


if __name__ == "__main__":
    main()
