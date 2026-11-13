# -*- coding: utf-8 -*-
"""Preço unitário NORMALIZADO e grupos de comparação HOMOGÊNEOS — base do sobrepreço.

Pedido do dono (2026-11-13): "não pode comparar itens de unidades métricas diferentes com o
mesmo preço. galão de água é diferente de copinho de água [...] o sistema precisa saber
individualizar tudo e isolar os preços pela mesma unidade de medida". E, como diretriz:
"não pode ter margem pra erro em nada. esse é um projeto de governo."

O que estava errado (medido no dado real em 13/11/2026, conferido no PNCP):
  · a aba comparava 'Água Destilada / Ampola 10 ML' a R$ 140,00 (TCE-RJ, 3 unidades) com a
    mediana de R$ 0,21 — "666×". Preço de CAIXA lançado como ampola; não é sobrepreço.
  · 'Água mineral / Copo 200 ML' a R$ 26,00 (Volta Redonda) contra mediana R$ 0,58: o PNCP
    estima R$ 70,40 por "copo" — é caixa de copos registrada como copo.
  · 'Desinfetante / Litro' de R$ 1,32 a R$ 296,55 no MESMO grupo (224×): saneante hospitalar
    e desinfetante de limpeza sob o mesmo nome de catálogo. Grupo heterogêneo, não sobrepreço.

Regras (todas determinísticas, sem modelo de linguagem — cada conversão guarda o TRECHO
literal que a justificou):

1. **Unidade só do que está comprovado.** A unidade vem do campo estruturado
   `unidade_medida` do PNCP; a descrição só entra quando traz texto EXPLÍCITO casado por
   regra ('caixa com 48', 'cx c/ 12 un', 'fardo 6x1,5L'). Unidade ausente, desconhecida,
   genérica ('kit', 'conjunto', 'serviço', 'lote', 'vaga'), embalagem sem conteúdo declarado
   ('Caixa' sozinha) ou CONFLITO entre campo e descrição → **INDETERMINADO**: sai da mediana
   e de qualquer soma. Nunca se chuta.
2. **Preço normalizado.** Medida pura vira R$ por unidade de medida (litro, kg, metro);
   embalagem com contagem declarada vira R$ por unidade contida ('Caixa 100 UN' a R$ 50 →
   R$ 0,50/un). Recipiente com conteúdo ('Garrafa 500 ML') fica como APRESENTAÇÃO: garrafa
   de 500 mL só se compara com garrafa de 500 mL.
3. **Grupo homogêneo.** Mesma descrição normalizada + mesma unidade canônica + mesma
   apresentação + mesmas medidas citadas na descrição. Dentro dele, um SALTO de preço
   ≥ `GAP`× entre valores consecutivos separa faixas (mercado do mesmo produto é contínuo; um
   salto é unidade/apresentação/produto diferente). Faixa pequena demais ou dispersa demais
   (p90/p10 > `DISP_MAX`) não é grupo de comparação: seus itens vão para INDETERMINADO com o
   motivo por extenso. **Separar, nunca achar sobrepreço em grupo errado.**
"""
from __future__ import annotations

import math
import re
import unicodedata

GAP = 4.0          # salto entre preços consecutivos que separa faixas (produto/unidade diferente)
DISP_MAX = 4.0     # p90/p10 máximo de um grupo de comparação aceitável

INDETERMINADO = "INDETERMINADO"


def _norm(s: str | None) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _num(s: str) -> float:
    """Número pt-BR → float ('1.500' = 1500; '1,5' = 1.5; '1.5' = 1.5)."""
    s = s.strip().strip(".,")
    if "," in s:
        return float(s.replace(".", "").replace(",", "."))
    if "." in s:
        partes = s.split(".")
        if all(len(p) == 3 for p in partes[1:]):
            return float("".join(partes))
        return float(s)
    return float(s)


_N = r"(\d+(?:[.,]\d+)*)"

