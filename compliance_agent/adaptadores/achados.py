# -*- coding: utf-8 -*-
"""Adaptador das três gerações de detectores para o contrato único `dominio.achado` — O5.2, em SOMBRA.

Converte a saída que JÁ EXISTE em `Achado` sem mudar o que cada geração grava hoje (`alertas`, `achados.db`, os
caches de `cruzamentos_intel`): só LÊ. `alertas` passará a visão de compatibilidade depois (O5.3+).

  geração 1 · motor de regras e perícias que gravam em `alertas` (rules/engine.py, emendas/pericia.py D1–D6,
              pcrj/pericia_gastos.py D7–D12)                                       → `de_alerta(linha)`
  geração 2 · framework `compliance_agent/detectores/` (ResultadoDetector; tabelas achado_certame,
              achado_detector, achado_execucao de achados.db)                     → `de_resultado` / `de_achado_db`
  geração 3 · `cruzamentos_intel` (itens dos caches data/cache/*.json)            → `de_intel(nome, item)`

Honestidade da conversão:
  · status legado `confirmado`/`descartado` de `alertas` NÃO vira decisão: a tabela não tem autor. Vai a
    `em_revisao` com o status legado no resultado (O5.5 trata os 58 mil descartes sem autor);
  · `confirmado` de detector é "a regra disparou" (INDICIO, triagem), não confirmação humana; `descartado` é
    AUSENTE (consultou, não consta); `nao_avaliavel` é INDISPONIVEL — nunca zero;
  · título de `alertas` que nenhuma regra atual produz (zumbi de versão antiga) vai à entrada-agregado do tipo, com
    `titulo_sem_regra_atual` no resultado; tipo sem entrada no registro vira `nao_registrado.<tipo>` (contado).
  · `entradas_hash` é o sha256 do que a linha registrou como entrada (nunca o carimbo de hora): reler a mesma linha
    dá o mesmo hash — é o que `tools/reproduzir_achado.py` confere.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from compliance_agent.dominio.achado import Achado, ExecucaoRegra, Fato, Papel, StatusAchado, hash_entradas
from compliance_agent.dominio.estados import EstadoSaida
from compliance_agent.qualidade import detectores as registro

REPO = Path(__file__).resolve().parents[2]

# ── geração 1: tipo (+ prefixo do título) de `alertas` → id do registro ──
_POR_TITULO = (
    ("acumulacao", "Possível acúmulo ilegal", "rules.acumulo_cargo"),
    ("acumulacao", "CPF em múltiplas fontes", "rules.cpf_duplicado_fontes"),
    ("acumulacao", "Emprego múltiplo a verificar", "rules.emprego_multiplo_orgaos"),
    ("fracionamento", "Possível fracionamento", "rules.fracionamento_contrato"),
    ("fracionamento", "Fracionamento OB", "rules.ob_fracionamento"),
    ("nepotismo", "Empresa possivelmente residencial", "rules.empresa_mesmo_cep_servidor"),
    ("direcionamento", "Empresa nova com contrato", "rules.cnpj_abertura_recente_contrato"),
    ("direcionamento", "Favorecido em", "rules.ob_favorecido_multiplas_ugs"),
    ("direcionamento", "OB para empresa nova", "rules.ob_empresa_nova"),
)
_POR_TIPO = {  # tipo de uma regra só, ou agregado quando o título não casa
    "acumulacao": "rules.acumulacao", "fantasma": "rules.funcionario_fantasma",
    "enriquecimento": "rules.remuneracao_acima_teto", "fracionamento": "rules.engine",
    "nepotismo": "rules.empresa_parente", "direcionamento": "rules.engine",
    "ob_sem_processo": "rules.ob_sem_processo_sei", "ob_valor_atipico": "rules.ob_valor_redondo",
    "doerj_anomalia": "rules.ob_favorecido_doerj_cruzado",
}
_RX_EMENDAS = re.compile(r"^emendas_d(\d+)_")
_RX_PCRJ = re.compile(r"^pcrj_(d\d+_\w+)$")


def regra_do_alerta(tipo: str, titulo: str | None) -> tuple[str, bool]:
    """(id do registro, título_sem_regra_atual)."""
    reg = registro.carregar()
    for t, prefixo, rid in _POR_TITULO:
        if tipo == t and str(titulo or "").startswith(prefixo):
            return rid, False
    if m := _RX_EMENDAS.match(tipo or ""):
        return f"emendas.D{m.group(1)}", False
    if m := _RX_PCRJ.match(tipo or ""):
        rid = f"pcrj.{m.group(1)}"
        return (rid, False) if rid in reg else (f"nao_registrado.{tipo}", False)
    if tipo in _POR_TIPO:
        return _POR_TIPO[tipo], tipo in {t for t, _, _ in _POR_TITULO}
    return f"nao_registrado.{tipo}", False


# ── geração 2: código do detector → id do registro (lido do `id = "…"` de cada classe, sem importar o pacote) ──
_EXTRA_DET = {"C1": "det.CFachada", "C2": "det.CFachada", "C3/C5": "det.CFachada", "C3-5": "det.CFachada",
              "C4": "det.CFachada", "EST-VALOR-EXCEDIDO": "est.valor_excedido", "EST-ADITIVO-TETO": "est.aditivo_teto"}


@lru_cache(maxsize=1)
def _codigos_detector() -> dict[str, str]:
    out = dict(_EXTRA_DET)
    rx = re.compile(r"^class (\w+)\(Detector\):.*?^\s+id\s*=\s*[\"']([^\"']+)[\"']", re.M | re.S)
    for p in sorted((REPO / "compliance_agent" / "detectores").glob("*.py")):
        for classe, cod in rx.findall(p.read_text(encoding="utf-8")):
            out.setdefault(cod, f"det.{classe}")
    return out


def regra_do_detector(codigo: str) -> str:
    return _codigos_detector().get(codigo, f"nao_registrado.{codigo}")


# ── versão da regra: sha do arquivo do módulo hoje (o legado não gravou versão) ──
@lru_cache(maxsize=512)
def _sha_arquivo(rel: str) -> str:
    p = REPO / rel
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.is_file() else "indisponivel"


def versao_regra(regra_id: str) -> str:
    e = registro.carregar().get(regra_id)
    return f"{e['modulo']}@{_sha_arquivo(e['modulo'])}" if e else "nao_registrado"


def _entrada(regra_id: str) -> dict:
    return registro.carregar().get(regra_id) or {}


def _hipoteses(regra_id: str) -> list[str]:
    return [h["hipotese"] for h in _entrada(regra_id).get("hipoteses_inocentes") or [] if h.get("hipotese")]


def _inferencia(regra_id: str) -> str:
    return str(_entrada(regra_id).get("afirma") or f"regra {regra_id} sem entrada no registro")


def _json(txt) -> Any:
    if isinstance(txt, (dict, list)):
        return txt
    try:
        return json.loads(txt) if txt else {}
    except (TypeError, ValueError):
        return {"_texto": str(txt)}


def _processo(d: Any) -> str | None:
    if isinstance(d, dict):
        for k in ("processo", "processo_sei", "numero_processo"):
            if d.get(k):
                return str(d[k])
    return None


# ───────────────────────────── geração 1: `alertas` ─────────────────────────────
COLS_ALERTA = ("id", "tipo", "severidade", "titulo", "descricao", "evidencias", "status", "pessoa_id",
               "empresa_id", "contrato_id", "processo_sei_id", "ordem_bancaria_id", "data_referencia", "created_at")


def de_alerta(linha: dict) -> Achado:
    """Uma linha de `alertas` (dict com COLS_ALERTA) → Achado em triagem/em_revisao, estado INDICIO."""
    rid, zumbi = regra_do_alerta(linha["tipo"], linha.get("titulo"))
    ev = _json(linha.get("evidencias"))
    entradas = {"tipo": linha["tipo"], "titulo": linha.get("titulo"), "evidencias": ev,
                "data_referencia": linha.get("data_referencia"),
                "chaves": {k: linha.get(k) for k in ("pessoa_id", "empresa_id", "contrato_id", "processo_sei_id",
                                                     "ordem_bancaria_id") if linha.get(k) is not None}}
    status_legado = linha.get("status") or "novo"
    resultado = {"severidade": linha.get("severidade"), "status_legado": status_legado,
                 "geracao": "alertas", "criado_em_legado": str(linha.get("created_at") or "")}
    if zumbi:
        resultado["titulo_sem_regra_atual"] = True
    exe = ExecucaoRegra(regra_id=rid, versao=versao_regra(rid), entradas_hash=hash_entradas(entradas),
                        resultado=resultado, processo=_processo(ev), origem=f"alertas:{linha['id']}")
    return Achado.de_regra(
        execucao=exe,
        status=StatusAchado.TRIAGEM if status_legado == "novo" else StatusAchado.EM_REVISAO,
        estado=EstadoSaida.INDICIO,
        observacao=str(linha.get("descricao") or linha.get("titulo") or "(alerta sem descrição)"),
        inferencia=_inferencia(rid), qualificacao=None,
        hipotese=str(linha.get("titulo") or _inferencia(rid)),
        hipoteses_alternativas=_hipoteses(rid),
        evidencias=[Fato(papel=Papel.SUPORTE, tipo="registro", fonte="alertas.evidencias",
                         referencia=f"alertas:{linha['id']}", descricao="registro estruturado gravado pela regra",
                         dados=ev if isinstance(ev, dict) else {"lista": ev})])


# ───────────────────────────── geração 2: detectores/ ─────────────────────────────
_ESTADO_DET = {"confirmado": EstadoSaida.INDICIO, "descartado": EstadoSaida.AUSENTE,
               "nao_avaliavel": EstadoSaida.INDISPONIVEL}


def de_resultado(res: dict, *, origem: str, escopo: dict | None = None) -> Achado:
    """`ResultadoDetector.to_dict()` (ou linha equivalente) → Achado. `escopo`: chaves do lugar (ug, certame, …)."""
    rid = regra_do_detector(res["detector"])
    valores = _json(res.get("valores"))
    evid = _json(res.get("evidencia")) or []
    entradas = {"detector": res["detector"], "processo": res.get("processo"), "escopo": escopo or {},
                "valores": valores}
    st = res.get("status") or "nao_avaliavel"
    estado = _ESTADO_DET.get(st, EstadoSaida.INCERTO)
    resultado = {"status_detector": st, "score": res.get("score"), "geracao": "detectores",
                 "refutada": bool(res.get("refutada")), "motivo": res.get("motivo") or res.get("motivo_refutacao")}
    exe = ExecucaoRegra(regra_id=rid, versao=versao_regra(rid), entradas_hash=hash_entradas(entradas),
                        resultado=resultado, processo=res.get("processo"), origem=origem)
    papel = Papel.SUPORTE if estado is EstadoSaida.INDICIO else Papel.CONTEXTO
    fatos = [Fato(papel=papel, tipo="documento", fonte=str(e.get("fonte") or "detector"),
                  trecho_literal=e.get("trecho"), descricao="evidência do detector",
                  dados={k: e[k] for k in ("hash", "capturado_em") if k in e})
             for e in (evid if isinstance(evid, list) else []) if isinstance(e, dict)]
    fatos.append(Fato(papel=papel, tipo="registro", fonte="detector.valores", referencia=origem,
                      dados=valores if isinstance(valores, dict) else {"valores": valores}))
    inocente = str(res.get("explicacao_inocente") or "").strip()
    return Achado.de_regra(
        execucao=exe, status=StatusAchado.TRIAGEM, estado=estado,
        observacao=str(res.get("motivo") or f"{res['detector']} {st} em {res.get('processo')}"),
        inferencia=_inferencia(rid), qualificacao=None, hipotese=_inferencia(rid),
        hipoteses_alternativas=([inocente] if inocente else []) + _hipoteses(rid), evidencias=fatos)


TABELAS_DET = {"achado_certame": ("certame", "orgao_cnpj"), "achado_detector": ("ug", "processo", "escopo"),
               "achado_execucao": ("contrato", "orgao_cnpj", "fornecedor")}


def de_achado_db(tabela: str, linha: dict) -> Achado:
    """Linha de achados.db (achado_certame | achado_detector | achado_execucao) → Achado."""
    chaves = TABELAS_DET[tabela]
    escopo = {k: linha.get(k) for k in chaves if k != "processo"}
    proc = linha.get("processo") or linha.get("certame") or linha.get("contrato")
    origem = f"{tabela}:" + "|".join(str(linha.get(k)) for k in (*chaves[:1], "detector") + (
        ("processo",) if tabela == "achado_detector" else ()))
    res = {"detector": linha["detector"], "processo": proc, "score": linha.get("score"), "status": linha.get("status"),
           "valores": linha.get("valores"), "evidencia": linha.get("evidencia"),
           "explicacao_inocente": linha.get("explicacao_inocente"), "motivo": linha.get("motivo")}
    return de_resultado(res, origem=origem, escopo=escopo)


# ───────────────────────────── geração 3: cruzamentos_intel ─────────────────────────────
LISTA_INTEL = ("achados", "empresas", "grupos", "casos", "pares", "itens", "comunidades")


def itens_intel(cache: dict) -> list[dict]:
    for k in LISTA_INTEL:
        if isinstance(cache.get(k), list):
            return [x for x in cache[k] if isinstance(x, dict)]
    return []


def de_intel(nome: str, item: dict) -> Achado:
    """Item de um cruzamento intel (ex.: `sancionadas_contratadas`, `radar_risco`, `ninho_sala`) → Achado."""
    rid = f"intel.{nome}" if f"intel.{nome}" in registro.carregar() else (
        nome if nome in registro.carregar() else f"nao_registrado.intel.{nome}")
    chave = next((str(item[k]) for k in ("cnpj", "chave", "sala", "cpf_cnpj", "id") if item.get(k)), None)
    exe = ExecucaoRegra(regra_id=rid, versao=versao_regra(rid), entradas_hash=hash_entradas(item),
                        resultado={"geracao": "cruzamentos_intel", "score": item.get("score"),
                                   "grau": item.get("grau") or item.get("rating") or item.get("risco")},
                        processo=_processo(item), origem=f"intel:{nome}:{chave}")
    return Achado.de_regra(
        execucao=exe, status=StatusAchado.TRIAGEM, estado=EstadoSaida.INDICIO,
        observacao=f"{nome}: {chave}", inferencia=_inferencia(rid), qualificacao=None, hipotese=_inferencia(rid),
        hipoteses_alternativas=_hipoteses(rid),
        evidencias=[Fato(papel=Papel.SUPORTE, tipo="registro", fonte=f"cache:{nome}", referencia=chave, dados=item)])


# ───────────────────────────── persistência (PG, esquema dado) ─────────────────────────────
SQL_MIGRACAO = REPO / "deploy" / "vm2" / "postgres" / "achados_001.sql"


def aplicar_schema(con, esquema: str) -> None:
    """Aplica `achados_001.sql` (idempotente) no esquema — conexão psycopg em autocommit."""
    from compliance_agent.fluxo.schema import renderizar
    con.execute(f'CREATE SCHEMA IF NOT EXISTS "{esquema}"')
    con.execute(renderizar(SQL_MIGRACAO.read_text(encoding="utf-8"), esquema))


def gravar(con, esquema: str, achados: list[Achado]) -> dict:
    """Grava execucao_regra + achado + achado_evidencia (idempotente pela chave da execução). Devolve contagens."""
    from psycopg.types.json import Jsonb

    from compliance_agent.fluxo.schema import validar_esquema
    s = validar_esquema(esquema)
    novos = 0
    with con.transaction():
        for a in achados:
            e = a.execucao
            r = con.execute(
                f'INSERT INTO "{s}".execucao_regra (regra_id, regra_versao, processo, entradas_hash, resultado, origem) '
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (origem, regra_id, regra_versao, entradas_hash) DO NOTHING "
                "RETURNING id", (e.regra_id, e.versao, e.processo, e.entradas_hash, Jsonb(e.resultado), e.origem)
            ).fetchone()
            if r is None:
                continue
            novos += 1
            aid = con.execute(
                f'INSERT INTO "{s}".achado (execucao_regra_id, status, estado, motivo_estado, observacao, inferencia, '
                "qualificacao, hipotese, hipoteses_alternativas) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (r[0], a.status.value, a.estado.value, a.motivo_estado, a.observacao, a.inferencia, a.qualificacao,
                 a.hipotese, Jsonb(a.hipoteses_alternativas))).fetchone()[0]
            for i, f in enumerate(a.evidencias):
                con.execute(f'INSERT INTO "{s}".achado_evidencia (achado_id, ordem, papel, fato) VALUES (%s,%s,%s,%s)',
                            (aid, i, f.papel.value, Jsonb(f.model_dump(mode="json"))))
    return {"recebidos": len(achados), "gravados": novos}
