"""
Enriquecimento automático de CNPJ via BrasilAPI (gratuita, sem auth).

Para cada OB coletada com favorecido sendo pessoa jurídica:
  - Busca dados completos da empresa (razão social, situação, abertura, sócios)
  - Salva na tabela `empresas` e `empresa_socios`
  - Detecta automaticamente flags de risco:
      * Empresa SUSPENSA ou BAIXADA continuando a receber pagamentos
      * Empresa aberta há menos de 6 meses
      * Endereço residencial (tipo "CASA", "APTO")
      * Sócio que é servidor público no DOERJ
"""

import asyncio
import re
from datetime import date, datetime
from typing import Optional

import httpx

BRASILAPI = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
RECEITAWS  = "https://www.receitaws.com.br/v1/cnpj/{cnpj}"  # fallback


def _is_cnpj(s: str) -> bool:
    return bool(s and re.fullmatch(r"\d{14}", re.sub(r"\D", "", str(s))))


async def _fetch_cnpj(cnpj: str) -> Optional[dict]:
    cnpj_digits = re.sub(r"\D", "", cnpj)
    if len(cnpj_digits) != 14:
        return None

    for url_template in [BRASILAPI, RECEITAWS]:
        url = url_template.format(cnpj=cnpj_digits)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(url, headers={"User-Agent": "JFN-Compliance/1.0"})
                if r.status_code == 200:
                    return r.json()
        except Exception:
            continue
    return None


def _parse_date(s) -> Optional[date]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(s)[:10], fmt).date()
        except (ValueError, TypeError):
            continue
    return None


async def enriquecer_ob_cnpj(session, ob) -> dict:
    """
    Busca dados do CNPJ do favorecido de uma OB e salva no banco.
    Retorna dict com flags de risco detectados.
    """
    from compliance_agent.database.models import Empresa, EmpresaSocio, Pessoa

    cnpj = re.sub(r"\D", "", str(ob.favorecido_cpf or ""))
    if not _is_cnpj(cnpj):
        return {}

    # Busca na API
    data = await _fetch_cnpj(cnpj)
    if not data:
        return {}

    # Upsert empresa
    empresa = session.query(Empresa).filter_by(cnpj=cnpj).first()
    if not empresa:
        empresa = Empresa(cnpj=cnpj)
        session.add(empresa)

    situacao = (
        data.get("descricao_situacao_cadastral")
        or data.get("situacao")
        or ""
    ).upper()

    abertura_raw = data.get("data_inicio_atividade") or data.get("abertura")
    data_abertura = _parse_date(abertura_raw)

    empresa.razao_social    = (data.get("razao_social") or data.get("nome") or "")[:300]
    empresa.nome_fantasia   = (data.get("nome_fantasia") or "")[:300]
    empresa.situacao        = situacao[:50]
    empresa.data_abertura   = data_abertura
    empresa.municipio       = (data.get("municipio") or "")[:100]
    empresa.uf              = (data.get("uf") or "")[:2]
    empresa.cep             = re.sub(r"\D", "", str(data.get("cep") or ""))[:8]
    empresa.atividade_princ = str(data.get("cnae_fiscal_descricao") or data.get("atividade_principal", [{}])[0].get("text","") or "")[:200]
    try:  # capital vem numérico na BrasilAPI e string na ReceitaWS ("1.000,00")
        cap = data.get("capital_social")
        if isinstance(cap, str):
            cap = cap.replace(".", "").replace(",", ".")
        empresa.capital_social = float(cap) if cap not in (None, "") else None
    except (TypeError, ValueError):
        pass
    empresa.porte        = str(data.get("porte") or "")[:50]
    empresa.natureza_jur = str(data.get("natureza_juridica") or "")[:100]
    empresa.updated_at   = datetime.utcnow()
    session.flush()  # garante empresa.id ANTES dos sócios (senão NOT NULL em empresa_socios)

    # Sócios (quadro societário)
    qsa = data.get("qsa") or data.get("socios") or []
    for socio_data in qsa:
        nome_socio = socio_data.get("nome_socio") or socio_data.get("nome") or ""
        cpf_socio  = re.sub(r"\D", "", str(socio_data.get("cpf_cnpj_socio") or socio_data.get("cpf") or ""))[:14]
        qualif     = socio_data.get("qualificacao_socio") or socio_data.get("qual") or ""

        existing = session.query(EmpresaSocio).filter_by(
            empresa_id=empresa.id, cpf_cnpj=cpf_socio or nome_socio[:14]
        ).first() if empresa.id else None

        if not existing:
            pessoa = session.query(Pessoa).filter_by(cpf=cpf_socio).first() if cpf_socio else None
            socio = EmpresaSocio(
                empresa_id=empresa.id,
                pessoa_id=pessoa.id if pessoa else None,
                cpf_cnpj=cpf_socio or "",
                nome=nome_socio[:200],
                qualific=str(qualif)[:100],
            )
            session.add(socio)

    session.commit()

    # ── Detecta flags de risco ──────────────────────────────────────────────
    flags = []
    ob_valor = ob.valor or 0

    if "INAPT" in situacao or "BAIXAD" in situacao or "SUSPEND" in situacao:
        flags.append({
            "tipo": "empresa_irregular",
            "severidade": "alta",
            "descricao": (
                f"Empresa {empresa.razao_social} (CNPJ {cnpj}) está com situação "
                f"'{situacao}' na Receita Federal e recebeu OB nº {ob.numero_ob} "
                f"de R$ {ob_valor:,.2f}. Pagamento a empresa irregular é vedado."
            ),
        })

    if data_abertura and ob.data_emissao:
        dias = (ob.data_emissao - data_abertura).days
        if 0 <= dias < 180:
            flags.append({
                "tipo": "empresa_nova",
                "severidade": "alta",
                "descricao": (
                    f"{empresa.razao_social} foi aberta há apenas {dias} dias "
                    f"({data_abertura}) e já recebeu R$ {ob_valor:,.2f} via OB {ob.numero_ob}."
                ),
            })

    logradouro = str(data.get("logradouro") or data.get("tipo_logradouro") or "").upper()
    complemento = str(data.get("complemento") or "").upper()
    if any(t in complemento for t in ["APTO", "AP ", "CASA", "BLOCO", "COND."]):
        if ob_valor > 30_000:
            flags.append({
                "tipo": "endereco_residencial",
                "severidade": "média",
                "descricao": (
                    f"{empresa.razao_social} tem endereço residencial "
                    f"({logradouro} {complemento}) e recebeu R$ {ob_valor:,.2f}."
                ),
            })

    return {"empresa": empresa.razao_social, "situacao": situacao, "flags": flags}


