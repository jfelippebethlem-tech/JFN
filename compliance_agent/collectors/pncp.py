"""
Coletor do PNCP — Portal Nacional de Contratações Públicas.
API pública, sem autenticação.

Usos:
  1. Verificar se OBs acima de R$30k têm contrato publicado no PNCP
     (obrigatório desde Lei 14.133/21 art. 94)
  2. Buscar contratos de um fornecedor específico (CNPJ)
  3. Coletar licitações abertas de órgãos do RJ para monitoramento

Endpoint principal:
  https://pncp.gov.br/api/pncp/v1/contratos
  Parâmetros: cnpjOrgao, dataInicial, dataFinal, pagina, tamanhoPagina
"""

import asyncio
import re
from datetime import date, timedelta
from typing import Optional

import logging

import httpx

logger = logging.getLogger(__name__)

PNCP_BASE = "https://pncp.gov.br/api/pncp/v1"
# API de CONSULTA (publica, sem login) — Onda 2. Difere da de gestao (api/pncp/v1).
CONSULTA_BASE = "https://pncp.gov.br/api/consulta/v1"

# Modalidades (codigoModalidadeContratacao) — a API EXIGE este parametro. Quando o
# chamador nao especifica, varremos as de maior relevancia fiscalizatoria.
#   4=Concorrencia-Eletronica · 6=Pregao-Eletronico · 8=Dispensa · 9=Inexigibilidade
MODALIDADES_PADRAO = [6, 8, 9, 4]
MODALIDADE_NOME = {
    1: "Leilao-Eletronico", 2: "Dialogo Competitivo", 3: "Concurso",
    4: "Concorrencia-Eletronica", 5: "Concorrencia-Presencial", 6: "Pregao-Eletronico",
    7: "Pregao-Presencial", 8: "Dispensa", 9: "Inexigibilidade", 10: "Manifestacao de Interesse",
    11: "Pre-qualificacao", 12: "Credenciamento", 13: "Leilao-Presencial",
}

# CNPJs dos principais órgãos do Estado do RJ para monitoramento
ORGAOS_RJ = {
    "SECRETARIA DE FAZENDA RJ":          "30636722000105",
    "GOVERNO DO ESTADO RJ":              "42498600000148",
    "SECRETARIA DE SAUDE RJ":            "08739068000103",
    "SECRETARIA DE EDUCACAO RJ":         "08739068000104",
    "DETRAN RJ":                         "09176466000109",
    "INEA":                              "10736572000109",
}


async def _get_pncp(endpoint: str, params: dict) -> Optional[dict]:
    url = f"{PNCP_BASE}{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, params=params,
                                 headers={"User-Agent": "JFN-Compliance/1.0"})
            if r.status_code == 200:
                return r.json()
    except Exception as exc:
        logger.warning("PNCP %s indisponível (None pode ser falso 'sem contrato'): %s", endpoint, exc)
    return None


