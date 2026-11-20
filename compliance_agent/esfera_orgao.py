# -*- coding: utf-8 -*-
"""FONTE ÚNICA de "o órgão é do RJ?" — esfera, Poder e UF de um órgão público pelo CNPJ.

Escopo do JFN (dono, 19/11/2026: "esquece a parte federal, nao queremos tratar disso" / "existe uma
defensoria em cada estado da federacao e um tce tambem. tem que ser do RJ"): Estado do RJ — todos os
Poderes e órgãos autônomos (Executivo, ALERJ, TJRJ, TCE-RJ, MPRJ, DPE-RJ, autarquias/fundações/empresas
estaduais com CNPJ próprio) — e Prefeitura do Rio. Federal, outros estados e outros municípios = FORA.

Por que existe: havia quatro lógicas de esfera (pcrj/esfera, collectors/pncp_resultados, orgao_fonte,
cores_orgaos), todas por regex de NOME. `SECRETARIA DE ESTADO` e `TRIBUNAL DE CONTAS DO ESTADO` casavam
órgão de QUALQUER estado, e o teste estadual vinha antes do federal: UNIRIO (federal) e os conselhos
regionais de profissão "DO ESTADO DO RIO DE JANEIRO" (autarquias federais) saíam "estadual-rj".

Ordem de PROVA (a primeira que responde decide; `via` e `prova` dizem qual):
  1. raiz do CNPJ conhecida (Estado do RJ 42498600 · Município do Rio 42498733 · União 00394);
  2. natureza jurídica da Receita (tabela oficial, grupo 1 = administração pública: diz federal/estadual/
     municipal e o Poder) + UF/município da SEDE (estabelecimento na Receita; sem ele, unidades do órgão
     no PNCP, coletadas e guardadas em `orgao_uf_pncp`);
  3. estatal (natureza 2xxx) / consórcio: nome federal → federal; marcador estadual/municipal + sede;
     esferaId do PNCP + UF (o PNCP erra: marcou a INB, federal, como "E" — por isso vem depois do nome
     federal);
  4. nome SÓ como último recurso: padrões federais ANTES de estadual, e estadual/municipal exigem
     "RIO DE JANEIRO" / "RJ" / "FLUMINENSE" no nome. Outro estado nomeado → outro-estado.
Sem sinal → "indefinido" (nunca chuta; indefinido NÃO é RJ).

O mapa CNPJ→esfera é materializado em `compliance.db.orgao_esfera` (com via/prova) por `materializar()`.
"""
from __future__ import annotations

import functools
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DB_COMPLIANCE = RAIZ / "data" / "compliance.db"
DB_RECEITA = RAIZ / "data" / "receita_estab.db"

ESFERAS = ("estadual-rj", "municipal-rio", "federal", "outro-estado", "outro-municipio", "indefinido")
NO_RJ = frozenset({"estadual-rj", "municipal-rio"})   # o escopo do JFN

RAIZ_ESTADO_RJ = "42498600"        # ESTADO DO RIO DE JANEIRO (Receita, natureza 1236)
RAIZ_MUNICIPIO_RIO = "42498733"    # MUNICIPIO DE RIO DE JANEIRO (Receita, natureza 1244)
RAIZES_RJ = {RAIZ_ESTADO_RJ: "estadual-rj", RAIZ_MUNICIPIO_RIO: "municipal-rio"}
RAIZ_UNIAO = "00394"               # base dos órgãos da administração direta da União
UF_RJ = "RJ"
MUNICIPIO_RIO_RECEITA = "6001"     # tabela Municipios da Receita (dump 2026-10): "6001";"RIO DE JANEIRO"
MUNICIPIO_RIO_IBGE = "3304557"

