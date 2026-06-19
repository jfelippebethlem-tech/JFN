#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lex_pesquisa_internet — Fase 5: o Lex PESQUISA as dúvidas na internet, APRENDE e RE-AJUSTA a análise.

Fecha o ciclo do cérebro vivo: para um fornecedor (top-score ou --cnpj), extrai as DÚVIDAS abertas do que o
sweep já levantou (red_flags da `sei_ficha`/`sei_direcionamento` + o "o que verificar" da análise + a ressalva
do parecer de direcionamento), PESQUISA cada uma reusando o OSINT já existente (web_research + Querido Diário
+ mídia adversa), e roda o LLM (gemini, tier PRODUTO) p/ julgar se a evidência RESOLVE, AGRAVA ou deixa a
dúvida em aberto — produzindo um RE-AJUSTE da análise. O aprendizado fica PERMANENTE em dois lugares:
  • DB `lex_pesquisa` (queryável; o Lex/relatório faz SURFACE sem re-pesquisar);
  • vault `~/vault/aprendizados/pesquisa-fornecedor-<cnpj>.md` (memória de longo prazo, AI-first).

HONESTO (cláusula JFN): indício a verificar, NUNCA acusação (presunção de legitimidade). INDISPONÍVEL ≠ 0:
OSINT vazio/sem resposta NÃO vira agravante; cada achado cita as FONTES. LLM injetável p/ teste sem rede.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.lex_pesquisa_internet --cnpj 12345678000190
    PYTHONPATH=. .venv/bin/python -m tools.lex_pesquisa_internet --top 4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "compliance.db"
VAULT = Path(__import__("os").environ.get("VAULT_DIR", str(Path.home() / "vault")))

_REAVALIAR_DIAS = 30
_MAX_DUVIDAS = 8
_MAX_EVID = 9000   # teto do texto de evidência mandado ao LLM


_DDL = """
CREATE TABLE IF NOT EXISTS lex_pesquisa (
  fornecedor_cnpj TEXT PRIMARY KEY,
  fornecedor_nome TEXT,
  duvidas    TEXT,   -- JSON [str]
  achados    TEXT,   -- JSON [{duvida, veredito, nota, fontes}]
  resumo     TEXT,
  reajuste   TEXT,   -- como a análise se re-ajusta com o que foi aprendido
  n_fontes   INTEGER,
  modelo     TEXT,
  vault_path TEXT,
  em         TEXT
);
"""

_SYS = (
    "Você é AUDITOR DE CONTROLE EXTERNO (TCE-RJ) que recebeu DÚVIDAS abertas sobre um fornecedor do Estado e "
    "EVIDÊNCIAS coletadas na internet (busca web, notícias, Diário Oficial/Querido Diário, mídia adversa). "
    "Para CADA dúvida, decida com base SÓ nas evidências: 'resolvido' (a evidência esclarece/afasta a dúvida), "
    "'agrava' (a evidência reforça o indício — cite a fonte), ou 'inconclusivo' (evidência insuficiente). "
    "Regras ABSOLUTAS: (1) NUNCA afirme irregularidade/fraude — fale 'indício a verificar' (presunção de "
    "legitimidade). (2) INDISPONÍVEL ≠ irregular: ausência de notícia/registro NÃO agrava. (3) Cada achado que "
    "'agrava' DEVE citar a fonte (url/título) da evidência; sem fonte, não agrave. (4) Não invente fatos. "
    "Produza também um 'reajuste' (2-4 frases): como a análise do fornecedor muda com o que foi aprendido. "
    "Responda SOMENTE com o objeto JSON do schema, sem texto fora do JSON."
)

_SCHEMA = (
    '{"achados":[{"duvida":"a dúvida avaliada","veredito":"resolvido|agrava|inconclusivo",'
    '"nota":"1-2 frases do porquê, citando a evidência","fontes":["url ou título da fonte"]}],'
    '"resumo":"1-2 frases do conjunto (indício, não acusação)",'
    '"reajuste":"como a análise se re-ajusta com o aprendido (2-4 frases)"}'
)


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(_DDL)
    # migração aditiva idempotente (padrão _COLS_LLM): coluna do aprendizado cruzado p/ SURFACE sem recomputar
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(lex_pesquisa)")}
        if "cruzado" not in cols:
            con.execute("ALTER TABLE lex_pesquisa ADD COLUMN cruzado TEXT")
            con.commit()
    except sqlite3.OperationalError:
        pass
    return con


