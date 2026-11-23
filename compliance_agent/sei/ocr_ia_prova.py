# -*- coding: utf-8 -*-
"""Trava de PROVA do OCR por IA: número crítico lido pela IA só vale como prova CONFIRMADO.

POR QUE (23/11/2026). O OCR por IA da GPU (Surya, `ocr_motor` "surya…") e a reserva (RapidOCR, "reserva…") só
PREENCHEM documento que estava sem texto (`tools/sei_ocr_gpu_integrar`), e o texto deles vira o canônico do acervo.
Medido em 20/11: frente ao Tesseract, 1,0% dos documentos perderam CNPJ válido e 23,1% perderam algum valor em R$; a
literatura de VLM-OCR descreve o mesmo modo de falha — texto fluente que NÃO está na página (KIE-HVQA, arXiv
2506.20168; "Do VLMs read or rewrite?", Amazon Science). O texto continua legível e pesquisável; o que muda é o
NÚMERO: CNPJ, valor em R$, data, nº de processo/contrato/ata/NF tirado de documento de IA não é fato até ser
confirmado por uma fonte INDEPENDENTE do motor que o leu:

  · segunda leitura de outra família — Tesseract da casa (`sei/ocr_docs._ocr_tesseract`, por, 200 dpi) na mesma
    página do PDF, o texto nativo da página quando ela é nativa, ou o outro motor já guardado ao lado
    (`.gpu.txt` / `.reserva.txt` / `.tesseract.txt`) — concordância LITERAL do número normalizado;
  · fonte externa da casa no MESMO processo — OB e NE do SIAFE (valor, credor);
  · outro documento NÃO-IA do mesmo processo que traz o mesmo número (só CNPJ, valor ≥ R$ 100,00, processo e
    contrato com ano: data e nº curto de NF coincidem por acaso);
  · decisão registrada por quem conferiu a página (`marcar`, humano ou Opus).

Concordância de dois motores de famílias diferentes é o que a literatura de OCR multi-motor usa como sinal de acerto
(votação tipo ROVER); DV válido NÃO confirma (troca de um dígito passa no módulo 11 em ~1 de 11 casos).

ESTADOS por número (registro durável `data/sei_ocr_ia_conferencia.jsonl`, só acrescenta; a decisão HUMANA vale
sobre a automática, a última de cada classe vale):
  confirmado  — achado numa fonte independente (a fonte fica no registro);
  divergente  — a segunda leitura traz um número PARECIDO e diferente (as duas leituras ficam no registro);
  a_conferir  — nenhuma segunda fonte o viu (ou ainda não se tentou);
  errado      — quem conferiu a página disse que a IA leu errado.
Só `confirmado` é prova. Documento que não é de IA passa direto (`vale_como_prova` → True): a trava não muda nada
fora dos documentos da IA.

    from compliance_agent.sei import ocr_ia_prova as P
    P.vale_como_prova(tag, doc, "cnpj", "12.345.678/0001-95")
    P.texto_para_prova(pasta, doc, texto)   # texto com os números NÃO confirmados trocados por ⟦a conferir⟧
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date
from pathlib import Path

from compliance_agent.cpf_cnpj import cnpj_valido

_REPO = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("JFN_DATA_DIR") or _REPO / "data")
LEDGER = Path(os.environ.get("JFN_OCR_IA_LEDGER") or DATA / "sei_ocr_ia_conferencia.jsonl")
MOTORES_IA = ("surya", "reserva")
TIPOS = ("cnpj", "valor", "data", "processo", "contrato", "ata", "nf")
ESTADOS = ("confirmado", "divergente", "a_conferir", "errado")
MARCA = "⟦a conferir⟧"


def eh_ocr_ia(doc: dict | None) -> bool:
    """O texto canônico do documento veio do OCR por IA (Surya na GPU ou reserva RapidOCR)?"""
    return str((doc or {}).get("ocr_motor") or "").strip().lower().startswith(MOTORES_IA)


# ── extração e normalização ──────────────────────────────────────────────────────────────────────
_RX_CNPJ = re.compile(r"(?<!\d)\d{2}[.,]?\d{3}[.,]?\d{3}\s?/\s?\d{4}[-.,]?\d{2}(?!\d)")
_RX_VALOR = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+,\d{2}|\d{1,12},\d{2})(?![\d,]|\.\d)")
# segunda leitura: o Tesseract troca a vírgula decimal por ponto em tabela miúda ("1.234.56") — mesma correção da
# reserva (`tools/sei_ocr_reserva.corrigir`). Só na leitura de CONFERÊNCIA, nunca na da IA.
_RX_VALOR_TOLERANTE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})(?![\d,]|\.\d)")
_RX_DATA = re.compile(r"(?<![\d/])(\d{1,2})\s?/\s?(\d{1,2})\s?/\s?(\d{4})(?![\d/])")
_RX_PROCESSO = re.compile(r"(?<!\d)(\d{5,6})\s*/\s*(\d{3,6})\s*/\s*(\d{4}|\d{2})(?![\d/])")
_RX_CONTRATO = re.compile(r"\bcontrato\s*(?:de\s+gest[aã]o\s+)?(?:n[º°o.]*\s*)?(\d{1,5})\s*/\s*(\d{4}|\d{2})(?!\d)",
                          re.I)
_RX_ATA = re.compile(r"\bata\s+de\s+registro\s+de\s+pre[çc]os?\s*(?:n[º°o.]*\s*)?(\d{1,5})\s*/\s*(\d{4}|\d{2})(?!\d)",
                     re.I)
# nº da NF: na mesma linha do rótulo, ou na linha de baixo só com marcador explícito ("NF-e\nN. 000001536"); nunca
# o contador de página que segue o título do portal ("Portal da Nota Fiscal Eletrônica\n1217/429", medido 23/11)
_RX_NF = re.compile(r"\b(?:nfs?-?e|nota\s+fiscal(?:\s+de\s+servi[çc]os?)?(?:\s+eletr[ôo]nica)?)"
                    r"(?:[ \t]*[:\-]?[ \t]*(?:n[º°o.]*[ \t]*|n[úu]mero[ \t]*:?[ \t]*)?"
                    r"|\s*(?:n[º°o.]+|n[úu]mero)\s*:?\s*)0*(\d{1,9})\b(?![/\d])", re.I)


def _ano(a: str) -> str:
    return a if len(a) == 4 else "20" + a


def _valor_norma(s: str, tolerante: bool = False) -> str | None:
    """'1.234,56' → '1234.56'. Tolerante: o último separador é o decimal ('1.234.56' → '1234.56')."""
    if tolerante:
        inteiro, dec = re.sub(r"\D", "", s[:-3]), s[-2:]
    else:
        inteiro, _, dec = s.partition(",")
        inteiro = inteiro.replace(".", "")
    if not inteiro.isdigit() or not dec.isdigit():
        return None
    return f"{int(inteiro)}.{dec}"


def _data_norma(d: str, m: str, a: str) -> str | None:
    try:
        x = date(int(a), int(m), int(d))
    except ValueError:
        return None
    return x.isoformat() if 1990 <= x.year <= 2100 else None


def normalizar(tipo: str, valor) -> str | None:
    """Forma canônica de um número crítico — a que se compara entre leituras e se grava no registro."""
    s = str(valor or "").strip()
    if not s:
        return None
    if tipo == "cnpj":
        d = re.sub(r"\D", "", s)
        return d if cnpj_valido(d) else None
    if tipo == "valor":
        if re.fullmatch(r"\d+\.\d{2}", s):                  # já normalizado
            return f"{int(s[:-3])}.{s[-2:]}"
        if isinstance(valor, (int, float)):
            return f"{float(valor):.2f}"
        m = re.search(r"\d[\d.]*,\d{2}", s)
        return _valor_norma(m.group(0)) if m else None
    if tipo == "data":
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return s
        m = _RX_DATA.search(s)
        return _data_norma(*m.groups()) if m else None
    if tipo == "processo":
        m = _RX_PROCESSO.search(s)
        return f"{int(m[1]):06d}/{int(m[2]):06d}/{_ano(m[3])}" if m else None
    if tipo in ("contrato", "ata"):
        m = re.search(r"(\d{1,5})\s*/\s*(\d{4}|\d{2})(?!\d)", s)
        return f"{int(m[1])}/{_ano(m[2])}" if m else None
    if tipo == "nf":
        d = re.sub(r"\D", "", s).lstrip("0")
        return d or None
    return None


def extrair(texto: str, *, tolerante: bool = False) -> list[dict]:
    """Números críticos do texto: [{tipo, norma, literal, ini, fim}]. CNPJ só com DV válido; data só de calendário;
    valor R$ 0,00 fica de fora (não carrega prova). `tolerante` = leitura de conferência (aceita '1.234.56')."""
    t = texto or ""
    out: list[dict] = []

    def add(tipo, norma, m, g=0):
        if norma:
            out.append({"tipo": tipo, "norma": norma, "literal": m.group(g), "ini": m.start(g), "fim": m.end(g)})

    for m in _RX_CNPJ.finditer(t):
        add("cnpj", normalizar("cnpj", m.group(0)), m)
    for m in (_RX_VALOR_TOLERANTE if tolerante else _RX_VALOR).finditer(t):
        n = _valor_norma(m.group(1), tolerante=tolerante)
        if n and float(n) > 0:
            add("valor", n, m, 1)
    for m in _RX_DATA.finditer(t):
        add("data", _data_norma(*m.groups()), m)
    for m in _RX_PROCESSO.finditer(t):
        add("processo", normalizar("processo", m.group(0)), m)
    for tipo, rx in (("contrato", _RX_CONTRATO), ("ata", _RX_ATA)):
        for m in rx.finditer(t):
            add(tipo, f"{int(m[1])}/{_ano(m[2])}", m)
    for m in _RX_NF.finditer(t):
        add("nf", m[1].lstrip("0") or None, m, 1)
    return out


def _chaves(numeros: list[dict]) -> set[tuple[str, str]]:
    return {(n["tipo"], n["norma"]) for n in numeros}


# ── registro durável ─────────────────────────────────────────────────────────────────────────────
_cache: dict = {"mtime": None, "tam": None, "auto": {}, "humano": {}}


def _carregar() -> tuple[dict, dict]:
    """{(tag, i, tipo, norma): entrada} da decisão automática e da humana — relido só quando o arquivo muda."""
    try:
        st = LEDGER.stat()
    except OSError:
        return {}, {}
    if _cache["mtime"] == st.st_mtime_ns and _cache["tam"] == st.st_size and _cache.get("caminho") == str(LEDGER):
        return _cache["auto"], _cache["humano"]
    auto, humano = {}, {}
    with LEDGER.open(encoding="utf-8") as f:
        for ln in f:
            try:
                e = json.loads(ln)
                k = (str(e["tag"]), int(e["i"]), e["tipo"], e["norma"])
            except (ValueError, KeyError, TypeError):
                continue
            (humano if e.get("por") else auto)[k] = e
    _cache.update(mtime=st.st_mtime_ns, tam=st.st_size, auto=auto, humano=humano, caminho=str(LEDGER))
    return auto, humano


def registrar(entradas: list[dict]) -> int:
    """Acrescenta ao registro, sob trava de arquivo (vários escritores: lote automático e `marcar`)."""
    if not entradas:
        return 0
    from compliance_agent.llm.arquivo_estado import trava
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    agora = time.strftime("%F %T")
    with trava(LEDGER.with_name(LEDGER.name + ".lock"), 60) as pegou:
        if not pegou:
            raise TimeoutError(f"{LEDGER.name}: trava ocupada")
        with LEDGER.open("a", encoding="utf-8") as f:
            for e in entradas:
                f.write(json.dumps({"em": agora, **e}, ensure_ascii=False) + "\n")
    return len(entradas)


def decisao(tag: str, i, tipo: str, norma: str) -> dict | None:
    """A entrada que vale para o número: a humana, se houver; senão a automática; senão None (nunca conferido)."""
    auto, humano = _carregar()
    k = (str(tag), int(i), tipo, norma)
    return humano.get(k) or auto.get(k)


def estado(tag: str, i, tipo: str, norma: str) -> str:
    e = decisao(tag, i, tipo, norma)
    return str(e.get("estado")) if e and e.get("estado") in ESTADOS else "a_conferir"


# ── a trava (consumidores) ───────────────────────────────────────────────────────────────────────
def vale_como_prova(tag: str, doc: dict | None, tipo: str, valor) -> bool:
    """O número lido deste documento pode ser usado como PROVA? Documento que não é de IA: sim (inalterado).
    Documento de IA: só se o número está `confirmado` no registro."""
    if not eh_ocr_ia(doc):
        return True
    n = normalizar(tipo, valor)
    if n is None:
        return False
    try:
        return estado(tag, (doc or {}).get("i"), tipo, n) == "confirmado"
    except (TypeError, ValueError):
        return False


def nao_confirmados(tag: str, doc: dict | None, texto: str) -> list[dict]:
    """Os números críticos do texto de um documento de IA que ainda NÃO são prova ([] para documento que não é de IA)."""
    if not eh_ocr_ia(doc):
        return []
    i = (doc or {}).get("i")
    try:
        return [n for n in extrair(texto) if estado(tag, i, n["tipo"], n["norma"]) != "confirmado"]
    except (TypeError, ValueError):
        return extrair(texto)


def mascarar(texto: str, numeros: list[dict]) -> str:
    """Troca cada ocorrência (pela posição) por `⟦a conferir⟧` — o resto do texto fica intacto."""
    t, fim = texto or "", -1
    trechos = []
    for n in sorted(numeros, key=lambda x: (x["ini"], -x["fim"])):   # sobreposto (nº dentro de "Contrato nº …"): o maior
        if n["ini"] >= fim:
            trechos.append(n)
            fim = n["fim"]
    for n in reversed(trechos):
        t = t[:n["ini"]] + MARCA + t[n["fim"]:]
    return t


def texto_para_prova(pasta: Path | str, doc: dict | None, texto: str) -> str:
    """O texto que um EXTRATOR DE PROVA pode ler: igual ao original fora dos documentos de IA; nos de IA, cada número
    crítico ainda não confirmado vira `⟦a conferir⟧` (o número some da prova, não do acervo: quem LÊ o processo usa
    `acervo_texto.ler`). Ausência aqui é 'a conferir', nunca zero."""
    if not eh_ocr_ia(doc):
        return texto
    return mascarar(texto, nao_confirmados(Path(pasta).name, doc, texto))


def mascarar_por_chaves(texto: str, chaves: set[tuple[str, str]]) -> str:
    """Mascara, num texto qualquer (janela montada de vários documentos), os números cujas (tipo, norma) estão em
    `chaves` — para quando já não se sabe de que documento veio cada trecho."""
    if not chaves:
        return texto
    return mascarar(texto, [n for n in extrair(texto) if (n["tipo"], n["norma"]) in chaves])


def numeros_a_conferir_do_processo(tag: str) -> set[tuple[str, str]]:
    """(tipo, norma) dos números NÃO confirmados nos documentos de IA do processo, menos os que um documento NÃO-IA
    do mesmo processo também traz (vazio se não há documento de IA — o caso comum, que nem lê os textos)."""
    from compliance_agent.sei import acervo_texto
    pasta = acervo_texto.RAIZ / tag
    docs = [d for d in (acervo_texto.manifesto(pasta) or {}).get("docs") or [] if isinstance(d, dict)]
    if not any(eh_ocr_ia(d) for d in docs):
        return set()
    out: set[tuple[str, str]] = set()
    for d in docs:
        if eh_ocr_ia(d):
            out |= _chaves(nao_confirmados(tag, d, acervo_texto.ler(pasta, d)))
    for d in docs:
        if out and not eh_ocr_ia(d):
            out -= _chaves(extrair(acervo_texto.ler(pasta, d)))
    return out


# ── confirmação automática ───────────────────────────────────────────────────────────────────────
def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _parecido(tipo: str, a: str, b: str) -> bool:
    """Leitura vizinha do mesmo número: mesmo tipo, até 2 caracteres trocados e tamanho quase igual."""
    if tipo == "data":
        return a != b and sum(x != y for x, y in zip(a, b)) <= 2
    da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    return a != b and abs(len(da) - len(db)) <= 1 and len(da) >= 3 and _lev(da, db) <= 2


# tipos que podem ser confirmados por OUTRO documento do processo (os curtos coincidem por acaso)
_TIPOS_OUTRO_DOC = {"cnpj", "processo", "contrato", "ata", "valor"}
_VALOR_MIN_OUTRO_DOC = 100.0


def confirmar_numeros(numeros: list[dict], leituras: dict[str, str], externos: dict[str, set] | None = None,
                      outros_docs: dict[str, set] | None = None) -> list[dict]:
    """Decide cada número da IA contra as fontes independentes.

    leituras    {fonte: texto} — segunda leitura do MESMO documento (Tesseract, nativo, outro motor)
    externos    {fonte: {(tipo, norma)}} — SIAFE do mesmo processo
    outros_docs {fonte: {(tipo, norma)}} — documentos NÃO-IA do mesmo processo
    Devolve [{tipo, norma, literal, estado, fonte?, leitura_2?, fontes_tentadas}] — um por (tipo, norma)."""
    externos, outros_docs = externos or {}, outros_docs or {}
    lidos = {f: extrair(t, tolerante=True) for f, t in leituras.items()}
    chaves_lidas = {f: _chaves(ns) for f, ns in lidos.items()}
    tentadas = sorted(leituras) + sorted(externos) + sorted(outros_docs)
    out, vistos = [], set()
    for n in numeros:
        k = (n["tipo"], n["norma"])
        if k in vistos:
            continue
        vistos.add(k)
        r = {"tipo": n["tipo"], "norma": n["norma"], "literal": n["literal"], "fontes_tentadas": tentadas}
        fonte = next((f for f, ks in chaves_lidas.items() if k in ks), None) \
            or next((f for f, ks in externos.items() if k in ks), None)
        if fonte is None and n["tipo"] in _TIPOS_OUTRO_DOC and (
                n["tipo"] != "valor" or float(n["norma"]) >= _VALOR_MIN_OUTRO_DOC):
            fonte = next((f for f, ks in outros_docs.items() if k in ks), None)
        if fonte:
            out.append({**r, "estado": "confirmado", "fonte": fonte})
            continue
        vizinho = next(((f, x["norma"], x["literal"]) for f, ns in lidos.items() for x in ns
                        if x["tipo"] == n["tipo"] and _parecido(n["tipo"], n["norma"], x["norma"])), None)
        if vizinho:
            out.append({**r, "estado": "divergente", "fonte": vizinho[0], "leitura_2": vizinho[1],
                        "literal_2": vizinho[2]})
        else:
            out.append({**r, "estado": "a_conferir"})
    return out


def fontes_externas(numero_sei: str, con=None) -> dict[str, set]:
    """{(tipo, norma)} do SIAFE no MESMO processo: valor e credor das OB pagas e das NE. Base indisponível → {}
    (a fonte simplesmente não confirma; nada vira zero)."""
    import sqlite3
    from compliance_agent.ob_processo import chave_processo, obs_por_processo
    proprio = con is None
    try:
        con = con or sqlite3.connect(f"file:{DATA / 'compliance.db'}?mode=ro", uri=True, timeout=60)
    except sqlite3.Error:
        return {}
    out: dict[str, set] = {}
    try:
        k = chave_processo(numero_sei)
        if not k:
            return {}
        # autos=False: a camada dos autos lê o PRÓPRIO acervo (inclusive o documento da IA) — não é fonte externa
        res = obs_por_processo(con, [numero_sei], autos=False).get(k) or {}
        ob = set()
        for o in res.get("obs") or []:
            if o.get("valor"):
                ob.add(("valor", f"{float(o['valor']):.2f}"))
            c = normalizar("cnpj", o.get("credor"))
            if c:
                ob.add(("cnpj", c))
        if ob:
            out["siafe_ob"] = ob
        ne = set()
        try:
            un, num, _ = k.split("/")
            rows = con.execute("SELECT processo, credor, valor FROM ne_siafe WHERE processo LIKE ?",
                               (f"%{int(un)}%/%{int(num)}%",)).fetchall()
        except (sqlite3.Error, ValueError):
            rows = []
        for proc, credor, valor in rows:
            if chave_processo(proc) != k:
                continue
            if valor:
                ne.add(("valor", f"{abs(float(valor)):.2f}"))
            c = normalizar("cnpj", credor)
            if c:
                ne.add(("cnpj", c))
        if ne:
            out["siafe_ne"] = ne
        return out
    except sqlite3.Error:
        return out
    finally:
        if proprio:
            con.close()


def outros_documentos(pasta: Path, i_alvo) -> dict[str, set]:
    """{(tipo, norma)} de cada documento NÃO-IA do processo (texto nativo ou Tesseract), menos o próprio alvo."""
    from compliance_agent.sei import acervo_texto
    man = acervo_texto.manifesto(pasta) or {}
    out: dict[str, set] = {}
    for d in man.get("docs") or []:
        if not isinstance(d, dict) or eh_ocr_ia(d) or str(d.get("i")) == str(i_alvo):
            continue
        t = acervo_texto.ler(pasta, d)
        if t.strip():
            ks = _chaves(extrair(t))
            if ks:
                out[f"documento_{d.get('i')}"] = ks
    return out


def leituras_ao_lado(pasta: Path, doc: dict) -> dict[str, str]:
    """Textos de OUTROS motores já guardados ao lado do canônico (`.gpu.txt`, `.reserva.txt`, `.tesseract.txt`) —
    menos o do próprio motor do documento (a mesma leitura não confirma a si mesma)."""
    from compliance_agent.sei import acervo_texto
    rel = doc.get("texto")
    if not rel:
        return {}
    base = Path(pasta) / rel
    proprio = "gpu" if str(doc.get("ocr_motor") or "").startswith("surya") else "reserva"
    out = {}
    for nome in ("gpu", "reserva", "tesseract"):
        if nome == proprio:
            continue
        p = base.with_suffix(f".{nome}.txt")
        try:
            t = acervo_texto.sem_etiqueta(p.read_text(encoding="utf-8", errors="ignore"), str(doc.get("titulo") or ""))
        except OSError:
            continue
        if len(t.strip()) >= acervo_texto.MIN_CHARS_CONTEUDO:
            out[{"gpu": "surya_ao_lado", "reserva": "reserva_ao_lado", "tesseract": "tesseract_ao_lado"}[nome]] = t
    return out


# ── segunda leitura do PDF (Tesseract da casa / texto nativo da página) ──────────────────────────────────────────
_RX_PAGINA = re.compile(r"^\[página (\d+)\]\s*$", re.M)


def paginas_da_ia(bruto: str) -> dict[int, str]:
    """Texto por página da entrega crua do trabalhador da GPU (`NNN.ocr_gpu.txt`, marcadores `[página N]`)."""
    partes = _RX_PAGINA.split(bruto or "")
    return {int(partes[k]): partes[k + 1] for k in range(1, len(partes) - 1, 2)}


def paginas_com(numeros: list[dict], por_pagina: dict[int, str]) -> list[int]:
    """Páginas (1-based) onde a IA leu algum dos números — só elas vão à segunda leitura."""
    ks = _chaves(numeros)
    return sorted(p for p, t in por_pagina.items() if ks & _chaves(extrair(t)))


def _pagina_nativa(pg) -> bool:
    """Mesmo critério do trabalhador da GPU (`ocr_gpu_worker.pagina_nativa`): texto visível ≥ 200, sem camada
    invisível de OCR antigo, imagens < 10% da página. Página nativa: o texto do PDF é a verdade."""
    area = abs(pg.rect) or 1.0
    cobertura = sum(abs(r & pg.rect) for x in pg.get_images() for r in pg.get_image_rects(x[0])) / area
    invisivel = any(s.get("type") == 3 for s in pg.get_texttrace())
    return cobertura < 0.10 and not invisivel and len(pg.get_text().strip()) >= 200


def ler_pdf(pdf: Path | str, paginas: list[int] | None = None, max_paginas: int = 20,
            dpi: int = 200) -> dict:
    """Segunda leitura INDEPENDENTE do PDF: página nativa → texto do PDF; escaneada → Tesseract da casa (`por`,
    pré-processamento e melhor-dos-dois de `ocr_docs._ocr_tesseract`, 200 dpi como a GPU). Nunca a GPU (o
    `_ocr_pil` da casa a usaria quando `JFN_OCR_GPU_URL` existe — seria o mesmo motor confirmando a si mesmo).
    Devolve {leituras: {fonte: texto}, paginas: [...], segundos: {pagina: s}}."""
    import fitz
    from PIL import Image
    from compliance_agent.sei.ocr_docs import _ocr_tesseract
    textos: dict[str, list[str]] = {"tesseract": [], "pdf_nativo": []}
    seg: dict[int, float] = {}
    with fitz.open(pdf) as doc:
        alvo = [p for p in (paginas or range(1, doc.page_count + 1)) if 1 <= p <= doc.page_count][:max_paginas]
        for p in alvo:
            t0 = time.monotonic()
            pg = doc.load_page(p - 1)
            if _pagina_nativa(pg):
                textos["pdf_nativo"].append(pg.get_text())
            else:
                pix = pg.get_pixmap(dpi=dpi)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples) if pix.n < 4 else \
                    Image.frombytes("RGBA", (pix.width, pix.height), pix.samples).convert("RGB")
                textos["tesseract"].append(_ocr_tesseract(img, "por"))
            seg[p] = round(time.monotonic() - t0, 2)
    return {"leituras": {f: "\n".join(ts) for f, ts in textos.items() if any(x.strip() for x in ts)},
            "paginas": alvo, "segundos": seg}
