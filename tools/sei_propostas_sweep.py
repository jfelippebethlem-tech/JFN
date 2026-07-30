#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sweep do acervo SEI → `proposta_item`: os preços por fornecedor que estavam presos no texto.

POR QUE ESTE CAMINHO NÃO EXISTIA. `editais/coletor_propostas.backfill()` itera os certames de
`ata_documento` — que tem **33 linhas**. Por isso `proposta_item` tinha **77**. O motor de comparação
(J9, `sei/conluio_propostas`) estava ligado, testado e sem matéria-prima: o PNCP não publica proposta
de perdedor (ver `limites_de_fonte`), e a ata quase nunca é capturada. Mas o preço por fornecedor
está no acervo, em texto, desde sempre — 40.241 documentos que ninguém tinha varrido para isto.

O QUE O ACERVO REALMENTE TEM — medido antes de escrever uma linha de código:
    40.241 documentos de texto
     4.627 com 3+ valores em R$
     2.722 desses com pelo menos um CNPJ
       757 com tabela unitária (menciona "unitário" E quantidade/unidade)
        56 que são COTAÇÃO/pesquisa de preço/planilha comparativa **com 2 a 8 CNPJs**  ← o alvo

O corte de 2-8 CNPJs não é arbitrário: documentos com 100+ CNPJs existem e são **faturas** listando
clientes, não concorrentes. Filtrar só por "2+ CNPJs" traria 615 documentos, e os maiores seriam
faturas com 154 CNPJs — lixo que o LLM leria a peso de ouro.

⚠️ E O QUE O ACERVO **NÃO** TEM, dito antes que alguém se anime: este acervo é de EXECUÇÃO
(despacho, empenho, liquidação, medição), não de licitação. Não há propostas de licitantes
concorrentes num certame. O que há são **cotações de dispensa/pesquisa de preço** — três "orçamentos
concorrentes" para justificar uma contratação direta. Isso é MAIS interessante para esta casa, não
menos: orçamento de fachada em dispensa é o padrão dominante aqui, e é exatamente o que o J9 pega
(markup uniforme, preço idêntico, texto copiado). Mas o rótulo tem de ser honesto.

A FORMA DO DOCUMENTO — e uma tentativa minha que o dado derrubou. Supus blocos "RAZÃO SOCIAL /
CNPJ / tabela" e escrevi um partidor por bloco, para atribuir o preço ao fornecedor pela POSIÇÃO.
Falso: nestes documentos os CNPJs estão todos no CABEÇALHO e a tabela é uma MATRIZ COMPARATIVA —
uma linha por item, N preços em colunas paralelas, achatadas pela extração de PDF. O partidor
devolvia UM bloco (não há blocos) e o extrator genérico, feito para tabela de um fornecedor só,
devolvia [] com razão. Então o modelo recebe a lista de CNPJs e a tarefa explícita de casar preço
com fornecedor.

DUAS TRAVAS DE HONESTIDADE, porque atribuição errada num indício de conluio é pior que indício nenhum:
  1. o CNPJ devolvido tem de ser UM DOS QUE ESTÃO no documento — o modelo não inventa fornecedor;
  2. cada valor é conferido contra o TEXTO DE ORIGEM, nas duas grafias ('1.234,56' e '1234,56').
     Valor que não aparece literalmente NÃO ENTRA, e o descarte é contado no laudo. A regra da casa
     é "nunca inventar número"; num sweep com modelo livre isso não pode ficar na confiança.