def _norm_cnpj(c: str) -> str:
    return re.sub(r"\D", "", c or "")


def extrair_duvidas(cnpj: str, con: sqlite3.Connection) -> tuple[str, list[str]]:
    """Junta as DÚVIDAS abertas do fornecedor a partir do que o sweep já sabe: red_flags acumuladas
    (`sei_direcionamento`), red_flags + 'o que verificar' das fichas das suas árvores (`sei_ficha`), e a
    ressalva do parecer de direcionamento LLM. Dedup, bounded. Retorna (nome, duvidas)."""
    cd = _norm_cnpj(cnpj)
    nome = ""
    duvidas: list[str] = []

    def _add(x):
        x = (x or "").strip()
        if x and x not in duvidas:
            duvidas.append(x)

    # 1) memória cruzada de direcionamento (red_flags dedup + ressalva LLM)
    cols = {r[1] for r in con.execute("PRAGMA table_info(sei_direcionamento)")} \
        if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sei_direcionamento'").fetchone() else set()
    if cols:
        sel = "fornecedor_nome, red_flags" + (", arvores" if "arvores" in cols else "") \
              + (", llm_json" if "llm_json" in cols else "")
        row = con.execute(
            f"SELECT {sel} FROM sei_direcionamento WHERE "
            "replace(replace(replace(fornecedor_cnpj,'.',''),'/',''),'-','')=?", (cd,)).fetchone()
        if row:
            nome = row[0] or ""
            for rf in _json_list(row[1]):
                _add(str(rf))
            if "llm_json" in cols and row[-1]:
                try:
                    j = json.loads(row[-1])
                    _add(j.get("ressalva"))
                    for ex in (j.get("exigencias_restritivas") or [])[:3]:
                        _add(ex.get("por_que_restringe"))
                except Exception:  # noqa: BLE001
                    pass

    # 2) red_flags + análise ('o que verificar') das fichas das árvores do fornecedor
    if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sei_ficha'").fetchone():
        like = f'%{cd}%'
        for rf_json, analise in con.execute(
                "SELECT red_flags, analise FROM sei_ficha WHERE cnpjs LIKE ? AND red_flags IS NOT NULL "
                "AND red_flags<>'[]' LIMIT 30", (like,)):
            for rf in _json_list(rf_json):
                _add(str(rf))
    return nome, duvidas[:_MAX_DUVIDAS]


def _json_list(s) -> list:
    try:
        v = json.loads(s or "[]")
        return v if isinstance(v, list) else []
    except Exception:  # noqa: BLE001
        return []


