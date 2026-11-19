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
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone


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
    "A OB costuma ser o valor LÍQUIDO: bruto da NF/NL menos as retenções (guias de recolhimento de tributo). "
    "FAÇA A CONTA antes de chamar diferença de 'discrepância' — bruto − guias = OB é pagamento regular. "
    "(9) FONTES QUE ENGANAM (medido 18/11/2026 em 5 de 9 laudos de risco alto conferidos na fonte): "
    "(a) a PUBLICAÇÃO do DOERJ juntada traz a página inteira — só vale o ato que cita ESTE processo/valor; atos "
    "vizinhos (outra unidade, outra empresa, outro TAC) NÃO são divergência; (b) o OBJETO do resumo pode ser "
    "impreciso — se contradiz a nota de empenho/NF, vale a NE (natureza de despesa) e a NF, e não há contradição; "
    "(c) número com dígito trocado/ilegível no texto de NF é provável OCR — confira contra o quadro de apuração/NL "
    "antes de apontar diferença de valor; (d) documento 'CANCELADO' acompanhado de termo de cancelamento e "
    "documento substituto é substituição regular; (e) a PESQUISA DE PREÇOS cita contratos de OUTROS órgãos e "
    "empresas como referência — fornecedor, unidade ou município dela não é divergência com este processo. "
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
    # 120 s (era 30): o parecer já foi PAGO (assinatura/cascata) quando a gravação acontece; perder por trava de
    # escrita alheia é jogar fora a chamada — 9 de 10 num ciclo de 14/11/2026.
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
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
# Lições da rubrica: as do CAMPEÃO do autoaprimoramento (`data/autoaprimoramento/campeao.json`, só entra lá o que
# passou no portão determinístico e na sombra — docs/AUTOAPRIMORAMENTO-JFN.md). `_LICOES_SOMBRA` troca essa lista
# durante a reexecução de um desafiante (compliance_agent/autoaprimoramento/reexecucao.py); None = produção.
_LICOES_SOMBRA: list[str] | None = None


def _licoes_da_rubrica() -> list[str]:
    if _LICOES_SOMBRA is not None:
        return list(_LICOES_SOMBRA)
    try:
        from compliance_agent.autoaprimoramento.registro import licoes_do_campeao
        return licoes_do_campeao()
    except ImportError:
        return []


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
    # as da rubrica vão PRIMEIRO (o meio de um prompt longo é o trecho menos lido)
    return "\n".join(f"- {x}" for x in _licoes_da_rubrica() + _REGRAS_CACHE) or "(sem lições registradas)"


def _chave_processo(p: str | None) -> str | None:
    """'SEI-330002/031566/24', 'sei-330002/31566/2024' e '330002/031566/2024' são o MESMO processo."""
    m = re.search(r"(\d{6})\s*/\s*0*(\d+)(?:-\d)?\s*/\s*(\d{4}|\d{2})(?!\d)", p or "")
    if not m:
        return None
    ano = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
    return f"{m.group(1)}/{int(m.group(2))}/{ano}"


def mapa_obs_siafe(con: sqlite3.Connection, processos: list[str], *, autos: bool = True) -> dict[str, dict]:
    """OBs PAGAS no SIAFE por processo — UMA varredura por lote (a busca por processo custava 8 s).

    Medido em 29/10/2026: 550 dos 666 processos em que a perícia de execução apontou 'ausência de Ordem
    Bancária' têm OB contabilizada no SIAFE. A perícia lia só a pasta do SEI; a OB não mora lá.
    18/11/2026: a ligação é por CAMADAS (`compliance_agent.ob_processo`): nº do processo (exato e normalizado) e
    NL/PD/OB juntadas nos autos, com a devolução (GD) descontada; cada OB traz a sua `via`. Formato mantido
    ({n, total, datas}) + `obs`, `por_via`, `piso`, `candidatas`, `nos_autos_fora_da_base`."""
    from compliance_agent.ob_processo import obs_por_processo
    return obs_por_processo(con, processos, autos=autos, so_pagos=True)


