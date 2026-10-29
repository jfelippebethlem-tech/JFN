"""lex_execucao — o Lex avalia a EXECUÇÃO do contrato a partir do processo SEI de pagamento.

Pergunta central do dono: o contrato foi REALMENTE cumprido, ou estão tentando burlar o controle
interno? Checa, por processo (ficha SEI já capturada em `sei_ficha`):
  1. Tem PRESTAÇÃO DE CONTAS adequada?
  2. Tem FISCALIZAÇÃO com RELATÓRIO FOTOGRÁFICO?
  3. A evidência é COERENTE com o objeto e a QUANTIDADE contratada?
     (ex.: 100.000 livros "comprovados" com foto de 1 caixa = fisicamente implausível → indício)

Regra de ouro JFN: **stepfun = coletar/indexar; gemini = analisar.** Esta é ANÁLISE → Gemini
(`direcionamento_cerebro.gerar_sync`). Honestidade: indício ≠ acusação; INDISPONÍVEL ≠ irregular;
presunção de legitimidade; nunca inventar fato.

Fonte: tabela `sei_ficha` (objeto, documentos[{tipo,ponto}], valores, red_flags). Persiste em
`lex_execucao` e alimenta o canal `lex_feedback` quando a execução é frágil/duvidosa.

CLI:
  python -m tools.lex_execucao --top 5            # avalia as N fichas com mais docs ainda não avaliadas
  python -m tools.lex_execucao --processo SEI-...  # uma específica
  python -m tools.lex_execucao --reavaliar --top 5 # ignora cache de avaliação
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sqlite3
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "compliance.db")

# Termos que denunciam a presença de cada tipo de evidência de execução (sobre tipo+ponto do doc).
_SINAIS = {
    "prestacao_contas": ["presta", "comprova"],
    "fiscalizacao": ["fiscaliza", "fiscal de contrato", "gestor do contrato"],
    "relatorio_fotografico": ["fotograf", "registro fotográfico", "reportagem fotográfica"],
    "atesto_recebimento": ["atesto", "atestad", "recebiment", "termo de recebimento", "aceite"],
    "nota_fiscal": ["nota fiscal", "nfe", "nf-e", "danfe"],
    "medicao": ["medi", "boletim de medi"],
}

_SYS = (
    "Você é AUDITOR DE CONTROLE EXTERNO (TCE-RJ) avaliando se a EXECUÇÃO de um contrato público foi "
    "efetivamente comprovada no processo de pagamento, ou se há tentativa de burlar o controle interno. "
    "Avalie SOMENTE com base nos documentos listados (tipo + ponto) e no objeto/valor informados. "
    "Regras ABSOLUTAS: (1) indício ≠ acusação — fale 'indício a verificar', presunção de legitimidade. "
    "(2) INDISPONÍVEL ≠ irregular: a AUSÊNCIA de um documento é uma FRAGILIDADE a verificar, não prova de fraude. "
    "(3) Nunca invente documento ou fato que não esteja na lista. (4) Foque a COERÊNCIA FÍSICA entre o objeto/"
    "quantidade contratado e a evidência: quantidades grandes exigem evidência condizente (medição, recebimento "
    "detalhado, múltiplos registros) — uma única foto/atesto genérico NÃO comprova entrega de grande volume "
    "(ex.: 100.000 livros não cabem numa caixa). "
    "(5) CALIBRE A NOTA (0-10) PELO RISCO REAL, não pela completude da captura: reserve 7-10 APENAS para "
    "incoerência física (volume×evidência) OU achado material PRESENTE nos documentos (e-mail pessoal/@gmail "
    "em ato oficial, valor redondo/incompatível, documento contraditório, fornecedor sancionado); a mera "
    "AUSÊNCIA de NF/atesto/medição/OB NÃO justifica nota ≥7. "
    "(6) ÁRVORE RASA = NÃO PERICIÁVEL: se os documentos são poucos e só de abertura/encerramento (nota de "
    "empenho, recibo de envio ao TCE-RJ, despacho de encaminhamento) SEM a fase de execução, então a árvore "
    "não foi coletada — responda execucao_comprovada='indeterminado', coerencia='indeterminado', nota ≤4 e "
    "registre em 'duvidas' que a árvore de contratação precisa ser re-coletada (captura incompleta ≠ irregularidade). "
    "(7) CONTRATO RECENTE: empenho de poucas semanas não pode ter documentos de execução pós-entrega; não "
    "trate ausência por recência como risco. "
    "(8) PAGAMENTO = SIAFE: a Ordem Bancária vive no SIAFE, não na pasta do SEI. Se o bloco 'PAGAMENTO NO SIAFE' "
    "traz OB contabilizada, o pagamento ESTÁ registrado na fonte oficial — NUNCA aponte 'ausência de OB'; a "
    "pergunta passa a ser se a ENTREGA que justificou esse pagamento está comprovada. Se o bloco diz que não "
    "localizou OB, isso é INDISPONÍVEL (o processo pode estar sob outra numeração), não ausência de pagamento. "
    "Responda SOMENTE o objeto JSON do schema, sem texto fora."
)
_SCHEMA = (
    '{"execucao_comprovada":"sim|parcial|nao|indeterminado",'
    '"coerencia_objeto_evidencia":"coerente|insuficiente|incoerente|indeterminado",'
    '"indicios":["indício a verificar (cite o doc/lacuna)"],'
    '"duvidas":["dúvida aberta para fiscalização/pesquisa"],'
    '"nota_risco_execucao": 0,'
    '"resumo":"1-3 frases (indício, não acusação)"}'
)


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute(
        """CREATE TABLE IF NOT EXISTS lex_execucao (
            numero_sei TEXT PRIMARY KEY,
            objeto TEXT,
            tem_prestacao_contas INTEGER, tem_fiscalizacao INTEGER, tem_relatorio_fotografico INTEGER,
            tem_atesto_recebimento INTEGER, tem_nota_fiscal INTEGER, tem_medicao INTEGER,
            execucao_comprovada TEXT, coerencia TEXT, nota_risco INTEGER,
            indicios TEXT, duvidas TEXT, resumo TEXT, modelo TEXT, em TEXT
        )"""
    )
    return con


def _agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _flags(documentos: list[dict]) -> dict:
    blob = " ".join(f"{d.get('tipo','')} {d.get('ponto','')}" for d in documentos if isinstance(d, dict)).lower()
    return {k: int(any(t in blob for t in termos)) for k, termos in _SINAIS.items()}


def _parse_json(txt: str) -> dict | None:
    txt = (txt or "").strip()
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j < 0:
        return None
    try:
        return json.loads(txt[i : j + 1])
    except Exception:
        return None


_REGRAS_CACHE: list[str] | None = None


def _regras_calibracao() -> str:
    """Reinjeta as lições de perícia aprendidas (memoria 'metodo', chave 'pericia:*') — as MESMAS que o
    sei_ficha já injeta — para o scorer de execução também aprender a calibrar. Best-effort (cacheado)."""
    global _REGRAS_CACHE
    if _REGRAS_CACHE is None:
        try:
            from compliance_agent.llm.memoria import lembrar
            regras = lembrar("metodo", chave="pericia", min_confianca=0.0) or []
            _REGRAS_CACHE = [(r.get("valor") or "")[:240] for r in regras[:16] if r.get("valor")]
        except Exception:
            _REGRAS_CACHE = []
    return "\n".join(f"- {x}" for x in _REGRAS_CACHE) or "(sem lições registradas)"


def _chave_processo(p: str | None) -> str | None:
    """'SEI-330002/031566/24', 'sei-330002/31566/2024' e '330002/031566/2024' são o MESMO processo."""
    m = re.search(r"(\d{6})\s*/\s*0*(\d+)(?:-\d)?\s*/\s*(\d{4}|\d{2})(?!\d)", p or "")
    if not m:
        return None
    ano = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
    return f"{m.group(1)}/{int(m.group(2))}/{ano}"


def mapa_obs_siafe(con: sqlite3.Connection, processos: list[str]) -> dict[str, dict]:
    """OBs CONTABILIZADAS no SIAFE por processo — UMA varredura por lote (a busca por processo custava 8 s).

    Medido em 29/10/2026: 550 dos 666 processos em que a perícia de execução apontou 'ausência de Ordem
    Bancária' têm OB contabilizada no SIAFE. A perícia lia só a pasta do SEI; a OB não mora lá."""
    alvo = {k for k in map(_chave_processo, processos) if k}
    out: dict[str, dict] = {}
    if not alvo:
        return out
    try:
        rows = con.execute("SELECT processo, valor, data_emissao FROM ob_orcamentaria_siafe "
                           "WHERE status='Contabilizado' AND processo LIKE '%/%'")
    except sqlite3.OperationalError:
        return out                                     # base sem SIAFE: o bloco diz INDISPONÍVEL
    for proc, valor, data in rows:
        k = _chave_processo(proc)
        if k in alvo:
            d = out.setdefault(k, {"n": 0, "total": 0.0, "datas": []})
            d["n"] += 1; d["total"] += valor or 0; d["datas"].append(str(data or ""))
    return out