async def coletar_osint(nome: str, cnpj: str) -> dict:
    """Reusa o OSINT existente (best-effort, honesto em erro): web_research.investigar + Querido Diário
    (histórico no DOERJ) + mídia adversa. Retorna {evidencia, fontes:[...], blocos:{...}, erros:[...]}."""
    blocos: dict = {}
    fontes: list[str] = []
    erros: list[str] = []
    alvo = nome or cnpj
    # web + notícias + cadastro
    try:
        from compliance_agent.collectors import web_research
        d = await web_research.investigar(alvo, cnpj=cnpj)
        blocos["web"] = {"resumo": d.get("resumo", ""), "riscos": d.get("riscos_detectados", []),
                         "web": d.get("web", [])[:6], "noticias": d.get("noticias", [])[:6]}
        for it in (d.get("web", []) + d.get("noticias", [])):
            u = it.get("url") or it.get("link") or it.get("titulo")
            if u:
                fontes.append(str(u))
    except Exception as e:  # noqa: BLE001
        erros.append(f"web_research: {str(e)[:60]}")
    # Querido Diário (DOERJ)
    try:
        from compliance_agent.collectors import querido_diario
        qd = await querido_diario.historico_empresa(cnpj or nome, anos=3)
        blocos["doerj"] = {"total": qd.get("total_publicacoes", 0), "tipos": qd.get("tipos", {}),
                           "tem_sancao": qd.get("tem_sancao_historica", False),
                           "excerpts": qd.get("excerpts", [])}
        for ex in qd.get("excerpts", []):
            if ex.get("url"):
                fontes.append(str(ex["url"]))
    except Exception as e:  # noqa: BLE001
        erros.append(f"querido_diario: {str(e)[:60]}")
    # mídia adversa (síncrono → executor p/ não bloquear o loop)
    try:
        from compliance_agent.enrich import midia_adversa
        ma = await asyncio.to_thread(midia_adversa.varrer, nome, cnpj)
        if ma.get("ok"):
            blocos["midia_adversa"] = {"n_adversos": ma.get("n_adversos", 0),
                                       "adversos": (ma.get("adversos") or [])[:5]}
            for a in (ma.get("adversos") or []):
                if a.get("url"):
                    fontes.append(str(a["url"]))
    except Exception as e:  # noqa: BLE001
        erros.append(f"midia_adversa: {str(e)[:60]}")
    evidencia = json.dumps(blocos, ensure_ascii=False)[:_MAX_EVID]
    # dedup preservando ordem
    fontes_d = list(dict.fromkeys(fontes))
    return {"evidencia": evidencia, "fontes": fontes_d, "blocos": blocos, "erros": erros}


def _aprendizado_previo(cnpj: str, con: sqlite3.Connection) -> str:
    """ELO PROGRESSIVO (auditoria 2026-06-17): relê o aprendizado JÁ persistido deste fornecedor
    (lex_pesquisa) p/ ALIMENTAR o raciocínio — antes era escrito no vault/DB e nunca relido. Bounded;
    honesto se não há ('')."""
    try:
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lex_pesquisa'").fetchone():
            return ""
        cd = _norm_cnpj(cnpj)
        row = con.execute(
            "SELECT resumo, reajuste, achados, em FROM lex_pesquisa WHERE "
            "replace(replace(replace(fornecedor_cnpj,'.',''),'/',''),'-','')=?", (cd,)).fetchone()
    except sqlite3.Error:
        return ""
    if not row:
        return ""
    resumo, reajuste, achados_j, em = row
    if not ((resumo or "").strip() or (reajuste or "").strip()):
        return ""
    ach = "; ".join(str(a) for a in _json_list(achados_j))[:600]
    blk = [f"(pesquisa anterior em {em or '?'})"]
    if (resumo or "").strip():
        blk.append(f"resumo: {resumo.strip()[:800]}")
    if ach:
        blk.append(f"achados: {ach}")
    if (reajuste or "").strip():
        blk.append(f"re-ajuste anterior: {reajuste.strip()[:400]}")
    return "\n".join(blk)


def _montar_user(nome: str, cnpj: str, duvidas: list[str], osint: dict, previo: str = "",
                 cruzado: str = "") -> str:
    dv = "\n".join(f"  {i+1}. {d}" for i, d in enumerate(duvidas)) or "  (sem dúvidas registradas)"
    prev = (f"=== APRENDIZADO PRÉVIO (releia e CONSTRUA sobre ele; NÃO repita o já concluído) ===\n{previo}\n\n"
            if previo else "")
    # Aprendizado cruzado: o que já se sabe de fornecedores LIGADOS (mesmos sócios/veículos). Anti-viés:
    # serve p/ corroborar/contrastar, JAMAIS p/ presumir culpa por associação (presunção de legitimidade).
    cruz = (f"=== PADRÕES EM FORNECEDORES LIGADOS (mesmos sócios/veículos) — corrobore/contraste, NÃO copie; "
            f"presunção de legitimidade ===\n{cruzado}\n\n" if (cruzado or "").strip() else "")
    # respeita o teto de evidência: o bloco cruzado entra no budget _MAX_EVID junto com o OSINT
    evid = (osint.get("evidencia") or "(nada coletado)")
    if cruz:
        folga = max(0, _MAX_EVID - len(cruz))
        evid = evid[:folga] if folga else "(omitido por limite)"
    return (f"FORNECEDOR: {nome or '?'} · CNPJ {cnpj}\n\n=== DÚVIDAS ABERTAS ===\n{dv}\n\n"
            f"{prev}{cruz}=== EVIDÊNCIAS COLETADAS (OSINT) ===\n{evid}\n\n"
            f"Avalie cada dúvida à luz das evidências e do aprendizado prévio (e dos padrões em fornecedores "
            f"ligados, como contexto — não como prova) e responda SOMENTE com este JSON:\n{_SCHEMA}")


