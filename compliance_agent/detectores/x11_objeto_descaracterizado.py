# -*- coding: utf-8 -*-
"""X11 · OBJETO DESCARACTERIZADO — aditar até virar outra contratação.

O DISPOSITIVO É CURTO E DIRETO. "As alterações unilaterais a que se refere o inciso I do caput do
art. 124 desta Lei **não poderão transfigurar o objeto da contratação**" — Lei 14.133/2021, art.
126. Não há percentual: uma alteração pode caber folgadamente nos 25% do art. 125 e ainda assim
ser ilícita, porque o que se contratou deixou de ser o que se executa.

POR QUE ISSO IMPORTA MAIS QUE O TETO. O art. 125 protege o equilíbrio econômico; o art. 126
protege a LICITAÇÃO. Quando o objeto muda, o certame que escolheu o vencedor deixa de dizer
alguma coisa: quem não participou não concorreu por aquilo, e o preço foi disputado para outra
coisa. É contratação nova sem licitação, vestida de aditivo — e é por isso que este card não olha
valor, olha OBJETO.

COMO SE MEDE UMA COISA QUALITATIVA SEM CHUTAR. Por dissimilaridade textual entre o objeto do
contrato e o objeto aditado, usando o comparador de similaridade que a casa já tem
(`objeto_similaridade`, o mesmo que agrupa "mesmo objeto" no P4 — reusar é o que mantém as duas
leituras coerentes). Sozinha, a dissimilaridade é sinal fraco: termo aditivo costuma descrever
apenas o que muda, e não repetir o objeto inteiro. Por isso o card exige CONVERGÊNCIA:

  T1 DISSIMILARIDADE — o objeto aditado tem baixa similaridade com o contratado ......... fraco
  T2 CATEGORIA DIFERENTE — muda a natureza declarada (obra → serviço, bem → locação) .... forte
  T3 ITEM NOVO SEM CORRESPONDENTE — item aditado que não existe na planilha original .... medio
     (com T1, vira forte: descrição distante E item que não estava previsto)
  T4 RUBRICA — juízo fechado do LLM sobre a pertinência, com citação obrigatória ........ forte

Um sinal isolado NÃO confirma: `fraco` sozinho é ruído, e a casa já pagou por detector que
transformou distância textual em achado. Confirma-se com dois sinais ou com a rubrica ancorada.

HONESTIDADE JFN: sem objeto do contrato OU sem objeto do aditivo → nao_avaliavel. A explicação
inocente é forte aqui e vai junto: aditivo descreve o DELTA, não o todo, e por isso a
dissimilaridade textual é esperada mesmo em alteração perfeitamente regular.
"""
from __future__ import annotations

import re
import unicodedata

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
    evidencia,
)

# Limiares no CÓDIGO. Calibrados para o texto curto e burocrático dos extratos: abaixo de 0.35 as
# descrições praticamente não compartilham vocabulário técnico.
_SIMILARIDADE_BAIXA = 0.35
_ORDEM = ("ausente", "fraco", "medio", "forte", "critico")

# Categorias de NATUREZA do objeto — obra, serviço, aquisição, locação. Mudar de natureza é o
# sinal mais objetivo de transfiguração: não depende de limiar, depende de o texto dizer outra
# coisa.
#
# SETOR ficou de fora de propósito. "Aquisição de medicamentos" → "aquisição de material de
# escritório" muda o setor e NÃO transfigura: continua sendo compra de bem, dentro do que o art.
# 125 disciplina por valor. Misturar setor com natureza produziria mudança de categoria em
# alteração perfeitamente regular, que é o falso positivo que este card precisa evitar.
#
# A ordem importa: `servico_continuado` vem antes de `obra` porque "mão de obra" contém "obra".
# O lookbehind cobre o caso restante — o texto já chega sem acento por `_norm`.
_CATEGORIAS = (
    ("servico_continuado", r"servi[çc]os?\s+cont[íi]nuos?|m[ãa]o\s+de\s+obra|posto\s+de\s+trabalho|"
                           r"vigil[âa]ncia|limpeza|conserva[çc][ãa]o|dedica[çc][ãa]o\s+de\s+m[ãa]o"),
    ("locacao", r"loca[çc][ãa]o|aluguel|comodato"),
    ("obra", r"(?<!mao de )\bobra\b|constru[çc][ãa]o|pavimenta|edifica|reforma"),
    ("engenharia", r"engenharia|projeto\s+executivo|supervis[ãa]o\s+de\s+obra"),
    ("aquisicao", r"aquisi[çc][ãa]o|fornecimento|compra\s+de"),
)

