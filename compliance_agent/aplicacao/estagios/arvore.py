# -*- coding: utf-8 -*-
"""E2 `arvore` — a árvore viva do processo SEI e o `tree_hash` (plano mestre v2 §3.2 E2, §7 "guarda de convergência";
item O3.3). Absorve a ENTRADA do `sei_sweep`, do `sei_bombeiros_sweep` e dos sweeps noturnos: quem decide QUAL processo
lê é a fila única (`fila`, abaixo) e não a posição de nada.

Entrada: `arvore:<processo>` (payload `{processo, lente?}`). O navegador é injetável (`obter_navegador`); o real
(`NavegadorSEI`) REUSA o leitor canônico itkava de tools/sei_reader.py — `entrar` (sessão por elemento real, não por
URL), `_ler_cracked` (processo de outra unidade) e, sem ele, `abrir_processo` + `arvore_do_fonte` (pastas lazy-load
expandidas pelo loader nativo do SEI) — o MESMO caminho de enumeração de tools/sei_integra_completa.py.

PAGINAÇÃO ATÉ O FIM (lição "quais 40", memória sei-paginacao-processo-completo): `ler_arvore` pede página após
página até o navegador dizer que acabou; página que não traz documento novo três vezes seguidas ANTES do fim é
leitura nossa quebrada ⇒ erro (o job tenta de novo), nunca "a árvore é isso". O leitor real devolve a árvore inteira
numa página (o frame da árvore com todas as pastas expandidas); o fake dos testes pagina de 10 em 10.

Saída e efeito (PG, esquema `JFN_CAPTURA_ESQUEMA`, padrão `public` — ADR-001: identidade no PG):
  · `arvore_leitura` (uma linha por leitura, idempotente pela posse do job), `arvores` (identidade do hash),
    `documentos` (título, posição, id_documento, restrito) e `processos`;
  · ids pela função única `dominio.documento_id.ids_documentos`; hash = `evidencias.hash_arvore` dos ids sem `#k`
    (a MESMA conta da carga dos manifestos, O3.1);
  · GUARDA DE CONVERGÊNCIA: hash igual ao da leitura anterior E nenhum documento sem versão ⇒ `sem_mudanca` e fim
    (nenhum evento). Hash igual com documento ainda sem versão (E3 anterior parou no meio) ⇒ `documento_novo` de novo:
    convergir é ficar sem falta, não só ver o mesmo hash. Restrito não conta como falta (fica declarado).
  · `documento_novo` ⇒ evento `arvore/documento_novo` (suja o E3 do processo); relacionados ⇒ `sei_relacionado/citado`.
Efeito conferido (outro processo): a linha desta posse existe, o hash recalculado dos ids GRAVADOS = o declarado, o nº
de documentos confere, e as faltas recontadas no PG = as declaradas.

FILA ÚNICA (`fila`): o universo de processos (OB do SIAFE, OB do espelho TFE só como fonte de nº, contratos e compras
diretas do TCE-RJ, citações do acervo, identidade do PG e o estado legado do sei_sweep), filtrado pela lente e na ordem
`fluxo.prioridade` com os sinais do `tools/sei_sweep` (manual, direta ≥ R$ 1 mi, lacuna, OSINT, folha, legível) e a
cota Couto; valor = OB PAGA do SIAFE, nunca empenho nem TFE.

CLI:
    python -m compliance_agent.aplicacao.estagios.arvore schema aplicar [--esquema X]
    python -m compliance_agent.aplicacao.estagios.arvore ler --processo 270006/000236/2026      # navegador real
    python -m compliance_agent.aplicacao.estagios.arvore fila [--lente bombeiros] [--limite 20] [--fonte <db só-leitura>]
    python -m compliance_agent.aplicacao.estagios.arvore paridade --lente bombeiros [--saida rel.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from compliance_agent import evidencias as EV
from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio, ForaDeAlcance
from compliance_agent.dominio import documento_id as DI
from compliance_agent.dominio import processo_id as PI
from compliance_agent.fluxo.fila import Resultado
from compliance_agent.fluxo import fonte_coleta

VERSAO = "e2-1"
ESQUEMA_PADRAO = "public"
ENV_ESQUEMA = "JFN_CAPTURA_ESQUEMA"
RAIZ = Path(__file__).resolve().parents[3]
SQL_EVIDENCIAS = RAIZ / "deploy" / "vm2" / "postgres" / "evidencias_001.sql"
SQL_CAPTURA = RAIZ / "deploy" / "vm2" / "postgres" / "captura_001.sql"
SQL_CAPTURA_002 = RAIZ / "deploy" / "vm2" / "postgres" / "captura_002.sql"   # versão com a identidade capturada
FONTE_PARADA = Path.home() / "snapshot-20261124" / "compliance.db"
ENV_FONTE = "JFN_CAPTURA_FONTE"
MAX_PAGINAS = 500
CONTROLE_POSITIVO = "080002/002886/2024"   # legível (68 docs, 01/08/2026); troca por SEI_CONTROLE_POSITIVO
PAGINAS_SEM_NOVO = 3
SEM_MUDANCA, SEM_DOC_NOVO, DOC_NOVO = "sem_mudanca", "sem_documento_novo", "documento_novo"
_RX_ID_DOC = re.compile(r"id_documento=(\d+)")


# ══ 1. PostgreSQL ═══════════════════════════════════════════════════════════════════════════════════════════════
def esquema_vigente(esquema: str | None = None) -> str:
    from compliance_agent.fluxo.schema import validar_esquema
    return validar_esquema(esquema or os.environ.get(ENV_ESQUEMA) or ESQUEMA_PADRAO)


def conectar(dsn: str | None = None, esquema: str | None = None):
    import psycopg
    dsn = dsn or EV.dsn_vigente()
    if not dsn:
        raise RuntimeError("sem DSN do PostgreSQL (JFN_EVIDENCIAS_DSN)")
    con = psycopg.connect(dsn, autocommit=True)
    con.execute(f'SET search_path TO "{esquema_vigente(esquema)}"')
    return con


def aplicar_schema(dsn: str, esquema: str | None = None) -> None:
    """Esquema + tabelas do evidencias.py + evidencias_001 (aquisicao) + captura_001/002 — idempotente."""
    import psycopg

    from compliance_agent.fluxo.schema import renderizar
    esq = esquema_vigente(esquema)
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(f'CREATE SCHEMA IF NOT EXISTS "{esq}"')
    EV.conectar(dsn + ("&" if "?" in dsn else "?") + f"options=-csearch_path%3D{esq}").close()
    with psycopg.connect(dsn, autocommit=True) as c:
        for arq in (SQL_EVIDENCIAS, SQL_CAPTURA, SQL_CAPTURA_002):
            c.execute(renderizar(arq.read_text(encoding="utf-8"), esq))


# binário do E3 cuja extração MAIS RECENTE do E4 (`texto_nativo`) deu perfil `invalida` (página de WAF/menu no lugar
# do documento): não é captura (revisão de falhas caladas 1.8) — o documento volta a faltar
_INVALIDA = ("COALESCE(v.hash_de, '') = 'binario' AND (SELECT t.parametros->>'perfil' FROM transformacao t WHERE "
             "t.processo = v.processo AND t.doc_id = v.doc_id AND t.tipo = 'texto_nativo' AND t.entrada_sha = v.sha256 "
             "ORDER BY t.criada_em DESC, t.id DESC LIMIT 1) = 'invalida'")


def capturados(con, processo: str) -> set[str]:
    """doc_id que já têm alguma versão VÁLIDA (texto do legado ou binário do E3 que o E4 não declarou inválido)."""
    return {r[0] for r in con.execute(f"SELECT DISTINCT v.doc_id FROM versoes v WHERE v.processo = %s AND NOT "
                                      f"COALESCE(({_INVALIDA}), false)", (processo,))}


def versoes_invalidas(con, processo: str) -> list[tuple[str, str, str]]:
    """(doc_id, sha256, id_documento capturado) dos binários que o E4 declarou inválidos."""
    return [(k, sh, str(i or "")) for k, sh, i in con.execute(
        f"SELECT v.doc_id, v.sha256, v.id_documento FROM versoes v WHERE v.processo = %s AND ({_INVALIDA})",
        (processo,))]


def identidade_capturada(con, processo: str) -> dict[str, set[tuple[str, str]]]:
    """doc_id → {(id_documento, título)} com que cada versão do E3 foi capturada (captura_002). O legado O3.1 não a
    tem (nulo) e fica fora: sem identidade capturada não há o que comparar. Conjunto (e não "a mais recente"):
    `vista_em` tem resolução de segundo e duas capturas no mesmo segundo empatariam."""
    out: dict[str, set[tuple[str, str]]] = {}
    for k, i, t in con.execute("SELECT v.doc_id, v.id_documento, v.titulo FROM versoes v WHERE v.processo = %s AND "
                               "(v.id_documento IS NOT NULL OR v.titulo IS NOT NULL) AND NOT "
                               f"COALESCE(({_INVALIDA}), false)", (processo,)):     # inválido não é captura
        out.setdefault(k, set()).add((str(i or ""), str(t or "")))
    return out


def _norm(t) -> str:
    return " ".join(str(t or "").split())


def casa_identidade(idd: str, titulo: str, cap: set[tuple[str, str]]) -> bool:
    """A identidade viva (id_documento, título) é a de alguma versão capturada? Lado vazio não discorda."""
    return any((not ci or not idd or ci == idd) and (not ct or not _norm(titulo) or _norm(ct) == _norm(titulo))
               for ci, ct in cap)


def retificados(ids: list[str], docs: list[dict], ident: dict[str, set[tuple[str, str]]]) -> list[str]:
    """doc_id com versão capturada, mas nenhuma com a identidade VIVA: id_documento trocado sob o mesmo nº
    (numeração reaproveitada) ou título retificado. `docs` = nós da árvore ({t, u}) ou linhas gravadas
    ({titulo, id_documento})."""
    return [k for k, d in zip(ids, docs) if ident.get(k)
            and not casa_identidade(id_documento(d), d.get("titulo", d.get("t", "")), ident[k])]


def leitura_anterior(con, processo: str, antes_de: int | None = None) -> str | None:
    """tree_hash da leitura vigente (a de maior id, ou a de maior id < `antes_de`); sem leitura, None."""
    sql = "SELECT tree_hash FROM arvore_leitura WHERE processo = %s" + (" AND id < %s" if antes_de else "")
    r = con.execute(sql + " ORDER BY id DESC LIMIT 1", (processo, antes_de) if antes_de else (processo,)).fetchone()
    return r[0] if r else None


def hashes_legado(con, processo: str) -> set[str]:
    return {r[0] for r in con.execute("SELECT hash FROM arvores WHERE processo = %s", (processo,))}


# ══ 2. navegador (injetável) ════════════════════════════════════════════════════════════════════════════════════
@dataclass
class PaginaArvore:
    docs: list[dict]                               # [{t, u, restrito}]
    proxima: int | None = None                     # None = acabou
    via: str = ""
    relacionados: list[str] = field(default_factory=list)
    sem_resultado: bool = False                    # "Nenhum resultado" do SEI (resposta definitiva da pesquisa)
    restrito: str | None = None                    # aviso do SEI de processo restrito à unidade
    controle_positivo: bool | None = None          # "Nenhum resultado": o controle na MESMA sessão abriu? None = não
    #                                                rodou


class Navegador(Protocol):
    def arvore(self, processo: str, pagina: int) -> PaginaArvore: ...

    def capturar(self, processo: str, guardados: dict, raiz: Path) -> Path: ...


def id_documento(d: dict) -> str:
    m = _RX_ID_DOC.search(str(d.get("u") or d.get("url") or ""))
    return m.group(1) if m else str(d.get("id_documento") or "")


class NavegadorSEI:
    """O navegador real: leitor canônico itkava (tools/sei_reader.py) para a árvore; tools/sei_integra_completa.py
    (subprocesso, delta ligado) para a captura. Um navegador por vez (`recursos.browser_lock_async`)."""

    def arvore(self, processo: str, pagina: int) -> PaginaArvore:
        if pagina:
            raise ValueError("o leitor real devolve a árvore inteira na página 0")
        return asyncio.run(self._arvore(processo))

    async def _arvore(self, processo: str) -> PaginaArvore:
        from playwright.async_api import Error as PWError
        from playwright.async_api import async_playwright

        from compliance_agent.recursos import browser_lock_async
        from tools import sei_reader as SR
        from tools import vm_guard as G
        async with browser_lock_async(espera_max=1800), async_playwright() as pw:
            b, ctx, fixo = await SR.navegador_sei(
                pw, args=G.guarded_launch_args(os.environ.get("SEI_CHROMIUM_ARGS", "").split() or None))
            pg = await ctx.new_page()
            await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            try:
                if not await SR.entrar(pg, fixo=fixo, tentativas=25):
                    raise RuntimeError(f"login no SEI falhou — {SR.ULTIMA_FALHA_LOGIN or 'sem motivo registrado'}")
                dump: dict = {}
                try:
                    dump = await SR._ler_cracked(pg, processo)
                except (PWError, asyncio.TimeoutError) as e:
                    dump = {"erro_cracked": f"{type(e).__name__}: {str(e)[:80]}"}
                arv, via = dump.get("documentos") or [], "cracked"
                # "Nenhum resultado" do cracked NÃO dispensa o caminho normal (revisão de falhas caladas 1.7): o
                # abrir_processo já encurta a pesquisa repetida e cai na pesquisa rápida
                if not arv and await SR.abrir_processo(pg, processo):
                    arv, via = await SR.arvore_do_fonte(pg), "fallback/arvore_do_fonte"
                aviso, controle = None, None
                if not arv:
                    try:
                        aviso = SR.aviso_restrito(await pg.evaluate("()=>document.body?document.body.innerText:''"))
                    except PWError:
                        aviso = None
                if not arv and dump.get("sem_resultado") and not aviso:
                    controle = await self._controle_positivo(SR, pg)
                rel = sorted({k for r in dump.get("relacionados") or []
                              for k in [PI.chave_processo(r.get("texto") or r.get("titulo") or "")] if k})
                docs = [{"t": d.get("titulo") or d.get("texto") or "", "u": d.get("url") or "",
                         "restrito": bool(d.get("restrito"))} for d in arv if d.get("url")]
                return PaginaArvore(docs=docs, via=via if docs else (dump.get("erro_cracked") or via),
                                    relacionados=[k for k in rel if k != processo],
                                    sem_resultado=bool(dump.get("sem_resultado")), restrito=aviso,
                                    controle_positivo=controle)
            finally:
                await SR.fechar_sei(b, pg, fixo=fixo)

    @staticmethod
    async def _controle_positivo(SR, pg) -> bool:
        """CONTROLE POSITIVO na MESMA sessão (lição sei-invisivel-pesquisa-controle-positivo): o MESMO método num
        processo sabidamente legível (`SEI_CONTROLE_POSITIVO`). Só com ele "Nenhum resultado" é resposta do SEI;
        sem ele, 0 é ambíguo (sessão morta, método quebrado). Falha do controle = False (não houve prova)."""
        from playwright.async_api import Error as PWError
        alvo = PI.chave_processo(os.environ.get("SEI_CONTROLE_POSITIVO", CONTROLE_POSITIVO)) or CONTROLE_POSITIVO
        try:
            return bool((await SR._ler_cracked(pg, alvo)).get("documentos"))
        except (PWError, asyncio.TimeoutError) as e:
            print(f"controle positivo {alvo} falhou ({type(e).__name__}) — 'Nenhum resultado' fica sem prova",
                  file=sys.stderr, flush=True)
            return False

    def capturar(self, processo: str, guardados: dict, raiz: Path) -> Path:
        """tools/sei_integra_completa.py, sem PDF único nem Telegram, com o delta da chave `JFN_E3_DELTA`
        (`captura_delta.modo_e3`: padrão "sombra" = baixa tudo e registra o plano; `=1` só baixa o que não está
        guardado — ligado na religação O9.0). Os guardados vão no arquivo que o encaixe do delta lê
        (`captura_delta.GUARDADOS_DIR`)."""
        import subprocess

        from compliance_agent.captura_delta import GUARDADOS_DIR, modo_e3
        pasta = PI.pasta(processo)
        GUARDADOS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = GUARDADOS_DIR / f"{pasta}.json.tmp"
        tmp.write_text(json.dumps(guardados, ensure_ascii=False), encoding="utf-8")
        tmp.replace(GUARDADOS_DIR / f"{pasta}.json")
        env = {**os.environ, "JFN_CAPTURA_DELTA": modo_e3(), "SEI_SEM_PDF_UNICO": "1", "SEI_SEM_TG": "1",
               "SEI_INTEGRA_RAIZ": str(raiz), "PYTHONPATH": str(RAIZ)}
        t = int(os.environ.get("JFN_CAPTURA_TIMEOUT_S", "3300"))
        p = subprocess.run([sys.executable, str(RAIZ / "tools" / "sei_integra_completa.py"), processo], cwd=RAIZ,
                           env=env, capture_output=True, text=True, timeout=t)
        cauda = (p.stdout or "")[-1500:] + (p.stderr or "")[-500:]
        if p.returncode != 0:
            raise RuntimeError(f"sei_integra_completa rc={p.returncode} (3 login, 4 sem árvore, 75 adiado): "
                               f"{cauda[-400:]}")
        (raiz / f"integra_{pasta}" / "e3_saida.log").write_text(cauda, encoding="utf-8")
        return raiz / f"integra_{pasta}"


def obter_navegador() -> Navegador:
    """Ponto de injeção (os testes trocam por um fake)."""
    return NavegadorSEI()


# ══ 3. leitura e gravação ═══════════════════════════════════════════════════════════════════════════════════════
def ler_arvore(nav: Navegador, processo: str, max_paginas: int = MAX_PAGINAS) -> dict:
    """Pede páginas até o fim. Dedup por id_documento (senão url+título). Página sem documento novo antes do fim,
    `PAGINAS_SEM_NOVO` vezes seguidas, ou mais de `max_paginas` ⇒ RuntimeError (a leitura não chegou ao fim)."""
    docs: list[dict] = []
    vistos: set[str] = set()
    rel: set[str] = set()
    pagina, paginas, sem_novo, via = 0, 0, 0, ""
    primeira: PaginaArvore | None = None
    while True:
        pg = nav.arvore(processo, pagina)
        paginas += 1
        primeira = primeira or pg
        via = via or pg.via
        rel.update(pg.relacionados)
        novos = 0
        for d in pg.docs:
            k = id_documento(d) or f"{d.get('u')}|{d.get('t')}"
            if k not in vistos:
                vistos.add(k)
                docs.append(d)
                novos += 1
        if pg.proxima is None:
            break
        sem_novo = 0 if novos else sem_novo + 1
        if sem_novo >= PAGINAS_SEM_NOVO:
            raise RuntimeError(f"paginação de {processo} parou de trazer documento na página {pagina} sem chegar "
                               f"ao fim ({len(docs)} até aqui) — leitura incompleta, não gravo")
        if paginas >= max_paginas:
            raise RuntimeError(f"{processo}: mais de {max_paginas} páginas na árvore — leitura interrompida")
        pagina = pg.proxima
    return {"docs": docs, "paginas": paginas, "via": via, "relacionados": sorted(rel - {processo}),
            "sem_resultado": bool(primeira and primeira.sem_resultado and not docs),
            "restrito": primeira.restrito if primeira and not docs else None,
            "controle_positivo": primeira.controle_positivo if primeira and not docs else None}


def hash_ids(ids: list[str]) -> str:
    """O hash da carga dos manifestos (O3.1, `arvores` do legado): só os doc_id, sem o `#k`."""
    return EV.hash_arvore([DI.sem_repeticao(x) for x in ids])


def tree_hash(ids: list[str], idds: list[str]) -> str:
    """tree_hash do E2 (O3.5): doc_id sem o `#k` E o id_documento (`sei:N@idd`) — trocar o documento sob o mesmo nº
    muda o hash. Sem id_documento o elemento é o doc_id puro."""
    return EV.hash_arvore([f"{DI.sem_repeticao(k)}@{i}" if i else DI.sem_repeticao(k) for k, i in zip(ids, idds)])


def identidade(docs: list[dict]) -> tuple[list[str], str]:
    """ids pela função única do domínio (posição = ordem da árvore) e o tree_hash (doc_id sem o `#k` + id_documento)."""
    ids = DI.ids_documentos([{"titulo": d.get("t", d.get("titulo", "")), "i": i} for i, d in enumerate(docs)])
    return ids, tree_hash(ids, [id_documento(d) for d in docs])


def faltantes(ids: list[str], docs: list[dict], tem: set[str],
              ident: dict[str, set[tuple[str, str]]] | None = None) -> list[str]:
    """Sem versão, ou com versão de OUTRA identidade (`retificados`), e não restrito."""
    ret = set(retificados(ids, docs, ident or {}))
    return [k for k, d in zip(ids, docs) if (k not in tem or k in ret) and not d.get("restrito")]


_INS_LEIT = ("INSERT INTO arvore_leitura(processo, tree_hash, n_docs, ids, docs, relacionados, via, paginas, no, lente, "
             "job_chave, ficha) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (job_chave, ficha) DO NOTHING")
_INS_DOC = ("INSERT INTO documentos(processo, doc_id, posicao, titulo, visto_em, id_documento, restrito) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (processo, doc_id) DO UPDATE SET posicao = excluded.posicao, "
            "titulo = excluded.titulo, id_documento = excluded.id_documento, restrito = excluded.restrito "
            "WHERE (documentos.posicao, documentos.titulo, documentos.id_documento, documentos.restrito) IS DISTINCT "
            "FROM (excluded.posicao, excluded.titulo, excluded.id_documento, excluded.restrito)")


def registrar(con, processo: str, lido: dict, ctx: Contexto, lente: list[str]) -> dict:
    """Grava a leitura e decide (guarda de convergência). Devolve o efeito declarado."""
    docs = lido["docs"]
    ids, h = identidade(docs)
    anterior = leitura_anterior(con, processo)
    igual = (h == anterior) if anterior is not None else (hash_ids(ids) in hashes_legado(con, processo))
    falta = faltantes(ids, docs, capturados(con, processo), identidade_capturada(con, processo))
    estado = DOC_NOVO if falta else (SEM_MUDANCA if igual else SEM_DOC_NOVO)
    em = time.strftime("%Y-%m-%d %H:%M:%S")
    linhas = [{"doc_id": k, "i": i, "titulo": d.get("t", ""), "id_documento": id_documento(d),
               "restrito": bool(d.get("restrito"))} for i, (k, d) in enumerate(zip(ids, docs))]
    with con.transaction():
        con.execute(_INS_LEIT, (processo, h, len(ids), json.dumps(ids), json.dumps(linhas, ensure_ascii=False),
                                json.dumps(lido["relacionados"]), lido["via"], lido["paginas"], ctx.no,
                                json.dumps(lente), ctx.chave, ctx.ficha))
        if estado != SEM_MUDANCA:
            con.execute("INSERT INTO processos(processo, tag, primeira_em, ultima_em) VALUES (%s,%s,%s,%s) "
                        "ON CONFLICT (processo) DO UPDATE SET ultima_em = excluded.ultima_em",
                        (processo, PI.pasta(processo) or processo, em, em))
            con.execute("INSERT INTO arvores(processo, hash, n_docs, vista_em, origem) VALUES (%s,%s,%s,%s,'e2') "
                        "ON CONFLICT DO NOTHING", (processo, h, len(ids), em))
            cur = con.cursor()
            cur.executemany(_INS_DOC, [(processo, x["doc_id"], x["i"], x["titulo"], em, x["id_documento"] or None,
                                        x["restrito"]) for x in linhas])
    lid = con.execute("SELECT id FROM arvore_leitura WHERE job_chave = %s AND ficha = %s",
                      (ctx.chave, ctx.ficha)).fetchone()[0]
    return {"processo": processo, "estado": estado, "tree_hash": h, "n_docs": len(ids), "faltantes": len(falta),
            "restritos": sum(1 for x in linhas if x["restrito"]), "paginas": lido["paginas"], "via": lido["via"],
            "relacionados": lido["relacionados"], "leitura_id": lid, "anterior": anterior, "lente": lente,
            "versao": VERSAO}


def conferir(con, efeito: dict, ctx: Contexto) -> dict:
    """Relê o PG: linha desta posse, hash recalculado dos ids GRAVADOS, nº de documentos e faltas recontadas."""
    r = con.execute("SELECT id, processo, tree_hash, n_docs, ids, docs FROM arvore_leitura WHERE job_chave = %s "
                    "AND ficha = %s", (ctx.chave, ctx.ficha)).fetchone()
    if r is None:
        return {"ok": False, "motivo": "leitura desta posse não está no PG"}
    lid, proc, h, n, ids, docs = r
    h2 = tree_hash(ids, [str(d.get("id_documento") or "") for d in docs])
    falta = faltantes(ids, docs, capturados(con, proc), identidade_capturada(con, proc))
    ant = leitura_anterior(con, proc, antes_de=lid)
    c = {"hash_recalculado": h2 == h == efeito.get("tree_hash"), "n_docs": n == len(ids) == efeito.get("n_docs") > 0,
         "faltantes": len(falta) == efeito.get("faltantes")}
    if efeito.get("estado") == SEM_MUDANCA:
        c["sem_mudanca"] = not falta and (ant == h if ant is not None else hash_ids(ids) in hashes_legado(con, proc))
    c["ok"] = all(c.values())
    return c


# ══ 4. contrato do estágio ══════════════════════════════════════════════════════════════════════════════════════
def processo_do(payload: dict, ctx: Contexto) -> str:
    bruto = str(payload.get("processo") or (ctx.chave.split(":", 1)[1] if ":" in ctx.chave else "")).strip()
    k = PI.chave_processo(bruto)
    if not k or k.startswith(PI.PREFIXO_PCRJ):
        raise ErroPermanente(f"processo SEI-RJ inválido no payload/chave: {bruto!r}")
    return k


def _lente(payload: dict) -> list[str]:
    ev = payload.get("evento") or {}
    v = payload.get("lente") or (ev.get("detalhe") or {}).get("lente") or ev.get("lente") or []
    return sorted({v} if isinstance(v, str) else set(v))


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    processo = processo_do(payload, ctx)
    lido = ler_arvore(obter_navegador(), processo)
    if not lido["docs"]:
        if lido["restrito"]:
            raise ForaDeAlcance(f"{processo}: SEI respondeu RESTRITO ({lido['restrito']})")
        if lido["sem_resultado"] and lido.get("controle_positivo") is True:
            raise ForaDeAlcance(f"{processo}: 'Nenhum resultado' com controle positivo na mesma sessão — invisível à "
                                 "pesquisa (sigilo integral); rota: requisição formal")
        if lido["sem_resultado"]:
            raise RuntimeError(f"{processo}: INDISPONIVEL — 'Nenhum resultado' SEM controle positivo na sessão "
                               f"(controle={lido.get('controle_positivo')!r}): 0 ambíguo, transitório")
        raise RuntimeError(f"{processo}: árvore vazia (via {lido['via']!r}) — falha de leitura, tento de novo")
    lente = _lente(payload)
    con = conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        ef = registrar(con, processo, lido, ctx, lente)
    finally:
        con.close()
    eventos = []
    if ef["estado"] == DOC_NOVO:
        eventos.append({"fonte": "arvore", "tipo": DOC_NOVO, "chave": processo,
                        "detalhe": {"tree_hash": ef["tree_hash"], "faltantes": ef["faltantes"], "lente": lente}})
    eventos += [{"fonte": "sei_relacionado", "tipo": "citado", "chave": k, "detalhe": {"de": processo, "lente": lente}}
                for k in ef["relacionados"]]
    return Resultado(efeito=ef, eventos=eventos)


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    con = conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        c = conferir(con, resultado.efeito, ctx)
    finally:
        con.close()
    resultado.efeito["conferencia"] = c
    return bool(c["ok"])


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["navegador"], prioridade=50,
                  volta={"nos": ["vm2", "vm1"], "nota": "VM-2 ×1; VM-1 ×1 só em emergência"})


# ══ 5. fila única (seleção + ordem + lente) ═════════════════════════════════════════════════════════════════════
@dataclass
class Item:
    processo: str
    ugs: set[str] = field(default_factory=set)
    fontes: set[str] = field(default_factory=set)
    ob_paga: float = 0.0
    couto: bool = False
    credores: set[str] = field(default_factory=set)   # CNPJ/CPF das OB pagas do processo (lente por credor)
    data_fato: str | None = None                      # última OB PAGA (AAAA-MM-DD) — lente por data (couto)


def abrir_fonte(caminho: str | Path | None = None) -> sqlite3.Connection:
    """A coleta em modo só-leitura imutável (padrão: snapshot da parada de obras) — nunca o compliance.db vivo."""
    p = Path(caminho or os.environ.get(ENV_FONTE) or fonte_coleta.caminho())
    if not p.exists():
        raise ErroPermanente(f"fonte só-leitura ausente: {p}")
    return sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)


def _siglas_ug(indice: Path | None = None) -> dict[str, set[str]]:
    """sigla (como o índice do SIAFE a escreve) → UGs — o casamento da `unidade` do TCE-RJ ('FUNESBOM - …')."""
    from compliance_agent.fluxo.lentes import INDICE_UG
    idx = json.loads(Path(indice or INDICE_UG).read_text(encoding="utf-8")).get("ugs") or {}
    out: dict[str, set[str]] = {}
    for ug, sigla in idx.items():
        out.setdefault(str(sigla).strip(), set()).add(str(ug))
    return out


def _tabela(fonte, nome: str) -> bool:
    return fonte.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)).fetchone() is not None


def universo(fonte: sqlite3.Connection, extras: dict[str, set[str]] | None = None,
             indice: Path | None = None) -> dict[str, Item]:
    """Todo processo SEI-RJ conhecido, com as UGs de onde veio e a OB PAGA do SIAFE (régua `ob_paga_sql`)."""
    from compliance_agent.dominio.pagamento import ob_paga_sql
    from compliance_agent.governo_couto import INICIO
    u: dict[str, Item] = {}

    def add(proc, fonte_nome: str, ugs=()) -> Item | None:
        k = PI.chave_processo(proc or "")
        if not k or k.startswith(PI.PREFIXO_PCRJ):
            return None
        it = u.setdefault(k, Item(k))
        it.fontes.add(fonte_nome)
        it.ugs.update(x for x in ugs if x)
        return it

    iso = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"
    pago = ob_paga_sql(fonte)
    # credor só quando a coleta tem a coluna (fixture antiga não tem): o agrupamento ganha o credor, o resto é igual
    tem_credor = "credor" in {r[1] for r in fonte.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}
    cred = f"CASE WHEN {pago} THEN credor END" if tem_credor else "NULL"
    for proc, ug, v, ult, credor in fonte.execute(
            f"SELECT processo, ug_emitente, SUM(CASE WHEN {pago} THEN valor ELSE 0 END), "
            f"MAX(CASE WHEN {pago} THEN {iso} END), {cred} FROM ob_orcamentaria_siafe "
            f"WHERE COALESCE(processo,'') <> '' GROUP BY 1, 2{', 5' if tem_credor else ''}"):
        it = add(proc, "ob_siafe", [str(ug or "")])
        if it:
            it.ob_paga += float(v or 0.0)
            it.couto = it.couto or bool(ult and ult >= INICIO)
            if ult and (it.data_fato is None or ult > it.data_fato):
                it.data_fato = ult
            if credor:
                it.credores.add(str(credor))
    if _tabela(fonte, "ordens_bancarias"):                     # espelho TFE: só como fonte do nº (valor nunca)
        for proc, ug in fonte.execute("SELECT DISTINCT numero_sei, ug_codigo FROM ordens_bancarias "
                                      "WHERE COALESCE(numero_sei,'') <> ''"):
            add(proc, "ob_tfe", [str(ug or "")])
    siglas = _siglas_ug(indice)
    for tab in ("contratos_tcerj", "compras_diretas_tcerj"):
        if _tabela(fonte, tab):
            for proc, uni in fonte.execute(f"SELECT DISTINCT processo, unidade FROM {tab} "
                                           "WHERE COALESCE(processo,'') <> ''"):
                sig = str(uni or "").split(" - ", 1)[0].strip()
                add(proc, tab, siglas.get(sig, set()))
    for nome, procs in (extras or {}).items():
        for p in procs:
            add(p, nome)
    return u


def extras_locais(con_pg=None) -> dict[str, set[str]]:
    """Fontes de nº de processo fora da coleta: citações do acervo (`data/sei_familia.json`), o estado legado do E2
    (`data/sei_cache/sei_sweep_progress.json` — o sweep antigo migra como 'processo já conhecido') e a identidade
    do PG (`processos`). Arquivo ausente ⇒ a fonte fica vazia e é DECLARADA vazia (nunca inventada)."""
    out: dict[str, set[str]] = {"citacao_acervo": set(), "legado_sei_sweep": set(), "identidade_pg": set()}
    fam = RAIZ / "data" / "sei_familia.json"
    if fam.exists():
        d = json.loads(fam.read_text(encoding="utf-8"))
        for chave in ("cita", "citado_por"):
            for a, filhos in (d.get(chave) or {}).items():
                out["citacao_acervo"].add(a)
                out["citacao_acervo"].update(filhos)
    prog = RAIZ / "data" / "sei_cache" / "sei_sweep_progress.json"
    if prog.exists():
        out["legado_sei_sweep"].update((json.loads(prog.read_text(encoding="utf-8")).get("feitos") or {}).keys())
    if con_pg is not None:
        out["identidade_pg"].update(r[0] for r in con_pg.execute("SELECT processo FROM processos"))
    return out


def sinais_sweep(fonte: sqlite3.Connection) -> dict[str, Callable[[Item], bool]]:
    """Os sinais da ordem do tools/sei_sweep, pelas MESMAS funções de lá (porte sem reescrever), sobre a fonte."""
    from tools import sei_sweep as S

    def norm(conj) -> set[str]:
        return {k for k in (PI.chave_processo(x) or PI.chave_processo(_16(x)) for x in conj) if k}

    def _16(x) -> str:
        d = re.sub(r"\D", "", str(x))
        return d if len(d) == 16 else ""

    manual = norm(S._dirigidos(fonte))
    lacuna = norm(S._fila_com_lacuna_provada(fonte))
    diretas = norm(S._contratacao_direta())
    folha = norm(S._processos_de_folha(fonte))
    legiveis = S._unidades_legiveis()
    raizes = S._raizes_com_sinal_osint()
    credores: dict[str, set[str]] = {}
    if raizes:
        for proc, rz in S._credores_por_processo(fonte).items():
            k = PI.chave_processo(proc)
            if k:
                credores.setdefault(k, set()).update(rz)
    return {"manual": lambda it: it.processo in manual, "lacuna_provada": lambda it: it.processo in lacuna,
            "contratacao_direta": lambda it: it.processo in diretas, "folha": lambda it: it.processo in folha,
            "legivel": lambda it: it.processo[:6] in legiveis,
            "osint": lambda it: bool(credores.get(it.processo, set()) & raizes)}


def fila(fonte: sqlite3.Connection, lentes_res: dict, lente: str | None = None, extras: dict | None = None,
         sinais: dict | None = None, fracao_couto: float | None = None) -> list[tuple[Item, dict]]:
    """[(item, explicar)] na ordem única. `lente` = só os itens que casam com ela (filtro); toda lente que casa soma o
    bônus (prioridade). `explicar` traz os componentes gravados com o job e o motivo da lente."""
    from compliance_agent.fluxo import lentes as L
    from compliance_agent.fluxo.prioridade import Sinais, explicar, ordenar
    sinais = sinais if sinais is not None else sinais_sweep(fonte)
    itens = universo(fonte, extras)
    if lente is not None:
        if lente not in lentes_res:
            raise ErroPermanente(f"lente desconhecida: {lente}")
        alvo = lentes_res[lente]
        itens = {k: it for k, it in itens.items() if L.casa(alvo, it.ugs, k, it.credores, it.data_fato)}
    sin: dict[str, Sinais] = {}
    for k, it in itens.items():
        b, nomes = L.bonus(lentes_res, it.ugs, k, it.credores, it.data_fato)
        sin[k] = Sinais(ob_paga=round(it.ob_paga, 2), couto=it.couto, bonus_lente=b, lente=",".join(nomes) or None,
                        **{n: bool(f(it)) for n, f in sinais.items()})
    ordem = ordenar(list(itens.values()), lambda it: sin[it.processo], fracao_couto=fracao_couto)
    out = []
    for it in ordem:
        e = explicar(sin[it.processo])
        e["fontes"] = sorted(it.fontes)
        e["lente_motivo"] = {n: L.casa(lentes_res[n], it.ugs, it.processo, it.credores, it.data_fato)
                             for n in (e["sinais"]["lente"] or "").split(",") if n}
        out.append((it, e))
    return out


# ══ 6. paridade da lente (replay sobre o estado gravado — sem navegador) ═══════════════════════════════════════
def capturados_pelo_sweep(log: Path) -> dict[str, int]:
    """Processos que o sweep antigo leu COM documento (linha `SEI-… → N docs`, N > 0), com o maior N visto."""
    out: dict[str, int] = {}
    for m in re.finditer(r"(SEI-[0-9/]+) → (\d+) docs", log.read_text(encoding="utf-8", errors="replace")):
        k, n = PI.chave_processo(m[1]), int(m[2])
        if k and n > 0:
            out[k] = max(out.get(k, 0), n)
    return out


def paridade(fonte: sqlite3.Connection, lentes_res: dict, lente: str, log: Path, extras: dict) -> dict:
    """A ⊆ B? A = capturados pelo sweep antigo; B = selecionados pela fila nova com a lente. Relatório das diferenças
    e de QUAL fonte cobre cada capturado (para dizer quanto depende do estado legado migrado)."""
    from compliance_agent.fluxo.lentes import casa
    A = capturados_pelo_sweep(log)
    sel = fila(fonte, lentes_res, lente, extras=extras, sinais={})
    B = {it.processo: it for it, _ in sel}
    falta = sorted(set(A) - set(B))
    por_fonte: dict[str, int] = {}
    so_legado = 0
    for k in set(A) & set(B):
        fs = B[k].fontes
        for f in fs:
            por_fonte[f] = por_fonte.get(f, 0) + 1
        so_legado += fs <= {"legado_sei_sweep"}
    motivo: dict[str, int] = {}
    for k in set(A) & set(B):
        m = (casa(lentes_res[lente], B[k].ugs, k, B[k].credores, B[k].data_fato) or "?").split(":")[0]
        motivo[m] = motivo.get(m, 0) + 1
    return {"lente": lente, "capturados_sweep_antigo": len(A), "selecionados_fila_nova": len(B),
            "contido": not falta, "faltando": len(falta), "faltando_lista": falta[:200],
            "capturados_por_fonte": dict(sorted(por_fonte.items(), key=lambda x: -x[1])),
            "capturados_so_pelo_legado": so_legado, "capturados_por_motivo_da_lente": motivo,
            "a_mais_na_fila_nova": len(set(B) - set(A)),
            "a_mais_com_ob_paga": sum(1 for k in set(B) - set(A) if B[k].ob_paga > 0)}


# ══ 7. CLI ══════════════════════════════════════════════════════════════════════════════════════════════════════
def main(argv: list[str] | None = None) -> int:
    from compliance_agent.fluxo import lentes as L
    ap = argparse.ArgumentParser(description="E2 árvore (O3.3)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("schema")
    s.add_argument("acao", choices=["aplicar"])
    s.add_argument("--esquema")
    lr = sub.add_parser("ler")
    lr.add_argument("--processo", required=True)
    for nome in ("fila", "paridade"):
        p = sub.add_parser(nome)
        p.add_argument("--lente", required=nome == "paridade")
        p.add_argument("--fonte")
        p.add_argument("--limite", type=int, default=20)
        p.add_argument("--saida")
        p.add_argument("--log", default=str(RAIZ / "data" / "bombeiros_sweep.out"))
    a = ap.parse_args(argv)
    if a.cmd == "schema":
        aplicar_schema(EV.dsn_vigente(), a.esquema)
        print(f"arvore: schema aplicado em {esquema_vigente(a.esquema)}")
        return 0
    if a.cmd == "ler":
        lido = ler_arvore(obter_navegador(), PI.chave_processo(a.processo) or a.processo)
        ids, h = identidade(lido["docs"])
        print(json.dumps({"n_docs": len(ids), "tree_hash": h, "paginas": lido["paginas"], "via": lido["via"],
                          "restritos": sum(1 for d in lido["docs"] if d.get("restrito")),
                          "relacionados": lido["relacionados"][:20]}, ensure_ascii=False))
        return 0
    fonte = abrir_fonte(a.fonte)
    lentes_res, medidas = L.resolver(L.carregar(), fonte, externas=a.lente == "beneficios")
    pg = conectar() if EV.dsn_vigente() else None
    try:
        extras = extras_locais(pg)
    finally:
        if pg is not None:
            pg.close()
    if a.cmd == "fila":
        sel = fila(fonte, lentes_res, a.lente, extras=extras)
        out = {"total": len(sel), "lente": a.lente, "medida_lentes": medidas,
               "topo": [{"processo": it.processo, **e} for it, e in sel[: a.limite]]}
    else:
        out = paridade(fonte, lentes_res, a.lente, Path(a.log), extras)
        out["medida_lentes"] = medidas
    txt = json.dumps(out, ensure_ascii=False, indent=1)
    if a.saida:
        Path(a.saida).write_text(txt, encoding="utf-8")
    print(txt if not a.saida else json.dumps({k: v for k, v in out.items() if k not in ("topo", "faltando_lista")},
                                             ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
