# -*- coding: utf-8 -*-
"""dossie_fracionado — lê processo SEI grande demais para caber num modelo, sem perder citação.

PROBLEMA MEDIDO (acervo real, 2026-07-28, 2.007 processos com texto):

    mediana        6.295 tokens      ← a esmagadora maioria cabe folgada
    p90           54.353 tokens
    p99          429.242 tokens
    maior      1.847.408 tokens      (291 documentos)
    estouram 128k:  56 (2,8%)  ·  262k: 31 (1,5%)  ·  1M: 6 (0,3%)

Ou seja: fracionar TODO processo seria desperdício e perda de qualidade — 97% cabem inteiros, e
um modelo que vê o processo inteiro raciocina melhor que um que vê pedaços. O fracionamento é
para a cauda, e a decisão é medida por processo, não presumida.

POR QUE NÃO USAR UM FATIADOR GENÉRICO (LangChain/llama-index). Eles cortam por contagem de
caracteres com sobreposição, o que serve para prosa corrida. Aqui o processo JÁ VEM FATIADO
pela própria estrutura: cada documento tem número, título e tipo. Cortar por documento em vez
de por caractere preserva a coisa mais importante que existe numa peça de controle externo —
**a citação**. Um achado que não diz de qual documento veio não vale nada perante o tribunal.
Também evita o corte no meio de uma tabela ou de uma cláusula, que é onde o fatiador cego
destrói justamente o trecho que interessa.

DESENHO — map-reduce em duas etapas, com a citação amarrada em todas elas:

  1. `planejar()` mede o processo e decide: cabe inteiro, ou quantos lotes. Lote = conjunto de
     documentos INTEIROS que cabe no orçamento. Documento sozinho maior que o orçamento é o
     único caso em que se corta por caractere — e o corte é declarado no .md.
  2. `mapear()` extrai de cada lote um bloco de fatos com a origem (`[doc 0034 — Termo de
     Referência]`). Nunca resume: extrai. Resumo perde número, e número é o que se fiscaliza.
  3. `reduzir()` consolida os blocos num dossiê .md com seções fixas, mantendo as citações.

HONESTIDADE (invariantes da casa, aplicados aqui):
  · o que não está no processo entra como LACUNA declarada, nunca como ausência de problema;
  · valor não encontrado é "não consta", nunca R$ 0,00;
  · o .md registra a cobertura — quantos documentos entraram, quantos ficaram de fora e por quê.
    Um dossiê que leu 40 de 291 documentos e não diz isso é pior que nenhum dossiê.
"""
from __future__ import annotations

import html
import logging
import pathlib
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Português jurídico é denso em palavra longa e número; ~3,5 caracteres por token é a razão
# medida no acervo. Estimativa serve para PLANEJAR — a verdade é o tokenizador do provedor,
# por isso a margem de segurança abaixo.
# MEDIDO em 2026-07-28, e a lição é que NÃO EXISTE constante boa. Num processo de faturas de
# energia (tabela densa, números, espaçamento de PDF) o tokenizador real contou 1.036.551 tokens
# onde 3,5 char/token previa 445.259 — razão verdadeira de **1,50**, subestimativa de 2,3×, e o
# lote estourou a janela de 1.000.000. Amostrando 36 processos do acervo, a razão vai de 2,4 a
# 3,8. Por isso 2,0: conservador, perto do pior caso observado.
#
# A defesa que realmente resolve não é este número, é reagir à contagem VERDADEIRA que o provedor
# devolve no erro de estouro — ver `llm/free_llm.estouro_de_contexto` e a subdivisão em
# `tools/sei_dossie_md`. A constante só evita gastar a primeira chamada à toa.
CHARS_POR_TOKEN = 2.0
# Fração do contexto reservada ao prompt, ao sistema e à resposta. Encher a janela até a borda
# é receita de truncamento silencioso no meio do último documento.
FRACAO_UTIL = 0.55


def estimar_tokens(texto: str) -> int:
    return int(len(texto or "") / CHARS_POR_TOKEN)