# Tabela OFICIAL de natureza jurídica da Receita (dump CNPJ 2026-10, arquivo Naturezas.zip, grupo 1 =
# administração pública). Código → (nível, Poder). Nível: F federal · E estadual/DF · M municipal.
# Conferida no arquivo baixado em 19/11/2026, não de memória.
NATUREZA_PUBLICA: dict[str, tuple[str, str]] = {
    "1015": ("F", "Executivo"),   # Órgão Público do Poder Executivo Federal
    "1023": ("E", "Executivo"),   # Órgão Público do Poder Executivo Estadual ou do Distrito Federal
    "1031": ("M", "Executivo"),   # Órgão Público do Poder Executivo Municipal
    "1040": ("F", "Legislativo"),  # Órgão Público do Poder Legislativo Federal
    "1058": ("E", "Legislativo"),  # Órgão Público do Poder Legislativo Estadual ou do Distrito Federal
    "1066": ("M", "Legislativo"),  # Órgão Público do Poder Legislativo Municipal
    "1074": ("F", "Judiciário"),  # Órgão Público do Poder Judiciário Federal
    "1082": ("E", "Judiciário"),  # Órgão Público do Poder Judiciário Estadual
    "1104": ("F", "Executivo"),   # Autarquia Federal (inclui conselhos de fiscalização profissional)
    "1112": ("E", "Executivo"),   # Autarquia Estadual ou do Distrito Federal
    "1120": ("M", "Executivo"),   # Autarquia Municipal
    "1139": ("F", "Executivo"),   # Fundação Pública de Direito Público Federal
    "1147": ("E", "Executivo"),   # Fundação Pública de Direito Público Estadual ou do Distrito Federal
    "1155": ("M", "Executivo"),   # Fundação Pública de Direito Público Municipal
    "1163": ("F", "Autônomo"),    # Órgão Público Autônomo Federal
    "1171": ("E", "Autônomo"),    # Órgão Público Autônomo Estadual ou do Distrito Federal
    "1180": ("M", "Autônomo"),    # Órgão Público Autônomo Municipal
    "1236": ("E", "Executivo"),   # Estado ou Distrito Federal
    "1244": ("M", "Executivo"),   # Município
    "1252": ("F", "Executivo"),   # Fundação Pública de Direito Privado Federal
    "1260": ("E", "Executivo"),   # Fundação Pública de Direito Privado Estadual ou do Distrito Federal
    "1279": ("M", "Executivo"),   # Fundação Pública de Direito Privado Municipal
    "1287": ("F", "Executivo"),   # Fundo Público da Administração Indireta Federal
    "1295": ("E", "Executivo"),   # Fundo Público da Administração Indireta Estadual ou do Distrito Federal
    "1309": ("M", "Executivo"),   # Fundo Público da Administração Indireta Municipal
    "1317": ("F", "Executivo"),   # Fundo Público da Administração Direta Federal
    "1325": ("E", "Executivo"),   # Fundo Público da Administração Direta Estadual ou do Distrito Federal
    "1333": ("M", "Executivo"),   # Fundo Público da Administração Direta Municipal
    "1341": ("F", "Executivo"),   # União
}
NATUREZA_CONSORCIO = {"1210", "1228"}     # Consórcio Público de Direito Público / Privado
from compliance_agent.credor_institucional import NATUREZA_ESTATAL  # noqa: E402  (empresa pública / SEM)
NATUREZA_ESTADUAL = frozenset(k for k, (n, _) in NATUREZA_PUBLICA.items() if n == "E")
NATUREZA_MUNICIPAL = frozenset(k for k, (n, _) in NATUREZA_PUBLICA.items() if n == "M")
NATUREZA_FEDERAL = frozenset(k for k, (n, _) in NATUREZA_PUBLICA.items() if n == "F")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.upper()).strip()


# ── Poder pelo nome (refina "Autônomo"/"Legislativo" da natureza: o TCE-RJ é 1058 Legislativo) ────────
PODER_POR_NOME = (
    (re.compile(r"tribunal de justi|\btjrj\b|poder judici", re.I), "Judiciário"),
    (re.compile(r"tribunal de contas|\btce\b", re.I), "Tribunal de Contas"),
    (re.compile(r"assembl[eé]ia legislativa|\balerj\b", re.I), "Legislativo"),
    (re.compile(r"minist[eé]rio p[uú]blico|\bmprj\b|procuradoria-geral de justi", re.I), "Ministério Público"),
    (re.compile(r"defensoria", re.I), "Defensoria Pública"),
)
# Sinal de ENTIDADE municipal no nome (não a substring "MUNICIP": a "SECRETARIA DE ESTADO DE APOIO AOS
# MUNICÍPIOS" é estadual). `\bpcrj\b` = sigla da Prefeitura do Rio usada nas notas do vault.
RX_MUNICIPAL = re.compile(
    r"\bMUNIC[IÍ]PIO\s+D[EO]\b|PREF(EITURA|\.)|\bMUN\.|C[ÂA]MARA\s+MUNICIPAL|FUNDO\s+MUNICIPAL|"
    r"SECRETARIA\s+MUNICIPAL|\bPCRJ\b|(?<!TEATRO )(?<!THEATRO )\bMUNICIPAL\b", re.I)   # Theatro Municipal é do Estado