async def _get_consulta(endpoint: str, params: dict) -> Optional[dict]:
    """GET na API de CONSULTA do PNCP (sem login). Retorna o JSON ou None."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{CONSULTA_BASE}{endpoint}", params=params,
                                 headers={"User-Agent": "JFN-Compliance/2.0"})
            if r.status_code == 200:
                return r.json()
    except Exception as exc:
        logger.warning("PNCP %s indisponível (None pode ser falso 'sem contrato'): %s", endpoint, exc)
    return None


def _simplificar_contratacao(it: dict) -> dict:
    """Normaliza uma contratacao do PNCP no shape do contrato /api/pncp.

    docs/red_flags ficam vazios aqui (preenchidos na Onda 2c, ao baixar e analisar o
    edital/TR). Mantem proveniencia (link, numeroControlePNCP) p/ rastreabilidade."""
    org = it.get("orgaoEntidade") or {}
    uni = it.get("unidadeOrgao") or {}
    return {
        "id_pncp": it.get("numeroControlePNCP"),
        "objeto": it.get("objetoCompra"),
        "valor": it.get("valorTotalEstimado") or it.get("valorTotalHomologado"),
        "modalidade": it.get("modalidadeNome"),
        "situacao": it.get("situacaoCompraNome"),
        "orgao_cnpj": org.get("cnpj"),
        "orgao": org.get("razaoSocial"),
        "unidade": uni.get("nomeUnidade"),
        "uf": uni.get("ufSigla"),
        "municipio": uni.get("municipioNome"),
        "data_abertura": it.get("dataAberturaProposta"),
        "data_encerramento": it.get("dataEncerramentoProposta"),
        "processo": it.get("processo"),
        "link": it.get("linkSistemaOrigem"),
        "docs": [],        # Onda 2c
        "red_flags": [],   # Onda 2c
    }


async def buscar_contratacoes(
    uf: str = "RJ",
    data_ini: Optional[date] = None,
    data_fim: Optional[date] = None,
    modalidade: Optional[int] = None,
    abertos: bool = False,
    orgao_cnpj: Optional[str] = None,
    max_paginas: int = 3,
) -> list[dict]:
    """Consulta contratacoes no PNCP (API publica de consulta) — Onda 2.

    abertos=False: historico por publicacao (janela data_ini..data_fim).
    abertos=True:  contratacoes com PROPOSTA EM ABERTO (fiscalizacao preventiva) —
                   a API exige dataFinal >= hoje (prazo de encerramento futuro).
    modalidade=None varre MODALIDADES_PADRAO. orgao_cnpj filtra por orgao (client-side).
    tamanhoPagina e fixo em 50 (a API exige >=10). Idempotente; dedup por id_pncp.
    """
    hoje = date.today()
    if abertos:
        # propostas abertas: encerramento entre hoje e +N dias
        d_fim = data_fim or (hoje + timedelta(days=30))
        if d_fim < hoje:
            d_fim = hoje + timedelta(days=30)
        endpoint, base_params = "/contratacoes/proposta", {"dataFinal": d_fim.strftime("%Y%m%d")}
    else:
        d_ini = data_ini or (hoje - timedelta(days=30))
        d_fim = data_fim or hoje
        endpoint = "/contratacoes/publicacao"
        base_params = {"dataInicial": d_ini.strftime("%Y%m%d"), "dataFinal": d_fim.strftime("%Y%m%d")}

    if uf:
        base_params["uf"] = uf.upper()
    modalidades = [modalidade] if modalidade else MODALIDADES_PADRAO
    alvo_orgao = re.sub(r"\D", "", orgao_cnpj) if orgao_cnpj else None

    vistos: set[str] = set()
    out: list[dict] = []
    for mod in modalidades:
        for pagina in range(1, max_paginas + 1):
            params = {**base_params, "codigoModalidadeContratacao": mod,
                      "pagina": pagina, "tamanhoPagina": 50}
            j = await _get_consulta(endpoint, params)
            data = (j or {}).get("data") or []
            if not data:
                break
            for it in data:
                cid = it.get("numeroControlePNCP")
                if not cid or cid in vistos:
                    continue
                if alvo_orgao and re.sub(r"\D", "", (it.get("orgaoEntidade") or {}).get("cnpj", "")) != alvo_orgao:
                    continue
                vistos.add(cid)
                out.append(_simplificar_contratacao(it))
            total_pag = (j or {}).get("totalPaginas") or 1
            if pagina >= total_pag:
                break
            await asyncio.sleep(0.2)
    return out


# ---------------------------------------------------------------------------
# Onda 2c — baixar documentos do edital (PDF/ZIP/DOCX → texto) p/ red flags Lex
# ---------------------------------------------------------------------------

def _parse_id_pncp(id_pncp: str) -> Optional[tuple]:
    """'CNPJ-modulo-SEQ/ANO' -> (cnpj, ano, seq:int). Ex.: 42441758000105-1-000101/2025."""
    try:
        esq, ano = id_pncp.split("/")
        partes = esq.split("-")
        cnpj = re.sub(r"\D", "", partes[0])
        seq = int(re.sub(r"\D", "", partes[-1]))
        if len(cnpj) != 14:
            return None
        return cnpj, ano.strip(), seq
    except Exception:
        return None


async def buscar_itens(id_pncp: str) -> list[dict]:
    """Itens com PREÇO UNITÁRIO de uma contratação (a 'tabela de preço' da Lei 14.133, ESTRUTURADA).

    Resolve o muro da Onda 2: a ARP/tabela de itens NÃO é alcançável raspando a árvore SEI (processos
    acessíveis via OB são de pagamento), mas o PNCP a expõe estruturada, pública e sem login —
    `GET /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens`. Insumo do extrator de preço e do conluio
    (comparar valor unitário entre fornecedores do mesmo objeto). id_pncp vem de `buscar_contratacoes`.
    """
    pr = _parse_id_pncp(id_pncp)
    if not pr:
        return []
    cnpj, ano, seq = pr
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{PNCP_BASE}/orgaos/{cnpj}/compras/{ano}/{seq}/itens",
                                 headers={"User-Agent": "JFN-Compliance/2.0"})
            if r.status_code != 200:
                return []
            itens = r.json() or []
    except Exception:
        return []
    out = []
    for it in itens:
        out.append({
            "numero": it.get("numeroItem"),
            "descricao": it.get("descricao"),
            "quantidade": it.get("quantidade"),
            "unidade": it.get("unidadeMedida"),
            "valor_unitario": it.get("valorUnitarioEstimado"),
            "valor_total": it.get("valorTotal"),
            "ncm_catmat": it.get("ncmNbsCodigo") or it.get("catalogo"),
            "situacao": it.get("situacaoCompraItemNome"),
        })
    return out


def _texto_de_pdf(blob: bytes, max_paginas: int = 12) -> str:
    try:
        import io

        from pypdf import PdfReader

        rd = PdfReader(io.BytesIO(blob))
        return "\n".join((p.extract_text() or "") for p in rd.pages[:max_paginas])
    except Exception:
        return ""


def _texto_de_docx(blob: bytes) -> str:
    try:
        import io
        import zipfile

        z = zipfile.ZipFile(io.BytesIO(blob))
        if "word/document.xml" in z.namelist():
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml))
    except Exception as exc:
        logger.debug("docx do PNCP ilegível (segue sem texto do edital): %s", exc)
    return ""


def _extrair_texto(nome: str, blob: bytes) -> str:
    """Extrai texto de PDF, ZIP (PDFs/DOCX internos) ou DOCX. '' se não suportado."""
    if blob[:4] == b"%PDF":
        return _texto_de_pdf(blob)
    if blob[:2] == b"PK":  # zip (pode ser .docx OU um .zip com PDFs)
        if nome.lower().endswith(".docx"):
            return _texto_de_docx(blob)
        try:
            import io
            import zipfile

            z = zipfile.ZipFile(io.BytesIO(blob))
            partes = []
            for n in z.namelist():
                inner = z.read(n)
                if n.lower().endswith(".pdf") or inner[:4] == b"%PDF":
                    partes.append(_texto_de_pdf(inner))
                elif n.lower().endswith(".docx"):
                    partes.append(_texto_de_docx(inner))
            return "\n".join(p for p in partes if p)
        except Exception:
            return ""
    return ""


async def baixar_documentos(id_pncp: str, max_arquivos: int = 5,
                            max_chars: int = 80_000) -> list[dict]:
    """Baixa os arquivos de uma contratação do PNCP e extrai o texto (PDF/ZIP/DOCX).

    Retorna [{titulo, tipo, url, n_chars, texto}]. Idempotente (cache em data/pncp_cache/).
    O texto alimenta os red flags do Lex (Onda 2c). Sem login (API pública).
    """
    parsed = _parse_id_pncp(id_pncp)
    if not parsed:
        return []
    cnpj, ano, seq = parsed
    meta = await _get_pncp(f"/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos", {})
    arquivos = meta if isinstance(meta, list) else (meta or {}).get("data", []) if meta else []
    out: list[dict] = []
    total = 0
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for a in (arquivos or [])[:max_arquivos]:
            url = a.get("url") or a.get("uri")
            if not url:
                continue
            try:
                d = await client.get(url, headers={"User-Agent": "JFN-Compliance/2.0"})
                blob = d.content if d.status_code == 200 else b""
            except Exception:
                blob = b""
            texto = _extrair_texto(a.get("titulo", "") or "", blob) if blob else ""
            if total < max_chars:
                texto = texto[: max_chars - total]
                total += len(texto)
            else:
                texto = ""
            out.append({
                "titulo": a.get("titulo"),
                "tipo": a.get("tipoDocumentoNome"),
                "url": url,
                "n_chars": len(texto),
                "texto": texto,
            })
            await asyncio.sleep(0.2)
    return out


async def buscar_contratos_fornecedor(
    cnpj_fornecedor: str,
    data_inicial: date,
    data_final: date,
) -> list[dict]:
    """Retorna contratos de um fornecedor (por CNPJ) em um período."""
    cnpj = re.sub(r"\D", "", cnpj_fornecedor)
    if len(cnpj) != 14:
        return []

    params = {
        "cnpjFornecedor": cnpj,
        "dataInicial": data_inicial.strftime("%Y%m%d"),
        "dataFinal": data_final.strftime("%Y%m%d"),
        "pagina": 1,
        "tamanhoPagina": 50,
    }
    result = await _get_pncp("/contratos", params)
    if not result:
        return []
    return result.get("data", []) or (result if isinstance(result, list) else [])


async def buscar_licitacoes_orgao(
    cnpj_orgao: str,
    data_inicial: date,
    data_final: date,
) -> list[dict]:
    """Retorna licitações de um órgão em um período."""
    cnpj = re.sub(r"\D", "", cnpj_orgao)
    params = {
        "cnpjOrgao": cnpj,
        "dataInicial": data_inicial.strftime("%Y%m%d"),
        "dataFinal": data_final.strftime("%Y%m%d"),
        "pagina": 1,
        "tamanhoPagina": 100,
    }
    result = await _get_pncp("/contratacoes/publicacao", params)
    if not result:
        return []
    return result.get("data", []) or (result if isinstance(result, list) else [])


async def verificar_obs_sem_pncp(session, target_date: date = None) -> list[dict]:
    """
    Para cada OB acima de R$30k do dia, verifica se há contrato publicado
    no PNCP para o mesmo CNPJ favorecido. Gera alertas para os que não têm.

    Lei 14.133/21 art. 94: contratos devem ser publicados no PNCP.
    """
    from compliance_agent.database.models import OrdemBancaria, Alerta

    target_date = target_date or date.today()
    MINIMO = 30_000.0
    JANELA_DIAS = 365  # contrato pode ter sido assinado até 1 ano antes da OB

    obs = (
        session.query(OrdemBancaria)
        .filter(
            OrdemBancaria.data_emissao == target_date,
            OrdemBancaria.valor >= MINIMO,
            OrdemBancaria.favorecido_cpf.isnot(None),
        )
        .all()
    )

    alertas = []
    verificados = set()  # evita checar mesmo CNPJ múltiplas vezes

    for ob in obs:
        cnpj = re.sub(r"\D", "", str(ob.favorecido_cpf or ""))
        if len(cnpj) != 14 or cnpj in verificados:
            continue
        verificados.add(cnpj)

        data_ini = target_date - timedelta(days=JANELA_DIAS)
        contratos = await buscar_contratos_fornecedor(cnpj, data_ini, target_date)
        await asyncio.sleep(0.3)

        if not contratos:
            # Sem contrato publicado no PNCP para este CNPJ
            titulo = f"OB sem contrato no PNCP — {ob.favorecido_nome or cnpj}"[:300]
            existe = session.query(Alerta).filter_by(titulo=titulo).first()
            if not existe:
                alerta = Alerta(
                    tipo="pncp_sem_contrato",
                    severidade="alta",
                    titulo=titulo,
                    descricao=(
                        f"OB nº {ob.numero_ob} (R$ {ob.valor:,.2f}) paga a "
                        f"'{ob.favorecido_nome}' (CNPJ {cnpj}) em {target_date}. "
                        f"Nenhum contrato encontrado no PNCP para este fornecedor "
                        f"nos últimos {JANELA_DIAS} dias. Pagamento sem amparo contratual "
                        f"publicado — possível irregularidade à luz da Lei 14.133/21 art. 94."
                    ),
                    evidencias=str({
                        "numero_ob": ob.numero_ob,
                        "cnpj": cnpj,
                        "favorecido": ob.favorecido_nome,
                        "valor": ob.valor,
                        "pncp_contratos_encontrados": 0,
                    }),
                    data_referencia=target_date,
                    ordem_bancaria_id=ob.id,
                )
                session.add(alerta)
                alertas.append({"ob": ob.numero_ob, "cnpj": cnpj, "valor": ob.valor})

    session.commit()
    return alertas


async def monitorar_licitacoes_rj() -> list[dict]:
    """
    Coleta licitações recentes de todos os órgãos RJ monitorados.
    Útil para alertas proativos antes de contratos suspeitos serem assinados.
    """
    hoje = date.today()
    semana_passada = hoje - timedelta(days=7)
    todas = []

    for nome, cnpj in ORGAOS_RJ.items():
        licitacoes = await buscar_licitacoes_orgao(cnpj, semana_passada, hoje)
        for lic in licitacoes:
            lic["orgao_nome"] = nome
            todas.append(lic)
        await asyncio.sleep(0.5)

    return todas


# ---------------------------------------------------------------------------
# Municipal Rio (PCRJ) — contratos por CNPJ do órgão + contratações por IBGE
# ---------------------------------------------------------------------------

MUNICIPIO_RIO_IBGE = "3304557"
CNPJ_PCRJ = "42498733000148"   # MUNICIPIO DE RIO DE JANEIRO (esfera M)


async def _consulta_retry(endpoint: str, params: dict, tentativas: int = 3) -> Optional[dict]:
    """_get_consulta com retry/backoff — o PNCP devolve timeout transitório sob volume."""
    for i in range(tentativas):
        j = await _get_consulta(endpoint, params)
        if j is not None:
            return j
        if i < tentativas - 1:
            await asyncio.sleep(20 * (i + 1))
    return None


def _simplificar_contrato_pcrj(it: dict) -> dict:
    """Mapeia /contratos (consulta v1) → shape da tabela pcrj_contratos."""
    org = it.get("orgaoEntidade") or {}
    uni = it.get("unidadeOrgao") or {}
    return {
        "numero_controle_pncp": it.get("numeroControlePNCP") or it.get("numeroControlePncpCompra"),
        "numero_compra": it.get("numeroControlePncpCompra"),
        "ano": it.get("anoContrato"),
        "orgao_cnpj": org.get("cnpj"),
        "orgao_nome": org.get("razaoSocial"),
        "unidade": uni.get("nomeUnidade"),
        "fornecedor_documento": it.get("niFornecedor"),
        "fornecedor_nome": it.get("nomeRazaoSocialFornecedor"),
        "tipo": (it.get("tipoContrato") or {}).get("nome"),
        "objeto": it.get("objetoContrato"),
        "valor_inicial": it.get("valorInicial"),
        "valor_global": it.get("valorGlobal"),
        "data_assinatura": it.get("dataAssinatura"),
        "vigencia_ini": it.get("dataVigenciaInicio"),
        "vigencia_fim": it.get("dataVigenciaFim"),
        "num_aditivos": it.get("numeroRetificacao") or 0,
        "fonte": "pncp",
    }


async def coletar_contratos_pcrj(data_ini: str, data_fim: str,
                                 cnpj_orgao: str = CNPJ_PCRJ) -> dict:
    """Contratos/empenhos do órgão municipal (datas AAAAMMDD).

    HONESTIDADE: se a 1ª página falhar, retorna verificado=False (INDISPONÍVEL ≠ 0).
    """
    itens: list[dict] = []
    pagina = 1
    while True:
        j = await _consulta_retry("/contratos", {
            "dataInicial": data_ini, "dataFinal": data_fim,
            "cnpjOrgao": cnpj_orgao, "pagina": pagina, "tamanhoPagina": 50})
        if j is None:
            if pagina == 1:
                return {"verificado": False, "itens": [], "motivo": "PNCP /contratos indisponível"}
            break  # páginas já coletadas valem; total pode estar incompleto
        data = j.get("data") or []
        itens.extend(_simplificar_contrato_pcrj(it) for it in data)
        if pagina >= (j.get("totalPaginas") or 1) or not data:
            break
        pagina += 1
        await asyncio.sleep(0.3)
    return {"verificado": True, "itens": itens, "motivo": None}


async def coletar_contratacoes_municipio_rio(data_ini: str, data_fim: str,
                                             modalidades: Optional[list[int]] = None) -> dict:
    """Contratações publicadas do MUNICÍPIO do Rio (uf=RJ + codigoMunicipioIbge).

    POR QUE por IBGE: descobre TODOS os órgãos municipais (secretarias, COMLURB,
    RioSaúde etc.) sem lista manual de CNPJs.
    """
    itens: list[dict] = []
    vistos: set[str] = set()
    falhas_pag1 = 0
    for mod in (modalidades or MODALIDADES_PADRAO):
        pagina = 1
        while True:
            j = await _consulta_retry("/contratacoes/publicacao", {
                "dataInicial": data_ini, "dataFinal": data_fim, "uf": "RJ",
                "codigoMunicipioIbge": MUNICIPIO_RIO_IBGE,
                "codigoModalidadeContratacao": mod,
                "pagina": pagina, "tamanhoPagina": 50})
            if j is None:
                if pagina == 1:
                    falhas_pag1 += 1
                break
            data = j.get("data") or []
            for it in data:
                cid = it.get("numeroControlePNCP")
                if cid and cid not in vistos:
                    vistos.add(cid)
                    itens.append(_simplificar_contratacao(it))
            if pagina >= (j.get("totalPaginas") or 1) or not data:
                break
            pagina += 1
            await asyncio.sleep(0.3)
    if falhas_pag1 == len(modalidades or MODALIDADES_PADRAO):
        return {"verificado": False, "itens": [], "motivo": "PNCP /contratacoes indisponível"}
    return {"verificado": True, "itens": itens, "motivo": None}


# ---------------------------------------------------------------------------
# Termos aditivos (api/pncp/v1) — o valor/prazo que o aditivo mudou
# ---------------------------------------------------------------------------

def _parse_termo(t: dict) -> dict:
    return {
        "sequencial_termo": t.get("sequencialTermoContrato"),
        "numero_termo": t.get("numeroTermoContrato"),
        "objeto": t.get("objetoTermoContrato"),
        "valor_acrescido": t.get("valorAcrescido"),
        "valor_global": t.get("valorGlobal"),
        "prazo_aditado_dias": t.get("prazoAditadoDias"),
        "vigencia_fim": t.get("dataVigenciaFim"),
        "qualif_acrescimo": t.get("qualificacaoAcrescimoSupressao"),
        "qualif_vigencia": t.get("qualificacaoVigencia"),
        "qualif_reajuste": t.get("qualificacaoReajuste"),
        "fundamento_legal": t.get("fundamentoLegal"),
    }


async def termos_contrato(cnpj: str, ano, seq) -> list[dict]:
    """Termos aditivos de um contrato (api/pncp/v1; 200=lista, 204=sem termos)."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{PNCP_BASE}/orgaos/{cnpj}/contratos/{ano}/{seq}/termos",
                            headers={"User-Agent": "JFN-Compliance/2.0"})
            if r.status_code != 200:
                return []
            return [_parse_termo(t) for t in (r.json() or [])]
    except Exception:
        return []


