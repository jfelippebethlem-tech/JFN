# -*- coding: utf-8 -*-
"""Leitura integral comprovada — piloto (docs/PLANO-PLATAFORMA-EVIDENCIAS.md, Fase 1).

Medido em 23/11/2026: a perícia integral alcança só 17,3% dos caracteres do acervo (teto 240k, 12k por peça).
Dono: "deveria ler tudo mesmo" — resumo por IA pode omitir, inventar ou falsear. Aqui:

  1. `fatiar`     100% do texto do processo em fatias (~40k caracteres ≈ 12k tokens: o recall dos modelos despenca
                  a partir de ~32k tokens — NoLiMa/ICML 2025, Chroma Context Rot 2025), na ordem da árvore, sem
                  cortar documento que cabe; documento maior é dividido por parágrafo com sobreposição.
  2. `mascarar`   CPF (11 dígitos, com ou sem pontuação — vazar é pior que sobrar) e conta bancária viram
                  marcadores ANTES de sair da VM; o mapa fica local e `desmascarar` reconstrói a citação.
  3. o modelo extrai FATOS com citação literal (prompt fixo `SISTEMA`, em cache).
  4. `verificar`  a citação tem de existir no documento citado (espaços normalizados) e o valor tem de estar DENTRO
                  da citação; senão o fato fica INDISPONÍVEL — nunca vira número.
  5. `projetar`   custo estimado (preço do lote, conservador) ANTES de enviar; o teto duro é o de `llm/claude_api`.

Uso:
    python -m compliance_agent.leitura_integral projetar [--limite N]         # só conta; não gasta
    python -m compliance_agent.leitura_integral piloto --processos arq.txt --enviar   # lote Haiku (teto da API)
    python -m compliance_agent.leitura_integral colher                         # colhe os lotes prontos e verifica
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from compliance_agent import evidencias as E
from compliance_agent.dominio.mascara import _RE_CONTA, _RE_CPF, desmascarar, mascarar  # noqa: F401 — reexportação

TAREFA = "leitura_integral"
VERSAO_PROMPT = "li-2"   # li-1 → li-2 (23/11): + atos/decisões — 36 de 75 achados do Opus eram atos não extraídos
ALVO_CHARS = 40_000
SOBREPOSICAO = 1_500

SISTEMA = """Você é um extrator de FATOS de autos de processo administrativo do Estado do Rio de Janeiro.
Leia TODO o trecho recebido. Para cada documento (bloco "=== DOC <doc_id> | <título> ==="), registre:

A) DADOS: valores em R$ (com o que representam), CNPJ, datas de atos, nota de empenho (NE), ordem bancária (OB),
   nota fiscal (NF), contrato, aditivo, quantidades medidas/entregues, objeto.
B) ATOS E DECISÕES: toda autorização, aprovação, determinação, homologação, ratificação, dispensa, prorrogação,
   repasse, pagamento autorizado, glosa, recusa ou devolução — QUEM decidiu (cargo/unidade) e O QUÊ.
C) FUNDAMENTOS: justificativas, motivações, conclusões de parecer jurídico/técnico/controle interno e as
   condições, ressalvas, pendências ou exigências que o próprio texto registre (inclusive "sem", "pendente",
   "vencido", "não consta", "em desacordo").

Regras absolutas:
- Cada fato traz "citacao": um trecho COPIADO LITERALMENTE do documento (até 300 caracteres) que sustenta o fato.
  Não parafraseie, não complete, não corrija. Se não houver trecho literal, NÃO registre o fato.
- "doc_id" é o do bloco de onde a citação foi copiada. "valor" só para dados (A); para atos e fundamentos, vazio.
- Não conclua, não julgue, não acrescente o que o texto não diz. Marcadores como [CPF_1] ou [CONTA_1] são
  copiados como estão. Ausência de algo no trecho não é fato.