_RUBRICA_PERTINENCIA = {
    "mesmo_objeto_detalhado": "ausente",     # o termo detalha ou ajusta o que já foi contratado
    "objeto_ampliado": "medio",              # amplia o escopo sem sair da natureza
    "objeto_novo_disfarcado": "forte",       # escopo que exigiria novo certame
}

_SYS_PERTINENCIA = (
    "Você é AUDITOR DE CONTROLE EXTERNO avaliando se um TERMO ADITIVO transfigurou o objeto da "
    "contratação (Lei 14.133/2021, art. 126: a alteração unilateral não pode transfigurar o "
    "objeto). Compare o OBJETO CONTRATADO com o OBJETO ADITADO.\n"
    "Classifique APENAS: 'mesmo_objeto_detalhado' = o termo detalha, ajusta ou corrige o que já "
    "foi contratado; 'objeto_ampliado' = amplia o escopo mantendo a mesma natureza; "
    "'objeto_novo_disfarcado' = introduz escopo que exigiria NOVO certame; 'nao_sei' quando o "
    "texto não permite concluir.\n"
    "ATENÇÃO: termo aditivo descreve o que MUDA, não repete o objeto inteiro — a diferença "
    "textual, sozinha, NÃO é transfiguração.\n"
    'Responda SÓ um JSON: {"nivel":"...","trecho":"citação LITERAL do objeto aditado"}. '
    "Sem trecho literal a resposta será DESCARTADA."
)


def _norm(s: str) -> str:
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", t.lower())


def _tokens(s: str) -> set[str]:
    """Palavras com carga semântica: descarta conectivo e burocratês que aparece em tudo."""
    vazias = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "em", "para", "com",
              "por", "no", "na", "nos", "nas", "ao", "aos", "que", "presente", "objeto",
              "contrato", "termo", "aditivo", "instrumento", "constitui", "referente"}
    return {p for p in _norm(s).split() if len(p) > 2 and p not in vazias}


