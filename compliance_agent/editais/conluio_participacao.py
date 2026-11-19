# -*- coding: utf-8 -*-
"""Conluio por PARTICIPAÇÃO — quem sempre perde para o mesmo, quem nunca se separa, quem se reveza.

Pedido do dono (18/11/2026): "tem empresas que o direcionamento pode ser comprovado pelo fato de
sempre participarem com outras e nunca ganharem nada". Literatura: OCDE, *Guidelines for Fighting
Bid Rigging in Public Procurement* (2009/2025) — cover bidding, bid rotation, bid suppression;
CADE, *Guia de Combate a Cartéis em Licitação* (2019) — "propostas de cobertura" e "rodízio";
Imhof, Karagök & Rutz (2018) e Huber & Imhof (2019) — screens sobre o comportamento recorrente dos
licitantes; Conley & Decarolis (2016) — o teste de participação conjunta contra o acaso.

TRÊS PADRÕES, TODOS CONTRA O ACASO DO PRÓPRIO MERCADO:
  1. **Perdedor de cobertura** (B): participou ≥ `MIN_PARTICIPACOES` vezes, nunca venceu nada na
     fonte, e ≥ `FIDELIDADE_MIN` das suas participações foram certames vencidos pelo MESMO A.
  2. **Par inseparável**: duas empresas que aparecem juntas em quase todo certame de qualquer uma
     delas (Jaccard ≥ `JACCARD_MIN`) — figurantes que andam em bloco.
  3. **Rodízio**: duas empresas que disputam juntas e cada uma já venceu a outra ≥ 2 vezes,
     levando ≥ `PARTILHA_MIN` dos certames em que se encontram.

POR QUE O ANTECESSOR NÃO SERVE. `editais/screens_participacao.pares_cobertura` mede o lift contra
o universo inteiro: o "esperado" de duas empresas de um município pequeno se encontrarem em 15 mil
certames de 91 entes é 0,0 — medido em 18/11/2026, os 10 primeiros pares tinham lift 1.286× a
2.572× com 4 encontros. Ranquear por esse lift é ranquear por raridade. Aqui o esperado é calculado
por MERCADO (ente × tipologia do TCE-RJ) e, para cobertura, também por NICHO (certames do mesmo
ente com objeto parecido): perder sempre para quem vence 80% do nicho é o acaso, não conluio.

ESTATÍSTICA. Encontros observados k contra esperado λ = Σ (probabilidade de A vencer / de os dois
estarem) certame a certame; p = P(Poisson(λ) ≥ k). A Poisson tem variância ≥ a da hipergeométrica
exata (sorteio sem reposição dentro do mercado), então o p é CONSERVADOR. Corte de Bonferroni sobre
o número de pares efetivamente testados (`ALFA / m`) — com 14 mil pares, p < 0,05 isolado daria
centenas de falsos alarmes.

LEITURA DO CERTAME (defeitos medidos no dado real):
  · 15.064 (ente, processo, participante) aparecem como VENCEDOR e PERDEDOR — pregão por item.
    Perdedor do certame é quem participou e NÃO venceu nenhum item.
  · Credenciamento (todos "vencem"), chamamento, leilão (quem disputa é comprador), alienação e
    permissão de uso não são disputa de preço: ficam fora.
  · A fonte identifica por NOME. `resolver_cnpj` só resolve razão social única na Receita (ou única
    entre as de estabelecimento no RJ); o resto fica sem CNPJ e sem vínculo — INDISPONÍVEL, não 0.

HONESTIDADE. Tudo é INDÍCIO a verificar (presunção de legitimidade; art. 337-F CP e art. 36 da Lei
12.529 exigem prova do ajuste). Cada achado leva as explicações inocentes testadas. Valores dos
certames são VALOR HOMOLOGADO do TCE-RJ — não é pagamento. Pagamento só por OB do SIAFE, e o SIAFE é
do Estado: certame municipal não tem OB do Estado (a coluna diz isso, não 0).

CLI:  python -m compliance_agent.editais.conluio_participacao [--gravar] [--top 15]
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from compliance_agent.editais.screens_participacao import normalizar_nome
from compliance_agent.osint.marca_grupo import mesmo_grupo

MIN_PARTICIPACOES = 5      # perdedor de cobertura: abaixo disso é anedota
MIN_ENCONTROS = 4          # A venceu com B perdendo, no mínimo
FIDELIDADE_MIN = 0.6       # ≥ 60% das participações de B foram certames vencidos por A
MIN_JUNTOS = 5             # par inseparável
JACCARD_MIN = 0.8
MIN_JUNTOS_RODIZIO = 4
MIN_VITORIAS_CRUZADAS = 2  # cada um venceu o outro ≥ 2×
PARTILHA_MIN = 0.7         # o par leva ≥ 70% dos certames em que se encontra
ALFA = 0.01                # antes de Bonferroni
MAX_PARTICIPANTES_PAR = 40  # certame-ônibus (registro de preço com dezenas de itens) não informa par
PREFIXO_MIN = 30           # razão cortada pelo ente: prefixo só a partir de 30 caracteres
SIM_NICHO = 0.3            # Jaccard de tokens do objeto para "mesmo nicho"

_SEM_DISPUTA_MOD = ("CREDENCIAMENTO", "CHAMAMENTO", "LEILAO")
_SEM_DISPUTA_TIP = ("CHAMAMENTO", "ALIENACAO", "PERMISSAO DE USO")
_STOP = {"AQUISICAO", "CONTRATACAO", "EMPRESA", "PARA", "PRESTACAO", "SERVICO", "SERVICOS", "DESTINADOS",
         "ATENDER", "ATENDIMENTO", "SECRETARIA", "MUNICIPAL", "MUNICIPIO", "REGISTRO", "PRECOS", "PRECO",
         "EVENTUAL", "FUTURA", "FORNECIMENTO", "OBJETO", "PRESENTE", "LICITACAO", "MATERIAL", "MATERIAIS",
         "DIVERSOS", "DEMANDA", "CONFORME", "ESPECIFICACOES", "TERMO", "REFERENCIA", "ANEXO", "COM", "DOS",
         "DAS", "PELA", "PELO", "VISANDO", "ATRAVES", "MEDIANTE", "SOB", "REGIME", "UNIDADES", "SAUDE"}

# mesmo piso do coletor (compliance_agent/collectors/tcerj_licitantes.MAX_HOMOLOGADO_SOBRE_ESTIMADO)
MAX_HOMOLOGADO_SOBRE_ESTIMADO = 10.0
SAIDA = Path("data/conluio/participacao.json")
RESSALVA = ("Indício a verificar, nunca acusação. Fonte: licitantes declarados ao TCE-RJ (dados abertos, "
            "municípios jurisdicionados, 2024–2026), identificados por NOME; CNPJ só por razão social única. "
            "Valor = homologado no certame (não é pagamento). OB do SIAFE é do Estado e não cobre certame "
            "municipal. Explicações inocentes testadas ao lado de cada achado.")


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()


def cauda_poisson(k: int, lam: float) -> float:
    """P(X ≥ k), X ~ Poisson(lam). Soma a cauda direto (sem 1 − CDF) para não perder p minúsculo."""
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    log_t = -lam + k * math.log(lam) - math.lgamma(k + 1)
    t, s, i = math.exp(log_t), 0.0, k
    if t == 0.0:                       # underflow: devolve o termo líder em escala de log, nunca 0
        return math.exp(max(log_t, -745.0)) or 5e-324
    while True:
        s += t
        i += 1
        t *= lam / i
        if t < s * 1e-17:
            break
    return min(1.0, s)


def _tokens(objeto: str) -> frozenset:
    return frozenset(w for w in re.findall(r"[A-Z]{4,}", _sem_acento(objeto)) if w not in _STOP)


def _jac(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


# ───────────────────────── leitura ───────────────────────────────────────────────────────────

def certames_tcerj(con: sqlite3.Connection) -> list[dict]:
    """Um registro por certame com disputa: vencedores, perdedores (participou e não venceu nada)."""
    try:
        cur = con.execute(
            "SELECT ente, ano, processo, participante, resultado, modalidade, tipologia, objeto, "
            "valor_homologacao, data_homologacao, tipo_participacao, valor_estimado FROM tcerj_licitante "
            "WHERE COALESCE(participante,'') <> ''")
        linhas = cur.fetchall()
    except sqlite3.OperationalError:
        return []
    cert: dict[tuple, dict] = {}
    for ente, ano, proc, part, res, mod, tip, obj, vh, data, tipo, ve in linhas:
        m, t = _sem_acento(mod), _sem_acento(tip)
        if any(x in m for x in _SEM_DISPUTA_MOD) or any(t.startswith(x) for x in _SEM_DISPUTA_TIP):
            continue
        nome = normalizar_nome(part)
        if not nome:
            continue
        d = cert.setdefault((ente, ano, proc), {
            "chave": f"{ente}|{ano}|{proc}", "ente": ente, "ano": ano, "processo": proc,
            "tipologia": tip or "", "modalidade": mod or "", "objeto": obj or "", "data": data or "",
            "valor_homologacao": None, "vencedores": set(), "participantes": set(),
            "consorcio": set(), "nomes": {}})
        d["participantes"].add(nome)
        d["nomes"].setdefault(nome, part)
        if str(tipo or "").upper() == "CONSORCIO":
            d["consorcio"].add(nome)
        if str(res).upper() == "VENCEDOR":
            d["vencedores"].add(nome)
        # O campo é o TOTAL do processo, repetido em toda linha (vencedor e perdedor) — somar por vencedor
        # multiplicava (medido: "R$ 1,04 bi" para um par de Belford Roxo). Homologado > 10× o estimado é
        # defeito da fonte (o coletor mede: 1,1% das linhas carregam 87,4% da soma) e vira ausente.
        if vh and not (ve and float(ve) > 0 and float(vh) > MAX_HOMOLOGADO_SOBRE_ESTIMADO * float(ve)):
            d["valor_homologacao"] = max(d["valor_homologacao"] or 0.0, float(vh))
    out = []
    for d in cert.values():
        d["perdedores"] = d["participantes"] - d["vencedores"]
        out.append(d)
    out.sort(key=lambda d: d["chave"])
    return out


# ───────────────────────── análise ───────────────────────────────────────────────────────────

def _mercado(c: dict) -> tuple:
    return (c["ente"], c["tipologia"])


def analisar(certames: list[dict], *, alfa: float = ALFA) -> dict[str, Any]:
    cs = [c for c in certames if len(c["participantes"]) >= 2 and c["vencedores"]]
    n_merc = Counter(_mercado(c) for c in cs)
    vit_merc: Counter = Counter()
    part_merc: Counter = Counter()
    part, vit = Counter(), Counter()
    de: dict[str, list[dict]] = defaultdict(list)
    for c in cs:
        m = _mercado(c)
        for a in c["vencedores"]:
            vit_merc[(a, m)] += 1
            vit[a] += 1
        for a in c["participantes"]:
            part_merc[(a, m)] += 1
            part[a] += 1
            de[a].append(c)
    por_ente: dict[str, list[dict]] = defaultdict(list)
    for c in cs:
        c["_tok"] = _tokens(c["objeto"])
        por_ente[c["ente"]].append(c)
    ctx = {"por_ente": por_ente, "cs": cs, "n_merc": n_merc, "vit_merc": vit_merc, "part_merc": part_merc,
           "part": part, "vit": vit, "de": de, "alfa": alfa}
    return {"n_certames": len(certames), "n_certames_com_disputa": len(cs),
            "cobertura": _cobertura(ctx), "inseparaveis": _inseparaveis(ctx), "rodizio": _rodizio(ctx)}


def _nicho(ctx, a: str, certs: list[dict]) -> tuple[int, int]:
    """(certames do nicho, vencidos por A): mesmo ente, objeto parecido com algum dos certames dados."""
    nicho = _certames_do_nicho(ctx, certs)
    return len(nicho), sum(1 for c in nicho if a in c["vencedores"])


def _certames_do_nicho(ctx, certs: list[dict]) -> list[dict]:
    """Certames dos mesmos entes com objeto parecido (Jaccard de tokens ≥ SIM_NICHO) com algum dos dados.
    O mercado ente×tipologia do TCE-RJ é largo demais ('OUTROS SERVIÇOS' tem 3.670 certames): seguro de
    frota e material odontológico são nichos de meia dúzia de fornecedores dentro dele."""
    toks = {c["_tok"] for c in certs}
    vistos, out = set(), []
    for e in sorted({c["ente"] for c in certs}):
        for c in ctx["por_ente"].get(e, ()):
            if c["chave"] not in vistos and any(_jac(c["_tok"], t) >= SIM_NICHO for t in toks):
                vistos.add(c["chave"])
                out.append(c)
    return out


def _nicho_par(ctx, a: str, b: str, certs: list[dict]) -> tuple[float, int]:
    """Esperado de a e b juntos se participassem por acaso DENTRO do nicho: n_a·n_b/N."""
    nicho = [c for c in _certames_do_nicho(ctx, certs) if len(c["participantes"]) <= MAX_PARTICIPANTES_PAR]
    na = sum(1 for c in nicho if a in c["participantes"])
    nb = sum(1 for c in nicho if b in c["participantes"])
    return (na * nb / len(nicho) if nicho else 0.0), len(nicho)


def _juntos_de(ctx, a: str, b: str) -> list[dict]:
    return [c for c in ctx["de"][a] if b in c["participantes"] and len(c["participantes"]) <= MAX_PARTICIPANTES_PAR]


def _explicacoes(ctx, a: str, b: str, juntos: list[dict]) -> list[dict]:
    ex = []
    g = mesmo_grupo(a, b)
    if g:
        ex.append({"tipo": "grupo_aparente", "detalhe": f"marca comum aparente '{g}' — grupo econômico declarado "
                   "não concorre de verdade, mas também não é conluio oculto; conferir QSA"})
    if any(a in c["consorcio"] or b in c["consorcio"] for c in juntos):
        ex.append({"tipo": "consorcio", "detalhe": "participação como consórcio em ao menos um certame"})
    so_dois = sum(1 for c in juntos if len(c["participantes"]) == 2)
    if so_dois == len(juntos):
        ex.append({"tipo": "mercado_restrito", "detalhe": "em todos os encontros só os dois disputaram — "
                   "mercado de poucos fornecedores explica parte; também é o desenho da cobertura única"})
    multi = sum(1 for c in juntos if len(c["vencedores"]) >= 3)
    if multi * 2 > len(juntos):
        ex.append({"tipo": "multi_vencedor", "detalhe": f"{multi} de {len(juntos)} encontros foram certames com 3+ "
                   "vencedores (pregão por item): perder 'para A' ali é perder itens que A dividiu com outros"})
    entes = sorted({c["ente"] for c in juntos})
    if len(entes) == 1:
        ex.append({"tipo": "regional", "detalhe": f"todos os encontros em {entes[0]} — fornecedores locais "
                   "se encontram mais; o esperado já é calculado por mercado do mesmo ente"})
    return ex


def _soma_vh(cs: list[dict]) -> dict:
    """Soma do valor homologado dos PROCESSOS (total do certame, não a parcela de cada vencedor)."""
    com = [c["valor_homologacao"] for c in cs if c["valor_homologacao"] is not None]
    return {"valor": round(sum(com), 2), "processos_com_valor": len(com), "processos": len(cs),
            "natureza": "homologado do processo inteiro (TCE-RJ) — não é a parcela do vencedor nem pagamento"}


def _resumo_certame(c: dict) -> dict:
    return {"chave": c["chave"], "ente": c["ente"], "processo": c["processo"], "data": c["data"],
            "modalidade": c["modalidade"], "tipologia": c["tipologia"], "objeto": c["objeto"][:160],
            "vencedores": sorted(c["vencedores"]), "n_participantes": len(c["participantes"]),
            "valor_homologado_do_processo": (round(c["valor_homologacao"], 2)
                                             if c["valor_homologacao"] is not None else "INDISPONÍVEL")}


def _cobertura(ctx) -> dict:
    cs, part, vit, de = ctx["cs"], ctx["part"], ctx["vit"], ctx["de"]
    # Só certame de VENCEDOR ÚNICO conta encontro: no pregão por item com 3+ vencedores, "perder para A"
    # é perder itens que A dividiu com outros (os 8 primeiros achados de 18/11/2026 eram todos assim).
    enc: Counter = Counter()
    for c in cs:
        if len(c["vencedores"]) != 1:
            continue
        for b in c["perdedores"]:
            for a in c["vencedores"]:
                enc[(a, b)] += 1
    funil = {"pares_brutos": len(enc)}
    cand = [(a, b, k) for (a, b), k in enc.items() if k >= MIN_ENCONTROS]
    funil["com_min_encontros"] = len(cand)
    cand = [(a, b, k) for a, b, k in cand if vit[b] == 0 and part[b] >= MIN_PARTICIPACOES]
    funil["perdedor_nunca_venceu"] = len(cand)
    cand = [(a, b, k) for a, b, k in cand if k / part[b] >= FIDELIDADE_MIN]
    funil["fidelidade"] = len(cand)
    m_testes = max(1, sum(1 for k in enc.values() if k >= 3))
    alfa_c = ctx["alfa"] / m_testes
    achados, sem_nicho = [], 0
    for a, b, k in cand:
        lam = sum(ctx["vit_merc"][(a, _mercado(c))] / ctx["n_merc"][_mercado(c)] for c in de[b])
        p = cauda_poisson(k, lam)
        if p >= alfa_c:
            continue
        juntos = [c for c in de[b] if c["vencedores"] == {a}]
        n_nicho, a_nicho = _nicho(ctx, a, juntos)
        lam_n = part[b] * (a_nicho / n_nicho) if n_nicho else 0.0
        p_n = cauda_poisson(k, lam_n)
        ex = _explicacoes(ctx, a, b, juntos)
        if p_n >= alfa_c:
            sem_nicho += 1
            ex.append({"tipo": "nicho_dominado", "detalhe": f"{a} venceu {a_nicho} de {n_nicho} certames de objeto "
                       f"parecido no mesmo ente ({a_nicho / max(1, n_nicho):.0%}) — perder sempre para quem domina o "
                       "nicho é esperado; não passa no corte do nicho"})
        achados.append({
            "vencedor": a, "perdedor": b, "encontros": k, "participacoes_do_perdedor": part[b],
            "vitorias_do_perdedor": vit[b], "fidelidade": round(k / part[b], 3),
            "vitorias_do_vencedor": vit[a], "participacoes_do_vencedor": part[a],
            "dependencia_do_vencedor": round(k / max(1, vit[a]), 3),
            "esperado_mercado": round(lam, 3), "p_valor": p, "esperado_nicho": round(lam_n, 3), "p_valor_nicho": p_n,
            "passa_nicho": p_n < alfa_c, "entes": sorted({c["ente"] for c in juntos}),
            "valor_homologado_ao_vencedor": _soma_vh(juntos),
            "certames": [_resumo_certame(c) for c in sorted(juntos, key=lambda c: c["data"])],
            "nomes_crus": {a: juntos[0]["nomes"].get(a, a), b: juntos[0]["nomes"].get(b, b)},
            "explicacoes_inocentes": ex,
            "texto": (f"{b} participou de {part[b]} certame(s), nunca venceu, e em {k} deles perdeu para {a}; "
                      f"pelo mercado o acaso daria {lam:.2f} (p={p:.1e})"),
        })
    funil["acima_do_acaso_corrigido"] = len(achados)
    funil["acima_do_acaso_do_nicho"] = len(achados) - sem_nicho
    achados.sort(key=lambda d: (not d["passa_nicho"], d["p_valor"]))
    return {"achados": achados, "funil": funil, "pares_testados": m_testes, "alfa_corrigido": alfa_c}


def _pares_juntos(cs) -> Counter:
    juntos: Counter = Counter()
    for c in cs:
        ps = sorted(c["participantes"])
        if len(ps) > MAX_PARTICIPANTES_PAR:
            continue
        for a, b in combinations(ps, 2):
            juntos[(a, b)] += 1
    return juntos


def _esperado_par(ctx, a: str, b: str) -> float:
    merc_a = Counter(_mercado(c) for c in ctx["de"][a])
    lam = 0.0
    for m, na in merc_a.items():
        nb = ctx["part_merc"][(b, m)]
        if nb:
            lam += na * nb / ctx["n_merc"][m]
    return lam


def _inseparaveis(ctx) -> dict:
    juntos = _pares_juntos(ctx["cs"])
    part = ctx["part"]
    funil = {"pares_brutos": len(juntos)}
    cand = [(a, b, k) for (a, b), k in juntos.items() if k >= MIN_JUNTOS]
    funil["com_min_juntos"] = len(cand)
    cand = [(a, b, k) for a, b, k in cand if k / (part[a] + part[b] - k) >= JACCARD_MIN]
    funil["jaccard"] = len(cand)
    m_testes = max(1, sum(1 for k in juntos.values() if k >= 3))
    alfa_c = ctx["alfa"] / m_testes
    achados = []
    for a, b, k in cand:
        lam = _esperado_par(ctx, a, b)
        p = cauda_poisson(k, lam)
        if p >= alfa_c:
            continue
        cs = _juntos_de(ctx, a, b)
        va = sum(1 for c in cs if a in c["vencedores"])
        vb = sum(1 for c in cs if b in c["vencedores"])
        lam_n, n_nicho = _nicho_par(ctx, a, b, cs)
        p_n = cauda_poisson(k, lam_n)
        ex = _explicacoes(ctx, a, b, cs)
        if p_n >= alfa_c:
            ex.append(_ex_nicho(n_nicho, lam_n))
        achados.append({
            "esperado_nicho": round(lam_n, 3), "p_valor_nicho": p_n, "passa_nicho": p_n < alfa_c,
            "a": a, "b": b, "juntos": k, "participacoes": [part[a], part[b]],
            "jaccard": round(k / (part[a] + part[b] - k), 3), "vitorias_juntos": [va, vb],
            "vitorias_totais": [ctx["vit"][a], ctx["vit"][b]],
            "esperado_mercado": round(lam, 3), "p_valor": p, "entes": sorted({c["ente"] for c in cs}),
            "classe": ("figurantes_em_bloco" if va == 0 and vb == 0 else
                       "cobertura" if (va == 0) != (vb == 0) else "alternam"),
            "certames": [_resumo_certame(c) for c in sorted(cs, key=lambda c: c["data"])],
            "explicacoes_inocentes": ex,
        })
    funil["acima_do_acaso_corrigido"] = len(achados)
    funil["acima_do_acaso_do_nicho"] = sum(1 for a in achados if a["passa_nicho"])
    achados.sort(key=lambda d: (not d["passa_nicho"], d["p_valor"]))
    return {"achados": achados, "funil": funil, "pares_testados": m_testes, "alfa_corrigido": alfa_c}


def _ex_nicho(n_nicho: int, lam_n: float) -> dict:
    return {"tipo": "nicho_restrito", "detalhe": f"dentro do nicho (objeto parecido nos mesmos entes, {n_nicho} certames) "
            f"o acaso já daria {lam_n:.1f} encontros — poucos fornecedores disputam esse objeto; não passa no corte do nicho"}


def _rodizio(ctx) -> dict:
    juntos = _pares_juntos(ctx["cs"])
    funil = {"pares_brutos": len(juntos)}
    cand = [(a, b, k) for (a, b), k in juntos.items() if k >= MIN_JUNTOS_RODIZIO]
    funil["com_min_juntos"] = len(cand)
    m_testes = max(1, sum(1 for k in juntos.values() if k >= 3))
    alfa_c = ctx["alfa"] / m_testes
    achados = []
    n_cruz = 0
    for a, b, k in cand:
        cs = _juntos_de(ctx, a, b)
        # vitória cruzada só em certame de vencedor único: dividir itens não é revezar o 1º lugar
        a_vence_b = sum(1 for c in cs if c["vencedores"] == {a})
        b_vence_a = sum(1 for c in cs if c["vencedores"] == {b})
        if min(a_vence_b, b_vence_a) < MIN_VITORIAS_CRUZADAS:
            continue
        n_cruz += 1
        levam = sum(1 for c in cs if c["vencedores"] & {a, b})
        if levam / k < PARTILHA_MIN:
            continue
        lam = _esperado_par(ctx, a, b)
        p = cauda_poisson(k, lam)
        if p >= alfa_c:
            continue
        lam_n, n_nicho = _nicho_par(ctx, a, b, cs)
        p_n = cauda_poisson(k, lam_n)
        ex = _explicacoes(ctx, a, b, cs)
        if p_n >= alfa_c:
            ex.append(_ex_nicho(n_nicho, lam_n))
        achados.append({
            "esperado_nicho": round(lam_n, 3), "p_valor_nicho": p_n, "passa_nicho": p_n < alfa_c,
            "membros": [a, b], "certames_juntos": k, "a_vence_b": a_vence_b, "b_vence_a": b_vence_a,
            "partilha": round(levam / k, 3), "esperado_mercado": round(lam, 3), "p_valor": p,
            "entes": sorted({c["ente"] for c in cs}),
            "valor_homologado_ao_par": _soma_vh([c for c in cs if c["vencedores"] & {a, b}]),
            "certames": [_resumo_certame(c) for c in sorted(cs, key=lambda c: c["data"])],
            "explicacoes_inocentes": ex,
        })
    funil["vitorias_cruzadas"] = n_cruz
    funil["acima_do_acaso_corrigido"] = len(achados)
    funil["acima_do_acaso_do_nicho"] = sum(1 for a in achados if a["passa_nicho"])
    achados.sort(key=lambda d: (not d["passa_nicho"], d["p_valor"]))
    return {"achados": achados, "funil": funil, "pares_testados": m_testes, "alfa_corrigido": alfa_c}


# ───────────────────────── identidade e vínculos ─────────────────────────────────────────────

def resolver_cnpj(estab: sqlite3.Connection, nomes: dict[str, str]) -> dict[str, dict]:
    """Nome normalizado → {raiz, via}. Razão social idêntica e ÚNICA na Receita; se repetida, só quando
    exatamente uma das raízes tem estabelecimento no RJ. Nada de semelhança: não se adivinha CNPJ."""
    out = {}
    for n, cru in nomes.items():
        alvo = re.sub(r"\s+", " ", _sem_acento(cru)).strip()
        variantes = [alvo, re.sub(r"[.\-]", "", alvo), re.sub(r"\s*-\s*(ME|EPP|EIRELI)$", "", alvo)]
        raizes: set = set()
        via = "razao"
        for v in dict.fromkeys(variantes):
            raizes |= {r[0] for r in estab.execute("SELECT cnpj_basico FROM empresas WHERE razao_social = ?", (v,))}
            if raizes:
                break
        if not raizes and len(alvo) >= PREFIXO_MIN:
            # 9.117 dos ~38 mil nomes do TCE-RJ têm EXATAMENTE 50 caracteres — o ente cortou a razão social.
            # Prefixo por faixa do índice (>= x AND < x+U+FFFF); só vale se sobrar uma raiz (ou uma no RJ).
            raizes = {r[0] for r in estab.execute(
                "SELECT cnpj_basico FROM empresas WHERE razao_social >= ? AND razao_social < ? LIMIT 20",
                (alvo, alvo + "\uffff"))}
            via = "prefixo"
        if len(raizes) == 1:
            out[n] = {"raiz": raizes.pop(), "via": f"{via}_unica"}
        elif 1 < len(raizes) < 20:
            rj = {r for r in raizes if estab.execute(
                "SELECT 1 FROM estabelecimentos WHERE cnpj_basico = ? AND uf = 'RJ' LIMIT 1", (r,)).fetchone()}
            if len(rj) == 1:
                out[n] = {"raiz": rj.pop(), "via": f"{via}_repetida_unica_no_rj"}
    return out


def _complemento(c: str) -> str:
    return re.sub(r"\s+", " ", _sem_acento(c)).strip()


def vinculos(estab: sqlite3.Connection, pares: list[tuple[str, str]]) -> dict:
    """Para pares de RAÍZES: mesmo telefone/e-mail (Receita, fan-out medido — `ligacoes_conluio.contatos`,
    mesmos limiares) e mesma SALA. O SÓCIO não é medido aqui: `tools/screen_coparticipacao_relacionados`
    já cruza o QSA com a data do certame (sócio que entrou depois não descreve o certame — DROGAFONTE ×
    LYF e ROMA × MEDKA eram anacronismo), e `levantar` anexa o resultado dele.

    Contato e endereço só da MATRIZ (falso positivo medido em 18/11/2026: Itaú Unibanco × Santander
    "ligados" por telefone e endereço de AGÊNCIAS — redes com milhares de filiais esbarram em prédio e
    PABX). Endereço é a SALA (logradouro+número+CEP+complemento com dígito, ≤ 5 raízes nela) — o prédio
    não liga ninguém (`ninho_sala`: Rua da Assembleia 10 tem 318 CNPJs)."""
    from compliance_agent import ligacoes_conluio as lc
    raizes = sorted({r for p in pares for r in p})
    cnpjs, sala = [], {}
    for r in raizes:
        linhas = estab.execute("SELECT cnpj, endereco_norm, complemento FROM estabelecimentos "
                               "WHERE cnpj_basico = ? AND matriz_filial = '1'", (r,)).fetchall()
        for c, e, comp in linhas:
            cnpjs.append(c)
            comp_n = _complemento(comp)
            if e and len(e) > 12 and re.search(r"\d", comp_n):
                sala[r] = (e, comp_n)
    ct = lc.contatos(estab, cnpjs)
    fan_sala: dict[tuple, int] = {}
    out = {}
    for a, b in {tuple(sorted(p)) for p in pares}:
        k = (a, b)
        vs = list(ct["pares"].get(k, []))
        if a in sala and sala.get(a) == sala.get(b):
            e, comp = sala[a]
            if (e, comp) not in fan_sala:
                fan_sala[(e, comp)] = sum(1 for (c2,) in estab.execute(
                    "SELECT complemento FROM estabelecimentos WHERE endereco_norm = ? LIMIT 5000", (e,))
                    if _complemento(c2) == comp)
            if fan_sala[(e, comp)] <= 5:
                vs.append({"tipo": "endereco", "via": f"mesma sala ({comp[:40]}; {fan_sala[(e, comp)]} CNPJs nela)"})
        out[k] = {"vinculos": vs}
    return {"pares": out, "medida_contato": ct["medida"]}


def pares_que_concorreram(certames: list[dict], ids: dict[str, dict]) -> dict[tuple, list[dict]]:
    """Par de RAÍZES distintas (ambas resolvidas) → certames em que as duas disputaram (≤ 40 participantes)."""
    out: dict[tuple, list[dict]] = defaultdict(list)
    for c in certames:
        if len(c["participantes"]) < 2 or len(c["participantes"]) > MAX_PARTICIPANTES_PAR or not c["vencedores"]:
            continue
        rs = sorted({(ids[n]["raiz"], n) for n in c["participantes"] if n in ids})
        for (ra, na), (rb, nb) in combinations(rs, 2):
            if ra != rb:
                out[(ra, rb)].append({"c": c, "a": na, "b": nb})
    return out


_FORCA = {"socio_vigente": 3, "telefone": 2, "email": 2, "endereco": 1}


def concorrentes_vinculados(juntos: dict[tuple, list[dict]], vin: dict) -> list[dict]:
    """Concorrência entre empresas LIGADAS (sócio, contato ou endereço em comum) no MESMO certame.
    CADE, Guia de cartéis em licitação (2019): "propostas de empresas com sócios/administradores em comum"
    é indicador de cartel; OCDE (2009), checklist: endereço, telefone ou pessoal comum entre concorrentes."""
    achados = []
    for par, lista in juntos.items():
        v = vin["pares"].get(par)
        if not v or not v["vinculos"]:
            continue
        a, b = lista[0]["a"], lista[0]["b"]
        cs = [x["c"] for x in lista]
        a_vence = sum(1 for x in lista if x["a"] in x["c"]["vencedores"] and x["b"] not in x["c"]["vencedores"])
        b_vence = sum(1 for x in lista if x["b"] in x["c"]["vencedores"] and x["a"] not in x["c"]["vencedores"])
        tipos = sorted({x["tipo"] for x in v["vinculos"]})
        g = mesmo_grupo(a, b)
        achados.append({
            "a": a, "b": b, "cnpj_raiz": {a: par[0], b: par[1]}, "certames_juntos": len(cs),
            "a_vence_b": a_vence, "b_vence_a": b_vence,
            "ambos_vencem": sum(1 for c in cs if {a, b} <= c["vencedores"]),
            "ambos_perdem": sum(1 for c in cs if not (c["vencedores"] & {a, b})),
            "um_sempre_perde": (a_vence == 0) != (b_vence == 0) and max(a_vence, b_vence) == len(cs),
            "vinculos": v["vinculos"], "tipos_vinculo": tipos, "forca": max(_FORCA.get(t, 1) for t in tipos),
            "entes": sorted({c["ente"] for c in cs}),
            "valor_homologado_aos_dois": _soma_vh([c for c in cs if c["vencedores"] & {a, b}]),
            "certames": [_resumo_certame(c) for c in sorted(cs, key=lambda c: c["data"])],
            "explicacoes_inocentes": ([{"tipo": "grupo_aparente", "detalhe": f"marca comum aparente '{g}': grupo "
                                        "econômico que disputa contra si mesmo — é o próprio indício (concorrência "
                                        "fictícia), salvo se o edital admitiu e a disputa foi por itens distintos"}]
                                      if g else []),
        })
    achados.sort(key=lambda d: (-d["forca"], -d["certames_juntos"]))
    return achados


def ob_estado(con: sqlite3.Connection, raizes: list[str]) -> dict[str, dict]:
    """OB paga do Estado (SIAFE) por raiz — contexto: mostra se a empresa é fornecedora real do Estado.
    Não é pagamento do certame municipal."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    filtro = _ob_paga(con)
    out = {}
    for r in raizes:
        try:
            n, v = con.execute(f"SELECT COUNT(*), ROUND(COALESCE(SUM(valor),0),2) FROM ob_orcamentaria_siafe "
                               f"WHERE credor LIKE ? AND {filtro}", (r + "%",)).fetchone()
        except sqlite3.OperationalError:       # base sem SIAFE: ausência de fonte, não "nada pago"
            out[r] = "INDISPONÍVEL (sem ob_orcamentaria_siafe)"
            continue
        out[r] = {"n_ob": n, "valor": v}
    return out


