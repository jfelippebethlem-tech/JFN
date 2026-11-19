"""carona_aderente_vedado — órgão do Estado do RJ aderiu (carona) a ata cujo próprio instrumento não o admite.

Origem: SEI-420001/003312/2024 (CDEL × SEGOV) — edital FDE-SP 36/00456/23/05, item 15.1: a ata "poderá ser utilizada
… por órgãos ou entidades da Administração Pública do Estado de São Paulo e de Municípios paulistas"; a SEGOV aderiu.
Também SEI-150002/000471/2025 e 150002/001417/2025 (Casa Civil × CIM Jequitinhonha/MG, foro Diamantina).

Sinais (cada um com trecho literal do processo):
  V1 restricao_ente   — cláusula de adesão que nomeia como aderentes só entes de OUTRA unidade federativa
                        (ou só a Administração federal). Vinculação ao instrumento convocatório.
  V2 vedacao_carona   — o instrumento veda a adesão por não participantes.
  V3 gerenciador_municipal — ata gerenciada por município ou consórcio municipal. Lei 14.133 art. 86 §3º (red. Lei
                        14.770/2023): órgão ESTADUAL só adere a ata de gerenciador federal, estadual ou distrital;
                        ata municipal só serve a aderente municipal (inciso II). Sob a Lei 8.666 o regime é o do
                        decreto do ente (RJ: Dec. 46.751/2019) — fica médio.
Só conta processo com prova de ADESÃO DESTE ÓRGÃO (NE "Adesão ao Registro de Preços Externo" ou ato de adesão).
"""
from __future__ import annotations

import re

from compliance_agent.padroes import _carona_comum as cc

ID = "carona_aderente_vedado"
VICIO = "carona_abusiva"  # knowledge/catalogo_vicios.py

RX_EXTERNO = re.compile(r"ades[ãa]o\s+ao\s+registro\s+de\s+pre[çc]os\s+externo", re.I)
RX_INTERNO = re.compile(r"ades[ãa]o\s+ao\s+registro\s+de\s+pre[çc]os\s+interno", re.I)
# ato de adesão praticado por este órgão (não cláusula genérica de edital): pedido/autorização/termo de adesão
RX_ATO_ADESAO = re.compile(
    r"(?:solicit\w+|autoriz\w+|requer\w*|pedido\s+de|termo\s+de|of[íi]cio\s+de|anu[êe]ncia\s+(?:para|à|a)\s+(?:a\s+)?)"
    r"[^.;]{0,60}?ades[ãa]o\s+(?:à|a|ao)\s+(?:ata|arp|sistema\s+de\s+registro|registro\s+de\s+pre)"
    r"|ades[ãa]o\s+(?:à|a)\s+(?:ata|arp)[^.;]{0,120}?(?:gerenciad[ao]|d[oa]\s+(?:IF|Instituto|Funda|Cons[óo]rcio|Prefeitura|Munic|Minist|Secretaria|Universidade))",
    re.I)

_UF_NOMES = {
    "AC": "acre", "AL": "alagoas", "AP": "amapa", "AM": "amazonas", "BA": "bahia", "CE": "ceara",
    "DF": "distrito federal", "ES": "espirito santo", "GO": "goias", "MA": "maranhao", "MT": "mato grosso",
    "MS": "mato grosso do sul", "MG": "minas gerais", "PA": "para", "PB": "paraiba", "PR": "parana",
    "PE": "pernambuco", "PI": "piaui", "RN": "rio grande do norte", "RS": "rio grande do sul", "RO": "rondonia",
    "RR": "roraima", "SC": "santa catarina", "SP": "sao paulo", "SE": "sergipe", "TO": "tocantins"}
_GENTILICOS = ("paulista", "mineir", "baian", "goian", "capixaba", "paranaense", "gaucho", "catarinense",
               "pernambucan", "cearense", "paraense", "amazonense", "maranhense", "piauiense", "potiguar",
               "paraiban", "alagoan", "sergipan", "tocantinense", "rondoniense", "roraimense", "amapaense",
               "acrean", "mato-grossense", "matogrossense", "sul-mato-grossense", "brasiliense")

