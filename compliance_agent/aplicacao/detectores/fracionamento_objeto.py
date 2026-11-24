# -*- coding: utf-8 -*-
"""E10 · `e10.p4_fracionamento_objeto` — fracionamento de despesa por OBJETO sobre as dispensas do TCE-RJ (SOMBRA ⚖️).

Porta as réguas que só existiam em `tools/sweep_fracionamento_tcerj.py` (plano §16.3; registro
`a_portar.p4_obra_e_lei_8666_tcerj`) para um detector genérico do E10, e usa o card P4
(`detectores/p4_fracionamento.py`) sem alterá-lo — limiares, âncoras e degradação honesta ficam LÁ.

Réguas portadas (cada uma com a medida que a justificou no sweep):
  · UMA linha por PROCESSO: `valor` repete o total do processo em cada item → MAX por processo (somar itens inflava
    o acervo 2,30×); grafias do mesmo processo ("SEI 31…" × "SEI-31…") contam uma vez; processo IRMÃO de sufixo
    (000778 × 000778A) com o MESMO valor é o mesmo registro duplicado;
  · natureza do objeto (inciso I × II do art. 75): "reforma é obra; mão de obra não é"; aquisição de material, ainda
    que de construção, é COMPRA; cada natureza soma contra o PRÓPRIO teto (nunca misturadas);
  · só dispensa POR VALOR soma: inciso citado decide; "Pequenas Compras" é por valor; sem inciso legível, só é
    candidata se o valor cabe no teto do exercício (teto pela fonte única `limites_dispensa`, via card P4);
  · NÃO é contratação de objeto: inscrição, anuidade, juros e multas, credenciamento/chamada pública, DEA e consumo
    de concessionária (luz/água/esgoto); credor que não é fornecedor licitável (ente público, concessionária, tributo)
    não soma — a mesma peneira da triagem SIAFE;
  · o nome da própria unidade sai do texto que agrupa (casava qualquer objeto que citasse a sigla).

Elegibilidade (invariante 3): só entra no cálculo o processo com veredito 'E' na exigência `dispensa_valor` da E9
(`compra_direta_tcerj`); 'I:' (não é dispensa por valor, ente público…) e '?:' (regime/teto indeterminado) ficam fora
— e são contados no resumo (INDISPONÍVEL ≠ 0). Sem LLM: o flag objetivo é indício, nunca acusação.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from decimal import Decimal

from compliance_agent.aplicacao.detectores import Carga, Disparo, elegivel
from compliance_agent.dominio.achado import Fato, Papel
from compliance_agent.reporting.intel_base import reais

ID = "e10.p4_fracionamento_objeto"
UNIDADE = "compra_direta_tcerj"
VERSAO = "e10-p4-1"
MAX_CLUSTERS_POR_GRUPO = 10      # o card devolve o MELHOR cluster: remove-o e re-roda até descartar (teto de segurança)
TIPOS = ("compras", "obras")

# art. 75, I = obras, SERVIÇOS DE ENGENHARIA e manutenção de veículos. Reforma/impermeabilização são serviço de
# engenharia (sweep 19/11/2026: ITERJ 2026 media duas reformas de cisterna contra o teto de COMPRAS); "obra" solta
# casava "MÃO DE OBRA" de serviço comum.
_RE_OBRAS = re.compile(r"(?<!m[ãa]o de )\bobras?\b|engenharia|reforma|constru[çc][ãa]o|pavimenta|"
                       r"impermeabiliza|manuten[çc][ãa]o\s+predial|manuten[çc][ãa]o\s+(?:de\s+)?ve[íi]culo", re.I)
# AQUISIÇÃO de material (ainda que "de construção") é COMPRA (art. 75, II), não obra (I): sweep de 19/11/2026.
_RE_AQUISICAO = re.compile(r"^\W*(?:o\s+presente\s+.{0,80}?objeto\s+a\s+)?(?:aquisi[çc][ãa]o|compra|"
                           r"fornecimento\s+de\s+(?:materia|produto|equipamento))", re.I)
_INCISOS_VALOR = {"I", "II", "1", "2"}
# Não é contratação de objeto (não soma no art. 75 §1º): medido nos sweeps de 19/11 e 23/11/2026 (FEC chamada pública,
# UERJ inscrições/anuidades, GSI juros e multas do INSS; CODERTE/INEA/IVB/EMOP somavam conta de Light/Ampla/Águas).
_RE_NAO_CONTRATACAO = re.compile(
    r"inscri[çc](?:[ãa]o|[õo]es)|anuidade|juros\s+e\s+multas|credenci|chamada\s+p[úu]blica|"
    r"reconhecimento\s+de\s+d[íi]vida|exerc[íi]cios?\s+anteriores|\bDEA\b|"
    r"consumo\s+de\s+(?:energia|[áa]gua)|fornecimento\s+de\s+energia|[áa]gua\s+e\s+(?:tratamento\s+de\s+)?esgoto",
    re.I)


def tipo_objeto(objeto: str | None) -> str:
    """'obras' (art. 75, I) ou 'compras' (II) pelo texto do objeto."""
    t = (objeto or "").lower()
    if _RE_AQUISICAO.search(t):
        return "compras"
    return "obras" if _RE_OBRAS.search(t) else "compras"


def inciso_valor(enquadramento: str | None) -> bool | None:
    """True se cita inciso de dispensa POR VALOR (75/24/29, I ou II); False se outro inciso; None se ilegível."""
    t = re.sub(r"[\s.ºo°]+", "", (enquadramento or "").upper())
    if not t:
        return None
    m = re.search(r"INC(?:ISO)?([IVX]+|\d+),?D?O?ART(?:IGO)?(?:75|24|29)", t)
    if not m:
        m = re.search(r"ART(?:IGO)?(?:75|24|29)[^A-Z0-9]{0,3}(?:INC(?:ISO)?)?([IVX]+|\d+)", t)
    if not m:
        return None
    return m.group(1) in _INCISOS_VALOR


def nao_fornecedor(nome: str | None) -> bool:
    """Credor que não é compra licitável (concessionária, ente público, tributo): peneira canônica, pelo nome — a
    E9 já tirou o ente público pela natureza jurídica quando havia CNPJ; isto cobre o processo sem CNPJ."""
    from compliance_agent.entidades_gov import eh_nao_fornecedor
    from compliance_agent.fracionamento_siafe import _CREDOR_NAO_LICITAVEL
    n = (nome or "").strip()
    return bool(n) and bool(_CREDOR_NAO_LICITAVEL.search(n) or eh_nao_fornecedor(n))


def dispensa_por_valor(afastamento: str | None, enquadramento: str | None, valor: float, exercicio: int,
                       tipo_obj: str, objeto: str | None = None) -> bool:
    """A contratação conta como DISPENSA por valor para o somatório? (inexigibilidade e não-contratação: não)."""
    from compliance_agent.detectores.p4_fracionamento import limite_dispensa
    a = (afastamento or "").lower()
    if "dispensa" not in a:
        return False
    if objeto and _RE_NAO_CONTRATACAO.search(objeto):
        return False
    if "pequenas compras" in a:
        return True
    iv = inciso_valor(enquadramento)
    if iv is not None:
        return iv
    limite = limite_dispensa(exercicio, tipo_obj)
    return limite is not None and valor <= limite


def _sem_nome_da_unidade(objeto: str | None, unidade: str | None) -> str:
    sigla = (unidade or "").split(" - ")[0]
    out = objeto or ""
    for w in re.findall(r"\w{3,}", sigla):
        out = re.sub(rf"\b{re.escape(w)}\b", " ", out, flags=re.I)
    return out


def _norm_processo(p: str | None) -> str:
    t = re.sub(r"[^0-9A-Z]", "", (p or "").upper())
    return t[3:] if t.startswith("SEI") else t


_SQL = """
    SELECT processo, unidade, ano_processo, MAX(valor) AS valor, MIN(objeto) AS objeto,
           MIN(afastamento) AS afastamento, MIN(enquadramento_legal) AS enquadramento, MIN(fornecedor) AS fornecedor
      FROM compras_diretas_tcerj
     WHERE processo IS NOT NULL AND unidade IS NOT NULL AND ano_processo IS NOT NULL {filtro}
     GROUP BY processo, unidade, ano_processo