# ── vocabulário do campo unidade_medida ─────────────────────────────────────────
# medida pura → (dimensão, fator para a unidade de exibição)
_MEDIDA = {
    "litro": ("L", 1.0), "litros": ("L", 1.0), "l": ("L", 1.0), "lt": ("L", 1.0),
    "lts": ("L", 1.0), "mililitro": ("L", 0.001), "mililitros": ("L", 0.001), "ml": ("L", 0.001),
    "quilograma": ("kg", 1.0), "quilogramas": ("kg", 1.0), "kilograma": ("kg", 1.0),
    "kg": ("kg", 1.0), "quilo": ("kg", 1.0), "kilo": ("kg", 1.0), "grama": ("kg", 0.001),
    "gramas": ("kg", 0.001), "g": ("kg", 0.001), "gr": ("kg", 0.001),
    "miligrama": ("kg", 1e-6), "mg": ("kg", 1e-6), "tonelada": ("kg", 1000.0),
    "ton": ("kg", 1000.0), "t": ("kg", 1000.0),
    "metro": ("m", 1.0), "metros": ("m", 1.0), "m": ("m", 1.0), "mt": ("m", 1.0),
    "centimetro": ("m", 0.01), "cm": ("m", 0.01), "milimetro": ("m", 0.001), "mm": ("m", 0.001),
    "quilometro": ("km", 1.0), "quilometros": ("km", 1.0), "km": ("km", 1.0),
}
# unidades de tempo (serviço contínuo): só se comparam com a MESMA unidade
_TEMPO = {
    "hora": "hora", "horas": "hora", "h": "hora", "hr": "hora", "minuto": "minuto",
    "minutos": "minuto", "dia": "dia", "dias": "dia", "diaria": "diaria", "diarias": "diaria",
    "mes": "mes", "meses": "mes", "mensal": "mes", "mensalidade": "mes", "ano": "ano",
    "anual": "ano", "semana": "semana",
}
# unidade contável simples (preço por peça)
_UNITARIO = {"unidade", "unidades", "un", "und", "unid", "uni", "peca", "pecas", "pc", "pca",
             "item"}
# formas farmacêuticas / elementos contáveis com nome próprio
_ELEMENTO = {
    "comprimido": "comprimido", "comprimidos": "comprimido", "comp": "comprimido",
    "compr": "comprimido", "cp": "comprimido", "capsula": "capsula", "capsulas": "capsula",
    "cap": "capsula", "dragea": "dragea", "dose": "dose", "doses": "dose", "teste": "teste",
    "testes": "teste", "folha": "folha", "folhas": "folha", "fl": "folha", "par": "par",
    "pares": "par", "resma": "resma", "resmas": "resma", "molho": "molho",
}
# recipientes: a APRESENTAÇÃO é o recipiente + o conteúdo declarado
_RECIPIENTE = {
    "frasco": "frasco", "fr": "frasco", "ampola": "ampola", "amp": "ampola",
    "garrafa": "garrafa", "grf": "garrafa", "garrafao": "galao", "galao": "galao",
    "galoes": "galao", "gl": "galao", "gal": "galao", "bombona": "bombona", "lata": "lata",
    "bisnaga": "bisnaga", "bolsa": "bolsa", "pote": "pote", "saco": "saco", "sc": "saco",
    "balde": "balde", "copo": "copo", "tubo": "tubo", "tubete": "tubete", "cilindro": "cilindro",
    "botijao": "botijao", "seringa": "seringa", "sache": "sache", "envelope": "envelope",
    "rolo": "rolo", "bobina": "bobina", "bloco": "bloco", "bandeja": "bandeja",
    "cartucho": "cartucho", "refil": "refil", "disco": "disco", "tambor": "tambor",
}
# embalagens AGRUPADORAS: só valem com conteúdo/contagem declarados
_AGRUPADORA = {"caixa": "caixa", "caixas": "caixa", "pacotes": "pacote", "fardos": "fardo",
               "embalagens": "embalagem", "cx": "caixa", "cxa": "caixa", "pacote": "pacote",
               "pct": "pacote", "pcte": "pacote", "fardo": "fardo", "fd": "fardo",
               "frd": "fardo", "embalagem": "embalagem", "emb": "embalagem",
               "cartela": "cartela", "blister": "blister", "display": "display"}
# contagens nomeadas no campo unidade → nº de unidades
_CONTAGEM = {"centena": 100, "cento": 100, "milheiro": 1000, "mileiro": 1000, "milhar": 1000,
             "duzia": 12, "duzias": 12, "dezena": 10, "grosa": 144}