# ── Nome (último recurso), sobre texto normalizado (sem acento, maiúsculo) ──────────────────────────
_RJ_MARCA = re.compile(r"RIO DE JANEIRO|\bRJ\b|FLUMINENSE|\bERJ\b|\bALERJ\b|\bTJRJ\b|\bMPRJ\b|\bUERJ\b")
_OUTRAS_UF = (r"ACRE|ALAGOAS|AMAPA|AMAZONAS|BAHIA|CEARA|DISTRITO FEDERAL|ESPIRITO SANTO|GOIAS|MARANHAO|"
              r"MATO GROSSO DO SUL|MATO GROSSO|MINAS GERAIS|PARAIBA|PARANA|PARA|PERNAMBUCO|PIAUI|"
              r"RIO GRANDE DO NORTE|RIO GRANDE DO SUL|RONDONIA|RORAIMA|SANTA CATARINA|SAO PAULO|SERGIPE|"
              r"TOCANTINS")
_OUTRO_ESTADO = re.compile(rf"\b(ESTADO|GOVERNO)\s+D[OEA]\s+({_OUTRAS_UF})\b")
# Federal ANTES de estadual. "MINISTERIO" exclui o MP estadual ("MINISTERIO PUBLICO DO ESTADO ...",
# "MINISTERIO PUBLICO DE CONTAS ..."); conselhos regionais/federais de profissão são autarquias federais.
_FEDERAL = re.compile(
    r"\bMINISTERIO\b(?!\s+PUBLICO\s+(DO\s+ESTADO|DE\s+CONTAS|ESTADUAL))|COMANDO D[AO] (MARINHA|EXERCITO|AERONAUTICA)|"
    r"UNIVERSIDADE FEDERAL|INSTITUTO FEDERAL|CENTRO FEDERAL|HOSPITAL FEDERAL|\bFEDERAL\b|"
    r"CONSELHO (REGIONAL|FEDERAL)\b|\bBNDES\b|OSWALDO CRUZ|\bFIOCRUZ\b|\bFIOTEC\b|\bUNIAO\b|"
    r"AGENCIA NACIONAL|CAIXA ECONOMICA|BANCO CENTRAL|BANCO DO BRASIL|TRIBUNAL REGIONAL|SUPERIOR TRIBUNAL|"
    r"CASA DA MOEDA|COLEGIO PEDRO II|\bFURNAS\b|CENTRAIS ELETRICAS|ELETROBRAS|ELETRONUCLEAR|"
    r"COMISSAO NACIONAL|COMPANHIA DE PESQUISA DE RECURSOS MINERAIS|SERVICO GEOLOGICO|PETROLEO BRASILEIRO|"
    r"PETROBRAS|EMPRESA BRASILEIRA|\bCORREIOS\b|\bSERPRO\b|\bDATAPREV\b|INSTITUTO NACIONAL|"
    r"FUNDACAO NACIONAL|CONSELHO NACIONAL|AGENCIA ESPACIAL|INDUSTRIAS NUCLEARES|\bNUCLEP\b|"
    r"INSTITUTO BRASILEIRO|DEPARTAMENTO NACIONAL|SUPERINTENDENCIA (FEDERAL|NACIONAL)|\bDNIT\b|\bIBGE\b|"
    r"\bIBAMA\b|\bINSS\b|\bUFRJ\b|\bUFF\b|\bUNIRIO\b|\bUFRRJ\b|\bCEFET\b|\bEBSERH\b|\bFINEP\b|"
    r"\bIMBEL\b|NAV BRASIL|PRE-SAL PETROLEO|\bEMGEPRON\b|PROJETOS NAVAIS|\bCNEN\b|\bINPI\b|\bINMETRO\b")
_MUNICIPAL_RIO = re.compile(
    r"MUNICIPIO D[EO] RIO DE JANEIRO|PREFEITURA\b.*RIO DE JANEIRO|CAMARA MUNICIPAL\b.*RIO DE JANEIRO")
_MUNICIPAL = re.compile(
    r"MUNICIPIO D[EO] |PREFEITURA (MUNICIPAL )?D[EO] |CAMARA MUNICIPAL|FUNDO MUNICIPAL|SECRETARIA MUNICIPAL|"
    r"\bMUNICIPAL\b|INTERMUNICIPAL")
_ESTADUAL = re.compile(
    r"\bESTADO\b|\bESTADUAL\b|GOVERNO DO ESTADO|SECRETARIA DE ESTADO|ASSEMBLEIA LEGISLATIVA|TRIBUNAL DE JUSTICA|"
    r"TRIBUNAL DE CONTAS|DEFENSORIA PUBLICA|MINISTERIO PUBLICO|\bDETRAN\b|POLICIA (MILITAR|CIVIL)|"
    r"CORPO DE BOMBEIROS|\bALERJ\b|\bUERJ\b")


