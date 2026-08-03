# -*- coding: utf-8 -*-
"""Olhar GLOBAL sobre o processo inteiro — map-reduce sobre todos os documentos.

O buraco que isto fecha. O 360 agrega SINAIS (detectores, lacunas, juízo por documento), mas
ninguém lia o CONJUNTO. Num processo de 484 documentos e 3 milhões de caracteres — a obra de
macrodrenagem do Jacarezinho, R$ 129.595.387,83 — a casa produzia uma lista de achados e nenhuma
narrativa: em que ordem as coisas aconteceram, quem decidiu o quê, onde os documentos se
contradizem, o que o processo diz de si mesmo.

Nenhum modelo lê 3 milhões de caracteres de uma vez, e a resposta não é ler menos: é ler em três
tempos.

  1. **MAPA** — uma ficha por documento (`fichas`): fase, tipo, data, quem assinou, valores,
     números de contrato citados e o juízo já pago em `doc_veredito`. Determinístico, sobre o
     texto INTEIRO (o corte de 20.000 caracteres morreu em 2026-08-03).
  2. **REDUÇÃO por fase** (`por_fase`) — o esqueleto do processo: quantos documentos, o intervalo
     de datas, quem assina, quanto se fala em dinheiro em cada etapa.
  3. **CONFRONTO entre documentos** (`contradicoes`) — o que só aparece olhando o conjunto: fase
     que termina depois da seguinte, valor que aparece com dois números, contrato de outro
     processo, assinante que decide em etapas incompatíveis.

O veredito final (`sintetizar`) usa as FICHAS, nunca o texto cru: é o que permite abarcar um
processo inteiro dentro de qualquer janela. A camada subjetiva é opcional e injetável; sem ela, a
síntese determinística sai igual — mais pobre em prosa, idêntica em fato.

HONESTIDADE: a síntese não inventa nexo. Onde falta documento (lacuna de captura declarada), ela
diz que a leitura é parcial; onde a data não existe, não se afirma ordem.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from compliance_agent.sei.instrumento_assinatura import assinaturas

_RE_VALOR = re.compile(r"R\$\s*([\d\.]{1,15},\d{2})")
_RE_CONTRATO = re.compile(r"contrato\s*(?:n?[ºo°.]?\s*)?(\d{1,4}\s*/\s*\d{4})", re.I)
_RE_DATA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")

# Controle prévio (art. 53 da Lei 14.133 / art. 38 da 8.666): parecer JURÍDICO ou de controle —
# não o "parecer de análise" que integra o expediente de pagamento.
_TIPOS_CONTROLE_PREVIO = {"parecer", "parecer_juridico", "manifestacao_juridica", "cota_juridica"}
# Formulário de conformidade NÃO é peça opinativa: quem preenche checklist não exerce o controle
# prévio. Falso positivo medido (080002/004433/2026): "Checklist Consolidado PGE" passava porque
# tem 'PGE' no título. Mesma doutrina do `_RE_BOILERPLATE` do parecer_cumprimento.
_RE_NAO_E_PARECER = re.compile(
    r"checklist|check-?list|lista\s+de\s+verifica|declara[çc][ãa]o\s+de\s+conformidade|"
    r"anexo\s+[úu]nico|resolu[çc][ãa]o\s+conjunta", re.I)
_RE_CONTROLE_JURIDICO = re.compile(
    r"jur[íi]dic|\bPGE\b|\bPGM\b|procuradoria|assessoria\s+jur|assjur|\bCGE\b|"
    r"controladoria|auditoria|controle\s+interno", re.I)
# Atos que DECIDEM — autorizam, homologam, contratam. Liquidação e desembolso são expediente.
_TIPOS_DECISORIOS = {"autorizacao_despesa", "homologacao", "adjudicacao", "contrato", "aditivo",
                     "contratacao_direta", "ata_rp"}

ORDEM_FASES = ("planejamento", "selecao", "contratacao", "execucao", "despesa",
               "controle", "tramitacao", "indefinida")


def _valor(txt: str) -> float | None:
    m = _RE_VALOR.search(txt or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _data(txt: str) -> date | None:
    for d, mth, a in _RE_DATA.findall(txt or "")[:8]:
        try:
            return date(int(a), int(mth), int(d))
        except ValueError:
            continue
    return None


def _num_contrato(s: str) -> str:
    """'016/2023' e '16/2023' são o MESMO contrato — o zero à esquerda é estilo de redação.

    Falso positivo medido ao ligar a síntese ao 360: a contradição G2 acusava documento de
    contrato alheio comparando as duas grafias do mesmo ajuste.
    """
    n, _, ano = re.sub(r"\s+", "", s or "").partition("/")
    return f"{n.lstrip('0') or '0'}/{ano}"


def _cmp(dstr: str) -> tuple:
    """Chave de ordenação de 'dd/mm/aaaa' — ANO primeiro. Usada na redução e no confronto."""
    try:
        d, m, a = (dstr or "01/01/1900").split("/")
    except ValueError:
        return ("1900", "01", "01")
    return (a, m, d)


def fichas(docs: list[dict], vereditos: dict[int, dict] | None = None) -> list[dict]:
    """MAPA: uma ficha compacta por documento. É o que a síntese lê no lugar do texto cru."""
    ver = vereditos or {}
    saida = []
    for d in docs or []:
        texto = d.get("texto") or ""
        ass = assinaturas(texto)
        i = d.get("i")
        try:
            i = int(i)
        except (TypeError, ValueError):
            i = -1
        v = ver.get(i) or {}
        saida.append({
            "i": i, "ref": d.get("ref") or d.get("titulo") or "", "tipo": d.get("tipo") or "",
            "fase": d.get("fase") or "indefinida", "chars": len(texto),
            "data": (ass[0]["data"] if ass else None),
            "assinantes": [a["nome"] for a in ass],
            "valor": _valor(texto),
            # guarda como ESTÁ ESCRITO no documento (o entregável cita o número tal qual);
            # a comparação é que normaliza o zero à esquerda, em `contradicoes`.
            "contratos_citados": sorted({re.sub(r"\s+", "", m.group(1))
                                         for m in _RE_CONTRATO.finditer(texto)}),
            "escala": v.get("escala"),
            "juizo": (v.get("justificativa_curta") or "")[:200],
        })
    return saida


def por_fase(fs: list[dict]) -> dict[str, dict]:
    """REDUÇÃO: o esqueleto do processo, fase a fase — o que uma lista de achados não mostra."""
    grupos: dict[str, list[dict]] = defaultdict(list)
    for f in fs:
        grupos[f["fase"]].append(f)
    saida = {}
    for fase in ORDEM_FASES:
        g = grupos.get(fase)
        if not g:
            continue
        # ordena por ANO/mês/dia: 'dd/mm/aaaa' como texto ordena pelo DIA, e a fase saía
        # "de 08/12/2025 a 28/11/2025" — início depois do fim. Mesma armadilha já registrada no
        # acervo para o `data_emissao` do SIAFE.
        datas = sorted((x["data"] for x in g if x["data"]), key=_cmp)
        valores = [x["valor"] for x in g if x["valor"]]
        escalas = [x["escala"] for x in g if x["escala"]]
        assinantes: list[str] = []
        for x in g:
            assinantes += x["assinantes"]
        saida[fase] = {
            "n_docs": len(g), "chars": sum(x["chars"] for x in g),
            "de": datas[0] if datas else None, "ate": datas[-1] if datas else None,
            "maior_valor": max(valores) if valores else None,
            "assinantes": sorted(set(assinantes)),
            "julgados": len(escalas),
            "viciados": sum(1 for e in escalas if e == 3),
            "frageis": sum(1 for e in escalas if e == 2),
        }
    return saida


def contradicoes(fs: list[dict]) -> list[dict]:
    """CONFRONTO: o que só aparece olhando o conjunto. Cada item cita os documentos envolvidos."""
    achados: list[dict] = []

    # G1 (sobreposição de fases) e G2 (documento citando outro contrato) foram REMOVIDOS em
    # 2026-08-03, depois de validá-los caso a caso no acervo — a mesma conferência que já tinha
    # derrubado o G3 de 73 para 2. O que a leitura mostrou:
    #
    #   G1, 202 ocorrências: os pares mais frequentes eram `despesa × controle` (94×),
    #   `execucao × despesa` (31×) e `contratacao × despesa` (25×). Nenhum é defeito — paga-se
    #   ENQUANTO se executa, e o controle atravessa o processo inteiro. A inversão que importa
    #   (contrato antes do parecer) já é apurada pelo `cadeia_processo.analisar_cadeia` e pelo
    #   `I2_AUTORIZACAO_ANTES_DO_PARECER`, ambos por MARCO, não por intervalo de fase.
    #
    #   G2, 305 ocorrências: o "contrato do processo" saía de uma heurística de frequência sobre
    #   todo o texto, e o número exibido era a CHAVE NORMALIZADA — num caso o achado dizia "cita o
    #   contrato 010/2024 enquanto o processo discute o 1/2024" sendo que o documento ERA o
    #   "Contrato Nº 010/2024". Citar outro contrato é normal em publicação de DOERJ, ata de
    #   registro e ato de inexigibilidade. O caso REAL que originou a ideia — declaração que
    #   atesta conformidade de outro ajuste — já é o `I5_DECLARACAO_DE_OUTRO_CONTRATO`, que apura
    #   o instrumento pela fórmula de celebração e dispara 2 vezes no acervo, não 305.
    #
    # Detector que não sobrevive à conferência sai: alarme que o fiscal aprende a ignorar é pior
    # que alarme nenhum, porque some junto com ele o que era verdadeiro.

    # 3) quem exerce o CONTROLE PRÉVIO e também DECIDE. Estreitado em 2026-08-03 depois de
    #    amostrar o acervo: com "fase controle × fase despesa" o achado disparava 73 vezes, e o
    #    caso mais frequente (35×) era o mesmo servidor assinando "Parecer de Análise para Emissão
    #    DL" e "Despacho de Formalização de Liquidação" — nenhum dos dois é o que o achado diz.
    #    Controle prévio é o parecer JURÍDICO/de controle do art. 53; decisão é o ato que autoriza,
    #    homologa ou contrata. Expediente de liquidação não é nem um nem outro.
    de_controle = {n for f in fs
                   if f["tipo"] in _TIPOS_CONTROLE_PREVIO
                   and _RE_CONTROLE_JURIDICO.search(f["ref"])
                   and not _RE_NAO_E_PARECER.search(f["ref"])
                   for n in f["assinantes"]}
    de_decisao = {n for f in fs if f["tipo"] in _TIPOS_DECISORIOS for n in f["assinantes"]}
    for nome in sorted(de_controle & de_decisao):
        achados.append({
            "codigo": "G3_MESMA_PESSOA_CONTROLA_E_DECIDE",
            "diz": (f"{nome} assina tanto peça de CONTROLE quanto ato de decisão/despesa — "
                    "o controle prévio perde independência quando quem opina é quem decide"),
            "evidencia": nome})
    return achados


def sintetizar(fs: list[dict], *, lacunas_captura: int = 0, gerar=None) -> dict:
    """Veredito do CONJUNTO. Determinístico sempre; `gerar` (LLM) acrescenta a leitura em prosa."""
    fases = por_fase(fs)
    contr = contradicoes(fs)
    julgados = sum(r["julgados"] for r in fases.values())
    viciados = sum(r["viciados"] for r in fases.values())
    chars = sum(f["chars"] for f in fs)
    linha = [f"{fase}: {r['n_docs']} doc(s)"
             + (f", de {r['de']} a {r['ate']}" if r["de"] else "")
             + (f", {r['viciados']} viciado(s)" if r["viciados"] else "")
             for fase, r in fases.items()]
    leitura = (f"Processo com {len(fs)} documentos e {chars:,} caracteres lidos. "
               f"Esqueleto: {' · '.join(linha)}. "
               f"{julgados} documento(s) com juízo, {viciados} em escala de vício. "
               + (f"{len(contr)} contradição(ões) entre documentos. " if contr else
                  "Nenhuma contradição entre documentos pela leitura do conjunto. ")
               + ("LEITURA PARCIAL: há documento citado nos autos que não foi capturado — o que "
                  "depender dele fica INDISPONÍVEL." if lacunas_captura else
                  "Cobertura: todos os documentos citados foram capturados."))
    saida = {"n_docs": len(fs), "chars": chars, "fases": fases,
             "contradicoes": contr, "julgados": julgados, "viciados": viciados,
             "leitura": leitura, "fonte": "sintese_global (determinística)"}
    if gerar is not None:
        saida["prosa"] = _prosa(saida, gerar)
    return saida


_SYS = (
    "Você é AUDITOR DE CONTROLE EXTERNO (TCE-RJ) escrevendo a leitura de CONJUNTO de um processo "
    "administrativo. Recebe o ESQUELETO do processo (fases, datas, assinantes, juízo por "
    "documento) e as contradições já apuradas — NÃO o texto dos documentos. Escreva 3 a 6 frases "
    "sobre o que o CONJUNTO mostra: a ordem dos atos, quem decidiu, onde a instrução falha. "
    "REGRAS: indício ≠ acusação (presunção de legitimidade); não invente fato, número ou "
    "documento que não esteja no esqueleto; se o esqueleto disser que a leitura é parcial, diga "
    "isso na sua conclusão. Responda em prosa corrida, sem markdown."
)


def _prosa(sintese: dict, gerar) -> str:
    import json
    resumo = {k: sintese[k] for k in ("n_docs", "chars", "fases", "contradicoes",
                                      "julgados", "viciados")}
    try:
        return str(gerar(json.dumps(resumo, ensure_ascii=False, default=str)[:12000], _SYS)).strip()
    except Exception as e:  # noqa: BLE001 — fronteira de LLM: a síntese determinística fica de pé
        return f"(leitura em prosa indisponível: {type(e).__name__})"
