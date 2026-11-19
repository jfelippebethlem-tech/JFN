# -*- coding: utf-8 -*-
"""Laudo de execução SEM CONCLUSÃO → por que, e o que o resolveria (18/11/2026, pedido do dono: "tem que resolver").

Universo: `lex_execucao` com `execucao_comprovada` ∈ {indeterminado, sem_documento_execucao} ou sem veredito
(~4.300 em 18/11/2026). Três peças, todas determinísticas e sem API paga:

1. `causas()` — classifica cada laudo pela causa MEDIDA no arquivo do processo (manifesto, texto em disco, família
   de citações, OB do SIAFE), nunca pela frase do LLM ("árvore rasa" aparece em 90% dos indeterminados e não diz
   se a captura é rasa ou se o processo é só de empenho).
2. `relacionados()` / `relacionados_dos_documentos()` — números SEI citados nos autos COM PAPEL (ata, contrato,
   licitação, origem/apensado/referência) ou por ≥ 2 documentos. Precedente jurídico e norma ficam fora. O processo
   relacionado fora do acervo vai para `sei_fila_captura` (`enfileirar`), com o valor pago em OB dos filhos sem
   conclusão como prioridade — dado real, nunca número de furar fila.
3. `fontes_externas()` — o que TCE-RJ (contratos/compras diretas), SIGA, vínculo OB↔contrato, DOERJ (extrato com as
   PARTES conferidas) e SIAFE (OB paga) dizem do processo: houve contrato? valor? aditivo? pagamento? Evidência com
   proveniência e estado (VERIFICADO/PENDENTE), gravada em `indeterminado_evidencia`. Fonte externa NÃO prova a
   entrega — fecha as perguntas laterais e aponta onde a entrega está documentada.

A reperícia não é feita aqui: `tools/lex_execucao._recapturados` já refaz o laudo quando a captura do processo fica
mais nova que ele; o mecanismo daqui alimenta a captura.

CLI (nice; leitura pontual, escrita só na fila e na tabela de evidência):
  python -m compliance_agent.indeterminados diagnosticar   # data/indeterminados/estado.json
  python -m compliance_agent.indeterminados ciclo          # diagnosticar + enfileirar + fontes externas
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DB = RAIZ / "data" / "compliance.db"
CATALOGO = RAIZ / "data" / "sei_rj_catalogo.db"
FAMILIA = RAIZ / "data" / "sei_familia.json"
AGENTES = RAIZ / "data" / "pericia_agentes"
SAIDA = RAIZ / "data" / "indeterminados"

MOTIVO = "indeterminado_relacionado"
ESTADOS = ("indeterminado", "sem_documento_execucao")
CONCLUSIVOS = ("sim", "parcial", "nao")

TIPOS_EXEC = {"aceite", "medicao", "nota_fiscal", "relatorio_fotografico", "fiscalizacao"}
TIPOS_PAG = {"nota_liquidacao", "ordem_bancaria", "programacao_desembolso", "liquidacao"}
TIPOS_CONTR = {"contrato", "edital", "termo_referencia", "ata_rp", "homologacao", "etp", "julgamento"}

# ── extrator ─────────────────────────────────────────────────────────────────────────────────────────────────────
# Número SEI do Estado: 6 dígitos / até 6 (zeros à esquerda somem no texto) / ano. "SEI" opcional — sem ele o
# papel no contexto é que segura o casamento (número solto sem papel é descartado adiante).
_RX_NUM = re.compile(r"(?<![\d/])(?:SEI[\s\-:nº°]*)?(\d{6})\s*/\s*(\d{1,6})\s*/\s*(\d{4})(?![\d/])", re.I)
_JANELA = 90
# ordem = prioridade quando a janela tem mais de um papel ("Contrato 036/2022, edital, TR… (SEI-…)" é o contrato).
# Medido em 57 processos (19/11/2026): "documentação anexada ao processo" é lista de deliberação (CIB) e "Origem 1 -
# Origem nacional" é origem do PRODUTO — o papel de origem exige a palavra "processo" junto.
_PAPEIS = (
    ("ata_rp", re.compile(r"\bata\s+de\s+registro|registro\s+de\s+pre[çc]os|\bARP\b", re.I)),
    ("contrato", re.compile(r"\bcontrato\s*(?:n[º°o.]|\d)|termo\s+aditivo", re.I)),
    ("licitacao", re.compile(r"licitat[óo]ri|licita[çc][ãa]o|preg[ãa]o|edital|concorr[êe]ncia|"
                             r"dispensa\s+de\s+licita|inexigibilidade", re.I)),
    ("origem", re.compile(r"processo\s+(?:de\s+)?origem|processo\s+origin[áa]ri|processo\s+principal|"
                          r"processo[\s-]+m[ãa]e|apensad[oa]|processos?\s+relacionad|vinculad[oa]\s+ao\s+processo|"
                          r"constante\s+dos\s+autos|em\s+continuidade|continua[çc][ãa]o\s+d", re.I)),
)
# precedente jurídico e norma: o número citado é de OUTRA matéria, não da família deste processo
_NAO_FAMILIA = re.compile(r"decidid[oa]\s+no|documenta[çc][ãa]o\s+anexada|precedente|parecer\s+normativo|enunciado|decreto|\blei\s+n|"
                          r"resolu[çc][ãa]o|delibera[çc][ãa]o|portaria|ac[óo]rd[ãa]o", re.I)
_RX_COLETIVO = re.compile(r"publica[çc][ãa]o|doerj|di[áa]rio\s+oficial|extrato|anexo\s+d\.?o\.?\b|recorte", re.I)
MAX_CITACOES_DOC = 15


def _numero(a: str, b: str, c: str) -> str:
    return f"SEI-{a}/{int(b):06d}/{c}"


def norm(numero: str | None) -> str | None:
    m = _RX_NUM.search(numero or "")
    return _numero(*m.groups()) if m else None


def relacionados(texto: str, proprio: str) -> list[dict]:
    """Números citados com PAPEL no contexto anterior (até o número precedente). Sem papel → papel 'citado' só no
    agregado por documentos (`relacionados_dos_documentos`); aqui, descartado."""
    return [x for x in _citacoes(texto, proprio) if x["papel"] != "citado"]


def _citacoes(texto: str, proprio: str) -> list[dict]:
    texto = str(texto or "")
    eu = norm(proprio)
    out: dict[str, dict] = {}
    fim_anterior = 0
    for m in _RX_NUM.finditer(texto):
        num = _numero(*m.groups())
        ini = max(fim_anterior, m.start() - _JANELA)
        janela = texto[ini:m.start()]
        fim_anterior = m.end()
        if num == eu or _NAO_FAMILIA.search(janela[-60:]):
            continue
        papel = next((p for p, rx in _PAPEIS if rx.search(janela)), "citado")
        trecho = re.sub(r"\s+", " ", texto[max(0, m.start() - 80):m.end()]).strip()
        atual = out.get(num)
        if atual is None or (atual["papel"] == "citado" and papel != "citado"):
            out[num] = {"numero": num, "papel": papel, "trecho": trecho}
    return list(out.values())


def relacionados_dos_documentos(docs: list[dict], proprio: str, *, min_docs_solto: int = 2) -> list[dict]:
    """Agrega por processo citado: papel mais forte visto, nº de documentos que o citam. Página coletiva (título de
    publicação/extrato, ou > 15 números) fica fora — misturou contratos alheios no INEA 34/2023."""
    ordem = {p: i for i, (p, _) in enumerate(_PAPEIS)} | {"citado": len(_PAPEIS)}
    agg: dict[str, dict] = {}
    for d in docs:
        if _RX_COLETIVO.search(str(d.get("titulo") or "")):
            continue
        cs = _citacoes(str(d.get("texto") or ""), proprio)
        if len(cs) > MAX_CITACOES_DOC:
            continue
        for c in cs:
            a = agg.setdefault(c["numero"], {**c, "n_docs": 0, "doc": d.get("titulo")})
            a["n_docs"] += 1
            if ordem[c["papel"]] < ordem[a["papel"]]:
                a.update(papel=c["papel"], trecho=c["trecho"], doc=d.get("titulo"))
    return [a for a in agg.values() if a["papel"] != "citado" or a["n_docs"] >= min_docs_solto]


# ── causa ────────────────────────────────────────────────────────────────────────────────────────────────────────
CAUSAS = {
    "sem_arquivo": "processo sem arquivo local (só a ficha do sweep) — capturar a íntegra",
    "captura_vazia": "captura voltou vazia — recapturar",
    "documento_sigiloso": "documentos sigilosos/restritos sem texto — pedir acesso (não contornar)",
    "sem_texto_ocr": "menos de 60% dos documentos com texto em disco — OCR (escaneado)",
    "captura_truncada": "árvore maior que a captura (teto de documentos) — recapturar inteira",
    "execucao_so_em_imagem": "documento de execução só em imagem — OCR",
    "execucao_avaliada_na_familia": "a execução é avaliada em processo da mesma família já periciado",
    "processo_relacionado_fora_do_acervo": "processo de origem/contrato/ata citado nos autos e fora do acervo — capturar",
    "lacuna_do_processo": "captura íntegra sem documento de execução — falta DO PROCESSO (pesa como achado)",
    "autos_nao_varridos": "autos ainda não varridos atrás do processo de origem (próximas rodadas)",
    "juizo_inconclusivo": "há documento de execução com texto e o laudo não concluiu — reperícia/perícia integral",
    "ob_nao_ligada": "nenhuma OB paga ligada ao processo no SIAFE (INDISPONÍVEL ≠ 0)",
}


def causas(d: dict) -> list[str]:
    """Causas em ordem de precedência (a 1ª é a principal). Mede pelo TEXTO em disco, não pela etiqueta."""
    out: list[str] = []
    n = int(d.get("n_docs") or 0)
    if not d.get("arquivo"):
        out.append("sem_arquivo")
    elif d.get("captura_vazia") or n == 0:
        out.append("captura_vazia")
    else:
        pouco_texto = (d.get("com_texto") or 0) < 0.6 * n
        if pouco_texto and d.get("sigilo"):
            out.append("documento_sigiloso")
        if pouco_texto:
            out.append("sem_texto_ocr")
        if (d.get("total_arvore") or 0) > n:
            out.append("captura_truncada")
        if d.get("exec") and d.get("exec_sem_texto"):
            out.append("execucao_so_em_imagem")
        if not d.get("exec"):
            if d.get("familia_conclusiva"):
                out.append("execucao_avaliada_na_familia")
            if d.get("relacionados_fora"):
                out.append("processo_relacionado_fora_do_acervo")
            if not d.get("familia_conclusiva") and not d.get("relacionados_fora") and not out:
                # sem ter varrido os autos atrás do processo-mãe, "falta do processo" seria afirmação sem leitura
                out.append("autos_nao_varridos" if d.get("autos_lidos") is False else "lacuna_do_processo")
        else:
            if d.get("relacionados_fora"):
                out.append("processo_relacionado_fora_do_acervo")
            if not out:
                out.append("juizo_inconclusivo")
    if not d.get("ob_n"):
        out.append("ob_nao_ligada")
    return out


# ── fila ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def enfileirar(con: sqlite3.Connection, alvos: list[dict], *, agora: str | None = None, teto: int = 2000) -> int:
    """`alvos` = [{numero, papel, filho, pago_filho, estado_filho}]. Um pedido por número (soma do pago dos filhos
    DISTINTOS); INSERT OR IGNORE — não rebaixa nem reescreve pedido de outra origem. Devolve quantos entraram."""
    agora = agora or time.strftime("%Y-%m-%dT%H:%M:%S")
    por: dict[str, dict] = {}
    for a in alvos:
        num = norm(a.get("numero"))
        if not num:
            continue
        p = por.setdefault(num, {"filhos": {}, "papeis": Counter()})
        p["filhos"][a.get("filho")] = float(a.get("pago_filho") or 0.0)
        p["papeis"][a.get("papel") or "citado"] += 1
    ordenados = sorted(por.items(), key=lambda kv: -sum(kv[1]["filhos"].values()))[:teto]
    n = 0
    for num, p in ordenados:
        pago = round(sum(p["filhos"].values()), 2)
        filhos = sorted(f for f in p["filhos"] if f)
        motivo = (f"{MOTIVO}: {p['papeis'].most_common(1)[0][0]} citado por {len(filhos)} laudo(s) de execução "
                  f"sem conclusão (ex.: {filhos[0] if filhos else '?'})")
        n += con.execute("INSERT OR IGNORE INTO sei_fila_captura VALUES (?,?,?,?,?,?)",
                         (num, num.replace("SEI-", "").replace("/", ""), motivo, pago, 0, agora)).rowcount
    con.commit()
    return n


# ── medição por processo ─────────────────────────────────────────────────────────────────────────────────────────
def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def medir_arquivo(numero_sei: str) -> dict:
    """O que o arquivo do processo TEM (manifesto normalizado + texto em disco). Sem arquivo → {'arquivo': False}."""
    from compliance_agent.sei import manifesto_norm
    man = manifesto_norm.carregar(numero_sei)
    if man is None:
        return {"arquivo": False}
    docs = manifesto_norm.normalizar(man)["docs"]
    tipos = {x.get("tipo") or "?" for x in docs}
    return {"arquivo": True, "pasta": str(man.get("_pasta") or ""), "n_docs": len(docs),
            "total_arvore": _int(man.get("total_arvore")), "captura_vazia": bool(man.get("captura_vazia")),
            "com_texto": sum(1 for x in docs if _int(x.get("chars")) >= 200),
            "exec": sorted(TIPOS_EXEC & tipos), "pag": sorted(TIPOS_PAG & tipos), "contr": sorted(TIPOS_CONTR & tipos),
            "exec_sem_texto": sum(1 for x in docs if x.get("tipo") in TIPOS_EXEC and _int(x.get("chars")) < 200),
            "sigilo": sum(1 for x in docs if re.search(r"sigil|restrit", str(x.get("titulo") or ""), re.I))}


def relacionados_do_arquivo(numero_sei: str, pasta: str | None) -> list[dict]:
    if not pasta:
        return []
    from compliance_agent.cronologia_do_ato import docs_do_arquivo
    return relacionados_dos_documentos(docs_do_arquivo(pasta), numero_sei)


def lacunas_dos_agentes(pasta: Path = AGENTES) -> dict[str, list[dict]]:
    """Números SEI citados em `lacunas`/`lido.nao_lidos` dos laudos integrais por agente → {processo: [relacionado]}.
    O agente leu os autos inteiros: o número que ele pede é processo da família por construção (papel 'lacuna_agente')."""
    out: dict[str, list[dict]] = defaultdict(list)
    for f in sorted(pasta.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        dono = norm(str(d.get("processo") or ""))
        if not dono:
            continue
        lido = d.get("lido") if isinstance(d.get("lido"), dict) else {}
        for item in list(d.get("lacunas") or []) + [lido.get("nao_lidos") or ""]:
            texto = str(item)
            for m in _RX_NUM.finditer(texto):
                num = _numero(*m.groups())
                if num != dono:
                    out[dono].append({"numero": num, "papel": "lacuna_agente", "trecho": texto[:200]})
    return dict(out)


# ── fontes externas ──────────────────────────────────────────────────────────────────────────────────────────────
def _digitos(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _brl(v) -> str:
    return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Indices:
    """Fontes pequenas carregadas UMA vez (SIGA ~5 mil, vínculo ~6 mil); TCE-RJ e DOERJ por índice/FTS."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.siga: dict[str, list] = defaultdict(list)
        for row in con.execute("SELECT processo, id_contrato, cnpj, valor, data, objeto, situacao, valor_pago_siga "
                               "FROM siga_contratos WHERE COALESCE(processo,'') <> ''"):
            k = norm(row[0])
            if k:
                self.siga[k].append(row)
        self.vinculo: dict[str, list] = defaultdict(list)
        for row in con.execute("SELECT processo_pagamento, processo_contrato, contrato_tcerj_id, credor, estado, ob "
                               "FROM vinculo_ob_contrato WHERE estado = 'VERIFICADO' "
                               "AND COALESCE(processo_pagamento,'') <> ''"):
            k = norm(row[0])
            if k:
                self.vinculo[k].append(row)