def _resp(esfera: str, via: str, prova: str, *, poder: str = "", uf: str = "", natureza: str = "") -> dict:
    return {"esfera": esfera, "poder": poder, "uf": uf, "natureza": natureza, "via": via, "prova": prova,
            "no_rj": esfera in NO_RJ}


def poder_por_nome(nome: str, padrao: str = "") -> str:
    return next((p for rx, p in PODER_POR_NOME if rx.search(nome or "")), padrao)


def _poder(nome: str, natureza_poder: str, poder_pncp: str = "") -> str:
    p = poder_por_nome(nome)
    if p:
        return p
    if natureza_poder and natureza_poder != "Autônomo":
        return natureza_poder
    return {"E": "Executivo", "L": "Legislativo", "J": "Judiciário"}.get(poder_pncp or "", natureza_poder)


def _por_nome(nome: str, *, nivel_hint: str = "") -> dict:
    """Último recurso. Federal antes de estadual; estadual/municipal-Rio exigem marca do RJ."""
    n = _norm(nome)
    if not n:
        return _resp("indefinido", "sem_sinal", "sem CNPJ reconhecido e sem nome")
    if _FEDERAL.search(n):
        return _resp("federal", "nome", f"nome casa padrão federal: {nome!r}")
    m = _OUTRO_ESTADO.search(n)
    if m:
        return _resp("outro-estado", "nome", f"nome cita outro estado ({m.group(2)}): {nome!r}")
    if _MUNICIPAL_RIO.search(n):
        return _resp("municipal-rio", "nome", f"nome de entidade municipal do Rio de Janeiro: {nome!r}")
    if _MUNICIPAL.search(n) and nivel_hint != "E":
        if "INTERMUNICIPAL" in n or not _RJ_MARCA.search(n):
            return _resp("outro-municipio", "nome", f"entidade municipal sem ser a do Rio: {nome!r}")
    if (_ESTADUAL.search(n) or nivel_hint == "E") and _RJ_MARCA.search(n):
        return _resp("estadual-rj", "nome", f"nome estadual com marca do RJ: {nome!r}")
    if _MUNICIPAL.search(n):
        return _resp("outro-municipio", "nome", f"entidade municipal sem ser a do Rio: {nome!r}")
    return _resp("indefinido", "sem_sinal", f"nome sem sinal seguro de esfera (estadual exige marca do RJ): {nome!r}")


def _por_nivel(nivel: str, uf: str, municipio: str, fonte_uf: str, via: str, base: str,
               poder: str, natureza: str) -> dict | None:
    """Nível (F/E/M) + sede → esfera. None quando a sede não decide (cai para o nome)."""
    if nivel == "F":
        return _resp("federal", via, base, poder=poder, uf=uf, natureza=natureza)
    if not uf:
        return None
    sede = f"sede {uf}" + (f"/{municipio}" if municipio else "") + f" ({fonte_uf})"
    if nivel == "E":
        esf = "estadual-rj" if uf == UF_RJ else "outro-estado"
        return _resp(esf, via + "+uf", f"{base}; {sede}", poder=poder, uf=uf, natureza=natureza)
    if nivel == "M":
        if uf != UF_RJ:
            return _resp("outro-municipio", via + "+uf", f"{base}; {sede}", poder=poder, uf=uf, natureza=natureza)
        if not municipio:
            return None
        rio = municipio in (MUNICIPIO_RIO_RECEITA, MUNICIPIO_RIO_IBGE)
        return _resp("municipal-rio" if rio else "outro-municipio", via + "+municipio", f"{base}; {sede}",
                     poder=poder, uf=uf, natureza=natureza)
    return None


def _cnpj14(cnpj: str) -> str:
    """14 dígitos ou "" — CNPJ gravado como número perde zeros à esquerda (aceita ≥11 dígitos); lixo curto
    ("O1", "1") NÃO vira CNPJ: zfill de "1" dava a raiz 00000000 = BANCO DO BRASIL."""
    d = re.sub(r"\D", "", cnpj or "")
    return d.zfill(14) if 11 <= len(d) <= 14 else ""