@dataclass
class Documento:
    nome: str
    titulo: str
    texto: str

    @property
    def tokens(self) -> int:
        return estimar_tokens(self.texto)


@dataclass
class Lote:
    indice: int
    docs: list[Documento] = field(default_factory=list)
    truncado: bool = False

    @property
    def tokens(self) -> int:
        return sum(d.tokens for d in self.docs)


@dataclass
class Plano:
    processo: str
    n_docs: int
    tokens_total: int
    orcamento: int
    lotes: list[Lote]
    docs_vazios: int = 0

    @property
    def cabe_inteiro(self) -> bool:
        return len(self.lotes) <= 1 and not any(x.truncado for x in self.lotes)


def carregar_documentos(pasta: pathlib.Path) -> list[Documento]:
    """Documentos com texto, na ordem do processo. Sem manifest, cai no nome do arquivo."""
    import json

    pasta = pathlib.Path(pasta)
    titulos: dict[str, str] = {}
    try:
        manifesto = json.loads((pasta / "manifest.json").read_text())
        for d in manifesto.get("docs") or []:
            alvo = (d.get("texto") or "").split("/")[-1]
            if alvo:
                titulos[alvo] = d.get("titulo") or ""
    except (OSError, json.JSONDecodeError):
        logger.debug("%s: sem manifest legível — usando o nome do arquivo como título", pasta)

    docs: list[Documento] = []
    for f in sorted((pasta / "texto").glob("*.txt")) if (pasta / "texto").is_dir() else []:
        try:
            txt = f.read_text(errors="replace")
        except OSError:
            continue
        # ENTIDADE HTML NÃO DECODIFICADA no acervo: "Subsecret&aacute;rio" em vez de
        # "Subsecretário". Medido em 2026-07-28 numa amostra de 300 processos: 5 processos e 45
        # arquivos afetados, 727 ocorrências. Pouco em volume, mas quebra o casamento de NOME —
        # e é justamente em despacho e portaria, que é onde estão os responsáveis.
        docs.append(Documento(nome=f.name, titulo=titulos.get(f.name, ""),
                              texto=html.unescape(txt)))
    return docs


def orcamento_tokens(contexto_modelo: int) -> int:
    return max(2_000, int(contexto_modelo * FRACAO_UTIL))


def planejar(processo: str, pasta: pathlib.Path, *, contexto_modelo: int) -> Plano:
    """Decide se o processo cabe inteiro e, se não, como agrupá-lo em lotes de documentos."""
    todos = carregar_documentos(pasta)
    docs = [d for d in todos if d.texto.strip()]
    orc = orcamento_tokens(contexto_modelo)

    lotes: list[Lote] = []
    atual = Lote(indice=1)
    for d in docs:
        if d.tokens > orc:
            # Documento sozinho maior que o orçamento: único caso de corte por caractere.
            if atual.docs:
                lotes.append(atual)
                atual = Lote(indice=len(lotes) + 1)
            limite = int(orc * CHARS_POR_TOKEN)
            for i in range(0, len(d.texto), limite):
                pedaco = Documento(nome=d.nome, titulo=f"{d.titulo} (parte {i // limite + 1})",
                                   texto=d.texto[i:i + limite])
                lotes.append(Lote(indice=len(lotes) + 1, docs=[pedaco], truncado=True))
            atual = Lote(indice=len(lotes) + 1)
            continue
        if atual.tokens + d.tokens > orc and atual.docs:
            lotes.append(atual)
            atual = Lote(indice=len(lotes) + 1)
        atual.docs.append(d)
    if atual.docs:
        lotes.append(atual)

    return Plano(processo=processo, n_docs=len(docs),
                 tokens_total=sum(d.tokens for d in docs), orcamento=orc, lotes=lotes,
                 docs_vazios=len(todos) - len(docs))


