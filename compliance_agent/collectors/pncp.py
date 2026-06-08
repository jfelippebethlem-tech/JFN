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

import httpx

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
    except Exception:
        pass
    return None


async def _get_consulta(endpoint: str, params: dict) -> Optional[dict]:
    """GET na API de CONSULTA do PNCP (sem login). Retorna o JSON ou None."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{CONSULTA_BASE}{endpoint}", params=params,
                                 headers={"User-Agent": "JFN-Compliance/2.0"})
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
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
    except Exception:
        pass
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