Responda SÓ com JSON: {"fatos": [{"tipo": "...", "valor": "...", "descricao": "até 20 palavras",
"citacao": "...", "doc_id": "..."}]}. Tipos: valor, cnpj, data, ne, ob, nf, contrato, aditivo, quantidade, objeto,
ato, decisao, justificativa, parecer, condicao, ressalva, assinatura."""


# ── 1. fatiamento ─────────────────────────────────────────────────────────────────────────────────────
def portao(pasta: Path) -> tuple[bool, str]:
    """Porta do lote (dono, 23/11/2026: "só entra no lote o que sabemos ser 100% correto"): só processo com a
    captura DECLARADA completa, sem documento faltando e não vazia. Estado desconhecido não é completo (medido:
    8.834 de 12.707 passam; o resto vai para recaptura antes de ser lido)."""
    try:
        man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "manifesto ilegível"
    if man.get("captura_vazia"):
        return False, "captura vazia"
    if man.get("docs_faltantes"):
        return False, "documentos faltando na captura"
    if man.get("captura_completa") is not True:
        return False, "captura não declarada completa"
    docs = [d for d in man.get("docs") or [] if isinstance(d, dict)]
    # dono 23/11: "nos processos que temos certeza que o ocr, a extração, estão todos certos em tudo pra não ter que
    # gastar duas vezes" — qualquer pendência barra o PROCESSO inteiro, que é lido uma vez só quando estiver pronto
    if any(_eh_ocr(d) and (pasta.name, str(d.get("i"))) not in _ocr_confirmados() for d in docs):
        return False, "documento de OCR ainda não confirmado"
    if any(not d.get("texto") for d in docs):
        return False, "documento sem texto"
    return True, ""


_CONF: set | None = None


def _ocr_confirmados() -> set:
    """(tag, i) com OCR CONFIRMADO por leitura independente (`sei/ocr_confirmacao`, Fase 5) — esses entram como certos."""
    global _CONF
    if _CONF is None:
        from compliance_agent.sei import ocr_confirmacao
        _CONF = ocr_confirmacao.confirmados()
    return _CONF


def _ocr_ok(pasta: Path, d: dict) -> bool:
    """O documento de OCR está confirmado? O texto do estágio traz a decisão do E6 (`ocr_confirmado`, de
    `ocr_conferencia` para o mesmo texto — fatos.acervo_do_estagio); o do legado, o registro `sei/ocr_confirmacao`."""
    if "ocr_confirmado" in d:
        return d["ocr_confirmado"] is True
    return (pasta.name, d["i"]) in _ocr_confirmados()


def _eh_ocr(d: dict) -> bool:
    return bool(d.get("ocr") or d.get("ocr_motor"))


def _docs(pasta: Path) -> list[dict]:
    from compliance_agent.sei import acervo_texto
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    vistos: dict[str, int] = {}
    out = []
    for d in man.get("docs") or []:
        if not isinstance(d, dict) or not d.get("texto"):
            continue
        n = E.id_sei(d.get("titulo", ""))
        base = f"sei:{n}" if n else f"pos:{d.get('i')}"
        vistos[base] = vistos.get(base, 0) + 1
        texto = acervo_texto.ler(pasta, d).strip()
        if texto:
            out.append({"doc_id": base if vistos[base] == 1 else f"{base}#{vistos[base]}",
                        "titulo": str(d.get("titulo") or "").strip(), "texto": texto, "ocr": _eh_ocr(d),
                        "i": str(d.get("i")),
                        "sha": hashlib.sha256(texto.encode("utf-8")).hexdigest()})
    return out


def _partes(texto: str, alvo: int, sobreposicao: int) -> list[str]:
    """Divide por parágrafo; parágrafo maior que o alvo é cortado duro. Cada parte (menos a 1ª) começa com os
    últimos `sobreposicao` caracteres da anterior — o que cai na emenda aparece inteiro em uma das duas."""
    blocos, atual = [], ""
    for par in re.split(r"(\n\s*\n)", texto):
        while len(par) > alvo:
            if atual:
                blocos.append(atual)
                atual = ""
            blocos.append(par[:alvo])
            par = par[alvo:]
        if len(atual) + len(par) > alvo and atual:
            blocos.append(atual)
            atual = ""
        atual += par
    if atual:
        blocos.append(atual)
    return [b if k == 0 else blocos[k - 1][-sobreposicao:] + b for k, b in enumerate(blocos)]


def eh_tabela(texto: str) -> bool:
    """Planilha/tabela exportada: grande, muito dígito e linhas curtas (células). Medido 23/11/2026: os 119 maiores
    documentos do acervo (460 M caracteres) são planilhas — orçamento de obra de 23.633 páginas com 1,1 mi de linhas,
    tabela CMED pública de 7 M em cada processo que a anexa. Amostra de 400 processos: 14,5% do texto. A IA não lê
    1 milhão de células com confiança; o CÓDIGO lê todas (extrator de tabela, Fase 5) — cobertura 'por código'."""
    n = len(texto)
    if n <= 20_000:
        return False
    linhas = texto.splitlines() or [""]
    dig = sum(ch.isdigit() for ch in texto) / n
    curtas = sum(len(ln.strip()) < 25 for ln in linhas) / len(linhas)
    colunadas = sum(ln.count("|") >= 2 for ln in linhas) / len(linhas)     # "a | b | c" (amostra: '0 | #VALUE! | …')
    return dig > 0.25 and (curtas > 0.6 or colunadas > 0.6)


def fatiar(pasta: Path, alvo: int = ALVO_CHARS, sobreposicao: int = SOBREPOSICAO,
           ja_lidos: set[str] | None = None, tabelas_lidas: set[str] | None = None,
           docs: list[dict] | None = None) -> tuple[list[dict], dict]:
    """Só vai à IA o texto que sabemos certo e ainda não lido: texto NATIVO do PDF (OCR — por IA ou Tesseract, que
    errou 8% na bancada de 23/11 — espera a confirmação por página), fora de tabela, e cujo sha256 não foi lido
    antes (`ja_lidos`, mesma versão do prompt) nem aparece de novo no próprio processo. Tudo o que não vai fica
    DECLARADO na cobertura com o motivo; `fracao` conta só o que foi de fato lido (IA ou reaproveitado).
    `docs`: a lista que o chamador JÁ leu com `_docs(pasta)` (O8.5, leitura única: o E8 e o E11 liam cada documento
    duas vezes no mesmo job — uma para os originais, outra aqui). Sem ela, lê como antes."""
    fatias: list[dict] = []
    atual: list[dict] = []
    tam = 0
    vistos = set(ja_lidos or ())
    soma = {"tabela": 0, "tabela_lida": 0, "ocr_pendente": 0, "duplicado": 0, "enviados": 0}
    tabelas_lidas = tabelas_lidas or set()
    listas: dict[str, list[str]] = {"tabela": [], "ocr_pendente": [], "duplicados": []}
    existentes = 0

    def fecha():
        nonlocal atual, tam
        if atual:
            fatias.append({"id": len(fatias), "docs": atual,
                           "texto": "\n\n".join(f"=== DOC {d['doc_id']} | {d['titulo']} ===\n{d['texto']}" for d in atual)})
        atual, tam = [], 0

    for d in (docs if docs is not None else _docs(pasta)):
        n = len(d["texto"])
        existentes += n
        if d["sha"] in vistos:
            soma["duplicado"] += n
            listas["duplicados"].append(d["doc_id"])
            continue
        if d["ocr"] and not _ocr_ok(pasta, d):
            soma["ocr_pendente"] += n
            listas["ocr_pendente"].append(d["doc_id"])
            continue
        if eh_tabela(d["texto"]):
            if d["sha"] in tabelas_lidas:            # lida por CÓDIGO (ler_tabelas): 100% das linhas, citação literal
                soma["tabela_lida"] += n
                continue
            soma["tabela"] += n
            listas["tabela"].append(d["doc_id"])
            continue
        vistos.add(d["sha"])
        soma["enviados"] += n
        if n > alvo:
            fecha()
            partes = _partes(d["texto"], alvo, sobreposicao)
            for k, t in enumerate(partes, 1):
                atual = [dict(d, texto=t, titulo=f"{d['titulo']} [parte {k}/{len(partes)}]")]
                fecha()
            continue
        if tam + n > alvo:
            fecha()
        atual.append(d)
        tam += n
    fecha()
    lido = soma["enviados"] + soma["duplicado"] + soma["tabela_lida"]
    return fatias, {"chars_existentes": existentes, "chars_enviados": soma["enviados"], "chars_tabela": soma["tabela"],
                    "chars_tabela_lida": soma["tabela_lida"],
                    "chars_ocr_pendente": soma["ocr_pendente"], "chars_duplicado": soma["duplicado"],
                    "docs_tabela": listas["tabela"], "docs_ocr_pendente": listas["ocr_pendente"],
                    "docs_duplicados": listas["duplicados"],
                    "fracao": round(lido / existentes, 4) if existentes else 0.0,
                    "leitura": "sem_texto" if not existentes else ("integral" if lido == existentes else "parcial")}


# ── 1b. leitor de tabela por CÓDIGO ───────────────────────────────────────────────────────────────────
def _arq_tabela(sha: str) -> Path:
    return E.RAIZ / "data" / "leitura_integral" / "tabelas" / f"{sha}.jsonl.gz"


def ler_tabelas(con, pasta: Path) -> dict:
    """Lê 100% das linhas de cada tabela/planilha do processo (as que a IA não lê — `eh_tabela`): todo número
    crítico (valor, CNPJ, data, NE/OB/processo/contrato — `sei/ocr_ia_prova.extrair`) com a LINHA inteira como
    citação (literal por construção). Guarda por sha256 do conteúdo: tabela pública repetida em vários processos
    (ex.: CMED, 7 M caracteres) é lida uma vez só. Sem custo de API."""
    import gzip
    from compliance_agent.sei import ocr_ia_prova as P
    feitos = tabelas_lidas(con)
    r = {"tabelas": 0, "novas": 0, "linhas_com_numero": 0}
    for d in _docs(pasta):
        if d["ocr"] or not eh_tabela(d["texto"]):
            continue
        r["tabelas"] += 1
        if d["sha"] in feitos:
            continue
        linhas = []
        for k, ln in enumerate(d["texto"].splitlines(), 1):
            ns = P.extrair(ln)
            if ns:
                linhas.append({"linha": k, "citacao": ln.strip()[:500],
                               "numeros": [{"tipo": x["tipo"], "norma": x["norma"]} for x in ns]})
        arq = _arq_tabela(d["sha"])
        arq.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(arq, "wt", encoding="utf-8") as f:
            for x in linhas:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
        with con:
            con.execute("INSERT INTO tabelas_lidas(sha, processo, doc_id, linhas, linhas_com_numero, em) "
                        "VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                        (d["sha"], pasta.name, d["doc_id"], len(d["texto"].splitlines()), len(linhas), E._agora()))
        feitos.add(d["sha"])
        r["novas"] += 1
        r["linhas_com_numero"] += len(linhas)
    return r


def tabelas_lidas(con) -> set[str]:
    return {x[0] for x in con.execute("SELECT sha FROM tabelas_lidas")}


def linhas_da_tabela(sha: str) -> list[dict]:
    import gzip
    with gzip.open(_arq_tabela(sha), "rt", encoding="utf-8") as f:
        return [json.loads(x) for x in f]


# ── 2. máscara reversível ─────────────────────────────────────────────────────────────────────────────
# Centralizada em `dominio/mascara.py` (24/11/2026, O6.1: o gateway LLM usa a mesma); reexportada aqui com o
# comportamento idêntico (`mascarar(texto)` sem `estrito`); o import está no topo do módulo.


# ── 4. verificação literal ────────────────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


_MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro")


def _data_na_citacao(valor: str, cit: str) -> bool | None:
    """Data do valor (dd/mm/aaaa ou aaaa-mm-dd) presente na citação, com mês em número OU por extenso. None = o
    valor não é data reconhecível (cai na regra geral). Piloto 23/11: 220 datas por extenso recusadas por rigidez."""
    m = re.fullmatch(r"\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\s*", valor) or None
    if m:
        d, me, a = int(m[1]), int(m[2]), m[3]
    else:
        m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*", valor)
        if not m:
            return None
        a, me, d = m[1], int(m[2]), int(m[3])
    if not 1 <= me <= 12:
        return False
    c = cit.lower()
    num = re.search(rf"(?<!\d)0?{d}[/.-]0?{me}[/.-]{a}(?!\d)", c)
    ext = re.search(rf"(?<!\d)0?{d}º?\s+(de\s+)?{_MESES[me - 1]}\s+(de\s+)?{a}(?!\d)", c)
    return bool(num or ext)


def verificar(fato: dict, textos: dict[str, str], normalizados: dict[str, str] | None = None) -> dict:
    """VERIFICADO só se a citação existe no documento citado e o valor (dígitos, quando tem ≥ 3) está nela.
    `normalizados` = textos já com espaços normalizados (23/11: normalizar o documento inteiro A CADA fato deixava a
    colheita presa em CPU — centenas de fatos × documentos de centenas de KB)."""
    cit, doc = _norm(fato.get("citacao")), str(fato.get("doc_id") or "")
    motivo = ""
    if not cit:
        motivo = "sem citação"
    elif doc not in textos:
        motivo = f"documento {doc!r} não está na fatia"
    elif cit not in (normalizados[doc] if normalizados and doc in normalizados else _norm(textos[doc])):
        motivo = "citação não existe no documento"
    else:
        data = _data_na_citacao(str(fato.get("valor") or ""), cit) if fato.get("tipo") == "data" else None
        dig = re.sub(r"\D", "", str(fato.get("valor") or ""))
        if data is False or (data is None and len(dig) >= 3 and dig.lstrip("0") not in re.sub(r"\D", "", cit)):
            motivo = "valor não está dentro da citação"
    return dict(fato, estado="INDISPONIVEL" if motivo else "VERIFICADO", motivo=motivo or None)


def interpretar(resposta: str, textos: dict[str, str]) -> list[dict] | None:
    """Resposta do modelo → fatos verificados. JSON inválido → None (falha de leitura, NÃO "sem fatos")."""
    m = re.search(r"\{.*\}", resposta or "", re.S)
    try:
        dados = json.loads(m[0]) if m else None
    except ValueError:
        dados = None
    if not isinstance(dados, dict) or not isinstance(dados.get("fatos"), list):
        return None
    normalizados = {k: _norm(v) for k, v in textos.items()}            # uma vez por fatia, não por fato
    return [verificar(f, textos, normalizados) for f in dados["fatos"] if isinstance(f, dict)]


# ── 5. projeção de custo (antes de gastar) ────────────────────────────────────────────────────────────
# real ÷ projetado MEDIDO (23/11/2026): li-2 1,18; lote 3 1,50 (US$ 7,37 × 4,91 em 4.239 fatias). A estimativa de
# tokens de entrada (2,5 chars/token) fica abaixo do tokenizador real em português; o fator mantém a projeção honesta.
FATOR_REAL = 1.5


def projetar(fatias: list[dict], saida_tokens: int = 1500) -> dict:
    from compliance_agent.llm import claude_api as C
    tok = sum(C._tokens_aprox(f["texto"]) for f in fatias)
    usd = sum(C.estimativa(C.MODELO_BARATO, C._tokens_aprox(f["texto"]), saida_tokens, lote=True) for f in fatias)
    sem = sum(C.estimativa(C.MODELO_BARATO, C._tokens_aprox(f["texto"]), saida_tokens, lote=False) for f in fatias)
    return {"fatias": len(fatias), "tokens_entrada": tok, "usd": round(usd * FATOR_REAL, 6),
            "usd_sem_lote": round(sem * FATOR_REAL, 6)}


# ── persistência (data/evidencias.db) ─────────────────────────────────────────────────────────────────
_DDL = """
CREATE TABLE IF NOT EXISTS leituras(processo TEXT NOT NULL, estagio TEXT NOT NULL, versao TEXT NOT NULL,
  chars_existentes INTEGER, chars_enviados INTEGER, fracao REAL, leitura TEXT, fatias INTEGER, lote TEXT,
  em TEXT NOT NULL, PRIMARY KEY(processo, estagio, versao));
