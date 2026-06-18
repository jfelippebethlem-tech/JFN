"""lex_feedback — canal Lex/JFN → Claude Code (nós).

O Lex e o JFN passam para nós (via Claude Code) suas DIFICULDADES (dúvidas que não
conseguiram resolver, dados faltando, baselines incertos) e IDEIAS de aprimoramento.

- Fonte da verdade: tabela `lex_feedback` (data/compliance.db) — append-only com flag `resolvido`.
- Espelho legível: nota do vault `~/vault/aprendizados/lex-jfn-feedback.md`, REGERADA a cada run
  a partir do que está ABERTO — é o que o Claude Code lê no início de cada sessão.

Modos:
  registrar(fonte, tipo, contexto, mensagem, sugestao)  → uma entrada (dedup por fonte+tipo+mensagem aberta)
  coletar_auto()                                         → deriva dificuldades/ideias SEM LLM (determinístico)
                                                           de lex_pesquisa (inconclusivos) + memoria_aprendizado (baixa confiança)

CLI:
  python -m tools.lex_feedback --auto                    # roda no fim do sweep (cron); custo ZERO de LLM
  python -m tools.lex_feedback --registrar --fonte lex --tipo dificuldade --contexto "..." --msg "..." [--sugestao "..."]
  python -m tools.lex_feedback --listar                  # imprime as pendências abertas
"""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "compliance.db")
VAULT_NOTE = os.path.expanduser("~/vault/aprendizados/lex-jfn-feedback.md")

TIPOS = {"dificuldade", "ideia"}


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute(
        """CREATE TABLE IF NOT EXISTS lex_feedback (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            em         TEXT,
            fonte      TEXT,     -- 'lex' | 'jfn'
            tipo       TEXT,     -- 'dificuldade' | 'ideia'
            contexto   TEXT,     -- onde/quando (cnpj, etapa, tabela...)
            mensagem   TEXT,     -- a dificuldade/ideia em si
            sugestao   TEXT,     -- proposta de aprimoramento (opcional)
            resolvido  INTEGER DEFAULT 0,
            resolvido_em TEXT
        )"""
    )
    return con


def _agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def registrar(fonte: str, tipo: str, contexto: str, mensagem: str, sugestao: str | None = None) -> bool:
    """Registra uma dificuldade/ideia. Dedup: ignora se já existe ABERTA igual. Retorna True se inseriu."""
    fonte = (fonte or "jfn").strip().lower()
    tipo = (tipo or "dificuldade").strip().lower()
    if tipo not in TIPOS:
        tipo = "dificuldade"
    mensagem = (mensagem or "").strip()
    if not mensagem:
        return False
    con = _con()
    try:
        dup = con.execute(
            "SELECT 1 FROM lex_feedback WHERE resolvido=0 AND fonte=? AND tipo=? AND mensagem=? LIMIT 1",
            (fonte, tipo, mensagem),
        ).fetchone()
        if dup:
            return False
        con.execute(
            "INSERT INTO lex_feedback (em, fonte, tipo, contexto, mensagem, sugestao) VALUES (?,?,?,?,?,?)",
            (_agora(), fonte, tipo, (contexto or "").strip(), mensagem, (sugestao or "").strip() or None),
        )
        con.commit()
        return True
    finally:
        con.close()


