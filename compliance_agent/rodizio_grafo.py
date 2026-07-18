# -*- coding: utf-8 -*-
"""rodizio_grafo — grafo de rodízio CROSS-ata (licitante × certame × tempo).

Fecha a lacuna que uma ata isolada NÃO alcança: os padrões de cartel que só aparecem
ao cruzar VÁRIOS certames (OCDE, *Guidelines for Fighting Bid Rigging* 2025):

  • **cobertura / licitante-fantasma** — quem PARTICIPA muito e NUNCA vence (cover bidding:
    entra só para dar aparência de competição ao vencedor combinado);
  • **rodízio** — par/grupo que co-ocorre e ALTERNA as vitórias (bid rotation: cada um vence
    na sua vez, com o outro presente e "perdendo");
  • **roster de cartel** — conjunto de licitantes que co-participam repetidamente (a turma).

ARQUITETURA (deliberada): a ANÁLISE de grafo é determinística e testável a partir de um
contrato de registro limpo; o EXTRATOR de texto de ata é best-effort e reporta cobertura
honesta. INDÍCIO a verificar — presunção de legitimidade, nunca acusação.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from itertools import combinations

logger = logging.getLogger(__name__)

# ── identidade do licitante ──────────────────────────────────────────────────
# formatado sempre; cru de 14 dígitos SÓ com dígito verificador válido (evita nº de processo)
_CNPJ = re.compile(r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{14})\b")
_VENC = re.compile(r"vencedor|adjudicad|declarad[oa] vencedor|homologad|arrematant|1[ºo°]?\s*lugar|"
                   r"primeir[oa]\s+colocad", re.I)
_PERD = re.compile(r"inabilitad|desclassificad|desabilitad|desistiu|desistenc|nao\s+habilitad|"
                   r"segund[oa]\s+colocad|perdedor", re.I)
# Preâmbulo do CONTRATANTE/órgão/foundation — NÃO é licitante (falso-positivo real: a Fundação
# contratante "neste ato representada" aparecia como fantasma perdedor). Se o CNPJ está nesse
# contexto, é a autoridade, não um proponente.
_PREAMBULO = re.compile(r"neste ato representad|doravante denominad|órg[ãa]o gerenciador|"
                        r"\bcontratante\b|autoridade competente|pregoeir|entidade promotora|"
                        r"ora denominad|qualificada? como contratante", re.I)


def _so_digitos(s: str) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


def _cnpj_dv_ok(c: str) -> bool:
    """Dígitos verificadores do CNPJ (módulo 11) — separa CNPJ real de nº de processo."""
    if len(c) != 14 or c == c[0] * 14:
        return False
    pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    for n in (12, 13):
        d = sum(int(a) * b for a, b in zip(c[:n], ([6] + pesos) if n == 13 else pesos)) % 11
        if c[n] != str(0 if 11 - d > 9 else 11 - d):
            return False
    return True


def extrair_participantes_ata(texto: str, janela: int = 140, orgao_cnpj: str | None = None) -> dict:
    """Best-effort: de UMA ata/julgamento, extrai os licitantes (CNPJ) e o resultado de cada um
    pelo marcador mais próximo (janela de chars). Retorna
    {participantes:[{cnpj, venceu:bool|None}], n_cnpj, avaliavel}. Honesto: venceu=None quando o
    texto não sustenta o resultado; avaliavel=False se <2 CNPJs (não dá para inferir competição).

    Exclui a autoridade contratante: o ``orgao_cnpj`` do certame e todo CNPJ em contexto de
    PREÂMBULO ('neste ato representada', 'contratante', 'pregoeiro') — que não é proponente.
    Só entra como licitante o CNPJ que carrega um marcador de RESULTADO (vencedor/perdedor) por
    perto; CNPJ sem resultado E sem contexto de disputa é descartado (era o vetor de FP)."""
    t = re.sub(r"[ \t\n]+", " ", texto or "")
    org = _so_digitos(orgao_cnpj or "")
    matches = list(_CNPJ.finditer(t))
    starts = [mm.start() for mm in matches]
    vistos: dict[str, dict] = {}
    for idx, m in enumerate(matches):
        cnpj = _so_digitos(m.group(1))
        if "." not in m.group(1) and not _cnpj_dv_ok(cnpj):
            continue  # 14 dígitos crus sem DV válido = nº de processo, não licitante
        if cnpj in vistos or (org and cnpj == org):
            continue
        i, fim = m.start(), m.end()
        # o resultado, em ata, vem DEPOIS do CNPJ e antes do próximo CNPJ (fronteira do segmento).
        prox = starts[idx + 1] if idx + 1 < len(starts) else len(t)
        prev_fim = matches[idx - 1].end() if idx > 0 else 0  # fronteira do CNPJ anterior
        fwd = t[fim:min(prox, fim + janela)]
        # preâmbulo (autoridade contratante) — só no SEGMENTO deste CNPJ (entre o anterior e o próximo),
        # senão o 'neste ato representada' de um órgão contamina os licitantes seguintes.
        seg = t[max(prev_fim, i - 60):min(prox, fim + janela)]
        if _PREAMBULO.search(seg):
            continue
        venc = _VENC.search(fwd)
        perd = _PERD.search(fwd)
        if not venc and not perd:
            continue  # sem marcador de resultado no segmento do CNPJ → não afirma que competiu
        if venc and not perd:
            resultado = True
        elif perd and not venc:
            resultado = False
        else:
            resultado = venc.start() < perd.start()  # o primeiro marcador após o CNPJ decide
        vistos[cnpj] = {"cnpj": cnpj, "venceu": resultado}
    parts = list(vistos.values())
    return {"participantes": parts, "n_cnpj": len(parts), "avaliavel": len(parts) >= 2}


# ── grafo (determinístico, testável) ─────────────────────────────────────────

def construir_grafo(registros: list[dict]) -> dict:
    """Agrega registros de certame num grafo licitante×licitante.

    registro = {certame: str, participantes: [{cnpj/id, venceu: bool|None}], data?, orgao?}.
    Retorna {licitantes:{id:{n_certames,n_vitorias,co:{outro:vezes}}}, pares:{(a,b):{juntos,
    a_venceu,b_venceu}}, n_certames}. Só considera certames com ≥2 participantes (houve disputa)."""
    lic: dict[str, dict] = defaultdict(lambda: {"n_certames": 0, "n_vitorias": 0, "co": defaultdict(int)})
    pares: dict[tuple, dict] = defaultdict(lambda: {"juntos": 0, "a_venceu": 0, "b_venceu": 0})
    n_certames = 0
    for reg in registros:
        parts = reg.get("participantes") or []
        ids = []
        venc_ids = set()
        for p in parts:
            pid = _so_digitos(p.get("cnpj") or p.get("id") or "") or (p.get("id") or "")
            if not pid:
                continue
            ids.append(pid)
            if p.get("venceu") is True:
                venc_ids.add(pid)
        ids = sorted(set(ids))
        if len(ids) < 2:
            continue  # sem disputa registrada → não entra no grafo de rodízio
        n_certames += 1
        for pid in ids:
            lic[pid]["n_certames"] += 1
            if pid in venc_ids:
                lic[pid]["n_vitorias"] += 1
        for a, b in combinations(ids, 2):
            lic[a]["co"][b] += 1
            lic[b]["co"][a] += 1
            key = (a, b)
            pares[key]["juntos"] += 1
            if a in venc_ids:
                pares[key]["a_venceu"] += 1
            if b in venc_ids:
                pares[key]["b_venceu"] += 1
    # normaliza defaultdicts para dict comum (serializável)
    return {
        "licitantes": {k: {"n_certames": v["n_certames"], "n_vitorias": v["n_vitorias"],
                           "co": dict(v["co"])} for k, v in lic.items()},
        "pares": {f"{a}|{b}": v for (a, b), v in pares.items()},
        "n_certames": n_certames,
    }


def detectar_padroes(grafo: dict, min_certames: int = 3, min_juntos: int = 3) -> dict:
    """Extrai os indícios de conluio do grafo. Thresholds conservadores (default 3) — abaixo
    disso a amostra não sustenta padrão. Retorna {cobertura, rodizio, roster}, cada um lista de
    indícios com os números que os sustentam. INDÍCIO a verificar, jamais conclusão."""
    lics = grafo.get("licitantes", {})
    pares = grafo.get("pares", {})

    # (1) cobertura / licitante-fantasma: participa ≥K e NUNCA vence
    cobertura = []
    for lid, v in lics.items():
        if v["n_certames"] >= min_certames and v["n_vitorias"] == 0:
            # com quem ele "perde junto" — o beneficiário provável da cobertura
            top_co = sorted(v["co"].items(), key=lambda kv: -kv[1])[:3]
            cobertura.append({"licitante": lid, "participou": v["n_certames"], "venceu": 0,
                              "co_frequentes": top_co})
    cobertura.sort(key=lambda x: -x["participou"])

    # (2) rodízio: par co-ocorre ≥K e AMBOS vencem (alternância) estando o outro presente
    rodizio = []
    for key, p in pares.items():
        a, b = key.split("|")
        if p["juntos"] >= min_juntos and p["a_venceu"] >= 1 and p["b_venceu"] >= 1:
            # quão "equilibrada" é a alternância (1.0 = perfeita) — mais suspeita quanto mais equilibrada
            tot = p["a_venceu"] + p["b_venceu"]
            equilibrio = 1 - abs(p["a_venceu"] - p["b_venceu"]) / tot if tot else 0
            rodizio.append({"par": [a, b], "juntos": p["juntos"],
                            "vitorias": [p["a_venceu"], p["b_venceu"]],
                            "equilibrio": round(equilibrio, 2)})
    rodizio.sort(key=lambda x: (-x["juntos"], -x["equilibrio"]))

    # (3) roster de cartel: componentes de co-participação densa (par junto ≥K vira aresta)
    adj: dict[str, set] = defaultdict(set)
    for key, p in pares.items():
        if p["juntos"] >= min_juntos:
            a, b = key.split("|")
            adj[a].add(b)
            adj[b].add(a)
    roster = []
    visto: set = set()
    for n in adj:
        if n in visto:
            continue
        # BFS do componente conexo
        comp, fila = set(), [n]
        while fila:
            x = fila.pop()
            if x in comp:
                continue
            comp.add(x)
            visto.add(x)
            fila.extend(adj[x] - comp)
        if len(comp) >= 3:  # trio+ que anda junto = roster candidato
            roster.append({"membros": sorted(comp), "tamanho": len(comp)})
    roster.sort(key=lambda x: -x["tamanho"])

    return {"cobertura": cobertura, "rodizio": rodizio, "roster": roster,
            "n_certames": grafo.get("n_certames", 0),
            "ressalva": "Indício de conluio a verificar (OCDE bid rigging); presunção de legitimidade — "
                        "corroborar QSA, endereços, propostas e cronologia. Indício ≠ acusação."}


def analisar_atas(atas: list[dict], min_certames: int = 3, min_juntos: int = 3) -> dict:
    """Pipeline completo: lista de {certame, texto[, data, orgao]} → extrai → grafo → padrões.
    Reporta COBERTURA da extração (quantas atas viraram registro avaliável) — honestidade epistêmica."""
    registros, avaliaveis = [], 0
    for a in atas:
        ext = extrair_participantes_ata(a.get("texto") or "", orgao_cnpj=a.get("orgao"))
        if ext["avaliavel"]:
            avaliaveis += 1
            registros.append({"certame": a.get("certame"), "data": a.get("data"),
                              "orgao": a.get("orgao"), "participantes": ext["participantes"]})
    grafo = construir_grafo(registros)
    padroes = detectar_padroes(grafo, min_certames=min_certames, min_juntos=min_juntos)
    padroes["cobertura_extracao"] = {"atas_entrada": len(atas), "atas_avaliaveis": avaliaveis,
                                     "certames_no_grafo": grafo["n_certames"]}
    return padroes


# termos genéricos de compra pública que NÃO discriminam o objeto (não entram na similaridade)
_STOP_OBJ = {
    "contratacao", "contratacoes", "empresa", "empresas", "especializada", "aquisicao", "aquisicoes",
    "prestacao", "servico", "servicos", "fornecimento", "registro", "precos", "preco", "objeto",
    "para", "com", "por", "dos", "das", "que", "atender", "atendimento", "eventual", "futura",
    "material", "materiais", "diversos", "diversas", "conforme", "termo", "referencia", "edital",
    "pregao", "eletronico", "licitacao", "compra", "compras", "visando", "destinado", "destinada",
    "necessidade", "necessidades", "demanda", "demandas", "presente", "instrumento", "solucao",
    # boilerplate administrativo (não discrimina o objeto; nomes de órgão inflam falsamente a coesão)
    "municipio", "municipal", "camara", "prefeitura", "secretaria", "fundo", "estado", "estadual",
    "federal", "governo", "instituto", "fundacao", "autarquia", "departamento", "superintendencia",
}


def _termos_objeto(texto: str) -> frozenset:
    """Termos SIGNIFICATIVOS do objeto (normalizado, sem stopwords de compra pública). Discrimina
    'ventilador' de 'vestibular' — a base do gate de similaridade do rodízio."""
    import unicodedata
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    toks = re.findall(r"[a-z]{4,}", t)
    return frozenset(w for w in toks if w not in _STOP_OBJ)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _clusters_por_objeto(certames: list[dict], limiar: float = 0.30) -> list[list[dict]]:
    """Agrupa (guloso) os certames de um órgão por similaridade de objeto. Certames SEM objeto
    (termos vazios) caem num único cluster '∅' — preserva o comportamento sem-gate (grafo/sintético)."""
    sem_obj = [c for c in certames if not c["_termos"]]
    com_obj = [c for c in certames if c["_termos"]]
    clusters: list[list[dict]] = []
    reps: list[frozenset] = []  # termos representativos (união) de cada cluster
    for c in sorted(com_obj, key=lambda x: -len(x["_termos"])):
        melhor, melhor_sim = -1, 0.0
        for i, rep in enumerate(reps):
            s = _jaccard(c["_termos"], rep)
            if s > melhor_sim:
                melhor, melhor_sim = i, s
        if melhor >= 0 and melhor_sim >= limiar:
            clusters[melhor].append(c)
            reps[melhor] = reps[melhor] | c["_termos"]
        else:
            clusters.append([c])
            reps.append(set(c["_termos"]))
    if sem_obj:
        clusters.append(sem_obj)  # bucket ∅
    return clusters


def detectar_rodizio_vencedores(registros: list[dict], min_certames: int = 5,
                                limiar_objeto: float = 0.30) -> dict:
    """Rodízio/captura a partir de VENCEDORES por certame (dados estruturados do PNCP, que só
    publica o homologado). Captura é ÓRGÃO-level; RODÍZIO passa por um GATE DE SIMILARIDADE DE OBJETO:

      • **captura** — 1 fornecedor vence ≥80% dos certames do órgão (mercado capturado);
      • **rodízio** — 2-3 fornecedores repartem ~igualmente as vitórias DENTRO DE UM MESMO TIPO DE
        OBJETO (não do órgão inteiro). Certames com objetos diversos caem em clusters distintos e NÃO
        contam como rodízio — corta o falso-positivo 'A vence ventilador, B vence vestibular'.

    Cada rodízio traz `coesao_objeto` (similaridade média do cluster) e `termos_comuns` (o que os
    certames compartilham) para o humano julgar. INDÍCIO a verificar — corroborar propostas/QSA."""
    from collections import Counter
    from itertools import combinations
    por_orgao: dict[str, list] = defaultdict(list)
    for r in registros:
        org = _so_digitos(r.get("orgao") or "")
        vs = r.get("vencedores") or []
        if not org or not vs:
            continue
        venc = max(vs, key=lambda x: x.get("valor") or 0)  # vencedor dominante (maior valor)
        # remove os tokens do NOME DO ÓRGÃO do objeto (senão 'paty alferes itabapoana' viram
        # coesão falsa entre objetos diversos do mesmo município)
        termos = _termos_objeto(r.get("objeto") or "") - _termos_objeto(r.get("orgao_nome") or "")
        por_orgao[org].append({"certame": r.get("certame"), "data": r.get("data"),
                               "cnpj": _so_digitos(venc.get("cnpj") or ""),
                               "nome": venc.get("nome"), "_termos": termos})
    captura, rodizio = [], []
    for org, certames in por_orgao.items():
        # CAPTURA é órgão-level (concentração vale para o conjunto do órgão)
        if len(certames) >= min_certames:
            cont_org = Counter(c["cnpj"] for c in certames if c["cnpj"])
            if cont_org:
                top_cnpj, top_n = cont_org.most_common(1)[0]
                share = top_n / len(certames)
                if share >= 0.80:
                    nome_top = next((c["nome"] for c in certames if c["cnpj"] == top_cnpj), "?")
                    captura.append({"orgao": org, "certames": len(certames), "vencedor": top_cnpj,
                                    "nome": nome_top, "share": round(share, 2), "distintos": len(cont_org)})
        # RODÍZIO por CLUSTER DE OBJETO (gate de similaridade)
        for grupo in _clusters_por_objeto(certames, limiar=limiar_objeto):
            n = len(grupo)
            if n < min_certames:
                continue
            cont = Counter(c["cnpj"] for c in grupo if c["cnpj"])
            if not (2 <= len(cont) <= 3) or cont.most_common(1)[0][1] >= n:
                continue
            cobre = sum(v for _, v in cont.most_common(3)) / n
            if cobre < 0.9:
                continue
            termos = [c["_termos"] for c in grupo if c["_termos"]]
            comuns = frozenset.intersection(*termos) if termos else frozenset()
            if termos:  # há objeto → o gate exige coesão real (senão são compras diversas coincidentes)
                coesao = sum(_jaccard(a, b) for a, b in combinations(termos, 2)) / max(1, len(termos) * (len(termos) - 1) // 2)
                if coesao < limiar_objeto and not comuns:
                    continue
                coesao = round(coesao, 2)
            else:
                coesao = None  # bucket ∅ (sem objeto): rodízio órgão-level, sem gate (compat)
            rodizio.append({"orgao": org, "certames": n, "grupo": list(cont.keys()),
                            "reparticao": dict(cont), "cobertura_grupo": round(cobre, 2),
                            "coesao_objeto": coesao, "termos_comuns": sorted(comuns)[:6]})
    captura.sort(key=lambda x: -x["certames"])
    rodizio.sort(key=lambda x: (-(x["coesao_objeto"] or 0), -x["certames"]))
    return {"captura": captura, "rodizio_vencedores": rodizio, "n_orgaos": len(por_orgao),
            "ressalva": "Indício a verificar (OCDE): concentração pode ser mérito ou mercado raso; "
                        "rodízio (mesmo objeto) pede exame das propostas e do QSA. Indício ≠ acusação."}


def coletar_atas_do_corpus(db_path: str = "data/compliance.db", limite: int = 8000) -> list[dict]:
    """Lê o corpus de editais/atas já coletado (edital_documento) filtrando os que têm marcadores de
    RESULTADO (vencedor/adjudicado + inabilitado). Certame = numero_controle_pncp; órgão = orgao_cnpj."""
    import sqlite3
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT numero_controle_pncp npc, orgao_cnpj, texto FROM edital_documento "
            "WHERE texto LIKE '%inabilitad%' AND (texto LIKE '%vencedor%' OR texto LIKE '%adjudicad%') "
            "AND length(texto) > 1500 LIMIT ?", (limite,)).fetchall()
    finally:
        con.close()
    # pós-filtro: o LIKE acima é satisfeito pelo BOILERPLATE de edital ("será inabilitado o
    # licitante que…"); só entra no grafo o texto com marcador REAL de ata/sessão de julgamento.
    from compliance_agent.detectores.coletor_ata import _RX_ATA_MARCADOR
    out = [{"certame": r["npc"], "orgao": r["orgao_cnpj"], "texto": r["texto"]}
           for r in rows if _RX_ATA_MARCADOR.search(r["texto"])]
    # atas de julgamento REAIS coletadas do PNCP (atas_julgamento — a fonte densa de perdedoras)
    con2 = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con2.row_factory = sqlite3.Row
    try:
        vistos = {a["certame"] for a in out}
        for r in con2.execute("SELECT certame, orgao_cnpj, texto FROM ata_documento"):
            if r["certame"] not in vistos:
                out.append({"certame": r["certame"], "orgao": r["orgao_cnpj"], "texto": r["texto"]})
    except sqlite3.OperationalError as exc:
        logger.debug("ata_documento ainda ausente (sweep de atas não rodou): %s", exc)
    finally:
        con2.close()
    return out


def _nome(cnpj: str, db_path: str = "data/compliance.db") -> str:
    import sqlite3
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        r = con.execute("SELECT favorecido_nome FROM favorecido_resumo WHERE "
                        "replace(replace(replace(favorecido_cpf,'.',''),'/',''),'-','')=? LIMIT 1",
                        (cnpj,)).fetchone()
        return (r[0] if r and r[0] else "?")
    except sqlite3.Error:
        return "?"
    finally:
        con.close()


if __name__ == "__main__":
    import json
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else "data/compliance.db"
    atas = coletar_atas_do_corpus(db)
    r = analisar_atas(atas, min_certames=3, min_juntos=2)
    print(f"# GRAFO DE RODÍZIO CROSS-ATA\n\nCobertura da extração: {r['cobertura_extracao']}")
    print(f"\n## Licitantes-fantasma (cobertura — participam e nunca vencem): {len(r['cobertura'])}")
    for c in r["cobertura"][:20]:
        print(f"- {c['licitante']} ({_nome(c['licitante'], db)[:40]}): {c['participou']}×, 0 vitória")
    print(f"\n## Rodízio (pares que alternam vitórias): {len(r['rodizio'])}")
    for x in r["rodizio"][:20]:
        print(f"- {x['par']} — juntos {x['juntos']}×, vitórias {x['vitorias']}, equilíbrio {x['equilibrio']}")
    print(f"\n## Rosters (grupos que andam juntos): {len(r['roster'])}")
    for x in r["roster"][:10]:
        print(f"- {x['tamanho']} membros: {x['membros']}")
    print(f"\n{r['ressalva']}")
    print("\n" + json.dumps(r["cobertura_extracao"]))
