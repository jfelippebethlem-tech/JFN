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
        docs.append(Documento(nome=f.name, titulo=titulos.get(f.name, ""), texto=txt))
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


def cabecalho_md(plano: Plano, modelo: str) -> str:
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
    linhas += [
        "",
        "> Documento de trabalho. Os itens de indício são **hipóteses a verificar**, não "
        "afirmação de irregularidade: vigora a presunção de legitimidade dos atos "
        "administrativos. Dado ausente é registrado como lacuna, nunca como zero.",
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