def classificar(cnpj: str = "", nome: str = "", *, fatos: dict | None = None) -> dict:
    """Esfera do órgão. Retorna {esfera, poder, uf, natureza, via, prova, no_rj}.

    `fatos` (natureza, uf, municipio, fonte_uf, esfera_pncp, poder_pncp, razao_social) — injetável em
    teste; None = lidos da base (Receita + PNCP) por `fatos_do_cnpj`."""
    c14 = _cnpj14(cnpj)
    raiz = c14[:8]
    if raiz in RAIZES_RJ:
        esf = RAIZES_RJ[raiz]
        return _resp(esf, "raiz_cnpj", f"raiz {raiz} = {'ESTADO DO RIO DE JANEIRO' if esf == 'estadual-rj' else 'MUNICIPIO DE RIO DE JANEIRO'}",
                     poder=poder_por_nome(nome, "Executivo"), uf=UF_RJ)
    if raiz.startswith(RAIZ_UNIAO):
        return _resp("federal", "raiz_cnpj", f"raiz {raiz} = administração direta da União (00394…)",
                     poder="Executivo")
    f = fatos if fatos is not None else (fatos_do_cnpj(c14) if c14 else {})
    nome = nome or f.get("razao_social") or ""
    nat = str(f.get("natureza") or "").strip()
    uf = str(f.get("uf") or "").strip().upper()
    muni = str(f.get("municipio") or "").strip()
    fonte_uf = f.get("fonte_uf") or "Receita"
    esf_pncp = str(f.get("esfera_pncp") or "").strip().upper()
    poder_pncp = str(f.get("poder_pncp") or "").strip().upper()

    if nat in NATUREZA_PUBLICA:
        nivel, pnat = NATUREZA_PUBLICA[nat]
        poder = _poder(nome, pnat, poder_pncp)
        r = _por_nivel(nivel, uf, muni, fonte_uf, "natureza", f"natureza jurídica {nat} (Receita, nível {nivel})",
                       poder, nat)
        if r:
            return r
        r = _por_nome(nome, nivel_hint=nivel)
        r.update(poder=poder, natureza=nat, uf=uf,
                 prova=f"natureza {nat} (nível {nivel}) sem sede conhecida; {r['prova']}")
        return r

    if nat in NATUREZA_CONSORCIO:
        n = _norm(nome)
        if "MUNICIP" in n:
            return _resp("outro-municipio", "natureza", f"natureza {nat} consórcio público intermunicipal: {nome!r}",
                         uf=uf, natureza=nat, poder="Executivo")
        return _resp("indefinido", "natureza", f"natureza {nat} consórcio público sem ente identificado",
                     uf=uf, natureza=nat)

    # privado (natureza 3xxx-5xxx) antes de tudo: o PNCP dá "M"/"E" a SEBRAE-RJ e PUC-Rio; FIOTEC (apoio à
    # Fiocruz) é fundação privada — nada disso é órgão público, de esfera nenhuma
    if nat and nat[0] in "345":
        return _resp("indefinido", "natureza", f"natureza {nat} = entidade privada, não é órgão público",
                     uf=uf, natureza=nat)
    # estatal / sem natureza: nome federal decide antes do esferaId do PNCP (o PNCP marcou a INB como "E")
    n = _norm(nome)
    if _FEDERAL.search(n):
        return _resp("federal", "nome", f"nome casa padrão federal: {nome!r}" + (f" (natureza {nat})" if nat else ""),
                     uf=uf, natureza=nat)
    if nat in NATUREZA_ESTATAL or esf_pncp in ("E", "M"):
        nivel = ""
        if nat in NATUREZA_ESTATAL and re.search(r"\bESTADUAL\b|\bESTADO DO RIO\b|\bERJ\b", n):
            nivel, base = "E", f"estatal (natureza {nat}) com marca estadual no nome"
        elif nat in NATUREZA_ESTATAL and re.search(r"\bMUNICIPAL\b", n):
            nivel, base = "M", f"estatal (natureza {nat}) com marca municipal no nome"
        elif esf_pncp in ("E", "M"):
            nivel, base = esf_pncp, f"esferaId {esf_pncp} do PNCP" + (f" (natureza {nat})" if nat else "")
        if nivel:
            r = _por_nivel(nivel, uf, muni, fonte_uf, "pncp_esfera" if base.startswith("esferaId") else "natureza",
                           base, _poder(nome, "", poder_pncp), nat)
            if r:
                return r
    if esf_pncp == "F":
        return _resp("federal", "pncp_esfera", "esferaId F do PNCP" + (f" (natureza {nat})" if nat else ""),
                     uf=uf, natureza=nat)
    r = _por_nome(nome)
    r.update(uf=r["uf"] or uf, natureza=nat, poder=poder_por_nome(nome))
    return r