_INSTRUCAO_MAP = (
    "Você é analista de controle externo lendo peças de um processo administrativo. "
    "EXTRAIA fatos, não resuma. Cada fato deve vir com a origem entre colchetes, no formato "
    "[doc <arquivo>]. Se um dado não estiver no texto, escreva 'não consta' — nunca estime, "
    "nunca escreva zero no lugar de ausente, nunca invente nome, número ou data. "
    "Não conclua por irregularidade: você registra fatos e indícios, não acusa."
)


def _sistema_map() -> str:
    """Instrução + moldura jurídica brasileira.

    Sem a moldura, o modelo opinava sobre licitação brasileira com o que tivesse aprendido na
    internet: errava o dispositivo, citava súmula inexistente e tratava a Lei 8.666/1993 como
    vigente para contratação nova. A moldura dá o regime, o vocabulário fechado de vícios e o
    dispositivo de cada um — e cabe em ~3.200 tokens, folgado num lote de 144 mil.
    """
    try:
        from compliance_agent.knowledge.moldura_juridica import moldura
        return f"{_INSTRUCAO_MAP}\n\n{moldura()}"
    except Exception as e:  # noqa: BLE001 — sem a moldura a leitura piora, mas não pode parar
        logger.warning("moldura jurídica indisponível (%s) — seguindo sem ela", str(e)[:80])
        return _INSTRUCAO_MAP


_SISTEMA_MAP = _INSTRUCAO_MAP   # compatibilidade: quem importava a constante segue funcionando

_ROTEIRO_MAP = """Extraia, quando houver, e sempre com [doc <arquivo>]:
- objeto e sua descrição
- valores (estimado, contratado, pago) com a data
- modalidade, enquadramento legal e fundamento da contratação direta, se houver
- datas: publicação, abertura, assinatura, vigência
- partes: órgão, unidade, fornecedor com CNPJ
- responsáveis: ordenador de despesas, gestor e fiscal, com ID funcional
- prazos, prorrogações e aditivos
- cláusulas que restrinjam a competição
- inconsistências entre documentos do próprio lote

Responda em tópicos curtos. Sem introdução e sem conclusão."""


def prompt_map(lote: Lote) -> tuple[str, str]:
    partes = [f"### [doc {d.nome}] {d.titulo}".rstrip() + f"\n{d.texto}" for d in lote.docs]
    return _sistema_map(), f"{_ROTEIRO_MAP}\n\n---\n\n" + "\n\n---\n\n".join(partes)


_SISTEMA_REDUCE = (
    "Você consolida extrações parciais de um mesmo processo administrativo num dossiê único. "
    "Preserve TODAS as citações [doc ...] dos fatos que mantiver. Quando duas partes se "
    "contradisserem, registre a contradição em vez de escolher uma. Não introduza nenhum fato "
    "que não esteja nas extrações. O que faltar entra na seção de lacunas."
)


def _sistema_reduce() -> str:
    try:
        from compliance_agent.knowledge.moldura_juridica import moldura
        return f"{_SISTEMA_REDUCE}\n\n{moldura(com_catalogo=False)}"
    except Exception as e:  # noqa: BLE001
        logger.warning("moldura jurídica indisponível (%s)", str(e)[:80])
        return _SISTEMA_REDUCE


def prompt_reduce(processo: str, blocos: list[str]) -> tuple[str, str]:
    corpo = "\n\n".join(f"## Extração do lote {i}\n{b}" for i, b in enumerate(blocos, 1))
    roteiro = f"""Consolide as extrações abaixo do processo {processo} em Markdown, com
exatamente estas seções e nesta ordem:

## 1. Objeto e enquadramento
## 2. Partes e responsáveis
## 3. Linha do tempo
## 4. Valores
## 5. Indícios a verificar
## 6. Contradições entre documentos
## 7. Lacunas

Regras: valor sem origem não entra. Em "Indícios a verificar", cada item começa com o fato e
a citação, e diz o que precisaria ser confirmado — nunca afirma irregularidade. Em "Lacunas",
liste o que se esperaria encontrar num processo desse tipo e não foi localizado.

---

{corpo}"""
    return _sistema_reduce(), roteiro


