# -*- coding: utf-8 -*-
"""Casamento termo-de-risco × favorecido DENTRO DO MESMO ATO do DOERJ.

Por que existe (medido em 20/11/2026): a regra `doerj_anomalia` casava o nome do favorecido em
QUALQUER lugar da publicação e um termo de risco ('multa', 'rescisão', 'irregularidade'...) em
QUALQUER outro lugar dela. Uma "publicação" da tabela `publicacoes_doerj` é um bloco do diário com
dezenas de atos colados (até 78 atos, 95 mil caracteres): o favorecido estava num extrato de
contrato e o termo numa portaria de exoneração de outra pessoa. A triagem do Opus marcou 29 de 49
alertas como `provavel_falso_positivo` — a tupla (favorecido, termo) era híbrida, montada com
pedaços de atos diferentes (lição da casa: extrator-janela-simetrica-fabrica-tupla-hibrida).

O conserto é estrutural, não de prompt:
  1. o texto é cortado em ATOS pelo marcador de fim de ato do DOERJ ("Id: 2763138");
  2. o termo só conta no MESMO ato do favorecido, e perto dele (janela recortada pelas bordas do
     ato), sem CNPJ de outra empresa no meio (lista do INEA: a multa do vizinho não é dele);
  3. em ato SANCIONADOR em que o favorecido é a única empresa (nenhum outro CNPJ no ato), o termo
     vale no ato inteiro — a portaria que instaura o processo contra ela é sobre ela;
  4. ato de PESSOAL (nomeia/exonera/designa comissão/fiscais) não conta, salvo se for sancionador;
  5. favorecido localizado por CNPJ (com ou sem pontuação) ou nome normalizado (sem acento,
     pontuação, espaço duplo e hifenização de fim de linha — "INFORMÁ- TICA", "S/A" × "S.a").

Sem banco (só `re`/`unicodedata` e o classificador leve `entidades_gov`), para ser testável sem banco.
"""
from __future__ import annotations

import re
import unicodedata

# Variações flexionadas de cada termo (texto já normalizado: maiúsculo, sem acento, sem hífen de
# quebra). Antes era `termo in texto`: casava só a forma exata e perdia "IRREGULARIDADES".
_RX_TERMO = {
    "rescisão": r"RESCIS(?:AO|OES)",
    "improbidade": r"IMPROBIDADES?",
    "irregularidade": r"IRREGULARIDADES?",
    "condenação": r"CONDENA(?:CAO|COES)",
    "cassação": r"CASSA(?:CAO|COES)",
    "multa": r"MULTAS?",
    "embargos": r"EMBARGOS?",
    "inabilitação": r"INABILITA(?:CAO|COES)",
}
TERMOS_RISCO = tuple(_RX_TERMO)

# Distância máxima (caracteres) entre a menção ao favorecido e o termo, DENTRO do mesmo ato.
JANELA = 400

# Fim de ato no DOERJ: "... Id: 2763138 SECRETARIA DE ESTADO ...". O número fecha o ato anterior.
# NÃO confundir com a identidade funcional de servidor ("ID: 4368780-6"), que tem dígito verificador:
# cortar ali partia a portaria sancionadora ao meio e separava a empresa da multa.
_FIM_DE_ATO = re.compile(r"\bID:\s*\d{6,8}(?!\s*-\s*\d)(?![\d/.])")

# Sufixos societários: não identificam a empresa e mudam de grafia entre fontes (S.a / S/A / SA).
_SUFIXOS = {"LTDA", "ME", "EPP", "EIRELI", "SA", "S", "A", "SS", "CIA", "E"}

# Verbo operativo / objeto de ato de PESSOAL. Procurado só no CABEÇALHO do ato (início), onde o
# DOERJ põe o dispositivo ("NOMEIA", "DESIGNA servidores", "ALTERA COMISSÃO DE FISCALIZAÇÃO").
_CABECALHO = 600
_ATO_PESSOAL = re.compile(
    r"\b(NOMEIA|NOMEAR|EXONERA|EXONERAR|DESIGNA|DESIGNAR|DESIGNADOS?|CEDE|MANTEM A DISPOSICAO|"
    r"TORNA SEM EFEITO A (NOMEACAO|EXONERACAO|DESIGNACAO)|APOSENTA|"
    r"COMISSAO DE (FISCALIZACAO|GESTAO|AVALIACAO|RECEBIMENTO|ACOMPANHAMENTO)|"
    r"(GESTOR|GESTORES|FISCAL|FISCAIS) (SUBSTITUTO|TITULAR|SUPLENTE|DO CONTRATO|DOS CONTRATOS))\b")