# ── Fatos da base (somente leitura) ──────────────────────────────────────────────────────────────────

def _ro(p: Path) -> sqlite3.Connection | None:
    if not p.exists():
        return None
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, check_same_thread=False)
    except sqlite3.Error:
        return None


@functools.lru_cache(maxsize=1)
def _cons() -> tuple:
    return _ro(DB_RECEITA), _ro(DB_COMPLIANCE)


def _um(con, sql: str, args: tuple):
    if con is None:
        return None
    try:
        return con.execute(sql, args).fetchone()
    except sqlite3.Error:
        return None


@functools.lru_cache(maxsize=20000)
def fatos_do_cnpj(cnpj14: str) -> dict:
    """Natureza, UF/município da sede e esfera do PNCP de um CNPJ — o que a base tiver. {} sem base."""
    rec, comp = _cons()
    b = cnpj14[:8]
    f: dict = {}
    r = _um(rec, "SELECT natureza_cod, razao_social FROM empresas WHERE cnpj_basico=?", (b,))
    if r:
        f["natureza"], f["razao_social"] = r[0], r[1]
    else:
        r = _um(comp, "SELECT natureza_cod, razao_social FROM empresas_cadastro WHERE cnpj_basico=?", (b,))
        if r:
            f["natureza"], f["razao_social"] = r[0], r[1]
    e = (_um(rec, "SELECT uf, municipio FROM estabelecimentos WHERE cnpj=?", (cnpj14,))
         or _um(rec, "SELECT uf, municipio FROM estabelecimentos WHERE cnpj_basico=? AND matriz_filial='1'", (b,)))
    if e and e[0]:
        f["uf"], f["municipio"], f["fonte_uf"] = e[0], e[1] or "", "Receita"
    p = _um(comp, "SELECT esfera_id, poder_id, natureza_juridica, nome FROM pncp_ente WHERE cnpj=?", (cnpj14,))
    if p:
        f["esfera_pncp"], f["poder_pncp"] = p[0] or "", p[1] or ""
        f.setdefault("natureza", p[2] or "")
        f.setdefault("razao_social", p[3] or "")
    if not f.get("uf"):
        u = _um(comp, "SELECT uf, municipio_ibge FROM orgao_uf_pncp WHERE cnpj=? AND uf<>''", (cnpj14,))
        if u:
            f["uf"], f["municipio"], f["fonte_uf"] = u[0], u[1] or "", "PNCP unidades"
    if not f.get("natureza"):
        f.pop("natureza", None)
    return f


@functools.lru_cache(maxsize=20000)
def _classificar_cache(c14: str, nome: str) -> dict:
    return classificar(c14, nome)


def esfera(cnpj: str = "", nome: str = "") -> str:
    """Atalho: só o rótulo de `ESFERAS`."""
    return dict(_classificar_cache(_cnpj14(cnpj), nome or ""))["esfera"]


def no_rj(cnpj: str = "", nome: str = "") -> bool:
    """O órgão é do escopo do JFN (Estado do RJ ou Prefeitura do Rio)?"""
    return esfera(cnpj, nome) in NO_RJ


# Marcador de unidade ESTADUAL (unidades do Estado no interior têm: SECRETARIA DE ESTADO, DETRAN, POLÍCIA…).
RX_UNIDADE_ESTADUAL = re.compile(
    r"\bESTAD|SECRETARIA DE ESTADO|GOVERNO DO ESTADO|FUNDO ESTADUAL|ASSEMBLEIA LEGISLATIVA|"
    r"TRIBUNAL DE JUSTI|DETRAN|POL[ÍI]CIA (MILITAR|CIVIL)|CORPO DE BOMBEIROS", re.I)


def classificar_unidade(cnpj: str, nome_ente: str = "", unidade_nome: str = "", municipio: str = "",
                        uf: str = "", esfera_pncp: str | None = None) -> dict:
    return dict(_classificar_unidade(cnpj or "", nome_ente or "", unidade_nome or "", municipio or "",
                                     uf or "", esfera_pncp or ""))