# cláusula de "limites subjetivos" da adesão: quem PODE aderir
RX_CLAUSULA = re.compile(
    r"(?:poder[áa]\s+ser\s+utilizad[ao]|poder[ãa]o\s+(?:aderir|utiliz\w+)|ades[ãa]o\s+[àa]\s+(?:presente\s+)?ata"
    r"|facultad[ao]\s+a\s+ades[ãa]o|limites\s+subjetivos)[^;]{0,420}", re.I)
_PERMISSIVO = re.compile(r"qualquer|federal,?\s+estadu|estaduais|estadual|demais\s+entes|outros\s+entes|"
                         r"rio\s+de\s+janeiro|fluminense|todos\s+os\s+entes|esferas", re.I)
_NAO_PARTICIPANTE = re.compile(r"n[ãa]o\s+(?:tenham\s+)?particip|n[ãa]o[\s-]participante|ades[ãa]o|aderir", re.I)

RX_VEDA = re.compile(
    r"(?:[ée]\s+vedad[ao]|fica(?:m)?\s+vedad[ao]s?|n[ãa]o\s+ser[áa]\s+(?:admitid|permitid|autorizad)[ao]|"
    r"n[ãa]o\s+se\s+admitir[áa]|fica\s+proibid[ao]|n[ãa]o\s+caber[áa])\s+(?:a\s+)?"
    r"(?:ades[ãa]o|carona|utiliza[çc][ãa]o\s+da\s+(?:presente\s+)?ata\s+(?:de\s+registro\s+de\s+pre[çc]os\s+)?por\s+"
    r"(?:[óo]rg[ãa]os?|entidades?)[^.;]{0,30}n[ãa]o[\s-]participantes?)[^.;]{0,160}", re.I)
# vedação CONDICIONAL ou de outro sujeito (art. 86 §8º: órgãos federais; limites; prazo) não é vedação de carona
_VEDA_CONDICIONAL = re.compile(r"federa|§\s*8|limite|quantitativ|exced|superior|al[ée]m\s+d|ap[óo]s|vencid|"
                               r"expirad|sem\s+(?:a\s+)?(?:pr[ée]via|anu[êe]ncia|consulta|justific)|"
                               r"\bcuj[ao]s?\b|que\s+n[ãa]o\s+tenha|itens?\s+(?:n[ãa]o\s+)?registrad|"
                               r"de\s+atas?\s+(?:de|gerenciad)|registro\s+de\s+pre[çc]os\s+(?:de|d[oa])\s|"
                               r"munic[íi]pio|distrit|estadua", re.I)

RX_GERENCIADOR = re.compile(
    r"Ata\s+de\s+Registro\s+de\s+Pre[çc]os\s*(?:(?:n[º°o.]*|n[úu]mero)\s*[\d./\-]+\s*,?\s*)?(?:\([^)]{0,40}\)\s*)?,?\s*"
    r"(?:d[oa]|gerenciad[ao]\s+pel[oa]|realizad[ao]\s+pel[oa])\s+"
    r"(Cons[óo]rcio[^.;:]{3,200}|Prefeitura\s+(?:Municipal\s+)?d[eo]\s+[^.;:]{3,80}|Munic[íi]pio\s+d[eo]\s+[^.;:]{3,80})",
    re.I)
RX_UF = re.compile(r"(?:[/\-–(]\s*|\bEstado\s+de\s+|\b-\s*)(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RN|RS|RO|RR|SC|SP|SE|TO)\b")
RX_FORO = re.compile(r"[Ff]oro\s+da\s+(?:Comarca|Cidade)\s+de\s+([A-ZÀ-Ú][\wÀ-ú ]{2,40}?)\s*[/\-–]\s*([A-Z]{2})\b")


def _ente_restrito(clausula: str) -> str | None:
    """Ente(s) a que a cláusula RESTRINGE a adesão, se não for o RJ nem permissiva. None = permissiva/indefinida."""
    c = cc.sem_acento(clausula).lower()
    if not _NAO_PARTICIPANTE.search(c):
        return None
    alvo = c.split("que nao")[0] if "que nao" in c else c   # "…por órgãos X que não tenham participado"
    if _PERMISSIVO.search(alvo):
        return None
    for uf, nome in _UF_NOMES.items():
        if re.search(rf"estado\s+d[eoa]\s+{nome}\b", alvo):
            return f"Estado de {nome.title()} ({uf})"
    for g in _GENTILICOS:
        if re.search(rf"municipios?\s+{g}", alvo):
            return f"municípios {g}*"
    if re.search(r"administracao\s+publica\s+federal", alvo) and not re.search(r"estad|municip|distrit", alvo):
        return "somente a Administração Pública federal"
    return None


