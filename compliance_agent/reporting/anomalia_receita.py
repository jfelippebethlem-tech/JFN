# -*- coding: utf-8 -*-
"""
DETECTOR DE ANOMALIA — CRUZAMENTO DUMP DA RECEITA FEDERAL × FORNECEDORES, POR ÓRGÃO (UG).

Função PURA `anomalias_orgao(ug)` que cruza as Ordens Bancárias (verdade de pagamento) com o dump
da Receita Federal já ingerido (`empresas_min`, `socios_receita`, `socios_reverso`) para flagar, por
Unidade Gestora, padrões ANÔMALOS determinísticos:

  1. SEM FINS LUCRATIVOS recebendo — fornecedores cuja natureza jurídica começa em '3' (associação /
     fundação / organização social / religiosa). Anômalo para um *fornecedor comum* de bens/serviços;
     ranqueado por R$. (No TJRJ: Mútua dos Magistrados, Inst. Travessia/Dignidade.) Honesto: educação/
     pesquisa/estágio legítimos (CIEE, FGV, CEBRASPE, VUNESP) recebem RESSALVA — indício ≠ acusação.
  2. REDE / GRUPO — (a) pessoas (nome+doc) que administram ≥2 fornecedores DO MESMO órgão = possível
     grupo / concorrência fictícia; (b) administradores deste órgão que aparecem em MUITOS CNPJs no
     Brasil (`socios_reverso`) = possível "veículo de aluguel"/administrador profissional. Honesto:
     executivos de grandes conglomerados legítimos (Bradesco, etc.) dominam o (b) → RESSALVA.
  3. LARANJA / SÓCIO-ÚNICO — fornecedor de ALTO valor com 1 só administrador no QSA.
  4. (opcional, bounded) SITUAÇÃO CADASTRAL — INAPTA/baixada via API grátis (minhareceita.org).
     Só amostra os top-suspeitos; cacheia em `cadastro_externo`; NÃO derruba o relatório se a API falhar.

Chave de junção: `empresas_min.cnpj_basico = substr(ordens_bancarias.favorecido_cpf, 1, 8)` (a raiz de 8
dígitos do CNPJ). Apenas favorecidos PJ (CNPJ de 14 dígitos) entram.

HONESTIDADE (regra-mãe do projeto):
  - indício ≠ acusação; presunção de legitimidade;
  - INDISPONÍVEL ≠ 0 — nem todo fornecedor está no `empresas_min`/`socios_receita` (cobertura informada);
  - entes públicos (natureza '1xxx') e grandes empresas/instituições legítimas NÃO são anomalia;
  - CPF de sócio PF mascarado por LGPD (vem mascarado do dump; não é desmascarado aqui).

Pura/testável: sem rede no caminho default (cadastral só roda com `checar_cadastro=True`). Degrada
honesto: se as tabelas do dump não existirem (DB de teste), devolve `ok=False` com nota — nunca levanta.

USO (CLI):
    cd ~/JFN && .venv/bin/python -m compliance_agent.reporting.anomalia_receita 036100
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import urllib.error
import urllib.request
from typing import Optional

_log = logging.getLogger(__name__)

# ── parâmetros (determinísticos, ajustáveis) ───────────────────────────────────
_VALOR_ALTO = 5_000_000.0       # piso de "alto valor" p/ a anomalia 3 (laranja/sócio-único)
_REDE_MIN_FORN = 2              # pessoa administrando ≥N fornecedores DO MESMO órgão (anomalia 2a)
_VEICULO_MIN_CNPJS = 10        # administrador em ≥N CNPJs no Brasil (anomalia 2b — veículo de aluguel)
_TOP = 25                      # teto de linhas por lista (relatório enxuto; XLSX guarda o resto)

# Naturezas jurídicas "3xxx" (sem fins lucrativos) cujo recebimento é, por si só, MENOS suspeito —
# entidades de ensino/pesquisa/estágio costumam contratar legitimamente com o setor público.
# NÃO removemos da lista (transparência), apenas marcamos `ressalva=True` para o leitor/IA ponderar.
# (Heurística por TOKENS no nome; conservadora — na dúvida, NÃO ressalva.)
_TOKENS_RESSALVA = (
    "universidade", "faculdade", "fundacao getulio", "getulio vargas", "vunesp",
    "cebraspe", "vestibular", "integracao empresa escola", "ciee", "cesgranrio",
    "pesquisa", "escola", "ensino", "pontificia", "catolicas", "instituto federal",
)

# Rótulo legível das naturezas 3xxx mais comuns (dump RF). Só p/ exibição; ausência → código cru.
_NATUREZA_3 = {
    "3069": "Fundação privada",
    "3220": "Organização religiosa",
    "3301": "Organização social (OS)",
    "3999": "Associação privada",
    "3085": "Entidade de mediação e arbitragem",
}


def _conn() -> sqlite3.Connection:
    """Conexão read-only-friendly respeitando JFN_DB/DB_PATH (isolamento de teste, lição cont.36)."""
    from compliance_agent.database.models import _resolver_db
    con = sqlite3.connect(str(_resolver_db()), timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
    except sqlite3.Error:
        pass
    return con


def _tem_tabela(con: sqlite3.Connection, nome: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)).fetchone())


def _norm_ug(ug) -> str:
    """UG só-dígitos (o `ug_codigo` na base é a string com zeros à esquerda, ex.: '036100')."""
    return "".join(ch for ch in str(ug or "") if ch.isdigit())


def _ressalva_nome(nome: str) -> bool:
    n = (nome or "").lower()
    return any(tok in n for tok in _TOKENS_RESSALVA)


# ── anomalia 1: sem fins lucrativos recebendo ──────────────────────────────────
def _sem_fins_lucrativos(con: sqlite3.Connection, ug: str) -> list[dict]:
    rows = con.execute(
        """
        SELECT em.razao_social, em.natureza_cod,
               substr(ob.favorecido_cpf,1,8) AS cb,
               SUM(ob.valor) AS v
          FROM ordens_bancarias ob
          JOIN empresas_min em ON em.cnpj_basico = substr(ob.favorecido_cpf,1,8)
         WHERE ob.ug_codigo = ? AND length(ob.favorecido_cpf) = 14
           AND em.natureza_cod LIKE '3%'
         GROUP BY cb
         ORDER BY v DESC
         LIMIT ?
        """,
        (ug, _TOP),
    ).fetchall()
    out = []
    for razao, nat, cb, v in rows:
        out.append({
            "cnpj_basico": cb,
            "razao_social": razao,
            "natureza_cod": nat,
            "natureza_txt": _NATUREZA_3.get(nat, f"Natureza {nat}"),
            "total": float(v or 0.0),
            "ressalva": _ressalva_nome(razao),
        })
    return out


# ── anomalia 2a: pessoas administrando ≥2 fornecedores DO MESMO órgão ──────────
def _rede_mesmo_orgao(con: sqlite3.Connection, ug: str) -> list[dict]:
    rows = con.execute(
        """
        WITH forn AS (
            SELECT DISTINCT substr(favorecido_cpf,1,8) AS cb
              FROM ordens_bancarias
             WHERE ug_codigo = ? AND length(favorecido_cpf) = 14
        )
        SELECT s.nome_socio, s.doc_socio,
               COUNT(DISTINCT s.cnpj_basico) AS nf,
               GROUP_CONCAT(DISTINCT s.qualificacao_txt) AS quals,
               GROUP_CONCAT(DISTINCT s.cnpj_basico)      AS cnpjs
          FROM socios_receita s
          JOIN forn f ON f.cb = s.cnpj_basico
         GROUP BY s.nome_norm, s.doc_socio
        HAVING nf >= ?
         ORDER BY nf DESC, s.nome_socio
         LIMIT ?
        """,
        (ug, _REDE_MIN_FORN, _TOP),
    ).fetchall()
    out = []
    for nome, doc, nf, quals, cnpjs in rows:
        out.append({
            "nome_socio": nome,
            "doc_socio": doc,                      # PF mascarado (LGPD) / PJ = CNPJ
            "eh_pj": bool(doc and len(_norm_ug(doc)) == 14),
            "n_fornecedores": int(nf),
            "qualificacoes": (quals or "").replace(",", ", "),
            "cnpjs_basicos": [c for c in (cnpjs or "").split(",") if c],
        })
    return out


# ── anomalia 2b: administrador deste órgão em MUITOS CNPJs no Brasil ───────────
def _veiculo_de_aluguel(con: sqlite3.Connection, ug: str) -> list[dict]:
    if not _tem_tabela(con, "socios_reverso"):
        return []
    rows = con.execute(
        """
        WITH forn AS (
            SELECT DISTINCT substr(favorecido_cpf,1,8) AS cb
              FROM ordens_bancarias
             WHERE ug_codigo = ? AND length(favorecido_cpf) = 14
        ),
        adm AS (
            SELECT DISTINCT s.nome_norm, s.nome_socio, s.doc_socio
              FROM socios_receita s
              JOIN forn f ON f.cb = s.cnpj_basico
             WHERE s.doc_socio LIKE '***%'        -- só PF (mascarado); PJ-holding é outra história
        )
        SELECT a.nome_socio, a.doc_socio,
               COUNT(DISTINCT r.cnpj_basico) AS ncnpj
          FROM adm a
          JOIN socios_reverso r ON r.doc_socio = a.doc_socio AND r.nome_norm = a.nome_norm
         GROUP BY a.nome_norm, a.doc_socio
        HAVING ncnpj >= ?
         ORDER BY ncnpj DESC, a.nome_socio
         LIMIT ?
        """,
        (ug, _VEICULO_MIN_CNPJS, _TOP),
    ).fetchall()
    out = []
    for nome, doc, ncnpj in rows:
        out.append({
            "nome_socio": nome,
            "doc_socio": doc,
            "n_cnpjs_brasil": int(ncnpj),
        })
    return out


# ── anomalia 3: laranja / sócio-único de alto valor ───────────────────────────
def _socio_unico_alto_valor(con: sqlite3.Connection, ug: str, piso: float) -> list[dict]:
    rows = con.execute(
        """
        WITH fv AS (
            SELECT substr(favorecido_cpf,1,8) AS cb,
                   MAX(favorecido_nome) AS nm,
                   SUM(valor) AS v
              FROM ordens_bancarias
             WHERE ug_codigo = ? AND length(favorecido_cpf) = 14
             GROUP BY cb
        )
        SELECT fv.cb, fv.nm, fv.v,
               COUNT(*) AS nsocios,
               MAX(s.nome_socio) AS unico_nome,
               MAX(s.qualificacao_txt) AS unico_qual,
               MAX(em.natureza_cod) AS nat
          FROM fv
          JOIN socios_receita s ON s.cnpj_basico = fv.cb
          LEFT JOIN empresas_min em ON em.cnpj_basico = fv.cb
         GROUP BY fv.cb
        HAVING nsocios = 1 AND fv.v >= ?
         ORDER BY fv.v DESC
         LIMIT ?
        """,
        (ug, piso, _TOP),
    ).fetchall()
    out = []
    for cb, nm, v, _ns, unome, uqual, nat in rows:
        out.append({
            "cnpj_basico": cb,
            "razao_social": nm,
            "total": float(v or 0.0),
            "socio_unico": unome,
            "qualificacao": uqual,
            "natureza_cod": nat,
            "sem_fins": bool(nat and str(nat).startswith("3")),
        })
    return out


# ── anomalia 4 (opcional, bounded, com cache): situação cadastral externa ──────
_MINHARECEITA = "https://minhareceita.org/{cnpj}"
_UA = "JFN-compliance/1.0 (controle externo TCE-RJ; auditoria publica)"


def _garante_cache_cadastro(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS cadastro_externo (
            cnpj_basico  TEXT PRIMARY KEY,
            situacao     TEXT,
            descricao    TEXT,
            data_situacao TEXT,
            fonte        TEXT,
            consultado_em TEXT
        )
        """
    )
    con.commit()