def cabecalho_md(plano: Plano, modelo: str, *, lotes_truncados: int = 0) -> str:
    """Cabeçalho de cobertura — o dossiê declara o que leu antes de dizer o que achou."""
    modo = ("leitura integral" if plano.cabe_inteiro
            else f"leitura fracionada em {len(plano.lotes)} lote(s)")
    cortados = sum(1 for x in plano.lotes if x.truncado)
    linhas = [
        f"# Dossiê do processo {plano.processo}",
        "",
        "| Cobertura | |",
        "|---|---|",
        f"| Documentos com texto | {plano.n_docs} |",
        f"| Documentos sem texto | {plano.docs_vazios} |",
        f"| Extensão estimada | {plano.tokens_total:,} tokens |".replace(",", "."),
        f"| Modo de leitura | {modo} |",
        f"| Modelo | `{modelo}` |",
    ]
    if cortados:
        linhas.append(f"| Lotes com documento cortado | {cortados} |")
    if lotes_truncados:
        linhas.append(f"| Lotes com LEITURA INCOMPLETA | {lotes_truncados} |")
    linhas += [
        "",
        "> Documento de trabalho. Os itens de indício são **hipóteses a verificar**, não "
        "afirmação de irregularidade: vigora a presunção de legitimidade dos atos "
        "administrativos. Dado ausente é registrado como lacuna, nunca como zero.",
        "",
    ]
    if lotes_truncados:
        linhas += [
            f"> ⚠️ {lotes_truncados} lote(s) tiveram a leitura **incompleta**: a resposta do "
            "modelo foi cortada no limite de tamanho. Parte dos documentos desses lotes NÃO foi "
            "lida, e a ausência de fatos sobre eles não significa ausência de conteúdo.",
            "",
        ]
    if plano.docs_vazios:
        linhas += [
            f"> ⚠️ {plano.docs_vazios} documento(s) do processo não têm texto extraído e "
            "**não foram lidos**. A ausência de achado neles não significa ausência de "
            "problema.",
            "",
        ]
    return "\n".join(linhas)


# ──────────────────────────────────────────────────────────────────────────────────────────
# Consolidação DETERMINÍSTICA — sem IA.
#
# Medido em 2026-07-28, duas tentativas com dois modelos: nenhum modelo grátis produziu as sete
# seções ao consolidar 7 lotes; ambos devolveram o próprio raciocínio, truncado. E é uma tarefa
# em que o modelo não agrega nada — as extrações já vêm rotuladas por tema pelo `map`, e juntar
# rótulo com rótulo é trabalho de código: determinístico, sem cota, sem alucinação, e sem perder
# citação. A IA lê os documentos; o código arruma o resultado.

SECOES = (
    "Objeto e enquadramento",
    "Partes e responsáveis",
    "Linha do tempo",
    "Valores",
    "Indícios a verificar",
    "Contradições entre documentos",
    "Lacunas",
    "Outros fatos extraídos",
)

# Ordem IMPORTA: o primeiro padrão que casar decide. "inconsistência" precisa ser testada antes
# de "documento", e "restrinja a competição" antes de "cláusula".
_TEMAS = (
    ("Contradições entre documentos",
     r"inconsist|contradi|diverg|conflit|discrep"),
    ("Indícios a verificar",
     r"ind[ií]cio|restrinj|restri[cç]|competi|alerta|aten[cç][aã]o|irregular|suspeit|red\s*flag"),
    ("Lacunas",
     r"lacuna|n[aã]o\s+consta|ausent|faltant|n[aã]o\s+localiz|n[aã]o\s+identific"),
    # Valores ANTES de partes: "Valores (estimado, contratado, pago)" casava `contratad` e ia
    # parar em Partes. "Contratado" ali é adjetivo do valor, não nome de parte — por isso Partes
    # só reconhece `contratada`/`contratante`, que são as palavras que designam quem contrata.
    ("Valores",
     r"valor|pre[cç]o|reten[cç]|empenho|pagament|liquida[cç]|juros|multa|desconto|total"
     r"|or[cç]ament|desembolso|r\$"),
    ("Partes e responsáveis",
     r"respons[aá]|ordenador|gestor|fiscal|parte|fornecedor|credor|contratad[ao]s?\b"
     r"|contratante|[oó]rg[aã]o|unidade|cnpj|empresa"),
    ("Linha do tempo",
     r"data|prazo|vig[eê]nci|per[ií]odo|cronogram|prorroga|aditiv|assinatur|publica[cç]"
     r"|abertur|compet[eê]ncia"),
    ("Objeto e enquadramento",
     r"objeto|enquadrament|modalidade|fundament|amparo|inexigibilidade|dispensa|legal"
     r"|contrata[cç][aã]o|licita[cç]"),
)
_TEMAS_RE = tuple((sec, __import__("re").compile(rx, __import__("re").IGNORECASE))
                  for sec, rx in _TEMAS)