# unidade que NÃO mede o que foi entregue: sempre INDETERMINADO
_GENERICA = {"kit", "kits", "conjunto", "conjuntos", "jogo", "jogos", "lote", "lotes", "global",
             "verba", "servico", "servicos", "serv", "srv", "sv", "evento", "eventos", "vaga",
             "vagas", "pessoa", "pessoas", "outras", "perfil", "posto", "sessao", "sessoes"}

# objeto que não é mercadoria fungível: preço de um não diz nada do preço de outro
_NAO_FUNGIVEL = re.compile(
    r"locacao de imove|imovel|\bobras?\b|reforma|engenharia|\bprojeto|consultoria|assessoria")
# nome de CLASSE do catálogo: 'Peça mecânica/elétrica - veículo' (parafuso e motor), 'Peça
# Equipamento Médico', 'Material Gasoterapia' — medido: dispersão de até 1.292× no mesmo rótulo
_CLASSE_GENERICA = re.compile(
    r"(pecas?|materia(?:l|is)|acessorios?|componentes?|diversos|insumos?|suprimentos?|"
    r"equipamentos?|utensilios?|produtos?)\b")
# objeto de serviço: só se compara com unidade de TEMPO ou de MEDIDA (m², km, hora...)
_SERVICO = re.compile(
    r"servic|contratac|locacao|manutenc|treinament|\bcursos?\b|capacitac|hospedag|inscric|"
    r"\beventos?\b|instalac|transporte|fretamento|qualificacao profissional|aperfeicoamento")

# medidas citadas no texto (especificação: volume, massa, dose, comprimento, concentração)
_RX_MEDIDA_TXT = re.compile(
    rf"{_N}\s*(ml|l|lt|lts|litros?|kg|quilos?|g|gr|gramas?|mg|mcg|ui|mm|cm|m|%)(?![a-z0-9])")
_ML = {"ml": 1, "l": 1000, "lt": 1000, "lts": 1000, "litro": 1000, "litros": 1000}
_MG = {"kg": 1e6, "quilo": 1e6, "quilos": 1e6, "g": 1e3, "gr": 1e3, "grama": 1e3,
       "gramas": 1e3, "mg": 1, "mcg": 1e-3}
_MM = {"mm": 1, "cm": 10, "m": 1000}

# embalagem com contagem EXPLÍCITA na descrição. Exige a palavra da embalagem e o número.
_RX_PACK_TXT = re.compile(
    r"\b(caixa|cx|pacote|pct|fardo|fd|embalagem|emb)\b\.?\s*"
    r"(?:com|c/|c\.|contendo|de)?\s*(\d{1,5})(?![\d.,])\s*"
    r"(?!(?:ml|l|lt|lts|litros?|g|gr|kg|mg|cm|mm|m)\b)"
    r"(unidades|unidade|unid|und|un|copos|copo|garrafas|garrafa|frascos|frasco|ampolas|"
    r"comprimidos|capsulas|latas|rolos|folhas|envelopes|pecas|saches|sacos)?\b")
_RX_FARDO_X = re.compile(rf"\b(fardo|fd|caixa|cx|pacote|pct)\b\.?\s*(?:com|c/|de)?\s*"
                         rf"(\d{{1,3}})\s*x\s*{_N}\s*(ml|l|lt|litros?)\b")
_ELEM_PLURAL = {"unidades": "unidade", "unidade": "unidade", "unid": "unidade",
                "und": "unidade", "un": "unidade", "copos": "copo", "copo": "copo",
                "garrafas": "garrafa", "garrafa": "garrafa", "frascos": "frasco",
                "frasco": "frasco", "ampolas": "ampola", "comprimidos": "comprimido",
                "capsulas": "capsula", "latas": "lata", "rolos": "rolo", "folhas": "folha",
                "envelopes": "envelope", "pecas": "unidade", "saches": "sache", "sacos": "saco"}


def _fmt(x: float) -> str:
    return f"{x:g}"