# ───────────────────────── orquestração ──────────────────────────────────────────────────────

def _todos_os_pares(r: dict) -> list[tuple[str, str]]:
    ps = [(a["vencedor"], a["perdedor"]) for a in r["cobertura"]["achados"]]
    ps += [(a["a"], a["b"]) for a in r["inseparaveis"]["achados"]]
    ps += [tuple(a["membros"]) for a in r["rodizio"]["achados"]]
    return ps


CACHE_IDENTIDADE = Path("data/conluio/identidade.json")


def _ids_com_cache(estab: sqlite3.Connection, nomes: dict[str, str], cache: Path | None,
                   estab_mtime: float) -> dict[str, dict]:
    """Resolve todos os nomes, reaproveitando a rodada anterior (positivos E negativos) enquanto a base da
    Receita não mudar. 18.691 nomes custaram 17 min com a VM em carga 13 — refazer todo dia é desperdício."""
    velho: dict = {}
    if cache is not None and cache.exists():
        try:
            d = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        if d.get("estab_mtime") == estab_mtime:
            velho = d.get("nomes", {})
    novos = {n: cru for n, cru in nomes.items() if n not in velho}
    res = resolver_cnpj(estab, novos)
    for n in novos:
        velho[n] = res.get(n)                  # None = tentado e não resolvido (não se tenta de novo)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps({"estab_mtime": estab_mtime, "nomes": velho}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache)
    return {n: velho[n] for n in nomes if velho.get(n)}


