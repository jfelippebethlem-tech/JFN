# -*- coding: utf-8 -*-
"""FOTO × QUANTITATIVO — a foto da medição prova que o serviço medido existe, e na quantidade cobrada?

Pedido do dono (18/11/2026): *"essas fotos têm que comprovar quantitativo também"*. `foto_medicao` responde se
a foto é RECICLADA e se bate com o OBJETO; aqui o confronto é com o BOLETIM: item por item, período por período.

Desenho (determinístico primeiro, visão só onde ele apontar):

  1. **Pareamento por medição** (`medicoes`): no processo, os documentos se agrupam pelo nº da medição do título
     ("7ª Medição", "MEDIÇÃO 11°", "BOLETIM MEDIÇÃO 4°"); sem número, pela vizinhança na árvore (a planilha abre
     o pacote, relatório/diário/atestado que vêm logo depois pertencem a ele). Cada pacote leva as NL citadas nos
     títulos entre ele e o próximo — é por elas que a OB do SIAFE se liga à medição.
  2. **Itens do boletim** (`itens_boletim`): só entra item cuja ARITMÉTICA FECHA (qtd × preço ≈ valor, e
     anterior + período ≈ acumulado). Número que não fecha é leitura quebrada, não achado — e o item fica de fora,
     declarado, em vez de virar "quantidade divergente".
  3. **Legendas** do relatório fotográfico: texto da página (e OCR). O casamento foto↔item é por CÓDIGO de serviço
     (EMOP/SCO/SINAPI) ou por LOCAL — nunca por palavra solta, que casa "escavação" com qualquer coisa.
  4. **Graduação**: foto quase nunca PROVA quantidade. "A foto não permite aferir" é LACUNA DE FISCALIZAÇÃO
     (documental), não superfaturamento. Contradição só com prova positiva no próprio processo (acumulado acima
     do contratado no boletim; legenda com período fora; contagem completa menor que a medida).
  5. **Porquê** de cada sinal (`porque`): volta ao processo atrás da explicação e cita o trecho — aditivo que muda o
     quantitativo, item que pela natureza não se fotografa (mão de obra, administração, hora de equipamento), nota
     do fiscal. Classes: inocente-comprovada · inocente-provável · sem-explicação · contradição.

Indício a apurar, não acusação. INDISPONÍVEL ≠ 0: medição sem boletim legível não é medição sem item.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASE_ACERVO = REPO / "data" / "sei_arquivo"
BASE_CACHE = REPO / "data" / "sei_cache"

RESSALVA = ("indício a apurar, não acusação; foto raramente prova quantidade — 'não permite aferir' é lacuna "
            "documental de fiscalização, não superfaturamento; INDISPONÍVEL ≠ 0; só OB Contabilizada (SIAFE) é pago")


def _sa(s: str) -> str:
    """minúsculo e sem acento."""
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


# ── papel do documento na medição ─────────────────────────────────────────────────────────────────────────────
_RX_RELATORIO = re.compile(r"fotogr")
_RX_DIARIO = re.compile(r"diario\s*(de|da)?\s*obras?\b|\brdo\b|relatorio diario")
_RX_MEMORIA = re.compile(r"memoria\s+(de\s+)?calculo")
_RX_ACEITE = re.compile(r"parecer tecnico|atestado|\batesto\b|termo de recebimento|termo de aceite")
_RX_BOLETIM = re.compile(r"boletim|planilha|planiha|\bmedicao\b|\bmed\b")
# Peças do pacote da medição que NÃO são o boletim de quantidades (medido no acervo, 18/11/2026).
_RX_NAO_BOLETIM = re.compile(r"carta|encaminha|checklist|guia|\biss\b|nota[s]? fisca|notas ficais|certid|manifesto"
                             r"|cronograma|funcionar|folha|croqui|\bdmt\b|controle tecnol|nota tecnica|drenagem"
                             r"|fgts|gfip|previd|requerimento|oficio|despacho|e-?mail|comprovante|recibo|declarac")


def papel_do_titulo(titulo: str) -> str | None:
    """'relatorio' · 'diario' · 'memoria' · 'aceite' · 'boletim' · None (peça que não entra no confronto)."""
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", _sa(titulo)))
    if _RX_RELATORIO.search(t):
        return "relatorio"
    if _RX_DIARIO.search(t):
        return "diario"
    if _RX_MEMORIA.search(t):
        return "memoria"
    if _RX_ACEITE.search(t):
        return "aceite"
    if _RX_BOLETIM.search(t) and not _RX_NAO_BOLETIM.search(t):
        return "boletim"
    return None


# "7ª Medição", "MEDIÇÃO 11°", "BOLETIM MEDIÇÃO 4°", "Planiha de Medição 07°.", "13ª MED". Ordinal obrigatório OU
# o número colado depois de "medição" — "Anexo 4.1" e "Anexo 02" não são número de medição.
_RX_N_ORDINAL = re.compile(r"(\d{1,3})\s*[ªº°]\s*(?:medi|med\b|etapa|bm\b)", re.I)
_RX_N_DEPOIS = re.compile(r"medi[cç][aã]o\s*(?:n[º°o.]*\s*)?(\d{1,3})\s*[ªº°]?(?!\s*[/.,]?\d)", re.I)
_RX_N_BM = re.compile(r"\bBM\s*(?:n[º°o.]*\s*)?(\d{1,3})\b")


def numero_medicao(titulo: str) -> int | None:
    t = titulo or ""
    t = re.sub(r"\(\d{6,}\)\s*$", "", t)  # nº SEI do documento no fim do título
    for rx in (_RX_N_ORDINAL, _RX_N_DEPOIS, _RX_N_BM):
        m = rx.search(t)
        if m and 0 < int(m.group(1)) < 200:
            return int(m.group(1))
    return None


_RX_NL = re.compile(r"\b(20\d\d)\s*NL\s*0*(\d{1,6})\b", re.I)
_RX_OB = re.compile(r"\b(20\d\d)\s*OB\s*0*(\d{1,6})\b", re.I)


def _num_siafe(m: re.Match, tipo: str) -> str:
    return f"{m.group(1)}{tipo}{int(m.group(2)):05d}"


# ── texto do documento ───────────────────────────────────────────────────────────────────────────────────────

def texto_doc(pasta: Path, doc: dict, com_ocr: bool = True) -> str:
    """Texto do arquivo (sem a etiqueta) + OCR do cache, quando existir e trouxer algo a mais."""
    from compliance_agent.sei import acervo_texto
    t = acervo_texto.ler(pasta, doc) if doc.get("texto") else ""
    if com_ocr:
        tag = Path(pasta).name
        i = doc.get("i")
        if isinstance(i, int):
            for suf in (".ocr_gpu.txt", ".ocr.txt"):
                f = BASE_CACHE / f"integra_{tag}" / f"{i:03d}{suf}"
                if f.is_file():
                    try:
                        o = f.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    if len(o.strip()) > 40 and o.strip()[:200] not in t:
                        t = (t + "\n\n[OCR]\n" + o) if t.strip() else o
                    break
    # NBSP (\xa0) separa as palavras da legenda em parte dos relatórios ("RIO\xa0DAS\xa0OSTRAS\xa0– RIO\xa0JUNDIÁ",
    # 12ª medição da Geo): sem normalizar, a linha não casa como local e a frente "some" do relatório.
    return t.replace("\xa0", " ").replace("\u202f", " ")


def _manifesto(pasta: Path) -> dict:
    try:
        return json.loads((Path(pasta) / "manifest.json").read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError):
        return {}


# ── pareamento por medição ───────────────────────────────────────────────────────────────────────────────────
JANELA_SEM_NUMERO = 12   # docs depois da planilha sem nº que ainda pertencem ao pacote dela


def medicoes(pasta: Path | str) -> list[dict]:
    """Pacotes de medição do processo: {'n', 'boletim', 'memoria', 'relatorio', 'diario', 'aceite', 'nl', 'ob'}.

    Cada lista guarda os docs do manifesto (dict com 'i', 'titulo', 'fotos'). 'n' é o nº da medição (None quando
    o título não o diz e o pacote foi montado por vizinhança)."""
    pasta = Path(pasta)
    docs = [d for d in (_manifesto(pasta).get("docs") or []) if isinstance(d, dict) and isinstance(d.get("i"), int)]
    docs.sort(key=lambda d: d["i"])
    pacotes: dict = {}
    ordem: list = []
    aberto = None       # chave do último pacote aberto por vizinhança
    ultimo_i = -999

    def _novo(ch, n):
        pacotes[ch] = {"n": n, "boletim": [], "memoria": [], "relatorio": [], "diario": [], "aceite": [],
                       "nl": [], "ob": [], "_i0": None}
        ordem.append(ch)

    for d in docs:
        tit = str(d.get("titulo") or "")
        papel = papel_do_titulo(tit)
        n = numero_medicao(tit)
        if papel is None:
            # NL/OB no título: pertencem ao último pacote aberto (o processo de pagamento segue a medição)
            if ordem:
                ult = pacotes[ordem[-1]]
                ult["nl"] += [_num_siafe(m, "NL") for m in _RX_NL.finditer(tit)]
                ult["ob"] += [_num_siafe(m, "OB") for m in _RX_OB.finditer(tit)]
            continue
        if n is not None:
            ch = ("n", n)
            if ch not in pacotes:
                _novo(ch, n)
            elif ordem[-1] != ch:          # pacote reaberto mais adiante (complementar, retificação)
                ordem.remove(ch)
                ordem.append(ch)
            aberto = None
        else:
            if papel == "boletim" and (aberto is None or pacotes[aberto]["boletim"]
                                       and d["i"] - ultimo_i > 1):
                ch = ("v", d["i"])
                _novo(ch, None)
                aberto = ch
            elif aberto is not None and d["i"] - pacotes[aberto]["_i0"] <= JANELA_SEM_NUMERO:
                ch = aberto
            elif ordem and pacotes[ordem[-1]]["_i0"] is not None and d["i"] - pacotes[ordem[-1]]["_i0"] <= JANELA_SEM_NUMERO:
                ch = ordem[-1]
            else:
                ch = ("v", d["i"])
                _novo(ch, None)
                aberto = ch
        p = pacotes[ch]
        if p["_i0"] is None:
            p["_i0"] = d["i"]
        p[papel].append(d)
        ultimo_i = d["i"]
    out = []
    for ch in ordem:
        p = pacotes[ch]
        p.pop("_i0", None)
        p["nl"] = sorted(set(p["nl"]))
        p["ob"] = sorted(set(p["ob"]))
        out.append(p)
    return out


# ── itens do boletim (só os que a aritmética fecha) ───────────────────────────────────────────────────────────
_UNIDADES = {
    "m", "m2", "m²", "m3", "m³", "un", "und", "unid", "unidade", "u", "pc", "pç", "peca", "h", "hr", "hs", "hora",
    "mes", "mês", "meses", "kg", "t", "ton", "tonelada", "vb", "cj", "conj", "l", "km", "ha", "dia", "dias", "ml",
    "m3xkm", "m³xkm", "txkm", "t.km", "tkm", "m3.km", "unxmes", "un x mês", "un x mes", "unxmês", "sc", "gl", "par",
    "pt", "ponto", "jg", "jogo", "cx", "rl", "kit", "lote", "verba", "diaria", "diária", "h/mes", "mes/h", "m2xmes",
    "m²xmês", "m2xmês", "unid/mes", "kwh", "kw", "dm3", "cm", "mxmes", "hxmes", "%",
}
_RX_ITEM = re.compile(r"^\d{1,2}(?:\.\d{1,3}){1,3}\.?(?:-[A-Z]{1,2})?$")   # "1.7-P"/"1.7-I": hora produtiva/improdutiva
_RX_COD = re.compile(r"\b(\d{2})\s?\.\s?(\d{3})\s?\.\s?(\d{3,4})\s?[- ]\s?(\w)\b")
_RX_NUM_BR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{1,6}$|^-?\d+,\d{1,6}$")
_RX_NUM_PT = re.compile(r"^-?\d{1,3}(?:\.\d{3})*\.\d{2}$")   # OCR com ponto decimal: "17.582.02", "8.00"
_RX_INT = re.compile(r"^-?\d{1,7}$")
TOL_REL = 0.012          # 1,2%: arredondamento de preço unitário com 2 casas
TOL_ABS = 0.05


def _num(tok: str, ponto_decimal: bool = True) -> float | None:
    t = tok.strip().replace("R$", "").replace(" ", "").strip()
    if t in {"-", "–", "—"}:
        return 0.0
    if _RX_NUM_BR.match(t):
        return float(t.replace(".", "").replace(",", "."))
    if ponto_decimal and _RX_NUM_PT.match(t):
        a, b = t.rsplit(".", 1)
        return float(a.replace(".", "") + "." + b)
    if _RX_INT.match(t):
        return float(t)
    return None


def _perto(a: float, b: float, tol_rel: float = TOL_REL) -> bool:
    return abs(a - b) <= max(TOL_ABS, tol_rel * max(abs(a), abs(b)))


def _tokens(texto: str) -> list[str]:
    out = []
    for linha in texto.splitlines():
        for t in re.split(r"\s*\|\s*|\s{2,}|\t", linha.strip()):
            t = t.strip()
            if t:
                out.append(t)
    return out


def _unidade(tok: str) -> str | None:
    t = re.sub(r"\s+", " ", tok.strip().lower())
    t2 = t.replace(" ", "")
    if t in _UNIDADES or t2 in _UNIDADES:
        return t2
    return None


def _interpretar(nums: list[float]) -> dict | None:
    """Do bloco numérico depois da unidade, (qc, pu, total) e, quando a conta fecha, anterior/período/acumulado/saldo."""
    k = None
    for a in range(0, min(len(nums) - 2, 6)):
        if nums[a] > 0 and nums[a + 1] > 0 and _perto(nums[a] * nums[a + 1], nums[a + 2]):
            k = a
            break
    if k is None:
        return None
    qc, pu, total = nums[k], nums[k + 1], nums[k + 2]
    # 2º preço (orçado × contratado, 020001): a mesma qtd fecha também com o par seguinte — vale o último
    if k + 4 < len(nums) and nums[k + 3] > 0 and _perto(qc * nums[k + 3], nums[k + 4]):
        pu, total = nums[k + 3], nums[k + 4]
        k += 2
    resto = nums[k + 3:]
    # pares (qtd, valor) intercalados: valor ≈ qtd × pu (070002: anterior · período · acumulado · saldo)
    pares, j = [], 0
    while j + 1 < len(resto) and _perto(resto[j] * pu, resto[j + 1], 0.02):
        pares.append(resto[j])
        j += 2
    qs = pares if len(pares) >= 2 else resto
    item = {"qc": qc, "pu": pu, "total": total, "ant": None, "per": None, "acum": None, "saldo": None,
            "fecha": ["qc×pu=total"]}
    for a in range(len(qs) - 2):
        x, y, z = qs[a], qs[a + 1], qs[a + 2]
        if not _perto(x + y, z, 0.005):
            continue
        com_saldo = a + 3 < len(qs) and _perto(z + qs[a + 3], qc, 0.005)
        # x + 0 = x é trivial (qualquer número seguido de zero e de si mesmo): só vale com o saldo confirmando
        # (020001/002796/2025: "23.942,48 | 0 | 23.942,48" era VALOR em R$, lido como 23.942 placas)
        if not ((x > 0 and y > 0) or com_saldo):
            continue
        item.update(ant=x, per=y, acum=z)
        item["fecha"].append("ant+per=acum")
        if com_saldo:
            item["saldo"] = qs[a + 3]
            item["fecha"].append("acum+saldo=contratado")
        break
    if item["acum"] is None:
        # SEHIS: "saldo antes | medido | saldo atual | acumulado" — saldo antes − medido = saldo atual
        for a in range(len(qs) - 2):
            x, y, z = qs[a], qs[a + 1], qs[a + 2]
            if x > 0 and y > 0 and _perto(x - y, z, 0.005) and x <= qc * 1.0001:
                item.update(ant=round(qc - x, 6), per=y, acum=round(qc - z, 6), saldo=z)
                item["fecha"].append("saldo_ant−per=saldo")
                break
    if item["acum"] is None:
        pares_ok = [(a, qs[a], qs[a + 1]) for a in range(len(qs) - 1)
                    if _perto(qs[a] + qs[a + 1], qc, 0.005) and not (a == 0 and _perto(qs[a], qc) and qs[a + 1] == 0)]
        # acumulado positivo antes do par trivial (0 | contratado), que casa com "saldo atual 0 | acumulado = total"
        pares_ok.sort(key=lambda t: (t[1] <= 0, t[0]))
        if pares_ok:
            _a, z, s = pares_ok[0]
            item.update(acum=z, saldo=s)
            item["fecha"].append("acum+saldo=contratado")
    if len(pares) >= 2 and item["acum"] is not None:
        item["fecha"].append("qtd×pu=valor em cada coluna")
    return item


def itens_boletim(texto: str) -> list[dict]:
    """Itens do boletim cuja aritmética fecha. Cada um: item, codigo, descricao, unidade, qc, pu, total,
    ant, per, acum, saldo, fecha (as identidades conferidas)."""
    toks = _tokens(texto or "")
    # documento em vírgula decimal não tem número "1.10": ali isso é o próximo ITEM, não 1,1
    n_br = sum(1 for t in toks if _RX_NUM_BR.match(t.replace("R$", "").strip()))
    n_pt = sum(1 for t in toks if _RX_NUM_PT.match(t.replace("R$", "").strip()))
    pd = n_pt > n_br
    out, vistos = [], set()
    i = 0
    while i < len(toks):
        # item "1.1"/"1.7-P"; ou inteiro "1" quando o código vem logo depois ("1 | 13.373.0020-0 | PISO…", SEHIS)
        if not (_RX_ITEM.match(toks[i]) or (re.fullmatch(r"\d{1,3}", toks[i]) and i + 1 < len(toks)
                                            and _RX_COD.fullmatch(toks[i + 1].strip()))):
            i += 1
            continue
        item_n = toks[i].rstrip(".")
        j, desc, cod = i + 1, [], None
        while j < len(toks) and j - i < 150:   # descrição palavra por linha (SEHIS) passa de 60 tokens
            u = _unidade(toks[j])
            if u and desc:
                break
            if _RX_ITEM.match(toks[j]) and desc and not (j + 1 < len(toks) and _unidade(toks[j + 1])):
                break        # próximo item (e não "8.00 | MÊS", quantidade em OCR de ponto decimal)
            m = _RX_COD.search(toks[j])
            if m and cod is None:
                cod = f"{m.group(1)}.{m.group(2)}.{m.group(3)}-{m.group(4)}".upper()
            if _num(toks[j], pd) is None:
                desc.append(toks[j])
            j += 1
        else:
            i += 1
            continue
        if j >= len(toks) or not _unidade(toks[j]):
            i += 1
            continue
        uni = _unidade(toks[j])
        # "… SERVIÇOS TOPOGRÁFICOS | 8.00 | MÊS | R$ 17.582.02 | R$ 105.372.12" (330001): a quantidade vem ANTES
        q_antes = _num(toks[j - 1], pd) if j - 1 > i else None
        nums, k = [], j + 1
        while k < len(toks) and len(nums) < 40:
            t = toks[k]
            if t.upper() in {"R$", "R$ -", "R$-"}:
                k += 1
                continue
            if _RX_ITEM.match(t) and k + 1 < len(toks) and _num(toks[k + 1], pd) is None:
                break            # "5.08 | SARJETA…": é o próximo item, não um número
            v = _num(t, pd)
            if v is None:
                break
            nums.append(v)
            k += 1
        it = _interpretar(nums) if len(nums) >= 3 else None
        if it is None and q_antes is not None and len(nums) >= 2:
            it = _interpretar([q_antes] + nums)
        if it is not None:
            chave = (item_n, round(it["qc"], 3), round(it["pu"], 2))
            if chave not in vistos:
                vistos.add(chave)
                d = " ".join(x for x in desc if not _RX_COD.fullmatch(x.strip()))
                out.append({"item": item_n, "codigo": cod, "descricao": re.sub(r"\s+", " ", d).strip()[:300],
                            "unidade": uni, **it})
            i = k
        else:
            i += 1
    return out


# ── LOCAIS: frente de serviço medida × frente fotografada ─────────────────────────────────────────────────────
# Contrato medido por HORA de equipamento em várias frentes (INEA, desassoreamento: memória de cálculo
# "BUZIOS - RIO ARETÊ … 1,00 un x 176,00 h x 70%") só casa com o relatório pelo LOCAL da legenda
# ("BUZIOS – CANAL DO ARETÊ"). Mesma frente escrita de jeitos diferentes: ordem trocada ("CANAL MARIMBONDO – CABO
# FRIO" × "CABO FRIO - CANAL MARIMBOMDO"), tipo do corpo hídrico trocado (rio × canal) e erro de digitação.
_RX_LOCAL = re.compile(r"^\s*([A-ZÀ-Ü][A-ZÀ-Ü .'/()]{2,40}?)\s+[-–—]\s+([A-ZÀ-Ü0-9][A-ZÀ-Ü0-9 .'/()]{2,50}?)\s*$")
_GENERICO_LOCAL = {"rio", "canal", "lagoa", "braco", "corrego", "valao", "vala", "rua", "av", "avenida", "estrada",
                   "do", "da", "de", "dos", "das", "e", "est", "bota", "fora", "trecho", "margem", "foz", "ponte"}
_NAO_LOCAL = re.compile(r"medicao|contrato|periodo|relatorio|governo|secretaria|instituto|diretor|cnpj|processo"
                        r"|pagina|item|total|inclusive|motor|capacidade|escavadeira|caminhao|regiao hidrografica")


def _toks_local(s: str) -> frozenset:
    return frozenset(t for t in re.findall(r"[a-z0-9]+", _sa(s)) if t not in _GENERICO_LOCAL and len(t) > 1)


def locais(texto: str) -> dict[frozenset, str]:
    """Frentes de serviço citadas como 'MUNICÍPIO - CORPO/LOGRADOURO' (linha própria, caixa alta)."""
    out: dict[frozenset, str] = {}
    for ln in (texto or "").splitlines():
        m = _RX_LOCAL.match(ln.strip())
        if not m or _NAO_LOCAL.search(_sa(ln)):
            continue
        k = _toks_local(ln)
        if len(k) >= 2:
            out.setdefault(k, re.sub(r"\s+", " ", ln.strip()))
    return out


def _ocorrencias_frente(texto_boletim: str) -> list[tuple[frozenset, str | None, float]]:
    """Quantidade que a memória atribui a cada frente, ocorrência a ocorrência.

    Dois formatos medidos na Geo Ambiental (INEA 35/2023):
      · 16ª em diante: "1.13-P | BUZIOS - CANAL ACEROLA | 19.005.0010-2 | 0 | -" (item, frente, código, nº de
        equipamentos, HORAS) — a frente do contrato aparece mesmo zerada;
      · até a 15ª: "BUZIOS - LAGOA EST. ÁLVARO GONÇALVES | Quantidade Horas % | 1,00 un x 0,00 h x 70,00% = 0,00 h".
    Ocorrência sem número reconhecível não entra (não vira zero)."""
    linhas = [ln.strip() for ln in (texto_boletim or "").splitlines() if ln.strip()]
    out: list[tuple[frozenset, str | None, float]] = []
    for k, ln in enumerate(linhas):
        m = _RX_LOCAL.match(ln)
        if not m or _NAO_LOCAL.search(_sa(ln)):
            continue
        prox = []
        for x in linhas[k + 1:k + 16]:
            if _RX_LOCAL.match(x) and not _NAO_LOCAL.search(_sa(x)):
                break       # a próxima frente começa: o número dali não é desta
            prox.append(x)
        h, cod = None, None
        if prox and _RX_COD.search(prox[0]):
            mc = _RX_COD.search(prox[0])
            cod = f"{mc.group(1)}.{mc.group(2)}.{mc.group(3)}-{mc.group(4)}".upper()
            qs = [q for q in (_num(x) for x in prox[1:3]) if q is not None]
            if qs:
                h = qs[1] if len(qs) >= 2 else qs[0]
        else:
            mm = re.search(r"=\s*(\d[\d.]*,\d+)\s*h\b", " ".join(prox), re.I)
            if mm:
                h = _num(mm.group(1))
        if h is not None:
            out.append((_toks_local(ln), cod, h))
    return out


def horas_por_frente(texto_boletim: str) -> dict[frozenset, list[float]]:
    out: dict[frozenset, list[float]] = {}
    for k, _cod, h in _ocorrencias_frente(texto_boletim):
        out.setdefault(k, []).append(h)
    return out


def valor_por_frente(texto_boletim: str, itens: list[dict]) -> dict[frozenset, dict]:
    """Horas e valor (horas × preço do item pelo código) por frente — só onde a memória dá código e horas."""
    pu = {}
    for x in itens:
        if x.get("codigo"):
            pu.setdefault(x["codigo"], x["pu"])
    out: dict = {}
    for k, cod, horas in _ocorrencias_frente(texto_boletim):
        d = out.setdefault(k, {"horas": 0.0, "valor": 0.0, "sem_preco": 0})
        d["horas"] = round(d["horas"] + horas, 2)
        if horas <= 0:
            continue
        if cod in pu:
            d["valor"] = round(d["valor"] + horas * pu[cod], 2)
        else:
            d["sem_preco"] += 1
    return out


def frentes_zeradas(texto_boletim: str) -> set[frozenset]:
    """Frentes que a memória lista só com quantidade ZERO: não foram medidas e não podem cobrar foto."""
    return {k for k, v in horas_por_frente(texto_boletim).items() if v and not any(x > 0 for x in v)}


def _parecido(a: str, b: str) -> bool:
    """mesmo token com até 1 erro de digitação (só em tokens de ≥ 5 letras: 'OSTAS' × 'OSTRAS')."""
    if a == b:
        return True
    if min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    c, l_ = (a, b) if len(a) < len(b) else (b, a)
    return any(l_[:i] + l_[i + 1:] == c for i in range(len(l_)))


def _partes_local(nome: str) -> tuple[frozenset, frozenset]:
    """(município, corpo) de 'MUNICÍPIO - CORPO' ou 'CORPO – MUNICÍPIO' (decide pelo lado que tem nome de cidade
    conhecido no outro: aqui, simplesmente devolve os dois lados)."""
    lados = re.split(r"\s+[-–—]\s+", nome, maxsplit=1)
    if len(lados) < 2:
        return _toks_local(nome), frozenset()
    return _toks_local(lados[0]), _toks_local(lados[1])


def mesma_frente_provavel(a: str, b: str) -> bool:
    """Mesmo município E pelo menos um nome próprio do CORPO em comum (com 1 erro de digitação):
    'BUZIOS - CASA DO PESCADOR' × 'BUZIOS - CANAL MERCADO DO PESCADOR'. Só município em comum NÃO basta
    ('IGUABA GRANDE - RIO UBÁS' × 'IGUABA GRANDE – CANAL BOA VISTA' são frentes diferentes)."""
    a1, a2 = _partes_local(a)
    b1, b2 = _partes_local(b)
    for (ma, ca), (mb, cb) in (((a1, a2), (b1, b2)), ((a1, a2), (b2, b1))):
        mun = bool(ma and mb) and (len(ma & mb) >= max(1, min(len(ma), len(mb)) - 1))
        corpo = any(_parecido(x, y) for x in ca for y in cb if len(x) >= 4 and len(y) >= 4)
        if mun and corpo:
            return True
    return False


def mesmo_local(a: frozenset, b: frozenset) -> bool:
    """Frente igual = os tokens próprios do MENOR conjunto aparecem (com tolerância) no outro."""
    menor, maior = (a, b) if len(a) <= len(b) else (b, a)
    return all(any(_parecido(x, y) for y in maior) for x in menor)


# ── datas: período da medição, carimbo da foto, atesto ────────────────────────────────────────────────────────
from datetime import date, timedelta  # noqa: E402

_RX_PERIODO = re.compile(
    r"per[ií]odo(?:\s+(?:medido|de\s+refer[eê]ncia|da\s+medi[cç][aã]o|de\s+execu[cç][aã]o))?\s*[:\-–]?\s*(?:de\s+)?"
    r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*(?:a|à|á|ate|até|-|–)\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", re.I)
_RX_DATA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
# carimbo de câmera/legenda: data COM hora. A assinatura do SEI ("em 09/04/2024, às 10:33") também tem hora — a
# linha dela sai pelo vocabulário.
_RX_CARIMBO = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\s*(?:[,\-–]\s*)?(?:[àa]s\s*)?(\d{1,2})[:h](\d{2})\b")
_RX_LINHA_ADMIN = re.compile(r"assinad|eletronicamente|hor[aá]rio oficial|sei\b|autenticidade|c[oó]digo verificador"
                             r"|acao=documento|decreto|juntad|inclu[ií]do|gerado|impress", re.I)


def _ano(a: str) -> int:
    v = int(a)
    return v + 2000 if v < 100 else v


def _d(dd, mm, aa) -> date | None:
    try:
        return date(_ano(aa), int(mm), int(dd))
    except (ValueError, TypeError):
        return None


def periodo(texto: str) -> tuple[date, date, str] | None:
    """(início, fim, trecho) do 1º 'Período …: dd/mm[/aaaa] a dd/mm/aaaa' do texto."""
    m = _RX_PERIODO.search(texto or "")
    if not m:
        return None
    fim = _d(m.group(4), m.group(5), m.group(6))
    if fim is None:
        return None
    ini = _d(m.group(1), m.group(2), m.group(3) or str(fim.year))
    if ini is None:
        return None
    if m.group(3) is None and ini > fim:
        ini = _d(m.group(1), m.group(2), str(fim.year - 1))
    if ini is None or ini > fim or (fim - ini).days > 400:
        return None
    return ini, fim, m.group(0)


def carimbos(texto: str) -> list[tuple[date, str]]:
    """Datas com hora fora de linha administrativa (assinatura, autenticação) — carimbo/legenda de foto."""
    out = []
    for ln in (texto or "").splitlines():
        if _RX_LINHA_ADMIN.search(ln):
            continue
        for m in _RX_CARIMBO.finditer(ln):
            d = _d(m.group(1), m.group(2), m.group(3))
            if d and 2000 < d.year < 2100:
                out.append((d, ln.strip()[:160]))
    return out


_RX_DATA_ASSINATURA = re.compile(r"assinado eletronicamente por[^\n]{0,200}?\bem\s+(\d{2})/(\d{2})/(\d{4})", re.I)
_MESES = {m: i for i, m in enumerate(["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
                                      "setembro", "outubro", "novembro", "dezembro"], 1)}
_RX_DATA_EXTENSO = re.compile(r"\b(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})\b")


def data_do_ato(texto: str) -> tuple[date, str] | None:
    """Data do atesto/parecer: a da assinatura eletrônica (mais tardia) ou, sem ela, a data por extenso."""
    ds = [(_d(*m.groups()), m.group(0)) for m in _RX_DATA_ASSINATURA.finditer(texto or "")]
    ds = [x for x in ds if x[0]]
    if ds:
        return max(ds)
    for m in _RX_DATA_EXTENSO.finditer(_sa(texto or "")):
        mes = _MESES.get(m.group(2))
        if mes:
            d = _d(m.group(1), mes, m.group(3))
            if d:
                return d, m.group(0)
    return None


# ── códigos de serviço (EMOP/SCO/SINAPI) ──────────────────────────────────────────────────────────────────────
_RX_COD_LIVRE = re.compile(r"\b(\d{2})\s?\.\s?(\d{2,3})\s?\.\s?(\d(?:\s?\d){2,3})(?!\d)")


def codigos(texto: str) -> set[str]:
    """Código de serviço normalizado (só dígitos, sem o verificador): '08.015.0060-0' → '080150060'."""
    out = set()
    for m in _RX_COD_LIVRE.finditer(texto or ""):
        dig = m.group(1) + m.group(2).zfill(3) + m.group(3).replace(" ", "").zfill(4)
        out.add(dig)
    return out


# ── diário de obra: dia a dia, parado ou não ─────────────────────────────────────────────────────────────────
_RX_PARADA = re.compile(r"sem\s+atividades?|sem\s+expediente|n[aã]o\s+houve\s+(?:atividade|expediente|servi[cç]o|trabalho)"
                        r"|paralisad[ao]|paralisa[cç][aã]o|servi[cç]os?\s+suspens|impratic[aá]vel|obra\s+parada"
                        r"|feriado|final\s+de\s+semana", re.I)
_RX_CHUVA = re.compile(r"chuv\w*(?:\s+(?:forte|intensa|fraca|moderada|torrencial))?", re.I)
MIN_DIAS_MOLDE = 5
FRACAO_MOLDE = 0.9   # frase presente em ≥ 90% dos dias é RÓTULO do formulário, não o que se preencheu


def dias_do_diario(texto: str, periodo_med: tuple | None = None) -> list[dict]:
    """Segmenta o diário pela 1ª ocorrência de cada data e marca o dia como parado/chuvoso.

    Rótulo de formulário ("Não houve atividade", "Paralisado", "3 - Chuvoso" em TODA página do RDO do INEA) não é
    o que o fiscal marcou: frase presente em ≥ 90% dos dias é molde e não conta."""
    t = texto or ""
    marcas, vistas = [], set()
    for m in _RX_DATA.finditer(t):
        d = _d(*m.groups())
        if not d or d in vistas:
            continue
        if periodo_med and not (periodo_med[0] - timedelta(days=3) <= d <= periodo_med[1] + timedelta(days=3)):
            continue
        vistas.add(d)
        marcas.append((m.start(), d))
    dias = []
    for k, (pos, d) in enumerate(marcas):
        fim = marcas[k + 1][0] if k + 1 < len(marcas) else len(t)
        dias.append({"data": d, "corpo": t[pos:fim]})
    if not dias:
        return []
    n = len(dias)

    def _frases(rx, corpo):
        return {re.sub(r"\s+", " ", _sa(m.group(0))) for m in rx.finditer(corpo)}
    conta: dict = {}
    for dd in dias:
        for f in _frases(_RX_PARADA, dd["corpo"]) | _frases(_RX_CHUVA, dd["corpo"]):
            conta[f] = conta.get(f, 0) + 1
    molde = {f for f, c in conta.items() if n >= MIN_DIAS_MOLDE and c / n >= FRACAO_MOLDE}
    for dd in dias:
        fr = _frases(_RX_PARADA, dd["corpo"]) - molde
        dd["parado"] = bool(fr)
        dd["motivo"] = sorted(fr)[:3]
        dd["chuva"] = bool(_frases(_RX_CHUVA, dd["corpo"]) - molde)
        # conteúdo PREENCHIDO: linhas do dia que não se repetem em ≥ 90% dos dias (sem as datas)
        dd["_linhas"] = {re.sub(r"\d", "", _sa(x)).strip() for x in dd["corpo"].splitlines() if len(x.strip()) > 3}
    freq: dict = {}
    for dd in dias:
        for ln in dd["_linhas"]:
            freq[ln] = freq.get(ln, 0) + 1
    for dd in dias:
        preench = sorted(ln for ln in dd.pop("_linhas") if freq[ln] / n < FRACAO_MOLDE and ln)
        dd["preenchido"] = "\n".join(preench)
        dd.pop("corpo")
    return dias


# ── natureza do item: o que a foto pode (e não pode) mostrar ──────────────────────────────────────────────────
# Unidade de TEMPO (h, mês, dia) ou verba: a foto mostra, no máximo, que o equipamento/pessoa esteve lá — nunca as
# horas. Unidade DIMENSIONAL (m, m², m³, t, un…): a quantidade é aferível em campo, e o registro que a prova é
# trena, croqui, marco, antes/depois — ou a memória de cálculo.
_UNI_TEMPO = {"h", "hr", "hs", "hora", "mes", "mês", "meses", "dia", "dias", "diaria", "diária", "unxmes", "unxmês",
              "h/mes", "mes/h", "m2xmes", "m²xmês", "m2xmês", "unid/mes", "mxmes", "hxmes", "vb", "verba", "%", "gl",
              "lote", "kwh", "kw"}
_RX_NAO_FOTOGRAFAVEL = re.compile(
    r"mao[- ]de[- ]obra|engenheir|arquitet|encarregad|apontador|tecnico|vigia|vigilancia|administra|consultoria"
    r"|projeto|ensaio|amostra|analise|limite de|topograf|levantamento|seguro|taxa|licen|art\b|mobiliza|desmobiliza"
    r"|transporte|dmt|momento de transporte|disposicao final|bota[- ]fora|carga e descarga|equipe|placa de identifica"
    r"|aluguel|locacao|caminhao|veiculo|camionete|escavadeira|retroescavadeira|trator|carreta|guindauto|rolo|motonivel",
    re.I)
_RX_REGISTRO_DIMENSIONAL = re.compile(
    r"\btrena\b|croqui|antes\s+e\s+depois|\bantes\b|\bdepois\b|estaca|marco|gabarito|medi[cç][aã]o\s+(?:em|de)\s+campo"
    r"|\b\d+(?:[.,]\d+)?\s*(?:m²|m2|m³|m3|metros?|ml|un|unid)\b|extens[aã]o|[aá]rea\s+(?:executada|medida)", re.I)


def natureza(item: dict) -> str:
    """'tempo' (h/mês/verba) · 'nao_fotografavel' (gestão, ensaio, transporte) · 'dimensional'."""
    u = (item.get("unidade") or "").replace(" ", "")
    if u in _UNI_TEMPO:
        return "tempo"
    if _RX_NAO_FOTOGRAFAVEL.search(_sa(item.get("descricao") or "")):
        return "nao_fotografavel"
    return "dimensional"


# ── SIAFE: OB paga ligada à medição ──────────────────────────────────────────────────────────────────────────

_COLS_OB = ["numero_ob", "ug", "data_emissao", "valor", "nl", "credor_nome", "credor_doc", "tipo_ob", "finalidade",
            "status", "status_envio", "processo"]


def chave_processo(p: str | None) -> str | None:
    """'SEI-070002/005897/2024', 'SEI070002/5897/24' e '070002/005897/2024' são o MESMO processo
    (mesma regra de `tools.lex_execucao._chave_processo`)."""
    m = re.search(r"(\d{6})\s*/\s*0*(\d+)(?:-\d)?\s*/\s*(\d{4}|\d{2})(?!\d)", p or "")
    if not m:
        return None
    ano = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
    return f"{m.group(1)}/{int(m.group(2))}/{ano}"


def mapa_obs_pagas(con, processos) -> dict[str, list[dict]]:
    """OB do SIAFE (nunca o espelho TFE) por processo, só as PAGAS pela regra canônica `_ob_paga` (Contabilizado,
    não devolvida pelo banco, com número). UMA varredura para o lote — a tabela não tem índice por processo."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    alvo = {k for k in map(chave_processo, processos) if k}
    out: dict[str, list[dict]] = {}
    vistos = set()
    sql = (f"SELECT numero_ob, ug_emitente, data_emissao, valor, nl, nome_credor, credor, tipo_ob, finalidade, status, "
           f"status_envio, processo FROM ob_orcamentaria_siafe WHERE {_ob_paga(con)}")
    for r in con.execute(sql):
        k = chave_processo(r[11])
        if k not in alvo:
            continue
        d = dict(zip(_COLS_OB, r))
        if (d["numero_ob"], d["ug"]) in vistos:
            continue
        vistos.add((d["numero_ob"], d["ug"]))
        de = str(d["data_emissao"] or "")
        d["data"] = _d(*de.split("/")) if re.fullmatch(r"\d{2}/\d{2}/\d{4}", de) else None
        out.setdefault(k, []).append(d)
    return out