def medidas_texto(texto: str) -> list[tuple[str, float, str]]:
    """Medidas citadas no texto → [(dimensão, valor canônico, trecho literal)].
    Dimensões: 'ml', 'mg' (massa e dose), 'mm', 'pct', 'ui'."""
    out = []
    for m in _RX_MEDIDA_TXT.finditer(_norm(texto)):
        try:
            v = _num(m.group(1))
        except ValueError:
            continue
        u = m.group(2)
        if u in _ML or u.startswith("litro"):
            out.append(("ml", v * _ML.get(u, 1000), m.group(0)))
        elif u in _MG:
            out.append(("mg", v * _MG[u], m.group(0)))
        elif u in _MM:
            out.append(("mm", v * _MM[u], m.group(0)))
        elif u == "%":
            out.append(("pct", v, m.group(0)))
        elif u == "ui":
            out.append(("ui", v, m.group(0)))
    return out


def _spec(meds: list[tuple[str, float, str]]) -> str:
    return ",".join(sorted({f"{d}{_fmt(round(v, 6))}" for d, v, _ in meds}))


def _indet(motivo: str, trecho: str = "") -> dict:
    return {"ok": False, "estado": INDETERMINADO, "motivo": motivo, "trecho": trecho,
            "chave": None, "fator": None, "rotulo": None}


def _tokens_unidade(u: str) -> list[str]:
    return re.findall(r"[a-z]+", u)