"""


def _itens(linhas) -> list[dict]:
    """Uma linha por processo (MAX = total), deduplicada por grafia e por irmão de sufixo com o mesmo valor."""
    out: list[dict] = []
    vistos: set[tuple] = set()
    # MAIOR valor primeiro: entre grafias do mesmo processo fica a linha de valor total
    for r in sorted(linhas, key=lambda r: -float(r["valor"] or 0)):
        grupo = (r["unidade"], int(r["ano_processo"]))
        k_proc = (grupo, _norm_processo(r["processo"]))
        k_irmao = (grupo, re.sub(r"\D", "", r["processo"] or ""), round(float(r["valor"] or 0), 2))
        if k_proc in vistos or k_irmao in vistos:
            continue
        vistos.update((k_proc, k_irmao))
        valor = float(r["valor"] or 0)
        ano = int(r["ano_processo"])
        tipo = tipo_objeto(r["objeto"])
        out.append({
            "chave_e9": r["processo"], "grupo": f"{r['unidade']}|{ano}", "processo": r["processo"],
            "unidade": r["unidade"], "exercicio": ano, "valor": valor,
            "objeto": _sem_nome_da_unidade(r["objeto"], r["unidade"]), "objeto_original": r["objeto"],
            "modalidade": r["afastamento"], "enquadramento": r["enquadramento"], "fornecedor": r["fornecedor"],
            "tipo_obj": tipo,
            "dispensa": (not nao_fornecedor(r["fornecedor"])
                         and dispensa_por_valor(r["afastamento"], r["enquadramento"], valor, ano, tipo,
                                                r["objeto"])),
        })
    return out


def _ler(con: sqlite3.Connection, filtro: str, par: tuple) -> list[dict]:
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(_SQL.format(filtro=filtro), par)]
    finally:
        con.row_factory = None


def carregar(con: sqlite3.Connection, exercicio: int | None = None) -> Carga:
    filtro, par = ("AND ano_processo = ?", (exercicio,)) if exercicio else ("", ())
    linhas = _ler(con, filtro, par)
    return Carga(itens=_itens(linhas), contexto={"linhas_processo_unidade_ano": len(linhas)})


def grupo_de(d: Disparo) -> str:
    return d.grupo


def carregar_grupo(con: sqlite3.Connection, grupo: str, exercicio: int | None = None) -> Carga:
    unidade, _, ano = grupo.rpartition("|")
    linhas = _ler(con, "AND unidade = ? AND ano_processo = ?", (unidade, int(ano)))
    return Carga(itens=_itens(linhas))


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:16]


# O card recebe SÓ os campos que o sweep lhe dava: chave extra mudaria o resultado (`grupo`, por exemplo, é chave dura
# de classificação em `objeto_similaridade` e juntaria a unidade inteira num cluster só — medido na paridade 24/11).
_CAMPOS_CARD = ("processo", "objeto", "objeto_original", "valor", "modalidade", "dispensa", "exercicio", "fornecedor",
                "tipo_obj")


def _para_card(c: dict) -> dict:
    return {k: c[k] for k in _CAMPOS_CARD}


def detectar(itens: list[dict], contexto: dict | None = None) -> list[Disparo]:
    """Roda o card P4 por (unidade, exercício) e natureza, extraindo TODOS os clusters confirmados — só sobre os
    processos elegíveis na E9. Ordem determinística (grupo, natureza, iteração)."""
    from compliance_agent.detectores.p4_fracionamento import P4Fracionamento
    det = P4Fracionamento()
    por_grupo: dict[str, list[dict]] = {}
    for c in itens:
        if elegivel(c):
            por_grupo.setdefault(c["grupo"], []).append(c)
    out: list[Disparo] = []
    for grupo in sorted(por_grupo):
        unidade, exercicio = por_grupo[grupo][0]["unidade"], por_grupo[grupo][0]["exercicio"]
        for tipo in TIPOS:
            restantes = [c for c in por_grupo[grupo] if c["tipo_obj"] == tipo]
            for it in range(MAX_CLUSTERS_POR_GRUPO):
                if len(restantes) < 2:
                    break
                res = det.avaliar({"processo": f"{unidade} · {exercicio}", "contratacoes": [_para_card(c) for c in restantes]})
                if res.status != "confirmado" or res.score <= 0:
                    break
                d = res.to_dict()
                procs = set(d.get("valores", {}).get("processos_cluster") or [])
                membros = [c for c in restantes if str(c["processo"]) in procs]
                out.append(_disparo(grupo, tipo, it, restantes, membros, d))
                antes = len(restantes)
                restantes = [c for c in restantes if str(c["processo"]) not in procs]
                if len(restantes) == antes:      # sem processos mapeáveis: não dá para iterar com segurança
                    break
    return out


def _disparo(grupo: str, tipo: str, it: int, restantes: list[dict], membros: list[dict], d: dict) -> Disparo:
    v = d.get("valores") or {}
    insumo = sorted((str(c["processo"]), round(c["valor"], 2), bool(c["dispensa"])) for c in restantes)
    cluster = sorted(({"processo": c["processo"], "valor": round(c["valor"], 2), "fornecedor": c["fornecedor"],
                       "objeto": (c["objeto_original"] or "")[:240], "modalidade": c["modalidade"],
                       "enquadramento": c["enquadramento"], "dispensa": c["dispensa"], "e9": c.get("e9")}
                      for c in membros), key=lambda x: (-x["valor"], str(x["processo"])))
    soma = float(v.get("soma_cluster") or 0)
    lim = v.get("limite_dispensa_vigente")
    unidade, _, ano = grupo.rpartition("|")
    obs = (f"{v.get('n_dispensas_cluster')} dispensa(s) por valor de mesma natureza ({tipo}) na unidade {unidade}, "
           f"exercício {ano}, somando {reais(soma)} (teto do exercício: {reais(lim) if lim else 'INDISPONÍVEL'}); "
           f"régua do card: {d.get('motivo_refutacao') or '—'}")
    fatos = [Fato(papel=Papel.SUPORTE, tipo="contratacao", fonte="compras_diretas_tcerj", referencia=str(c["processo"]),
                  descricao=c["objeto"], valor=Decimal(str(c["valor"])),
                  dados={"fornecedor": c["fornecedor"], "modalidade": c["modalidade"],
                         "enquadramento": c["enquadramento"], "veredito_e9": c["e9"]})
             for c in cluster]
    return Disparo(chave=f"{grupo}|{tipo}|{_sha([c['processo'] for c in cluster])}", grupo=grupo, estado="INDICIO",
                   observacao=obs, processo=str(cluster[0]["processo"]) if cluster else None,
                   entradas={"grupo": grupo, "tipo": tipo, "iteracao": it, "insumo_sha": _sha(insumo),
                             "cluster": cluster},
                   valores={"score": d.get("score"), "soma_cluster": round(soma, 2), "limite": lim,
                            "soma_acima_do_teto": bool(lim) and soma > float(lim),
                            "n_dispensas": v.get("n_dispensas_cluster"),
                            "max_mesmo_fornecedor": v.get("max_dispensas_mesmo_grupo_economico"),
                            "regras": d.get("motivo_refutacao")},
                   evidencias=fatos)


def resumo(itens: list[dict], disparos: list[Disparo]) -> dict:
    """Universo, determinável e cobertura (invariante 2): o que a E9 deixou ver e o que ficou de fora, com R$."""
    from collections import Counter
    por = Counter(c.get("e9") or "?:SEM_LINHA_E9" for c in itens)
    valor = Counter()
    for c in itens:
        valor[c.get("e9") or "?:SEM_LINHA_E9"] += c["valor"]
    eleg = [c for c in itens if elegivel(c)]
    return {"universo_processos": len(itens), "elegiveis": len(eleg),
            "indeterminados": sum(n for k, n in por.items() if k.startswith("?")),
            "inelegiveis": sum(n for k, n in por.items() if k.startswith("I")),
            "por_veredito": dict(sorted(por.items())), "valor_por_veredito": {k: round(v, 2) for k, v in
                                                                             sorted(valor.items())},
            "elegiveis_dispensa_sweep": sum(1 for c in eleg if c["dispensa"]),
            # cobertura = parte do universo que a E9 conseguiu DECIDIR (E ou I); '?' é o que não deu para olhar
            "cobertura": round(1 - sum(n for k, n in por.items() if k.startswith("?")) / len(itens), 4)
            if itens else None,
            "disparos": len(disparos), "soma_disparos": round(sum(d.valores["soma_cluster"] for d in disparos), 2)}
