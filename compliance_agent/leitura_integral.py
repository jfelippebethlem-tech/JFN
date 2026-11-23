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

TAREFA = "leitura_integral"
VERSAO_PROMPT = "li-1"
ALVO_CHARS = 40_000
SOBREPOSICAO = 1_500

SISTEMA = """Você é um extrator de FATOS de autos de processo administrativo do Estado do Rio de Janeiro.
Leia TODO o trecho recebido. Para cada documento (bloco "=== DOC <doc_id> | <título> ==="), extraia os fatos
objetivos que constarem do texto: valores em R$ (com o que representam), CNPJ, datas de atos, números de nota de
empenho (NE), ordem bancária (OB), nota fiscal (NF), contrato, aditivo, quantidades medidas/entregues, objeto,
quem atesta/assina e qualquer ressalva, glosa, divergência ou irregularidade que o PRÓPRIO texto afirme.

Regras absolutas:
- Cada fato traz "citacao": um trecho COPIADO LITERALMENTE do documento (até 300 caracteres), que contém o valor.
  Não parafraseie, não complete, não corrija. Se não houver trecho literal, NÃO registre o fato.
- "doc_id" é o do bloco de onde a citação foi copiada.
- Não conclua, não julgue, não resuma. Marcadores como [CPF_1] ou [CONTA_1] são copiados como estão.
- Ausência de algo no trecho não é fato.

Responda SÓ com JSON: {"fatos": [{"tipo": "...", "valor": "...", "descricao": "até 15 palavras",
"citacao": "...", "doc_id": "..."}]}. Tipos: valor, cnpj, data, ne, ob, nf, contrato, aditivo, quantidade, objeto,
assinatura, ressalva."""


# ── 1. fatiamento ─────────────────────────────────────────────────────────────────────────────────────
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
                        "titulo": str(d.get("titulo") or "").strip(), "texto": texto})
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
    return dig > 0.25 and curtas > 0.6


def fatiar(pasta: Path, alvo: int = ALVO_CHARS, sobreposicao: int = SOBREPOSICAO) -> tuple[list[dict], dict]:
    fatias: list[dict] = []
    atual: list[dict] = []
    tam = 0
    existentes = tabela = 0
    tabelas: list[str] = []

    def fecha():
        nonlocal atual, tam
        if atual:
            fatias.append({"id": len(fatias), "docs": atual,
                           "texto": "\n\n".join(f"=== DOC {d['doc_id']} | {d['titulo']} ===\n{d['texto']}" for d in atual)})
        atual, tam = [], 0

    for d in _docs(pasta):
        existentes += len(d["texto"])
        if eh_tabela(d["texto"]):
            tabela += len(d["texto"])
            tabelas.append(d["doc_id"])
            continue
        if len(d["texto"]) > alvo:
            fecha()
            partes = _partes(d["texto"], alvo, sobreposicao)
            for k, t in enumerate(partes, 1):
                atual = [dict(d, texto=t, titulo=f"{d['titulo']} [parte {k}/{len(partes)}]")]
                fecha()
            continue
        if tam + len(d["texto"]) > alvo:
            fecha()
        atual.append(d)
        tam += len(d["texto"])
    fecha()
    # cobertura pela CONSTRUÇÃO: todo documento com texto entrou na IA (inteiro ou em partes que o cobrem) ou foi
    # separado como tabela para o leitor por código — nada fica de fora sem estar declarado
    return fatias, {"chars_existentes": existentes, "chars_enviados": existentes - tabela, "chars_tabela": tabela,
                    "docs_tabela": tabelas, "fracao": 1.0 if existentes else 0.0,
                    "leitura": "integral" if existentes else "sem_texto"}


# ── 2. máscara reversível ─────────────────────────────────────────────────────────────────────────────
_RE_CPF = re.compile(r"(?<![\d./])\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?![\d/])")
_RE_CONTA = re.compile(r"(?i)\b(c/c|conta(?:\s+corrente)?|ag[êe]ncia|ag\.)(\s*(?:n[º°o.]*)?\s*:?\s*)(\d[\d.\-xX]{2,})")


def mascarar(texto: str) -> tuple[str, dict]:
    mapa: dict[str, str] = {}
    rev: dict[str, str] = {}

    def marca(tipo: str, original: str) -> str:
        if original not in rev:
            rev[original] = f"[{tipo}_{sum(1 for k in mapa if k.startswith('[' + tipo)) + 1}]"
            mapa[rev[original]] = original
        return rev[original]

    t = _RE_CPF.sub(lambda m: marca("CPF", m[0]), texto)
    t = _RE_CONTA.sub(lambda m: m[1] + m[2] + marca("CONTA", m[3]), t)
    return t, mapa


def desmascarar(texto: str, mapa: dict) -> str:
    for k, v in mapa.items():
        texto = texto.replace(k, v)
    return texto


# ── 4. verificação literal ────────────────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def verificar(fato: dict, textos: dict[str, str]) -> dict:
    """VERIFICADO só se a citação existe no documento citado e o valor (dígitos, quando tem ≥ 3) está nela."""
    cit, doc = _norm(fato.get("citacao")), str(fato.get("doc_id") or "")
    motivo = ""
    if not cit:
        motivo = "sem citação"
    elif doc not in textos:
        motivo = f"documento {doc!r} não está na fatia"
    elif cit not in _norm(textos[doc]):
        motivo = "citação não existe no documento"
    else:
        dig = re.sub(r"\D", "", str(fato.get("valor") or ""))
        if len(dig) >= 3 and dig.lstrip("0") not in re.sub(r"\D", "", cit):
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
    return [verificar(f, textos) for f in dados["fatos"] if isinstance(f, dict)]


