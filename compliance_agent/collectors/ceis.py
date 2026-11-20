"""
CEIS / CNEP / CEPIM — Cadastros Federais de Sanções (Portal da Transparência / CGU).

  - CEIS: Cadastro de Empresas Inidôneas e Suspensas
  - CNEP: Cadastro Nacional de Empresas Punidas
  - CEPIM: Entidades sem fins lucrativos impedidas

Fonte: **API do Portal da Transparência** (requer chave gratuita).
  Header obrigatório: `chave-api-dados: <chave>`.
  Chave em `PORTAL_TRANSPARENCIA_KEY` (ou `TRANSPARENCIA_API_KEY`).
  Filtro por documento: parâmetro **`codigoSancionado`** (NÃO `cnpjSancionado`/`cpfCnpj`,
  que a API IGNORA → devolviam a página inteira não-filtrada = falso-positivo/negativo).

HONESTIDADE (regra-mãe): se a consulta não puder ser feita (sem chave, rede, HTTP≠200),
retorna `verificado=False` + `motivo` (estado INDISPONÍVEL) — **nunca** "limpo" silencioso.
INDISPONÍVEL ≠ 0. O download keyless do CSV mensal foi DESCONTINUADO pela CGU (URL 405).
"""

import asyncio
import json
import re
import time
from datetime import date, datetime

import httpx
from compliance_agent.collectors.arquivos import dir_dados, gravar_atomico
from compliance_agent.collectors.portal_transparencia import chave as chave_portal
from compliance_agent.collectors.portal_transparencia import consultar
from compliance_agent.reporting.intel_base import moeda

CACHE_DIR = dir_dados()
_CACHE_FILE = CACHE_DIR / "sancoes_cache.json"
_CACHE_TTL = 7 * 86400  # 7 dias

# (endpoint, rótulo, nome_do_param_de_filtro, só_cnpj?): o param de filtro VARIA por endpoint —
# CEIS/CNEP usam `codigoSancionado`; CEPIM usa `cnpjSancionado` (e só aceita CNPJ). Usar o errado
# faz a API IGNORAR o filtro e devolver a página inteira (falso-positivo). Verificado no swagger.
_ENDPOINTS = [
    ("ceis", "CEIS", "codigoSancionado", False),
    ("cnep", "CNEP", "codigoSancionado", False),
    ("cepim", "CEPIM", "cnpjSancionado", True),
]

_cache: dict | None = None


def _carrega_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_CACHE_FILE.read_text("utf-8")) if _CACHE_FILE.exists() else {}
        except Exception:
            _cache = {}
    return _cache


def _salva_cache() -> None:
    try:
        gravar_atomico(_CACHE_FILE, json.dumps(_cache, ensure_ascii=False))
    except (OSError, TypeError):
        pass


def _nome_de(obj) -> str:
    if isinstance(obj, dict):
        return obj.get("nome") or obj.get("razaoSocial") or obj.get("descricao") or ""
    return str(obj or "")


def _normalizar(s: dict, tipo: str) -> dict:
    """Normaliza um registro da API para campos estáveis usados por alertas/relatórios."""
    pessoa = s.get("pessoa") if isinstance(s.get("pessoa"), dict) else {}
    return {
        "_fonte": tipo,
        "nome": _nome_de(pessoa) or _nome_de(s.get("nomeInformado")) or "",
        "cpf_cnpj": re.sub(r"\D", "", str(pessoa.get("cnpjFormatado") or pessoa.get("cpfFormatado")
                                          or pessoa.get("numeroInscricaoSocial") or "")),
        "tipo_sancao": (_nome_de(s.get("tipoSancao")) or s.get("tipoSancao", {}).get("descricaoResumida", "")
                        if isinstance(s.get("tipoSancao"), dict) else _nome_de(s.get("tipoSancao"))),
        "orgao": _nome_de(s.get("orgaoSancionador")),
        "fundamentacao": s.get("fundamentacaoLegal") or s.get("textoPublicacao") or "",
        "data_inicio": s.get("dataInicioSancao") or s.get("dataPublicacaoSancao") or "",
        "data_fim": s.get("dataFimSancao") or s.get("dataFinalSancao") or "",
        "_raw_id": s.get("id"),
    }


