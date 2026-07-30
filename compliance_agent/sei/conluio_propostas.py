# -*- coding: utf-8 -*-
"""Detector de CONLUIO entre propostas de uma mesma licitação (bid-rigging) — Onda 5/extra.

Pedido do dono: avaliar propostas que indicam concorrência fraudulenta (combinada):
  (1) MARKUP UNIFORME — proposta B = proposta A com o MESMO percentual em TODA a lista (ex.: B = A−5% item a
      item). Diferença percentual constante entre listas inteiras é forte indício de proposta-cobertura.
  (2) PREÇOS QUASE IDÊNTICOS entre concorrentes.
  (3) TEXTO MUITO SIMILAR entre propostas de empresas diferentes (mesmo redator / cópia).

Tudo INDÍCIO a verificar, nunca prova (presunção de legitimidade). Fundamento: Art. 90 Lei 8.666/Art. 337-F CP
(frustrar/fraudar licitação), Art. 36 Lei 12.529/2011 (CADE — conluio), red flags ACFE/TCU (propostas-cobertura).
Opera sobre os itens extraídos (extrator_precos) + texto das propostas — sem rede.
"""
from __future__ import annotations

import re
import statistics
import unicodedata


def _n(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", s)


def _chave_item(desc: str) -> str:
    """Chave para casar o MESMO item entre propostas (descrição normalizada + a MEDIDA).

    ⚠️ CORREÇÃO 2026-07-30 — a chave antiga COLAPSAVA itens diferentes. Ela era
    `[w for w in _n(desc).split() if len(w) > 3][:6]`: descartava todo token com até 3 caracteres,
    ou seja, **todos os números e medidas**. Numa planilha real de licitação, "PARAFUSO SEXTAVADO
    INOX 3/8" e "PARAFUSO SEXTAVADO INOX 1/2" viravam a MESMA chave; como o casamento usa
    `setdefault`, só o primeiro item sobrevivia e os outros eram descartados em silêncio. Efeito: uma
    lista de 12 itens virava 1 par, caía abaixo do `min_itens` e o detector devolvia `None` — não por
    ausência de conluio, mas por cegueira da chave. É a mesma lição que a casa já pagou no
    comparador de preços ("refino por esfera E medida do item").

    Agora a medida entra na chave: os tokens longos identificam O QUE é, e os numéricos identificam
    QUAL é. Vazio ≠ ausente — item sem descrição continua devolvendo chave vazia e sendo ignorado.
    """
    toks = _n(desc).split()
    nome = [w for w in toks if len(w) > 3 and not any(c.isdigit() for c in w)]
    medida = [w for w in toks if any(c.isdigit() for c in w)]
    if not nome and not medida:
        return ""
    return " ".join(nome[:6] + medida[:3])


def _ratios(itens_a: list[dict], itens_b: list[dict]) -> list[float]:
    """Razões vu_B/vu_A dos itens casados por descrição (preço unitário > 0 nos dois)."""
    mapa_a = {}
    for it in itens_a:
        k = _chave_item(it.get("descricao", ""))
        v = it.get("valor_unitario")
        if k and isinstance(v, (int, float)) and v > 0:
            mapa_a.setdefault(k, v)
    out = []
    for it in itens_b:
        k = _chave_item(it.get("descricao", ""))
        v = it.get("valor_unitario")
        if k in mapa_a and isinstance(v, (int, float)) and v > 0:
            out.append(v / mapa_a[k])
    return out


def markup_uniforme(itens_a: list[dict], itens_b: list[dict], min_itens: int = 3, cv_max: float = 0.02) -> dict | None:
    """Detecta diferença percentual ~constante entre as duas listas inteiras. Retorna {pct, n, cv} ou None."""
    r = _ratios(itens_a, itens_b)
    if len(r) < min_itens:
        return None
    media = statistics.mean(r)
    cv = (statistics.pstdev(r) / media) if media else 1.0
    # razão quase constante (cv baixo) e diferente de 1 (não é o mesmo preço por acaso)
    if cv <= cv_max and abs(media - 1.0) > 0.005:
        return {"pct": round((media - 1.0) * 100, 2), "n_itens": len(r), "cv": round(cv, 4)}
    return None


def precos_identicos(itens_a: list[dict], itens_b: list[dict], min_itens: int = 3, tol: float = 0.001) -> dict | None:
    """Itens com preço praticamente IGUAL entre as duas propostas (suspeito entre concorrentes)."""
    r = _ratios(itens_a, itens_b)
    if len(r) < min_itens:
        return None
    iguais = sum(1 for x in r if abs(x - 1.0) <= tol)
    if iguais >= max(min_itens, int(0.8 * len(r))):
        return {"iguais": iguais, "n_itens": len(r), "frac": round(iguais / len(r), 2)}
    return None


def texto_similar(texto_a: str, texto_b: str, limiar: float = 0.85) -> dict | None:
    """Similaridade de Jaccard (tokens) entre dois textos de proposta. Alta = mesmo redator/cópia."""
    ta = set(w for w in _n(texto_a).split() if len(w) > 3)
    tb = set(w for w in _n(texto_b).split() if len(w) > 3)
    if len(ta) < 20 or len(tb) < 20:
        return None
    j = len(ta & tb) / len(ta | tb)
    if j >= limiar:
        return {"jaccard": round(j, 3)}
    return None


def _paragrafos(texto: str, min_palavras: int = 8) -> list[str]:
    """Trechos com corpo suficiente para coincidência ser improvável. Frase curta coincide por acaso."""
    cru = re.split(r"(?:\n\s*\n|\.\s+|;\s+)", str(texto or ""))
    out = []
    for p in cru:
        p = re.sub(r"\s+", " ", p).strip()
        if len(p.split()) >= min_palavras:
            out.append(p)
    return out


def frases_identicas(texto_a: str, texto_b: str, min_palavras: int = 8,
                     max_exemplos: int = 5) -> dict | None:
    """Trechos LITERALMENTE iguais entre duas propostas — e devolve os trechos, não só um número.

    POR QUE ISTO E NÃO SÓ O JACCARD. `texto_similar` mede o quanto os dois vocabulários se
    sobrepõem, e serve para dizer "parece cópia". Mas ninguém instaura processo com um índice de
    0,87: o que um tribunal confere é o TRECHO, lado a lado. E é exatamente o que o detector J5 já
    exige na rubrica ("erros idênticos improváveis": evidência = os trechos idênticos lado a lado")
    e não tinha como medir.

    Compara por parágrafo/oração normalizada. Trecho curto sai fora: "conforme edital" coincide em
    toda proposta do país e viraria falso positivo em massa (a lição do P1, que acusava 71% dos
    certames por casar regex em edital integral).
    """
    pa, pb = _paragrafos(texto_a, min_palavras), _paragrafos(texto_b, min_palavras)
    if not pa or not pb:
        return None
    idx_b = {_n(p): p for p in pb}
    comuns: list[tuple[int, str]] = []
    for p in pa:
        k = _n(p)
        if k in idx_b:
            comuns.append((len(p.split()), p))
    if not comuns:
        return None
    comuns.sort(key=lambda x: -x[0])
    palavras_a = sum(len(p.split()) for p in pa)
    cobertos = sum(n for n, _ in comuns)
    return {
        "n_trechos": len(comuns),
        "palavras_identicas": cobertos,
        "fracao_do_texto": round(cobertos / palavras_a, 3) if palavras_a else 0.0,
        # a EVIDÊNCIA: os trechos, verbatim, para irem lado a lado no laudo
        "trechos": [p for _, p in comuns[:max_exemplos]],
    }


def markup_linear(itens_a: list[dict], itens_b: list[dict], min_itens: int = 4,
                  r2_min: float = 0.995) -> dict | None:
    """B = α·A por regressão pela origem — pega planilha derivada que o CV por item deixa passar.

    ONDE ELE GANHA DO `markup_uniforme`, medido (e não é onde eu supus primeiro). Testei a hipótese
    óbvia — "item faltando ou um item fora da regra" — e ela é FALSA: um outlier de +20% a +60% num
    conjunto de 8 itens cega os DOIS, porque a regressão pela origem também é sensível a ponto
    solto. Então a vantagem não é robustez a outlier.

    A vantagem real é FAIXA DE PREÇO LARGA. O CV trata todo item igual: numa planilha de obra que vai
    de R$ 8,50 a R$ 9.500,00, quem copia a coluna e ARREDONDA as linhas baratas (que é o que uma
    pessoa faz) produz razões 1,06 · 1,17 · 1,12 · 1,12 … — o desvio relativo dos centavos estoura o
    cv ≤ 2% e o padrão desaparece. A regressão pondera por magnitude: os itens grandes fixam a reta,
    o arredondamento dos pequenos é ruído, e o resultado sai R² = 1,000 com α = 1,12.

    Verificado neste cenário exato: `markup_uniforme` cego, `markup_linear` com R² 1.0 e +12,0%.
    """
    mapa_a: dict[str, float] = {}
    for it in itens_a:
        k = _chave_item(it.get("descricao", ""))
        v = it.get("valor_unitario")
        if k and isinstance(v, (int, float)) and v > 0:
            mapa_a.setdefault(k, float(v))
    pares: list[tuple[float, float]] = []
    for it in itens_b:
        k = _chave_item(it.get("descricao", ""))
        v = it.get("valor_unitario")
        if k in mapa_a and isinstance(v, (int, float)) and v > 0:
            pares.append((mapa_a[k], float(v)))
    if len(pares) < min_itens:
        return None
    sxx = sum(x * x for x, _ in pares)
    if not sxx:
        return None
    alfa = sum(x * y for x, y in pares) / sxx          # mínimos quadrados forçando origem
    my = statistics.mean(y for _, y in pares)
    sst = sum((y - my) ** 2 for _, y in pares)
    sse = sum((y - alfa * x) ** 2 for x, y in pares)
    if sst <= 0:
        return None
    r2 = 1.0 - sse / sst
    if r2 >= r2_min and abs(alfa - 1.0) > 0.005:
        return {"coeficiente": round(alfa, 4), "pct": round((alfa - 1.0) * 100, 2),
                "r2": round(r2, 5), "n_itens": len(pares)}
    return None


def detectar(propostas: list[dict], *, mercado_homogeneo: bool = False,
             template_de_mercado: bool = False) -> dict:
    """propostas = [{fornecedor, cnpj, itens:[{descricao,valor_unitario}], texto?}]. Compara par a par.
    Retorna {ok, n_propostas, indicios:[{tipo, a, b, ...}], _nota}. Indício, nunca acusação."""
    props = [p for p in (propostas or []) if p.get("itens") or p.get("texto")]
    indicios = []
    for i in range(len(props)):
        for j in range(i + 1, len(props)):
            a, b = props[i], props[j]
            na = a.get("fornecedor") or a.get("cnpj") or f"#{i}"
            nb = b.get("fornecedor") or b.get("cnpj") or f"#{j}"
            mu = markup_uniforme(a.get("itens", []), b.get("itens", []))
            if mu:
                indicios.append({"tipo": "markup_uniforme", "a": na, "b": nb, **mu,
                                 "obs": f"{nb} = {na} {mu['pct']:+.1f}% em {mu['n_itens']} itens (cv={mu['cv']}) — "
                                        "diferença percentual ~constante em toda a lista: indício de proposta-cobertura "
                                        "(Art. 90 Lei 8.666/Art. 337-F CP; Art. 36 Lei 12.529/CADE)."})
            # markup por REGRESSÃO: pega o padrão quando a lista não casa inteira (ver docstring).
            # Só entra se `markup_uniforme` não pegou — senão o mesmo fato conta duas vezes, e
            # indício contado em dobro é inflação de achado (a casa já pagou isso 3× numa noite).
            if not mu:
                ml = markup_linear(a.get("itens", []), b.get("itens", []))
                if ml:
                    indicios.append({"tipo": "markup_linear", "a": na, "b": nb, **ml,
                                     "obs": f"{nb} ≈ {na} × {ml['coeficiente']} (R²={ml['r2']}, {ml['n_itens']} itens) — "
                                            "os preços caem numa reta pela origem: assinatura de planilha DERIVADA "
                                            "da do concorrente, mesmo sem a lista casar inteira."})
            pid = precos_identicos(a.get("itens", []), b.get("itens", []))
            if pid:
                indicios.append({"tipo": "precos_identicos", "a": na, "b": nb, **pid,
                                 "grau_rebaixado": mercado_homogeneo or None,
                                 "obs": f"{pid['iguais']}/{pid['n_itens']} itens com preço idêntico entre concorrentes."
                                        + (" ATENUANTE: mercado declarado homogêneo/commodity — preço igual pode ser "
                                           "legítimo (margem fina, preço tabelado). Não sustenta sozinho."
                                           if mercado_homogeneo else "")})
            # trechos LITERAIS: é o que vai lado a lado no laudo (ver `frases_identicas`)
            fi = frases_identicas(a.get("texto", ""), b.get("texto", ""))
            if fi:
                indicios.append({"tipo": "frases_identicas", "a": na, "b": nb, **fi,
                                 "grau_rebaixado": template_de_mercado or None,
                                 "obs": f"{fi['n_trechos']} trecho(s) LITERALMENTE idêntico(s) entre propostas de "
                                        f"concorrentes distintos, cobrindo {fi['fracao_do_texto']*100:.0f}% do texto. "
                                        "Os trechos estão em `trechos`, verbatim, para conferência lado a lado."
                                        + (" ATENUANTE: template de mercado declarado — modelo de associação comercial "
                                           "produz texto igual licitamente." if template_de_mercado else "")})
            ts = texto_similar(a.get("texto", ""), b.get("texto", ""))
            if ts:
                indicios.append({"tipo": "texto_similar", "a": na, "b": nb, **ts,
                                 "grau_rebaixado": template_de_mercado or None,
                                 "obs": f"propostas com texto {ts['jaccard']*100:.0f}% similar — mesmo redator/cópia (verificar)."})
    return {"ok": True, "n_propostas": len(props), "indicios": indicios,
            "exculpatorias": {"mercado_homogeneo": mercado_homogeneo,
                              "template_de_mercado": template_de_mercado},
            "_nota": "Indício de conluio a verificar (presunção de legitimidade) — nunca prova. "
                     "Fundamento: Art. 90 Lei 8.666/Art. 337-F CP, Art. 36 Lei 12.529/2011 (CADE), ACFE/TCU. "
                     "Detectores irmãos, que este NÃO reimplementa: J2 (screen de cobertura por CV), "
                     "J3 (desconto rente ao teto), J5 (autoria/metadado compartilhado), "
                     "editais/screens_conluio (planilha compartilhada)."}