async def _gerar_default(messages: list[dict]) -> str:
    from compliance_agent.direcionamento_cerebro import _gerar_default as g
    return await g(messages)


async def pesquisar(cnpj: str, *, gerar=None, osint_fn=None, gravar_vault: bool = True,
                    con: sqlite3.Connection | None = None) -> dict:
    """Pesquisa as dúvidas do fornecedor, re-ajusta via LLM e APRENDE (DB + vault). `gerar` (async
    messages->str) e `osint_fn` (async (nome,cnpj)->dict) injetáveis p/ teste sem rede."""
    _con = con or _conectar()
    try:
        nome, duvidas = extrair_duvidas(cnpj, _con)
        if not duvidas:
            return {"cnpj": cnpj, "nome": nome, "status": "sem_duvidas",
                    "resumo": "Sem dúvidas abertas registradas p/ este fornecedor (nada a pesquisar)."}
        osint = await (osint_fn or coletar_osint)(nome, cnpj)
        previo = _aprendizado_previo(cnpj, _con)
        # ELO CROSS-FORNECEDOR: o que já se aprendeu de fornecedores LIGADOS (mesmos sócios/veículos).
        # Best-effort, custo LLM 0, honesto ('' em erro). Anti-viés tratado no _montar_user.
        try:
            from tools.lex_aprendizado_cruzado import aprendizado_cruzado
            cruzado = aprendizado_cruzado(cnpj, _con)
        except Exception:  # noqa: BLE001
            cruzado = ""
        gerar = gerar or _gerar_default
        messages = [{"role": "system", "content": _SYS},
                    {"role": "user", "content": _montar_user(nome, cnpj, duvidas, osint, previo, cruzado)}]
        from compliance_agent.direcionamento_cerebro import _parse_json
        try:
            raw = await gerar(messages)
            dados = _parse_json(raw) or {}
        except Exception as e:  # noqa: BLE001 — LLM indisponível: honesto, não fabrica
            dados = {"resumo": f"LLM indisponível ({str(e)[:50]}) — pesquisa coletada, análise não realizada.",
                     "achados": [], "reajuste": ""}
        # Guard: chamada OK mas JSON não-parseável/vazio → NÃO descartar o OSINT em silêncio (honestidade:
        # antes ficava resumo='' e achados=[], indistinguível de "sem nada"; agora sinaliza p/ reprocessar).
        if not (dados.get("resumo") or "").strip():
            dados["resumo"] = ("Análise não consolidada (LLM retornou resposta não-parseável); "
                               f"{len(osint.get('fontes') or [])} fonte(s) OSINT coletada(s) — reprocessar.")
        res = {"cnpj": cnpj, "nome": nome, "duvidas": duvidas,
               "achados": dados.get("achados") or [], "resumo": dados.get("resumo") or "",
               "reajuste": dados.get("reajuste") or "", "fontes": osint.get("fontes") or [],
               "n_fontes": len(osint.get("fontes") or []), "erros_osint": osint.get("erros") or [],
               "cruzado": cruzado or "",
               "ressalva": "presunção de legitimidade; indício a apurar, não acusação"}
        vault_path = _gravar_vault(res) if gravar_vault else ""
        _persistir(_con, res, vault_path)
        res["vault_path"] = vault_path
        return res
    finally:
        if con is None:
            _con.close()