def _ids_da_casa(con: sqlite3.Connection, nomes: dict[str, str]) -> dict[str, dict]:
    """`nome_cnpj_resolvido` (tools/resolver_nome_cnpj: dump NACIONAL da Receita, ambíguo = NULL) primeiro."""
    from tools.resolver_nome_cnpj import normalizar
    try:
        tab = dict(con.execute("SELECT nome_norm, cnpj_basico FROM nome_cnpj_resolvido "
                               "WHERE COALESCE(cnpj_basico,'') <> ''"))
    except sqlite3.OperationalError:
        return {}
    out = {}
    for n, cru in nomes.items():
        r = tab.get(normalizar(cru))
        if r:
            out[n] = {"raiz": r, "via": "nome_cnpj_resolvido"}
    return out


def _socio_vigente(con_db: str) -> dict[tuple, dict]:
    """Pares de raízes com sócio comum VIGENTE na data do certame — do screen da casa, não refeito aqui."""
    from tools.screen_coparticipacao_relacionados import medir
    return {tuple(sorted((x["cnpj_a"], x["cnpj_b"]))): x for x in medir(con_db, min_certames=1)}


def levantar(con: sqlite3.Connection, estab: sqlite3.Connection | None, *, cache: Path | None = None,
             estab_mtime: float = 0.0, db_path: str = "") -> dict:
    certames = certames_tcerj(con)
    r = analisar(certames)
    disputa = [c for c in certames if len(c["participantes"]) >= 2 and c["vencedores"]]
    r["cobertura_dos_dados"] = {
        "fonte": "tcerj_licitante (TCE-RJ dados abertos)", "certames_lidos": len(certames),
        "com_2_ou_mais_participantes_e_vencedor": r["n_certames_com_disputa"],
        "entes": len({c["ente"] for c in certames}),
        "periodo": [min((c["ano"] for c in certames), default=None), max((c["ano"] for c in certames), default=None)]}
    r["ressalva"] = RESSALVA
    r["gerado_em"] = datetime.now().isoformat(timespec="seconds")
    if estab is None:
        r["identidade"] = {"estado": "INDISPONÍVEL (sem receita_estab.db)"}
        r["vinculados"] = {"achados": [], "estado": "INDISPONÍVEL (sem receita_estab.db)"}
        return r
    nomes: dict[str, str] = {}
    for c in disputa:
        for n in c["participantes"]:
            nomes.setdefault(n, c["nomes"][n])
    ids = _ids_da_casa(con, nomes)
    # o que a casa não resolveu: razão cortada em 50 caracteres (prefixo) e homônima com uma só no RJ
    ids.update(_ids_com_cache(estab, {n: v for n, v in nomes.items() if n not in ids}, cache, estab_mtime))
    juntos = pares_que_concorreram(disputa, ids)
    pares = {tuple(sorted((ids[a]["raiz"], ids[b]["raiz"]))) for a, b in _todos_os_pares(r) if a in ids and b in ids}
    vin = vinculos(estab, sorted(set(juntos) | pares))
    try:
        soc = _socio_vigente(db_path) if db_path else {}
        estado_soc = "ok" if db_path else "INDISPONÍVEL (sem caminho do banco)"
    except sqlite3.OperationalError:
        soc, estado_soc = {}, "INDISPONÍVEL (socios_receita/nome_cnpj_resolvido)"
    for par, x in soc.items():
        if par in juntos:
            vin["pares"].setdefault(par, {"vinculos": []})["vinculos"].append(
                {"tipo": "socio_vigente", "via": "sócio comum vigente na data: " + "; ".join(x["elos"])})
    viz = [a for a in concorrentes_vinculados(juntos, vin) if set(a["tipos_vinculo"]) - {"socio_vigente"}]
    r["vinculados"] = {
        "achados": viz, "pares_resolvidos_que_concorreram": len(juntos),
        "por_tipo": dict(Counter(t for a in viz for t in a["tipos_vinculo"])),
        "um_sempre_perde": sum(1 for a in viz if a["um_sempre_perde"]),
        "so_socio_vigente": {"estado": estado_soc, "pares": len(soc),
                             "onde": "tools/screen_coparticipacao_relacionados (rota de vínculos) — não repetido aqui"},
        "medida_contato": vin.get("medida_contato")}
    ob = ob_estado(con, sorted({ids[x]["raiz"] for a in viz for x in (a["a"], a["b"])} |
                               {r_ for p in pares for r_ in p}))
    for a in viz:
        a["ob_estado"] = {n: ob.get(a["cnpj_raiz"][n]) for n in (a["a"], a["b"])}
    for lista, ka, kb in ((r["cobertura"]["achados"], "vencedor", "perdedor"),
                          (r["inseparaveis"]["achados"], "a", "b")):
        for a in lista:
            _anexar(a, a[ka], a[kb], ids, vin, ob)
    for a in r["rodizio"]["achados"]:
        _anexar(a, a["membros"][0], a["membros"][1], ids, vin, ob)
    r["identidade"] = {"nomes": len(nomes), "resolvidos": len(ids),
                       "por_via": dict(Counter(v["via"] for v in ids.values()))}
    return r