def _bloco_siafe(numero_sei: str, obs: dict | None) -> str:
    if obs is None:
        return "PAGAMENTO NO SIAFE: (não consultado nesta execução — INDISPONÍVEL)\n"
    d = obs.get(_chave_processo(numero_sei) or "")
    if not d or not d.get("n"):                         # só candidata/devolvida: nada pago a afirmar
        return ("PAGAMENTO NO SIAFE: nenhuma OB contabilizada localizada pelo nº deste processo — INDISPONÍVEL "
                "(pode estar sob outra numeração), não prova de ausência de pagamento.\n")
    total = f"{d['total']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    # data_emissao do SIAFE é TEXTO DD/MM/AAAA: ordenar como string punha 17/01/2025 antes de 03/12/2024
    ds = sorted((x for x in d["datas"] if x), key=lambda s: s[6:10] + s[3:5] + s[0:2])
    periodo = f", emitidas de {ds[0]} a {ds[-1]}" if ds else ""
    return (f"PAGAMENTO NO SIAFE (fonte oficial da OB): {d['n']} OB(s) contabilizada(s), total R$ {total}{periodo}. "
            f"{_ressalva_ob(d)}O pagamento está registrado — avalie se a ENTREGA está comprovada.\n")


def _ressalva_ob(d: dict) -> str:
    """De onde veio a soma além do nº do processo, e quando ela é só PISO (GD sem valor conhecido)."""
    from compliance_agent.ob_processo import resumo_auditavel
    vias = d.get("por_via") or {}
    r = f"Origem por via: {resumo_auditavel(d)}. " if set(vias) - {"processo_exato", "processo_normalizado"} else ""
    if d.get("piso"):
        r += "PISO: há OB com Guia de Devolução sem valor conhecido, fora da soma. "
    return r


# ── PRÉ-FILTRO DETERMINÍSTICO (11/11/2026) ───────────────────────────────────────────────────────────────
# A regra decide SE há execução a julgar; o LLM julga O TEXTO da peça. Medido: 2.020 de 4.839 vereditos
# (41,7%) eram "indeterminado", 1.314 deles com < 5 docs — sem atesto/medição/NF nos autos capturados não há
# o que o LLM avaliar, e a chamada era gasta para dizer isso. Tipos = vocabulário canônico de `sei/fases.py`.
TIPOS_EXECUCAO = ("aceite", "medicao", "nota_fiscal", "relatorio_fotografico", "fiscalizacao")
SEM_DOC_EXECUCAO = "sem_documento_execucao"
_TETO_TEXTO_DOC, _TETO_TEXTO_TOTAL = 4000, 12000


def evidencia_execucao(numero_sei: str, documentos: list[dict]) -> dict:
    """Há documento de execução? Fonte 1 = manifesto do `data/sei_arquivo` (36–71 docs por processo, com
    texto); fonte 2 (sem arquivo) = a ficha, classificada pelo MESMO `fases.classificar` (o regex `_SINAIS`
    casa "medi" em "medicamento"/"imediato" e não serve de árbitro). Devolve {tem, fonte, textos}."""
    from compliance_agent.sei import acervo_texto, fases, manifesto_norm
    man = manifesto_norm.carregar(numero_sei)
    if man is not None:
        norm = manifesto_norm.normalizar(man)
        exec_docs = [d for d in norm["docs"] if d.get("tipo") in TIPOS_EXECUCAO]
        textos, total = [], 0
        for d in exec_docs:
            if total >= _TETO_TEXTO_TOTAL:
                break
            t = acervo_texto.ler(man["_pasta"], d, min(_TETO_TEXTO_DOC, _TETO_TEXTO_TOTAL - total)).strip()
            if t:
                textos.append((d.get("tipo"), str(d.get("titulo") or "")[:120], t))
                total += len(t)
        return {"tem": bool(exec_docs), "fonte": "arquivo SEI", "textos": textos}
    tem = any(fases.classificar(f"{d.get('tipo', '')} {d.get('ponto', '')}")[1] in TIPOS_EXECUCAO
              for d in documentos if isinstance(d, dict))
    return {"tem": tem, "fonte": "ficha SEI (sem arquivo local)", "textos": []}


