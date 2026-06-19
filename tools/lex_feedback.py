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


# ── typology store: tags + keywords determinísticos (custo LLM 0) ──
# cada tipologia de fraude → keywords que a identificam no texto de dúvidas/red flags/resumos.
_TIPOLOGIAS = {
    "fachada": ["fachada", "sede", "endereco residencial", "endereço residencial", "sem negocio",
                "sem negócio", "inexistencia de fato", "inexistência de fato", "terreno baldio", "noteshell"],
    "laranja_socio_compartilhado": ["laranja", "socio compartilhad", "sócio compartilhad", "interposi",
                                     "mesmo socio", "mesmo sócio", "qsa", "socios em comum", "sócios em comum",
                                     "veiculo societario", "veículo societário"],
    "concorrencia_ficticia": ["concorrencia ficticia", "concorrência fictícia", "rodizio", "rodízio",
                              "cartel", "conluio", "co-ocorrencia", "co-ocorrência", "mesmos competidores"],
    "exigencia_restritiva": ["exigencia restritiva", "exigência restritiva", "direcionament", "restringe",
                             "clausula restritiva", "cláusula restritiva", "marca especifica", "marca específica"],
    "fracionamento": ["fracionament", "dispensa", "abaixo do limite", "multiplas compras", "múltiplas compras",
                      "split", "limite de dispensa"],
    "sobrepreco": ["sobrepreco", "sobrepreço", "superfaturament", "preco acima", "preço acima",
                   "valor redondo", "preco de mercado", "preço de mercado"],
}


def _classificar_tipologia(texto: str) -> list[str]:
    """Mapeia um texto (dúvida/red flag/resumo) → tags de tipologia por keyword determinístico (sem LLM)."""
    t = (texto or "").lower()
    return [tag for tag, kws in _TIPOLOGIAS.items() if any(k in t for k in kws)]


def coletar_auto() -> int:
    """Deriva dificuldades/ideias do estado atual do banco — SEM LLM. Retorna nº de itens novos."""
    con = _con()
    novos = 0
    # acumula sinais por tipologia p/ PROMOVER ao typology store (memoria padrao_fraude) — feito FORA do
    # lock da conexão sqlite (memoria usa SQLAlchemy na MESMA db); aqui só LEMOS e agregamos.
    tipologia_sinais: dict[str, dict] = {}

    def _acc_tip(texto: str, exemplo: str) -> None:
        for tag in _classificar_tipologia(texto):
            d = tipologia_sinais.setdefault(tag, {"n": 0, "exemplos": []})
            d["n"] += 1
            ex = (exemplo or "").strip()
            if ex and ex not in d["exemplos"] and len(d["exemplos"]) < 3:
                d["exemplos"].append(ex[:160])

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
            # PROMOÇÃO ao typology store: achados que AGRAVAM viram padrão de fraude por tipologia (det.).
            for a in achados:
                if str(a.get("veredito", "")).lower() == "agrava":
                    duvida = str(a.get("duvida", ""))
                    _acc_tip(duvida + " " + str(a.get("nota", "")), f"{nome or '?'}: {duvida}")
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

        # 3) sei_direcionamento: pareceres LLM AMARELO/VERMELHO → promovem padrão por tipologia (det.).
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(sei_direcionamento)")} \
                if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND "
                               "name='sei_direcionamento'").fetchone() else set()
            if {"llm_grau", "llm_resumo"} <= cols:
                rf = ", red_flags" if "red_flags" in cols else ""
                drows = con.execute(
                    f"SELECT fornecedor_nome, llm_grau, llm_resumo{rf} FROM sei_direcionamento "
                    "WHERE llm_grau IS NOT NULL AND lower(llm_grau) IN "
                    "('amarelo','vermelho','amarela','vermelha')").fetchall()
            else:
                drows = []
        except sqlite3.OperationalError:
            drows = []
        for row in drows:
            dnome, dgrau, dresumo = row[0], row[1], row[2]
            base = str(dresumo or "")
            if len(row) > 3 and row[3]:
                base += " " + str(row[3])
            _acc_tip(base, f"{dnome or '?'} ({str(dgrau).upper()}): {base[:120]}")
    finally:
        con.close()

    # PROMOÇÃO ao typology store — FORA do lock sqlite (memoria usa SQLAlchemy na mesma db). Custo LLM 0.
    if tipologia_sinais:
        try:
            from compliance_agent.llm import memoria
            _leis = {
                "fachada": "CF art.70-71 (fiscalização); L14.133 art.14/156; sede inexistente = indício de interposição.",
                "laranja_socio_compartilhado": "Súmula Vinc.13 STF (parentesco); interposição de pessoas; sócios/veículos comuns entre fornecedores.",
                "concorrencia_ficticia": "L14.133 art.337-F CP (frustrar caráter competitivo); rodízio/conluio entre licitantes.",
                "exigencia_restritiva": "L14.133 art.9/37 (vedação a cláusula restritiva); CP art.337-E (contratação direta indevida).",
                "fracionamento": "L14.133 art.75 §1º (veda fracionar p/ fugir do limite de dispensa).",
                "sobrepreco": "L14.133 art.6 LIX/art.59 (sobrepreço/superfaturamento); pesquisa de preços obrigatória.",
            }
            for tag, d in tipologia_sinais.items():
                exemplos = "; ".join(d.get("exemplos") or [])
                valor = (f"Padrão '{tag}' observado em {d.get('n', 0)} sinal(is) (achado agrava / parecer "
                         f"amarelo-vermelho). Exemplos: {exemplos or '—'}. Base legal: {_leis.get(tag, '—')} "
                         "Indício a verificar, não acusação.")
                try:
                    memoria.aprender("padrao_fraude", tag, valor, fonte="lex", delta_confianca=0.1)
                except Exception:  # noqa: BLE001 — promoção é best-effort; não derruba o feedback
                    pass
        except Exception:  # noqa: BLE001
            pass

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