def _anexar(a: dict, x: str, y: str, ids: dict, vin: dict, ob: dict) -> None:
    ix, iy = ids.get(x), ids.get(y)
    a["cnpj_raiz"] = {x: ix["raiz"] if ix else None, y: iy["raiz"] if iy else None}
    a["ob_estado"] = {n: (ob.get(i["raiz"]) if i else "INDISPONÍVEL (CNPJ não resolvido)")
                      for n, i in ((x, ix), (y, iy))}
    if ix and iy:
        a["vinculos"] = vin["pares"].get(tuple(sorted((ix["raiz"], iy["raiz"]))), {"vinculos": []})["vinculos"]
    else:
        a["vinculos"] = "INDISPONÍVEL (CNPJ não resolvido)"


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse
    import os
    ap = argparse.ArgumentParser(description="Conluio por participação (TCE-RJ licitantes)")
    ap.add_argument("--db", default=os.environ.get("JFN_DB", "data/compliance.db"))
    ap.add_argument("--estab", default="data/receita_estab.db")
    ap.add_argument("--gravar", action="store_true", help=f"grava {SAIDA}")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args(argv)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=60)
    estab = sqlite3.connect(f"file:{a.estab}?mode=ro", uri=True) if Path(a.estab).exists() else None
    try:
        r = levantar(con, estab, cache=CACHE_IDENTIDADE, db_path=a.db,
                     estab_mtime=Path(a.estab).stat().st_mtime if estab is not None else 0.0)
    finally:
        con.close()
    if a.gravar:
        SAIDA.parent.mkdir(parents=True, exist_ok=True)
        tmp = SAIDA.with_suffix(".tmp")
        tmp.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
        tmp.replace(SAIDA)
    resumo = {k: {"funil": r[k]["funil"], "top": r[k]["achados"][:a.top]} for k in ("cobertura", "inseparaveis", "rodizio")}
    resumo["vinculados"] = {k: v for k, v in r.get("vinculados", {}).items() if k != "achados"}
    resumo["vinculados"]["top"] = r.get("vinculados", {}).get("achados", [])[:a.top]
    print(json.dumps({"cobertura_dos_dados": r["cobertura_dos_dados"], "identidade": r.get("identidade"), **resumo},
                     ensure_ascii=False, indent=1, default=list))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