def avaliar(tag: str, ds: list[cc.Doc]) -> dict | None:
    """Avalia UM processo. Devolve None se não há prova de adesão deste órgão (fora do universo);
    {"adesao": ..., "sinais": [...]} caso contrário."""
    externo = interno = ato = None
    for d in ds:
        externo = externo or ((d, RX_EXTERNO.search(d.texto)) if RX_EXTERNO.search(d.texto) else None)
        interno = interno or ((d, RX_INTERNO.search(d.texto)) if RX_INTERNO.search(d.texto) else None)
        if not ato:
            m = RX_ATO_ADESAO.search(d.texto)
            ato = (d, m) if m else None
    if not (externo or ato):
        return {"adesao": "interna" if interno else None, "sinais": []}
    reg = cc.regime(ds)
    # foro fora do RJ: dá a UF de consórcio sem UF no nome e AGRAVA um sinal já existente (não é vício sozinho)
    foro = foro_uf = None
    for d in ds:
        m = RX_FORO.search(d.texto)
        if m and m.group(2) != "RJ":
            foro, foro_uf = f'{d.ref} — "{cc.trecho(d.texto, m.start(), m.end(), 30)[:200]}"', m.group(2)
            break
    sinais: list[dict] = []
    for d in ds:
        for m in RX_CLAUSULA.finditer(d.texto):
            ente = _ente_restrito(m.group(0))
            if ente:
                grau = "medio" if ente.startswith("somente") else "forte"
                sinais.append({"sinal": "restricao_ente", "grau": grau, "ente": ente,
                               "prova": f'{d.ref} ({d.titulo[:70]}) — "{cc.trecho(d.texto, m.start(), m.end(), 60)[:420]}"'})
                break
        for m in RX_VEDA.finditer(d.texto):
            if _VEDA_CONDICIONAL.search(m.group(0)):
                continue
            sinais.append({"sinal": "vedacao_carona", "grau": "medio",
                           "prova": f'{d.ref} ({d.titulo[:70]}) — "{cc.trecho(d.texto, m.start(), m.end(), 80)[:420]}"'})
            break
        for m in RX_GERENCIADOR.finditer(d.texto):
            ger = re.sub(r"\s+", " ", m.group(1))[:160]
            ctx = d.texto[m.start(1): m.end(1) + 200]
            ufm = RX_UF.search(ctx)
            uf = ufm.group(1) if ufm else foro_uf
            municipal = bool(re.match(r"(?:Prefeitura|Munic)", ger, re.I))
            if uf is None and not municipal:
                continue                                    # consórcio sem UF identificada: não afirma
            if uf == "RJ" and reg != "14133":
                continue                                    # consórcio/município fluminense sob a 8.666: regime local
            grau = "forte" if (municipal and reg == "14133") else "medio"
            sinais.append({"sinal": "gerenciador_municipal", "grau": grau, "gerenciador": ger, "uf": uf,
                           "uf_pelo_foro": ufm is None, "regime": reg,
                           "prova": f'{d.ref} ({d.titulo[:70]}) — "{cc.trecho(d.texto, m.start(), m.end(), 40)[:420]}"'})
            break
    uma: dict[str, dict] = {}
    for x in sinais:                                        # um por tipo: o mais grave, o primeiro documento
        if x["sinal"] not in uma or (x["grau"] == "forte" and uma[x["sinal"]]["grau"] != "forte"):
            uma[x["sinal"]] = x
    sinais = list(uma.values())
    prova_adesao = externo or ato
    d0, m0 = prova_adesao
    return {"adesao": "externa", "regime": reg, "sinais": sinais, "foro_fora_rj": foro,
            "prova_adesao": f'{d0.ref} — "{cc.trecho(d0.texto, m0.start(), m0.end(), 60)[:300]}"'}


_RX_TIT_ADESAO = re.compile(r"ades[aã]o|carona|anuencia|\barp\b|ata de registro", re.I)