# Ato cujo objeto é sancionar/apurar conduta de contratada (prevalece sobre "designa comissão").
# Só DISPOSITIVO de sanção (o ato aplica/instaura/notifica). Menção genérica ("cabendo aos fiscais
# propor a aplicação de multa", "sujeita às penalidades de") NÃO torna o ato sancionador.
_ATO_SANCIONADOR = re.compile(
    r"\b(SANCIONA(?:DOR|TORIO)|AUTO DE INFRACAO|NOTIFIQUE-SE|DECIDE PELA APLICACAO|APLICOU|"
    r"APLICA(?:-SE)? A (?:EMPRESA|CONTRATADA)|PENALIDADE:|RESCINDE|RESCISAO UNILATERAL|"
    r"DA CIENCIA .{0,300}? DA APLICACAO)")

_CNPJ_QUALQUER = re.compile(r"(?<!\d)\d{2}[.\s]?\d{3}[.\s]?\d{3}\s*/\s*\d{4}\s*-?\s*\d{2}(?!\d)")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def _normalizar(texto: str) -> tuple[str, list[int]]:
    """Texto maiúsculo, sem acento, sem hífen de quebra de linha ("INFORMÁ- TICA" → "INFORMATICA")
    e com espaços colapsados. Devolve também, para cada caractere, a posição no ORIGINAL — o
    trecho de evidência é sempre cortado do texto original, nunca da versão normalizada."""
    out: list[str] = []
    idx: list[int] = []
    i, n = 0, len(texto)
    while i < n:
        ch = texto[i]
        if ch == "-" and out and out[-1].isalpha():
            j = i + 1
            while j < n and texto[j] in " \t\r\n":
                j += 1
            if j > i + 1 and j < n and texto[j].isalpha() and texto[j].islower() == texto[i - 1].islower():
                i = j  # hífen de quebra: junta as metades da palavra
                continue
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                idx.append(i)
            i += 1
            continue
        base = unicodedata.normalize("NFD", ch)[0].upper()
        out.append(base[0])
        idx.append(i)
        i += 1
    return "".join(out), idx


# Abreviação que o classificador canônico não pega: "Rio De Janeiro Sec.de Estado Da Defesa Civil".
_SEC_ABREV = re.compile(r"\bSEC\.?\s*DE\s+ESTADO\b")
# Sufixo societário = pessoa jurídica de direito privado. O classificador canônico casa "uni[ãa]o\b"
# e marcaria "Uniao Norte Fluminense Eng. E Comercio Ltda" como ente — aqui isso NÃO pode ocorrer,
# porque descartar fornecedor real cega a regra.
_PRIVADO = re.compile(r"\b(LTDA|EIRELI|EPP|S\W?A|ME)\W*$|\bLTDA\b|\bEIRELI\b")


def eh_orgao_publico(nome: str) -> bool:
    """Favorecido que é o próprio ente (Secretaria, Município, Fundo...) — publicação do DOERJ
    sobre ele é ato do próprio Estado, não sanção a fornecedor. Reusa o classificador canônico,
    mas nunca descarta nome com sufixo societário (empresa privada)."""
    from compliance_agent.entidades_gov import eh_nao_fornecedor
    n = _sem_acento(nome or "").upper().strip()
    if not n or _PRIVADO.search(n):
        return False
    return eh_nao_fornecedor(n) or bool(_SEC_ABREV.search(n))


def padrao_cnpj(cpf_cnpj: str) -> re.Pattern | None:
    """CNPJ (14 dígitos) com ou sem pontuação, tolerando espaço de quebra de linha do diário."""
    d = re.sub(r"\D", "", cpf_cnpj or "")
    if len(d) != 14:
        return None
    sep = r"[\s./\-]*"
    grupos = (d[:2], d[2:5], d[5:8], d[8:12], d[12:])
    return re.compile(r"(?<!\d)" + sep.join(grupos) + r"(?!\d)")