def obs_pagas_do_processo(con, processo: str) -> list[dict]:
    return mapa_obs_pagas(con, [processo]).get(chave_processo(processo) or "", [])


def _cnpj_mascarado(doc: str) -> str:
    d = re.sub(r"\D", "", doc or "")
    if len(d) == 11:   # CPF (LGPD)
        return f"***.{d[3:6]}.{d[6:9]}-**"
    return doc or ""


# ── o porquê ─────────────────────────────────────────────────────────────────────────────────────────────────
CLASSES_PORQUE = ("inocente-comprovada", "inocente-provável", "sem-explicação", "contradição")
_RX_ADITIVO = re.compile(r"termo\s+aditivo|\baditivo\b|apostilamento|reprograma[cç][aã]o|acr[eé]scimo\s+de\s+quantitativ"
                         r"|planilha\s+(?:readequada|reformulada|aditivada)", re.I)


def _trecho(texto: str, rx, largura: int = 160) -> str | None:
    m = rx.search(texto or "") if hasattr(rx, "search") else None
    if not m:
        return None
    a = max(0, m.start() - largura // 2)
    return re.sub(r"\s+", " ", texto[a:m.end() + largura // 2]).strip()


def _porque(classe: str, explicacao: str, trecho: str | None = None, fonte: str | None = None) -> dict:
    assert classe in CLASSES_PORQUE
    return {"classe": classe, "explicacao": explicacao, "trecho": trecho, "fonte": fonte}


# ── confronto de UMA medição ─────────────────────────────────────────────────────────────────────────────────
MIN_CODIGOS_CONVENCAO = 3     # relatório que cita ≥ 3 códigos do boletim adotou a convenção "legenda = item"
MIN_LOCAIS_CONVENCAO = 2
MIN_LEGENDA_CHARS = 120       # abaixo disso (fora cabeçalho) o relatório não tem legenda que case com nada
FOLGA_DEPOIS_DIAS = 30        # foto até 30 dias depois do fim do período: vistoria/fechamento, não vício
FOLGA_ANTES_DIAS = 3


def _codigos_item(x: dict) -> set[str]:
    """Código do item normalizado; sem código separado, o do começo da descrição ('EMOP 01.001.0 075-1 …')."""
    return codigos(x.get("codigo") or "") or codigos((x.get("descricao") or "")[:40])


def _texto_pacote(pasta: Path, docs: list[dict]) -> str:
    return "\n\n".join(texto_doc(pasta, d) for d in docs)


def _legenda_util(texto_rf: str) -> str:
    """Texto do relatório sem cabeçalho repetido, linhas administrativas e lixo de OCR."""
    linhas = [ln.strip() for ln in (texto_rf or "").splitlines() if ln.strip()]
    freq: dict = {}
    for ln in linhas:
        freq[ln] = freq.get(ln, 0) + 1
    util = [ln for ln in linhas if not _RX_LINHA_ADMIN.search(ln) and len(re.findall(r"[A-Za-zÀ-ú]{3,}", ln)) >= 2
            and not re.search(r"relat[oó]rio fotogr|per[ií]odo|contrato|governo|secretaria|instituto|diretoria"
                              r"|\[ocr\]", ln, re.I)]
    return "\n".join(dict.fromkeys(util))


def paginas_sem_legenda(texto_rf: str) -> tuple[int, int] | None:
    """(páginas, páginas sem legenda) pelo cabeçalho que se repete a cada página do relatório.

    O texto da página vem do PDF; a legenda que está DENTRO da imagem não aparece. Por isso a frente "sem foto"
    só vale quando TODA página tem legenda em texto — senão a frente pode estar numa página muda (13ª medição da
    Geo Ambiental: 60 páginas, 4 legendas em texto)."""
    linhas = [ln.strip() for ln in (texto_rf or "").splitlines()]
    freq: dict = {}
    for ln in linhas:
        if len(ln) >= 15 and re.search(r"relat[oó]rio\s+fotogr|medi[cç][aã]o", ln, re.I):
            freq[ln] = freq.get(ln, 0) + 1
    if not freq:
        return None
    cab, n = max(freq.items(), key=lambda kv: kv[1])
    if n < 3:
        return None
    blocos, atual = [], []
    for ln in linhas:
        if ln == cab:
            blocos.append(atual)
            atual = []
        else:
            atual.append(ln)
    blocos.append(atual)
    blocos = blocos[1:] if not "".join(blocos[0]).strip() else blocos
    sem = 0
    for b in blocos:
        txt = "\n".join(b)
        uteis = [ln for ln in b if re.search(r"[A-Za-zÀ-ú]{4,}", ln) and not _RX_LINHA_ADMIN.search(ln)
                 and not re.search(r"relat[oó]rio\s+fotogr|per[ií]odo\s*:|governo do estado|secretaria de|instituto"
                                   r"|diretoria|\[ocr\]|empreendimentos", ln, re.I)]
        if not (uteis or codigos(txt)):
            sem += 1
    return len(blocos), sem


def confrontar_medicao(pasta: Path | str, pk: dict, *, obs: list[dict] | None = None,
                       titulos_processo: str = "") -> dict:
    """Sinais de UMA medição (pacote de `medicoes`). Cada sinal leva tipo, grau, evidência e o porquê."""
    pasta = Path(pasta)
    tb = _texto_pacote(pasta, pk["boletim"] + pk["memoria"])
    tr = _texto_pacote(pasta, pk["relatorio"])
    ta = _texto_pacote(pasta, pk["aceite"])
    td = _texto_pacote(pasta, pk["diario"])
    itens = itens_boletim(tb)
    per_b = periodo(tb) or periodo(ta)
    per_r = periodo(tr)
    per = per_b or per_r
    medidos = [x for x in itens if (x.get("per") or 0) > 0]
    valor_periodo = round(sum(x["per"] * x["pu"] for x in medidos), 2)
    fotos = [f for d in pk["relatorio"] for f in (d.get("fotos") or [])]
    res = {"n": pk["n"], "boletim": [d["titulo"] for d in pk["boletim"] + pk["memoria"]],
           "relatorio": [d["titulo"] for d in pk["relatorio"]], "diario": [d["titulo"] for d in pk["diario"]],
           "periodo": [per[0].isoformat(), per[1].isoformat()] if per else None,
           "n_itens_lidos": len(itens), "n_itens_medidos": len(medidos), "valor_periodo_itens": valor_periodo,
           "n_fotos": len(fotos), "fotos_locais": sum((pasta / f).exists() for f in fotos), "sinais": [],
           "estado": "VERIFICADO" if itens else ("INDISPONÍVEL" if pk["boletim"] else "SEM_BOLETIM")}
    if not pk["relatorio"]:
        res["estado"] = "SEM_RELATORIO"
    sinais = res["sinais"]
    tem_memoria = bool(pk["memoria"]) or bool(re.search(r"mem[oó]ria\s+de\s+c[aá]lculo", tb, re.I))
    tem_croqui = bool(re.search(r"croqui", " ".join(d["titulo"] for d in pk["boletim"] + pk["memoria"]) + tb[:4000], re.I))

    # (d) acumulado acima do contratado — só com a aritmética fechada
    for x in itens:
        # acima do contratado só com o SALDO negativo impresso ou com o valor de cada coluna fechando (prova positiva)
        if x.get("acum") is not None and x["acum"] > x["qc"] * 1.0001 and (
                "acum+saldo=contratado" in x["fecha"] or "qtd×pu=valor em cada coluna" in x["fecha"]):
            tr_ad = _trecho(titulos_processo, _RX_ADITIVO)
            pq = (_porque("inocente-provável", "há aditivo/apostilamento no processo; o boletim pode estar com a "
                          "quantidade ORIGINAL na coluna do contratado", tr_ad, "títulos do processo")
                  if tr_ad else
                  _porque("sem-explicação", "o próprio boletim mede acumulado acima do contratado e o processo não "
                          "traz aditivo que o explique (o aditivo pode estar no processo do contrato — conferir)"))
            sinais.append({"tipo": "ACUMULADO_EXCEDE_CONTRATADO", "grau": "achado", "item": x["item"],
                           "codigo": x["codigo"], "descricao": x["descricao"][:160], "unidade": x["unidade"],
                           "contratado": x["qc"], "acumulado": x["acum"], "excesso": round(x["acum"] - x["qc"], 4),
                           "valor_excesso": round((x["acum"] - x["qc"]) * x["pu"], 2), "fecha": x["fecha"],
                           "porque": pq})
    if not pk["relatorio"]:
        return res

    leg = _legenda_util(tr)
    cod_r = codigos(tr)
    cod_b = {c for x in itens for c in _codigos_item(x)}
    loc_r = locais(tr)
    loc_b = locais(tb)
    conv_cod = len(cod_r & cod_b) >= MIN_CODIGOS_CONVENCAO
    conv_loc = len(loc_r) >= MIN_LOCAIS_CONVENCAO and len(loc_b) >= MIN_LOCAIS_CONVENCAO
    res["convencao"] = "codigo" if conv_cod else ("local" if conv_loc else ("legenda_livre" if len(leg) >= MIN_LEGENDA_CHARS
                                                                            else "sem_legenda"))

    # (a) item medido sem foto — pela convenção que o PRÓPRIO relatório adotou
    if conv_cod:
        for x in medidos:
            cx = _codigos_item(x)
            if not cx or cx & cod_r:
                continue
            nat = natureza(x)
            pq = (_porque("inocente-provável", f"item de natureza '{nat}': a quantidade ({x['unidade']}) não se prova "
                          "por foto", x["descricao"][:160], "boletim")
                  if nat != "dimensional" else
                  _porque("sem-explicação", "item dimensional medido no período sem foto com o código dele; o relatório "
                          f"traz {len(cod_r & cod_b)} outros códigos do boletim"))
            sinais.append({"tipo": "ITEM_MEDIDO_SEM_FOTO", "grau": "lacuna" if nat != "dimensional" else "indicio",
                           "item": x["item"], "codigo": x["codigo"], "descricao": x["descricao"][:160],
                           "unidade": x["unidade"], "qtd_periodo": x["per"], "valor_periodo": round(x["per"] * x["pu"], 2),
                           "porque": pq})
    pag = paginas_sem_legenda(tr)
    if pag:
        res["paginas_relatorio"], res["paginas_sem_legenda"] = pag
    # página muda até o nº de frentes legendadas = MAPA de localização (Google Earth com pino, 1 por frente: 7ª
    # medição da Geo, 17 páginas mudas para 18 frentes, conferido a olho em 029_p04). Acima disso, foto sem legenda.
    mudas_demais = bool(pag) and pag[1] > len(loc_r)
    zeradas = frentes_zeradas(tb)
    i_ctl = tb.upper().find("CONTROLE DE HORAS")
    controle = tb[i_ctl:] if i_ctl >= 0 else ""
    controle_toks = _toks_local(controle)
    copia_de, copia_n = pk.get("_copia_de"), pk.get("_copia_n")
    horas_k = horas_por_frente(tb)
    vpf = valor_por_frente(tb, itens)
    if conv_loc and mudas_demais:
        faltam = [nome for k, nome in loc_b.items() if k not in zeradas and not any(mesmo_local(k, r) for r in loc_r)]
        if faltam:
            sinais.append({"tipo": "FOTOS_SEM_LEGENDA", "grau": "lacuna", "paginas": pag[0], "paginas_sem_legenda": pag[1],
                           "frentes_nao_identificadas": faltam[:30],
                           "porque": _porque("sem-explicação", f"{pag[1]} de {pag[0]} páginas do relatório trazem foto sem "
                                             "legenda em texto (local/data/item): não se sabe de que frente são, e "
                                             f"{len(faltam)} frente(s) medida(s) não aparecem nas legendas que existem")})
    if conv_loc and not mudas_demais:
        for k, nome in loc_b.items():
            if k in zeradas or any(mesmo_local(k, r) for r in loc_r):
                continue
            hk = horas_k.get(k) or next((v for kk, v in horas_k.items() if mesmo_local(kk, k)), None)
            if not hk or not any(h > 0 for h in hk):
                continue    # a memória não diz quanto se mediu na frente: sem quantidade, não há o que cobrar da foto
            parc = [loc_r[r] for r in loc_r if mesma_frente_provavel(nome, loc_r[r])]
            _mun, corpo = _partes_local(nome)
            no_controle = None
            if controle:
                no_controle = any(t in controle_toks or any(_parecido(t, c) for c in controle_toks)
                                  for t in corpo if len(t) >= 4)
            if parc:
                pq = _porque("inocente-provável", "frente fotografada com nome parecido (mesmo município e nome próprio "
                             "em comum) — provavelmente a mesma", f"boletim: '{nome}' × relatório: '{parc[0]}'",
                             "boletim × relatório")
            elif copia_de is not None and no_controle is False:
                pq = _porque("inocente-provável", f"a memória de cálculo desta medição é CÓPIA da {copia_de}ª "
                             f"({copia_n} linhas frente×equipamento idênticas) e o controle de horas do próprio período "
                             "não registra a frente: o que se cobrou segue o controle; a frente é resíduo da memória "
                             "copiada (a cópia em si é falha documental, ver MEMORIA_COPIADA)",
                             f"'{nome}' consta da memória e não do 'CONTROLE DE HORAS TRABALHADAS'", "boletim da medição")
            elif no_controle is False:
                pq = _porque("contradição", "a memória de cálculo mede horas na frente, o controle diário de horas do "
                             "período não a registra e o relatório não a fotografa",
                             f"'{nome}' na memória; ausente do 'CONTROLE DE HORAS TRABALHADAS'", "boletim da medição")
            elif no_controle:
                pq = _porque("sem-explicação", "o controle diário de horas registra trabalho na frente, mas o relatório "
                             "não traz foto dela — lacuna de registro fotográfico",
                             f"'{nome}' no 'CONTROLE DE HORAS TRABALHADAS'", "boletim da medição")
            else:
                tp = _trecho(ta + "\n" + td, re.compile(re.escape(nome.split("-")[-1].strip()[:20]), re.I))
                pq = (_porque("sem-explicação", "a frente aparece no parecer/diário, mas sem foto no relatório", tp,
                              "parecer/diário") if tp else
                      _porque("sem-explicação", "frente medida na memória de cálculo sem nenhuma legenda no relatório"))
            vf = vpf.get(k) or next((v for kk, v in vpf.items() if mesmo_local(kk, k)), None)
            sinais.append({"tipo": "FRENTE_MEDIDA_SEM_FOTO", "grau": "indicio", "local": nome,
                           "horas_medidas": vf["horas"] if vf else None,
                           "valor_medido_frente": vf["valor"] if vf and not vf["sem_preco"] else None,
                           "porque": pq})

    # (b) período do relatório ≠ período do boletim
    if per_b and per_r and (abs((per_b[0] - per_r[0]).days) > 3 or abs((per_b[1] - per_r[1]).days) > 3):
        so_ano = (per_b[0].replace(year=2000) == per_r[0].replace(year=2000)
                  and per_b[1].replace(year=2000) == per_r[1].replace(year=2000)) if per_b[0].day < 29 and per_r[0].day < 29 else False
        mi = re.search(r"in[ií]cio\s+do\s+contrato\s*:?\s*\|?\s*(\d{2})/(\d{2})/(\d{4})", tb + "\n" + td + "\n" + tr, re.I)
        ini_ct = _d(*mi.groups()) if mi else None
        pq = (_porque("inocente-comprovada", f"só o ANO difere e o período do relatório termina antes do INÍCIO DO "
                      f"CONTRATO ({ini_ct.strftime('%d/%m/%Y')}): não pode ser real — erro de digitação no cabeçalho",
                      f"boletim: '{per_b[2]}' × relatório: '{per_r[2]}' · '{mi.group(0)}'", "boletim × relatório × diário")
              if so_ano and ini_ct and per_r[1] < ini_ct else
              _porque("inocente-provável", "dia e mês iguais, só o ANO difere — cabeçalho do modelo não atualizado",
                      f"boletim: '{per_b[2]}' × relatório: '{per_r[2]}'", "boletim × relatório")
              if so_ano else
              _porque("sem-explicação", "o relatório fotográfico declara outro período",
                      f"boletim: '{per_b[2]}' × relatório: '{per_r[2]}'", "boletim × relatório"))
        sinais.append({"tipo": "PERIODO_RELATORIO_DIVERGE", "grau": "indicio" if not so_ano else "lacuna",
                       "periodo_boletim": [per_b[0].isoformat(), per_b[1].isoformat()],
                       "periodo_relatorio": [per_r[0].isoformat(), per_r[1].isoformat()], "porque": pq})

    # (c) carimbo/legenda com data fora do período
    if per:
        for d, ln in carimbos(tr):
            if per[0] - timedelta(days=FOLGA_ANTES_DIAS) <= d <= per[1] + timedelta(days=FOLGA_DEPOIS_DIAS):
                continue
            if d < per[0]:
                if re.search(r"\bantes\b|anterior|inicial|situa[cç][aã]o\s+original", ln, re.I):
                    pq = _porque("inocente-provável", "a legenda diz que é a situação ANTERIOR", ln, "relatório")
                elif (per[0] - d).days > 730:
                    pq = _porque("inocente-provável", "data anos antes do período — relógio da câmera desacertado", ln,
                                 "relatório")
                else:
                    pq = _porque("contradição", "foto datada ANTES do período que ela comprova", ln, "relatório")
            else:
                pq = _porque("sem-explicação", f"foto datada {(d - per[1]).days} dias depois do fim do período", ln,
                             "relatório")
            sinais.append({"tipo": "FOTO_FORA_DO_PERIODO", "grau": "indicio", "data_foto": d.isoformat(), "linha": ln,
                           "porque": pq})

    # (e) lacunas documentais: sem legenda; item dimensional sem registro dimensional
    if res["convencao"] == "sem_legenda":
        pq = (_porque("inocente-provável", "a quantidade vem da memória de cálculo/croqui do pacote, não da foto",
                      "; ".join(d["titulo"] for d in pk["memoria"])[:200] or "memória de cálculo citada no boletim",
                      "pacote da medição") if (tem_memoria or tem_croqui) else
              _porque("sem-explicação", "relatório sem legenda: nenhuma foto se liga a item, local ou data"))
        sinais.append({"tipo": "RELATORIO_SEM_LEGENDA", "grau": "lacuna", "n_fotos": len(fotos),
                       "valor_periodo_itens": valor_periodo, "porque": pq})
    dimensionais = [x for x in medidos if natureza(x) == "dimensional"]
    if dimensionais and not _RX_REGISTRO_DIMENSIONAL.search(leg):
        pq = (_porque("inocente-provável", "a quantidade é demonstrada pela memória de cálculo/croqui do pacote",
                      "; ".join(d["titulo"] for d in pk["memoria"])[:200] or "memória/croqui citada no boletim",
                      "pacote da medição") if (tem_memoria or tem_croqui) else
              _porque("sem-explicação", "itens medidos em m/m²/m³/un sem trena, croqui, antes/depois nem memória de "
                      "cálculo no pacote: a foto não permite aferir a quantidade"))
        sinais.append({"tipo": "SEM_REGISTRO_DIMENSIONAL", "grau": "lacuna", "n_itens": len(dimensionais),
                       "valor_periodo": round(sum(x["per"] * x["pu"] for x in dimensionais), 2),
                       "exemplos": [f"{x['item']} {x['descricao'][:60]} ({x['per']:g} {x['unidade']})"
                                    for x in sorted(dimensionais, key=lambda y: -y["per"] * y["pu"])[:3]],
                       "porque": pq})

    # diário: período inteiro parado com serviço medido; foto em dia parado
    if td.strip() and per:
        dias = dias_do_diario(td, per)
        res["diario_dias"] = len(dias)
        if not dias and len(td) >= 2000:
            fora = sorted({d for d in (_d(*m.groups()) for m in _RX_DATA.finditer(td)) if d})
            iso = sorted(set(re.findall(r"\b20\d\d-\d\d-\d\d\b", td)))
            achadas = [x.isoformat() for x in fora][:6] + iso[:6]
            sinais.append({"tipo": "DIARIO_SEM_DIA_DO_PERIODO", "grau": "indicio" if achadas else "lacuna",
                           "datas_no_diario": achadas,
                           "porque": (_porque("contradição", "o diário juntado à medição não registra nenhum dia do período "
                                              "medido; as únicas datas são de fora dele", ", ".join(achadas)[:160],
                                              "diário de obra") if achadas else
                                      _porque("sem-explicação", "o diário juntado à medição não traz data nenhuma — não "
                                              "se sabe a que dias se refere"))})
        parados = [d for d in dias if d["parado"]]
        res["diario_parados"] = len(parados)
        exec_med = [x for x in medidos if natureza(x) != "tempo"]
        if len(dias) >= MIN_DIAS_MOLDE and len(parados) == len(dias) and exec_med:
            sinais.append({"tipo": "DIARIO_PARADO_COM_MEDICAO", "grau": "indicio", "dias": len(dias),
                           "motivos": sorted({m for d in parados for m in d["motivo"]})[:5],
                           "porque": _porque("contradição", "todos os dias do diário no período registram parada, e o "
                                             "boletim mede serviço executado", ", ".join(sorted({m for d in parados
                                                                                                for m in d["motivo"]}))[:160],
                                             "diário de obra")})
        pdias = {d["data"]: d for d in parados}
        for d, ln in carimbos(tr):
            if d in pdias:
                sinais.append({"tipo": "FOTO_EM_DIA_PARADO", "grau": "indicio", "data_foto": d.isoformat(), "linha": ln,
                               "porque": _porque("contradição", "foto datada em dia que o diário registra parada",
                                                 f"diário {d.isoformat()}: {', '.join(pdias[d]['motivo'])}", "diário")})
        preench = [d["preenchido"] for d in dias if len(d["preenchido"]) > 40]
        if len(preench) >= MIN_DIAS_MOLDE:
            maior = max(preench.count(p) for p in set(preench))
            res["diario_dias_identicos"] = maior
            if maior / len(preench) >= 0.5:
                sinais.append({"tipo": "DIARIO_REPETIDO", "grau": "lacuna", "dias_identicos": maior,
                               "dias_preenchidos": len(preench),
                               "porque": _porque("sem-explicação", "o conteúdo preenchido é o mesmo em metade ou mais dos "
                                                 "dias — o diário não registra o que mudou dia a dia",
                                                 max(set(preench), key=preench.count)[:160], "diário de obra")})

    # OB: ligada pela NL/OB citada nos títulos do pacote
    if obs is not None:
        lig = [o for o in obs if (o["nl"] and o["nl"] in pk["nl"]) or o["numero_ob"] in pk["ob"]]
        res["obs_pagas"] = [{k: o[k] for k in ("numero_ob", "ug", "data_emissao", "valor", "nl")} for o in lig]
        res["valor_pago_ligado"] = round(sum(o["valor"] or 0 for o in lig), 2)
        ato = data_do_ato(ta) if ta.strip() else None
        if ato:
            res["data_atesto"] = ato[0].isoformat()
            for o in lig:
                if o["data"] and o["data"] < ato[0]:
                    sinais.append({"tipo": "OB_ANTES_DO_ATESTO", "grau": "indicio", "numero_ob": o["numero_ob"],
                                   "ug": o["ug"], "data_ob": o["data_emissao"], "valor": o["valor"],
                                   "data_atesto": ato[0].isoformat(),
                                   "porque": _porque("sem-explicação", "OB paga antes da data do atesto/parecer da medição",
                                                     ato[1], "atesto/parecer")})
    return res


MIN_LINHAS_COPIA = 20
FRACAO_COPIA = 0.9


def memorias_copiadas(pasta: Path, pks: list[dict]) -> dict[int, dict]:
    """Medição cuja memória (frente × código × horas > 0) é ≥ 90% idêntica à de uma medição ANTERIOR.

    Caso que ensinou (18/11/2026, INEA 35/2023, Geo Ambiental): a memória da 23ª medição (maio/2025) repete as 82
    linhas da 21ª (março/2025) — e não fecha com o boletim da 23ª em nenhum dos 16 códigos, enquanto o 'Controle de
    Horas Trabalhadas' da própria 23ª não traz três das frentes da memória."""
    from collections import Counter
    linhas, fech = {}, {}
    for pk in pks:
        if pk.get("n") is None:
            continue
        tb = _texto_pacote(Path(pasta), pk["boletim"] + pk["memoria"])
        oc = [(tuple(sorted(k)), c, round(h, 2)) for k, c, h in _ocorrencias_frente(tb) if c and h > 0]
        if len(oc) < MIN_LINHAS_COPIA:
            continue
        linhas[id(pk)] = (pk, Counter(oc))
        soma: dict = {}
        for _k, c, h in oc:
            soma[c] = soma.get(c, 0) + h
        per = {x["codigo"]: x["per"] for x in itens_boletim(tb) if x.get("codigo") and x.get("per") is not None}
        comuns = [c for c in soma if c in per]
        fech[id(pk)] = (sum(1 for c in comuns if _perto(soma[c], per[c], 0.005)), len(comuns))
    out: dict[int, dict] = {}
    ordem = sorted(linhas.values(), key=lambda t: t[0]["n"])
    for j, (b, cb) in enumerate(ordem):
        for a, ca in ordem[:j]:
            if a["n"] == b["n"]:
                continue
            iguais = sum((ca & cb).values())
            nb, na = sum(cb.values()), sum(ca.values())
            if iguais >= MIN_LINHAS_COPIA and iguais / max(nb, na) >= FRACAO_COPIA:
                ex = next(iter(ca & cb))
                out[id(b)] = {"de": a["n"], "iguais": iguais, "linhas": nb, "fecha": fech.get(id(b), (0, 0)),
                              "exemplo": f"{' '.join(ex[0]).upper()} · {ex[1]} · {ex[2]:g} h nas duas medições"}
                break
    return out


def confrontar_processo(pasta: Path | str, con=None, obs: list[dict] | None = None) -> dict:
    pasta = Path(pasta)
    man = _manifesto(pasta)
    processo = str(man.get("processo") or pasta.name).strip()
    titulos = "\n".join(str(d.get("titulo") or "") for d in man.get("docs") or [] if isinstance(d, dict))
    if obs is None and con is not None:
        obs = obs_pagas_do_processo(con, processo)
    pks = [pk for pk in medicoes(pasta) if pk["boletim"] or pk["relatorio"]]
    copias = memorias_copiadas(pasta, pks)
    for pk in pks:
        c = copias.get(id(pk))
        if c:
            pk["_copia_de"], pk["_copia_n"] = c["de"], c["iguais"]
    meds = []
    for pk in pks:
        r = confrontar_medicao(pasta, pk, obs=obs, titulos_processo=titulos)
        c = copias.get(id(pk))
        if c:
            fecha = c["fecha"]
            pq = (_porque("contradição", f"a memória de cálculo é idêntica à da {c['de']}ª medição ({c['iguais']} de "
                          f"{c['linhas']} linhas frente×equipamento×horas) e não fecha com a quantidade do período do "
                          f"próprio boletim em nenhum dos {fecha[1]} códigos — a quantidade cobrada não tem memória própria",
                          f"{c['exemplo']}", "boletim da medição × boletim da medição anterior")
                  if fecha[1] >= 5 and fecha[0] == 0 else
                  _porque("sem-explicação", f"memória de cálculo idêntica à da {c['de']}ª medição ({c['iguais']} de "
                          f"{c['linhas']} linhas); fecha com o boletim em {fecha[0]} de {fecha[1]} códigos",
                          c["exemplo"], "boletim da medição × boletim da medição anterior"))
            r["sinais"].append({"tipo": "MEMORIA_COPIADA", "grau": "achado" if pq["classe"] == "contradição" else "indicio",
                                "copia_da_medicao": c["de"], "linhas_iguais": c["iguais"], "linhas": c["linhas"],
                                "codigos_que_fecham": fecha[0], "codigos": fecha[1], "porque": pq})
        meds.append(r)
    credor = None
    if obs:
        tot: dict = {}
        for o in obs:
            tot[(o["credor_nome"], o["credor_doc"])] = tot.get((o["credor_nome"], o["credor_doc"]), 0) + (o["valor"] or 0)
        c = max(tot, key=tot.get)
        credor = {"nome": c[0], "doc": _cnpj_mascarado(c[1])}
    return {"processo": processo, "pasta": pasta.name, "credor_siafe": credor,
            "pago_processo": round(sum(o["valor"] or 0 for o in obs), 2) if obs is not None else None,
            "n_obs_pagas": len(obs) if obs is not None else None, "medicoes": meds,
            "fonte": "acervo SEI (data/sei_arquivo) + SIAFE ob_orcamentaria_siafe (só OB paga)", "ressalva": RESSALVA}


def _pastas_alvo(base: Path) -> list[Path]:
    out = []
    for p in sorted(Path(base).iterdir()):
        mf = p / "manifest.json"
        try:
            if mf.is_file() and "otogr" in mf.read_text(encoding="utf-8", errors="ignore").lower():
                out.append(p)
        except OSError:
            continue
    return out


def _um_processo(args) -> str | None:
    p, obs = args
    r = confrontar_processo(Path(p), obs=obs)
    return json.dumps(r, ensure_ascii=False, default=str) if r["medicoes"] else None


def exportar_obs(saida: Path, base: Path = BASE_ACERVO, db: Path | None = None) -> int:
    """Mapa processo → OB pagas (SIAFE) dos processos-alvo, em JSON — para rodar a varredura fora da VM-1."""
    import sqlite3
    db = db or (REPO / "data" / "compliance.db")
    pastas = _pastas_alvo(base)
    procs = [str(_manifesto(p).get("processo") or p.name) for p in pastas]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    try:
        mapa = mapa_obs_pagas(con, procs)
    finally:
        con.close()
    Path(saida).write_text(json.dumps(mapa, ensure_ascii=False, default=str), encoding="utf-8")
    return sum(len(v) for v in mapa.values())


def varrer(base: Path = BASE_ACERVO, saida: Path | None = None, db: Path | None = None,
           obs_json: Path | None = None, procs: int = 1) -> dict:
    """Todo processo do acervo com relatório fotográfico. Grava JSON por processo (uma linha cada).

    `obs_json` (de `exportar_obs`) dispensa o compliance.db — é assim que roda no it-campo; `procs` > 1 paraleliza."""
    saida = saida or (REPO / "data" / "foto_quantitativo" / "medicoes.jsonl")
    saida.parent.mkdir(parents=True, exist_ok=True)
    pastas = _pastas_alvo(base)
    nomes = {p: str(_manifesto(p).get("processo") or p.name) for p in pastas}
    if obs_json:
        mapa = json.loads(Path(obs_json).read_text(encoding="utf-8"))
        for v in mapa.values():
            for o in v:
                o["data"] = date.fromisoformat(o["data"]) if o.get("data") else None
    else:
        import sqlite3
        db = db or (REPO / "data" / "compliance.db")
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
        try:
            mapa = mapa_obs_pagas(con, nomes.values())
        finally:
            con.close()
    tarefas = [(str(p), mapa.get(chave_processo(nomes[p]) or "", [])) for p in pastas]
    n = 0
    with saida.open("w", encoding="utf-8") as fh:
        if procs > 1:
            from multiprocessing import Pool
            with Pool(procs) as pool:
                for linha in pool.imap_unordered(_um_processo, tarefas, chunksize=1):
                    if linha:
                        fh.write(linha + "\n")
                        n += 1
        else:
            for t in tarefas:
                linha = _um_processo(t)
                if linha:
                    fh.write(linha + "\n")
                    n += 1
    return {"processos": n, "saida": str(saida)}


if __name__ == "__main__":   # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(description="foto × quantitativo")
    ap.add_argument("acao", choices=["varrer", "obs"])
    ap.add_argument("--base", type=Path, default=BASE_ACERVO)
    ap.add_argument("--saida", type=Path)
    ap.add_argument("--obs-json", type=Path)
    ap.add_argument("--procs", type=int, default=1)
    a = ap.parse_args()
    if a.acao == "obs":
        print(exportar_obs(a.saida or (REPO / "data" / "foto_quantitativo" / "obs_pagas.json"), a.base))
    else:
        print(json.dumps(varrer(a.base, a.saida, obs_json=a.obs_json, procs=a.procs), ensure_ascii=False))