async def verificar_sancao(cnpj_cpf: str, forcar_update: bool = False) -> dict:
    """
    Verifica CEIS/CNEP/CEPIM para um CNPJ/CPF via API do Portal da Transparência.

    Retorna (honesto):
      {cnpj_cpf, verificado: bool, sancionado: bool|None, sancoes: [...], motivo, fonte, coletado_em}
    - verificado=True  → consulta feita; `sancionado` é confiável (True/False).
    - verificado=False → INDISPONÍVEL (sem chave / rede / HTTP); `sancionado=None`. NUNCA tratar como "limpo".
    """
    codigo = re.sub(r"\D", "", cnpj_cpf or "")
    base = {"cnpj_cpf": cnpj_cpf, "fonte": "CEIS/CNEP/CEPIM (Portal da Transparência/CGU)",
            "coletado_em": datetime.now().isoformat(timespec="seconds")}
    if len(codigo) not in (11, 14):
        return {**base, "verificado": False, "sancionado": None, "sancoes": [],
                "motivo": f"documento inválido: {cnpj_cpf!r}"}

    chave = chave_portal()
    if not chave:
        return {**base, "verificado": False, "sancionado": None, "sancoes": [],
                "motivo": "sem chave — defina PORTAL_TRANSPARENCIA_KEY (ou TRANSPARENCIA_API_KEY)"}

    cache = _carrega_cache()
    ent = cache.get(codigo)
    if ent and not forcar_update and (time.time() - ent.get("_ts", 0)) < _CACHE_TTL:
        return {**base, **{k: v for k, v in ent.items() if k != "_ts"}, "_cache": True}

    todas: list[dict] = []
    erros: list[str] = []
    consultados = 0
    async with httpx.AsyncClient() as client:
        for endpoint, tipo, param, so_cnpj in _ENDPOINTS:
            if so_cnpj and len(codigo) != 14:
                continue  # CEPIM só aceita CNPJ (entidades) — pular p/ CPF
            if consultados:
                await asyncio.sleep(0.3)  # respeita o rate-limit do Portal
            consultados += 1
            ok, lista, erro = await consultar(client, endpoint, {param: codigo}, chave)
            if ok:
                todas += [_normalizar(s, tipo) for s in lista]
            else:
                erros.append(f"{tipo}: {erro}")

    if erros and not todas:
        # algum cadastro não respondeu e nenhum acusou: "não sancionado" seria afirmar sobre o que não foi
        # lido (antes: verificado=True com motivo "parcial", gravado 7 dias no cache). Sanção ACHADA em
        # qualquer cadastro, ao contrário, é prova — por isso o parcial com achado segue verificado.
        return {**base, "verificado": False, "sancionado": None, "sancoes": [],
                "motivo": "; ".join(erros)}

    resultado = {"verificado": True, "sancionado": len(todas) > 0, "sancoes": todas,
                 "motivo": ("parcial: " + "; ".join(erros)) if erros else ""}
    cache[codigo] = {**resultado, "_ts": time.time()}
    _salva_cache()
    return {**base, **resultado, "_cache": False}


def _vigente(data_fim: str, ref: date) -> bool:
    """Sanção sem fim, ou com fim em/apos `ref`. O Portal manda 'dd/mm/aaaa'; a comparação antiga era de
    TEXTO nesse formato ('05/01/2030' < '20/11/2026'), ou seja, pelo dia do mês. Fim ilegível → vigente
    (não declarar expirada o que não se leu)."""
    if not data_fim:
        return True
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(data_fim.strip()[:10], fmt).date() >= ref
        except ValueError:
            continue
    return True


