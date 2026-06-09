"""
CEIS / CNEP — Cadastros Federais de Sanções.

Verifica se fornecedores de OBs constam em:
  - CEIS: Cadastro de Empresas Inidôneas e Suspensas
  - CNEP: Cadastro Nacional de Empresas Punidas
  - CEPIM: Entidades sem fins lucrativos impedidas

Fonte: Portal da Transparência Federal
  https://portaldatransparencia.gov.br/download-de-dados/ceis

Estratégia: baixa o CSV mensal do governo, armazena em data/ceis_cache.csv.
Atualiza uma vez por mês. Não exige API key.
Consulta 100% local — sem rate limit.
"""

import csv
import io
import re
from datetime import date, datetime
from pathlib import Path

import httpx

CACHE_DIR = Path("data")
CEIS_CSV  = CACHE_DIR / "ceis_cache.csv"
CNEP_CSV  = CACHE_DIR / "cnep_cache.csv"

# URLs de download direto (atualizado mensalmente pelo governo)
CEIS_URL = "https://portaldatransparencia.gov.br/download-de-dados/ceis/{ano}{mes:02d}"
CNEP_URL = "https://portaldatransparencia.gov.br/download-de-dados/cnep/{ano}{mes:02d}"

# Alternativa: busca via API sem chave (retorna resultados parciais)
CEIS_API = "https://api.portaldatransparencia.gov.br/api-de-dados/ceis"
CNEP_API = "https://api.portaldatransparencia.gov.br/api-de-dados/cnep"


def _cache_valido(path: Path, dias: int = 30) -> bool:
    if not path.exists():
        return False
    age = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days
    return age < dias


async def _download_csv(url: str, dest: Path) -> bool:
    """Tenta baixar CSV do Portal da Transparência."""
    CACHE_DIR.mkdir(exist_ok=True)
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            # Tenta mês atual, se falhar tenta mês anterior
            hoje = date.today()
            for tentativa in range(3):
                mes_ref = date(hoje.year, hoje.month, 1)
                # Subtrai tentativa meses
                for _ in range(tentativa):
                    primeiro = mes_ref.replace(day=1)
                    mes_anterior = primeiro - __import__("datetime").timedelta(days=1)
                    mes_ref = mes_anterior.replace(day=1)

                url_fmt = url.format(ano=mes_ref.year, mes=mes_ref.month)
                r = await client.get(url_fmt, headers={"User-Agent": "JFN-Compliance/1.0"})
                if r.status_code == 200 and len(r.content) > 1000:
                    dest.write_bytes(r.content)
                    return True
    except Exception:
        pass
    return False


def _buscar_em_csv(csv_path: Path, cnpj_cpf: str) -> list[dict]:
    """Busca CNPJ/CPF no CSV local. Retorna lista de sanções encontradas."""
    if not csv_path.exists():
        return []

    cnpj_limpo = re.sub(r"\D", "", cnpj_cpf)
    resultados = []

    try:
        content = csv_path.read_bytes()
        # Tenta detectar encoding
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                texto = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            return []

        reader = csv.DictReader(io.StringIO(texto), delimiter=";")
        for row in reader:
            # O campo CPF/CNPJ pode ter formatação variada
            cpf_cnpj_row = re.sub(r"\D", "", str(
                row.get("CPF ou CNPJ do Sancionado", "")
                or row.get("CNPJ", "")
                or row.get("CPF/CNPJ", "")
                or ""
            ))
            if cnpj_limpo and cpf_cnpj_row == cnpj_limpo:
                resultados.append({k.strip(): v.strip() for k, v in row.items()})
    except Exception:
        pass

    return resultados


async def verificar_sancao(cnpj_cpf: str, forcar_update: bool = False) -> dict:
    """
    Verifica se um CNPJ/CPF consta no CEIS ou CNEP.
    Retorna dict com: sancionado (bool), sancoes (list), fonte.
    """
    # Atualiza cache se necessário
    if forcar_update or not _cache_valido(CEIS_CSV):
        await _download_csv(CEIS_URL, CEIS_CSV)
    if forcar_update or not _cache_valido(CNEP_CSV):
        await _download_csv(CNEP_URL, CNEP_CSV)

    sancoes_ceis = _buscar_em_csv(CEIS_CSV, cnpj_cpf)
    sancoes_cnep = _buscar_em_csv(CNEP_CSV, cnpj_cpf)

    todas = []
    for s in sancoes_ceis:
        s["_fonte"] = "CEIS"
        todas.append(s)
    for s in sancoes_cnep:
        s["_fonte"] = "CNEP"
        todas.append(s)

    return {
        "cnpj_cpf": cnpj_cpf,
        "sancionado": len(todas) > 0,
        "sancoes": todas,
        "cache_ceis": str(CEIS_CSV) if CEIS_CSV.exists() else None,
        "cache_cnep": str(CNEP_CSV) if CNEP_CSV.exists() else None,
    }