def coletar_auto() -> int:
    """Deriva dificuldades/ideias do estado atual do banco — SEM LLM. Retorna nº de itens novos."""
    con = _con()
    novos = 0
    try:
        # 1) lex_pesquisa: dúvidas INCONCLUSIVAS = o Lex não conseguiu fechar (falta fonte/dado).
        try:
            rows = con.execute("SELECT fornecedor_nome, achados FROM lex_pesquisa WHERE achados IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            rows = []
        inconclusivos: list[str] = []
        n_forn = 0
        for nome, achados_json in rows:
            try:
                achados = json.loads(achados_json) if achados_json else []
            except Exception:
                continue
            faltas = [a.get("duvida", "?") for a in achados if str(a.get("veredito", "")).lower() == "inconclusivo"]
            if faltas:
                n_forn += 1
                for d in faltas[:2]:
                    inconclusivos.append(f"{nome or '?'}: {d}")
        if inconclusivos:
            exemplos = "; ".join(inconclusivos[:5])
            if registrar(
                "lex", "dificuldade",
                contexto="lex_pesquisa_internet (vereditos inconclusivos)",
                mensagem=f"{len(inconclusivos)} dúvida(s) inconclusiva(s) em {n_forn} fornecedor(es) — faltou fonte/dado p/ fechar. Ex.: {exemplos}",
                sugestao="Adicionar fontes (Diário Oficial municipal, JUCERJA, processos TJ) ou marcar p/ verificação manual quando o tema se repetir.",
            ):
                novos += 1

        # 2) memoria_aprendizado: baselines de BAIXA confiança ou poucas observações = incerteza.
        try:
            fracos = con.execute(
                "SELECT categoria, chave, confianca, n_observacoes FROM memoria_aprendizado "
                "WHERE (confianca IS NOT NULL AND confianca < 0.6) OR (n_observacoes IS NOT NULL AND n_observacoes < 3) "
                "ORDER BY confianca ASC LIMIT 8"
            ).fetchall()
        except sqlite3.OperationalError:
            fracos = []
        if fracos:
            itens = "; ".join(f"{c}/{k} (conf={cf}, n={n})" for c, k, cf, n in fracos[:5])
            if registrar(
                "lex", "dificuldade",
                contexto="memoria_aprendizado (baselines incertos)",
                mensagem=f"{len(fracos)} baseline(s) empírico(s) com baixa confiança/poucas observações: {itens}",
                sugestao="Ampliar a amostra (mais órgãos/exercícios) antes de usar esses baselines como régua.",
            ):
                novos += 1
    finally:
        con.close()
    _regenerar_vault()
    return novos


def _abertas(con: sqlite3.Connection) -> list[tuple]:
    return con.execute(
        "SELECT em, fonte, tipo, contexto, mensagem, sugestao FROM lex_feedback WHERE resolvido=0 ORDER BY tipo, em DESC"
    ).fetchall()


def _regenerar_vault() -> None:
    """Reescreve a nota do vault a partir das pendências ABERTAS — é o que o Claude Code lê."""
    con = _con()
    try:
        abertas = _abertas(con)
    finally:
        con.close()
    hoje = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    difs = [r for r in abertas if r[2] == "dificuldade"]
    ideias = [r for r in abertas if r[2] == "ideia"]
    L = [
        "---",
        "tipo: aprendizado",
        "projeto: ecossistema",
        "tags: [lex, jfn, feedback, dificuldade, ideia, aprimoramento]",
        f"atualizado: {hoje}",
        "---",
        "",
        "# Lex/JFN → Claude Code — dificuldades e ideias",
        "",
        "> Canal automático: o Lex e o JFN registram aqui o que NÃO conseguiram resolver e ideias de aprimoramento.",
        f"> Regerado a cada sweep por `tools.lex_feedback --auto`. **{len(difs)} dificuldade(s)**, **{len(ideias)} ideia(s)** abertas.",
        "> Resolver um item: `UPDATE lex_feedback SET resolvido=1, resolvido_em=... WHERE id=...` (ou via tool).",
        "",
    ]
    def bloco(titulo: str, rows: list[tuple]) -> None:
        L.append(f"## {titulo}")
        if not rows:
            L.append("_(nenhuma no momento)_")
            L.append("")
            return
        for em, fonte, _tipo, contexto, msg, sug in rows:
            dia = (em or "")[:10]
            L.append(f"- **[{fonte}]** {msg}")
            if contexto:
                L.append(f"  - contexto: {contexto}")
            if sug:
                L.append(f"  - 💡 ideia: {sug}")
            L.append(f"  - _{dia}_")
        L.append("")
    bloco("🔴 Dificuldades (Lex/JFN não fecharam)", difs)
    bloco("💡 Ideias de aprimoramento", ideias)
    os.makedirs(os.path.dirname(VAULT_NOTE), exist_ok=True)
    with open(VAULT_NOTE, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Canal de feedback Lex/JFN → Claude Code")
    ap.add_argument("--auto", action="store_true", help="deriva dificuldades/ideias do banco (sem LLM) e regenera a nota")
    ap.add_argument("--registrar", action="store_true", help="registra uma entrada manual")
    ap.add_argument("--listar", action="store_true", help="imprime as pendências abertas")
    ap.add_argument("--fonte", default="jfn")
    ap.add_argument("--tipo", default="dificuldade")
    ap.add_argument("--contexto", default="")
    ap.add_argument("--msg", default="")
    ap.add_argument("--sugestao", default="")
    a = ap.parse_args()
    if a.registrar:
        ok = registrar(a.fonte, a.tipo, a.contexto, a.msg, a.sugestao)
        _regenerar_vault()
        print("registrado" if ok else "ignorado (vazio ou duplicado)")
    elif a.auto:
        n = coletar_auto()
        print(f"lex_feedback --auto: {n} item(ns) novo(s); nota regenerada em {VAULT_NOTE}")
    elif a.listar:
        con = _con()
        try:
            for em, fonte, tipo, contexto, msg, sug in _abertas(con):
                print(f"[{(em or '')[:10]}] ({fonte}/{tipo}) {msg}" + (f"  💡 {sug}" if sug else ""))
        finally:
            con.close()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
