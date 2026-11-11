# -*- coding: utf-8 -*-
"""Dicionário territorial: do TEXTO (objeto, extrato, nome de unidade) ao município / ao bairro.

É o método mais FRACO da atribuição (`texto`), e por isso é o mais cercado. Toda regra aqui nasceu
de uma armadilha concreta — as do brief e as que apareceram ao ler os objetos reais:

  · "Rio de Janeiro" sozinho NÃO é a capital: é quase sempre "Estado do Rio de Janeiro". Só contam
    "Município/Cidade do Rio de Janeiro", "na capital" e bairro carioca reconhecido.
  · Nome de município que também é coisa, gente ou rua só vale com LOCATIVO ("em Vassouras",
    "município de Mendes", "Resende/RJ"): "aquisição de vassouras", "centro de tratamento de
    queimados", "Rua Barão de Mesquita", "Colégio Estadual Casimiro de Abreu" não são território.
  · O casamento é do MAIS LONGO para o mais curto, com máscara: "Rio das Ostras", "Rio Bonito" e
    "Rio Claro" nunca viram Rio de Janeiro; "Barra do Piraí" nunca vira Piraí; "São João da Barra"
    e "São João de Meriti" não se confundem.
  · Região ("Região Serrana", "Baixada Fluminense") NÃO é município: é devolvida à parte e ninguém
    espalha valor por ela.

Nada aqui acessa banco. Entrada = texto; saída = achados com a evidência (o trecho que casou).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from compliance_agent.territorio.geo import RIO, bairros, municipios, norm

# ── municípios ────────────────────────────────────────────────────────────────────────────────
# apelidos LIVRES (valem sozinhos) — sempre no texto já normalizado
_APELIDOS = {
    "ARMACAO DOS BUZIOS": ["BUZIOS", "ARMACAO DE BUZIOS"],
    "PARATY": ["PARATI"],
    "TRAJANO DE MORAES": ["TRAJANO DE MORAIS"],
    "CAMPOS DOS GOYTACAZES": ["CAMPOS DOS GOITACAZES", "CAMPOS DOS GOYTACAZES"],
    "DUQUE DE CAXIAS": ["CAXIAS"],
    "SAO JOAO DE MERITI": ["SAO JOAO DO MERITI", "S J DE MERITI", "S JOAO DE MERITI"],
    "COMENDADOR LEVY GASPARIAN": ["LEVY GASPARIAN"],
    "ENGENHEIRO PAULO DE FRONTIN": ["ENG PAULO DE FRONTIN"],
    "BOM JESUS DO ITABAPOANA": ["BOM JESUS DE ITABAPOANA"],
    "SAO FRANCISCO DE ITABAPOANA": ["SAO FRANCISCO DO ITABAPOANA"],
    "SAO PEDRO DA ALDEIA": ["SAO P DA ALDEIA", "S PEDRO DA ALDEIA", "SAO PEDRO D ALDEIA"],
    "ANGRA DOS REIS": ["AGRA DOS REIS"],          # erro de digitação recorrente no nome de unidade do PNCP
    "SANTO ANTONIO DE PADUA": ["STO ANTONIO DE PADUA"],
    "TERESOPOLIS": ["THERESOPOLIS"],
    "RIO DAS OSTRAS": ["OSTRASPREV"],
    "CACHOEIRAS DE MACACU": ["CACHOEIRA DE MACACU"],
}
# apelidos que só valem com LOCATIVO
_APELIDOS_LOC = {
    "CAMPOS DOS GOYTACAZES": ["CAMPOS"],
    "SANTO ANTONIO DE PADUA": ["PADUA"],
    "ENGENHEIRO PAULO DE FRONTIN": ["PAULO DE FRONTIN"],
}
# nomes oficiais que também são coisa, sobrenome, pessoa ou logradouro → só com locativo
_SO_LOCATIVO = {
    "VASSOURAS", "QUEIMADOS", "MENDES", "MESQUITA", "RESENDE", "CORDEIRO", "CARMO", "AREAL", "SUMIDOURO",
    "CANTAGALO", "NATIVIDADE", "ITATIAIA", "SAPUCAIA", "MACUCO", "VALENCA", "CASIMIRO DE ABREU", "SILVA JARDIM",
    "MIGUEL PEREIRA", "CARDOSO MOREIRA", "BOM JARDIM", "DUAS BARRAS", "PORTO REAL", "RIO CLARO", "PINHEIRAL",
    "PIRAI", "ITALVA", "QUATIS", "TANGUA", "MAGE", "JAPERI", "PARAIBA DO SUL", "TRES RIOS", "SAO FIDELIS",
    "SANTA MARIA MADALENA", "TRAJANO DE MORAES", "TRAJANO DE MORAIS", "ENGENHEIRO PAULO DE FRONTIN",
    "ENG PAULO DE FRONTIN", "COMENDADOR LEVY GASPARIAN", "LEVY GASPARIAN", "RIO BONITO", "RIO DAS FLORES",
}
# o que pode vir ANTES do nome para ele ser lugar
_LOC_ANTES = (r"(?:EM|NO MUNICIPIO DE|NOS MUNICIPIOS DE|MUNICIPIO DE|MUNICIPIOS DE|MUNICIPIO|CIDADE DE|COMARCA DE|"
              r"LOCALIZAD[OA]S? EM|SITUAD[OA]S? EM|SEDIAD[OA]S? EM|REGIONAL DE|REGIONAL|NUCLEO DE|POLO DE|"
              r"CAMPUS DE|CAMPUS|UNIDADE DE|FORUM DE|PREFEITURA DE|PREFEITURA MUNICIPAL DE|PREF MUN DE)")
# o que pode vir DEPOIS ("Resende/RJ", "Mendes - RJ" → já normalizado para "RESENDE RJ")
_LOC_DEPOIS = r"(?:RJ)\b"
# patronímico/logradouro colado ANTES do nome → é homenagem, não lugar ("Rua Barão de Mesquita")
_HOMENAGEM = (r"(?:RUA|AVENIDA|AV|RODOVIA|ROD|ESTRADA|PRACA|TRAVESSA|ALAMEDA|VIADUTO|TUNEL|PONTE|LARGO|"
              r"COLEGIO ESTADUAL|COLEGIO|ESCOLA ESTADUAL|ESCOLA MUNICIPAL|ESCOLA TECNICA ESTADUAL|ESCOLA|"
              r"C E|E E|E M|CIEP(?: \d+)?|BRIZOLAO(?: \d+)?|CRECHE|BIBLIOTECA|TEATRO|PALACIO|EDIFICIO|PREDIO|"
              r"BARAO DE|VISCONDE DE|MARQUES DE|CONDE DE|DR|DOUTOR|PROFESSOR|PROFESSORA|PROF|GOVERNADOR|"
              r"PRESIDENTE|DEPUTADO|VEREADOR|SENADOR|MINISTRO|MARECHAL|GENERAL|CORONEL|CEL|CAPITAO|TENENTE|"
              r"SARGENTO|PADRE|DOM|BATALHAO|FUNDACAO OSWALDO)")
# frases que CONTÊM nome de município e não são o município
_MASCARAS = [
    r"ESTADO DO RIO DE JANEIRO", r"GOVERNO DO RIO DE JANEIRO", r"EST(?:ADO)? DO RJ", r"RIO DE JANEIRO RJ",
    r"RIO PARAIBA DO SUL", r"BACIA DO (?:RIO )?PARAIBA DO SUL", r"VALE DO PARAIBA(?: DO SUL)?", r"MEDIO PARAIBA",
    r"CENTRO DE TRATAMENTO DE QUEIMADOS", r"TRATAMENTO DE QUEIMADOS", r"PACIENTES? QUEIMADOS", r"GRANDES QUEIMADOS",
    r"PARQUE NACIONAL D[EO] ITATIAIA", r"DUQUE DE CAXIAS (?:FUTEBOL|F C)", r"CAPITAL SOCIAL", r"CAPITAL DE GIRO",
    r"BENS DE CAPITAL", r"DESPESAS? DE CAPITAL",
]
_REGIOES = {
    "REGIAO SERRANA": "Região Serrana", "BAIXADA FLUMINENSE": "Baixada Fluminense",
    "BAIXADAS? LITORANEAS?": "Baixadas Litorâneas", "REGIAO DOS LAGOS": "Região dos Lagos",
    "NORTE FLUMINENSE": "Norte Fluminense", "NOROESTE FLUMINENSE": "Noroeste Fluminense",
    "SUL FLUMINENSE": "Sul Fluminense", "CENTRO SUL FLUMINENSE": "Centro-Sul Fluminense",
    "MEDIO PARAIBA": "Médio Paraíba", "COSTA VERDE": "Costa Verde",
    "REGIAO METROPOLITANA": "Região Metropolitana", "LESTE FLUMINENSE": "Leste Fluminense",
}
_CAPITAL = [r"MUNICIPIO DO RIO DE JANEIRO", r"CIDADE DO RIO DE JANEIRO", r"(?:NA|DA) CAPITAL", r"CAPITAL FLUMINENSE",
            r"CAPITAL DO ESTADO", r"RIO DE JANEIRO CAPITAL"]

# ── bairros cariocas ─────────────────────────────────────────────────────────────────────────
# nunca valem por texto: palavra comum, sobrenome, clube ou instituição
_BAIRRO_NUNCA = {"CENTRO", "SAUDE", "COLEGIO", "ROCHA", "SAMPAIO", "CAVALCANTI", "PORTUGUESA", "ZUMBI", "JACARE",
                 "TANQUE", "VASCO DA GAMA", "OSWALDO CRUZ", "GLORIA", "LAPA", "FLAMENGO", "BOTAFOGO", "CIDADE NOVA",
                 "ESTACIO", "CAJU", "RIBEIRA", "COSMOS", "ANIL", "LAGOA", "LEME", "MARE", "RAMOS", "OLARIA",
                 "PIEDADE", "ABOLICAO", "PACIENCIA", "FREGUESIA", "FREGUESIA JACAREPAGUA", "FREGUESIA ILHA",
                 "MONERO", "JOA", "ALTO DA BOA VISTA", "PRAIA DA BANDEIRA", "BANCARIOS", "GERICINO", "GALEAO",
                 "CIDADE UNIVERSITARIA", "JARDIM AMERICA", "VISTA ALEGRE", "HIGIENOPOLIS", "MANGUEIRA",
                 "LARANJEIRAS", "SANTA TERESA", "COELHO NETO", "GUADALUPE", "ANCHIETA", "PENHA", "RIACHUELO",
                 "BENFICA", "VARGEM GRANDE", "PITANGUEIRAS", "PARQUE COLUMBIA", "JARDIM CARIOCA", "TODOS OS SANTOS"}
# valem com locativo ("bairro de …", "em …", "no …")
_BAIRRO_LOC = {"SANTA CRUZ", "CAMPO GRANDE", "PENHA", "LARANJEIRAS", "SANTA TERESA", "BENFICA", "COELHO NETO",
               "GUADALUPE", "ANCHIETA", "RIACHUELO", "MANGUEIRA", "FLAMENGO", "BOTAFOGO", "GLORIA", "LAPA",
               "ESTACIO", "CAJU", "MARE", "RAMOS", "OLARIA", "PIEDADE", "PACIENCIA", "COSMOS", "FREGUESIA",
               "CIDADE NOVA", "GALEAO", "VARGEM GRANDE", "JARDIM AMERICA", "VISTA ALEGRE", "CIDADE UNIVERSITARIA",
               "ALTO DA BOA VISTA", "TODOS OS SANTOS", "LEME", "LAGOA"}
_BAIRRO_ANTES = r"(?:BAIRRO DE|BAIRRO DA|BAIRRO DO|BAIRRO|NO|NA|EM|\d{2,5})"      # o número é o do logradouro: "…, 6851 - Campo Grande"
# no escopo ESTADO o bairro só vale ANCORADO em lugar/unidade: "UPA de Jacarepaguá", "campus Maracanã".
# Sem âncora ele pode ser título de obra — a auditoria achou "espetáculo Copacabana (Tu) Não Me Engana".
_BAIRRO_ANCORA = (r"(?:UPA|HOSPITAL|CAMPUS|UNIDADE|BAIRRO|QUARTEL|DELEGACIA|ESCOLA|COLEGIO|TERMINAL|ESTACAO|PRESIDIO|"
                  r"EM|NO|NA|DE|DO|DA)(?: D[EOA])?")
# não são bairro oficial, mas são território inequívoco da capital (nome → AP)
_BAIRRO_EXTRA = {"ILHA DO GOVERNADOR": 3, "ILHA DE PAQUETA": 1, "ZONA PORTUARIA": 1, "PORTO MARAVILHA": 1,
                 "SAMBODROMO": 1, "ESTADIO DO MARACANA": 2, "JACAREPAGUA": 4, "BARRA DA TIJUCA": 4,
                 "RECREIO": 4, "ILHA DO FUNDAO": 3, "TELEFERICO DO ALEMAO": 3, "BONDES DE SANTA TERESA": 1,
                 "REGIAO DO PORTO": 1, "REGIAO PORTUARIA": 1}


@dataclass
class Achado:
    cod_ibge: str
    nome: str
    evidencia: str           # o trecho normalizado que casou


@dataclass
class Leitura:
    municipios: list[Achado] = field(default_factory=list)
    regiao: str | None = None
    capital_por: str | None = None      # 'expressao' | 'bairro' quando o Rio veio de pista indireta


@lru_cache(maxsize=1)
def _padroes():
    """[(regex, cod_ibge, nome, livre?)] do mais longo para o mais curto."""
    itens = []
    for m in municipios():
        if m["cod_ibge"] == RIO:
            continue                      # a capital tem regra própria
        oficial = norm(m["nome"])
        nomes = {oficial: oficial not in _SO_LOCATIVO}
        for ap in _APELIDOS.get(oficial, []):
            nomes[ap] = ap not in _SO_LOCATIVO
        for ap in _APELIDOS_LOC.get(oficial, []):
            nomes[ap] = False
        for n, livre in nomes.items():
            itens.append((n, m["cod_ibge"], m["nome"], livre))
    itens.sort(key=lambda x: -len(x[0]))
    return [(re.compile(rf"\b{re.escape(n)}\b"), n, cod, nome, livre) for n, cod, nome, livre in itens]


_RE_MASC = re.compile("|".join(rf"\b{p}\b" for p in _MASCARAS))
_RE_REG = [(re.compile(rf"\b{p}\b"), r) for p, r in _REGIOES.items()]
_RE_CAP = re.compile("|".join(rf"\b{p}\b" for p in _CAPITAL))


def _mascarar(t: str, a: int, b: int) -> str:
    return t[:a] + "#" * (b - a) + t[b:]


def ler_municipios(texto: str | None) -> Leitura:
    """Municípios do RJ citados como LUGAR no texto. Não decide nada: só lista, com a evidência."""
    t = norm(texto)
    out = Leitura()
    if not t:
        return out
    for rg, rot in _RE_REG:
        if rg.search(t):
            out.regiao = rot
            break
    capital = _RE_CAP.search(t)
    if capital:
        out.municipios.append(Achado(RIO, "Rio de Janeiro", capital.group(0)))
        out.capital_por = "expressao"
        t = _mascarar(t, capital.start(), capital.end())
    t = _RE_MASC.sub(lambda m: "#" * len(m.group(0)), t)
    # 1ª passada: todos os casamentos, do mais longo ao mais curto (o trecho casado sai do jogo)
    original, cands = t, []
    for rg, n, cod, nome, livre in _padroes():
        pos = 0
        while True:
            m = rg.search(t, pos)
            if not m:
                break
            a, b = m.span()
            antes = original[max(0, a - 60):a]
            cands.append((a, b, cod, nome, livre,
                          bool(re.search(rf"\b{_HOMENAGEM} $", antes)),
                          bool(re.search(rf"\b{_LOC_ANTES} $", antes) or re.match(rf" {_LOC_DEPOIS}", original[b:b + 4]))))
            t = _mascarar(t, a, b)
            pos = b
    # 2ª passada, na ordem do texto: nome ambíguo também vale como ITEM DE LISTA de lugares
    # ("em Rio das Ostras, Rio Bonito e Macaé" — o locativo do primeiro vale para os seguintes)
    vistos = {RIO} if capital else set()
    fim_valido = None
    for a, b, cod, nome, livre, homenagem, locativo in sorted(cands):
        em_lista = fim_valido is not None and original[fim_valido:a] in (" ", " E ")
        if not homenagem and (livre or locativo or em_lista):
            fim_valido = b
            if cod not in vistos:
                vistos.add(cod)
                out.municipios.append(Achado(cod, nome, original[max(0, a - 24):b + 3].strip()))
        else:
            fim_valido = None
    if not out.municipios:
        d = ler_distritos(original)
        if d:
            out.municipios.append(Achado(d[0], d[1], d[2]))
    if not out.municipios:
        bs = ler_bairros(texto, estrito=True)
        if bs:
            out.municipios.append(Achado(RIO, "Rio de Janeiro", "bairro carioca: " + bs[0]["bairro"]))
            out.capital_por = "bairro"
    return out


# ── distritos (IBGE) ───────────────────────────────────────────────────────────────────────────
# Distrito de nome inconfundível vale sozinho; os demais (muitos são palavra comum, santo ou sobrenome:
# "Posse", "Santa Maria", "Werneck") só com âncora forte — "distrito de …", "localidade de …", "em …".
_DISTRITO_LIVRE = {
    "ITAIPAVA", "XEREM", "CONSERVATORIA", "BARRA DE SAO JOAO", "LUMIAR", "VISCONDE DE MAUA", "ITAIPUACU", "BACAXA", "TAMOIOS",
    "MAMBUCABA", "MURIQUI", "ITACURUSSA", "IMBARIE", "INOA", "ATAFONA", "GRUSSAI", "PEDRO DO RIO", "CASCATINHA", "CAMPOS ELYSEOS",
    "SANTO ALEIXO", "INHOMIRIM", "SURUI", "GUIA DE PACOBAIBA", "ARROZAL", "ENGENHEIRO PASSOS", "LIDICE", "PARATY MIRIM", "TARITUBA",
    "CONCEICAO DE JACAREI", "PRAIA SECA", "IGUABINHA", "CACHOEIROS DE MACAE", "GLICERIO", "MONNERAT", "RIOGRANDINA",
    "CAMPO DO COELHO", "VILA DA GRAMA", "PURILANDIA", "EUCLIDELANDIA", "GETULANDIA", "DORANDIA", "IPIABAS",
    "SACRA FAMILIA DO TINGUA", "MORRO AZUL DO TINGUA", "SAO PEDRO DA SERRA", "SODRELANDIA", "MORRO DO COCO",
    "SANTO AMARO DE CAMPOS", "SANTO EDUARDO", "PORTO DAS CAIXAS", "ITAMBI", "SAMBAETIBA", "VALE DO PAQUEQUER", "CUNHAMBEBE",
    "COELHO DA ROCHA", "SAO JOSE DO RIBEIRAO", "SANTA ISABEL DO RIO PRETO", "BOM JESUS DO QUERENDO", "RETIRO DO MURIAE",
}
_DISTRITO_ANCORA = r"(?:DISTRITO DE|DISTRITO|LOCALIDADE DE|LOCALIDADE|EM)"


@lru_cache(maxsize=1)
def _padroes_distrito():
    import csv
    from pathlib import Path
    with open(Path(__file__).resolve().parent / "dados" / "distritos_rj.csv", encoding="utf-8") as f:
        linhas = sorted(csv.DictReader(f), key=lambda r: -len(r["nome_norm"]))
    return [(re.compile(rf"\b{re.escape(r['nome_norm'])}\b"), r["nome_norm"], r["cod_ibge"], r["municipio"], r["distrito"]) for r in linhas]


def ler_distritos(texto_norm: str) -> tuple[str, str, str] | None:
    """(cod_ibge, município, evidência) do 1º distrito citado como lugar — texto JÁ normalizado."""
    for rg, n, cod, mun, dist in _padroes_distrito():
        m = rg.search(texto_norm)
        if not m:
            continue
        antes = texto_norm[max(0, m.start() - 40):m.start()]
        if re.search(rf"\b{_HOMENAGEM} $", antes):
            continue
        if n in _DISTRITO_LIVRE or re.search(rf"\b{_DISTRITO_ANCORA} $", antes):
            return cod, mun, f"distrito de {dist} ({mun})"
    return None


@lru_cache(maxsize=1)
def _padroes_bairro():
    itens = []
    for b in bairros():
        n = norm(b["bairro"])
        if n and n not in _BAIRRO_NUNCA or n in _BAIRRO_LOC:
            itens.append((n, b["bairro"], b["ra"], int(b["ap"]), n not in _BAIRRO_LOC and n not in _BAIRRO_NUNCA))
    for n, ap in _BAIRRO_EXTRA.items():
        if not any(i[0] == n for i in itens):
            itens.append((n, n.title(), None, ap, True))
    itens.sort(key=lambda x: -len(x[0]))
    return [(re.compile(rf"\b{re.escape(n)}\b"), n, nome, ra, ap, livre) for n, nome, ra, ap, livre in itens]


def ler_bairros(texto: str | None, estrito: bool = False) -> list[dict]:
    """Bairros cariocas citados. `estrito` (uso no escopo Estado): só nome de 2+ palavras ou 8+ letras,
    porque fora do contexto "Prefeitura do Rio" um nome curto pode ser bairro de outra cidade."""
    t = norm(texto)
    out, vistos = [], set()
    if not t:
        return out
    t = _RE_MASC.sub(lambda m: "#" * len(m.group(0)), t)
    for rg, n, nome, ra, ap, livre in _padroes_bairro():
        pos = 0
        while True:
            m = rg.search(t, pos)
            if not m:
                break
            a, b = m.span()
            antes = t[max(0, a - 40):a]
            homenagem = re.search(rf"\b{_HOMENAGEM} $", antes)
            locativo = re.search(rf"\b{_BAIRRO_ANTES} $", antes)
            vale = (not homenagem) and (livre or locativo)
            if estrito and vale and not locativo and not (" " in n or len(n) >= 8):
                vale = False
            if estrito and vale and not re.search(rf"\b{_BAIRRO_ANCORA} $", antes):
                vale = False
            if vale and n not in vistos:
                vistos.add(n)
                out.append({"bairro": nome, "ra": ra, "ap": ap, "evidencia": t[max(0, a - 20):b].strip()})
            t = _mascarar(t, a, b)
            pos = b
    return out