MODELO: `nous stepfun:free`, por diretriz da casa (CLAUDE.md §LLM) — é a ÚNICA IA do sweep em volume.
Grátis e sem limite; cerebras e gemini ficam fora do volume.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.sei_propostas_sweep --laudo          # só mede o alvo
    PYTHONPATH=. .venv/bin/python -m tools.sei_propostas_sweep --rodar [--limite N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
_ACERVO = _REPO / "data" / "sei_arquivo"
_DB = _REPO / "data" / "compliance.db"

# ── seleção do alvo (as regras estão no docstring; aqui elas viram código) ───────────────────────
_RE_CNPJ = re.compile(r"\b(\d{2})[.\s]?(\d{3})[.\s]?(\d{3})[/\s]?(\d{4})[-\s]?(\d{2})\b")
_RE_VALOR = re.compile(r"R\$\s*[\d.]{1,12},\d{2}")
_RE_UNIT = re.compile(r"unit[áa]ri|pre[çc]o\s+unit|valor\s+unit", re.I)
_RE_QTD = re.compile(r"\bquant|\bqtd\b|\bunidade\b", re.I)
_RE_TIPO = re.compile(
    r"cota[çc][ãa]o|pesquisa.*pre[çc]|pre[çc]o.*pesquisa|mapa.*pre[çc]|quadro.*compar|"
    r"compar.*pre[çc]|proposta|or[çc]ament|planilha_de_custo|planilha_compar|banco_de_precos|"
    r"painel_de_precos", re.I)

MIN_FORNECEDORES, MAX_FORNECEDORES = 2, 8


def _cnpjs(texto: str) -> list[str]:
    """CNPJs plausíveis. Descarta 00000000000000 e afins — dígito repetido não identifica ninguém."""
    achados = {"".join(m) for m in _RE_CNPJ.findall(texto)}
    return sorted(c for c in achados if len(c) == 14 and len(set(c)) > 2)


def candidatos() -> list[dict]:
    """Documentos do acervo que comparam FORNECEDORES entre si. Determinístico e reexecutável."""
    out = []
    for t in sorted(_ACERVO.rglob("texto/*.txt")):
        if not _RE_TIPO.search(t.name):
            continue
        try:
            txt = t.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(txt) < 400 or len(_RE_VALOR.findall(txt)) < 3:
            continue
        if not (_RE_UNIT.search(txt) and _RE_QTD.search(txt)):
            continue
        cn = _cnpjs(txt)
        if not (MIN_FORNECEDORES <= len(cn) <= MAX_FORNECEDORES):
            continue
        out.append({"arquivo": t, "processo": t.parts[-3], "cnpjs": cn,
                    "valores": len(_RE_VALOR.findall(txt))})
    # Densidade de valores primeiro. Não é cosmético: documento com 250 valores é planilha itemizada
    # (onde o extrator rende); documento com 4 é orçamento de uma linha só, que devolve `[]` com
    # razão. Começar pelos densos faz o piloto medir o caminho que importa, e não o resíduo.
    out.sort(key=lambda x: -x["valores"])
    return out


# ── o motor de linguagem do sweep ────────────────────────────────────────────────────────────────
def _gerar_nous():
    """`gerar(prompt) -> str` no nous stepfun:free — a ÚNICA IA do sweep (CLAUDE.md §LLM).

    Síncrono por fora porque `extrator_precos.extrair_itens` espera um callable simples; por dentro
    usa httpx assíncrono com o mesmo tratamento de 502/503 do sweep de fichas (o nous é lento e
    oscila; "lento tá ok" enquanto a qualidade segura).
    """
    import httpx
    from tools.sei_ficha import STEPFUN, _nous_cred

    tok, base = _nous_cred()
    if not tok:
        raise SystemExit("sem credencial nous (NOUS_API_KEY ou auth.json) — rode `hermes` p/ re-auth")
    teto = int(os.environ.get("SWEEP_PROPOSTAS_MAX_TOKENS", "20000"))

    async def _post(prompt: str) -> str:
        async with httpx.AsyncClient(timeout=240) as c:
            for tentativa in range(3):
                r = await c.post(
                    f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"model": STEPFUN,
                          "messages": [{"role": "user", "content": prompt}],
                          "temperature": 0.1, "max_tokens": teto, "top_p": 0.9})
                # 520-527 = família Cloudflare (524 = "origin timed out"). O nous fica atrás de CF e
                # devolve 524 quando o modelo demora demais para o primeiro byte — medido no piloto,
                # 1 documento de 3 perdido por não estar nesta lista. Transitório, retenta.
                if r.status_code in (429, 500, 502, 503, 504) or 520 <= r.status_code <= 527:
                    await asyncio.sleep(3 * (tentativa + 1))
                    continue
                if r.status_code == 401:
                    raise RuntimeError("401 nous — token expirado (rode `hermes`)")
                r.raise_for_status()
                m = (r.json().get("choices") or [{}])[0].get("message", {}) or {}
                # modelo de RACIOCÍNIO: quando o teto corta o `content`, o JSON pode estar no
                # `reasoning`. Descartar isso seria jogar fora resposta já paga.
                return m.get("content") or m.get("reasoning") or ""
            return ""

    def gerar(prompt: str) -> str:
        return asyncio.run(_post(prompt))

    return gerar


