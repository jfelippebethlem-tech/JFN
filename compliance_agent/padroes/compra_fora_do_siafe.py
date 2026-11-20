# -*- coding: utf-8 -*-
"""Compra fora do SIAFE: incorporação patrimonial (SEDEC/CBMERJ/FUNESBOM, SEI 27xxxx) de bem cuja NF foi emitida
contra o CNPJ do órgão, paga à vista/PIX/boleto/cartão/"verba da unidade", SEM nota de empenho nos autos e SEM
nenhuma OB do SIAFE ao emitente.

ORIGEM (perícias de 18–19/11/2026, `data/pericia_agentes/`): SEI-270118/001445/2021 (9 NF, PIX), 270107/000106/2022
(Mercado Livre), 270087/000395/2022 (Americanas), 270073/000049/2022 ("verba própria"), 270089/000911/2023 (AUTORIZO
depois da NF), 270098/000603/2022 (IMPRESSISTEM × MOVEMAQ: mesmo sócio/telefone, pedidos 14.967/14.968, 75 s),
270063/000216/2022 (faturada com vencimento e dados bancários, sem OB).

MECANISMO MEDIDO (19/11/2026): a Resolução SEDEC 113/2018 (alterada pela 186/2020) institui o REDE/FUNESBOM —
Regime de Desembolso Descentralizado: o FUNESBOM (UG 166100, CNPJ 28.176.998/0004-41) empenha 3.3.90.39 ao PRÓPRIO
CNPJ (NE mensal, ex.: 2025NE02806 R$ 10.500.000,00 no SEI-270006/002628/2025), paga OB ao próprio CNPJ (~300 por mês,
mediana R$ 2.000,00 — as cotas das unidades) e a unidade compra no varejo; a CI PAGCENT nº 92/2023 (SEI-270089/000453/2023
doc 1) ORIENTA o gestor a usar a "verba de operacionalização". Logo o fornecedor nunca aparece como credor no SIAFE e a
NF não tem NE própria: o padrão é INSTITUCIONAL (execução descentralizada sem empenho por fornecedor), não do servidor.
O que a varredura mede é a fronteira: (i) NF que o processo amarra a uma explicação (doação, suprimento de fundos,
verba/REDE) e (ii) NF sem nenhuma explicação nos autos — essa pede a prestação de contas da cota (Res. 113 arts. 4º–5º).

SUBSINAIS: emitentes "irmãos" no mesmo processo (mesmo telefone, mesmo sócio no QSA, pedidos consecutivos ou emissão
em ≤ 5 min) e NF faturada (vencimento/duplicata/dados bancários) sem OB ao emitente — possível dívida sem empenho.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date

from compliance_agent.padroes import _pagamento_comum as P
from compliance_agent.padroes._comum import mascarar_cpf
from compliance_agent.cpf_cnpj import cnpj_valido as cnpj_ok

ID = "compra_fora_do_siafe"
def _parametros() -> dict:
    """CNPJ/UG do órgão vêm da ficha (config/padroes/compra_fora_do_siafe.yaml) — PAD-12: nada de CNPJ literal."""
    import yaml
    with open(P.RAIZ / "config" / "padroes" / f"{ID}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["parametros"]


_PAR = _parametros()
CNPJ_FUNESBOM = str(_PAR["cnpj_funesbom"])
RAIZ_ORGAO = CNPJ_FUNESBOM[:8]                 # SEDEC / CBMERJ / FUNESBOM
UG_SEDEC = tuple(str(u) for u in _PAR["ugs_sedec"])
_ESTATAIS = {str(r) for r in _PAR["raizes_estatais"]}   # órgão + Estado do RJ (nunca emitente de NF de varejo)

_RE_TIT_NF = re.compile(r"nota\s*fiscal|\bNF\b|\bNF-?e\b|DANFE|cupom\s+fiscal|\brecibo\b", re.I)
_RE_TIT_INC = re.compile(r"incorp|icorpora", re.I)
_RE_TIT_NE = re.compile(r"nota\s+de\s+empenho|\bNE\s+20\d\dNE", re.I)
_RE_NE_NUM = re.compile(r"\b20\d\dNE\d{3,6}\b")
_RE_CNPJ = re.compile(r"(?<!\d)(\d{2})[.\s]?(\d{3})[.\s]?(\d{3})\s?/?\s?(\d{4})\s?-?\s?(\d{2})(?!\d)")
_RE_CHAVE = re.compile(r"(?:\d[\s.,]*){44}")
_RE_VALOR_NF = re.compile(r"(?:V\.\s*Liq\.?|V\.\s*Orig\.?|Valor\s+a\s+pagar\s+R\$?|VALOR\s+TOTAL\s+DA\s+NOTA|VALOR\s+DA\s+NOTA|V(?:ALO)?R\.?\s+TOTAL(?:\s+DA\s+NF)?|TOTAL\s+A\s+PAGAR|"
                          r"Valor\s+a\s+Pagar)[^\d]{0,40}(" + P.MOEDA + ")", re.I)
_RE_DATA = re.compile(r"(?:DATA\s+(?:DE\s+|DA\s+)?EMISS[ÃA]O|EMISS[ÃA]O|Emitida\s+em)\s*:?\s*(\d{2}/\d{2}/\d{2,4})", re.I)
_RE_DATA_HORA = re.compile(r"(\d{2}/\d{2}/\d{2,4})\s*(?:[-–às]+\s*)?(\d{2}):(\d{2}):(\d{2})")
_RE_FONE = re.compile(r"\(?\b(\d{2})\)?\s?(\d{4,5})[-.\s]?(\d{4})\b")
_RE_PEDIDO = re.compile(r"PED(?:IDO)?\.?\s*(?:/\s*FAT)?\.?\s*(?:N[º°o]\.?)?\s*:?[^\d]{0,6}(\d{1,3}(?:\.\d{3})+|\d{3,9})", re.I)

FORMAS = {   # forma de pagamento citada (NF ou autos)
    "pix": r"\bPIX\b",
    "dinheiro": r"\bdinheiro\b|pag[oa]\s+em\s+esp[ée]cie",   # "ESPÉCIE" sozinho é campo de volume do DANFE
    "a_vista": r"[àa]\s+vista\b",
    "boleto": r"\bboleto\b",
    "cartao": r"cart[ãa]o\s+(?:de\s+)?(?:cr[ée]dito|d[ée]bito)",
    "deposito_transferencia": r"dep[óo]sito\s+(?:em\s+conta|banc)|transfer[êe]ncia\s+banc",
    "marketplace": r"mercado\s*livre|americanas|magazine\s+luiza|amazon|shopee|kabum",
    # "FATURA/VENCIMENTO" é bloco padrão do DANFE — só conta a NF que manda pagar em conta ou a prazo
    "faturado": r"dados\s+banc[áa]rios|pagamento\s+a\s+prazo|faturad[oa]\s+(?:com|para|em\s+nome)",
}
_RE_FORMAS = {k: re.compile(v, re.I) for k, v in FORMAS.items()}
_RE_DOACAO = re.compile(r"termo\s+de\s+doa[çc][ãa]o|\bdoad[oa]s?\s+(?:pel[oa]|por|à|ao)|recebid[oa]s?\s+(?:em|por|como)\s+doa[çc][ãa]o|"
                        r"\bdoa[çc][ãa]o\s+(?:de|d[oa]s?|feita|realizada)\b", re.I)
_RE_SUPRIMENTO = re.compile(r"suprimento\s+de\s+fundos|\bsuprid[oa]\b|adiantamento\s+(?:de\s+)?numer[áa]rio", re.I)
_RE_VERBA = re.compile(r"verba\s+(?:de\s+)?operacionaliza|verba\s+pr[óo]pria|verba\s+da\s+(?:pr[óo]pria\s+)?unidade|"
                       r"\bREDE\s*/\s*FUNESBOM|desembolso\s+descentralizado|cota\s+(?:de\s+)?operacionaliza|"
                       r"recursos?\s+(?:pr[óo]prios?\s+)?da\s+(?:pr[óo]pria\s+)?unidade", re.I)
_RE_AUTORIZO = re.compile(r"\bAUTORIZO\b|autoriza[çc][ãa]o\s+(?:de|para)\s+(?:a\s+)?compra", re.I)


# ----------------------------------------------------------------------------------------------- funções puras
def chave_ok(ch: str) -> bool:
    """DV (módulo 11) da chave de acesso NF-e de 44 dígitos."""
    if len(ch) != 44 or not ch.isdigit():
        return False
    s, peso = 0, 2
    for d in reversed(ch[:43]):
        s += int(d) * peso
        peso = 2 if peso == 9 else peso + 1
    r = s % 11
    return str(0 if r < 2 else 11 - r) == ch[43]


def chaves(texto: str) -> list[str]:
    out = []
    for m in _RE_CHAVE.finditer(texto):
        d = re.sub(r"\D", "", m.group(0))
        if len(d) == 44 and d[:2] in ("33", "35", "31", "32", "41", "42", "43", "50", "52", "53", "29", "26", "23") \
                and d not in out:
            out.append(d)
    return out


def _data(s: str | None) -> str | None:
    if not s:
        return None
    d, m, a = s.split("/")
    a = a if len(a) == 4 else "20" + a
    try:
        return date(int(a), int(m), int(d)).isoformat()
    except ValueError:
        return None


def segmentos(texto: str) -> list[str]:
    """Um documento SEI pode trazer várias NF (OCR de 9 notas num PDF): corta em cada 'DANFE'/'Documento Auxiliar'
    quando há mais de um; senão o documento é uma NF só."""
    marcas = [m.start() for m in re.finditer(r"DANFE|Documento\s+Auxiliar\s+d", texto, re.I)]
    if len(marcas) < 2:
        return [texto]
    marcas = [0] + marcas[1:]
    return [texto[a:b] for a, b in zip(marcas, marcas[1:] + [len(texto)])]


def extrair_nf(texto: str) -> dict:
    """Emitente(s) CNPJ (DV válido; chave de acesso primeiro), contra o órgão?, valor, data, hora, fone, pedido."""
    t = texto
    emit, fonte_emit = [], None
    for ch in chaves(t):
        c = ch[6:20]
        if (chave_ok(ch) or cnpj_ok(c)) and cnpj_ok(c) and c[:8] not in _ESTATAIS and c not in emit:
            emit.append(c)
            fonte_emit = "chave_de_acesso"
    contra = False
    for m in _RE_CNPJ.finditer(t):
        c = "".join(m.groups())
        if c.startswith(RAIZ_ORGAO):
            contra = True
            continue
        if cnpj_ok(c) and c[:8] not in _ESTATAIS and c not in emit and not emit:
            emit.append(c)
            fonte_emit = fonte_emit or "texto"
    if not contra and re.search(r"[.\s]?".join((RAIZ_ORGAO[:2], RAIZ_ORGAO[2:5], RAIZ_ORGAO[5:8])), t):
        contra = True
    # OCR perde o CNPJ do destinatário com frequência; o nome da unidade como destinatário também vale
    contra_nome = bool(re.search(r"CORPO\s+DE\s+BOMBEIROS|CBMERJ|\bG\.?B\.?M\b|GRUPAMENTO\s+DE\s+BOMBEIRO|DEFESA\s+CIVIL|"
                                 r"FUNESBOM|BOMBEIROS?\s+MILITAR", t, re.I))
    valor = valor_nf(t)
    md = _RE_DATA.search(t)
    mh = _RE_DATA_HORA.search(t)
    data = _data(md.group(1)) if md else (_data(mh.group(1)) if mh else None)
    hora = (f"{mh.group(2)}:{mh.group(3)}:{mh.group(4)}" if mh else None)
    fones = sorted({f"{a}{b}{c}" for a, b, c in _RE_FONE.findall(t)
                    if not a.startswith("0") and len(set(b + c)) > 2})   # 0000-0000 / 1111-1111 não é telefone
    mp = _RE_PEDIDO.search(t)
    pedido = int(re.sub(r"\D", "", mp.group(1))) if mp else None
    return {"emitentes": emit, "fonte_emitente": fonte_emit, "contra_orgao": contra or contra_nome,
            "contra_orgao_cnpj": contra, "valor": valor, "data": data,
            "hora": hora, "fones": fones, "pedido": pedido}


_RE_DIN = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})(?![\d])")
_RE_CAB_NOTA = re.compile(r"VALOR\s+TOTAL\s+DA\s+NOTA|VALOR\s+L[ÍI]QUIDO\s+DA\s+NOTA|TOTAL\s+DA\s+NOTA", re.I)
_RE_CAB_PROD = re.compile(r"VALOR\s+TOTAL\s+DOS\s+(?:PRODUTOS|SERVI[ÇC]OS)", re.I)


def _din(s: str) -> float | None:
    """'1.019,16' / '3.823.49' (OCR troca vírgula por ponto) → float: o último separador é o decimal."""
    d = re.sub(r"\D", "", s)
    return round(int(d) / 100, 2) if d else None


def valor_nf(texto: str) -> float | None:
    """Valor total da NF. DANFE é tabela: o rótulo fica numa linha e o número na seguinte (último da linha).
    Ordem: total da nota > total dos produtos/serviços > rótulo em linha ("Valor Total: 1.113,00")."""
    linhas = texto.splitlines()
    for cab in (_RE_CAB_NOTA, _RE_CAB_PROD):
        cands = []
        for i, ln in enumerate(linhas):
            if not cab.search(ln):
                continue
            resto = ln[cab.search(ln).end():]
            nums = [_din(x) for x in _RE_DIN.findall(resto)]
            if not nums:
                prox = [x for x in linhas[i + 1:i + 4] if x.strip()][:2]
                for x in prox:
                    nums = [_din(y) for y in _RE_DIN.findall(x)]
                    if nums:
                        break
            nums = [n for n in nums if n]
            if nums:
                cands.append(nums[-1])
        if cands and max(cands) > 0:       # OCR que perde o número deixa "0,00" no lugar: não é valor
            return max(cands)
    m = _RE_VALOR_NF.search(texto)
    return _din(m.group(1)) if m else None


def formas_pagamento(texto: str) -> list[str]:
    return [k for k, r in _RE_FORMAS.items() if r.search(texto)]


def explicacao(texto_autos: str) -> tuple[str | None, str | None]:
    """(classe, trecho) da explicação inocente citada nos autos — ordem: doação > suprimento > verba/REDE."""
    for classe, rx in (("doacao", _RE_DOACAO), ("suprimento_de_fundos_provavel", _RE_SUPRIMENTO),
                       ("verba_operacionalizacao", _RE_VERBA)):
        m = rx.search(texto_autos)
        if m:
            return classe, P.trecho(texto_autos, m.start(), m.end(), 80)
    return None, None


def classificar(tem_ne: bool, ob_ao_emitente: bool, expl: str | None) -> str:
    if tem_ne or ob_ao_emitente:
        return "dentro_do_siafe"
    return expl or "fora_do_siafe_sem_explicacao"


def _seg(h: str | None) -> int | None:
    if not h:
        return None
    a, b, c = (int(x) for x in h.split(":"))
    return a * 3600 + b * 60 + c


def irmas(nfs: list[dict], socios: dict[str, set] | None = None) -> list[dict]:
    """Pares de NF do MESMO processo com emitentes de raiz diferente que dividem telefone ou sócio, ou têm pedidos
    consecutivos (|Δ| ≤ 2) ou emissão no mesmo dia com Δ ≤ 300 s. Função pura."""
    socios = socios or {}
    # telefone em NF de 3+ emitentes distintos é do COMPRADOR (a unidade) impresso no destinatário, não vínculo
    raizes_do_fone: dict[str, set] = {}
    for nf in nfs:
        for x in nf.get("fones") or []:
            if nf.get("emitentes"):
                raizes_do_fone.setdefault(x[-7:], set()).add(nf["emitentes"][0][:8])
    comprador = {k for k, v in raizes_do_fone.items() if len(v) >= 3}
    out = []
    for i, a in enumerate(nfs):
        for b in nfs[i + 1:]:
            ea, eb = (a.get("emitentes") or [None])[0], (b.get("emitentes") or [None])[0]
            if not ea or not eb or ea[:8] == eb[:8]:
                continue
            motivos = []
            # últimos 7 dígitos: o OCR troca o 9º dígito do celular e o DDD
            f = ({x[-7:] for x in a.get("fones") or [] if not x[-7:].startswith("00") and len(set(x[-7:])) > 3} &
                 {x[-7:] for x in b.get("fones") or []}) - comprador
            # só vale o telefone que a Receita registra para um dos dois emitentes (o do destinatário não é vínculo)
            rec_ab = {x[-7:] for x in (a.get("fones_receita") or []) + (b.get("fones_receita") or [])}
            f &= rec_ab
            if f:
                motivos.append(f"telefone {sorted(f)[0]}")
            s = socios.get(ea[:8], set()) & socios.get(eb[:8], set())
            if s:
                motivos.append("sócio comum no QSA")
            if a.get("pedido") and b.get("pedido") and 0 < abs(a["pedido"] - b["pedido"]) <= 2:
                motivos.append(f"pedidos {a['pedido']}/{b['pedido']}")
            sa, sb = _seg(a.get("hora")), _seg(b.get("hora"))
            if a.get("data") and a.get("data") == b.get("data") and sa is not None and sb is not None \
                    and abs(sa - sb) <= 300:
                motivos.append(f"emitidas com {abs(sa - sb)} s de diferença")
            if motivos:
                out.append({"emitentes": [ea, eb], "docs": [a.get("doc"), b.get("doc")], "motivos": motivos})
    return out


# ----------------------------------------------------------------------------------------------- acervo
_RE_SECAO_AAPAT = re.compile(r"(INCORPORA[ÇC][ÃA]O|DESFAZIMENTO|MOVIMENTA[ÇC][ÃA]O(?:\s+DEFINITIVA)?|ERRATA|BAIXA\w*|"
                             r"TRANSFER[ÊE]NCIA\w*|CESS[ÃA]O|ALIENA[ÇC][ÃA]O|DOA[ÇC][ÃA]O)")


def secoes_aapat(texto: str) -> dict[str, str]:
    """{tag: ''} da seção INCORPORAÇÃO de uma publicação AAPAT. A unidade NÃO é lida daqui: a extração do PDF intercala
    as colunas processo/unidade (unidade com 2 processos sai "A código nome B") e a atribuição seria chute — a unidade
    do relatório é o prefixo SEI do protocolo. Função pura."""
    out: dict[str, str] = {}
    secao, pend, codigo = None, [], False
    for ln in texto.splitlines():
        s = ln.strip()
        if _RE_SECAO_AAPAT.fullmatch(s):
            secao, pend, codigo = s, [], False
            continue
        ms = re.match(r"SEI[- ]?(\d{6})/(\d{6})/(\d{4})", s)
        if ms:
            if secao and secao.startswith("INCORPORA"):
                if codigo:
                    pend, codigo = [], False
                pend.append(f"{ms[1]}_{ms[2]}_{ms[3]}")
                out.setdefault(pend[-1], "")
            continue
        if re.fullmatch(r"160\d{4}", s):
            codigo = bool(pend)
            continue
        if codigo and s:
            pend, codigo = [], False
    return out


def _aapat_incorporacoes() -> dict[str, str]:
    """{tag: unidade} de toda publicação AAPAT do acervo 27* (a cópia mais longa de cada número)."""
    melhor: dict[str, tuple] = {}
    for pasta in P.ACERVO.glob("27*"):
        man = P.manifesto(pasta)
        if not man:
            continue
        for d in P.docs(man):
            m = re.search(r"AAPAT\s*(\d{2}/\d{4})", str(d.get("titulo") or ""))
            if m and int(d.get("chars") or 0) > (melhor.get(m.group(1)) or (0,))[0]:
                melhor[m.group(1)] = (int(d.get("chars") or 0), pasta, man, d)
    out: dict[str, str] = {}
    for _, pasta, man, d in melhor.values():
        for tg, u in secoes_aapat(P.ler(pasta, man, d)).items():
            if u or tg not in out:
                out[tg] = u or out.get(tg, "")
    return out


def universo() -> dict[str, str]:
    """{tag: unidade|''}: 27* com documento de incorporação no título, ou listado em INCORPORAÇÃO de uma AAPAT."""
    out = {t: u for t, u in _aapat_incorporacoes().items() if (P.ACERVO / t).is_dir()}
    for pasta in P.ACERVO.glob("27*"):
        man = P.manifesto(pasta)
        if man and any(_RE_TIT_INC.search(str(d.get("titulo") or "")) and "AAPAT" not in str(d.get("titulo") or "")
                       for d in P.docs(man)):
            out.setdefault(pasta.name, "")
    return out


# ----------------------------------------------------------------------------------------------- SIAFE
def obs_ao_credor(con, cnpj: str) -> list[dict]:
    """OB pagas (CNF-02) ao CNPJ exato e à raiz (filiais) — consulta pelo índice de `credor`, nunca a tabela inteira."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    q = (f"SELECT numero_ob, ug_emitente, data_emissao, credor, valor FROM ob_orcamentaria_siafe "
         f"WHERE credor >= ? AND credor < ? AND {_ob_paga(con)}")
    return [dict(zip(("numero_ob", "ug", "data", "credor", "valor"), r))
            for r in con.execute(q, (cnpj[:8], cnpj[:8] + "~"))]


