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
    return dig > 0.25 and curtas > 0.6


def fatiar(pasta: Path, alvo: int = ALVO_CHARS, sobreposicao: int = SOBREPOSICAO,
           ja_lidos: set[str] | None = None) -> tuple[list[dict], dict]:
    """Só vai à IA o texto que sabemos certo e ainda não lido: texto NATIVO do PDF (OCR — por IA ou Tesseract, que
    errou 8% na bancada de 23/11 — espera a confirmação por página), fora de tabela, e cujo sha256 não foi lido
    antes (`ja_lidos`, mesma versão do prompt) nem aparece de novo no próprio processo. Tudo o que não vai fica
    DECLARADO na cobertura com o motivo; `fracao` conta só o que foi de fato lido (IA ou reaproveitado)."""
    fatias: list[dict] = []
    atual: list[dict] = []
    tam = 0
    vistos = set(ja_lidos or ())
    soma = {"tabela": 0, "ocr_pendente": 0, "duplicado": 0, "enviados": 0}
    listas: dict[str, list[str]] = {"tabela": [], "ocr_pendente": [], "duplicados": []}
    existentes = 0

    def fecha():
        nonlocal atual, tam
        if atual:
            fatias.append({"id": len(fatias), "docs": atual,
                           "texto": "\n\n".join(f"=== DOC {d['doc_id']} | {d['titulo']} ===\n{d['texto']}" for d in atual)})
        atual, tam = [], 0

    for d in _docs(pasta):
        n = len(d["texto"])
        existentes += n
        if d["sha"] in vistos:
            soma["duplicado"] += n
            listas["duplicados"].append(d["doc_id"])
            continue
        if d["ocr"] and (pasta.name, d["i"]) not in _ocr_confirmados():
            soma["ocr_pendente"] += n
            listas["ocr_pendente"].append(d["doc_id"])
            continue
        if eh_tabela(d["texto"]):
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
    lido = soma["enviados"] + soma["duplicado"]
    return fatias, {"chars_existentes": existentes, "chars_enviados": soma["enviados"], "chars_tabela": soma["tabela"],
                    "chars_ocr_pendente": soma["ocr_pendente"], "chars_duplicado": soma["duplicado"],
                    "docs_tabela": listas["tabela"], "docs_ocr_pendente": listas["ocr_pendente"],
                    "docs_duplicados": listas["duplicados"],
                    "fracao": round(lido / existentes, 4) if existentes else 0.0,
                    "leitura": "sem_texto" if not existentes else ("integral" if lido == existentes else "parcial")}


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
CREATE TABLE IF NOT EXISTS docs_lidos(sha TEXT NOT NULL, versao TEXT NOT NULL, processo TEXT, doc_id TEXT, lote TEXT,
  em TEXT NOT NULL, PRIMARY KEY(sha, versao));
"""


def _con():
    con = E.conectar(E.DB)      # SQLite explícito até a migração (executescript não existe no adaptador do PostgreSQL)
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
    sub.add_parser("reverificar")
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
    if a.cmd == "piloto":
        procs = [ln.strip() for ln in Path(a.processos).read_text().splitlines() if ln.strip()]
        itens, mapas, resumo = [], {}, {"processos": 0, "fatias": 0, "usd": 0.0, "fora_da_porta": 0}
        lidos = {r[0] for r in con.execute("SELECT sha FROM docs_lidos WHERE versao=?", (VERSAO_PROMPT,))}
        novos: list[tuple] = []
        aceitos: list[str] = []
        for proc in procs:
            pasta = _pasta_do(proc)
            ok, motivo = portao(pasta)
            if not ok:
                resumo["fora_da_porta"] += 1
                print(f"fora da porta: {proc} — {motivo}", file=sys.stderr)
                continue
            fatias, cob = fatiar(pasta, ja_lidos=lidos)
            if cob["docs_tabela"]:          # tabela espera o leitor por código: o processo inteiro espera junto
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
            with con:
                con.execute("INSERT OR REPLACE INTO leituras VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (proc, TAREFA, VERSAO_PROMPT, cob["chars_existentes"], cob["chars_enviados"], cob["fracao"],
                             cob["leitura"], len(fatias), None, E._agora()))
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
            con.executemany("UPDATE leituras SET lote=? WHERE processo=? AND estagio=? AND versao=?",
                            [(lote, p, TAREFA, VERSAO_PROMPT) for p in aceitos])
            con.executemany("INSERT OR IGNORE INTO docs_lidos VALUES(?,?,?,?,?,?)",
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


def _gravar(con, info: dict, resp: str | None, n: dict, motor: str) -> None:
    if resp is None:
        n["sem_resposta"] += 1
        return
    pasta = _pasta_do(info["processo"])
    docs = [d for d in _docs(pasta) if d["doc_id"] in set(info["docs"])]
    textos = {d["doc_id"]: mascarar(d["texto"])[0] for d in docs}
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
