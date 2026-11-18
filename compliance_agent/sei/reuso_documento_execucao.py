# -*- coding: utf-8 -*-
"""Documento de EXECUÇÃO reaproveitado entre processos — diário de obra, atesto, relatório de
fiscalização, medição ou relatório fotográfico com o MESMO corpo em processos diferentes.

ORIGEM (18/11/2026, lido na fonte primária):
  • SEHIS × Construtora Augusto Velloso — diários de obras SEI 135515994 e 140206635
    (SEI-490001/000249/2026, Contrato 034/2026) com o corpo idêntico ao dos diários dos Contratos
    019/2025 e 020/2025 (SEI 126871249, 126874480, 129485829), cabeçalho de outro processo
    (SEI-490001/001323/2024) e efetivo de 8 pessoas.
  • EUREKA × SEEDUC — o mesmo relatório-modelo de fiscalização (amostragem de 15%, galpão da
    Rod. Pres. Dutra 2.671, "projeto dos Itinerários Formativos", objeto do contrato 39/2024) nos
    três pagamentos SEI-030001/000071/2025, 015319/2025 e 025906/2025.

O QUE É SINAL E O QUE NÃO É. Documento de execução descreve o que foi feito, onde, quando e em que
quantidade; o corpo DEVERIA variar de um processo, contrato ou mês para outro. Já o formulário-
padrão do órgão (atesto, checklist, despacho) é idêntico por natureza. Por isso:
  1. só entram documentos cuja FASE é execução, pelo classificador da casa (`sei/fases.py` sobre
     o título, com o tipo do manifesto quando o título é mudo — `manifesto_norm.tipo_canonico`);
  2. o corpo é normalizado antes da comparação: etiqueta do acervo, blocos de assinatura
     eletrônica, "autenticidade", "Referência: Processo nº", "Criado por", número de processo SEI
     e número de documento SEI saem (variam de cópia para cópia e não descrevem a execução);
  3. o texto vira um conjunto de shingles de 6 palavras; o que aparece em documentos de `B` ou
     mais credores DISTINTOS é MODELO INSTITUCIONAL e sai do conjunto (frequência de documento
     medida no próprio acervo). Sobra o corpo descritivo, e é ele que se compara;
  4. documentos do MESMO processo nunca formam par (juntada em duplicidade não é achado), nem o
     mesmo número SEI em dois processos (processo anexado/relacionado), nem a CÓPIA do mesmo
     documento (mesmas assinaturas eletrônicas, mesmas datas) juntada noutro processo.

Comparação exata, sem amostragem: o índice invertido gera candidatos e cada par é conferido pela
interseção completa dos conjuntos. Nenhum LLM, nenhuma GPU, nenhuma rede.

ESTADO de cada par: VERIFICADO quando o corpo normalizado é IDÊNTICO (mesmo hash) e o número SEI de
cada documento está no título e no próprio texto (conferência literal por código); PENDENTE quando é
quase idêntico (precisa de leitura humana lado a lado); INDISPONÍVEL é o documento de execução sem
texto no acervo (não comparado — nunca "sem reuso").

Indício ≠ acusação. Corpo repetido pede o diário/relatório real e a vistoria; não prova, sozinho,
que o serviço não foi feito. Presunção de regularidade.

MEDIDO NO ACERVO (18/11/2026, rodada final no it-campo, B=3): 20.816 documentos de execução com texto
em 3.505 processos (1.118 INDISPONÍVEIS, sem texto — 855 atestos, 203 medições); 85.673 candidatos;
2.335 pares (372 famílias). Por NÍVEL (pares de documentos / pares de processos):
  identico_contratos_diferentes 9/6 — conferidos à mão: os 5 da SEHIS×Augusto Velloso e 1 da DEGASE
    (Contratos 007/2020 × 008/2020, mesmo relatório escaneado) → os dois são casos reais a apurar;
  trecho_contratos_diferentes 15/13 — 2 da EUREKA (reais); o resto é, na maioria, parágrafo de método
    do fiscal (≈ 3 a 4 em 13 merecem leitura) → PENDENTE, nunca manchete;
  quase_identico_contratos_diferentes 76/76 — amostra de 8: quase tudo formulário de avaliação
    preenchido igual ("bom x") e despacho-padrão → fraco;
  quase_identico_mesmo_contrato 1.519/726 e …_contrato_indisponivel 657/224 — relatório mensal do
    fiscal com cabeçalho fixo: endêmico, só leitura;
  identico_contrato_indisponivel 49/5, identico_mesmo_contrato_* 10/10 — a conferir (há cópia do mesmo
    relatório da medição de jul/2024 num processo de 2025; planilha da 23ª medição igual noutro processo).
Fora por regra, contados: 1.045 pares de catálogo EMOP, 22 de formulário em branco, 2 cópias assinadas.
Entre credores DIFERENTES: 43 pares (1,8%), quase todos modelo do órgão — por isso o filtro por credor.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE_ACERVO = REPO / "data" / "sei_arquivo"
DETECTOR_ID = "sei.reuso_documento_execucao"

# tipos de documento de execução física (fase `execucao`, sem aditivo/penalidade: aditivo é ato
# jurídico, não relato de execução; penalidade idem)
TIPOS_EXECUCAO = frozenset({"fiscalizacao", "relatorio_fotografico", "medicao", "aceite"})

K_SHINGLE = 6           # palavras por shingle
B_CREDORES = 3          # shingle presente em docs de ≥ B credores distintos = modelo institucional
MIN_DESCRITIVO = 40     # shingles descritivos em comum para haver par (≈ um parágrafo de 45 palavras)
LIMIAR_CONTENCAO = 0.80  # fração do menor corpo descritivo contida no outro
# 2º caminho (TRECHO): o relatório-modelo da EUREKA tem cabeçalho diferente em cada contrato (objeto,
# valor, NF), e a contenção do documento inteiro fica em 0,58–0,63; o que se repete é o MIOLO —
# condições de recebimento, galpão da Dutra, amostragem de 15%. Trecho contínuo de prosa descritiva
# (não tabela: planilha de medição da mesma ata repete a descrição dos itens do catálogo EMOP, com
# códigos, e isso é lícito) em documentos narrativos.
MIN_TRECHO_PALAVRAS = 100
MAX_FRACAO_NUMERICA_TRECHO = 0.20
TIPOS_NARRATIVOS = frozenset({"fiscalizacao", "relatorio_fotografico", "aceite"})
# 2ª rodada no acervo (18/11/2026): 1.590 pares de trecho, 497 pares de processos — a maioria era o
# texto de MÉTODO da equipe de fiscalização (SEEDUC, limpeza: o mesmo parágrafo em ~75 processos dos
# lotes de um credor) ou a metodologia de uma consultoria em ~90 medições (INEA). Texto que aparece em
# muitos documentos é modelo recorrente, não relato copiado. O trecho só conta com shingles presentes
# em no máximo MAX_DOCS_TRECHO documentos do acervo (a EUREKA: 3 relatórios).
MAX_DOCS_TRECHO = 6
G_MAX = 400             # posting maior que isto vira "família grande" (relatada, não pareada)

# ── normalização ────────────────────────────────────────────────────────────────────────────────

_RX_ASSINATURA = re.compile(
    r"documento assinado eletronicamente por\s+(?P<quem>[^,\n]+),[^\n]*?\bem\s+"
    r"(?P<data>\d{2}/\d{2}/\d{4})(?:,\s*[àa]s\s*(?P<hora>\d{1,2}:\d{2}))?", re.I)
_LINHAS_FORA = [re.compile(p, re.I) for p in (
    r"^\s*\[.*\]\s*(\((fase|tipo):.*\))?\s*$",          # etiqueta do acervo / cabeçalho repetido
    r"documento assinado eletronicamente",
    r"conforme hor[aá]rio oficial de bras[ií]lia",
    r"a autenticidade (d[eo]ste|do) documento",
    r"c[oó]digo verificador|c[oó]digo crc",
    r"controlador_externo\.php",
    r"^\s*refer[eê]ncia:\s*processo",
    r"^\s*criado por \S+,? vers[aã]o",
    r"^\s*p[aá]gina \d+\s*(de|/)\s*\d+\s*$",
    # a linha de assinatura quebra em duas no PDF: "…oficial de Brasília, com fundamento nos art.
    # 28º e 29º do Decreto nº 48.209…" sobra sozinha e virava 'trecho comum' entre credores
    r"decreto\s*n?[º°o.]*\s*48\.?209",
    r"^\s*oficial de bras[ií]lia",
    r"imprensa oficial do estado do rio de janeiro garante a autenticidade",
    r"www\.io\.rj\.gov\.br",
)]
# Linha de CATÁLOGO de preços (EMOP/SINAPI) exportado junto da planilha de medição em Excel: "código |
# descrição | unidade | preço" (ou a continuação "descrição | unidade | preço") e "01 | CATEGORIA". 3ª rodada
# (18/11/2026): o catálogo EMOP inteiro (1.478 linhas) vinha na "Planilha Boletim de Medição Excel" de dois
# credores e de contratos diferentes e virava "corpo idêntico". Catálogo público não é relato de execução.
# A linha de MEDIÇÃO tem mais colunas (quantidade contratada, medida, acumulada) e não casa.
_RX_LINHA_CATALOGO = re.compile(
    r"^\s*(?:\d{2}\.\d{3}\.\d{4}-[0-9A-Z]\s*\|\s*)?[^|]+\|\s*[A-Za-z0-9²³/%.]{1,8}\s*(?:\|\s*[\d.,]*)?\s*$"
    r"|^\s*\d{2}\.\d{3}\.\d{4}-[0-9A-Z]\s*\|[^|]+$"            # código | descrição (quebra de linha)
    r"|^\s*c[oó]digo\s*\|\s*descri[cç][aã]o\s*\|\s*unid\.?\s*\|\s*pre[cç]o"
    r"|^\s*\d{2}\s*\|\s*[A-ZÀ-Ú ,.()/-]+$|^\s*categorias cat[aá]logo|^\s*cat[aá]logo\s*\|", re.I)
# CPF (inteiro ou mascarado) nunca chega ao trecho que se exibe (LGPD) nem ao shingle
_RX_CPF = re.compile(r"(?:\d{3}|\*{3})\.\d{3}\.\d{3}-(?:\d{2}|\*{2})|\b\d{11}\b")
_RX_PROC_SEI = re.compile(r"\b(?:sei\s*[-–]?\s*)?\d{5,6}\s*/\s*\d{5,6}\s*/\s*\d{4}\b", re.I)
_RX_NUM_DOC = re.compile(r"\b\d{8,10}\b")
_RX_TOKEN = re.compile(r"[a-z0-9]+")


def _sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def assinaturas(texto: str) -> list[str]:
    """Bloco de assinatura eletrônica como lista ordenada 'nome|dd/mm/aaaa|hh:mm' (sem duplicata).

    É metadado, não corpo: sai da comparação e serve para reconhecer a CÓPIA do mesmo documento
    (as mesmas assinaturas, nas mesmas datas) juntada noutro processo."""
    out = set()
    for m in _RX_ASSINATURA.finditer(texto or ""):
        quem = re.sub(r"\s+", " ", _sem_acento(m.group("quem"))).strip()
        out.add(f"{quem}|{m.group('data')}|{m.group('hora') or ''}")
    return sorted(out)


def normalizar_corpo(texto: str) -> str:
    """Corpo descritivo do documento: sem etiqueta, assinatura, rodapé SEI e números SEI."""
    # linha repetida conta uma vez: a extração do PDF repete páginas inteiras (o relatório 90902746
    # vem 3× no acervo) e o bloco de signatários repetido virava "trecho comum" de 169 palavras
    vistas: set[str] = set()
    linhas = []
    for ln in (texto or "").splitlines():
        chave = " ".join(ln.split()).lower()
        if (not chave or chave in vistas or any(rx.search(ln) for rx in _LINHAS_FORA)
                or _RX_LINHA_CATALOGO.search(ln)):
            continue
        vistas.add(chave)
        linhas.append(ln)
    t = _sem_acento(_RX_CPF.sub(" cpf ", "\n".join(linhas)))
    t = _RX_PROC_SEI.sub(" procsei ", t)
    t = _RX_NUM_DOC.sub(" nsei ", t)
    return " ".join(_RX_TOKEN.findall(t))


_RX_ROTULO_VAZIO = re.compile(r"^[^:\d]{1,60}:\s*$")
_RX_LACUNA = re.compile(r"_{4,}|\(\s{0,3}\)|\[\s{0,3}\]")


def formulario_em_branco(texto: str) -> bool:
    """Formulário NÃO preenchido (modelo anexo ao edital, "Anexo II – Atestação Física" com
    "_____/_____/____", RDO com "Data:", "RDO:", "Contrato:" vazios). 3ª rodada (18/11/2026): o
    "Anexo 15 F – Relatório Diário de Obras" do CBMERJ (em branco) e a "Atestação Física" da SEEDUC
    (em branco) apareciam como corpo idêntico em contratos diferentes. Branco igual a branco não é
    relato reaproveitado. Exige pouco número no corpo (formulário preenchido tem data, quantidade)."""
    linhas = [ln.strip() for ln in (texto or "").splitlines() if ln.strip()]
    if not linhas:
        return False
    lacunas = len(_RX_LACUNA.findall(texto))
    rotulos = sum(1 for ln in linhas if _RX_ROTULO_VAZIO.match(ln))
    numeros = sum(1 for t in normalizar_corpo(texto).split() if t[0].isdigit())
    return numeros < 15 and (lacunas >= 3 or (rotulos >= 5 and rotulos / len(linhas) >= 0.25))


def predominio_de_catalogo(texto: str) -> bool:
    """Metade ou mais das linhas é catálogo de preços (EMOP/SINAPI). 4ª rodada: depois de tirar as linhas
    de catálogo, o resto da "Planilha Boletim de Medição Excel" (preço quebrado em linha própria, título de
    aba) ainda casava entre dois credores. Documento que é, no essencial, o catálogo público sai inteiro."""
    linhas = [ln for ln in (texto or "").splitlines() if ln.strip()]
    return len(linhas) >= 50 and sum(1 for ln in linhas if _RX_LINHA_CATALOGO.search(ln)) >= 0.5 * len(linhas)


def shingles(corpo: str, k: int = K_SHINGLE) -> set[int]:
    """Conjunto de shingles de k palavras, cada um como inteiro de 63 bits (blake2b, estável entre
    processos e máquinas — `hash()` do Python muda com PYTHONHASHSEED)."""
    toks = corpo.split()
    if len(toks) < k:
        return set()
    out = set()
    for i in range(len(toks) - k + 1):
        h = hashlib.blake2b(" ".join(toks[i:i + k]).encode(), digest_size=8).digest()
        out.add(int.from_bytes(h, "big") >> 1)
    return out


def hash_corpo(corpo: str) -> str:
    return hashlib.sha256(corpo.encode()).hexdigest()


_RX_NUM_TITULO = re.compile(r"\((\d{7,10})\)\s*$|\b(\d{7,10})\s*$")


def numero_sei_do_titulo(titulo: str) -> str | None:
    m = _RX_NUM_TITULO.search(str(titulo or "").strip())
    return (m.group(1) or m.group(2)) if m else None


_RX_CONTRATO = re.compile(r"contrato\s*(?:n\s*[o°º.]?\s*)?(\d{1,4})\s*/\s*(20\d\d)\b")


def contratos_citados(texto: str) -> set[str]:
    """'Contrato nº 034/2026' → {'34/2026'} (número sem zero à esquerda)."""
    return {f"{int(n)}/{a}" for n, a in _RX_CONTRATO.findall(_sem_acento(texto or ""))}


# ── seleção no acervo ───────────────────────────────────────────────────────────────────────────

def classificar_doc(d: dict) -> tuple[str, str]:
    """(fase, tipo) recalculados do título (o que o arquivo gravou pode ser de regra antiga)."""
    from compliance_agent.sei import fases, manifesto_norm
    titulo = str(d.get("titulo") or "")
    return fases.classificar_com_tipo(titulo, manifesto_norm.tipo_canonico(d.get("tipo"), titulo))


# Ato de DESIGNAÇÃO não é relato de execução: "Portaria Comissão de Fiscalização" casa `fiscalizacao`
# em `fases.py`, e a mesma portaria (ou a publicação no DOERJ que nomeia a comissão) juntada em vários
# processos do mesmo contrato é o mesmo ato, não execução copiada. Medido no controle de 18/11/2026:
# 3 portarias idênticas da SEHIS e 2 publicações da comissão da SEEDUC viravam par. Relatório,
# diário, medição e atesto continuam dentro mesmo quando o título cita a comissão.
# 18/11/2026, 1ª rodada no acervo: "Publicação de TODAS as Portarias de Gestão" (78 pares) e "Publicação
# da Comissão de Gestão, Acompanhamento…" (106 pares) passavam — plural e "publicação" faltavam.
_RX_TITULO_NAO_EXECUCAO = re.compile(r"\bportarias?\b|\bdesigna|\bnomea|\bnomeia|\bcomissao\b")
_RX_TITULO_RELATO = re.compile(r"relat|diario de obra|medi|atest|boletim|vistoria|recebimento|parecer")
# Sempre fora, mesmo quando o título fala em recebimento/medição: 2ª rodada (18/11/2026), dos 450 pares
# de corpo IDÊNTICO, ~270 eram publicação no D.O. da comissão, "Documento - Modelo de recebimento"
# (formulário EM BRANCO), "Resolução SECC 28/2021 - Regulamento", "Anotação ART/RRT" do fiscal e
# "Nomeção" (sic) da comissão — atos e modelos, não relato de execução.
# 4ª rodada: "Relatório ART – Atestado de Responsabilidade Técnica", "Guia de ISS e Comp. Pagto",
# "E-mail de sol./rec. doc", "Atestado de veracidade" e o "Boletim Comissão de Fiscalização" do CBMERJ
# (lista de membros) — documentos administrativos, não relato de execução.
_RX_TITULO_SEMPRE_FORA = re.compile(r"\bpublicac|\bd o\b|diario oficial|\bdoerj\b|resolucao|regulamento"
                                    r"|\bmodelo\b|\banotacao\b|\brrt\b|\bnomecao\b|\bnomeacao\b"
                                    r"|\bart\b|responsabilidade tecnica|\bguia\b|\be ?mail\b|veracidade"
                                    r"|boletim (da )?comiss|habilitac")


def titulo_e_de_designacao(titulo: str) -> bool:
    """Título de ato/modelo (designação, publicação, regulamento, formulário em branco, ART)."""
    t = re.sub(r"[^a-z0-9 ]+", " ", _sem_acento(titulo)).strip()
    t = re.sub(r"\s+", " ", t)
    if _RX_TITULO_SEMPRE_FORA.search(t):
        return True
    return bool(_RX_TITULO_NAO_EXECUCAO.search(t)) and not _RX_TITULO_RELATO.search(t)


def documentos_de_execucao(pasta: Path | str) -> tuple[list[dict], list[dict]]:
    """(com_texto, indisponiveis) dos documentos de execução de um processo do acervo."""
    from compliance_agent.sei import acervo_texto
    pasta = Path(pasta)
    try:
        man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
    processo = str(man.get("processo") or pasta.name)
    ok, fora = [], []
    for d in man.get("docs") or []:
        if not isinstance(d, dict):
            continue
        fase, tipo = classificar_doc(d)
        if fase != "execucao" or tipo not in TIPOS_EXECUCAO or titulo_e_de_designacao(d.get("titulo") or ""):
            continue
        base = {"processo": processo, "pasta": pasta.name, "i": d.get("i"),
                "titulo": str(d.get("titulo") or ""), "tipo": tipo,
                "sei": numero_sei_do_titulo(d.get("titulo") or ""), "arquivo": d.get("texto")}
        texto = acervo_texto.ler(pasta, d) if d.get("texto") else ""
        if not texto.strip():
            fora.append({**base, "estado": "INDISPONÍVEL", "motivo": "sem texto no acervo"})
            continue
        ok.append({**base, "texto": texto})
    return ok, fora


def contratos_do_processo(pasta: Path | str) -> list[str]:
    """Contratos que o PROCESSO cita nos títulos e no início dos documentos de contrato/execução."""
    from compliance_agent.sei import acervo_texto
    pasta = Path(pasta)
    try:
        man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    c: Counter = Counter()
    for d in man.get("docs") or []:
        if not isinstance(d, dict):
            continue
        c.update(contratos_citados(str(d.get("titulo") or "")))
        _, tipo = classificar_doc(d)
        if tipo in ("contrato", "ordem_inicio") and d.get("texto"):
            c.update(contratos_citados(acervo_texto.ler(pasta, d, 5000)))
    return [k for k, _ in c.most_common()]


_CREDOR_SIAFE: dict[str, str] | None = None


def _chave_proc(numero: str) -> str:
    return re.sub(r"\D", "", str(numero or ""))


def credor_siafe(numero: str) -> str | None:
    """Credor das OB do SIAFE cujo campo `processo` é este processo (maior soma; OB = verdade).

    Medido em 18/11/2026: o texto do Contrato 034/2026 da SEHIS traz o CNPJ da PRÓPRIA SEHIS no
    campo do contratado (erro material) e o fallback por texto devolvia o órgão como credor; o SIAFE
    devolve a Construtora Augusto Velloso. Só OB Contabilizada (a anulada não diz quem recebeu)."""
    global _CREDOR_SIAFE
    if _CREDOR_SIAFE is None:
        import sqlite3
        _CREDOR_SIAFE = {}
        db = REPO / "data" / "compliance.db"
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                somas: dict[tuple[str, str], float] = defaultdict(float)
                for proc, cred, v in con.execute(
                        "SELECT processo, credor, SUM(valor) FROM ob_orcamentaria_siafe "
                        "WHERE status='Contabilizado' AND processo LIKE '%/%/%' AND credor IS NOT NULL "
                        "GROUP BY 1, 2"):
                    cred = re.sub(r"\D", "", str(cred or ""))
                    if len(cred) == 14:
                        somas[(_chave_proc(proc), cred)] += float(v or 0)
            finally:
                con.close()
        except sqlite3.Error:
            somas = {}
        melhor: dict[str, tuple[float, str]] = {}
        for (k, cred), v in somas.items():
            if k not in melhor or v > melhor[k][0]:
                melhor[k] = (v, cred)
        _CREDOR_SIAFE = {k: c for k, (_, c) in melhor.items()}
    return _CREDOR_SIAFE.get(_chave_proc(numero))


def credor_do_processo(pasta: Path | str, docs_exec: list[dict]) -> tuple[str | None, str]:
    """(CNPJ, fonte). Reaproveita a resolução da casa (`processo_360`): `sei_arvore` (maior
    favorecido), depois o texto dos documentos de contrato; por fim os documentos de execução do
    próprio processo, pela MESMA regra (DV válido, sem ente público, sem quem se declara
    CONTRATANTE). Sem nada: (None, 'INDISPONÍVEL')."""
    from compliance_agent import processo_360 as P
    from compliance_agent.sei import fases
    pasta = Path(pasta)
    try:
        man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        man = {}
    numero = str(man.get("processo") or pasta.name)
    c = credor_siafe(numero)
    if c:
        return c, "SIAFE ob_orcamentaria_siafe.processo"
    c = P._cnpj_vencedor(numero)
    if c:
        return c, "sei_arvore.fornecedores"
    docs = [{**d, "tipo": classificar_doc(d)[1]} for d in man.get("docs") or [] if isinstance(d, dict)]
    c = P._cnpj_do_texto(pasta, docs)
    if c:
        return c, "texto do contrato no acervo"
    # mesma regra sobre execução/despesa: o relatório e a NF trazem o CNPJ da contratada
    alvo = [{**d, "tipo": "contrato"} for d in docs
            if fases.fase_do_tipo(d["tipo"]) in ("execucao", "despesa")]
    c = P._cnpj_do_texto(pasta, alvo)
    if c:
        return c, "texto de execução/despesa no acervo"
    return None, "INDISPONÍVEL"


# ── comparação ──────────────────────────────────────────────────────────────────────────────────

_JA_FILTRADO: dict = {}   # sentinela: `shingles` do doc já é o conjunto descritivo


def descritivo(sh: set[int], df_credores: dict[int, int] | None, b: int = B_CREDORES) -> set[int]:
    """Shingles que NÃO são modelo institucional (aparecem em menos de `b` credores)."""
    if df_credores is _JA_FILTRADO:
        return set(sh)
    if not df_credores:
        return set(sh)
    return {s for s in sh if df_credores.get(s, 0) < b}


def trechos_comuns(corpo_a: str, sh_comum: set[int], k: int = K_SHINGLE,
                   max_trechos: int = 3, max_palavras: int = 60) -> list[str]:
    """Os trechos LITERAIS (normalizados) que os dois documentos compartilham — o que um revisor
    confere lado a lado. Maiores primeiro."""
    toks = corpo_a.split()
    marc = _marcas(toks, sh_comum, k)
    runs, ini = [], None
    for i, m in enumerate(marc + [False]):
        if m and ini is None:
            ini = i
        elif not m and ini is not None:
            runs.append((ini, i)); ini = None
    runs.sort(key=lambda r: r[0] - r[1])
    return [" ".join(toks[a:min(b, a + max_palavras)]) for a, b in runs[:max_trechos]]


def _marcas(toks: list[str], sh_comum: set[int], k: int = K_SHINGLE) -> list[bool]:
    marc = [False] * len(toks)
    for i in range(len(toks) - k + 1):
        h = hashlib.blake2b(" ".join(toks[i:i + k]).encode(), digest_size=8).digest()
        if (int.from_bytes(h, "big") >> 1) in sh_comum:
            for j in range(i, i + k):
                marc[j] = True
    return marc


def trecho_mais_longo(corpo_a: str, sh_comum: set[int]) -> dict:
    """Maior trecho contínuo de A coberto por shingles comuns: palavras, fração numérica, texto."""
    toks = corpo_a.split()
    marc = _marcas(toks, sh_comum)
    best, ini = (0, 0), None
    for i, m in enumerate(marc + [False]):
        if m and ini is None:
            ini = i
        elif not m and ini is not None:
            if i - ini > best[1] - best[0]:
                best = (ini, i)
            ini = None
    w = toks[best[0]:best[1]]
    num = sum(1 for x in w if any(c.isdigit() for c in x))
    return {"palavras": len(w), "fracao_numerica": round(num / len(w), 3) if w else 0.0,
            "inicio": " ".join(w[:80])}


def _contratos_do_doc(d: dict) -> set[str]:
    """Contrato a que o documento PERTENCE: o do processo (títulos e instrumento); se o processo não
    diz, o que o próprio documento cita no cabeçalho. A ordem importa: um diário copiado cita o
    contrato de ORIGEM, e é o processo que diz a que contrato ele foi juntado."""
    return set(d.get("contratos") or []) or set(d.get("contratos_doc") or [])


def comparar(a: dict, b: dict, df_credores: dict[int, int] | None = None,
             b_credores: int = B_CREDORES, sh_contrato: set[int] | None = None) -> dict:
    """Par de documentos já preparados (`preparar`) → métricas e classificação.

    Classes: `mesmo_processo` · `mesmo_documento` (mesmo nº SEI) · `copia_do_mesmo_documento`
    (mesmas assinaturas e datas) · `modelo_institucional` (corpo descritivo em comum pequeno) ·
    `sem_semelhanca` · `reuso_execucao` (o achado)."""
    out = {"a": _ident(a), "b": _ident(b)}
    da = descritivo(a["shingles"], df_credores, b_credores)
    db = descritivo(b["shingles"], df_credores, b_credores)
    if sh_contrato:      # texto que vem do CONTRATO (objeto, prazos, cláusulas) não descreve execução
        da, db = da - sh_contrato, db - sh_contrato
    comum = da & db
    menor = min(len(da), len(db))
    cont = len(comum) / menor if menor else 0.0
    uniao = len(da | db)
    out.update({
        "identico": a["hash"] == b["hash"],
        "shingles_a": len(a["shingles"]), "shingles_b": len(b["shingles"]),
        "descritivos_a": len(da), "descritivos_b": len(db),
        "descritivos_comuns": len(comum),
        "contencao": round(cont, 4), "jaccard": round(len(comum) / uniao, 4) if uniao else 0.0,
        "contratos_a": sorted(_contratos_do_doc(a)), "contratos_b": sorted(_contratos_do_doc(b)),
    })
    ca, cb = _contratos_do_doc(a), _contratos_do_doc(b)
    contratos_diferentes = None if not (ca and cb) else not (ca & cb)
    if a["processo"] == b["processo"]:
        classe = "mesmo_processo"
    elif a.get("sei") and a.get("sei") == b.get("sei"):
        classe = "mesmo_documento"
    elif a.get("assinaturas") and a.get("assinaturas") == b.get("assinaturas"):
        classe = "copia_do_mesmo_documento"
    elif a.get("em_branco") or b.get("em_branco"):
        classe = "formulario_em_branco"
    elif a.get("catalogo") or b.get("catalogo"):
        classe = "catalogo_de_precos"
    elif len(comum) >= MIN_DESCRITIVO and cont >= LIMIAR_CONTENCAO:
        classe = "reuso_execucao"
        out["forma"] = "integral"
    # o TRECHO só vale entre contratos DIFERENTES: dentro do mesmo contrato o miolo que se repete é o
    # cabeçalho do contrato (objeto, vigência, fiscais) — 1ª rodada no acervo, 3.140 pares assim
    elif (contratos_diferentes is True
          and len(comum) >= MIN_DESCRITIVO and a.get("tipo") in TIPOS_NARRATIVOS
          and b.get("tipo") in TIPOS_NARRATIVOS
          and (tr := trecho_mais_longo(a["corpo"], _raros(comum, a, b)))["palavras"] >= MIN_TRECHO_PALAVRAS
          and tr["fracao_numerica"] <= MAX_FRACAO_NUMERICA_TRECHO):
        classe = "reuso_execucao"
        out["forma"] = "trecho"
        out["trecho_mais_longo"] = tr
    elif len(a["shingles"] & b["shingles"]) >= MIN_DESCRITIVO and (
            len(a["shingles"] & b["shingles"]) / max(1, min(len(a["shingles"]), len(b["shingles"])))
            >= LIMIAR_CONTENCAO):
        classe = "modelo_institucional"     # parecido no bruto, mas o que se repete é o modelo
    else:
        classe = "sem_semelhanca"
    out["classe"] = classe
    if classe == "reuso_execucao":
        out["contratos_diferentes"] = contratos_diferentes
        # NÍVEL (força do indício, medido no acervo em 18/11/2026): corpo idêntico é o mais forte;
        # quase idêntico entre contratos diferentes vem depois; dentro do MESMO contrato o quase
        # idêntico é, na maioria, o relatório mensal do fiscal com o cabeçalho fixo — fraco, só leitura.
        mesmo_titulo = _titulo_sem_numero(a.get("titulo")) == _titulo_sem_numero(b.get("titulo"))
        out["mesmo_titulo"] = mesmo_titulo
        if out["identico"]:
            nivel = {True: "identico_contratos_diferentes",
                     False: ("identico_mesmo_contrato_mesmo_titulo" if mesmo_titulo
                             else "identico_mesmo_contrato_titulos_diferentes"),
                     None: "identico_contrato_indisponivel"}[contratos_diferentes]
        elif out["forma"] == "trecho":
            nivel = "trecho_contratos_diferentes"
        else:
            nivel = {True: "quase_identico_contratos_diferentes", False: "quase_identico_mesmo_contrato",
                     None: "quase_identico_contrato_indisponivel"}[contratos_diferentes]
        out["nivel"] = nivel
        out["relacao_contratual"] = {True: "contratos diferentes", False: "mesmo contrato",
                                     None: "contrato indisponível"}[contratos_diferentes]
        rel = (None if not (a.get("credor") and b.get("credor"))
               else a["credor"] == b["credor"])
        out["mesmo_credor"] = rel
        # VERIFICADO = identidade literal conferida por código (mesmo hash do corpo normalizado e o
        # nº SEI de cada documento no próprio texto). A INTERPRETAÇÃO segue indício a verificar.
        out["estado"] = "VERIFICADO" if (out["identico"] and _sei_conferido(a)
                                         and _sei_conferido(b)) else "PENDENTE"
        out.setdefault("trecho_mais_longo", trecho_mais_longo(a["corpo"], comum))
        out["trechos_comuns"] = trechos_comuns(a["corpo"], comum)
    return out


def _titulo_sem_numero(t: str | None) -> str:
    """Título sem o nº SEI — 'Planilha 31ª Medição (123)' e '(456)' são o mesmo título."""
    t = re.sub(r"\(?\b\d{7,10}\b\)?", " ", _sem_acento(str(t or "")))
    return " ".join(re.findall(r"[a-z0-9]+", t))


def _raros(comum: set[int], a: dict, b: dict) -> set[int]:
    """Shingles comuns que aparecem em poucos documentos do acervo (`raros`, calculado em `parear`).
    Fora da varredura (par isolado) não há frequência a medir: vale o comum inteiro."""
    ra, rb = a.get("raros"), b.get("raros")
    if ra is None or rb is None:
        return comum
    return comum & ra & rb


def _sei_conferido(d: dict) -> bool:
    """O número SEI do título aparece literalmente no texto do próprio documento?"""
    return bool(d.get("sei")) and d["sei"] in (d.get("texto_bruto_inicio") or "")


def _ident(d: dict) -> dict:
    return {k: d.get(k) for k in ("processo", "sei", "titulo", "tipo", "credor", "credor_fonte",
                                  "arquivo", "assinaturas")}


def preparar(doc: dict) -> dict:
    """Documento lido do acervo → forma comparável (corpo, hash, shingles, assinaturas)."""
    texto = doc.get("texto") or ""
    corpo = normalizar_corpo(texto)
    sei = doc.get("sei")
    return {**{k: v for k, v in doc.items() if k != "texto"},
            "corpo": corpo, "hash": hash_corpo(corpo), "shingles": shingles(corpo),
            "assinaturas": assinaturas(texto),
            "contratos_doc": sorted(contratos_citados(texto[:4000])),
            "em_branco": formulario_em_branco(texto),
            "catalogo": predominio_de_catalogo(texto),
            # o SEI aparece no rodapé "código verificador N" e no cabeçalho "[Título (N)]" do
            # acervo; o rodapé é do SEI, não nosso — por isso confere-se no texto SEM etiqueta
            "texto_bruto_inicio": sei if (sei and sei in texto) else ""}


# ── varredura do acervo (3 etapas: exportar na VM-1, parear onde houver CPU, resumir) ────────────

def _pastas_com_execucao(base: Path):
    """(pasta, manifest) dos processos que têm ao menos um documento de execução — só lê manifests."""
    for pasta in sorted(p for p in Path(base).iterdir() if (p / "manifest.json").exists()):
        try:
            man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        docs = [d for d in man.get("docs") or [] if isinstance(d, dict)]
        tipos = [(d, classificar_doc(d)) for d in docs]
        if any(f == "execucao" and t in TIPOS_EXECUCAO and not titulo_e_de_designacao(d.get("titulo") or "")
               for d, (f, t) in tipos):
            yield pasta, man, tipos


_TIPOS_DO_CREDOR = ("contrato", "ordem_inicio", "homologacao", "ata_rp", "contratacao_direta", "adjudicacao")


def mapear_credores(base: Path = BASE_ACERVO, saida: Path | None = None,
                    lista: Path | None = None, so_lista: bool = False) -> dict:
    """Etapa 0 (perto do banco): processo → [CNPJ, fonte] pela resolução de `credor_do_processo`,
    e (opcional) a lista de arquivos de texto que a etapa 1 precisa — para levar só eles a outra
    máquina. Assim o banco não precisa sair da VM-1."""
    mapa, arquivos, fontes = {}, [], Counter()
    for pasta, man, tipos in _pastas_com_execucao(base):
        numero = str(man.get("processo") or pasta.name)
        c, f = (None, "não calculado") if so_lista else credor_do_processo(pasta, [])
        mapa[numero] = [c, f]
        fontes[f] += 1
        arquivos.append(f"{pasta.name}/manifest.json")
        for d, (fase, tipo) in tipos:
            # execução (o que se compara) + o que a resolução do credor e dos contratos lê
            if d.get("texto") and (fase in ("execucao", "despesa") or tipo in _TIPOS_DO_CREDOR):
                arquivos.append(f"{pasta.name}/{d['texto']}")
    if saida:
        Path(saida).write_text(json.dumps(mapa, ensure_ascii=False), encoding="utf-8")
    if lista:
        Path(lista).write_text("\n".join(arquivos) + "\n", encoding="utf-8")
    return {"processos": len(mapa), "fontes": dict(fontes), "arquivos": len(arquivos)}


def exportar(base: Path = BASE_ACERVO, saida: Path | None = None, limite: int | None = None,
             credores: dict | None = None) -> dict:
    """Etapa 1 (leve, perto do acervo e do banco): documentos de execução → jsonl.gz com corpo,
    hash, assinaturas, credor e contratos. Os INDISPONÍVEIS vão para o mesmo arquivo, marcados."""
    saida = Path(saida or "reuso_exec_corpus.jsonl.gz")
    n_proc = n_doc = n_ind = 0
    with gzip.open(saida, "wt", encoding="utf-8") as f:
        for pasta in sorted(p for p in Path(base).iterdir() if (p / "manifest.json").exists()):
            if limite and n_proc >= limite:
                break
            docs, fora = documentos_de_execucao(pasta)
            for x in fora:
                f.write(json.dumps({**x, "registro": "indisponivel"}, ensure_ascii=False) + "\n")
                n_ind += 1
            if not docs:
                continue
            n_proc += 1
            if credores is None:
                credor, fonte = credor_do_processo(pasta, docs)
            else:
                credor, fonte = (credores.get(docs[0]["processo"]) or [None, "INDISPONÍVEL"])
            contratos = contratos_do_processo(pasta)
            for corpo in textos_de_contrato(pasta):
                f.write(json.dumps({"registro": "texto_do_contrato", "processo": docs[0]["processo"],
                                    "corpo": corpo}, ensure_ascii=False) + "\n")
            for d in docs:
                p = preparar(d)
                f.write(json.dumps({
                    "registro": "doc", **{k: p[k] for k in ("processo", "pasta", "i", "titulo", "tipo",
                                                            "sei", "arquivo", "corpo", "hash",
                                                            "assinaturas", "texto_bruto_inicio",
                                                            "contratos_doc", "em_branco", "catalogo")},
                    "credor": credor, "credor_fonte": fonte, "contratos": contratos,
                }, ensure_ascii=False) + "\n")
                n_doc += 1
    return {"processos_com_execucao": n_proc, "documentos": n_doc, "indisponiveis": n_ind,
            "saida": str(saida)}


def textos_de_contrato(pasta: Path | str) -> list[str]:
    """Corpo normalizado dos instrumentos do processo (contrato, ata de RP, ordem de início)."""
    from compliance_agent.sei import acervo_texto
    pasta = Path(pasta)
    try:
        man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for d in man.get("docs") or []:
        if isinstance(d, dict) and d.get("texto") and classificar_doc(d)[1] in ("contrato", "ata_rp", "ordem_inicio"):
            out.append(normalizar_corpo(acervo_texto.ler(pasta, d)))
    return out


def _carregar_corpus(arq: Path) -> tuple[list[dict], list[dict], list[str]]:
    docs, ind, contratos = [], [], []
    with gzip.open(arq, "rt", encoding="utf-8") as f:
        for ln in f:
            r = json.loads(ln)
            reg = r.get("registro")
            if reg == "doc":
                docs.append(r)
            elif reg == "texto_do_contrato":
                contratos.append(r["corpo"])
            else:
                ind.append(r)
    return docs, ind, contratos


def _shingles_de(corpo: str):
    import numpy as np
    return np.fromiter(sorted(shingles(corpo)), dtype=np.int64)


def parear(corpus: Path, saida: Path, processos: int = 1, b_credores: int = B_CREDORES) -> dict:
    """Etapa 2 (pesada): índice invertido EXATO sobre o corpus exportado → pares classificados.

    1. shingles de cada documento (multiprocesso); 2. frequência de documento por CREDOR (credor
    desconhecido conta como credor próprio do processo — nunca some do denominador); 3. shingle em
    ≥ b credores = modelo institucional, fora; 4. postings descritivos com ≥2 processos geram
    candidatos (posting com mais de G_MAX documentos vira 'família grande', relatada à parte);
    5. cada candidato é conferido pela interseção COMPLETA dos conjuntos descritivos (`comparar`),
    e também pelo conjunto bruto (para separar modelo institucional de corpo sem semelhança)."""
    import numpy as np
    docs, ind, corpos_contrato = _carregar_corpus(Path(corpus))
    from multiprocessing import Pool
    if processos > 1:
        with Pool(processos) as pool:
            listas = pool.map(_shingles_de, [d["corpo"] for d in docs], chunksize=32)
    else:
        listas = [_shingles_de(d["corpo"]) for d in docs]
    # shingles que vêm do texto dos contratos do acervo (um array ordenado, sem repetir)
    if corpos_contrato:
        if processos > 1:
            with Pool(processos) as pool:
                lc = pool.map(_shingles_de, corpos_contrato, chunksize=8)
        else:
            lc = [_shingles_de(c) for c in corpos_contrato]
        sh_contrato_arr = np.unique(np.concatenate(lc)) if lc else np.zeros(0, np.int64)
        del lc
    else:
        sh_contrato_arr = np.zeros(0, np.int64)
    cred_ids: dict[str, int] = {}
    cred_doc = np.array([cred_ids.setdefault(d.get("credor") or f"?{d['processo']}", len(cred_ids))
                         for d in docs], dtype=np.int32)
    proc_ids: dict[str, int] = {}
    proc_doc = np.array([proc_ids.setdefault(d["processo"], len(proc_ids)) for d in docs], dtype=np.int32)
    tam = np.array([len(x) for x in listas], dtype=np.int64)
    H = np.concatenate(listas) if len(listas) else np.zeros(0, np.int64)
    D = np.repeat(np.arange(len(docs), dtype=np.int32), tam)
    C = cred_doc[D]
    ordem = np.lexsort((D, C, H))
    H, D, C = H[ordem], D[ordem], C[ordem]
    del ordem
    n = len(H)
    novo_h = np.ones(n, bool); novo_h[1:] = H[1:] != H[:-1]
    novo_hc = novo_h.copy(); novo_hc[1:] |= C[1:] != C[:-1]
    ini = np.flatnonzero(novo_h)
    dfc_grupo = np.add.reduceat(novo_hc.astype(np.int32), ini) if n else np.zeros(0, np.int32)
    tam_grupo = np.diff(np.append(ini, n))
    dfc = np.repeat(dfc_grupo, tam_grupo)
    del novo_hc
    do_contrato = np.isin(H, sh_contrato_arr, assume_unique=False)
    descr = (dfc < b_credores) & ~do_contrato
    # conjunto descritivo de cada documento (para a conferência exata) e quantos shingles são modelo
    modelo_por_doc = np.bincount(D[~descr], minlength=len(docs))
    # grupos descritivos com ≥2 documentos
    g_ok = (dfc_grupo < b_credores) & (tam_grupo >= 2) & ~do_contrato[ini]
    contagem: Counter = Counter()
    grupos: Counter = Counter()
    familias_grandes: Counter = Counter()
    for gi in np.flatnonzero(g_ok):
        a, t = ini[gi], tam_grupo[gi]
        lst = D[a:a + t]
        if len(set(proc_doc[lst].tolist())) < 2:
            continue
        if t > G_MAX:
            familias_grandes[tuple(sorted({docs[i]["processo"] for i in lst.tolist()})[:6])] += 1
            continue
        grupos[tuple(lst.tolist())] += 1
    for lst, peso in grupos.items():
        for x in range(len(lst)):
            px = proc_doc[lst[x]]
            for y in range(x + 1, len(lst)):
                if proc_doc[lst[y]] != px:
                    contagem[(lst[x], lst[y])] += peso
    del grupos
    cand = [(x, y) for (x, y), k in contagem.items() if k >= MIN_DESCRITIVO]
    envolvidos = sorted({i for p in cand for i in p})
    # conjuntos completos só de quem é candidato
    por_doc_descr: dict[int, set] = {}
    alvo = np.zeros(len(docs), bool); alvo[envolvidos] = True
    sel = alvo[D] & descr
    for i in envolvidos:
        por_doc_descr[i] = set()
    df_docs = np.repeat(tam_grupo, tam_grupo)
    por_doc_raro: dict[int, set] = {i: set() for i in envolvidos}
    for h, d, nd in zip(H[sel].tolist(), D[sel].tolist(), df_docs[sel].tolist()):
        por_doc_descr[d].add(h)
        if nd <= MAX_DOCS_TRECHO:
            por_doc_raro[d].add(h)
    pares, classes = [], Counter()
    for x, y in cand:
        a = {**docs[x], "shingles": por_doc_descr[x], "raros": por_doc_raro[x]}
        b = {**docs[y], "shingles": por_doc_descr[y], "raros": por_doc_raro[y]}
        r = comparar(a, b, _JA_FILTRADO, b_credores)
        r["shingles_modelo_a"] = int(modelo_por_doc[x]); r["shingles_modelo_b"] = int(modelo_por_doc[y])
        classes[r["classe"]] += 1
        if r["classe"] == "reuso_execucao":
            pares.append(r)
    pares.sort(key=lambda r: (-r["descritivos_comuns"]))
    resumo = {
        "detector": DETECTOR_ID, "documentos": len(docs), "indisponiveis": len(ind),
        "processos": len(proc_ids), "credores_distintos_ou_processo_sem_credor": len(cred_ids),
        "docs_sem_credor": sum(1 for d in docs if not d.get("credor")),
        "shingles_total": int(n), "shingles_modelo": int((dfc >= b_credores).sum()),
        "shingles_do_contrato": int(do_contrato.sum()), "textos_de_contrato": len(corpos_contrato),
        "parametros": {"k": K_SHINGLE, "b_credores": b_credores, "min_descritivo": MIN_DESCRITIVO,
                       "limiar_contencao": LIMIAR_CONTENCAO, "g_max": G_MAX,
                       "min_trecho_palavras": MIN_TRECHO_PALAVRAS, "max_docs_trecho": MAX_DOCS_TRECHO},
        "candidatos": len(cand),
        "classes_dos_candidatos": dict(classes),
        "familias_grandes": [{"processos_amostra": list(k), "shingles": v}
                             for k, v in familias_grandes.most_common(50)],
        "pares": pares,
        "indisponiveis_por_tipo": dict(Counter(r.get("tipo") for r in ind)),
    }
    Path(saida).write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: v for k, v in resumo.items() if k not in ("pares", "familias_grandes")} | {
        "pares": len(pares), "familias_grandes": len(familias_grandes)}


def _orgao(processo: str) -> str:
    """Prefixo do número SEI-RJ (código da unidade autuadora, ex.: 490001 SEHIS, 030001 SEEDUC)."""
    return re.sub(r"\D", "", str(processo or ""))[:6]


def _chave_par(r: dict) -> tuple:
    return tuple(sorted([(r["a"]["processo"], r["a"]["sei"]), (r["b"]["processo"], r["b"]["sei"])]))


def resumir(pares_json: Path, sem_filtro_json: Path | None = None) -> dict:
    """Etapa 3 (leve): números do acervo — pares por forma/estado/relação de credor, por credor e
    por órgão, famílias (componentes conexos de documentos) e, se dada a rodada SEM o filtro de
    modelo institucional, quantos pares só existiam por causa do modelo."""
    R = json.loads(Path(pares_json).read_text(encoding="utf-8"))
    pares = R["pares"]
    por = lambda f: dict(Counter(f(r) for r in pares).most_common())  # noqa: E731
    rel = lambda r: {True: "mesmo credor", False: "credores diferentes", None: "credor indisponível"}[r.get("mesmo_credor")]  # noqa: E731
    # famílias: documentos ligados por algum par
    pai: dict = {}

    def raiz(x):
        while pai.setdefault(x, x) != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x
    for r in pares:
        a, b = (r["a"]["processo"], r["a"]["sei"]), (r["b"]["processo"], r["b"]["sei"])
        pai[raiz(a)] = raiz(b)
    fam: dict = defaultdict(set)
    for x in list(pai):
        fam[raiz(x)].add(x)
    out = {
        "documentos_comparados": R["documentos"], "processos": R["processos"],
        "indisponiveis": R["indisponiveis"], "parametros": R["parametros"],
        "pares": len(pares),
        "por_nivel": por(lambda r: r.get("nivel")),
        "pares_de_processos_por_nivel": dict(Counter(
            n for n, _ in {(r.get("nivel"), tuple(sorted([r["a"]["processo"], r["b"]["processo"]])))
                           for r in pares}).most_common()),
        "por_nivel_e_credor": por(lambda r: f"{r.get('nivel')} · {rel(r)}"),
        "por_forma_estado": por(lambda r: f"{r['forma']} · {r['estado']}"),
        "por_relacao_de_credor": por(rel),
        "por_credor_mesmo_credor": por(lambda r: r["a"].get("credor") if r.get("mesmo_credor") else "—"),
        "por_orgao": por(lambda r: "×".join(sorted({_orgao(r["a"]["processo"]), _orgao(r["b"]["processo"])}))),
        "por_tipo": por(lambda r: "×".join(sorted({r["a"]["tipo"], r["b"]["tipo"]}))),
        "familias": len(fam),
        "familias_maiores": sorted(([len(v), sorted({p for p, _ in v})[:8]] for v in fam.values()),
                                   reverse=True)[:15],
        "familias_grandes_nao_pareadas": len(R.get("familias_grandes") or []),
    }
    if sem_filtro_json:
        S = json.loads(Path(sem_filtro_json).read_text(encoding="utf-8"))
        com = {_chave_par(r) for r in pares}
        sem = {_chave_par(r) for r in S["pares"]}
        out["sem_filtro_de_modelo"] = {"pares": len(sem), "so_existiam_pelo_modelo_institucional": len(sem - com),
                                       "pares_que_o_filtro_manteve": len(sem & com)}
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("exportar")
    e.add_argument("--base", default=str(BASE_ACERVO))
    e.add_argument("--saida", required=True)
    e.add_argument("--limite", type=int)
    e.add_argument("--credores", help="mapa processo→[cnpj, fonte] da etapa `credores`")
    c = sub.add_parser("credores")
    c.add_argument("--base", default=str(BASE_ACERVO))
    c.add_argument("--saida", required=True)
    c.add_argument("--lista")
    c.add_argument("--so-lista", action="store_true")
    p = sub.add_parser("parear")
    p.add_argument("--corpus", required=True)
    p.add_argument("--saida", required=True)
    p.add_argument("--processos", type=int, default=1)
    p.add_argument("--b-credores", type=int, default=B_CREDORES)
    z = sub.add_parser("resumir")
    z.add_argument("--pares", required=True)
    z.add_argument("--sem-filtro")
    a = ap.parse_args(argv)
    if a.cmd == "resumir":
        r = resumir(Path(a.pares), Path(a.sem_filtro) if a.sem_filtro else None)
    elif a.cmd == "credores":
        r = mapear_credores(Path(a.base), Path(a.saida), Path(a.lista) if a.lista else None, a.so_lista)
    elif a.cmd == "exportar":
        cred = json.loads(Path(a.credores).read_text(encoding="utf-8")) if a.credores else None
        r = exportar(Path(a.base), Path(a.saida), a.limite, cred)
    else:
        r = parear(Path(a.corpus), Path(a.saida), a.processos, a.b_credores)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