def fontes_externas(idx: Indices, numero_sei: str, *, cnpjs: set[str] | None = None,
                    via: str | None = None) -> list[dict]:
    """Evidência de fonte externa sobre `numero_sei` (o próprio ou um processo relacionado, `via`).
    Estado: VERIFICADO = chave exata e partes conferidas (ou sem parte a conferir na fonte); PENDENTE = casou o
    número mas a parte diverge/não aparece (ato vizinho não descartado)."""
    con, out = idx.con, []
    cnpjs = {c for c in (cnpjs or set()) if len(c) == 14}
    chave = _digitos(numero_sei)

    def _ev(fonte, pergunta, resposta, prova, estado, valor=None):
        out.append({"numero_sei": via or numero_sei, "via_processo": numero_sei if via else "", "fonte": fonte,
                    "pergunta": pergunta, "resposta": resposta, "valor": valor, "prova": prova, "estado": estado})

    for id_, cnpj, valor, ini, fim, forn, pago in con.execute(
            "SELECT id, cnpj, valor_contrato, vig_inicio, vig_fim, fornecedor, valor_pago FROM contratos_tcerj "
            "WHERE sei_norm = ?", (chave,)):
        cn = _digitos(cnpj)
        est = "VERIFICADO" if not cnpjs or cn in cnpjs else "PENDENTE"
        _ev("TCE-RJ contratos (dados abertos)", "houve_contrato",
            f"contrato registrado com {forn or '?'} (CNPJ {cn or '?'}), valor {_brl(valor or 0)}, vigência "
            f"{ini or '?'} a {fim or '?'}" + ("" if est == "VERIFICADO" else " — CNPJ difere do credor dos autos"),
            f"contratos_tcerj.id={id_}", est, valor)
    for id_, valor, forn, enq in con.execute(
            "SELECT id, valor, fornecedor, enquadramento_legal FROM compras_diretas_tcerj WHERE sei_norm = ? LIMIT 20",
            (chave,)):
        _ev("TCE-RJ compras diretas", "houve_contratacao_direta",
            f"compra direta registrada ({enq or 'enquadramento n/d'}) com {forn or '?'}, {_brl(valor or 0)}",
            f"compras_diretas_tcerj.id={id_}", "VERIFICADO", valor)
    k = norm(numero_sei) or ""
    for _, id_c, cnpj, valor, data, objeto, sit, pago in idx.siga.get(k, []):
        cn = _digitos(cnpj)
        est = "VERIFICADO" if not cnpjs or cn in cnpjs else "PENDENTE"
        _ev("SIGA contratos", "houve_contrato",
            f"contrato SIGA {id_c} ({sit or 'situação n/d'}), {_brl(valor or 0)}, data {data or '?'}",
            f"siga_contratos.id_contrato={id_c}", est, valor)
    for _, proc_c, id_t, credor, est, ob in idx.vinculo.get(k, []):
        _ev("vínculo OB↔contrato (autos)", "processo_do_contrato",
            f"OB {ob} deste pagamento ligada ao contrato do processo {proc_c or '?'} (TCE-RJ {id_t or 'n/d'})",
            f"vinculo_ob_contrato.ob={ob}", "VERIFICADO")
    a, b, c = (k[4:].split("/") + ["", "", ""])[:3] if k else ("", "", "")
    if a:
        frase = f'"{a} {b} {c}"'
        try:
            rows = con.execute("SELECT p.id, p.data_publicacao, p.tipo_ato, p.titulo, p.texto FROM fts_doerj f "
                               "JOIN publicacoes_doerj p ON p.id = f.rowid WHERE fts_doerj MATCH ? LIMIT 20",
                               (frase,)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for pid, data, tipo, titulo, texto in rows:
            texto = str(texto or "")
            m = re.search(rf"{a}\s*/\s*0*{int(b)}\s*/\s*{c}", texto)
            if not m:
                continue
            janela = _digitos(texto[max(0, m.start() - 1500):m.end() + 1500])
            partes_ok = bool(cnpjs) and any(cn in janela for cn in cnpjs)
            ato = re.search(r"extrato|aditivo|ratifica|homologa|adjudica|rescis|apostil", f"{titulo} {tipo} "
                            f"{texto[max(0, m.start() - 600):m.end() + 600]}", re.I)
            _ev("DOERJ", "ato_publicado",
                f"{(ato.group(0).lower() if ato else 'ato')} publicado em {data} ({(titulo or tipo or '')[:80]})"
                + ("" if partes_ok else " — PARTES não conferidas (CNPJ do credor ausente perto do número)"),
                f"publicacoes_doerj.id={pid}", "VERIFICADO" if partes_ok else "PENDENTE")
    return out


_DDL_EVIDENCIA = """CREATE TABLE IF NOT EXISTS indeterminado_evidencia (
    numero_sei TEXT NOT NULL, via_processo TEXT NOT NULL DEFAULT '', fonte TEXT NOT NULL, pergunta TEXT,
    resposta TEXT, valor REAL, prova TEXT NOT NULL, estado TEXT, em TEXT,
    PRIMARY KEY (numero_sei, via_processo, fonte, prova))"""


def gravar_evidencias(con: sqlite3.Connection, numero_sei: str, evs: list[dict], *, agora: str) -> int:
    """Substitui a evidência externa do processo (idempotente: a rodada nova é a fotografia vigente)."""
    con.execute(_DDL_EVIDENCIA)
    con.execute("DELETE FROM indeterminado_evidencia WHERE numero_sei = ?", (numero_sei,))
    for e in evs:
        con.execute("INSERT OR REPLACE INTO indeterminado_evidencia VALUES (?,?,?,?,?,?,?,?,?)",
                    (numero_sei, e["via_processo"], e["fonte"], e["pergunta"], e["resposta"], e["valor"],
                     e["prova"], e["estado"], agora))
    return len(evs)


# ── ciclo ────────────────────────────────────────────────────────────────────────────────────────────────────────
PAPEIS_FORTES = {"ata_rp", "contrato", "licitacao", "origem", "lacuna_agente"}
_CACHE_REL = SAIDA / "relacionados_cache.json"
FILA_JSON = SAIDA / "fila_captura.json"
ESTADO_JSON = SAIDA / "estado.json"
CAUSAS_DE_CAPTURA = {"sem_arquivo", "captura_vazia", "captura_truncada"}


def _ler_json(p: Path, padrao):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def _gravar_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _laudos_sem_conclusao(con: sqlite3.Connection) -> list[tuple[str, str | None]]:
    return con.execute("SELECT numero_sei, execucao_comprovada FROM lex_execucao WHERE execucao_comprovada IS NULL "
                       "OR execucao_comprovada IN (?, ?)", ESTADOS).fetchall()


def _cnpjs_da_ficha(con: sqlite3.Connection, ns: str) -> set[str]:
    r = con.execute("SELECT cnpjs FROM sei_ficha WHERE numero_sei = ?", (ns,)).fetchone()
    try:
        lst = json.loads(r[0]) if r and r[0] else []
    except ValueError:
        lst = []
    return {_digitos(str(x)) for x in lst if isinstance(x, (str, int))}


def diagnosticar(con: sqlite3.Connection, *, ler_texto: bool = True, max_ler: int | None = None,
                 log=print) -> list[dict]:
    """Uma linha por laudo sem conclusão, com as causas medidas. Texto dos autos lido só quando o manifesto mudou
    desde a última leitura (cache por mtime) — o ciclo inteiro não relê 100 mil arquivos. `max_ler` limita as
    leituras por rodada (I/O: ~1 processo/5 s com carga alta); o resto entra nas próximas, maior pago primeiro."""
    from compliance_agent.ob_processo import chave_processo, obs_por_processo
    laudos = _laudos_sem_conclusao(con)
    lex = dict(con.execute("SELECT numero_sei, execucao_comprovada FROM lex_execucao"))
    ficha = dict(con.execute("SELECT numero_sei, n_docs FROM sei_ficha"))
    fam = _ler_json(FAMILIA, {"cita": {}, "citado_por": {}, "no_acervo": []})
    no_acervo = set(fam.get("no_acervo") or [])
    agentes = lacunas_dos_agentes()
    pago = obs_por_processo(con, [ns for ns, _ in laudos], autos=False, so_pagos=True)
    cache = _ler_json(_CACHE_REL, {})
    laudos.sort(key=lambda t: -((pago.get(chave_processo(t[0]) or "") or {}).get("total") or 0.0))
    lidos = 0
    out: list[dict] = []
    for i, (ns, est) in enumerate(laudos):
        d = {"sei": ns, "estado": est, **medir_arquivo(ns), "ficha_ndocs": ficha.get(ns)}
        if d.get("arquivo") and (ficha.get(ns) or 0) > d["n_docs"]:
            d["total_arvore"] = max(d["total_arvore"], ficha[ns])       # o sweep viu mais documentos que a captura
        p = pago.get(chave_processo(ns) or "") or {}
        d["ob_n"], d["ob_total"] = p.get("n", 0), round(p.get("total", 0.0) or 0.0, 2)
        rel: list[dict] = []
        c = cache.get(ns)
        mt = 0.0
        if d.get("arquivo"):
            try:
                mt = Path(d["pasta"], "manifest.json").stat().st_mtime
            except OSError:
                mt = 0.0
        if c and (c.get("mtime") == mt or not ler_texto or (max_ler is not None and lidos >= max_ler)):
            rel = c["rel"]
        elif d.get("arquivo") and ler_texto and (max_ler is None or lidos < max_ler):
            rel = [{k: x[k] for k in ("numero", "papel", "n_docs", "trecho")}
                   for x in relacionados_do_arquivo(ns, d["pasta"])]
            cache[ns] = {"mtime": mt, "rel": rel}
            lidos += 1
            if lidos % 100 == 0:
                _gravar_json(_CACHE_REL, cache)
        d["autos_lidos"] = ns in cache
        rel = [x for x in rel if x["papel"] in PAPEIS_FORTES or x.get("n_docs", 0) >= 2]
        rel += agentes.get(ns, [])
        d["relacionados"] = rel
        d["relacionados_fora"] = sorted({x["numero"] for x in rel if x["numero"] not in no_acervo})
        fam_rel = {n for n, k in (fam["cita"].get(ns) or {}).items() if k >= 2}
        fam_rel |= {n for n, k in (fam["citado_por"].get(ns) or {}).items() if k >= 2}
        fam_rel |= {x["numero"] for x in rel}
        d["familia_conclusiva"] = sorted(n for n in fam_rel if lex.get(n) in CONCLUSIVOS)
        d["causas"] = causas(d)
        d.pop("pasta", None)
        out.append(d)
        if log and i and i % 500 == 0:
            log(f"  {i}/{len(laudos)}")
    _gravar_json(_CACHE_REL, cache)
    return out


def alvos_de_captura(diag: list[dict]) -> tuple[list[dict], list[dict]]:
    """(relacionados fora do acervo → sei_fila_captura, fila priorizada de captura dos indeterminados → JSON).
    A fila JSON junta o PRÓPRIO processo (sem arquivo/vazio/truncado) e os relacionados, por valor pago desc."""
    rel_alvos: list[dict] = []
    fila: dict[str, dict] = {}
    for d in diag:
        papeis = {x["numero"]: x["papel"] for x in d.get("relacionados") or []}
        for n in d.get("relacionados_fora") or []:
            rel_alvos.append({"numero": n, "papel": papeis.get(n, "citado"), "filho": d["sei"],
                              "pago_filho": d.get("ob_total") or 0.0, "estado_filho": d.get("estado")})
            f = fila.setdefault(n, {"sei": n, "pago": 0.0, "motivo": f"relacionado ({papeis.get(n, 'citado')})",
                                    "filhos": []})
            if d["sei"] not in f["filhos"]:
                f["filhos"].append(d["sei"])
                f["pago"] += d.get("ob_total") or 0.0
        if d["causas"][0] in CAUSAS_DE_CAPTURA:
            f = fila.setdefault(d["sei"], {"sei": d["sei"], "pago": 0.0, "motivo": d["causas"][0], "filhos": []})
            f["pago"] = max(f["pago"], d.get("ob_total") or 0.0)
            f["motivo"] = d["causas"][0]
    ordem = sorted(fila.values(), key=lambda x: (-x["pago"], x["sei"]))
    for x in ordem:
        x["pago"] = round(x["pago"], 2)
    return rel_alvos, ordem


def resolver_externo(con: sqlite3.Connection, diag: list[dict], *, maximo: int = 400, dias: int = 7,
                     agora: str | None = None, log=print) -> dict:
    """Fontes externas para o processo e para os seus relacionados COM PAPEL (o contrato vive no processo-mãe).
    Incremental: só quem não tem evidência ou a tem há mais de `dias`, maior pago primeiro, até `maximo`."""
    agora = agora or time.strftime("%Y-%m-%dT%H:%M:%S")
    con.execute(_DDL_EVIDENCIA)
    vistos = dict(con.execute("SELECT numero_sei, MAX(em) FROM indeterminado_evidencia GROUP BY numero_sei"))
    marca = dict(con.execute("SELECT numero_sei, em FROM indeterminado_evidencia_rodada")) \
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='indeterminado_evidencia_rodada'").fetchone() else {}
    con.execute("CREATE TABLE IF NOT EXISTS indeterminado_evidencia_rodada (numero_sei TEXT PRIMARY KEY, em TEXT, "
                "n INTEGER)")
    corte = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - dias * 86400))
    fila = [d for d in diag if max(str(vistos.get(d["sei"]) or ""), str(marca.get(d["sei"]) or "")) < corte]
    fila.sort(key=lambda d: -(d.get("ob_total") or 0.0))
    idx = Indices(con)
    n_proc = n_ev = 0
    for d in fila[:maximo]:
        ns = d["sei"]
        cnpjs = _cnpjs_da_ficha(con, ns)
        evs = fontes_externas(idx, ns, cnpjs=cnpjs)
        for r in d.get("relacionados") or []:
            if r["papel"] in PAPEIS_FORTES:
                evs += fontes_externas(idx, r["numero"], cnpjs=cnpjs, via=ns)
        gravar_evidencias(con, ns, evs, agora=agora)
        con.execute("INSERT OR REPLACE INTO indeterminado_evidencia_rodada VALUES (?,?,?)", (ns, agora, len(evs)))
        con.commit()
        n_proc += 1
        n_ev += len(evs)
    return {"processos_consultados": n_proc, "evidencias": n_ev, "pendentes_de_consulta": max(0, len(fila) - maximo)}