# ── persistência ─────────────────────────────────────────────────────────────────────────────────
def _certame_do_processo(processo: str) -> str:
    """`080002_008019_2026` → `SEI-080002/008019/2026`. É a chave que o resto da casa usa."""
    m = re.match(r"^(\d+)_(\d+)_(\d{4})$", processo)
    return f"SEI-{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else processo


def _prompt_comparativo(texto: str, cnpjs: list[str]) -> str:
    """A forma REAL do documento — e por que o extrator genérico não servia.

    `sei/extrator_precos` foi feito para uma tabela de UM fornecedor. Os documentos deste acervo são
    MATRIZES COMPARATIVAS: um cabeçalho com N fornecedores e, para cada item, N preços em colunas
    paralelas. Extraído de PDF, isso vira um fluxo achatado onde o preço não fica ao lado do dono.
    Partir o texto por bloco de CNPJ (a primeira coisa que tentei) devolve UM bloco, porque os CNPJs
    estão todos no cabeçalho — não há blocos.
    Então o modelo recebe a lista de CNPJs e a tarefa explícita de casar preço com fornecedor.
    """
    return (
        "TAREFA: extrair a tabela comparativa de preços deste documento público.\n"
        "SAÍDA: SOMENTE JSON. Nada antes, nada depois, sem markdown, sem explicação, sem raciocínio.\n"
        f"Fornecedores deste documento (CNPJ): {json.dumps(cnpjs, ensure_ascii=False)}\n"
        'FORMATO: [{"item":1,"descricao":"...","quantidade":null,'
        '"precos":[{"cnpj":"00000000000000","valor_unitario":12.34,"valor_total":null}]}]\n'
        "REGRAS DURAS:\n"
        "- use SOMENTE números que aparecem LITERALMENTE no texto; não calcule, não estime, não some;\n"
        "- preço que você não consiga atribuir a um CNPJ específico: OMITA aquele preço;\n"
        "- se não houver tabela de itens com preço, responda exatamente [].\n\n"
        "TEXTO:\n" + texto[:12000])


def _valor_literal(v, texto: str) -> bool:
    """O número aparece no documento, em formato brasileiro? Guard contra número inventado.

    A regra da casa é "nunca inventar número", e num sweep em volume com modelo livre isso não pode
    ficar na confiança: cada valor é conferido contra o texto de origem, nas duas grafias
    ('1.234,56' e '1234,56'). Valor que não aparece **não entra** — e o descarte é contado, para o
    laudo mostrar quanto o modelo estava inventando.
    """
    if v is None:
        return False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    com_milhar = f"{f:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
    sem_milhar = f"{f:.2f}".replace(".", ",")
    return com_milhar in texto or sem_milhar in texto


def _extrair_comparativo(texto: str, cnpjs: list[str], gerar, tentativas: int = 3) -> list[dict]:
    """Chama o modelo com retry de PARSE. Devolve [] honesto quando não vier JSON utilizável.

    O `stepfun` é modelo de RACIOCÍNIO: às vezes gasta o teto de tokens pensando e o JSON nunca sai.
    Medido aqui: a mesma pergunta, no mesmo documento, devolveu 25 itens numa chamada e nada na
    seguinte. Sem retry, o sweep perderia documento bom por sorteio.
    """
    from compliance_agent.llm.json_resposta import parse_json_llm

    for tent in range(tentativas):
        try:
            dados = parse_json_llm(gerar(_prompt_comparativo(texto, cnpjs)))
        except (ValueError, TypeError) as exc:
            logger.debug("  tentativa %d: JSON inválido (%s)", tent + 1, str(exc)[:60])
            continue
        itens = [x for x in (dados or []) if isinstance(x, dict) and x.get("precos")]
        if itens:
            return itens
        if isinstance(dados, list) and not dados:
            return []          # `[]` explícito = "não há tabela"; é resposta, não falha
        logger.debug("  tentativa %d: resposta sem itens utilizáveis", tent + 1)
    return []


