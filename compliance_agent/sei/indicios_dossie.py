# -*- coding: utf-8 -*-
"""indicios_dossie — lê o dossiê já extraído e aponta o que merece diligência.

A DIVISÃO DE TRABALHO desta casa, agora em três camadas bem separadas:

    IA        lê o documento e extrai o fato COM a citação   (insubstituível)
    código    agrupa, deduplica e organiza                   (`dossie_fracionado.consolidar`)
    código    aponta o que merece diligência                 (este módulo)

Por que o apontamento também é de código: um indício precisa de regra escrita, limiar auditável
e a citação do documento que o sustenta. Modelo que "acha suspeito" não serve para peça — não
se sabe qual régua usou, e amanhã usa outra. Aqui cada indício tem uma função com nome, um
motivo em português e o trecho de origem.

O que este módulo NÃO faz, e o motivo:
  · não conclui por irregularidade — vigora a presunção de legitimidade dos atos administrativos;
  · não pontua score público — o grau é indicação INTERNA de prioridade de diligência;
  · não afirma valor que não esteja citado no dossiê;
  · não confunde empenho com pagamento: só a Ordem Bancária comprova pagamento, e por isso o
    indício de valor fala em "valor citado no documento", nunca em "valor pago", salvo quando o
    próprio documento é de pagamento.

Os indícios nascem do que foi de fato encontrado no acervo, não de um catálogo teórico —
`juros_multa` existe porque o primeiro processo lido trazia R$ 68.143,66 de juros num único mês.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Grau = prioridade INTERNA de diligência. Nunca sai em documento público como nota.
GRAUS = ("informativo", "atencao", "prioritario")


@dataclass
class Indicio:
    codigo: str
    titulo: str
    grau: str
    motivo: str
    evidencia: list[str] = field(default_factory=list)
    valores: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"codigo": self.codigo, "titulo": self.titulo, "grau": self.grau,
                "motivo": self.motivo, "evidencia": self.evidencia[:6], "valores": self.valores}


_RE_MOEDA = re.compile(r"R\$\s*([\d.]+,\d{2})")


def _valor(txt: str) -> float | None:
    try:
        return float(txt.replace(".", "").replace(",", "."))
    except (AttributeError, ValueError):
        return None


def _linhas_com(texto: str, padrao: re.Pattern) -> list[str]:
    return [ln.strip() for ln in (texto or "").splitlines() if padrao.search(ln)]


# ── Indícios ───────────────────────────────────────────────────────────────────────────────

# "juros e multa" é UMA expressão, não duas ocorrências. Sem o `(?:\s+e\s+multa)?` o mesmo
# lançamento de R$ 7.093,26 entrava duas vezes na soma — uma por "juros", outra por "multa".
_RE_JUROS = re.compile(
    r"\bjuros(?:\s+e\s+multas?)?\b|\bmultas?\b|acr[eé]scimo\s+por\s+atraso|encargo\s+morat",
    re.IGNORECASE)


def i_juros_multa(dossie: str) -> Indicio | None:
    """Juros e multa pagos por atraso do próprio ente — ônus evitável ao erário.

    Encontrado no primeiro processo lido (energia elétrica das escolas estaduais): R$ 68.143,66
    de juros e multa referentes a um único mês. Não é irregularidade automática — pode haver
    fatura contestada, glosa em disputa ou repasse atrasado na origem —, mas é despesa que não
    entrega serviço nenhum, e por isso pede explicação nos autos.
    """
    linhas = _linhas_com(dossie, _RE_JUROS)
    if not linhas:
        return None
    # SOMAR TODO VALOR DA LINHA INFLA. A 1ª versão fazia isso e o total saiu R$ 3.995.001,04
    # num acervo onde a multa real do mesmo trecho era R$ 9.288,31 — porque a linha
    # "Bruto R$ 314.366,12; IR R$ 6.455,96; multa R$ 9.288,31; líquido R$ 314.366,12" menciona
    # "multa" e tem quatro valores, três deles de outra natureza. Só entra o valor ADJACENTE ao
    # termo, na mesma cláusula (até o próximo ponto-e-vírgula ou fim de item).
    # DEDUPLICAÇÃO CONSERVADORA. O mesmo lançamento é descrito em mais de um item do dossiê
    # ("Juros e multa (julho/2026): R$ 7.093,26" e "Cobrança de juros e multa (R$ 7.093,26) por
    # pagamento extemporâneo"), e somá-lo duas vezes inflaria. Valor idêntico conta UMA vez.
    # Isso pode SUBcontar se dois meses coincidirem no centavo — assumido de propósito: neste
    # projeto, errar para menos num número de manchete é o erro tolerável.
    valores: list[float] = []
    vistos: set[float] = set()
    for ln in linhas:
        for m in _RE_JUROS.finditer(ln):
            trecho = ln[m.end():m.end() + 90].split(";")[0]
            v = _RE_MOEDA.search(trecho)
            if v and (valor := _valor(v.group(1))) and valor not in vistos:
                vistos.add(valor)
                valores.append(valor)
    if not valores:
        # A palavra aparece mas sem valor: informativo, e a lacuna é dita.
        return Indicio("JM", "Menção a juros/multa sem valor apurado", "informativo",
                       "O dossiê menciona juros ou multa, mas nenhum valor foi localizado nos "
                       "documentos lidos — o montante do ônus por atraso é INDISPONÍVEL, não zero.",
                       linhas[:4])
    total = sum(valores)
    grau = "prioritario" if total >= 50_000 else "atencao" if total >= 5_000 else "informativo"
    return Indicio(
        "JM", "Juros e multa por atraso de pagamento", grau,
        f"Foram localizados {len(valores)} lançamento(s) de juros/multa somando "
        f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") +
        ". Despesa acessória não entrega serviço; cabe verificar a causa do atraso e se houve "
        "apuração de responsabilidade (art. 141 da Lei 14.133/2021 — ordem cronológica de "
        "pagamento).",
        linhas[:6], {"n_lancamentos": len(valores), "total": total, "maior": max(valores)})


_RE_INEXIG = re.compile(r"inexigibilidade|dispensa\s+de\s+licita", re.IGNORECASE)
_RE_JUSTIF = re.compile(r"justificativ|raz[aã]o\s+da\s+escolha|comprova[cç][aã]o.{0,20}pre[cç]o"
                        r"|art\.?\s*72", re.IGNORECASE)


def i_direta_sem_justificativa(dossie: str) -> Indicio | None:
    """Contratação direta cujo processo não exibe os elementos do art. 72.

    O art. 72 lista o que o processo de contratação direta TEM de conter — razão da escolha,
    justificativa de preço, aprovação jurídica. Ausência no dossiê é LACUNA de captura ou de
    instrução, e a distinção entre as duas é justamente o que a diligência resolve.
    """
    if not _RE_INEXIG.search(dossie or ""):
        return None
    tem_justif = bool(_RE_JUSTIF.search(dossie or ""))
    if tem_justif:
        return None
    return Indicio(
        "CD", "Contratação direta sem elementos do art. 72 no dossiê", "atencao",
        "O processo indica contratação direta (inexigibilidade/dispensa), mas os documentos "
        "lidos não trazem razão da escolha nem justificativa de preço (art. 72, Lei "
        "14.133/2021). Pode ser lacuna de CAPTURA e não de instrução — a diligência separa as "
        "duas hipóteses.",
        _linhas_com(dossie, _RE_INEXIG)[:4])


_RE_FISCAL = re.compile(r"\bfiscal\b|\bgestor\s+do\s+contrato\b", re.IGNORECASE)
_RE_EXECUCAO = re.compile(r"atestad|medi[cç][aã]o|liquida[cç][aã]o|nota\s+fiscal|recebiment",
                          re.IGNORECASE)


def i_execucao_sem_fiscal(dossie: str) -> Indicio | None:
    """Execução atestada sem fiscal identificado nos autos (art. 117)."""
    if not _RE_EXECUCAO.search(dossie or ""):
        return None
    if _RE_FISCAL.search(dossie or ""):
        return None
    return Indicio(
        "F117", "Execução atestada sem fiscal identificado", "atencao",
        "Há atesto/liquidação nos documentos lidos, mas nenhum fiscal de contrato foi "
        "identificado. O art. 117 da Lei 14.133/2021 exige representante designado para "
        "acompanhar a execução. A ausência pode ser de designação ou apenas de captura do ato.",
        _linhas_com(dossie, _RE_EXECUCAO)[:4])


_RE_DIVERG = re.compile(r"inconsist|diverg|contradi|discrep", re.IGNORECASE)


# Uma divergência REAL nomeia o que difere: dois valores, duas datas, dois nomes. O rótulo
# sozinho não é achado — e o roteiro de extração PEDE "inconsistências entre documentos" como
# item, então o cabeçalho aparece em quase toda leitura, com "não consta" logo depois.
# Negação explícita: o modelo responde ao item do roteiro dizendo que não há inconsistência.
_RE_NEGA = re.compile(
    r"n[aã]o\s+(?:h[aá]|consta|foram|foi|se\s+(?:verific|observ|constat))|nenhum[ao]?\b"
    r"|aus[eê]ncia\s+de|inexist|sem\s+ind[ií]cio|nada\s+a\s+(?:apontar|registrar)",
    re.IGNORECASE)

_RE_CONCRETO = re.compile(
    r"\bdifere\b|\bdiverg[ei]|\benquanto\b|\bvs\.?\b|\bcontra\b|\bmas\s+o\b"
    r"|R\$\s*[\d.]+,\d{2}.{0,80}R\$\s*[\d.]+,\d{2}"
    r"|\d{2}/\d{2}/\d{4}.{0,60}\d{2}/\d{2}/\d{4}", re.IGNORECASE)


def _afirma_divergencia(linha: str) -> bool:
    """A linha afirma uma divergência concreta, ou só repete o rótulo do roteiro?"""
    if _RE_NEGA.search(linha):
        return False
    return bool(_RE_CONCRETO.search(linha))


def i_divergencia_declarada(dossie: str) -> Indicio | None:
    """Divergência entre documentos AFIRMADA pela leitura, com o que difere nomeado.

    A 1ª versão contava qualquer linha com a palavra "inconsistência", e disparou em **70% dos
    72 processos** analisados — implausível. A causa era minha: o roteiro de extração PEDE
    "inconsistências entre documentos do próprio lote" como item, e o modelo responde ao item
    com "não consta". Eu estava detectando a PERGUNTA, não a resposta.

    É a mesma lição do checklist de vícios, que eu já havia aprendido e não apliquei aqui: o
    default é NÃO ser achado. Agora a linha precisa (a) não estar negada e (b) NOMEAR o que
    difere — dois valores, duas datas, ou um verbo de comparação. Sem isso, é rótulo.
    """
    linhas = [ln.strip() for ln in _linhas_com(dossie, _RE_DIVERG)
              if "[doc" in ln and _afirma_divergencia(ln)]
    if not linhas:
        return None
    return Indicio(
        "DV", "Divergência entre documentos do processo", "atencao",
        f"A leitura apontou {len(linhas)} divergência(s) entre peças do mesmo processo. "
        "Divergência de valor ou de data entre documentos é o que mais frequentemente antecede "
        "erro de liquidação — cabe conferir qual peça prevalece.",
        linhas[:5], {"n": len(linhas)})


_RE_UNICO = re.compile(
    r"apenas\s+(?:uma|1)\s+(?:proposta|licitante|empresa|cota[cç][aã]o)"
    r"|(?:proposta|licitante|cota[cç][aã]o)\s+[úu]nic[ao]"
    r"|[úu]nic[ao]\s+(?:proposta|licitante|interessad[ao]|participante)"
    r"|somente\s+(?:uma|1)\s+(?:proposta|empresa|licitante)", re.IGNORECASE)


def i_licitante_unico(dossie: str) -> Indicio | None:
    """Um só proponente — o fato que a leitura registrou de passagem e vale por si.

    Nasceu de um dossiê real: o modelo mencionou "apenas uma proposta" apenas para DESCARTAR
    cotações combinadas, e seguiu adiante. Mas proponente único é, ele mesmo, o que os
    detectores J4 (supressão de propostas) e E8 (deserto dirigido) investigam. Não prova nada
    — mercado de nicho tem um fornecedor só, e é explicação inocente frequente —, mas é
    exatamente o caso em que se quer olhar o edital.
    """
    linhas = [ln for ln in _linhas_com(dossie, _RE_UNICO) if "[doc" in ln]
    if not linhas:
        return None
    return Indicio(
        "LU", "Proponente único no certame", "atencao",
        "A leitura registrou proposta ou licitante único. Isso não prova direcionamento — "
        "mercado de nicho tem fornecedor único, e é a explicação inocente mais comum —, mas é "
        "a hipótese que os detectores de supressão de propostas (J4) e deserto dirigido (E8) "
        "investigam. Cabe conferir as exigências de habilitação do edital.",
        linhas[:4], {"n_mencoes": len(linhas)})


# Vício do catálogo AFIRMADO pela leitura. A moldura jurídica dá ao modelo os 42 identificadores
# canônicos, e ele os percorre como checklist — respondendo à esmagadora maioria NEGATIVAMENTE.
#
# A 1ª versão procurava negação para descartar, e falhou feio: apontou 27 vícios "afirmados" num
# processo onde as linhas eram "`subcontratacao_cruzada`: não.", "`vigencia_excessiva`: ARP 12
# meses, normal.", "`publicidade_prazos_minimizados`: pregão eletrônico com prazo normal". Listar
# formas de negar é perder sempre: a língua tem infinitas, e "normal" nem parece negação.
#
# O padrão certo é o inverso, e é o mesmo da presunção de legitimidade que rege a casa: o default
# é NÃO ser achado. Só vira indício quando a leitura AFIRMA, com marca explícita.
_RE_AFIRMA = re.compile(
    r"\bsim\b|h[aá]\s+ind[ií]cio|verifica-se|constata-se|observa-se|identificad[oa]"
    r"|configurad[oa]|caracterizad[oa]|presente\s+no|foi\s+constatad|evidencia-se"
    r"|aparent(?:a|emente)\s+(?:haver|configurar)|poss[íi]vel\s+(?:ind[ií]cio|ocorr)",
    re.IGNORECASE)


def _afirma(linha: str) -> bool:
    """Afirmação de verdade, e não a que vem dentro de uma negação.

    "não há indício" contém "há indício" — a marca afirmativa embutida na negação. Lookbehind
    de largura variável não existe em `re`, então a checagem fica aqui: olha os caracteres
    imediatamente anteriores ao casamento.
    """
    for m in _RE_AFIRMA.finditer(linha or ""):
        antes = linha[max(0, m.start() - 12):m.start()].lower()
        if "não" in antes or "nao" in antes or "sem" in antes:
            continue
        return True
    return False


def i_vicio_afirmado(dossie: str) -> Indicio | None:
    """Vício do catálogo que a leitura AFIRMA — não o que ela apenas menciona para descartar."""
    from compliance_agent.knowledge.catalogo_vicios import CATALOGO

    ids = {v.id for v in CATALOGO}
    achados: list[str] = []
    vistos: set[str] = set()
    for ln in (dossie or "").splitlines():
        if not _afirma(ln):
            continue                       # sem afirmação explícita, não é achado
        for vid in ids:
            if f"`{vid}`" in ln or vid.replace("_", " ") in ln.lower():
                if vid not in vistos:
                    vistos.add(vid)
                    achados.append(ln.strip())
                break
    if not achados:
        return None
    return Indicio(
        "VC", "Vício do catálogo apontado pela leitura", "prioritario",
        f"A leitura AFIRMOU {len(vistos)} vício(s) do catálogo canônico: "
        f"{', '.join(sorted(vistos))}. Vem da leitura do documento, não de régua de código — "
        "por isso exige conferência humana no trecho citado antes de qualquer encaminhamento.",
        achados[:5], {"vicios": sorted(vistos)})


DETECTORES = (i_juros_multa, i_direta_sem_justificativa, i_execucao_sem_fiscal,
              i_divergencia_declarada, i_licitante_unico, i_vicio_afirmado)


def varrer(dossie: str) -> list[Indicio]:
    """Todos os indícios do dossiê, do mais prioritário para o menos."""
    achados = []
    for fn in DETECTORES:
        try:
            r = fn(dossie or "")
        except Exception as e:  # noqa: BLE001 — um indício quebrado não cega os outros
            # MAS ELE PRECISA APARECER. Em 2026-07-28 um `NameError` numa régua recém-editada
            # foi engolido aqui, e o indício simplesmente deixou de existir — sem erro, sem
            # log, sem nada. Silêncio é pior que a falha: a fila fica limpa por engano.
            logger.error("indício %s falhou e foi PULADO (%s: %s)",
                         getattr(fn, "__name__", "?"), type(e).__name__, str(e)[:120])
            continue
        if r is not None:
            achados.append(r)
    return sorted(achados, key=lambda i: -GRAUS.index(i.grau))


def resumo_md(indicios: list[Indicio]) -> str:
    """Bloco para o dossiê e para a nota do vault."""
    if not indicios:
        return ("## Indícios apontados\n\n_Nenhum indício das réguas atuais foi acionado neste "
                "processo. Isso NÃO significa ausência de problema: significa que as réguas "
                "existentes não encontraram o que procuram._")
    simbolo = {"prioritario": "🔴", "atencao": "🟡", "informativo": "🔵"}
    linhas = ["## Indícios apontados", "",
              "> Indício é hipótese a verificar, não afirmação de irregularidade. O grau indica "
              "prioridade INTERNA de diligência.", ""]
    for i in indicios:
        linhas += [f"### {simbolo.get(i.grau, '·')} {i.titulo}  \n"
                   f"`{i.codigo}` · grau **{i.grau}**", "", i.motivo, ""]
        if i.evidencia:
            linhas.append("Trechos de origem:")
            linhas += [f"> {t[:300]}" for t in i.evidencia[:4]]
            linhas.append("")
    return "\n".join(linhas)