def similaridade(a: str, b: str) -> float:
    """Jaccard sobre tokens com carga. 0 quando um dos lados fica vazio após a limpeza."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def categoria(texto: str) -> str | None:
    t = _norm(texto)
    for nome, padrao in _CATEGORIAS:
        if re.search(padrao, t):
            return nome
    return None


def _sobe(nivel: str) -> str:
    return _ORDEM[min(len(_ORDEM) - 1, _ORDEM.index(nivel) + 1)]


class X11ObjetoDescaracterizado(Detector):
    """Detector X11 — transfiguração do objeto por aditivo (art. 126).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do contrato.
      contexto["objeto_contrato"]: descrição do objeto contratado (ESSENCIAL).
      contexto["aditivos"]: list[dict] com `descricao_objeto` (ESSENCIAL em ao menos um).
      contexto["itens_contrato"] / contexto["itens_aditados"]: opcional list[str] — alimenta o T3.
      contexto["gerar"]: opcional callable(prompt, sistema)->str — rubrica de pertinência.
      contexto["_rubrica_pertinencia"]: opcional dict — atalho de teste, sem rede.

    Honesto: sinal isolado FRACO não confirma; exige convergência ou rubrica ancorada."""

    id = "X11"
    nome = "Objeto descaracterizado por aditivo (art. 126)"
    familia = "execucao"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        obj_contrato = str(contexto.get("objeto_contrato") or "").strip()
        aditivos = [a for a in (contexto.get("aditivos") or []) if isinstance(a, dict)]
        com_objeto = [a for a in aditivos if str(a.get("descricao_objeto") or "").strip()]
        if not obj_contrato or not com_objeto:
            res.motivo_refutacao = (
                "nao_avaliavel: sem objeto do contrato ou sem descrição de objeto nos termos — "
                "a transfiguração se afere comparando TEXTO, e ele não está aqui")
            res.valores = {"tem_objeto_contrato": bool(obj_contrato),
                           "n_aditivos_com_objeto": len(com_objeto)}
            return res

        cat_contrato = categoria(obj_contrato)
        sinais: list[str] = []
        nivel = "ausente"
        pior_sim = 1.0
        cats_aditadas: set[str] = set()

        for a in com_objeto:
            texto = str(a["descricao_objeto"])
            sim = similaridade(obj_contrato, texto)
            pior_sim = min(pior_sim, sim)
            cat_ad = categoria(texto)
            if cat_ad:
                cats_aditadas.add(cat_ad)
            # T2 · categoria diferente — objetivo, não depende de limiar
            if cat_contrato and cat_ad and cat_ad != cat_contrato:
                nivel = max(nivel, "forte", key=_ORDEM.index)
                sinais.append(
                    f"CATEGORIA DIFERENTE: contrato é de '{cat_contrato}' e o termo "
                    f"{a.get('numero_termo') or ''} descreve '{cat_ad}' — mudança de natureza do "
                    f"objeto, não de dimensão")

        # T1 · dissimilaridade textual (sozinha, é FRACO)
        if pior_sim < _SIMILARIDADE_BAIXA:
            if nivel == "ausente":
                nivel = "fraco"
            sinais.append(
                f"DISSIMILARIDADE: o objeto aditado compartilha {pior_sim:.0%} do vocabulário "
                f"técnico do objeto contratado (limiar {_SIMILARIDADE_BAIXA:.0%})")

        # T3 · item novo sem correspondente na planilha original
        itens_c = {_norm(x) for x in (contexto.get("itens_contrato") or []) if str(x).strip()}
        itens_a = [x for x in (contexto.get("itens_aditados") or []) if str(x).strip()]
        novos = [x for x in itens_a if _norm(x) not in itens_c] if itens_c else []
        if itens_c and novos:
            if nivel in ("ausente", "fraco"):
                nivel = "medio" if nivel == "ausente" else _sobe(nivel)
            sinais.append(
                f"ITEM SEM CORRESPONDENTE: {len(novos)} de {len(itens_a)} item(ns) aditado(s) não "
                f"constam da planilha original — item novo não tem preço disputado no certame")

        # T4 · rubrica de pertinência (LLM-opcional; citação conferida contra o objeto aditado)
        rubrica = contexto.get("_rubrica_pertinencia")
        gerar = contexto.get("gerar")
        fonte_rubrica = "\n".join(str(a["descricao_objeto"]) for a in com_objeto)
        if rubrica is None and gerar:
            try:
                bruto = gerar(
                    f"OBJETO CONTRATADO:\n{obj_contrato[:1500]}\n\n"
                    f"OBJETO ADITADO:\n{fonte_rubrica[:1500]}\n\nResponda só o JSON.",
                    _SYS_PERTINENCIA)
                from compliance_agent.llm.json_resposta import parse_json_llm
                rubrica = parse_json_llm(bruto) or {}
            except Exception as exc:  # noqa: BLE001 — sem LLM o objetivo permanece
                rubrica = None
                sinais.append(f"(rubrica de pertinência indisponível: {str(exc)[:60]})")
        if rubrica:
            nv, _score, motivo = avaliar_rubrica(rubrica, _RUBRICA_PERTINENCIA, fonte_rubrica)
            if nv and nv != "ausente":
                nivel = max(nivel, nv, key=_ORDEM.index)
                sinais.append(f"PERTINÊNCIA: {motivo}")

        valores = {
            "tem_objeto_contrato": True, "n_aditivos_com_objeto": len(com_objeto),
            "similaridade_minima": round(pior_sim, 3),
            "categoria_contrato": cat_contrato,
            "categorias_aditadas": sorted(cats_aditadas),
            "itens_sem_correspondente": len(novos),
            "sem_rubrica": rubrica is None,
        }

        # Sinal isolado FRACO não confirma — a casa já pagou por detector que virou distância
        # textual em achado. Confirma com dois sinais ou com a rubrica ancorada.
        confirma = nivel not in ("ausente", "fraco") or len(sinais) >= 2
        if not confirma:
            res.status = "descartado"
            res.score = 0.0
            res.valores = valores
            res.motivo_refutacao = (
                (f"apenas dissimilaridade textual ({pior_sim:.0%}), que é ESPERADA — o termo "
                 f"aditivo descreve o que muda, não repete o objeto inteiro. Sinal isolado não "
                 f"confirma transfiguração.") if sinais else
                "objeto aditado compatível com o contratado nos testes aplicados")
            return res

        res.status = "confirmado"
        res.score = ancora(nivel)
        res.valores = valores
        res.evidencia = [evidencia("contrato e termos aditivos", s) for s in sinais]
        res.motivo_refutacao = ""
        res.explicacao_inocente = (
            "Termo aditivo descreve o DELTA, não o objeto inteiro — diferença textual é esperada "
            "mesmo em alteração perfeitamente regular, e detalhamento técnico costuma introduzir "
            "vocabulário ausente do contrato. O que sustenta o indício é a mudança de NATUREZA e "
            "o item sem correspondente na planilha; a apuração pede o termo na íntegra e a "
            "planilha comparada.")
        return res