def _bloco_siafe(numero_sei: str, obs: dict | None) -> str:
    if obs is None:
        return "PAGAMENTO NO SIAFE: (não consultado nesta execução — INDISPONÍVEL)\n"
    d = obs.get(_chave_processo(numero_sei) or "")
    if not d:
        return ("PAGAMENTO NO SIAFE: nenhuma OB contabilizada localizada pelo nº deste processo — INDISPONÍVEL "
                "(pode estar sob outra numeração), não prova de ausência de pagamento.\n")
    total = f"{d['total']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    # data_emissao do SIAFE é TEXTO DD/MM/AAAA: ordenar como string punha 17/01/2025 antes de 03/12/2024
    ds = sorted((x for x in d["datas"] if x), key=lambda s: s[6:10] + s[3:5] + s[0:2])
    periodo = f", emitidas de {ds[0]} a {ds[-1]}" if ds else ""
    return (f"PAGAMENTO NO SIAFE (fonte oficial da OB): {d['n']} OB(s) contabilizada(s), total R$ {total}{periodo}. "
            "O pagamento está registrado — avalie se a ENTREGA está comprovada.\n")


def avaliar_processo(con: sqlite3.Connection, numero_sei: str, objeto: str, valores: str,
                     documentos: list[dict], red_flags: list, gerar, obs_siafe: dict | None = None) -> dict | None:
    fl = _flags(documentos)
    docs_txt = "\n".join(f"- [{d.get('tipo','?')}] {d.get('ponto','')}" for d in documentos[:40] if isinstance(d, dict))
    prompt = (
        f"OBJETO CONTRATADO: {objeto or '(não informado na ficha)'}\n"
        f"VALORES: {valores or '(n/d)'}\n"
        f"RED FLAGS já anotadas: {red_flags or '[]'}\n"
        f"{_bloco_siafe(numero_sei, obs_siafe)}"
        f"PRESENÇA DETECTADA (1=sim): {fl}\n\n"
        f"DOCUMENTOS DO PROCESSO ({len(documentos)}):\n{docs_txt or '(nenhum doc inventariado)'}\n\n"
        f"LIÇÕES DE CALIBRAÇÃO DA PERÍCIA (aplique antes de pontuar):\n{_regras_calibracao()}\n\n"
        f"Avalie se a execução do contrato está comprovada e coerente com o objeto/quantidade. "
        f"Se a árvore é rasa (poucos docs, só empenho/envio-TCE/despacho, sem fase de execução), é captura "
        f"incompleta → 'indeterminado' e nota ≤4, NÃO risco alto. "
        f"Dê atenção à fiscalização/relatório fotográfico e à plausibilidade física da entrega. "
        f"Responda SOMENTE o JSON: {_SCHEMA}"
    )
    try:
        txt = gerar(prompt, _SYS, 60.0)
    except Exception as e:
        # TimeoutError do futuro (60 s) vem sem argumentos: str(e) == "" e o log
        # dizia só "erro LLM: ". O tipo é o que identifica a falha.
        print(f"  [{numero_sei}] erro LLM: {type(e).__name__}: {str(e)[:80]}")
        return None
    r = _parse_json(txt) or {}
    nota = r.get("nota_risco_execucao")
    try:
        nota = max(0, min(10, int(nota)))  # clamp 0-10: o LLM às vezes devolve fora de faixa/negativo
    except Exception:
        nota = None
    r["nota_risco_execucao"] = nota  # verdict devolvido carrega a nota CLAMPADA (o log lia a crua, ex. 75)
    try:
        from compliance_agent import direcionamento_cerebro as _dc
        modelo = _dc.ultimo_provedor or "desconhecido"
    except Exception:
        modelo = "desconhecido"
    con.execute(
        """INSERT INTO lex_execucao (numero_sei,objeto,tem_prestacao_contas,tem_fiscalizacao,
            tem_relatorio_fotografico,tem_atesto_recebimento,tem_nota_fiscal,tem_medicao,
            execucao_comprovada,coerencia,nota_risco,indicios,duvidas,resumo,modelo,em)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(numero_sei) DO UPDATE SET objeto=excluded.objeto,
            tem_prestacao_contas=excluded.tem_prestacao_contas, tem_fiscalizacao=excluded.tem_fiscalizacao,
            tem_relatorio_fotografico=excluded.tem_relatorio_fotografico,
            tem_atesto_recebimento=excluded.tem_atesto_recebimento, tem_nota_fiscal=excluded.tem_nota_fiscal,
            tem_medicao=excluded.tem_medicao, execucao_comprovada=excluded.execucao_comprovada,
            coerencia=excluded.coerencia, nota_risco=excluded.nota_risco, indicios=excluded.indicios,
            duvidas=excluded.duvidas, resumo=excluded.resumo, modelo=excluded.modelo, em=excluded.em""",
        (numero_sei, objeto, fl["prestacao_contas"], fl["fiscalizacao"], fl["relatorio_fotografico"],
         fl["atesto_recebimento"], fl["nota_fiscal"], fl["medicao"],
         r.get("execucao_comprovada"), r.get("coerencia_objeto_evidencia"), nota,
         json.dumps(r.get("indicios") or [], ensure_ascii=False),
         json.dumps(r.get("duvidas") or [], ensure_ascii=False),
         r.get("resumo"), modelo, _agora()),
    )
    con.commit()
    # Execução frágil NÃO vai mais para `lex_feedback`: é achado DE CASO e já está aqui em `lex_execucao` (é
    # daqui que a seção 1-G do relatório lê). Lá virava 1 item por processo — 2.400 dos 3.074 abertos em
    # 28/10/2026 — numa fila de dificuldades DO SISTEMA que ninguém consome por processo.
    return {"numero_sei": numero_sei, **fl, "verdict": r}