def base_adesao(limite: int | None = None) -> tuple[list[tuple[str, dict]], dict]:
    """Processos de ADESÃO do acervo: NE com Mod. Licitação 12 (externa) / 10 (interna) ou, sem NE legível, título de
    documento que fala de adesão/ARP. → [(tag, info_ne)], cobertura."""
    cache = cc.carregar_cache_ne()
    todos = cc.tags()[: limite or None]
    base, cob = [], {"processos_no_acervo": len(todos), "sem_ne_legivel": 0, "ne_12_externa": 0, "ne_10_interna": 0,
                     "sem_ne_mas_titulo_de_adesao": 0}
    cc.prefetch_ne(todos, cache)
    try:
        for n, t in enumerate(todos):
            ne = cc.modalidade_ne(t, cache)
            cod = cc.codigo_mod(ne)
            if cod == "12":
                cob["ne_12_externa"] += 1
                base.append((t, ne))
            elif cod == "10":
                cob["ne_10_interna"] += 1
                base.append((t, ne))
            elif cod is None:
                cob["sem_ne_legivel"] += 1
                if cc.titulos_casam(t, _RX_TIT_ADESAO):
                    cob["sem_ne_mas_titulo_de_adesao"] += 1
                    base.append((t, ne))
            if n % 500 == 499:
                cc.salvar_cache_ne(cache)
    finally:
        cc.salvar_cache_ne(cache)
    return base, cob


def varrer(limite: int | None = None) -> dict:
    base, cob = base_adesao(limite)
    avaliados = sem_texto = interna = sem_ato = 0
    brutos: list[tuple[str, dict, list[cc.Doc]]] = []
    externas = [(t, None) for t, ne in base if cc.codigo_mod(ne) != "10"]
    interna += len(base) - len(externas)      # ata do próprio Estado (Mod. 10): restrição de ente não se aplica
    for t, ds in cc.docs_em_paralelo(externas):
        if not ds:
            sem_texto += 1
            continue
        r = avaliar(t, ds)
        if r["adesao"] == "interna":
            interna += 1
            continue
        if r["adesao"] is None:
            sem_ato += 1
            continue
        avaliados += 1
        if r["sinais"]:
            brutos.append((t, r, ds))
    obs = cc.ob_pagas({cc.canon(t) for t, _, _ in brutos})
    achados = []
    for t, r, ds in brutos:
        ordem = {"forte": 0, "medio": 1, "fraco": 2}
        s = sorted(r["sinais"], key=lambda x: ordem[x["grau"]])
        ob = obs.get(cc.canon(t))
        achados.append({
            "processo": cc.canon(t), "grau": s[0]["grau"], "sinal": s[0]["sinal"],
            "prova": " | ".join(x["prova"] for x in s) + f" | adesão: {r['prova_adesao']}"
                     + (f" | foro: {r['foro_fora_rj']}" if r.get("foro_fora_rj") else ""),
            "sinais": s, "regime": r["regime"], "orgao": cc.orgao(ds), "credor": cc.credor_principal(ob),
            "valor_pago_ob": ob["total"] if ob else None, "obs": (ob or {}).get("obs", [])[:20],
            "porque": ("Inocente possível: anuência expressa do gerenciador e norma do ente aderente admitindo a carona "
                       "(RJ: Dec. 46.751/2019 art. 26). Não afasta a cláusula do PRÓPRIO instrumento que limita os "
                       "aderentes (vinculação ao edital) nem o art. 86 §3º da Lei 14.133 para gerenciador municipal; "
                       "conferir a anuência e a cláusula no edital/ata juntados."),
            "fonte": "SEI (texto dos autos) + SIAFE (_ob_paga, piso)"})
    achados.sort(key=lambda a: ({"forte": 0, "medio": 1, "fraco": 2}[a["grau"]], -(a["valor_pago_ob"] or 0)))
    cob.update({"sem_texto": sem_texto, "adesao_interna": interna, "sem_prova_de_adesao_do_orgao": sem_ato,
                "nota": "universo = processos com prova de adesão EXTERNA deste órgão (NE Mod. 12 ou ato de adesão); "
                        "edital/ata do gerenciador nem sempre está juntado — ausência da cláusula nos autos ≠ ausência "
                        "no instrumento."})
    cc.ligar(achados, VICIO)
    return cc.resultado(ID, avaliados, cob, achados)