def _persistir(con: sqlite3.Connection, res: dict, vault_path: str, modelo: str = "gemini") -> None:
    # 'cruzado' surface-only: a coluna pode não existir em bancos antigos → grava best-effort sem quebrar.
    tem_cruzado = "cruzado" in {r[1] for r in con.execute("PRAGMA table_info(lex_pesquisa)")}
    if tem_cruzado:
        con.execute(
            """INSERT INTO lex_pesquisa
               (fornecedor_cnpj,fornecedor_nome,duvidas,achados,resumo,reajuste,n_fontes,modelo,vault_path,cruzado,em)
               VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(fornecedor_cnpj) DO UPDATE SET fornecedor_nome=excluded.fornecedor_nome,
                 duvidas=excluded.duvidas,achados=excluded.achados,resumo=excluded.resumo,
                 reajuste=excluded.reajuste,n_fontes=excluded.n_fontes,modelo=excluded.modelo,
                 vault_path=excluded.vault_path,cruzado=excluded.cruzado,em=datetime('now')""",
            (res["cnpj"], res.get("nome") or "", json.dumps(res.get("duvidas") or [], ensure_ascii=False),
             json.dumps(res.get("achados") or [], ensure_ascii=False), res.get("resumo") or "",
             res.get("reajuste") or "", res.get("n_fontes") or 0, modelo, vault_path,
             res.get("cruzado") or ""))
    else:
        con.execute(
            """INSERT INTO lex_pesquisa
               (fornecedor_cnpj,fornecedor_nome,duvidas,achados,resumo,reajuste,n_fontes,modelo,vault_path,em)
               VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(fornecedor_cnpj) DO UPDATE SET fornecedor_nome=excluded.fornecedor_nome,
                 duvidas=excluded.duvidas,achados=excluded.achados,resumo=excluded.resumo,
                 reajuste=excluded.reajuste,n_fontes=excluded.n_fontes,modelo=excluded.modelo,
                 vault_path=excluded.vault_path,em=datetime('now')""",
            (res["cnpj"], res.get("nome") or "", json.dumps(res.get("duvidas") or [], ensure_ascii=False),
             json.dumps(res.get("achados") or [], ensure_ascii=False), res.get("resumo") or "",
             res.get("reajuste") or "", res.get("n_fontes") or 0, modelo, vault_path))
    con.commit()


def _gravar_vault(res: dict) -> str:
    """Grava/atualiza a nota de aprendizado no vault (~/vault/aprendizados/pesquisa-internet/) — memória de
    longo prazo, AI-first, AGRUPADA numa subpasta. Honesto: degrada silencioso se o vault não existir ('')."""
    base = VAULT / "aprendizados" / "pesquisa-internet"
    try:
        if not VAULT.exists():
            return ""
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ""
    safe = re.sub(r"[^0-9A-Za-z]", "", res["cnpj"]) or "sem_cnpj"
    p = base / f"pesquisa-fornecedor-{safe}.md"
    L = ["---", "tipo: aprendizado", "fonte: lex_pesquisa_internet", f"cnpj: '{res['cnpj']}'",
         "ai-first: true", "honesto: indício a verificar, não acusação", "---", "",
         f"# Pesquisa-internet — {res.get('nome') or res['cnpj']}", "",
         "> Indício a verificar (presunção de legitimidade), nunca acusação. INDISPONÍVEL ≠ irregular.", "",
         f"**Resumo:** {res.get('resumo') or '—'}", "",
         f"**Re-ajuste da análise:** {res.get('reajuste') or '—'}", "", "## Dúvidas pesquisadas"]
    for a in (res.get("achados") or []):
        vd = str(a.get("veredito") or "?").upper()
        L.append(f"- **[{vd}]** {a.get('duvida','')} — {a.get('nota','')}")
        for f in (a.get("fontes") or [])[:4]:
            L.append(f"  - fonte: {f}")
    if res.get("erros_osint"):
        L += ["", f"_OSINT parcial: {'; '.join(res['erros_osint'])}_"]
    try:
        p.write_text("\n".join(L) + "\n", encoding="utf-8")
    except OSError:
        return ""
    return str(p)