def normalizar(descricao: str | None, unidade: str | None) -> dict:
    """(descrição, unidade_medida do PNCP) → unidade canônica e fator de normalização.

    Devolve {ok, estado, motivo, trecho, chave, fator, rotulo}:
      · `fator` = quantas unidades canônicas há em UMA unidade de venda. Preço normalizado =
        valor_unitario / fator; quantidade normalizada = quantidade × fator.
      · `chave` = unidade canônica + apresentação + medidas da descrição (entra no grupo).
      · `rotulo` = como mostrar a unidade normalizada ('litro', 'garrafa 500 mL', 'unidade').
      · `trecho` = texto LITERAL que justificou a conversão (campo unidade ou descrição).
    Qualquer ambiguidade → ok=False, estado INDETERMINADO, motivo por extenso.
    """
    d = _norm(descricao)
    u_raw = (unidade or "").strip()
    u = _norm(u_raw).strip()
    if not u:
        return _indet("o PNCP não informa a unidade de medida do item")

    if _CLASSE_GENERICA.match(d.strip()):
        return _indet("descrição de CLASSE ('peça', 'material', 'acessório'...): cobre produtos "
                      "distintos sob o mesmo nome — preço de um não é referência do outro",
                      descricao or "")
    if _NAO_FUNGIVEL.search(d):
        return _indet("objeto não fungível (imóvel, obra, projeto, consultoria): o preço de "
                      "um contrato não serve de referência para outro", descricao or "")

    meds_d = medidas_texto(d)
    meds_u = medidas_texto(u)
    toks = _tokens_unidade(u)
    # área / volume pelo campo (m², m³) — antes de 'metro'
    if re.search(r"\bm2\b|metros? quadrados?", u):
        tipo, nome = "medida", ("m2", 1.0)
    elif re.search(r"\bm3\b|metros? cubicos?", u):
        tipo, nome = "medida", ("m3", 1.0)
    else:
        tipo, nome = None, None
        for t in toks:
            if t in _GENERICA:
                return _indet(f"unidade '{u_raw}' não mede o que foi entregue (genérica)", u_raw)
            if t in _AGRUPADORA:
                tipo, nome = "agrupadora", _AGRUPADORA[t]
                break
            if t in _RECIPIENTE:
                tipo, nome = "recipiente", _RECIPIENTE[t]
                break
            if t in _CONTAGEM:
                tipo, nome = "contagem", _CONTAGEM[t]
                break
            if t in _UNITARIO:
                tipo, nome = "unitario", "unidade"
                break
            if t in _ELEMENTO:
                tipo, nome = "elemento", _ELEMENTO[t]
                break
            if t in _TEMPO:
                tipo, nome = "tempo", _TEMPO[t]
                break
            if t in _MEDIDA:
                tipo, nome = "medida", _MEDIDA[t]
                break
        if tipo is None:
            return _indet(f"unidade '{u_raw}' não reconhecida — sem regra que a converta", u_raw)

    servico = bool(_SERVICO.search(d))
    if servico and tipo not in ("tempo", "medida"):
        return _indet(f"serviço medido em '{u_raw}': a unidade não mede a quantidade entregue "
                      f"(só hora/dia/mês ou m²/km sustentam comparação)", u_raw)

    pack = _RX_PACK_TXT.search(d)
    fardo_x = _RX_FARDO_X.search(d)
    spec_d = _spec(meds_d)

    # ── medida pura (litro, kg, metro, m², km) ──────────────────────────────
    if tipo == "medida":
        dim, fator = nome
        nums = [_num(x) for x in re.findall(_N, re.sub(r"\bm[23]\b", "", u))]
        if any(v not in (0.0, 1.0) for v in nums):
            return _indet(f"unidade de medida com número ('{u_raw}'): não se sabe se o preço é "
                          f"por unidade de medida ou pela embalagem", u_raw)
        # conteúdo de embalagem na descrição contradiz unidade de medida pura
        dim_txt = {"L": "ml", "kg": "mg"}.get(dim)
        if dim_txt:
            base = {"ml": 1000, "mg": 1e6}[dim_txt] * fator
            outros = [t for dd, v, t in meds_d if dd == dim_txt and abs(v - base) > 1e-9]
            if outros:
                return _indet(f"unidade '{u_raw}', mas a descrição cita embalagem de "
                              f"'{outros[0]}': não se sabe se o preço é por {u_raw.lower()} ou "
                              f"pela embalagem", outros[0])
        if pack or fardo_x:
            t = (pack or fardo_x).group(0)
            return _indet(f"unidade '{u_raw}', mas a descrição cita embalagem '{t}'", t)
        rot = {"L": "litro", "kg": "kg", "m": "metro", "km": "km", "m2": "m²", "m3": "m³"}[dim]
        return {"ok": True, "estado": "OK", "motivo": "", "trecho": u_raw,
                "chave": f"{dim}||{spec_d}", "fator": fator, "rotulo": rot}

    # ── tempo (serviço contínuo) ─────────────────────────────────────────────
    if tipo == "tempo":
        return {"ok": True, "estado": "OK", "motivo": "", "trecho": u_raw,
                "chave": f"t:{nome}||{spec_d}", "fator": 1.0, "rotulo": nome}

    # ── unidade simples / elemento nomeado ───────────────────────────────────
    if tipo in ("unitario", "elemento"):
        if pack or fardo_x:
            t = (pack or fardo_x).group(0)
            return _indet(f"unidade '{u_raw}', mas a descrição cita embalagem '{t}': não se sabe "
                          f"se o preço é da unidade ou da embalagem", t)
        n_u = [v for _, v, _t in meds_u]
        if n_u and any(v not in (0, 1) for v in n_u):
            return _indet(f"unidade com medida embutida ('{u_raw}') sem regra de conversão", u_raw)
        return {"ok": True, "estado": "OK", "motivo": "", "trecho": u_raw,
                "chave": f"un|{nome}|{spec_d}", "fator": 1.0, "rotulo": nome}

    # ── contagem nomeada no campo (centena, milheiro, dúzia) ─────────────────
    if tipo == "contagem":
        if pack or fardo_x:
            t = (pack or fardo_x).group(0)
            return _indet(f"unidade '{u_raw}', mas a descrição cita embalagem '{t}'", t)
        return {"ok": True, "estado": "OK", "motivo": "", "trecho": u_raw,
                "chave": f"un|unidade|{spec_d}", "fator": float(nome), "rotulo": "unidade"}

    # ── recipiente com conteúdo (garrafa 500 mL, ampola 10 mL, rolo 10 m) ────
    if tipo == "recipiente":
        if pack or fardo_x:
            t = (pack or fardo_x).group(0)
            return _indet(f"unidade '{u_raw}', mas a descrição cita embalagem '{t}': não se sabe "
                          f"se o preço é do recipiente ou da embalagem", t)
        cont_u = _spec(meds_u)
        # conteúdo do campo e da descrição precisam concordar (mesma dimensão)
        dims_u = {dd: v for dd, v, _ in meds_u}
        for dd, v, t in meds_d:
            if dd in dims_u and dd in ("ml", "mm") and abs(dims_u[dd] - v) > 1e-9:
                return _indet(f"conflito: unidade '{u_raw}' × descrição '{t}'", t)
        spec = _spec(meds_u + meds_d)
        cont = f" {cont_u.replace(',', ' ')}" if cont_u else ""
        return {"ok": True, "estado": "OK", "motivo": "", "trecho": u_raw,
                "chave": f"rc|{nome}|{spec}", "fator": 1.0, "rotulo": f"{nome}{cont}"}

    # ── embalagem agrupadora: precisa de contagem ou conteúdo DECLARADO ─────
    m_un = re.search(rf"{_N}\s*(un|und|unid|unidades?)\b", u)
    if m_un:
        n = _num(m_un.group(1))
        if n >= 2 and n == int(n):
            if pack or fardo_x:
                t = (pack or fardo_x).group(0)
                return _indet(f"embalagem '{u_raw}' e descrição '{t}' declaram contagens — "
                              f"conferir antes de converter", t)
            return {"ok": True, "estado": "OK", "motivo": "", "trecho": u_raw,
                    "chave": f"un|unidade|{spec_d}", "fator": float(n), "rotulo": "unidade"}
    if meds_u:
        # 'Embalagem 500 G', 'Pacote 1 KG', 'Caixa 5 L': a embalagem é a apresentação
        spec = _spec(meds_u + meds_d)
        return {"ok": True, "estado": "OK", "motivo": "", "trecho": u_raw,
                "chave": f"rc|{nome}|{spec}", "fator": 1.0,
                "rotulo": f"{nome} {_spec(meds_u).replace(',', ' ')}"}
    m_cnt = re.search(rf"{_N}\s*(fl|folhas?|ro|rolos?)\b", u)
    if m_cnt:
        # 'Fardo 64 RO', 'Pacote 500 FL': a contagem é parte da APRESENTAÇÃO (rolo de 30 m e
        # de 300 m são ambos 'rolo' — converter por rolo seria chute)
        n_txt = f"{m_cnt.group(2)[:2]}{_fmt(_num(m_cnt.group(1)))}"
        spec = ",".join(x for x in (n_txt, spec_d) if x)
        return {"ok": True, "estado": "OK", "motivo": "", "trecho": u_raw,
                "chave": f"rc|{nome}|{spec}", "fator": 1.0, "rotulo": f"{nome} {n_txt}"}
    if re.search(r"\d", u):
        return _indet(f"embalagem '{u_raw}' com contagem não conversível — sem regra", u_raw)
    # sem nada no campo: a descrição pode declarar explicitamente
    if fardo_x:
        n = int(fardo_x.group(2))
        vol = _num(fardo_x.group(3)) * _ML.get(fardo_x.group(4), 1000)
        if n >= 2:
            return {"ok": True, "estado": "OK", "motivo": "", "trecho": fardo_x.group(0),
                    "chave": f"rc|garrafa|ml{_fmt(vol)}", "fator": float(n),
                    "rotulo": f"garrafa ml{_fmt(vol)}"}
    if pack and pack.group(1) in ("caixa", "cx", "pacote", "pct", "fardo", "fd", "embalagem",
                                  "emb"):
        n = int(pack.group(2))
        elem = _ELEM_PLURAL.get(pack.group(3) or "", None)
        if n >= 2 and elem:
            vols = [(dd, v, t) for dd, v, t in meds_d if dd == "ml"]
            if elem == "unidade" or not vols:
                chave = f"un|{elem}|{spec_d}"
            else:
                chave = f"rc|{elem}|{_spec(meds_d)}"
            return {"ok": True, "estado": "OK", "motivo": "", "trecho": pack.group(0),
                    "chave": chave, "fator": float(n), "rotulo": elem}
        if n >= 2:
            return _indet(f"a descrição cita '{pack.group(0)}' sem dizer o que é contado", pack.group(0))
    return _indet(f"embalagem '{u_raw}' sem conteúdo nem quantidade declarados", u_raw)