def processar(doc: dict, gerar, *, db: Path) -> dict:
    """Extrai e PERSISTE os itens de um documento. Devolve o laudo daquele documento."""
    from compliance_agent.editais.coletor_propostas import persistir_propostas
    from compliance_agent.editais.db import conectar

    texto = doc["arquivo"].read_text(encoding="utf-8", errors="replace")
    certame = _certame_do_processo(doc["processo"])
    linhas: list[dict] = []
    por_fornecedor: dict[str, int] = {}
    descartados = 0

    itens = _extrair_comparativo(texto, doc["cnpjs"], gerar)
    validos = set(doc["cnpjs"])
    for idx, it in enumerate(itens, start=1):
        try:
            num = int(it.get("item") or idx)
        except (TypeError, ValueError):
            num = idx
        desc = str(it.get("descricao") or "")[:200]
        for p in it.get("precos") or []:
            cnpj = "".join(c for c in str(p.get("cnpj") or "") if c.isdigit())
            # CNPJ tem de ser um dos que ESTÃO no documento — o modelo não inventa fornecedor
            if cnpj not in validos:
                descartados += 1
                continue
            vu = p.get("valor_unitario") if _valor_literal(p.get("valor_unitario"), texto) else None
            vt = p.get("valor_total") if _valor_literal(p.get("valor_total"), texto) else None
            if vu is None and vt is None:
                descartados += 1
                continue
            linhas.append({
                "item": num, "fornecedor_cnpj": cnpj, "fornecedor_nome": None,
                "valor_unitario": vu, "valor_total": vt, "marca": it.get("marca"),
                "fonte": "sei_precos",
                "trecho": f"{num} | {desc} | {vu if vu is not None else vt}",
            })
            por_fornecedor[cnpj] = por_fornecedor.get(cnpj, 0) + 1

    if not linhas:
        return {"processo": doc["processo"], "certame": certame, "linhas": 0, "fornecedores": 0,
                "descartados": descartados,
                "motivo": "sem tabela comparativa utilizável (ou nenhum valor conferiu com o texto)"}

    con = conectar(db)
    try:
        n = persistir_propostas(con, certame, linhas)
        con.commit()
    finally:
        con.close()
    return {"processo": doc["processo"], "certame": certame, "linhas": n,
            "fornecedores": len(por_fornecedor), "por_fornecedor": por_fornecedor,
            "descartados": descartados}


def laudo() -> dict:
    c = candidatos()
    return {"documentos_alvo": len(c), "processos": len({x["processo"] for x in c}),
            "cnpjs_por_doc": {str(k): sum(1 for x in c if len(x["cnpjs"]) == k)
                              for k in sorted({len(x["cnpjs"]) for x in c})},
            "amostra": [{"processo": x["processo"], "arquivo": x["arquivo"].name,
                         "fornecedores": len(x["cnpjs"]), "valores": x["valores"]}
                        for x in sorted(c, key=lambda y: -y["valores"])[:8]]}