async def verificar_obs_contra_sancoes(session, target_date: date = None) -> list[dict]:
    """
    Verifica as OBs do dia contra CEIS/CNEP/CEPIM. Gera alertas ALTA para cada match VERIFICADO.
    (Não gera alerta quando a verificação fica INDISPONÍVEL — honestidade: não inventa nem zera.)
    """
    from compliance_agent.database.models import Alerta, OrdemBancaria

    target_date = target_date or date.today()
    obs = (session.query(OrdemBancaria)
           .filter(OrdemBancaria.data_emissao == target_date,
                   OrdemBancaria.favorecido_cpf.isnot(None))
           .all())

    alertas: list[dict] = []
    verificados: set[str] = set()
    for ob in obs:
        cpf_cnpj = re.sub(r"\D", "", str(ob.favorecido_cpf or ""))
        if not cpf_cnpj or cpf_cnpj in verificados:
            continue
        verificados.add(cpf_cnpj)

        resultado = await verificar_sancao(cpf_cnpj)
        if not resultado.get("verificado") or not resultado.get("sancionado"):
            continue

        for sancao in resultado["sancoes"]:
            fonte = sancao.get("_fonte", "CEIS/CNEP")
            tipo_sancao = sancao.get("tipo_sancao") or sancao.get("fundamentacao") or "Sanção federal"
            orgao = sancao.get("orgao", "")
            data_ini = sancao.get("data_inicio", "")
            data_fim = sancao.get("data_fim", "")
            vigente = _vigente(data_fim, target_date)
            titulo = (f"[{fonte}] Pagamento a empresa SANCIONADA — "
                      f"{ob.favorecido_nome or cpf_cnpj}")[:300]
            if session.query(Alerta).filter_by(titulo=titulo).first():
                continue
            session.add(Alerta(
                tipo="empresa_sancionada", severidade="alta", titulo=titulo,
                descricao=(f"OB nº {ob.numero_ob} (R$ {moeda(ob.valor)}) paga a "
                           f"'{ob.favorecido_nome}' (CPF/CNPJ {cpf_cnpj}), que consta no {fonte} "
                           f"com sanção: '{tipo_sancao}'. Sancionado por: {orgao}. "
                           f"Período: {data_ini} a {data_fim or 'indeterminado'}. "
                           f"{'⚠️ SANÇÃO VIGENTE' if vigente else 'Sanção possivelmente expirada'}. "
                           f"Lei 8.666/93 art. 87 e Lei 14.133/21 art. 156 vedam contratar sancionada."),
                evidencias=str(sancao), data_referencia=target_date, ordem_bancaria_id=ob.id))
            alertas.append({"ob": ob.numero_ob, "favorecido": ob.favorecido_nome, "valor": ob.valor,
                            "fonte": fonte, "tipo_sancao": tipo_sancao, "vigente": vigente})

    session.commit()
    return alertas


async def atualizar_cache_sancoes():
    """Probe de saúde da API de sanções (a verificação agora é por API, não por CSV mensal).

    Mantido p/ compatibilidade com a manutenção: confirma que a chave responde. Retorna (ok, ok)."""
    chave = chave_portal()
    if not chave:
        print("  Sanções: SEM CHAVE (defina PORTAL_TRANSPARENCIA_KEY) — verificação INDISPONÍVEL")
        return False, False
    try:
        async with httpx.AsyncClient() as client:
            # faltava o argumento `param`: o TypeError caía no except e o probe acusava falha SEMPRE
            ok, _, erro = await consultar(client, "ceis", {"codigoSancionado": "00000000000191"}, chave)  # BB (probe)
        print(f"  Sanções API: {'OK' if ok else 'falhou — ' + erro}")
        return ok, ok
    except Exception as exc:  # noqa: BLE001
        print(f"  Sanções API: erro {exc}")
        return False, False