async def coletar_aditivos(con, numero_controle_pncp: str) -> int:
    """'CNPJ-2-SEQ/ANO' → grava termos em contrato_aditivo. Idempotente."""
    pr = _parse_id_pncp(numero_controle_pncp)
    if not pr:
        return 0
    cnpj, ano, seq = pr
    termos = await termos_contrato(cnpj, ano, seq)
    for row in termos:
        con.execute(
            """INSERT OR IGNORE INTO contrato_aditivo (numero_controle_pncp, sequencial_termo,
                 numero_termo, objeto, valor_acrescido, valor_global, prazo_aditado_dias,
                 vigencia_fim, qualif_acrescimo, qualif_vigencia, qualif_reajuste, fundamento_legal)
               VALUES (:ncp,:sequencial_termo,:numero_termo,:objeto,:valor_acrescido,:valor_global,
                 :prazo_aditado_dias,:vigencia_fim,:qualif_acrescimo,:qualif_vigencia,:qualif_reajuste,:fundamento_legal)""",
            {**row, "ncp": numero_controle_pncp})
    con.commit()
    return len(termos)


# ---------------------------------------------------------------------------
# Contratos ESTADUAIS + aditivos (PNCP) — alimenta o detector de aditivos e o art. 9
# ---------------------------------------------------------------------------

