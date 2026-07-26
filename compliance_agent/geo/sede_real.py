# -*- coding: utf-8 -*-
"""
Existe sede real neste endereço? — sem Google, sem Mapillary.

Por que trocar: o caminho anterior dependia de Street View/Places (billing do
dono desligado em 2026-06-25 → o sweep passou a rodar em vazio: 1.272 endereços
processados, 0 foto) e de Mapillary (vetado — imagem ruim virava falso-positivo).
Foto é o ELO MAIS FRACO da cadeia: cara, rara, desatualizada e interpretável.

O que substitui, e é mais forte: **a própria base da Receita**. Em
`data/receita_estab.db` há 6,17 milhões de estabelecimentos com endereço já
partido em campos e `endereco_norm` em nível de PRÉDIO (logradouro+número+
bairro+CEP, sem complemento) — indexado, offline, custo zero. Ninho de CNPJs,
sala compartilhada, contabilidade hospedando terceiros, telefone e e-mail
repetidos: tudo isso é apurável em milissegundos e diz mais sobre substância
econômica do que qualquer fachada fotografada.

Cadeia de sinais (nenhum condena sozinho — composição condena):

  SUSPEITA                         SUBSTÂNCIA (sede real)
  ninho_empresarial                unica_no_predio
  mesma_sala                       endereco_antigo
  contabilidade_no_local           osm_uso_comercial
  telefone_compartilhado           telefone_exclusivo
  email_compartilhado              cep_coerente
  email_generico
  complemento_residencial
  osm_residencial
  osm_sem_edificacao
  cep_incoerente

HONESTIDADE (regra da casa, e a lição que o Mapillary ensinou):
  · dado ausente → `inapuravel`, jamais "fachada";
  · OSM não ter o prédio mapeado NÃO é prova de terreno vazio — o sinal
    `osm_sem_edificacao` só dispara se a REGIÃO estiver mapeada (há prédios em
    volta), senão é lacuna de cobertura do OSM e cala a boca;
  · suspeita e substância são DUAS escalas — substância não apaga suspeita,
    porque um escritório de verdade num prédio-ninho continua sendo um ninho.

Puro (`avaliar_sede`) separado da montagem (`perfil_sede`), como em
`compliance_agent/empresa_fantasma.py`. Camada física OSM/CEP em `.osm_local`.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from datetime import date, datetime
from pathlib import Path
from compliance_agent.reporting.intel_base import moeda

logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent.parent
DB_RECEITA = RAIZ / "data" / "receita_estab.db"

VEREDITOS = ("inapuravel", "sede_provavel", "indefinido", "suspeita", "forte_suspeita")

# CNAE 6920-6: atividades de contabilidade — hospedar dezenas de CNPJs no
# próprio endereço é o padrão clássico do endereço cedido/virtual.
_CNAE_CONTABIL = "6920"
_EMAIL_GENERICO = ("gmail.", "hotmail.", "yahoo.", "outlook.", "bol.com",
                   "uol.com", "terra.com", "ig.com.br", "live.com")
_COMPL_RESIDENCIAL = ("apt", "apto", "apartamento", "casa", "fundos", "sobrado",
                      "kitnet", "quitinete", "res ", "residencia")
_SEM_NUMERO = ("", "s/n", "sn", "s n", "snº", "0", "00", "000", "sem numero")

# Faixa em que compartilhar um identificador SIGNIFICA algo. Calibrado no dump:
# 7 empresas com o mesmo e-mail é indício (ONG Con-tato); 16.846 é a Contabilizei
# abrindo CNPJ, e 616 é o grupo Enel — serviço/holding, não ninho.
_RARO_MIN, _RARO_MAX = 2, 20

# Complemento que identifica UNIDADE (sala/conjunto/apto) vs apenas ANDAR/piso.
# 'ANDAR 2' (Telemar) e 'ANDAR 4' (Barcas) reúnem dezenas de empresas legítimas
# num andar de torre comercial — dividir andar não é dividir sala.
_UNIDADE_RE = re.compile(
    r"\b(SALAS?|SL|CJ|CONJ|CONJUNTO|APTO?|AP|UNIDADE|UNID|GRUPO|GR)\b\.?\s*\d",
    re.IGNORECASE)
_ANDAR_RE = re.compile(
    r"\b(ANDAR|PAV|PAVMTO|PAVIMENTO|PISO|TERREO|SOBRELOJA|LOJA|GALPAO|BLOCO|BLC|BL)\b",
    re.IGNORECASE)


def complemento_e_unidade(c) -> bool:
    """'BLOCO 001 SALA 721' → True (sala). 'ANDAR 2' / 'LOJA' → False (andar/genérico).

    Só complemento de UNIDADE sustenta o sinal `mesma_sala`: dividir o mesmo
    andar de uma torre é o normal do mercado, dividir a mesma sala não é.
    """
    t = normalizar_complemento(c)
    if not t:
        return False
    if _UNIDADE_RE.search(t):
        return True
    return bool(re.fullmatch(r"\d{1,5}", t)) and not _ANDAR_RE.search(t)


def telefone_valido(t) -> bool:
    """Descarta preenchimento de formulário: '00', '210', '2122222222', '2199999999'.

    São 129.152 + 28.628 + 21.238 + 13.234 ocorrências no dump — agrupar por eles
    inventaria ninhos que não existem.
    """
    d = re.sub(r"\D", "", str(t or ""))
    if len(d) < 10:
        return False
    corpo = d[2:]
    return len(set(corpo)) > 2


def _norm(s) -> str:
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", t).strip()


def normalizar_complemento(c) -> str:
    """'  BLOCO 001 SALA 721' e 'BLOCO 001;SALA 721' → mesma chave de sala.

    A Receita entrega complemento sujo (espaços de padding, ';' como separador,
    caixa variável). Sem normalizar, a mesma sala vira duas e o ninho some.
    """
    t = unicodedata.normalize("NFKD", str(c or ""))
    t = "".join(x for x in t if not unicodedata.combining(x)).upper()
    return re.sub(r"[^A-Z0-9]+", " ", t).strip()


def _para_data(s):
    if isinstance(s, (date, datetime)):
        return s if isinstance(s, date) else s.date()
    txt = re.sub(r"\D", "", str(s or ""))
    for fmt, corte in (("%Y-%m-%d", 10), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(str(s)[:corte] if "-" in str(s) else txt[:8],
                                     fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _sem_numero(p) -> bool:
    return _norm(p.get("numero")).replace(".", "") in _SEM_NUMERO


# ── sinais de SUSPEITA (perfil → dict|None) ──────────────────────────────────

def _s_ninho(p):
    """CONTEXTO, nunca decisivo. Torre comercial no Centro do Rio hospeda 300
    empresas legítimas — contagem de prédio não distingue torre de ninho, e pesá-la
    alto acusava RIOCARD, Telemar e Ampla Energia de fachada (2026-07-23)."""
    n = p.get("no_predio_terceiros") or 0
    if n >= 20:
        peso = 8
    elif n >= 8:
        peso = 5
    else:
        return None
    return dict(id="ninho_empresarial", peso=peso,
                detalhe=f"{n} empresas de terceiros no mesmo prédio (contexto)")


def _s_mesma_sala(p):
    """Terceiros na MESMA UNIDADE — só conta complemento de sala, não de andar."""
    n = p.get("na_sala_terceiros") or 0
    if not complemento_e_unidade(p.get("complemento")):
        return None  # andar/genérico: dividir andar de torre é o normal do mercado
    if n >= 5:
        peso = 26
    elif n >= 3:
        peso = 18
    elif n == 2:
        peso = 8
    else:
        return None
    return dict(id="mesma_sala", peso=peso,
                detalhe=f"{n} CNPJs de terceiros na MESMA sala/conjunto "
                        f"('{str(p.get('complemento') or '').strip()[:30]}')")


def _s_contabilidade(p):
    """Contabilidade na mesma SALA (no prédio inteiro é ruído: toda torre tem)."""
    n = p.get("contabilidade_na_sala") or 0
    if n >= 1:
        return dict(id="contabilidade_na_sala", peso=12,
                    detalhe=f"{n} escritório(s) de contabilidade na mesma sala "
                            f"(padrão de endereço cedido)")


def _s_telefone_compartilhado(p):
    """Fraco por design: o campo é sujo e acusaria RIOCARD (5) e Ampla (12)."""
    n = p.get("com_mesmo_telefone") or 0
    if not telefone_valido(p.get("telefone")) or not (_RARO_MIN <= n <= _RARO_MAX):
        return None
    return dict(id="telefone_compartilhado", peso=6,
                detalhe=f"telefone declarado por {n} empresas")


def _s_email_compartilhado(p):
    """O melhor discriminador do conjunto — desde que raro.

    Fora da faixa é serviço, não identidade: abertura@maismei (17.665),
    meucnpj@contabilizei (16.846), BTG/XP/Santander, ou holding (Enel, 616).
    """
    n = p.get("com_mesmo_email") or 0
    if not p.get("email") or n < _RARO_MIN:
        return None
    if n <= _RARO_MAX:
        peso, nota = 22, "grupo pequeno = identidade compartilhada"
    elif n <= 100:
        peso, nota = 6, "grupo grande — provável serviço contábil"
    else:
        return None  # serviço de massa: não diz nada sobre esta empresa
    return dict(id="email_compartilhado", peso=peso,
                detalhe=f"e-mail declarado por {n} empresas ({nota})")


def _s_email_generico(p):
    mail = _norm(p.get("email"))
    tot = p.get("total_recebido") or 0
    if mail and any(d in mail for d in _EMAIL_GENERICO) and tot >= 1_000_000:
        return dict(id="email_generico", peso=10,
                    detalhe=f"e-mail pessoal/gratuito para quem recebeu R$ {moeda(tot)}")


def _s_complemento_residencial(p):
    c = f" {_norm(p.get('complemento'))} "
    if any(f" {t}" in c for t in _COMPL_RESIDENCIAL):
        return dict(id="complemento_residencial", peso=12,
                    detalhe=f"complemento residencial '{str(p.get('complemento') or '').strip()[:40]}'")


def _s_osm_residencial(p):
    osm = p.get("osm") or {}
    if osm.get("apuravel") and osm.get("classe") == "residencial":
        return dict(id="osm_residencial", peso=14,
                    detalhe="edificação mapeada no OSM é residencial (casa/apto)")


def _s_osm_sem_edificacao(p):
    """Só acusa se a REGIÃO estiver mapeada — senão é lacuna do OSM, não terreno vazio."""
    osm = p.get("osm") or {}
    if (osm.get("apuravel") and osm.get("classe") == "sem_edificacao"
            and osm.get("regiao_mapeada")):
        return dict(id="osm_sem_edificacao", peso=18,
                    detalhe="nenhuma edificação no ponto, embora a região esteja "
                            "mapeada no OSM")


def _s_cep_incoerente(p):
    if p.get("cep_coerente") is False:
        return dict(id="cep_incoerente", peso=16,
                    detalhe="logradouro declarado não confere com o do CEP (ViaCEP/BrasilAPI)")


def _s_sem_numero(p):
    if _sem_numero(p):
        return dict(id="sem_numero", peso=0,
                    detalhe="endereço sem número — não localizável (INAPURÁVEL)")


_SINAIS_SUSPEITA = [_s_ninho, _s_mesma_sala, _s_contabilidade,
                    _s_telefone_compartilhado, _s_email_compartilhado,
                    _s_email_generico, _s_complemento_residencial,
                    _s_osm_residencial, _s_osm_sem_edificacao, _s_cep_incoerente]


# ── sinais de SUBSTÂNCIA ─────────────────────────────────────────────────────

def _b_unica_no_predio(p):
    if not (p.get("no_predio_terceiros") or 0) and _norm(p.get("situacao")).startswith("ativ"):
        return dict(id="unica_no_predio", peso=15,
                    detalhe="nenhuma empresa de terceiros no endereço (sede exclusiva)")


def _b_muitas_filiais(p):
    """Rede própria de estabelecimentos = operação real, não CNPJ de papel.
    (Telemar 502, MGS 362, Ampla 270 — o que separa empresa grande de casca.)"""
    n = p.get("filiais_proprias") or 0
    if n >= 10:
        peso = 20
    elif n >= 3:
        peso = 10
    else:
        return None
    return dict(id="rede_propria", peso=peso,
                detalhe=f"{n} estabelecimentos do mesmo grupo econômico")


def _b_endereco_antigo(p):
    d = _para_data(p.get("data_inicio"))
    if d and (date.today() - d).days >= 3650:
        return dict(id="endereco_antigo", peso=10,
                    detalhe=f"estabelecimento aberto em {d.isoformat()} (>10 anos)")


def _b_osm_comercial(p):
    osm = p.get("osm") or {}
    if osm.get("apuravel") and osm.get("classe") == "comercial":
        return dict(id="osm_uso_comercial", peso=18,
                    detalhe="edificação mapeada no OSM é comercial/industrial")


def _b_telefone_exclusivo(p):
    if telefone_valido(p.get("telefone")) and (p.get("com_mesmo_telefone") or 0) == 1:
        return dict(id="telefone_exclusivo", peso=6,
                    detalhe="telefone não repetido em outras empresas")


def _b_cep_coerente(p):
    if p.get("cep_coerente") is True:
        return dict(id="cep_coerente", peso=8,
                    detalhe="logradouro confere com o CEP declarado")


_SINAIS_SUBSTANCIA = [_b_unica_no_predio, _b_muitas_filiais, _b_endereco_antigo,
                      _b_osm_comercial, _b_telefone_exclusivo, _b_cep_coerente]


# ── veredito ─────────────────────────────────────────────────────────────────

def avaliar_sede(perfil: dict) -> dict:
    """Perfil → veredito de substância física. Puro, testável offline."""
    if _sem_numero(perfil) or not (perfil.get("no_predio") or 0):
        motivo = ("endereço sem número" if _sem_numero(perfil)
                  else "CNPJ não localizado na base de estabelecimentos")
        sinais = [s for f in (_s_sem_numero,) if (s := f(perfil))]
        return {"cnpj": perfil.get("cnpj"), "veredito": "inapuravel", "apuravel": False,
                "score_suspeita": 0, "score_substancia": 0, "sinais": sinais,
                "motivo": motivo}

    suspeita = [s for f in _SINAIS_SUSPEITA if (s := f(perfil))]
    substancia = [s for f in _SINAIS_SUBSTANCIA if (s := f(perfil))]
    ss = min(100, sum(s["peso"] for s in suspeita))
    sb = min(100, sum(s["peso"] for s in substancia))

    # Substância pesa CONTRA a acusação: empresa com rede própria e décadas no
    # mesmo endereço não vira suspeita por dividir o prédio (lição dos falsos
    # -positivos RIOCARD/Telemar/Ampla). Mas também não apaga suspeita forte —
    # as duas escalas convivem e ficam visíveis no laudo.
    if ss >= 45 and sb < 15:
        v = "forte_suspeita"
    elif ss >= 25 and sb < 25:
        v = "suspeita"
    elif sb >= 25 and ss < 15:
        v = "sede_provavel"
    else:
        v = "indefinido"

    for s in suspeita:
        s["direcao"] = "suspeita"
    for s in substancia:
        s["direcao"] = "substancia"
    return {"cnpj": perfil.get("cnpj"), "razao": perfil.get("razao"),
            "veredito": v, "apuravel": True,
            "score_suspeita": ss, "score_substancia": sb,
            "sinais": sorted(suspeita + substancia, key=lambda s: -s["peso"])}


# ── montagem do perfil (base local da Receita) ───────────────────────────────

def _conn(db: Path | str | None = None) -> sqlite3.Connection:
    caminho = Path(db) if db else DB_RECEITA
    return sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)


def perfil_sede(cnpj: str, *, com_rede: bool = False, db: Path | str | None = None) -> dict | None:
    """Monta o perfil a partir de `receita_estab.db` (local, indexado, offline).

    `com_rede=True` acrescenta a camada física gratuita (OSM + CEP). Sem rede o
    veredito continua válido — só perde os sinais osm_*/cep_*.
    """
    cnpj = re.sub(r"\D", "", str(cnpj or ""))
    if len(cnpj) != 14:
        return None
    try:
        c = _conn(db)
    except sqlite3.Error as exc:
        logger.warning("base de estabelecimentos indisponível (%s): sede INAPURÁVEL", exc)
        return None
    try:
        row = c.execute(
            "SELECT tipo_logradouro, logradouro, numero, complemento, bairro, cep, "
            "uf, municipio, situacao_cadastral, cnae_principal, data_inicio_atividade, "
            "telefone1, correio_eletronico, endereco_norm, nome_fantasia "
            "FROM estabelecimentos WHERE cnpj=?", (cnpj,)).fetchone()
        if row is None:
            return None
        (tipo_log, log, num, compl, bairro, cep, uf, mun, sit, cnae,
         dt_ini, tel, mail, norm_end, fantasia) = row

        p = {"cnpj": cnpj, "razao": fantasia or "", "logradouro": f"{tipo_log or ''} {log or ''}".strip(),
             "numero": num, "complemento": compl, "bairro": bairro, "cep": cep,
             "uf": uf, "municipio": mun, "situacao": sit, "cnae": cnae,
             "data_inicio": dt_ini, "telefone": tel, "email": mail,
             "endereco_norm": norm_end}

        basico = cnpj[:8]
        p["filiais_proprias"] = c.execute(
            "SELECT COUNT(*) FROM estabelecimentos WHERE cnpj_basico=?",
            (basico,)).fetchone()[0]

        if norm_end:
            viz = c.execute(
                "SELECT cnpj, cnpj_basico, complemento, cnae_principal "
                "FROM estabelecimentos WHERE endereco_norm=?", (norm_end,)).fetchall()
            # Filiais do PRÓPRIO grupo no mesmo endereço não são coabitantes.
            terceiros = [v for v in viz if v[1] != basico]
            p["no_predio"] = len(viz)
            p["no_predio_terceiros"] = len(terceiros)
            sala = normalizar_complemento(compl)
            if sala and complemento_e_unidade(compl):
                na_sala = [v for v in terceiros
                           if normalizar_complemento(v[2]) == sala]
            else:
                na_sala = []  # andar/genérico não caracteriza "mesma sala"
            p["na_sala_terceiros"] = len(na_sala)
            p["contabilidade_na_sala"] = sum(
                1 for v in na_sala if str(v[3] or "").startswith(_CNAE_CONTABIL))
            p["vizinhos"] = [v[0] for v in terceiros[:200]]
        else:
            p["no_predio"] = p["no_predio_terceiros"] = 0
            p["na_sala_terceiros"] = 0
            p["contabilidade_na_sala"] = 0

        p["com_mesmo_telefone"] = (
            c.execute("SELECT COUNT(*) FROM estabelecimentos WHERE telefone1=?",
                      (tel,)).fetchone()[0] if tel else 0)
        p["com_mesmo_email"] = (
            c.execute("SELECT COUNT(*) FROM estabelecimentos WHERE correio_eletronico=?",
                      (mail,)).fetchone()[0] if mail else 0)
    finally:
        c.close()

    if com_rede:
        # Uma única consulta de CEP serve às duas camadas: `municipio` na base da
        # Receita é CÓDIGO ('6001'), não nome — mandá-lo ao Nominatim envenenava a
        # busca. O nome da cidade vem do ViaCEP.
        cep_dados = _viacep(p.get("cep"))
        p["municipio_nome"] = (cep_dados or {}).get("localidade") or ""
        p["cep_coerente"] = _cep_confere(p, cep_dados)
        p["osm"] = _camada_osm(p)
    return p


# ── camada física gratuita (OSM + CEP) ───────────────────────────────────────

_OSM_COMERCIAL = ("commercial", "industrial", "office", "retail", "warehouse",
                  "supermarket", "hospital", "school", "public", "civic")
_OSM_RESIDENCIAL = ("house", "residential", "apartments", "detached", "bungalow",
                    "terrace", "semidetached_house", "hut")


def _classificar_edificacao(dados: dict) -> str | None:
    """Tags do Overpass → 'comercial' | 'residencial' | 'sem_edificacao' | None."""
    if not dados.get("apuravel"):
        return None
    tags = dados.get("tags") or []
    if dados.get("tem_shop") or dados.get("tem_office"):
        return "comercial"
    valores = {str(t.get("building") or "").lower() for t in tags}
    if valores & set(_OSM_COMERCIAL):
        return "comercial"
    if valores & set(_OSM_RESIDENCIAL):
        return "residencial"
    if not dados.get("tem_building"):
        return "sem_edificacao"
    return None  # building=yes sem tipo: existe prédio, natureza desconhecida


def _camada_osm(p: dict) -> dict:
    """Geocodifica e classifica o ponto. Falha de rede → {apuravel: False}."""
    from compliance_agent.geo import osm_local

    endereco = ", ".join(x for x in (p.get("logradouro"), p.get("numero"),
                                     p.get("bairro"), p.get("municipio_nome"),
                                     p.get("uf")) if x)
    ponto = osm_local.geocodificar(endereco)
    if not ponto:
        return {"apuravel": False, "motivo": "endereço não geocodificado"}
    perto = osm_local.edificacao_no_ponto(ponto["lat"], ponto["lon"], raio_m=40)
    if not perto.get("apuravel"):
        return {"apuravel": False, "motivo": "Overpass indisponível"}
    classe = _classificar_edificacao(perto)
    out = {"apuravel": True, "classe": classe, "lat": ponto["lat"],
           "lon": ponto["lon"], "precisao": ponto.get("precisao"),
           "regiao_mapeada": True}
    if classe == "sem_edificacao":
        # A pergunta que separa "terreno vazio" de "OSM não mapeou aqui".
        regiao = osm_local.edificacao_no_ponto(ponto["lat"], ponto["lon"], raio_m=300)
        out["regiao_mapeada"] = bool(regiao.get("apuravel") and regiao.get("tem_building"))
    return out


def _viacep(cep) -> dict | None:
    """CEP → payload do ViaCEP. Indisponibilidade/erro → None (nunca inventa)."""
    cep = re.sub(r"\D", "", str(cep or ""))
    if len(cep) != 8:
        return None
    try:
        import httpx
    except ImportError:
        return None
    try:
        r = httpx.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=12,
                      headers={"User-Agent": "JFN-fiscalizacao/1.0 (gabinete RJ)"})
        if r.status_code != 200:
            return None
        dados = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("ViaCEP indisponível p/ %s: %s", cep, exc)
        return None
    return None if dados.get("erro") else dados


def _cep_confere(p: dict, dados: dict | None) -> bool | None:
    """Logradouro do CEP × declarado. Indisponível/CEP genérico → None."""
    cep = re.sub(r"\D", "", str(p.get("cep") or ""))
    if not dados or len(cep) != 8 or cep.endswith("000"):
        return None  # CEP de município inteiro não prova nem desmente endereço
    oficial, declarado = _norm(dados.get("logradouro")), _norm(p.get("logradouro"))
    if not oficial or not declarado:
        return None
    nucleo = re.sub(r"^(rua|avenida|av|travessa|estrada|rodovia|praca|alameda|largo) ",
                    "", oficial)
    return nucleo in declarado or _norm(dados.get("localidade")) == _norm(p.get("municipio"))


def avaliar_cnpj(cnpj: str, *, com_rede: bool = False, db=None) -> dict | None:
    """Atalho: CNPJ → veredito de sede. None se o CNPJ não existe na base."""
    p = perfil_sede(cnpj, com_rede=com_rede, db=db)
    return avaliar_sede(p) if p else None