_NEGA_OB = re.compile(r"(aus[eê]ncia|sem|falta|n[aã]o h[aá]|inexist[eê]ncia)[^.;\"]{0,80}(ordem(ns)? banc|\bOBs?\b)", re.I)

# Vereditos dados ANTES de a perícia ver o SIAFE (29/10/2026) que acusaram falta de OB: refazer primeiro.
_CORTE_SIAFE = "2026-10-29T00:12"


def _contestados_por_siafe(con: sqlite3.Connection) -> list[str]:
    """Processos cujo veredito antigo apontou 'ausência de OB' e que TÊM OB contabilizada no SIAFE."""
    try:
        rows = con.execute(
            "SELECT numero_sei, COALESCE(indicios,'') || ' ' || COALESCE(resumo,'') FROM lex_execucao "
            "WHERE em < ? AND (indicios LIKE '%Ordem Banc%' OR indicios LIKE '%OB%' OR resumo LIKE '%Ordem Banc%') "
            "ORDER BY nota_risco DESC", (_CORTE_SIAFE,)).fetchall()
    except sqlite3.OperationalError:
        return []
    # só quem AFIRMOU ausência — "divergência na ordem bancária de retenção" leu a OB, não a negou
    cand = [ns for ns, txt in rows if _NEGA_OB.search(txt)]
    m = mapa_obs_siafe(con, cand) if cand else {}
    return [ns for ns in cand if _chave_processo(ns) in m]