def padrao_nome(nome: str) -> re.Pattern | None:
    """Nome normalizado em tokens, aceitando qualquer pontuação/espaço entre eles.

    Usa os tokens dos primeiros 30 caracteres (mesmo corte da busca SQL), sem o último se o corte
    o partiu, e sem sufixo societário. Exige ≥2 tokens ou ≥8 letras para não casar palavra solta."""
    bruto = _sem_acento(nome or "").upper()
    toks = re.findall(r"[A-Z0-9]+", bruto[:30])
    if len(bruto) > 30 and toks and re.match(r"[A-Z0-9]", bruto[30:31]) and bruto[29:30].isalnum():
        toks = toks[:-1]  # último token cortado no meio
    while toks and toks[-1] in _SUFIXOS:
        toks.pop()
    if not toks or (len(toks) < 2 and len(toks[0]) < 8):
        return None
    return re.compile(r"(?<![A-Z0-9])" + r"\W*".join(re.escape(t) for t in toks) + r"(?![A-Z0-9])")


def atos(texto_norm: str) -> list[tuple[int, int]]:
    """Fatias [ini, fim) de cada ato da publicação, cortadas no marcador de fim de ato."""
    cortes = [m.end() for m in _FIM_DE_ATO.finditer(texto_norm or "")]
    bordas = [0] + cortes + [len(texto_norm or "")]
    return [(a, b) for a, b in zip(bordas, bordas[1:]) if b > a]


def eh_ato_de_pessoal(seg_norm: str) -> bool:
    return bool(_ATO_PESSOAL.search(seg_norm[:_CABECALHO])) and not _ATO_SANCIONADOR.search(seg_norm)


def ocorrencias(texto: str, nome: str, cpf_cnpj: str = "") -> list[dict]:
    """Todas as ocorrências (termo de risco ↔ favorecido) no MESMO ato.

    Cada item: {termo, trecho, criterio}. `criterio` = 'janela' (termo a ≤ JANELA caracteres da
    menção, sem CNPJ alheio no meio) ou 'ato_sancionador_unico' (ato sancionador sem outra empresa).
    Ato de pessoal é descartado. Lista vazia = nada ligado ao favorecido."""
    if not texto:
        return []
    norm, idx = _normalizar(texto)
    pads = [p for p in (padrao_cnpj(cpf_cnpj), padrao_nome(nome)) if p is not None]
    if not pads:
        return []
    cnpj_fav = re.sub(r"\D", "", cpf_cnpj or "")
    termos = [(t, re.compile(r"(?<![A-Z])" + rx + r"(?![A-Z])")) for t, rx in _RX_TERMO.items()]
    achados: list[dict] = []
    for ini, fim in atos(norm):
        seg = norm[ini:fim]
        mencoes = sorted({m.start() for p in pads for m in p.finditer(seg)})
        if not mencoes or eh_ato_de_pessoal(seg):
            continue
        alheios = [m.span() for m in _CNPJ_QUALQUER.finditer(seg)
                   if re.sub(r"\D", "", m.group()) != cnpj_fav]
        unico_sancionador = not alheios and bool(_ATO_SANCIONADOR.search(seg))
        for termo, rx in termos:
            melhor = None  # (preferência, distância, pos_termo, pos_menção)
            for m in rx.finditer(seg):
                for p in mencoes:
                    d = abs(m.start() - p)
                    antes = m.start() < p
                    lo, hi = sorted((p, m.start()))
                    entre = any(lo < c0 and c1 <= hi for c0, c1 in alheios)
                    if not antes and entre:
                        continue  # CNPJ de OUTRA empresa no meio: o termo é do registro dela
                    if antes:
                        # Termo ANTES do nome: só vale se não estiver dentro do registro de outra
                        # empresa (lista do INEA: "NOME: OUTRA CNPJ ... Multa | NOME: FAVORECIDO") e
                        # se for o título do ato ("EXTRATO DE TERMO DE RESCISÃO ... PARTES: órgão,
                        # CNPJ, e FAVORECIDO") ou não houver outra empresa entre ele e o nome.
                        if any(c1 <= m.start() for _, c1 in alheios):
                            continue
                        if entre and m.start() > _CABECALHO:
                            continue
                    if d > JANELA and not unico_sancionador:
                        continue
                    # preferir o termo DEPOIS da menção (padrão "NOME ... PENALIDADE: Multa")
                    cand = (0 if m.start() > p else 1, d, m.start(), p)
                    if melhor is None or cand < melhor:
                        melhor = cand
            if melhor is None:
                continue
            _, d, pt, pm = melhor
            a = max(0, min(pt, pm) - 150)
            b = min(len(seg) - 1, max(pt, pm) + 250)
            achados.append({
                "termo": termo,
                "criterio": "janela" if d <= JANELA else "ato_sancionador_unico",
                "trecho": " ".join(texto[idx[ini + a]:idx[ini + b] + 1].split()),
            })
    return achados