CREATE TABLE IF NOT EXISTS fatos(id INTEGER PRIMARY KEY, processo TEXT NOT NULL, doc_id TEXT NOT NULL, tipo TEXT,
  valor TEXT, descricao TEXT, citacao TEXT, estado TEXT NOT NULL, motivo TEXT, motor TEXT, versao TEXT,
  payload_sha TEXT, em TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_fatos_proc ON fatos(processo, estado);
CREATE INDEX IF NOT EXISTS ix_fatos_sha ON fatos(payload_sha);
CREATE TABLE IF NOT EXISTS tabelas_lidas(sha TEXT PRIMARY KEY, processo TEXT, doc_id TEXT, linhas INTEGER,
  linhas_com_numero INTEGER, em TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS docs_lidos(sha TEXT NOT NULL, versao TEXT NOT NULL, processo TEXT, doc_id TEXT, lote TEXT,
  em TEXT NOT NULL, PRIMARY KEY(sha, versao));
"""
# PostgreSQL (Fase 3): só os tipos mudam, como em `evidencias._DDL_PG`.
_DDL_PG = (_DDL.replace("id INTEGER PRIMARY KEY", "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
           .replace("fracao REAL", "fracao DOUBLE PRECISION"))
# INSERT OR REPLACE (só SQLite) → upsert portável (SQLite ≥ 3.24 e PostgreSQL): substitui as colunas não-chave
_UPSERT_LEITURA = ("INSERT INTO leituras VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(processo, estagio, versao) DO UPDATE "
                   "SET chars_existentes=excluded.chars_existentes, chars_enviados=excluded.chars_enviados, "
                   "fracao=excluded.fracao, leitura=excluded.leitura, fatias=excluded.fatias, lote=excluded.lote, "
                   "em=excluded.em")
_INS_DOC_LIDO = "INSERT INTO docs_lidos VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING"


def _comandos(ddl: str) -> list[str]:
    return [c.strip() for c in ddl.split(";") if c.strip()]


def _con():
    """PostgreSQL com `JFN_EVIDENCIAS_DSN` no ambiente; senão `data/evidencias.db` (como `evidencias.conectar`)."""
    con = E.conectar()
    with con:
        for c in _comandos(_DDL_PG if E._e_pg(con) else _DDL):
            con.execute(c)
    return con


def _pasta_do(processo: str) -> Path:
    return E.ARQUIVO / processo.replace("SEI-", "").replace("/", "_")


def _prompt(fatia: dict) -> tuple[str, dict]:
    return mascarar(fatia["texto"])


def aptos_por_valor(con) -> list[str]:
    """Processos que passam na porta e ainda não foram lidos nesta versão, por valor de OB no SIAFE (desc). Ordem só
    para priorizar — nenhum valor daqui vai a relatório."""
    import sqlite3
    from compliance_agent.ob_processo import chave_processo
    ja = {r[0] for r in con.execute("SELECT processo FROM leituras WHERE versao=?", (VERSAO_PROMPT,))}
    ok = [p.parent.name.replace("_", "/") for p in sorted(E.ARQUIVO.glob("*/manifest.json"))
          if p.parent.name.replace("_", "/") not in ja and portao(p.parent)[0]]
    val: dict[str, float] = {}
    try:
        from compliance_agent.cruzamentos_intel import _ob_paga
        db = sqlite3.connect(f"file:{E.RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=60)
        for proc, v in db.execute(f"SELECT processo, SUM(valor) FROM ob_orcamentaria_siafe WHERE {_ob_paga(db)} "
                                  "GROUP BY processo"):          # regra CNF-02: só OB paga, até para ordenar
            k = chave_processo(proc or "")
            if k:
                val[k] = val.get(k, 0.0) + (v or 0.0)
        db.close()
    except sqlite3.Error:
        pass
    return sorted(ok, key=lambda x: -val.get(chave_processo(x), 0.0))


def ler_pela_assinatura(con, procs: list[str], *, pensar=None, limite_fatias: int = 0) -> dict:
    """Braço da ASSINATURA da leitura integral (dono 23/11: "mistura" API com teto + assinatura; o balde da API fechou
    em US$ 35,15). Mesma porta, mesmo fatiador, mesma verificação literal. `backend="cli"`: nunca cai na API paga.
    Sem cota no meio do processo ⇒ PARA sem marcá-lo como lido (as fatias feitas ficam; a próxima rodada as refaz
    sem duplicar — `_gravar` apaga pelo sha do payload). Processo só vira 'lido' com TODAS as fatias de volta."""
    from compliance_agent.llm import claude_api as C
    if pensar is None:
        from compliance_agent.llm import claude_motor

        def pensar(tarefa, prompt, **kw):
            return claude_motor.pensar(tarefa, prompt, backend="cli", modelo=C.MODELO_BARATO, timeout=600, **kw)
    lidos = {r[0] for r in con.execute("SELECT sha FROM docs_lidos WHERE versao=?", (VERSAO_PROMPT,))}
    ja = {r[0] for r in con.execute("SELECT processo FROM leituras WHERE versao=?", (VERSAO_PROMPT,))}
    r = {"processos_lidos": 0, "fatias": 0, "parou_sem_cota": False}
    for proc in procs:
        if proc in ja:
            continue
        pasta = _pasta_do(proc)
        if not portao(pasta)[0]:
            continue
        ler_tabelas(con, pasta)
        fatias, cob = fatiar(pasta, ja_lidos=lidos, tabelas_lidas=tabelas_lidas(con))
        if cob["docs_tabela"]:
            continue
        n = {"VERIFICADO": 0, "A_CONFIRMAR_OCR": 0, "INDISPONIVEL": 0, "resposta_invalida": 0, "sem_resposta": 0}
        completo = True
        for f in fatias:
            texto, mapa = mascarar(f["texto"])
            resp = pensar(TAREFA, texto, sistema=SISTEMA)
            if resp is None:
                completo = False
                r["parou_sem_cota"] = True
                break
            info = {"processo": proc, "mapa": mapa, "docs": [d["doc_id"] for d in f["docs"]],
                    "sha": hashlib.sha256(texto.encode()).hexdigest()}
            with con:
                con.execute("DELETE FROM fatos WHERE payload_sha=?", (info["sha"],))
            _gravar(con, info, getattr(resp, "texto", None), n, f"{C.MODELO_BARATO}@assinatura")
            r["fatias"] += 1
            if limite_fatias and r["fatias"] >= limite_fatias:
                completo = completo and f is fatias[-1]
                break
        if not completo:
            break
        with con:
            con.execute(_UPSERT_LEITURA,
                        (proc, TAREFA, VERSAO_PROMPT, cob["chars_existentes"], cob["chars_enviados"], cob["fracao"],
                         cob["leitura"], len(fatias), "assinatura", E._agora()))
            con.executemany(_INS_DOC_LIDO,
                            [(d["sha"], VERSAO_PROMPT, proc, d["doc_id"], "assinatura", E._agora())
                             for f in fatias for d in f["docs"]])
        lidos |= {d["sha"] for f in fatias for d in f["docs"]}
        r["processos_lidos"] += 1
        if limite_fatias and r["fatias"] >= limite_fatias:
            break
    return r


def main(argv: list[str] | None = None) -> int:
    from compliance_agent.llm import claude_api as C
    ap = argparse.ArgumentParser(description="Leitura integral comprovada (piloto)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pj = sub.add_parser("projetar")
    pj.add_argument("--limite", type=int, default=0)
    pl = sub.add_parser("piloto")
    pl.add_argument("--processos", required=True, help="arquivo com um número de processo por linha")
    pl.add_argument("--enviar", action="store_true", help="sem isto, só projeta")
    sub.add_parser("colher")
    sub.add_parser("reverificar")
    asg = sub.add_parser("assinatura", help="lê pela assinatura (sem API paga) até a cota parar")
    asg.add_argument("--processos", default="", help="arquivo com processos; vazio = aptos por valor de OB")
    asg.add_argument("--limite-fatias", type=int, default=0)
    a = ap.parse_args(argv)

    if a.cmd == "projetar":
        pastas = sorted(p.parent for p in E.ARQUIVO.glob("*/manifest.json"))
        if a.limite:
            pastas = pastas[: a.limite]
        tot = {"processos": 0, "fatias": 0, "tokens_entrada": 0, "usd": 0.0}
        tot["fora_da_porta"] = 0
        for p in pastas:
            if not portao(p)[0]:
                tot["fora_da_porta"] += 1
                continue
            try:
                f, _ = fatiar(p)
            except (OSError, ValueError):
                continue
            r = projetar(f)
            tot["processos"] += 1
            for k in ("fatias", "tokens_entrada", "usd"):
                tot[k] += r[k]
        tot["usd"] = round(tot["usd"], 2)
        print(json.dumps(tot, ensure_ascii=False))
        return 0

    con = _con()
    if a.cmd == "assinatura":
        procs = ([ln.strip() for ln in Path(a.processos).read_text().splitlines() if ln.strip()] if a.processos
                 else aptos_por_valor(con))
        print(json.dumps(ler_pela_assinatura(con, procs, limite_fatias=a.limite_fatias), ensure_ascii=False))
        return 0
    if a.cmd == "piloto":
        procs = [ln.strip() for ln in Path(a.processos).read_text().splitlines() if ln.strip()]
        itens, mapas, resumo = [], {}, {"processos": 0, "fatias": 0, "usd": 0.0, "fora_da_porta": 0}
        lidos = {r[0] for r in con.execute("SELECT sha FROM docs_lidos WHERE versao=?", (VERSAO_PROMPT,))}
        coberturas: dict[str, tuple] = {}
        novos: list[tuple] = []
        aceitos: list[str] = []
        for proc in procs:
            pasta = _pasta_do(proc)
            ok, motivo = portao(pasta)
            if not ok:
                resumo["fora_da_porta"] += 1
                print(f"fora da porta: {proc} — {motivo}", file=sys.stderr)
                continue
            ler_tabelas(con, pasta)          # tabela: lida por CÓDIGO antes (sem custo); a IA lê o resto
            fatias, cob = fatiar(pasta, ja_lidos=lidos, tabelas_lidas=tabelas_lidas(con))
            if cob["docs_tabela"]:          # tabela que o código não conseguiu ler: o processo inteiro espera junto
                resumo["fora_da_porta"] += 1
                print(f"fora da porta: {proc} — tabela aguardando o leitor por código", file=sys.stderr)
                continue
            aceitos.append(proc)
            for f in fatias:
                for d in f["docs"]:
                    if d["sha"] not in lidos:
                        lidos.add(d["sha"])
                        novos.append((d["sha"], VERSAO_PROMPT, proc, d["doc_id"]))
            r = projetar(fatias)
            resumo["processos"] += 1
            resumo["fatias"] += r["fatias"]
            resumo["usd"] += r["usd"]
            for f in fatias:
                texto, mapa = _prompt(f)
                cid = hashlib.sha1(f"{proc}|{f['id']}".encode()).hexdigest()[:24]
                itens.append((cid, texto))
                mapas[cid] = {"processo": proc, "mapa": mapa, "docs": [d["doc_id"] for d in f["docs"]],
                              "sha": hashlib.sha256(texto.encode()).hexdigest()}
            coberturas[proc] = (cob, len(fatias))     # só vira registro de leitura se o lote for ENVIADO
        resumo["usd"] = round(resumo["usd"], 4)
        print(json.dumps(resumo, ensure_ascii=False))
        if not a.enviar:
            return 0
        lote = C.enviar_lote(TAREFA, itens, sistema=SISTEMA, modelo=C.MODELO_BARATO, max_tokens=8000)  # 4000 cortou 11% (piloto)
        if not lote:
            print(f"lote recusado: {C.ultimo_motivo}", file=sys.stderr)
            return 1
        guarda = E.RAIZ / "data" / "leitura_integral" / f"{lote}.mapas.json"   # mapa de CPF/conta: SÓ local
        guarda.parent.mkdir(parents=True, exist_ok=True)
        guarda.write_text(json.dumps(mapas, ensure_ascii=False), encoding="utf-8")
        with con:
            # 23/11: a projeção (sem --enviar) gravava o registro de leitura — o processo seria pulado sem ter sido lido
            con.executemany(_UPSERT_LEITURA,
                            [(p, TAREFA, VERSAO_PROMPT, c["chars_existentes"], c["chars_enviados"], c["fracao"],
                              c["leitura"], nf, lote, E._agora()) for p, (c, nf) in coberturas.items()])
            con.executemany(_INS_DOC_LIDO,
                            [(*n, lote, E._agora()) for n in novos])
        print(f"lote {lote}: {len(itens)} fatias")
        return 0

    # colher / reverificar
    pasta_li = E.RAIZ / "data" / "leitura_integral"
    alvos = sorted(pasta_li.glob("*.mapas.json")) if a.cmd == "colher" else sorted(pasta_li.glob("*.mapas.colhido"))
    for arq in alvos:
        lote = arq.name.split(".")[0]
        if a.cmd == "colher":
            saida = C.colher_lote(lote)
            if saida is None:
                print(f"{lote}: em curso")
                continue
        else:                          # reverificar: resultado guardado pela colheita, sem chamar a API de novo
            saida = json.loads((E.RAIZ / "data" / "claude_api_lotes" / f"{lote}.json").read_text(encoding="utf-8"))
        mapas = json.loads(arq.read_text(encoding="utf-8"))
        n = {"VERIFICADO": 0, "A_CONFIRMAR_OCR": 0, "INDISPONIVEL": 0, "resposta_invalida": 0, "sem_resposta": 0}
        for cid, info in mapas.items():
            with con:
                con.execute("DELETE FROM fatos WHERE payload_sha=?", (info["sha"],))
            _gravar(con, info, saida.get(cid), n, C.MODELO_BARATO)
        if a.cmd == "colher":
            arq.rename(arq.with_suffix(".colhido"))
        print(f"{lote}: {n}")
    return 0


_CACHE_DOCS: dict[str, list[dict]] = {}


def _docs_mascarados(processo: str) -> list[dict]:
    """Documentos do processo já mascarados, lidos UMA vez por colheita (23/11/2026: a colheita relia e remascarava
    o processo inteiro a cada fatia — 200 fatias = 200 leituras; o lote 4 estourou 58 min). Cache pequeno: só o
    processo corrente e o anterior (as fatias de um processo vêm juntas)."""
    if processo not in _CACHE_DOCS:
        if len(_CACHE_DOCS) >= 2:
            _CACHE_DOCS.pop(next(iter(_CACHE_DOCS)))
        _CACHE_DOCS[processo] = [dict(d, mascarado=mascarar(d["texto"])[0]) for d in _docs(_pasta_do(processo))]
    return _CACHE_DOCS[processo]


def _gravar(con, info: dict, resp: str | None, n: dict, motor: str) -> None:
    if resp is None:
        n["sem_resposta"] += 1
        return
    docs = [d for d in _docs_mascarados(info["processo"]) if d["doc_id"] in set(info["docs"])]
    textos = {d["doc_id"]: d["mascarado"] for d in docs}
    de_ocr = {d["doc_id"] for d in docs if d["ocr"]}
    fatos = interpretar(resp, textos)
    if fatos is None:
        n["resposta_invalida"] += 1
        return
    for f in fatos:     # citação existe, mas o TEXTO veio de OCR ainda não confirmado: não é certo
        if f["estado"] == "VERIFICADO" and f.get("doc_id") in de_ocr:
            f["estado"], f["motivo"] = "A_CONFIRMAR_OCR", "texto do documento veio de OCR não confirmado"
    with con:
        for f in fatos:
            n[f["estado"]] += 1
            con.execute("INSERT INTO fatos(processo, doc_id, tipo, valor, descricao, citacao, estado, motivo, motor, "
                        "versao, payload_sha, em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (info["processo"], f.get("doc_id"), f.get("tipo"),
                         desmascarar(str(f.get("valor") or ""), info["mapa"]), f.get("descricao"),
                         desmascarar(str(f.get("citacao") or ""), info["mapa"]), f["estado"], f.get("motivo"),
                         motor, VERSAO_PROMPT, info["sha"], E._agora()))

if __name__ == "__main__":
    sys.exit(main())