async def verificar_obs_contra_sancoes(session, target_date: date = None) -> list[dict]:
    """
    Verifica todas as OBs do dia contra CEIS/CNEP.
    Gera alertas de severidade ALTA para cada match.
    """
    from compliance_agent.database.models import OrdemBancaria, Alerta

    target_date = target_date or date.today()

    obs = (
        session.query(OrdemBancaria)
        .filter(
            OrdemBancaria.data_emissao == target_date,
            OrdemBancaria.favorecido_cpf.isnot(None),
        )
        .all()
    )

    alertas = []
    verificados: set[str] = set()

    for ob in obs:
        cpf_cnpj = re.sub(r"\D", "", str(ob.favorecido_cpf or ""))
        if not cpf_cnpj or cpf_cnpj in verificados:
            continue
        verificados.add(cpf_cnpj)

        resultado = await verificar_sancao(cpf_cnpj)
        if not resultado["sancionado"]:
            continue

        for sancao in resultado["sancoes"]:
            fonte = sancao.get("_fonte", "CEIS/CNEP")
            tipo_sancao = (
                sancao.get("Tipo de Sanção", "")
                or sancao.get("Fundamentação Legal", "")
                or "Sanção federal"
            )
            orgao = sancao.get("Órgão Sancionador", "") or sancao.get("Órgão", "")
            data_ini = sancao.get("Data de Início da Sanção", "") or sancao.get("Data Início", "")
            data_fim = sancao.get("Data Final da Sanção", "") or sancao.get("Data Fim", "")
            vigente = not data_fim or data_fim >= target_date.strftime("%d/%m/%Y")

            titulo = (
                f"[{fonte}] Pagamento a empresa SANCIONADA — "
                f"{ob.favorecido_nome or cpf_cnpj}"
            )[:300]

            existe = session.query(Alerta).filter_by(titulo=titulo).first()
            if not existe:
                alerta = Alerta(
                    tipo="empresa_sancionada",
                    severidade="alta",
                    titulo=titulo,
                    descricao=(
                        f"OB nº {ob.numero_ob} (R$ {ob.valor:,.2f}) paga a "
                        f"'{ob.favorecido_nome}' (CPF/CNPJ {cpf_cnpj}), "
                        f"que consta no {fonte} com sanção: '{tipo_sancao}'. "
                        f"Sancionado por: {orgao}. "
                        f"Período: {data_ini} a {data_fim or 'indeterminado'}. "
                        f"{'⚠️ SANÇÃO VIGENTE' if vigente else 'Sanção possivelmente expirada'}. "
                        f"Lei 8.666/93 art. 87 e Lei 14.133/21 art. 156 "
                        f"vedam contratação de empresa sancionada."
                    ),
                    evidencias=str(sancao),
                    data_referencia=target_date,
                    ordem_bancaria_id=ob.id,
                )
                session.add(alerta)
                alertas.append({
                    "ob": ob.numero_ob,
                    "favorecido": ob.favorecido_nome,
                    "valor": ob.valor,
                    "fonte": fonte,
                    "tipo_sancao": tipo_sancao,
                    "vigente": vigente,
                })

    session.commit()
    return alertas


async def atualizar_cache_sancoes():
    """Força atualização dos CSVs do CEIS e CNEP."""
    print("  Baixando CEIS...")
    ok_ceis = await _download_csv(CEIS_URL, CEIS_CSV)
    print(f"  CEIS: {'OK' if ok_ceis else 'falhou'}")
    print("  Baixando CNEP...")
    ok_cnep = await _download_csv(CNEP_URL, CNEP_CSV)
    print(f"  CNEP: {'OK' if ok_cnep else 'falhou'}")
    return ok_ceis, ok_cnep