def analisar(db: Path | str = _DB, *, minimo_itens: int = 3) -> dict:
    """Roda o J9 sobre o que o sweep persistiu. Sem isto, a tabela cheia não vira achado.

    ⚠️ POR QUE UM CAMINHO PRÓPRIO, e não o do certame. `varredura_certames_ctx._propostas` monta o
    contexto dos detectores a partir de `pncp_resultado` — chave de certame do PNCP. As linhas deste
    sweep têm chave de PROCESSO SEI. São espaços de nome diferentes: encher `proposta_item` sem este
    consumidor deixaria o J9 tão cego quanto antes, só que com a tabela cheia — que é pior, porque
    parece resolvido.

    E o objeto é outro: aqui não são propostas de licitantes num certame, são **cotações de dispensa**
    (os três orçamentos que justificam a contratação direta). O J9 serve igual — markup uniforme,
    preço idêntico e planilha derivada são as mesmas assinaturas —, mas o laudo tem de dizer o que é.

    O casamento de item é pelo NÚMERO, não pela descrição: `proposta_item` não guarda descrição, e
    numa matriz comparativa o item 3 é o mesmo item para todos os fornecedores, por construção.
    """
    from compliance_agent.sei import conluio_propostas as CP

    con = sqlite3.connect(f"file:{Path(db)}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT certame, fornecedor_cnpj, item, valor_unitario, valor_total "
            "FROM proposta_item WHERE fonte='sei_precos' ORDER BY certame, fornecedor_cnpj, item"
        ).fetchall()
    except sqlite3.OperationalError:
        return {"erro": "proposta_item ausente"}
    finally:
        con.close()

    por_certame: dict[str, dict[str, list[dict]]] = {}
    for certame, cnpj, item, vu, vt in rows:
        valor = vu if vu is not None else vt
        if valor is None:
            continue
        por_certame.setdefault(certame, {}).setdefault(cnpj, []).append(
            {"descricao": f"item {item}", "valor_unitario": float(valor)})

    achados, avaliados, sem_par = [], 0, 0
    for certame, fornecedores in sorted(por_certame.items()):
        uteis = {c: i for c, i in fornecedores.items() if len(i) >= minimo_itens}
        if len(uteis) < 2:
            sem_par += 1
            continue
        avaliados += 1
        r = CP.detectar([{"fornecedor": c, "cnpj": c, "itens": i} for c, i in uteis.items()])
        for ind in r["indicios"]:
            achados.append({"certame": certame, "fornecedores": len(uteis), **ind})
    return {"certames_com_dado": len(por_certame), "avaliados": avaliados,
            "sem_par_comparavel": sem_par, "indicios": len(achados), "achados": achados,
            "_nota": "COTAÇÕES de dispensa (não propostas de certame). Indício ≠ acusação."}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--laudo", action="store_true", help="só mede o alvo, não chama IA nem escreve")
    ap.add_argument("--analisar", action="store_true", help="roda o J9 sobre o que já foi persistido")
    ap.add_argument("--rodar", action="store_true")
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--db", default=str(_DB))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if a.analisar:
        print(json.dumps(analisar(a.db), ensure_ascii=False, indent=1, default=str))
        return 0
    if a.laudo or not a.rodar:
        print(json.dumps(laudo(), ensure_ascii=False, indent=1, default=str))
        return 0

    docs = candidatos()
    if a.limite:
        docs = docs[:a.limite]
    gerar = _gerar_nous()
    antes = _contar_linhas(a.db)
    laudos, total = [], 0
    for i, d in enumerate(docs, 1):
        logger.info("[%d/%d] %s / %s (%d fornecedores)", i, len(docs), d["processo"],
                    d["arquivo"].name[:48], len(d["cnpjs"]))
        try:
            r = processar(d, gerar, db=Path(a.db))
        except Exception as exc:  # noqa: BLE001 — um documento ruim não derruba o sweep inteiro
            logger.warning("  falhou: %s: %s", type(exc).__name__, str(exc)[:120])
            r = {"processo": d["processo"], "linhas": 0, "erro": str(exc)[:120]}
        laudos.append(r)
        total += r.get("linhas", 0)
    depois = _contar_linhas(a.db)
    print(json.dumps({"documentos": len(docs), "linhas_persistidas": total,
                      "proposta_item_antes": antes, "proposta_item_depois": depois,
                      "com_resultado": sum(1 for x in laudos if x.get("linhas")),
                      "detalhe": laudos}, ensure_ascii=False, indent=1))
    return 0


def _contar_linhas(db) -> int:
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM proposta_item").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return -1


if __name__ == "__main__":
    raise SystemExit(main())