def _alvos(con: sqlite3.Connection, top: int, reavaliar: bool) -> list[tuple]:
    ja = set()
    if not reavaliar:
        ja = {r[0] for r in con.execute("SELECT numero_sei FROM lex_execucao")}
    # mesmo ritmo do slot (top por rodada): só a ORDEM muda — veredito errado vale mais que cobertura nova
    primeiro = set(_contestados_por_siafe(con)[:top]) if not reavaliar else set()
    ja -= primeiro
    rows = con.execute(
        "SELECT numero_sei, objeto, valores, documentos, red_flags FROM sei_ficha "
        "WHERE n_docs > 0 ORDER BY n_docs DESC"
    ).fetchall()
    rows.sort(key=lambda r: r[0] not in primeiro)      # estável: contestados na frente, resto na ordem de n_docs
    out = []
    for ns, obj, val, docs, rf in rows:
        if ns in ja:
            continue
        try:
            dl = json.loads(docs) if docs else []
        except Exception:
            dl = []
        if not isinstance(dl, list):
            dl = []
        try:
            rfl = json.loads(rf) if rf else []
        except Exception:
            rfl = []
        out.append((ns, obj or "", val or "", dl, rfl))
        if len(out) >= top:
            break
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Lex avalia a execução do contrato (processo SEI)")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--processo", type=str, default=None)
    ap.add_argument("--reavaliar", action="store_true")
    a = ap.parse_args()
    from compliance_agent.direcionamento_cerebro import gerar_sync
    con = _con()
    try:
        if a.processo:
            row = con.execute(
                "SELECT numero_sei,objeto,valores,documentos,red_flags FROM sei_ficha WHERE numero_sei=?",
                (a.processo,),
            ).fetchone()
            if not row:
                print(f"ficha não encontrada: {a.processo}")
                return
            ns, obj, val, docs, rf = row
            dl = json.loads(docs) if docs else []
            rfl = json.loads(rf) if rf else []
            alvos = [(ns, obj or "", val or "", dl if isinstance(dl, list) else [], rfl)]
        else:
            alvos = _alvos(con, a.top, a.reavaliar)
        if not alvos:
            print("nada a avaliar (todas as fichas com docs já avaliadas; use --reavaliar).")
            return
        print(f"avaliando execução de {len(alvos)} processo(s) via cadeia LLM (gemini→groq→cerebras→extra)…")
        obs = mapa_obs_siafe(con, [x[0] for x in alvos])
        for ns, obj, val, dl, rfl in alvos:
            try:
                res = avaliar_processo(con, ns, obj, val, dl, rfl, gerar_sync, obs)
            except sqlite3.OperationalError as e:
                # write-lock alheio (sweeps concorrentes) não pode abortar o lote e
                # jogar fora os pareceres de LLM já gastos dos demais processos.
                print(f"  [{ns}] banco ocupado ({e}) — segue para o próximo")
                continue
            if res:
                v = res["verdict"]
                print(f"  {ns}: execução={v.get('execucao_comprovada','?')} coerência={v.get('coerencia_objeto_evidencia','?')} "
                      f"risco={v.get('nota_risco_execucao','?')} | foto={res['relatorio_fotografico']} fisc={res['fiscalizacao']} presta={res['prestacao_contas']}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