def resumo(diag: list[dict], con: sqlite3.Connection | None = None) -> dict:
    prim, todas, pago = Counter(), Counter(), Counter()
    por_estado: dict[str, Counter] = defaultdict(Counter)
    for d in diag:
        c0 = d["causas"][0]
        prim[c0] += 1
        pago[c0] += d.get("ob_total") or 0.0
        por_estado[d.get("estado") or "sem_veredito"][c0] += 1
        todas.update(d["causas"])
    r = {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "laudos_sem_conclusao": len(diag),
         "causa_principal": {k: {"n": v, "pago_ob": round(pago[k], 2), "o_que_resolve": CAUSAS[k]}
                             for k, v in prim.most_common()},
         "todas_as_causas": dict(todas.most_common()),
         "por_estado": {k: dict(v.most_common()) for k, v in por_estado.items()}}
    if con is not None and con.execute("SELECT 1 FROM sqlite_master WHERE name='indeterminado_evidencia'").fetchone():
        ev = defaultdict(set)
        for ns, perg in con.execute("SELECT numero_sei, pergunta FROM indeterminado_evidencia "
                                    "WHERE estado = 'VERIFICADO'"):
            ev[perg].add(ns)
        r["fontes_externas_verificado"] = {k: len(v) for k, v in ev.items()}
    return r