# Entes estaduais do RJ no PNCP (esfera E). A lista base cobre os grandes; em runtime
# unimos com o que o pncp_ente já conhece (cresce sozinho a cada coleta de resultados).
_ENTES_ESTADO_BASE = {
    "42498600000171": "ESTADO DO RIO DE JANEIRO",       # Executivo (todas as secretarias, por unidade)
    "28538734000148": "TRIBUNAL DE JUSTICA DO RJ",
    "31443526000170": "DEFENSORIA PUBLICA DO RJ",
    "28305936000140": "MINISTERIO PUBLICO DO RJ",
    "30051023000196": "TRIBUNAL DE CONTAS DO RJ",
    "33540014000157": "UNIVERSIDADE DO ESTADO DO RJ",   # UERJ
    "32855236000104": "SECRETARIA DE ESTADO DE POLICIA CIVIL",
}


def _entes_estado(con) -> list[str]:
    cnpjs = set(_ENTES_ESTADO_BASE)
    try:
        cnpjs |= {r[0] for r in con.execute("SELECT cnpj FROM pncp_ente WHERE esfera_id='E'")}
    except Exception:
        pass
    return sorted(c for c in cnpjs if c and len(c) == 14)


def _meses_iso(ano_ini: int, mes_ini: int, ano_fim: int, mes_fim: int):
    a, m = ano_ini, mes_ini
    while (a, m) <= (ano_fim, mes_fim):
        ult = 28
        for d in (31, 30, 29):
            try:
                date(a, m, d); ult = d; break
            except ValueError:
                continue
        yield f"{a}{m:02d}01", f"{a}{m:02d}{ult:02d}"
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)