def classificar_tema(rotulo: str) -> str:
    """Seção do dossiê a que um rótulo do `map` pertence.

    Sem casamento, devolve "Outros fatos extraídos" — nunca descarta. Item extraído e jogado
    fora é pior que item mal arrumado, porque some sem deixar rastro.
    """
    for secao, rx in _TEMAS_RE:
        if rx.search(rotulo or ""):
            return secao
    return "Outros fatos extraídos"


def _bullets(bloco: str) -> list[tuple[str, str]]:
    """Cada marcador do bloco como item próprio, sem rótulo — para classificar por CONTEÚDO.

    Nem todo modelo usa rótulo em negrito. Medido em 2026-07-28: o `nemotron-3-ultra-550b`
    devolve bullets em prosa corrida, e o dossiê inteiro caía em "Outros fatos extraídos"
    porque a classificação só olhava o rótulo. Sem rótulo, o próprio texto do item decide.
    """
    import re as _re

    itens, atual = [], []
    for linha in (bloco or "").splitlines():
        if _re.match(r"^\s*[-*•]\s+\S", linha) and atual:
            itens.append("\n".join(atual).strip())
            atual = [linha]
        else:
            atual.append(linha)
    if atual:
        itens.append("\n".join(atual).strip())
    return [("", t) for t in itens if t]


def _itens_do_bloco(bloco: str) -> list[tuple[str, str]]:
    """(rótulo, corpo) de cada item rotulado do bloco; o resto vai como corpo sem rótulo."""
    import re as _re

    padrao = _re.compile(r"^\s*[-*]?\s*\*\*(.{2,80}?)\*\*\s*:?\s*(.*)$", _re.M)
    marcas = list(padrao.finditer(bloco or ""))
    if not marcas:
        return _bullets(bloco)
    itens, antes = [], (bloco[:marcas[0].start()] or "").strip()
    if antes:
        itens.append(("", antes))
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(bloco)
        corpo = (m.group(2) + "\n" + bloco[m.end():fim]).strip()
        if corpo:
            itens.append((m.group(1).strip(), corpo))
    return itens


# Deliberação do modelo sobre a própria tarefa. Vem misturada às extrações porque nem todo
# modelo grátis separa raciocínio de resposta; medido em 9 dos 16 lotes da primeira execução.
# Some na consolidação: é ruído do processo, não fato do processo administrativo.
_LINHA_MONOLOGO = __import__("re").compile(
    r"^\s*(?:(?:we|i|let(?:'s|\s+me))\b|the\s+(?:user|instruction|prompt)\b"
    r"|(?:vamos|preciso|devo)\s+(?:analisar|extrair|listar|verificar|come[cç]ar))",
    __import__("re").IGNORECASE)


def limpar_monologo(texto: str) -> str:
    """Remove linhas de deliberação do modelo, preservando qualquer linha com citação.

    A citação é o critério de segurança: se a linha traz `[doc ...]`, ela carrega fato e fica,
    por mais que comece com uma palavra do padrão. Perder fato para limpar ruído seria péssimo
    negócio.
    """
    saida = [ln for ln in (texto or "").splitlines()
             if "[doc" in ln or not _LINHA_MONOLOGO.match(ln)]
    return "\n".join(saida)