def nes_ao_credor(con, cnpj: str) -> list[dict]:
    q = "SELECT numero, ug_emitente, data_emissao, natureza, valor FROM ne_siafe WHERE credor >= ? AND credor < ?"
    try:
        return [dict(zip(("numero", "ug", "data", "natureza", "valor"), r)) for r in con.execute(q, (cnpj[:8], cnpj[:8] + "~"))]
    except sqlite3.OperationalError:
        return []


RECEITA = P.RAIZ / "data" / "receita_estab.db"


def _rec():
    return sqlite3.connect(f"file:{RECEITA}?mode=ro", uri=True, timeout=60) if RECEITA.is_file() else None


def razao(con, cnpj: str, rec=None) -> str | None:
    """Razão social pela raiz: Receita (empresas, nacional) > empresas_cadastro da casa."""
    if rec is not None:
        r = rec.execute("SELECT razao_social FROM empresas WHERE cnpj_basico=?", (cnpj[:8],)).fetchone()
        if r and r[0]:
            return r[0]
    r = con.execute("SELECT razao_social FROM empresas_cadastro WHERE cnpj_basico=?", (cnpj[:8],)).fetchone()
    return r[0] if r else None


def fones_receita(rec, cnpj: str) -> list[str]:
    if rec is None:
        return []
    r = rec.execute("SELECT telefone1, telefone2 FROM estabelecimentos WHERE cnpj=?", (cnpj,)).fetchone()
    return [re.sub(r"\D", "", x) for x in (r or []) if x and len(re.sub(r"\D", "", x)) >= 8]