def _upsert_contrato_estado(con, c: dict) -> None:
    c = {**c, "fonte": "pncp_estado"}
    cols = ["numero_controle_pncp", "numero_compra", "ano", "orgao_cnpj", "orgao_nome", "unidade",
            "fornecedor_documento", "fornecedor_nome", "tipo", "objeto", "valor_inicial",
            "valor_global", "data_assinatura", "vigencia_ini", "vigencia_fim", "num_aditivos", "fonte"]
    reg = {k: c.get(k) for k in cols}
    # não sobrescreve valor_global/num_aditivos já enriquecidos pelos termos (aditivos_checados=1)
    sets = ",".join(f"{k}=excluded.{k}" for k in cols
                    if k not in ("numero_controle_pncp", "valor_global", "num_aditivos"))
    con.execute(
        f"INSERT INTO pcrj_contratos ({','.join(cols)}) VALUES ({','.join(':'+k for k in cols)}) "
        f"ON CONFLICT(numero_controle_pncp) DO UPDATE SET {sets}", reg)


async def coletar_contratos_estado(con, ano_ini: int = 2021, mes_ini: int = 1,
                                   ano_fim: int | None = None, mes_fim: int | None = None,
                                   limite_termos: int = 4000, pausa: float = 0.3,
                                   so_aditivos: bool = False) -> dict:
    """Coleta contratos dos ENTES ESTADUAIS do RJ no PNCP (fonte='pncp_estado') e, para os que ainda
    não foram checados, busca os TERMOS ADITIVOS — grava em contrato_aditivo e atualiza valor_global +
    num_aditivos em pcrj_contratos (a variação real do valor, base do detector de aditivos). Serial e
    educado (pausas, backoff no _consulta_retry). Resumível: só re-checa aditivos onde falta.
    `so_aditivos=True` PULA a fase 1 (contratos) e roda só a fase 2 sobre os já coletados — desacopla
    a fase de aditivos da coleta de contratos (que o PNCP rate-limita depois de muitas chamadas)."""
    from compliance_agent.pcrj.gastos_db import init_schema
    init_schema(con)
    cols = {r[1] for r in con.execute("PRAGMA table_info(pcrj_contratos)")}
    if "aditivos_checados" not in cols:
        con.execute("ALTER TABLE pcrj_contratos ADD COLUMN aditivos_checados INTEGER DEFAULT 0")
        con.commit()
    hoje = date.today()
    ano_fim = ano_fim or hoje.year
    mes_fim = mes_fim or hoje.month
    tot = {"contratos": 0, "entes": 0, "aditivos_checados": 0, "termos": 0, "com_acrescimo": 0}

    # ── fase 1: contratos ──────────────────────────────────────────────────
    if not so_aditivos:
        for cnpj in _entes_estado(con):
            tot["entes"] += 1
            for d_ini, d_fim in _meses_iso(ano_ini, mes_ini, ano_fim, mes_fim):
                res = await coletar_contratos_pcrj(d_ini, d_fim, cnpj_orgao=cnpj)
                for c in res.get("itens", []):
                    if c.get("numero_controle_pncp"):
                        _upsert_contrato_estado(con, c)
                        tot["contratos"] += 1
                con.commit()
                await asyncio.sleep(pausa)

    # ── fase 2: termos aditivos (resumível) ────────────────────────────────
    pend = [r[0] for r in con.execute(
        "SELECT numero_controle_pncp FROM pcrj_contratos "
        "WHERE fonte='pncp_estado' AND COALESCE(aditivos_checados,0)=0 "
        "ORDER BY data_assinatura DESC LIMIT ?", (limite_termos,))]
    for ncp in pend:
        pr = _parse_id_pncp(ncp)
        if not pr:
            con.execute("UPDATE pcrj_contratos SET aditivos_checados=1 WHERE numero_controle_pncp=?", (ncp,))
            continue
        cnpj, ano, seq = pr
        termos = await termos_contrato(cnpj, ano, seq)
        acresc = 0.0
        vg_max = None
        for row in termos:
            con.execute(
                """INSERT OR IGNORE INTO contrato_aditivo (numero_controle_pncp, sequencial_termo,
                     numero_termo, objeto, valor_acrescido, valor_global, prazo_aditado_dias,
                     vigencia_fim, qualif_acrescimo, qualif_vigencia, qualif_reajuste, fundamento_legal)
                   VALUES (:ncp,:sequencial_termo,:numero_termo,:objeto,:valor_acrescido,:valor_global,
                     :prazo_aditado_dias,:vigencia_fim,:qualif_acrescimo,:qualif_vigencia,:qualif_reajuste,:fundamento_legal)""",
                {**row, "ncp": ncp})
            if row.get("valor_acrescido"):
                acresc += row["valor_acrescido"]
            if row.get("valor_global"):
                vg_max = max(vg_max or 0, row["valor_global"])
        # valor global efetivo: PRIORIZA inicial + Σacréscimo (confiável); o valorGlobal do termo
        # às vezes vem com lixo (< inicial) — só o usa se for sanamente MAIOR que o inicial.
        con.execute(
            """UPDATE pcrj_contratos SET num_aditivos=?, aditivos_checados=1,
                 valor_global=CASE
                    WHEN ?>0 THEN COALESCE(valor_inicial,0)+?
                    WHEN ?>COALESCE(valor_inicial,0) THEN ?
                    ELSE valor_global END
               WHERE numero_controle_pncp=?""",
            (len(termos), acresc, acresc, vg_max or 0, vg_max or 0, ncp))
        tot["aditivos_checados"] += 1
        tot["termos"] += len(termos)
        if acresc > 0 or (vg_max or 0) > 0:
            tot["com_acrescimo"] += 1
        if tot["aditivos_checados"] % 100 == 0:
            con.commit()
            print(f"[contratos-estado] aditivos {tot['aditivos_checados']}/{len(pend)} · "
                  f"{tot['com_acrescimo']} com acréscimo", flush=True)
        await asyncio.sleep(pausa)
    con.commit()
    return tot