@functools.lru_cache(maxsize=50000)
def _classificar_unidade(cnpj: str, nome_ente: str, unidade_nome: str, municipio: str, uf: str,
                         esfera_pncp: str) -> dict:
    """Esfera de uma COMPRA (ente + unidade compradora do PNCP). O ente decide (`classificar`); a unidade
    só corrige o caso real do PNCP de unidade MUNICIPAL cadastrada sob o ente "Estado do RJ" (ex.:
    Instituto de Seguridade Social de Maricá). `uf`/`municipio` da unidade só servem de sede quando a
    Receita não tem a do ente; `esfera_pncp` (esferaId do ente) completa o que a base não tiver."""
    c14 = _cnpj14(cnpj)
    f = dict(fatos_do_cnpj(c14)) if c14 else {}
    if esfera_pncp and not f.get("esfera_pncp"):
        f["esfera_pncp"] = esfera_pncp
    mun = (municipio or "").strip()
    rio_unidade = _norm(mun) == "RIO DE JANEIRO" or mun in (MUNICIPIO_RIO_IBGE, MUNICIPIO_RIO_RECEITA)
    if not f.get("uf") and uf:
        f["uf"], f["fonte_uf"] = uf.upper(), "PNCP unidade da compra"
        f["municipio"] = MUNICIPIO_RIO_IBGE if rio_unidade else (mun and "outro")
    r = classificar(c14, nome_ente or "", fatos=f)
    # dado real do PNCP: 16 compras da Prefeitura do Rio (Hortas Cariocas, HM Lourenço Jorge) sob o CNPJ do
    # Fundo Municipal de Saúde de ITATIAIA, unidade "PREFEITURA MUNICIPAL DO RIO DE JANEIRO - RJ", município Rio.
    if (r["esfera"] in ("estadual-rj", "outro-municipio") and unidade_nome
            and _MUNICIPAL_RIO.search(_norm(unidade_nome)) and (rio_unidade or not mun)):
        return {**r, "esfera": "municipal-rio", "no_rj": True, "via": "unidade",
                "prova": f"unidade compradora é a Prefeitura do Rio no PNCP: {unidade_nome!r} ({mun or 'sem município'})"}
    if r["esfera"] == "estadual-rj" and unidade_nome:
        uni = unidade_nome
        if RX_MUNICIPAL.search(uni) and not RX_UNIDADE_ESTADUAL.search(uni):
            # município vazio ≠ Rio (bug 20/07/2026, Maricá): sem município, só com "RIO DE JANEIRO" na unidade
            rio = rio_unidade or (not mun and "RIO DE JANEIRO" in _norm(uni))
            esf = "municipal-rio" if rio else "outro-municipio"
            return {**r, "esfera": esf, "no_rj": esf in NO_RJ, "via": "unidade",
                    "prova": f"unidade municipal sob o ente estadual no PNCP: {uni!r} ({mun or 'sem município'})"}
        if mun and not rio_unidade and not RX_UNIDADE_ESTADUAL.search(uni):
            return {**r, "esfera": "outro-municipio", "no_rj": False, "via": "unidade",
                    "prova": f"unidade sem marcador estadual fora da capital ({mun}) sob o ente estadual: {uni!r}"}
    return r


def cnpj_do_controle_pncp(numero_controle: str) -> str:
    """Número de controle do PNCP ('<cnpj14>-1-<seq>/<ano>') → o CNPJ de 14 dígitos do órgão."""
    return re.sub(r"\D", "", (numero_controle or "").split("-")[0])[:14]