def _nota_0a10(v) -> int | None:
    """Nota de risco só na escala 0–10. Fora dela é REJEITADA (None), não clampada: medido 11/11/2026, 21 notas
    entre 70 e 100 — o clamp antigo fazia 75 virar 10, inventando risco máximo de uma escala desconhecida."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        m = re.fullmatch(r"\s*(-?\d+(?:[.,]\d+)?)\s*(?:/\s*10)?\s*", str(v))
        if not m:
            return None
        x = float(m.group(1).replace(",", "."))
    return int(round(x)) if 0 <= x <= 10 else None


def _exec_norm(v) -> str | None:
    """'Não'/'NAO'/' sim ' → vocabulário da coluna (2 linhas com 'não' acentuado contaminavam agregados)."""
    if not isinstance(v, str):
        return v
    import unicodedata
    t = unicodedata.normalize("NFKD", v.strip().lower()).encode("ascii", "ignore").decode()
    return t if t in ("sim", "parcial", "nao", "indeterminado") else v


def _gravar(con, numero_sei, objeto, fl, r, nota, modelo):
    # "database is locked" aqui jogava fora o parecer de LLM já gasto e o processo voltava à fila (38 vezes no log
    # até 14/11/2026): desfaz a transação (libera o snapshot WAL vencido) e tenta de novo antes de desistir.
    for tentativa in range(4):
        try:
            return _gravar_uma_vez(con, numero_sei, objeto, fl, r, nota, modelo)
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) and "busy" not in str(e) or tentativa == 3:
                raise
            con.rollback()
            time.sleep(3 * (tentativa + 1))


def _antes_de_regravar(con, numero_sei, modelo_novo, laudo_novo: dict | None = None) -> bool:
    """Toda regravação de laudo passa por aqui: a linha vigente vai para o ledger do autoaprimoramento (18/11/2026:
    de 72 laudos de agente conferidos na fonte primária, 51 foram regravados por juízo sobre o resumo e não havia
    onde achar o anterior). True = a linha vigente é PROVA PRIMÁRIA e o laudo novo não é: NÃO regravar."""
    try:
        from compliance_agent.autoaprimoramento import ledger
        cur = con.execute("SELECT execucao_comprovada, coerencia, nota_risco, indicios, duvidas, resumo, modelo, em "
                          "FROM lex_execucao WHERE numero_sei=?", (numero_sei,))
        ant = cur.fetchone()
        if not ant:
            return False
        return ledger.antes_de_regravar(numero_sei, dict(zip([d[0] for d in cur.description], ant)), modelo_novo,
                                        laudo_novo)
    except (ImportError, sqlite3.Error):
        return False


def _gravar_uma_vez(con, numero_sei, objeto, fl, r, nota, modelo):
    if _antes_de_regravar(con, numero_sei, modelo, {**r, "nota_risco": nota}):
        print(f"  [{numero_sei}] laudo conferido na fonte primária — o de {modelo} foi para o ledger, não regrava")
        return
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


def aplicar_conferencia(item: str, resposta: str, modelo: str, concorda, con: sqlite3.Connection | None = None) -> bool:
    """Aplicador da fila de conferência do Opus (`llm/conferencia_opus.APLICADORES`): o parecer do processo foi
    feito por outro modelo enquanto o Claude da assinatura não respondia e o Opus releu a MESMA entrada.
    Concordou ⇒ só a proveniência muda; divergiu ⇒ o veredito do Opus substitui o gravado (o anterior fica na
    fila e no cruzamento). Resposta do Opus sem veredito válido nunca sobrescreve (mesma regra do upsert)."""
    if not str(item or "").startswith("sei:"):
        return False
    numero_sei = item[4:]
    proprio = con is None
    con = con or _con()
    try:
        ant = con.execute("SELECT modelo FROM lex_execucao WHERE numero_sei=?", (numero_sei,)).fetchone()
        if not ant:
            return False
        if _antes_de_regravar(con, numero_sei, modelo, _parse_json(resposta)):
            return False             # prova primária não é regravada por conferência sobre o resumo
        antes = (ant[0] or "desconhecido").split(" · conferido")[0]
        r = _parse_json(resposta) or {}
        r["execucao_comprovada"] = _exec_norm(r.get("execucao_comprovada"))
        if r.get("execucao_comprovada") not in ("sim", "parcial", "nao", "indeterminado"):
            if concorda == 1:        # concordou mas a resposta não traz o laudo: só a proveniência muda
                con.execute("UPDATE lex_execucao SET modelo=? WHERE numero_sei=?",
                            (f"{antes} · conferido claude:{modelo}", numero_sei))
                con.commit()
                return True
            return False
        # Com laudo válido do Opus, o TEXTO dele substitui o anterior MESMO quando o nível coincide (18/11/2026:
        # SEI-260005/011066/2025 — nível alto nos dois, mas fundamentos diferentes; ficava VERIFICADO com o
        # fundamento que o Opus não endossou). A concordância só muda a anotação de proveniência.
        antes = f"concordou com {antes}" if concorda == 1 else f"antes {antes}"
        con.execute("UPDATE lex_execucao SET execucao_comprovada=?, coerencia=?, nota_risco=?, indicios=?, duvidas=?, "
                    "resumo=?, modelo=?, em=? WHERE numero_sei=?",
                    (r["execucao_comprovada"], r.get("coerencia_objeto_evidencia"), _nota_0a10(r.get("nota_risco_execucao")),
                     json.dumps(r.get("indicios") or [], ensure_ascii=False),
                     json.dumps(r.get("duvidas") or [], ensure_ascii=False), r.get("resumo"),
                     f"claude:{modelo} (conferência; {antes})"[:200], _agora(), numero_sei))
        con.commit()
        return True
    finally:
        if proprio:
            con.close()


def avaliar_processo(con: sqlite3.Connection, numero_sei: str, objeto: str, valores: str,
                     documentos: list[dict], red_flags: list, gerar, obs_siafe: dict | None = None) -> dict | None:
    fl = _flags(documentos)
    ev = evidencia_execucao(numero_sei, documentos)
    if not ev["tem"]:
        ant = con.execute("SELECT execucao_comprovada FROM lex_execucao WHERE numero_sei=?",
                          (numero_sei,)).fetchone() if con is not None else None
        if ant and ant[0] and ant[0] != SEM_DOC_EXECUCAO:
            # a regra não apaga juízo já dado sobre outro recorte; só não gasta LLM de novo
            print(f"  [{numero_sei}] sem documento de execução ({ev['fonte']}) — mantido o veredito anterior")
            if con is not None:
                _marcar_revisto_sem_doc(numero_sei)
            return None
        r = {"execucao_comprovada": SEM_DOC_EXECUCAO, "coerencia_objeto_evidencia": "indeterminado",
             "indicios": [],
             "duvidas": [f"Nenhum documento de execução (atesto, medição, nota fiscal, relatório fotográfico ou "
                         f"fiscalização) na {ev['fonte']}: captura a completar ou fragilidade a verificar — "
                         f"INDISPONÍVEL ≠ irregular."],
             "nota_risco_execucao": None,
             "resumo": "Sem documento de execução nos autos capturados; não submetido ao LLM (regra)."}
        if con is not None:
            _gravar(con, numero_sei, objeto, fl, r, None, "regra:sem_doc_execucao")
        return {"numero_sei": numero_sei, **fl, "verdict": r, "deterministico": True}
    bloco_texto = ""
    if ev["textos"]:
        bloco_texto = ("TEXTO DOS DOCUMENTOS DE EXECUÇÃO (íntegra capturada, cortada em "
                       f"{_TETO_TEXTO_DOC} caracteres por peça — julgue SOBRE ESTE TEXTO):\n"
                       + "\n".join(f"--- [{tp}] {tit} ---\n{tx}" for tp, tit, tx in ev["textos"])
                       + "\n--- FIM ---\n\n")
    docs_txt = "\n".join(f"- [{d.get('tipo','?')}] {d.get('ponto','')}" for d in documentos[:40] if isinstance(d, dict))
    prompt = (
        f"OBJETO CONTRATADO: {objeto or '(não informado na ficha)'}\n"
        f"VALORES: {valores or '(n/d)'}\n"
        f"RED FLAGS já anotadas: {red_flags or '[]'}\n"
        f"{_bloco_siafe(numero_sei, obs_siafe)}"
        f"PRESENÇA DETECTADA (1=sim): {fl}\n\n"
        f"DOCUMENTOS DO PROCESSO ({len(documentos)}):\n{docs_txt or '(nenhum doc inventariado)'}\n\n"
        f"{bloco_texto}"
        f"LIÇÕES DE CALIBRAÇÃO DA PERÍCIA (aplique antes de pontuar):\n{_regras_calibracao()}\n\n"
        f"Avalie se a execução do contrato está comprovada e coerente com o objeto/quantidade. "
        f"Se a árvore é rasa (poucos docs, só empenho/envio-TCE/despacho, sem fase de execução), é captura "
        f"incompleta → 'indeterminado' e nota ≤4, NÃO risco alto. "
        f"Dê atenção à fiscalização/relatório fotográfico e à plausibilidade física da entrega. "
        f"Responda SOMENTE o JSON: {_SCHEMA}"
    )
    try:
        try:   # `item` liga o parecer à fila de conferência do Opus (llm/conferencia_opus) quando sai sem o Claude
            txt = gerar(prompt, _SYS, 60.0, item=f"sei:{numero_sei}")
        except TypeError:          # gerar dublê/antigo sem `item`
            txt = gerar(prompt, _SYS, 60.0)
    except Exception as e:
        # TimeoutError do futuro (60 s) vem sem argumentos: str(e) == "" e o log
        # dizia só "erro LLM: ". O tipo é o que identifica a falha.
        print(f"  [{numero_sei}] erro LLM: {type(e).__name__}: {str(e)[:80]}")
        return None
    r = _parse_json(txt) or {}
    r["execucao_comprovada"] = _exec_norm(r.get("execucao_comprovada"))
    if r.get("execucao_comprovada") not in ("sim", "parcial", "nao", "indeterminado"):
        # resposta sem veredito NUNCA sobrescreve um veredito: o upsert gravava NULL por cima (medido em
        # 29/10/2026 no SEI-420001/004995/2025, ao reavaliar). Sem veredito anterior, a linha vazia segue
        # sendo gravada — ela marca a TENTATIVA, e `_alvos` só a refaz depois de 7 dias.
        ant = con.execute("SELECT execucao_comprovada FROM lex_execucao WHERE numero_sei=?", (numero_sei,)).fetchone()
        if ant and ant[0]:
            print(f"  [{numero_sei}] resposta do LLM sem veredito válido — mantido o anterior: {str(txt)[:120]!r}")
            return None
    bruta = r.get("nota_risco_execucao")
    nota = _nota_0a10(bruta)
    if nota is None and bruta is not None:
        r["duvidas"] = list(r.get("duvidas") or []) + [f"nota do LLM fora da escala 0–10 ({str(bruta)[:12]}) — descartada"]
    r["nota_risco_execucao"] = nota  # verdict devolvido carrega a nota VALIDADA (o log lia a crua, ex. 75)
    try:
        from compliance_agent import direcionamento_cerebro as _dc
        modelo = _dc.ultimo_provedor or "desconhecido"
        if getattr(_dc, "ultimo_modelo", "") and modelo == "gemini":
            modelo = f"gemini:{_dc.ultimo_modelo}"   # versão exata (3-flash-preview/3.6/3.5/2.5) p/ auditar regressão
        if modelo == "claude":   # co-motor: 'claude:<id> (+<modelo da cascata>)' — os dois vereditos no cruzamento
            from compliance_agent.llm.comotor import proveniencia
            modelo = proveniencia(f"claude:{getattr(_dc, 'ultimo_modelo', '')}")
    except Exception:
        modelo = "desconhecido"
    _gravar(con, numero_sei, objeto, fl, r, nota, modelo)
    # Execução frágil NÃO vai mais para `lex_feedback`: é achado DE CASO e já está aqui em `lex_execucao` (é
    # daqui que a seção 1-G do relatório lê). Lá virava 1 item por processo — 2.400 dos 3.074 abertos em
    # 28/10/2026 — numa fila de dificuldades DO SISTEMA que ninguém consome por processo.
    return {"numero_sei": numero_sei, **fl, "verdict": r}


# Precisão > cobertura (o relatório põe aviso em quem casa): medido em 29/10/2026, a janela de 80 caracteres
# pegava "ausência do valor da NL…, vinculada à mesma OB" e "'SEM CONTRATO' na Ordem Bancária" — leram a OB.
_NEGA_OB = re.compile(r"(aus[eê]ncia|sem|falta\w*|n[aã]o h[aá]|inexist[eê]ncia)\b"
                      r"(?:(?!pr[oó]pria|vinculad|conforme|valor|reten[çc]|contrato)[^.;\"]){0,60}?"
                      r"(ordem(ns)? banc|\bOBs?\b)(?! de reten)", re.I)

# Vereditos dados ANTES de a perícia ver o SIAFE (29/10/2026) que acusaram falta de OB: refazer primeiro.
_CORTE_SIAFE = "2026-10-29T00:12"


# Contestado sem documento de execução: o veredito anterior é mantido (a regra não apaga juízo) e a linha NÃO é
# regravada — por isso ele voltava ao topo da fila a cada rodada (~53 processos, medido 14/11/2026). Fica registrado
# aqui quando foi revisto e sai da fila de contestados por 30 dias (o sweep pode trazer o atesto nesse meio-tempo).
_REVISTOS_SEM_DOC = Path(__file__).resolve().parents[1] / "data" / "lex_contestados_sem_doc.json"
_DIAS_REVISTO = 30


def _revistos_sem_doc() -> dict:
    try:
        d = json.loads(_REVISTOS_SEM_DOC.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _marcar_revisto_sem_doc(numero_sei: str) -> None:
    d = _revistos_sem_doc()            # relê do disco antes de gravar (outra rodada pode ter marcado)
    d[numero_sei] = _agora()
    tmp = _REVISTOS_SEM_DOC.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_REVISTOS_SEM_DOC)


def _contestados_por_siafe(con: sqlite3.Connection) -> list[str]:
    """Processos cujo veredito antigo apontou 'ausência de OB' e que TÊM OB contabilizada no SIAFE (menos os já
    revistos sem documento de execução há menos de `_DIAS_REVISTO` dias)."""
    try:
        rows = con.execute(
            "SELECT numero_sei, COALESCE(indicios,'') || ' ' || COALESCE(resumo,'') FROM lex_execucao "
            "WHERE em < ? AND (indicios LIKE '%Ordem Banc%' OR indicios LIKE '%OB%' OR resumo LIKE '%Ordem Banc%') "
            "ORDER BY nota_risco DESC", (_CORTE_SIAFE,)).fetchall()
    except sqlite3.OperationalError:
        return []
    # só quem AFIRMOU ausência — "divergência na ordem bancária de retenção" leu a OB, não a negou
    corte_rev = (datetime.now() - timedelta(days=_DIAS_REVISTO)).strftime("%Y-%m-%dT%H:%M:%S")
    rev = {k for k, v in _revistos_sem_doc().items() if str(v) >= corte_rev}
    cand = [ns for ns, txt in rows if _NEGA_OB.search(txt) and ns not in rev]
    m = mapa_obs_siafe(con, cand) if cand else {}
    return [ns for ns in cand if _chave_processo(ns) in m]


# "Já avaliado" = tem veredito, OU tentou há menos de 7 dias. Veredito VAZIO (resposta do LLM cortada — 616 em
# 29/10/2026) não é avaliação: volta após 7 dias. Régua ÚNICA — o lex_bombeiros tinha a sua e contava o vazio
# como feito ("periciados nesta passada: 0", medido 11/11/2026).
# O veredito da REGRA ("sem_documento_execucao") é revisto após 30 dias: o sweep SEI pode ter capturado o atesto.
SQL_JA_AVALIADO = ("SELECT numero_sei FROM lex_execucao WHERE (execucao_comprovada IS NOT NULL "
                   "AND NOT (execucao_comprovada = 'sem_documento_execucao' "
                   "AND em < strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime', '-30 days'))) "
                   "OR em >= strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime', '-7 days')")


_ARQUIVO_SEI = Path(__file__).resolve().parents[1] / "data" / "sei_arquivo"


def _recapturados(con: sqlite3.Connection) -> list[str]:
    """Laudos dados ANTES da última captura do processo (manifesto do arquivo SEI mais novo que `em`): a perícia
    vê documentos que o laudo não viu. 18/11/2026: recaptura de 79 processos de risco alto sem documento de
    execução — 52 ganharam atesto/medição/NF, e nada refazia o laudo (SQL_JA_AVALIADO os excluía para sempre).
    Fora: laudo conferido à mão na fonte primária (sessão/agente Claude Code — a cascata não sobrescreve) e
    processo já revisto sem documento DEPOIS dessa captura (senão volta a cada rodada). Só o que pesa: nota ≥ 7 ou
    execução não comprovada/indeterminada (962 laudos tinham manifesto mais novo; todos na frente parariam a cobertura)."""
    rev = _revistos_sem_doc()
    out = []
    try:
        rows = con.execute("SELECT numero_sei, COALESCE(em,'') FROM lex_execucao WHERE "
                              "(nota_risco >= 7 OR execucao_comprovada IN ('nao', 'indeterminado', ?)) AND "
                              "COALESCE(modelo,'') NOT LIKE '%sessão Claude Code%' AND "
                              "COALESCE(modelo,'') NOT LIKE '%agente Claude Code%'", (SEM_DOC_EXECUCAO,)).fetchall()
    except sqlite3.OperationalError:
        return []                                      # base sem modelo/em (fixture antiga): nada a reavaliar
    for ns, em in rows:
        man = _ARQUIVO_SEI / str(ns).replace("SEI-", "").replace("/", "_") / "manifest.json"
        try:
            cap = datetime.fromtimestamp(man.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
        except OSError:
            continue
        if cap > str(em)[:19] and str(rev.get(ns, ""))[:19] < cap:
            out.append(ns)
    return out


def _alvos(con: sqlite3.Connection, top: int, reavaliar: bool) -> list[tuple]:
    ja = set()
    if not reavaliar:
        ja = {r[0] for r in con.execute(SQL_JA_AVALIADO)}
    # mesmo ritmo do slot (top por rodada): só a ORDEM muda — veredito errado vale mais que cobertura nova
    primeiro = set(_contestados_por_siafe(con)[:top]) if not reavaliar else set()
    if not reavaliar:
        primeiro |= set(_recapturados(con)[:top])
    ja -= primeiro
    rows = con.execute(
        "SELECT numero_sei, objeto, valores, documentos, red_flags FROM sei_ficha "
        "WHERE n_docs > 0 ORDER BY n_docs DESC"
    ).fetchall()
    # FILA PELO DINHEIRO (14/11/2026): depois dos contestados, o maior VALOR PAGO (OB contabilizada no SIAFE); empate
    # (e processo sem OB localizada) segue a ordem de n_docs. Antes era só n_docs — o processo de R$ 8 bi esperava atrás
    # de qualquer pasta grande.
    rows = [r for r in rows if r[0] not in ja]
    # só ORDENA a fila (universo da sei_ficha): autos=False — a camada dos autos é para o processo periciado
    pago = mapa_obs_siafe(con, [r[0] for r in rows], autos=False) if rows else {}
    rows.sort(key=lambda r: (r[0] not in primeiro,
                             -(pago.get(_chave_processo(r[0])) or {}).get("total", 0.0)))   # estável: n_docs no empate
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
    # Co-motor (13/11/2026): Claude pela assinatura + a cascata de sempre sobre o mesmo processo; vereditos
    # cruzados em data/cruzamento_motores.db; o exibido/gravado é o do Claude quando houver.
    from compliance_agent.llm.comotor import juizo
    gerar_sync = juizo("pericia_execucao")
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
            # o veredito da REGRA não consome vaga do LLM: completa o lote até `top` processos COM documento de
            # execução (teto de 200 extras por passada — é leitura de disco, mas o slot divide a VM com o sweep SEI)
            alvos, vistos, n_llm = [], set(), 0
            while n_llm < a.top and len(vistos) < a.top + 200:
                lote = [x for x in _alvos(con, a.top + len(vistos), a.reavaliar) if x[0] not in vistos]
                if not lote:
                    break
                for x in lote:
                    vistos.add(x[0])
                    alvos.append(x)
                    if evidencia_execucao(x[0], x[3])["tem"]:
                        n_llm += 1
                        if n_llm >= a.top:
                            break
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