def ciclo(*, maximo_externo: int = 400, ler_texto: bool = True, max_ler: int | None = 300, enfileirar_db: bool = True,
          log=print) -> dict:
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    try:
        diag = diagnosticar(con, ler_texto=ler_texto, max_ler=max_ler, log=log)
        rel_alvos, fila = alvos_de_captura(diag)
        no_fila = {r[0] for r in con.execute("SELECT numero_sei FROM sei_fila_captura")}
        desconhecidos = {a["numero"] for a in rel_alvos} - no_fila
        entraram = enfileirar(con, rel_alvos) if enfileirar_db else 0
        _gravar_json(FILA_JSON, {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "fila": fila})
        ext = resolver_externo(con, diag, maximo=maximo_externo, log=log)
        r = resumo(diag, con)
        r["fila"] = {"relacionados_distintos": len({a["numero"] for a in rel_alvos}),
                     "relacionados_fora_da_fila_antes": len(desconhecidos), "inscritos_agora": entraram,
                     "fila_json": len(fila)}
        r["externo"] = ext
        _gravar_json(ESTADO_JSON, r)
        _gravar_json(SAIDA / "diagnostico.json", diag)
        return r
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("acao", choices=("diagnosticar", "ciclo"))
    ap.add_argument("--max-externo", type=int, default=400)
    ap.add_argument("--sem-texto", action="store_true", help="não lê os autos (usa só o cache de relacionados)")
    ap.add_argument("--max-ler", type=int, default=300, help="processos com autos varridos por rodada (0 = sem teto)")
    a = ap.parse_args(argv)
    if a.acao == "diagnosticar":
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120)
        try:
            diag = diagnosticar(con, ler_texto=not a.sem_texto, max_ler=a.max_ler or None)
            r = resumo(diag, con)
        finally:
            con.close()
        _gravar_json(SAIDA / "diagnostico.json", diag)
    else:
        r = ciclo(maximo_externo=a.max_externo, ler_texto=not a.sem_texto, max_ler=a.max_ler or None)
    print(json.dumps({k: v for k, v in r.items() if k != "por_estado"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