# ── Truncamento ────────────────────────────────────────────────────────────────────────────
# Medido em 2026-07-28: 6 dos 7 lotes do maior processo terminavam no meio de uma frase, e um
# deles trazia 98 caracteres para 37 documentos. O `max_tokens` do passo de leitura era pequeno
# demais, e o dossiê apresentava a extração cortada como se fosse completa — quem lesse
# concluiria que aqueles documentos nada tinham. O sinal autoritativo é `finish_reason ==
# "length"`, que o provedor devolve; adivinhar pela pontuação final é heurística, o campo é fato.

_MARCA_TRUNCADO = ("\n\n> ⚠️ **LEITURA INCOMPLETA DESTE LOTE** — a resposta do modelo atingiu o "
                   "limite de tamanho e foi cortada. Os documentos seguintes deste lote **não "
                   "foram lidos**; a ausência de fatos sobre eles NÃO significa ausência de "
                   "conteúdo.")


def marcar_truncado(texto: str) -> str:
    """Anexa o aviso de leitura incompleta, sem duplicar se já houver."""
    if aviso_truncamento(texto):
        return texto
    return (texto or "") + _MARCA_TRUNCADO


def aviso_truncamento(texto: str) -> bool:
    """O lote está marcado como leitura incompleta?

    Só o marcador — é o sinal AUTORITATIVO, posto a partir de `finish_reason == "length"`.
    Para checkpoints gravados antes de o marcador existir, use `parece_truncado`.
    """
    return "LEITURA INCOMPLETA" in (texto or "")


# Fechos plausíveis de uma extração completa: fim de frase, de item, de citação ou de lista.
_FECHOS = (".", "!", "?", ")", "]", ":", "—", "-", "_", "*", "\u201d", '"')


def parece_truncado(texto: str) -> bool:
    """HEURÍSTICA para entradas antigas, sem o marcador — nunca substitui `finish_reason`.

    Checkpoints gravados antes de 2026-07-28 têm truncamento INVISÍVEL: o corte aconteceu, mas
    nada o registrou. Sem esta checagem, a retomada congela a perda para sempre, porque o lote
    incompleto parece pronto e nunca é relido.

    Deliberadamente conservadora: só acusa quando o texto termina sem QUALQUER fecho plausível,
    porque marcar um lote bom como truncado custa uma releitura à toa — barato —, enquanto
    deixar passar um truncado custa conteúdo perdido no entregável.
    """
    t = (texto or "").rstrip()
    if not t:
        return False
    return not t.endswith(_FECHOS)


def _chave_dedup(texto: str) -> str:
    import re as _re
    t = _re.sub(r"\[doc [^\]]+\]", "", texto)          # citação não distingue o fato
    return _re.sub(r"\s+", " ", t).strip().lower()[:220]


def consolidar(blocos: list[str]) -> str:
    """Junta as extrações por lote nas seções do dossiê, sem IA e sem perder citação."""
    por_secao: dict[str, list[str]] = {s: [] for s in SECOES}
    vistos: set[str] = set()
    for bloco in blocos:
        for rotulo, corpo in _itens_do_bloco(limpar_monologo(bloco)):
            if not corpo.strip():
                continue
            chave = _chave_dedup(f"{rotulo}|{corpo}")
            if chave in vistos:
                continue
            vistos.add(chave)
            # Sem rótulo, o conteúdo decide — só as primeiras palavras, que é onde o item
            # anuncia do que trata; o corpo inteiro casaria com tudo.
            secao = classificar_tema(rotulo or corpo[:120])
            prefixo = f"**{rotulo}** — " if rotulo else ""
            por_secao[secao].append(f"- {prefixo}{corpo}")

    partes = []
    for secao in SECOES:
        if por_secao[secao]:
            partes.append(f"## {secao}\n\n" + "\n\n".join(por_secao[secao]))
    return "\n\n".join(partes)