def _socios(con, raizes: set[str]) -> dict[str, set]:
    out: dict[str, set] = {}
    for rz in raizes:
        try:
            rows = con.execute("SELECT COALESCE(NULLIF(doc_socio,''), nome_norm) FROM socios_receita WHERE cnpj_basico=?",
                               (rz,)).fetchall()
        except sqlite3.OperationalError:
            return {}
        out[rz] = {r[0] for r in rows if r[0]}
    return out


def serie_cotas(con) -> dict[str, dict]:
    """OB pagas do FUNESBOM ao próprio CNPJ (as cotas do REDE) por ano: n, total, mediana."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    out: dict[str, dict] = {}
    q = (f"SELECT exercicio, valor FROM ob_orcamentaria_siafe WHERE credor=? AND ug_emitente='166100' AND {_ob_paga(con)}")
    por: dict[str, list] = {}
    for ex, v in con.execute(q, (CNPJ_FUNESBOM,)):
        por.setdefault(str(ex), []).append(float(v or 0))
    for ex, vs in sorted(por.items()):
        vs.sort()
        out[ex] = {"n_ob": len(vs), "total": round(sum(vs), 2), "mediana": vs[len(vs) // 2]}
    return out


def _razao_no_texto(rz: str | None, texto: str) -> bool:
    if not rz:
        return False
    palavras = [w for w in re.findall(r"[A-Z0-9]{4,}", P.norm(rz).upper())
                if w not in ("LTDA", "EIRELI", "COMERCIO", "SERVICOS", "INDUSTRIA", "BRASIL")]
    tn = P.norm(texto).upper()
    return any(w in tn for w in palavras[:3])


# ----------------------------------------------------------------------------------------------- varredura
def avaliar(tag: str, unidade: str, con, rec=None) -> dict | None:
    pasta = P.ACERVO / tag
    man = P.manifesto(pasta)
    if not man:
        return None
    ds = P.docs(man)
    textos = {d["i"]: P.ler(pasta, man, d, 60000) for d in ds if "AAPAT" not in str(d.get("titulo") or "")}
    autos = "\n".join(textos.values())
    tem_ne_doc = [d["i"] for d in ds if _RE_TIT_NE.search(str(d.get("titulo") or ""))]
    nes_txt = sorted(set(_RE_NE_NUM.findall(autos)))
    nfs = []
    for d in ds:
        tit = str(d.get("titulo") or "")
        t = textos.get(d["i"], "")
        if not t or _RE_TIT_NE.search(tit) or re.search(r"doa[çc][ãa]o", tit, re.I):   # termo de doação não é NF
            continue
        if not (_RE_TIT_NF.search(tit) or re.search(r"DANFE|chave\s+de\s+acesso|NFS-?e|nota\s+fiscal\s+eletr", t[:4000], re.I)):
            continue
        doc_nfs = []
        for k, seg in enumerate(segmentos(t)):
            nf = extrair_nf(seg)
            if not (nf["emitentes"] or nf["valor"] or nf["contra_orgao"]):
                continue
            nf.update(doc=d["i"], seg=k, titulo=tit[:80], formas=formas_pagamento(seg))
            # canhoto e corpo do mesmo DANFE caem em segmentos vizinhos: funde o que repete o emitente sem valor
            if doc_nfs and nf["emitentes"][:1] == doc_nfs[-1]["emitentes"][:1] and not (nf["valor"] and doc_nfs[-1]["valor"]):
                ant = doc_nfs[-1]
                for c in ("valor", "data", "hora", "pedido"):
                    ant[c] = ant[c] or nf[c]
                ant["fones"] = sorted(set(ant["fones"]) | set(nf["fones"]))
                ant["formas"] = sorted(set(ant["formas"]) | set(nf["formas"]))
                continue
            doc_nfs.append(nf)
        if not doc_nfs:   # NF juntada mas ilegível no OCR: conta no universo, OB ao emitente fica INDISPONÍVEL
            doc_nfs.append({"emitentes": [], "fonte_emitente": None, "contra_orgao": False, "contra_orgao_cnpj": False,
                            "valor": None, "data": None, "hora": None, "fones": [], "pedido": None, "doc": d["i"],
                            "seg": 0, "titulo": tit[:80], "formas": formas_pagamento(t), "ilegivel": True})
        for nf in doc_nfs:
            if not any(x["doc"] != nf["doc"] and x["emitentes"][:1] == nf["emitentes"][:1] and x["valor"] == nf["valor"]
                       and nf["emitentes"] for x in nfs):     # mesma NF juntada duas vezes não soma duas vezes
                nfs.append(nf)
    if not nfs:
        return {"tag": tag, "sem_nf": True}
    # emitente: confirmar a raiz pela razão social no texto (OCR troca dígito)
    for nf in nfs:
        conf = []
        for c in nf["emitentes"]:
            rz = razao(con, c, rec)
            fr = fones_receita(rec, c)
            nf["fones_receita"] = sorted(set(nf.get("fones_receita") or []) | set(fr))
            nf["fones"] = sorted(set(nf["fones"]) | set(fr))
            conf.append({"cnpj": c, "razao_social": mascarar_cpf(rz) if rz else rz, "confirmado": bool(rz) and (
                nf["fonte_emitente"] == "chave_de_acesso" or _razao_no_texto(rz, textos.get(nf["doc"], "")))})
        nf["emitentes_conf"] = conf
    emitentes = sorted({c["cnpj"] for nf in nfs for c in nf["emitentes_conf"] if c["razao_social"]})
    obs, nes = {}, {}
    for c in emitentes:
        o = obs_ao_credor(con, c)
        if o:
            obs[c] = o
        n = nes_ao_credor(con, c)
        if n:
            nes[c] = n
    ob_sedec = {c: [o for o in os_ if o["ug"] in UG_SEDEC] for c, os_ in obs.items()}
    ob_sedec = {c: v for c, v in ob_sedec.items() if v}
    expl, trecho_expl = explicacao(autos)
    formas = sorted({f for nf in nfs for f in nf["formas"]} | set(formas_pagamento(autos)))
    tem_ne = bool(tem_ne_doc) or bool(nes_txt)
    classe = classificar(tem_ne, bool(ob_sedec), expl)
    datas = sorted(nf["data"] for nf in nfs if nf["data"])
    autorizo = _RE_AUTORIZO.search(autos)
    soc = _socios(con, {c[:8] for c in emitentes}) if len(emitentes) > 1 else {}
    return {
        "tag": tag, "processo": P.processo(tag), "unidade": unidade or f"SEI {tag[:6]}",
        "n_nf": len(nfs), "contra_orgao": any(nf["contra_orgao"] for nf in nfs),
        "contra_orgao_cnpj": any(nf.get("contra_orgao_cnpj") for nf in nfs),
        "emitente_verificado": bool(emitentes), "nf_ilegiveis": sum(1 for nf in nfs if nf.get("ilegivel")),
        "valor_nf": round(sum(nf["valor"] or 0 for nf in nfs), 2) if any(nf["valor"] for nf in nfs) else None,
        "nf_sem_valor_lido": sum(1 for nf in nfs if not nf["valor"]),
        "ano": (datas[0][:4] if datas else tag[-4:]), "datas_nf": datas[:1] + datas[-1:] if datas else [],
        "emitentes": [c for nf in nfs for c in nf["emitentes_conf"]],
        "formas": formas, "ne_nos_autos": tem_ne_doc or nes_txt[:5],
        "ob_ao_emitente": {c: {"n": len(v), "total": round(sum(o["valor"] for o in v), 2),
                               "ugs": sorted({o["ug"] for o in v})} for c, v in obs.items()},
        "ob_sedec_ao_emitente": sorted(ob_sedec),
        "ne_siafe_ao_emitente": {c: len(v) for c, v in nes.items()},
        "explicacao": trecho_expl, "classificacao": classe,
        "autorizacao_citada": P.trecho(autos, autorizo.start(), autorizo.end(), 60) if autorizo else None,
        "irmas": irmas(nfs, soc),
        "faturado_sem_ob": ("faturado" in formas and not obs and classe != "dentro_do_siafe"
                            and not {"pix", "dinheiro", "a_vista", "cartao"} & set(formas)),
        "nfs": [{k: nf[k] for k in ("doc", "seg", "titulo", "data", "hora", "valor", "contra_orgao", "formas",
                                     "fones", "pedido")} | {"emitentes": nf["emitentes_conf"]} for nf in nfs],
    }


def varrer(limite: int | None = None) -> dict:
    uni = universo()
    tags = sorted(uni)[: limite or None]
    con = P.con_ro()
    rec = _rec()
    proc, sem_nf = [], []
    for t in tags:
        r = avaliar(t, uni[t], con, rec)
        if r is None:
            continue
        if r.get("sem_nf"):
            sem_nf.append(t)
            continue
        proc.append(r)
    # doação não é compra: fica contada na classificação, fora dos achados e das somas por unidade/ano
    no_padrao = [r for r in proc if r["classificacao"] not in ("dentro_do_siafe", "doacao")]
    cont: dict[str, dict] = {}
    por_unid: dict[str, float] = {}
    por_ano: dict[str, float] = {}
    for r in proc:
        c = cont.setdefault(r["classificacao"], {"processos": 0, "valor_nf": 0.0})
        c["processos"] += 1
        c["valor_nf"] = round(c["valor_nf"] + (r["valor_nf"] or 0), 2)
    for r in no_padrao:
        por_unid[r["unidade"]] = round(por_unid.get(r["unidade"], 0) + (r["valor_nf"] or 0), 2)
        por_ano[r["ano"]] = round(por_ano.get(r["ano"], 0) + (r["valor_nf"] or 0), 2)
    achados = []
    for r in no_padrao:
        grau = "medio" if r["classificacao"] == "fora_do_siafe_sem_explicacao" else "fraco"
        if not r["emitente_verificado"]:
            grau = "fraco"            # sem emitente legível a ausência de OB não foi medida
        if r["irmas"] or r["faturado_sem_ob"]:
            grau = "forte" if r["irmas"] else "medio"
        prova = "; ".join(f"doc {nf['doc']} ({nf['titulo'][:50]}) — emitente "
                          f"{(nf['emitentes'][0]['cnpj'] if nf['emitentes'] else 'ilegível')}, "
                          f"R$ {P.fmt(nf['valor']) if nf['valor'] else 'valor ilegível'}, {nf['data'] or 's/ data'}"
                          for nf in r["nfs"][:4])
        achados.append({
            "processo": r["processo"], "grau": grau, "prova": prova, "valor_pago_ob": None,
            "valor_nf": r["valor_nf"], "classificacao": r["classificacao"], "unidade": r["unidade"], "ano": r["ano"],
            "formas_pagamento": r["formas"], "ne_nos_autos": r["ne_nos_autos"],
            "ob_ao_emitente": r["ob_ao_emitente"] if r["emitente_verificado"] else "INDISPONÍVEL (emitente ilegível no OCR)",
            "contra_orgao": r["contra_orgao"], "irmas": r["irmas"], "faturado_sem_ob": r["faturado_sem_ob"],
            "porque": ("NF contra o CNPJ do órgão sem NE nos autos e sem OB da SEDEC/FUNESBOM ao emitente. Mecanismo "
                       "institucional provável: REDE/FUNESBOM (Res. SEDEC 113/2018) — a despesa está empenhada ao "
                       "próprio CNPJ e a prova de regularidade é a prestação de contas mensal da cota (arts. 4º–5º). "
                       f"Explicação citada nos autos: {r['explicacao'] or 'nenhuma'}."),
            "fonte": "autos SEI (arquivo) + SIAFE ob_orcamentaria_siafe/ne_siafe por credor",
        })
    res = P.resultado(ID, len(proc), {
        "nota": ("universo = 27* com documento de incorporação no título ou listado em INCORPORAÇÃO de AAPAT; "
                 "'valor_pago_ob' é None porque a compra não tem OB por fornecedor — o valor é o da NF (não é pago "
                 "SIAFE). ne_siafe só cobre UG 166100/2025."),
        "processos_sem_nf_legivel": len(sem_nf), "universo_bruto": len(tags)}, achados, "autos SEI + SIAFE")
    res["prevalencia"] = {"processos_com_nf": len(proc), "no_padrao": len(no_padrao),
                          "pct": round(100 * len(no_padrao) / len(proc), 1) if proc else None,
                          "com_emitente_verificado": sum(1 for r in no_padrao if r["emitente_verificado"]),
                          "com_valor_lido": sum(1 for r in no_padrao if r["valor_nf"]),
                          "nf_contra_cnpj_do_orgao": sum(1 for r in no_padrao if r["contra_orgao_cnpj"])}
    res["classificacao"] = cont
    res["valor_nf_por_unidade"] = dict(sorted(por_unid.items(), key=lambda x: -x[1]))
    res["valor_nf_por_ano"] = dict(sorted(por_ano.items()))
    res["cotas_rede_funesbom_ob"] = serie_cotas(con)
    res["processos"] = proc
    return res


if __name__ == "__main__":
    print(json.dumps(varrer(5), ensure_ascii=False, indent=1, default=str)[:4000])