# ── 5. projeção de custo (antes de gastar) ────────────────────────────────────────────────────────────
def projetar(fatias: list[dict], saida_tokens: int = 1500) -> dict:
    from compliance_agent.llm import claude_api as C
    tok = sum(C._tokens_aprox(f["texto"]) for f in fatias)
    usd = sum(C.estimativa(C.MODELO_BARATO, C._tokens_aprox(f["texto"]), saida_tokens, lote=True) for f in fatias)
    sem = sum(C.estimativa(C.MODELO_BARATO, C._tokens_aprox(f["texto"]), saida_tokens, lote=False) for f in fatias)
    return {"fatias": len(fatias), "tokens_entrada": tok, "usd": round(usd, 6), "usd_sem_lote": round(sem, 6)}


# ── persistência (data/evidencias.db) ─────────────────────────────────────────────────────────────────
_DDL = """
CREATE TABLE IF NOT EXISTS leituras(processo TEXT NOT NULL, estagio TEXT NOT NULL, versao TEXT NOT NULL,
  chars_existentes INTEGER, chars_enviados INTEGER, fracao REAL, leitura TEXT, fatias INTEGER, lote TEXT,
  em TEXT NOT NULL, PRIMARY KEY(processo, estagio, versao));
CREATE TABLE IF NOT EXISTS fatos(id INTEGER PRIMARY KEY, processo TEXT NOT NULL, doc_id TEXT NOT NULL, tipo TEXT,
  valor TEXT, descricao TEXT, citacao TEXT, estado TEXT NOT NULL, motivo TEXT, motor TEXT, versao TEXT,
  payload_sha TEXT, em TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_fatos_proc ON fatos(processo, estado);
"""


def _con():
    con = E.conectar()
    con.executescript(_DDL)
    return con


def _pasta_do(processo: str) -> Path:
    return E.ARQUIVO / processo.replace("SEI-", "").replace("/", "_")


def _prompt(fatia: dict) -> tuple[str, dict]:
    return mascarar(fatia["texto"])


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
    a = ap.parse_args(argv)

    if a.cmd == "projetar":
        pastas = sorted(p.parent for p in E.ARQUIVO.glob("*/manifest.json"))
        if a.limite:
            pastas = pastas[: a.limite]
        tot = {"processos": 0, "fatias": 0, "tokens_entrada": 0, "usd": 0.0}
        for p in pastas:
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
    if a.cmd == "piloto":
        procs = [ln.strip() for ln in Path(a.processos).read_text().splitlines() if ln.strip()]
        itens, mapas, resumo = [], {}, {"processos": 0, "fatias": 0, "usd": 0.0}
        for proc in procs:
            pasta = _pasta_do(proc)
            if not (pasta / "manifest.json").is_file():
                print(f"sem acervo: {proc}", file=sys.stderr)
                continue
            fatias, cob = fatiar(pasta)
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
            with con:
                con.execute("INSERT OR REPLACE INTO leituras VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (proc, TAREFA, VERSAO_PROMPT, cob["chars_existentes"], cob["chars_enviados"], cob["fracao"],
                             cob["leitura"], len(fatias), None, E._agora()))
        resumo["usd"] = round(resumo["usd"], 4)
        print(json.dumps(resumo, ensure_ascii=False))
        if not a.enviar:
            return 0
        lote = C.enviar_lote(TAREFA, itens, sistema=SISTEMA, modelo=C.MODELO_BARATO, max_tokens=4000)
        if not lote:
            print(f"lote recusado: {C.ultimo_motivo}", file=sys.stderr)
            return 1
        guarda = E.RAIZ / "data" / "leitura_integral" / f"{lote}.mapas.json"   # mapa de CPF/conta: SÓ local
        guarda.parent.mkdir(parents=True, exist_ok=True)
        guarda.write_text(json.dumps(mapas, ensure_ascii=False), encoding="utf-8")
        with con:
            con.executemany("UPDATE leituras SET lote=? WHERE processo=? AND estagio=? AND versao=?",
                            [(lote, p, TAREFA, VERSAO_PROMPT) for p in procs])
        print(f"lote {lote}: {len(itens)} fatias")
        return 0

    # colher
    for arq in sorted((E.RAIZ / "data" / "leitura_integral").glob("*.mapas.json")):
        lote = arq.name.split(".")[0]
        saida = C.colher_lote(lote)
        if saida is None:
            print(f"{lote}: em curso")
            continue
        mapas = json.loads(arq.read_text(encoding="utf-8"))
        n = {"VERIFICADO": 0, "INDISPONIVEL": 0, "resposta_invalida": 0, "sem_resposta": 0}
        for cid, info in mapas.items():
            resp = saida.get(cid)
            if resp is None:
                n["sem_resposta"] += 1
                continue
            pasta = _pasta_do(info["processo"])
            textos = {d["doc_id"]: mascarar(d["texto"])[0] for d in _docs(pasta) if d["doc_id"] in set(info["docs"])}
            fatos = interpretar(resp, textos)
            if fatos is None:
                n["resposta_invalida"] += 1
                continue
            with con:
                for f in fatos:
                    n[f["estado"]] += 1
                    con.execute("INSERT INTO fatos(processo, doc_id, tipo, valor, descricao, citacao, estado, motivo, "
                                "motor, versao, payload_sha, em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                (info["processo"], f.get("doc_id"), f.get("tipo"),
                                 desmascarar(str(f.get("valor") or ""), info["mapa"]), f.get("descricao"),
                                 desmascarar(str(f.get("citacao") or ""), info["mapa"]), f["estado"], f.get("motivo"),
                                 C.MODELO_BARATO, VERSAO_PROMPT, info["sha"], E._agora()))
        arq.rename(arq.with_suffix(".colhido"))
        print(f"{lote}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