def parecer_pesquisa(cnpj: str) -> dict | None:
    """SURFACE (só leitura) do parecer de pesquisa-internet já persistido p/ o fornecedor. None se não há."""
    if not DB.exists():
        return None
    cd = _norm_cnpj(cnpj)
    if not cd:
        return None
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lex_pesquisa'").fetchone():
            return None
        tem_cruzado = "cruzado" in {r[1] for r in con.execute("PRAGMA table_info(lex_pesquisa)")}
        sel_cruz = ", cruzado" if tem_cruzado else ""
        row = con.execute(
            "SELECT fornecedor_nome, duvidas, achados, resumo, reajuste, n_fontes, modelo, vault_path, em"
            f"{sel_cruz} FROM lex_pesquisa WHERE replace(replace(replace(fornecedor_cnpj,'.',''),'/',''),'-','')=?",
            (cd,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not row:
        return None
    return {"nome": row[0], "duvidas": _json_list(row[1]), "achados": _json_list(row[2]),
            "resumo": row[3] or "", "reajuste": row[4] or "", "n_fontes": row[5] or 0,
            "modelo": row[6] or "", "vault_path": row[7] or "", "avaliado_em": row[8] or "",
            "cruzado": (row[9] if len(row) > 9 else "") or ""}


def _top_cnpjs(con: sqlite3.Connection, top_n: int, min_score: int) -> list[str]:
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sei_direcionamento'").fetchone():
        return []
    return [r[0] for r in con.execute(
        "SELECT fornecedor_cnpj FROM sei_direcionamento WHERE score>=? ORDER BY score DESC LIMIT ?",
        (min_score, top_n))]


def rodar(top_n: int = 4, cnpj: str | None = None, min_score: int = 1, forcar: bool = False,
          gravar_vault: bool = True) -> dict:
    if not DB.exists():
        return {"erro": "compliance.db ausente"}
    con = _conectar()
    alvos = [_norm_cnpj(cnpj)] if cnpj else _top_cnpjs(con, top_n, min_score)
    feitos = pulados = 0
    out: list[dict] = []
    for cd in alvos:
        if not forcar:
            row = con.execute("SELECT em FROM lex_pesquisa WHERE "
                              "replace(replace(replace(fornecedor_cnpj,'.',''),'/',''),'-','')=?", (cd,)).fetchone()
            if row and row[0]:
                try:
                    from datetime import datetime
                    if (datetime.now() - datetime.fromisoformat(row[0].replace("Z", ""))).days < _REAVALIAR_DIAS:
                        pulados += 1
                        continue
                except (ValueError, TypeError):
                    pass
        res = asyncio.run(pesquisar(cd, gravar_vault=gravar_vault, con=con))
        feitos += 1
        out.append({"cnpj": cd, "nome": res.get("nome"), "status": res.get("status", "ok"),
                    "n_achados": len(res.get("achados") or []), "n_fontes": res.get("n_fontes", 0),
                    "resumo": (res.get("resumo") or "")[:140]})
    con.close()
    return {"feitos": feitos, "pulados": pulados, "alvos": out}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=4, help="quantos top-score pesquisar")
    ap.add_argument("--min-score", type=int, default=1)
    ap.add_argument("--cnpj", type=str, default=None, help="pesquisa só este fornecedor (ignora --top)")
    ap.add_argument("--forcar", action="store_true", help="re-pesquisa mesmo com parecer recente (<30d)")
    ap.add_argument("--sem-vault", action="store_true", help="não grava a nota no vault (só DB)")
    a = ap.parse_args()
    r = rodar(top_n=a.top, cnpj=a.cnpj, min_score=a.min_score, forcar=a.forcar, gravar_vault=not a.sem_vault)
    if r.get("erro"):
        print(f"[lex_pesquisa] ERRO: {r['erro']}")
        return 1
    print(f"[lex_pesquisa] feitos={r['feitos']} · pulados(cache)={r['pulados']}")
    for x in r.get("alvos", []):
        print(f"  {x['nome'] or x['cnpj']} · {x['status']} · {x['n_achados']} achados · {x['n_fontes']} fontes")
        if x.get("resumo"):
            print(f"      {x['resumo']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