def _consulta_minhareceita(cnpj14: str, timeout: float = 8.0) -> Optional[dict]:
    """Consulta minhareceita.org (grátis). Retorna dict ou None se falhar (degrada honesto)."""
    req = urllib.request.Request(_MINHARECEITA.format(cnpj=cnpj14), headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (URL fixa/confiável)
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as exc:
        _log.info("minhareceita falhou p/ %s: %s", cnpj14, exc)
        return None
    sit = (data.get("descricao_situacao_cadastral") or data.get("situacao_cadastral") or "").strip()
    return {
        "situacao": sit.upper(),
        "descricao": (data.get("motivo_situacao_cadastral") or "").strip(),
        "data_situacao": (data.get("data_situacao_cadastral") or "").strip(),
    }


def _situacao_cadastral(con: sqlite3.Connection, alvos: list[str], limite: int = 8) -> dict:
    """Para uma AMOSTRA bounded de CNPJ-raiz (top suspeitos), consulta a situação cadastral via
    minhareceita.org, cacheando em `cadastro_externo`. Só reporta INAPTA/BAIXADA/SUSPENSA/NULA.
    Nunca derruba o relatório: cada consulta é try/except e o todo degrada honesto."""
    from datetime import datetime
    achados: list[dict] = []
    n_consultados = 0
    try:
        _garante_cache_cadastro(con)
    except sqlite3.Error as exc:
        return {"ok": False, "_nota": f"cache indisponível: {exc}", "achados": [], "n_consultados": 0}
    for cb in alvos[:limite]:
        cb = _norm_ug(cb)
        if len(cb) != 8:
            continue
        cached = con.execute(
            "SELECT situacao, descricao, data_situacao FROM cadastro_externo WHERE cnpj_basico=?", (cb,)
        ).fetchone()
        if cached is not None:
            sit, desc, dt = cached
        else:
            # minhareceita aceita o CNPJ completo; tentamos a matriz (0001) + DV via API que tolera.
            res = _consulta_minhareceita(cb + "000100")  # 14 díg (matriz, DV placeholder tolerado)
            n_consultados += 1
            if res is None:
                continue
            sit, desc, dt = res["situacao"], res["descricao"], res["data_situacao"]
            try:
                con.execute(
                    "INSERT OR REPLACE INTO cadastro_externo "
                    "(cnpj_basico,situacao,descricao,data_situacao,fonte,consultado_em) "
                    "VALUES (?,?,?,?,?,?)",
                    (cb, sit, desc, dt, "minhareceita.org", datetime.utcnow().isoformat(timespec="seconds")),
                )
                con.commit()
            except sqlite3.Error:
                pass
        if sit and sit not in ("ATIVA", ""):
            achados.append({"cnpj_basico": cb, "situacao": sit, "descricao": desc, "data_situacao": dt})
    return {"ok": True, "achados": achados, "n_consultados": n_consultados}


# ── orquestrador puro ──────────────────────────────────────────────────────────
def anomalias_orgao(ug, *, valor_alto: float = _VALOR_ALTO,
                    checar_cadastro: bool = False, cadastro_limite: int = 8) -> dict:
    """Cruza o dump da Receita × fornecedores da UG e devolve as anomalias determinísticas.

    Retorno (sempre um dict; NUNCA levanta):
      {ok, ug, cobertura:{...}, sem_fins_lucrativos:[...], rede_mesmo_orgao:[...],
       veiculos_aluguel:[...], socio_unico_alto_valor:[...], cadastro:{...}, ressalvas:[...]}
    `ok=False` + `_nota` se o dump da Receita não estiver ingerido (degrada honesto)."""
    ug = _norm_ug(ug)
    if not ug:
        return {"ok": False, "_nota": "UG vazia/!inválida", "ug": ug}
    try:
        con = _conn()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "_nota": f"DB indisponível: {str(exc)[:120]}", "ug": ug}
    try:
        if not (_tem_tabela(con, "empresas_min") and _tem_tabela(con, "socios_receita")):
            return {"ok": False, "ug": ug,
                    "_nota": "dump da Receita (empresas_min/socios_receita) não ingerido nesta base "
                             "— rode tools/socios_dump_sweep.py. INDISPONÍVEL ≠ ausência de anomalia."}

        # cobertura honesta: dos fornecedores PJ da UG, quantos têm match no dump?
        n_forn = con.execute(
            "SELECT COUNT(DISTINCT substr(favorecido_cpf,1,8)) FROM ordens_bancarias "
            "WHERE ug_codigo=? AND length(favorecido_cpf)=14", (ug,)).fetchone()[0] or 0
        n_match = con.execute(
            "SELECT COUNT(DISTINCT ob.favorecido_cpf) FROM ordens_bancarias ob "
            "JOIN empresas_min em ON em.cnpj_basico=substr(ob.favorecido_cpf,1,8) "
            "WHERE ob.ug_codigo=? AND length(ob.favorecido_cpf)=14", (ug,)).fetchone()[0] or 0
        n_qsa = con.execute(
            "SELECT COUNT(DISTINCT ob.favorecido_cpf) FROM ordens_bancarias ob "
            "JOIN socios_receita s ON s.cnpj_basico=substr(ob.favorecido_cpf,1,8) "
            "WHERE ob.ug_codigo=? AND length(ob.favorecido_cpf)=14", (ug,)).fetchone()[0] or 0

        sem_fins = _sem_fins_lucrativos(con, ug)
        rede = _rede_mesmo_orgao(con, ug)
        veiculos = _veiculo_de_aluguel(con, ug)
        socio_unico = _socio_unico_alto_valor(con, ug, valor_alto)

        cadastro = {"ok": False, "_nota": "não solicitado (checar_cadastro=False)", "achados": []}
        if checar_cadastro:
            # amostra: os CNPJ-raiz mais suspeitos (alto valor sem-fins + sócio-único), dedup ordenado.
            alvos: list[str] = []
            for r in sem_fins:
                if not r.get("ressalva"):
                    alvos.append(r["cnpj_basico"])
            for r in socio_unico:
                if r["cnpj_basico"] not in alvos:
                    alvos.append(r["cnpj_basico"])
            try:
                cadastro = _situacao_cadastral(con, alvos, limite=cadastro_limite)
            except Exception as exc:  # noqa: BLE001 — NUNCA derruba o relatório
                _log.warning("situação cadastral degradou: %s", exc)
                cadastro = {"ok": False, "_nota": f"API cadastral falhou: {str(exc)[:120]}", "achados": []}

        ressalvas = [
            "Indício ≠ acusação; presunção de legitimidade. Entes públicos (natureza '1xxx') e grandes "
            "empresas/instituições legítimas (ensino/pesquisa/estágio: CIEE, FGV, CEBRASPE, VUNESP, "
            "Ingram, etc.) NÃO são anomalia — recebem ressalva.",
            "INDISPONÍVEL ≠ 0: nem todo fornecedor está no dump da Receita ingerido — a cobertura é "
            "informada e os não-cobertos seguem INDISPONÍVEL, não 'limpos'.",
            "CPF de sócio PF vem mascarado do dump (LGPD) e não é desmascarado aqui.",
        ]

        indicio = bool(
            [r for r in sem_fins if not r.get("ressalva")] or rede or socio_unico
            or (cadastro.get("achados"))
        )
        return {
            "ok": True,
            "ug": ug,
            "indicio": indicio,
            "cobertura": {
                "n_fornecedores_pj": int(n_forn),
                "n_no_empresas_min": int(n_match),
                "n_com_qsa": int(n_qsa),
                "pct_empresas_min": round(100 * n_match / n_forn, 1) if n_forn else 0.0,
                "pct_qsa": round(100 * n_qsa / n_forn, 1) if n_forn else 0.0,
            },
            "sem_fins_lucrativos": sem_fins,
            "rede_mesmo_orgao": rede,
            "veiculos_aluguel": veiculos,
            "socio_unico_alto_valor": socio_unico,
            "cadastro": cadastro,
            "ressalvas": ressalvas,
        }
    except Exception as exc:  # noqa: BLE001 — função pura/robusta: degrada, nunca explode no produto
        _log.warning("anomalias_orgao(%s) degradou: %s", ug, exc)
        return {"ok": False, "ug": ug, "_nota": f"falha ao computar anomalias: {str(exc)[:160]}"}
    finally:
        con.close()


def _cli(argv: list[str]) -> int:
    if not argv:
        print("uso: python -m compliance_agent.reporting.anomalia_receita <UG> [--cadastro]")
        return 2
    ug = argv[0]
    checar = "--cadastro" in argv
    out = anomalias_orgao(ug, checar_cadastro=checar)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