# ── Materialização + coleta da UF que falta (PNCP, dados abertos) ────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orgao_esfera (
    cnpj          TEXT PRIMARY KEY,
    nome          TEXT,
    esfera        TEXT NOT NULL,     -- estadual-rj | municipal-rio | federal | outro-estado | outro-municipio | indefinido
    poder         TEXT,
    uf            TEXT,
    natureza      TEXT,
    via           TEXT,              -- raiz_cnpj | natureza+uf | natureza+municipio | pncp_esfera+uf | nome | sem_sinal
    prova         TEXT,
    atualizado_em TEXT
);
CREATE INDEX IF NOT EXISTS ix_orgao_esfera_esfera ON orgao_esfera(esfera);
CREATE TABLE IF NOT EXISTS orgao_uf_pncp (
    cnpj           TEXT PRIMARY KEY,
    uf             TEXT,             -- '' quando as unidades estão em mais de uma UF (não decide)
    municipio_ibge TEXT,
    ufs            TEXT,             -- todas as UFs vistas, para conferência
    n_unidades     INTEGER,
    coletado_em    TEXT
);
"""

_FONTES_ORGAO = (("pcrj_licitacoes", "orgao_cnpj"), ("pcrj_contratos", "orgao_cnpj"),
                 ("pncp_resultado", "orgao_cnpj"), ("edital_documento", "orgao_cnpj"), ("pncp_ente", "cnpj"))


def universo(con) -> dict[str, str]:
    """CNPJ(14) → nome de todos os órgãos que a casa usa como comprador."""
    out: dict[str, str] = {}
    for t, col in _FONTES_ORGAO:
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
        if col not in cols:
            continue
        cn = "orgao_nome" if "orgao_nome" in cols else ("nome" if "nome" in cols else "NULL")
        for c, n in con.execute(f"SELECT {col}, MAX({cn}) FROM {t} WHERE {col} IS NOT NULL GROUP BY {col}"):
            k = re.sub(r"\D", "", c or "")
            if len(k) < 8:
                continue
            k = k.zfill(14)
            if not out.get(k):
                out[k] = n or ""
    return out


def coletar_uf_pncp(con, cnpjs, pausa: float = 0.6, timeout: int = 30) -> dict:
    """UF das unidades do órgão no PNCP (GET /orgaos/{cnpj}/unidades) para quem a Receita não deu sede.
    Uma requisição por CNPJ, com pausa; resultado em `orgao_uf_pncp` (cache: não re-coleta)."""
    import json
    import time
    import urllib.request
    con.executescript(_SCHEMA)
    ja = {r[0] for r in con.execute("SELECT cnpj FROM orgao_uf_pncp")}
    n_ok = n_err = 0
    for c in sorted(set(cnpjs) - ja):
        try:
            req = urllib.request.Request(f"https://pncp.gov.br/api/pncp/v1/orgaos/{c}/unidades",
                                         headers={"User-Agent": "JFN-Compliance/2.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — host fixo, dado aberto
                unis = json.loads(r.read().decode("utf-8") or "[]")
        except (OSError, ValueError):   # rede/HTTP/timeout ou JSON inválido
            n_err += 1
            time.sleep(pausa)
            continue
        ufs = sorted({((u.get("municipio") or {}).get("uf") or {}).get("siglaUF") or "" for u in unis} - {""})
        munis = sorted({str((u.get("municipio") or {}).get("codigoIbge") or "") for u in unis} - {""})
        con.execute("INSERT OR REPLACE INTO orgao_uf_pncp VALUES (?,?,?,?,?,datetime('now','localtime'))",
                    (c, ufs[0] if len(ufs) == 1 else "", munis[0] if len(munis) == 1 else "",
                     ",".join(ufs), len(unis)))
        con.commit()
        n_ok += 1
        time.sleep(pausa)
    fatos_do_cnpj.cache_clear()
    _classificar_cache.cache_clear()
    _classificar_unidade.cache_clear()
    return {"coletados": n_ok, "erros": n_err}


def materializar(db_path: Path | str = DB_COMPLIANCE, coletar: bool = True) -> dict:
    """(Re)grava `orgao_esfera` para todo o universo de órgãos. Com `coletar`, busca antes no PNCP a UF
    de quem não tem sede na Receita (natureza estadual/municipal ou estatal sem UF)."""
    con = sqlite3.connect(str(db_path), timeout=60)
    con.executescript(_SCHEMA)
    uni = universo(con)
    if coletar:
        falta = [c for c in uni if c[:8] not in RAIZES_RJ and not c.startswith(RAIZ_UNIAO)
                 and not fatos_do_cnpj(c).get("uf")]
        coletar_uf_pncp(con, falta)
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linhas = []
    cont: dict[str, int] = {}
    for c, n in uni.items():
        r = classificar(c, n)
        cont[r["esfera"]] = cont.get(r["esfera"], 0) + 1
        linhas.append((c, n, r["esfera"], r["poder"], r["uf"], r["natureza"], r["via"], r["prova"], agora))
    with con:
        con.execute("DELETE FROM orgao_esfera")
        con.executemany("INSERT INTO orgao_esfera VALUES (?,?,?,?,?,?,?,?,?)", linhas)
    con.close()
    return {"orgaos": len(uni), "por_esfera": cont}


if __name__ == "__main__":
    import argparse
    import json as _json
    ap = argparse.ArgumentParser(description="Fonte única de esfera do órgão (escopo RJ do JFN)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("materializar", help="regrava compliance.db.orgao_esfera")
    m.add_argument("--sem-coleta", action="store_true", help="não consulta o PNCP para UF que falta")
    c = sub.add_parser("conferir", help="classifica um CNPJ e mostra a prova")
    c.add_argument("cnpj")
    c.add_argument("nome", nargs="?", default="")
    a = ap.parse_args()
    if a.cmd == "materializar":
        print(_json.dumps(materializar(coletar=not a.sem_coleta), ensure_ascii=False, indent=2))
    else:
        print(_json.dumps(classificar(a.cnpj, a.nome), ensure_ascii=False, indent=2))
