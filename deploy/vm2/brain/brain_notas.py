"""Busca POR NOTA e índice de ENTIDADES do jfn-brain (fases 2 e 4 de docs/ARQUITETURA-SEGUNDO-CEREBRO-ALVO.md).

A regra de busca e o extrator de identificadores vêm de `cerebro_fts.py` — o MESMO arquivo que a VM-1 usa
(JFN compliance_agent/cerebro_fts.py, implantado com md5 conferido). Aqui fica só a cola com o Postgres.

  sincronizar()            notas em disco → índice BM25 por nota (~/brain/notas_fts.db). Incremental.
  notas(q, n)              notas por BM25, na ordem
  mencoes_de(texto)        identificadores determinísticos (CNPJ com dígito conferido, processo SEI, UG, OB) + trecho
  gravar_mencoes(...)      regrava as menções de UMA origem ("vault:casos/x.md" ou "mem:123")
  entidade(ref, com)       tudo o que cita a entidade (e, com `com`, só o que cita as duas)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import cerebro_fts as F

BRAIN = Path.home() / "brain"
FTS = BRAIN / "notas_fts.db"
CORES = BRAIN / "ug_cores.json"


def chave_nota(source: str, path: str) -> str:
    return path if source == "vault" else f"{source}:{path}"


def sincronizar(arquivos) -> dict:
    """`arquivos`: iterável de (source, raiz, caminho) — o mesmo `iter_files` do indexador."""
    con = F.abrir(FTS)
    try:
        conhecidos = F.conhecidos(con)
        vistos, novos = set(), 0
        for src, raiz, p in arquivos:
            st = p.stat()
            chave, assinatura = chave_nota(src, str(p.relative_to(raiz))), f"{st.st_mtime}:{st.st_size}"
            vistos.add(chave)
            if conhecidos.get(chave) != assinatura:
                F.gravar(con, chave, assinatura, p.read_text(encoding="utf-8", errors="replace"), p.stem, extra=src)
                novos += 1
        sumidos = set(conhecidos) - vistos
        for chave in sumidos:
            F.remover(con, chave)
        con.commit()
        return {"notas_fts": len(vistos), "fts_regravadas": novos, "fts_removidas": len(sumidos)}
    finally:
        con.close()


def notas(q: str, n: int = 40) -> list[dict]:
    con = F.abrir(FTS)
    try:
        return F.consultar(con, q, n)
    finally:
        con.close()


# ---------- entidades ----------

def mencoes_de(texto: str) -> list[tuple[str, str, str]]:
    return [(t, c, F.trecho_de(texto, t, c)) for t, c in F.entidades(texto)]


def gravar_mencoes(c, ref: str, texto: str, papel: str = "citada") -> int:
    """Regrava as menções de uma origem. `c` = conexão psycopg já em transação."""
    c.execute("DELETE FROM entidade_mencao WHERE origem_ref=%s", (ref,))
    ms = mencoes_de(texto)
    for tipo, chave, trecho in ms:
        c.execute("INSERT INTO entidade(tipo,chave) VALUES (%s,%s) ON CONFLICT DO NOTHING", (tipo, chave))
        c.execute("INSERT INTO entidade_mencao(tipo,chave,origem_ref,papel,trecho) VALUES (%s,%s,%s,%s,%s) "
                  "ON CONFLICT DO NOTHING", (tipo, chave, ref, papel, trecho))
    return len(ms)


def papel_da_nota(path: str) -> str:
    return "caso" if path.startswith("casos/") else "citada"


def carregar_cores(c) -> int:
    """Nome e cor de cada UG (gerado na VM-1 por compliance_agent/cores_orgaos — a mesma paleta do Obsidian e da galáxia)."""
    if not CORES.exists():
        return 0
    dados = json.loads(CORES.read_text(encoding="utf-8"))
    for ug, d in dados.items():
        c.execute("INSERT INTO entidade(tipo,chave,nome,cor) VALUES ('ug',%s,%s,%s) "
                  "ON CONFLICT (tipo,chave) DO UPDATE SET nome=EXCLUDED.nome, cor=EXCLUDED.cor", (ug, d["nome"], d["cor"]))
    return len(dados)


def resolver(ref: str, tipo: str | None = None) -> tuple[str, str] | None:
    """Texto livre → (tipo, chave). Aceita CNPJ com ou sem pontuação, nº de processo, "UG 133100" ou só 133100, nº de OB."""
    ents = F.entidades(ref)
    if tipo:
        ents = [e for e in ents if e[0] == tipo] or ents
    if ents:
        return ents[0]
    d = re.sub(r"\D", "", ref)
    if len(d) == 14 and F.cnpj_valido(d):
        return ("cnpj", d)
    if len(d) == 6 and (tipo in (None, "ug")):
        return ("ug", d)
    return None


def entidade(c, ref: str, com: str | None = None, tipo: str | None = None, limite: int = 60) -> dict:
    alvo = resolver(ref, tipo)
    if not alvo:
        return {"erro": f"não reconheci um identificador em {ref!r} (CNPJ, nº de processo SEI, UG ou nº de OB)"}
    outro = resolver(com) if com else None
    if com and not outro:
        return {"erro": f"não reconheci um identificador em {com!r}"}
    filtro, args = "", [alvo[0], alvo[1]]
    if outro:
        filtro = ("AND m.origem_ref IN (SELECT origem_ref FROM entidade_mencao WHERE tipo=%s AND chave=%s)")
        args += [outro[0], outro[1]]
    linhas = c.execute(
        f"SELECT m.origem_ref, m.papel, m.trecho FROM entidade_mencao m WHERE m.tipo=%s AND m.chave=%s {filtro} "
        "ORDER BY (m.papel='caso') DESC, m.origem_ref", args).fetchall()
    refs = [r[0] for r in linhas]
    notas_, mems = [], []
    titulos = {chave_nota(s, p): (t, i) for s, p, t, i in c.execute(
        "SELECT source, path, title, id FROM notes WHERE (CASE WHEN source='vault' THEN path ELSE source||':'||path END) "
        "= ANY(%s)", ([r[5:] if r.startswith("nota:") else r for r in refs],))}
    ids = [int(r[4:]) for r in refs if r.startswith("mem:")]
    ativas = {i: (k, s, ct, cr) for i, k, s, ct, cr in c.execute(
        "SELECT id, kind, subject, content, created_at FROM memories WHERE id = ANY(%s) AND status='ativa'", (ids,))}
    for ref_, papel, trecho in linhas:
        if ref_.startswith("nota:"):
            chave = ref_[5:]
            if chave in titulos:
                notas_.append({"path": chave, "title": titulos[chave][0], "papel": papel, "trecho": trecho})
        elif int(ref_[4:]) in ativas:
            k, s, ct, cr = ativas[int(ref_[4:])]
            mems.append({"id": int(ref_[4:]), "kind": k, "subject": s, "content": ct[:400], "created_at": cr.isoformat()})
    co = c.execute(
        "SELECT o.tipo, o.chave, e.nome, e.cor, count(*) n FROM entidade_mencao o "
        "LEFT JOIN entidade e ON e.tipo=o.tipo AND e.chave=o.chave "
        "WHERE o.origem_ref = ANY(%s) AND NOT (o.tipo=%s AND o.chave=%s) GROUP BY 1,2,3,4 ORDER BY n DESC, 1, 2 LIMIT 40",
        (refs, alvo[0], alvo[1])).fetchall()
    cab = c.execute("SELECT nome, cor FROM entidade WHERE tipo=%s AND chave=%s", alvo).fetchone() or (None, None)
    return {"entidade": {"tipo": alvo[0], "chave": alvo[1], "nome": cab[0], "cor": cab[1]},
            "com": {"tipo": outro[0], "chave": outro[1]} if outro else None,
            "total_notas": len(notas_), "total_memorias": len(mems),
            "notas": notas_[:limite], "memorias": mems[:limite],
            "aparece_junto_de": [{"tipo": t, "chave": k, "nome": n, "cor": cor, "origens": q} for t, k, n, cor, q in co]}