# ── agrupamento homogêneo ──────────────────────────────────────────────────────

def _quantil(xs: list[float], q: float) -> float:
    """Quantil com interpolação linear (xs ordenado)."""
    if not xs:
        return float("nan")
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def mediana(xs: list[float]) -> float:
    return _quantil(sorted(xs), 0.5)


def faixas_por_salto(precos_ordenados: list[float], gap: float = GAP) -> list[tuple[int, int]]:
    """Índices [ini, fim) de cada faixa contínua: corta onde p[i+1]/p[i] ≥ gap."""
    if not precos_ordenados:
        return []
    cortes = [0]
    for i in range(1, len(precos_ordenados)):
        a, b = precos_ordenados[i - 1], precos_ordenados[i]
        if a <= 0 or b / a >= gap:
            cortes.append(i)
    cortes.append(len(precos_ordenados))
    return [(cortes[k], cortes[k + 1]) for k in range(len(cortes) - 1)]


def agrupar(registros: list[dict], chave_desc, min_amostra: int = 5, min_certames: int = 4,
            gap: float = GAP, disp_max: float = DISP_MAX, min_orgaos: int = 1) -> dict:
    """Separa registros em GRUPOS HOMOGÊNEOS de comparação e INDETERMINADOS.

    `registros`: dicts com 'd' (descrição), 'un' (unidade), 'vu' (valor unitário), 'certame'.
    `chave_desc`: função descrição → descrição normalizada.
    Cada registro ganha '_norm' (resultado de normalizar), 'pn' (preço normalizado) e 'qn'
    (quantidade normalizada, se houver 'quantidade').

    Devolve {grupos: [{chave, desc, rotulo, itens, mediana, p10, p90, dispersao, min, max,
    n, n_certames, faixa, n_faixas}], indeterminados: [(registro, motivo)],
    sem_par: int (registros válidos em grupos pequenos demais — não comparáveis, não
    indeterminados por unidade)}.
    """
    brutos: dict[tuple, list] = {}
    indet: list[tuple[dict, str]] = []
    for r in registros:
        nz = normalizar(r["d"], r["un"])
        r["_norm"] = nz
        if not nz["ok"]:
            indet.append((r, nz["motivo"]))
            continue
        base = chave_desc(r["d"])
        if not base:
            indet.append((r, "descrição vazia após normalização"))
            continue
        r["pn"] = r["vu"] / nz["fator"]
        q = r.get("quantidade")
        r["qn"] = (q * nz["fator"]) if q else None
        brutos.setdefault((base, nz["chave"]), []).append(r)

    grupos = []
    sem_par = 0
    for (base, chave), itens in brutos.items():
        if len(itens) < min_amostra or len({r["certame"] for r in itens}) < min_certames:
            sem_par += len(itens)
            continue
        itens.sort(key=lambda r: r["pn"])
        ps = [r["pn"] for r in itens]
        faixas = faixas_por_salto(ps, gap)
        for k, (i, j) in enumerate(faixas):
            sub = itens[i:j]
            sp = ps[i:j]
            n_cert = len({r["certame"] for r in sub})
            n_org = len({r.get("unidade_nome") or r.get("orgao_nome") for r in sub})
            if len(sub) < min_amostra or n_cert < min_certames or n_org < min_orgaos:
                motivo = (f"faixa de preço isolada por salto ≥{gap:g}× em relação ao resto do "
                          f"grupo ({len(sub)} compra(s)) — provável unidade, apresentação ou "
                          f"produto diferente" if len(faixas) > 1 else
                          "amostra insuficiente")
                for r in sub:
                    indet.append((r, motivo))
                continue
            p10, p90 = _quantil(sp, 0.10), _quantil(sp, 0.90)
            disp = (p90 / p10) if p10 > 0 else float("inf")
            if disp > disp_max:
                motivo = (f"grupo heterogêneo: o mesmo rótulo vai de R$ {sp[0]:.2f} a "
                          f"R$ {sp[-1]:.2f} (p90/p10 = {disp:.1f}×) — a descrição do PNCP "
                          f"mistura produtos diferentes")
                for r in sub:
                    indet.append((r, motivo))
                continue
            grupos.append({
                "chave": chave, "desc": base, "rotulo": sub[0]["_norm"]["rotulo"], "itens": sub,
                "mediana": mediana(sp), "p10": p10, "p90": p90, "dispersao": disp,
                "min": sp[0], "max": sp[-1], "n": len(sub), "n_certames": n_cert,
                "n_orgaos": n_org,
                "faixa": k + 1, "n_faixas": len(faixas)})
    return {"grupos": grupos, "indeterminados": indet, "sem_par": sem_par}