async def enriquecer_obs_do_dia(session, target_date: date = None,
                                cap: int = 60) -> list[dict]:
    """
    Enriquece OBs recentes cujo favorecido ainda NÃO está em `empresas`.

    Não filtra por ``data_emissao == hoje``: a coleta TFE tem lag de semanas,
    então "as OBs de hoje" é um conjunto quase sempre VAZIO (foi por isso que
    a tabela `empresas` ficou meses com 1 linha). Pega as maiores OBs recentes
    sem cadastro, limitado a ``cap`` favorecidos por rodada (gentileza com a
    BrasilAPI, que é grátis).
    """
    from compliance_agent.database.models import Empresa, OrdemBancaria, Alerta

    target_date = target_date or date.today()
    ja_cadastrados = {c for (c,) in session.query(Empresa.cnpj).all()}
    q = (
        session.query(OrdemBancaria)
        .filter(OrdemBancaria.favorecido_cpf.isnot(None),
                OrdemBancaria.valor.isnot(None))
        .order_by(OrdemBancaria.data_emissao.desc(),
                  OrdemBancaria.valor.desc())
        .limit(5000)
    )
    obs, vistos = [], set()
    for ob in q:
        cnpj = re.sub(r"\D", "", str(ob.favorecido_cpf or ""))
        if len(cnpj) != 14 or cnpj in ja_cadastrados or cnpj in vistos:
            continue
        vistos.add(cnpj)
        obs.append(ob)
        if len(obs) >= cap:
            break

    todos_flags = []
    for ob in obs:
        if not _is_cnpj(ob.favorecido_cpf or ""):
            continue
        try:
            resultado = await enriquecer_ob_cnpj(session, ob)
            for flag in resultado.get("flags", []):
                # Salva alerta no banco
                titulo = flag["descricao"][:300]
                existe = session.query(Alerta).filter_by(titulo=titulo).first()
                if not existe:
                    alerta = Alerta(
                        tipo=flag["tipo"],
                        severidade=flag["severidade"],
                        titulo=titulo,
                        descricao=flag["descricao"],
                        data_referencia=target_date,
                        ordem_bancaria_id=ob.id,
                    )
                    session.add(alerta)
                    todos_flags.append(flag)
            await asyncio.sleep(0.5)  # respeita rate limit da API
        except Exception:
            continue

    session.commit()
    return todos_flags