if __name__ == "__main__":
    import json
    import sqlite3
    import sys
    args = sys.argv[1:]
    con = sqlite3.connect("data/compliance.db", timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    if "--aditivos" in args:
        # SÓ fase 2: termos aditivos sobre os contratos estaduais já coletados (desacopla do rate-limit)
        lim = next((int(a) for a in args if a.isdigit()), 8000)
        r = asyncio.run(coletar_contratos_estado(con, so_aditivos=True, limite_termos=lim))
    elif "--incremental" in args:
        # timer diário: contratos dos 2 meses recentes + fatia de termos p/ completar a cobertura
        hoje = date.today()
        ai, mi = (hoje.year - 1, 12) if hoje.month == 1 else (hoje.year, hoje.month - 1)
        r = asyncio.run(coletar_contratos_estado(con, ano_ini=ai, mes_ini=mi,
                                                 ano_fim=hoje.year, mes_fim=hoje.month, limite_termos=800))
    else:
        ai = int(args[0]) if args and args[0].isdigit() else 2021
        lim = next((int(a) for a in args[1:] if a.isdigit()), 4000)
        r = asyncio.run(coletar_contratos_estado(con, ano_ini=ai, limite_termos=lim))
    con.close()
    print(json.dumps(r, ensure_ascii=False), flush=True)
