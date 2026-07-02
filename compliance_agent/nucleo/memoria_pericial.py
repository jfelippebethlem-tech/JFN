"""
Memória pericial — o sistema fica mais inteligente A CADA perícia.

Toda perícia executada é registrada aqui (SQLite, stdlib). Dessa memória saem
três formas de inteligência progressiva:

  1. REFERÊNCIA DE PREÇO — mediana e desvio-padrão por categoria (e por órgão)
     calculados sobre TODAS as perícias já feitas. O indicador de
     superfaturamento melhora automaticamente conforme a base cresce: com 10
     perícias a referência é fraca; com 10.000 é um preço de mercado real.
  2. PERFIL DO FORNECEDOR — histórico de risco de cada CNPJ. Reincidência vira
     evidência: um fornecedor com 5 laudos de risco alto entra na próxima
     perícia já com contexto.
  3. LASTRO PARA O APRENDIZADO — o veredito do perito (confirmado/descartado)
     fica ligado ao laudo original, alimentando a calibração de parâmetros
     (aprendizado.py) e o ciclo de autoaprimoramento (autoaprimoramento.py).

Sem IA e sem dependências externas: sqlite3 da stdlib.
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _db_path() -> Path:
    # Lido a cada chamada para permitir isolamento em testes via env.
    return Path(os.environ.get("NUCLEO_MEMORIA_DB", "data/nucleo_memoria.db"))


def _conectar() -> sqlite3.Connection:
    caminho = _db_path()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.execute("""
        CREATE TABLE IF NOT EXISTS pericias (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            referencia    TEXT,                -- nº OB/contrato/processo
            quando        TEXT NOT NULL,       -- ISO-8601 UTC
            categoria     TEXT,
            orgao         TEXT,
            cnpj          TEXT,
            valor         REAL,
            risco_score   REAL,
            classificacao TEXT,
            achados       TEXT,                -- JSON: [{indicador_id, confianca, ...}]
            veredito_perito TEXT               -- confirmado | descartado | NULL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS ix_pericias_cat ON pericias(categoria)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_pericias_cnpj ON pericias(cnpj)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_pericias_ref ON pericias(referencia)")
    try:  # migração: dossiê serializado (p/ promover perícia a caso-ouro)
        con.execute("ALTER TABLE pericias ADD COLUMN dossie TEXT")
    except sqlite3.OperationalError:
        pass  # coluna já existe
    return con


def _dossie_kwargs(dossie) -> dict:
    """
    Serializa o Dossie para os kwargs que o reconstroem (mesmo formato dos
    casos-ouro embutidos): datas → ISO, campos vazios descartados.
    """
    from dataclasses import asdict

    def _limpo(d: dict) -> dict:
        saida = {}
        for k, v in d.items():
            if v in (None, "", [], {}, False):
                continue
            if hasattr(v, "isoformat"):
                v = v.isoformat()
            if isinstance(v, list):
                v = [{kk: (vv.isoformat() if hasattr(vv, "isoformat") else vv)
                      for kk, vv in i.items()} if isinstance(i, dict) else i
                     for i in v]
            saida[k] = v
        return saida

    kwargs = {"contratacao": _limpo(asdict(dossie.contratacao)),
              "fornecedor": _limpo(asdict(dossie.fornecedor))}
    if dossie.historico_orgao_fornecedor:
        kwargs["historico"] = [_limpo(asdict(h))
                               for h in dossie.historico_orgao_fornecedor]
    if dossie.referencia_categoria:
        kwargs["referencia_categoria"] = dict(dossie.referencia_categoria)
    return kwargs


def registrar_laudo(laudo, referencia: str = "") -> int:
    """
    Grava um Laudo na memória. Retorna o id do registro.

    Chamado ao fim de cada perícia (nucleo.periciar com usar_memoria=True, ou
    explicitamente pelo ciclo). É o ato de "aprender que esta perícia existiu".
    """
    c = laudo.dossie.contratacao
    f = laudo.dossie.fornecedor
    achados = [
        {"indicador_id": a.indicador_id, "confianca": a.confianca,
         "severidade": a.severidade}
        for a in laudo.veredito.achados
    ]
    try:
        dossie_json = json.dumps(_dossie_kwargs(laudo.dossie), ensure_ascii=False)
    except Exception:
        dossie_json = None
    con = _conectar()
    try:
        cur = con.execute(
            "INSERT INTO pericias (referencia, quando, categoria, orgao, cnpj, valor,"
            " risco_score, classificacao, achados, dossie) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (referencia or c.identificador,
             datetime.now(timezone.utc).isoformat(timespec="seconds"),
             c.categoria or "", c.orgao or "", f.cnpj or "",
             c.valor, laudo.veredito.risco_score, laudo.veredito.classificacao,
             json.dumps(achados, ensure_ascii=False), dossie_json),
        )
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


def obter_pericia(referencia: str) -> dict | None:
    """Última perícia da referência: dossiê, achados e veredito (p/ promoção)."""
    con = _conectar()
    try:
        row = con.execute(
            "SELECT dossie, achados, veredito_perito, classificacao, valor "
            "FROM pericias WHERE referencia = ? ORDER BY id DESC LIMIT 1",
            (referencia,)).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    return {"dossie": json.loads(row[0]) if row[0] else None,
            "achados": json.loads(row[1] or "[]"),
            "veredito": row[2], "classificacao": row[3], "valor": row[4]}


def tem_pericia(referencia: str) -> bool:
    """True se há laudo registrado com esta referência (sem efeito colateral)."""
    con = _conectar()
    try:
        return con.execute("SELECT 1 FROM pericias WHERE referencia = ? LIMIT 1",
                           (referencia,)).fetchone() is not None
    finally:
        con.close()


def registrar_veredito(referencia: str, veredito: str) -> int:
    """
    Liga a decisão do perito (confirmado|descartado|inconclusivo) às perícias
    daquela referência E propaga para aprendizado.registrar_feedback de cada
    indicador que disparou. Retorna quantos registros foram atualizados.
    """
    veredito = veredito.strip().lower()
    if veredito not in ("confirmado", "descartado", "inconclusivo"):
        raise ValueError("veredito deve ser confirmado|descartado|inconclusivo")
    con = _conectar()
    try:
        linhas = con.execute(
            "SELECT id, achados FROM pericias WHERE referencia = ?", (referencia,)
        ).fetchall()
        con.execute(
            "UPDATE pericias SET veredito_perito = ? WHERE referencia = ?",
            (veredito, referencia),
        )
        con.commit()
    finally:
        con.close()
    # Propaga para o feedback por indicador (calibração).
    from compliance_agent.nucleo import aprendizado
    for _id, achados_json in linhas:
        try:
            for a in json.loads(achados_json or "[]"):
                aprendizado.registrar_feedback(a["indicador_id"], veredito, referencia)
        except Exception:
            continue
    return len(linhas)


def obter_referencia(categoria: str, orgao: str = "",
                     minimo_amostra: int = 5) -> dict[str, float]:
    """
    Referência de preço aprendida com as perícias anteriores.

    Prefere o recorte categoria+órgão; se a amostra for pequena, cai para a
    categoria inteira. Retorna {} se ainda não há amostra suficiente — o
    indicador de superfaturamento então não dispara (honestidade estatística).
    """
    if not categoria:
        return {}
    con = _conectar()
    try:
        def _valores(sql: str, args: tuple) -> list[float]:
            return [float(v) for (v,) in con.execute(sql, args).fetchall()
                    if v and v > 0]
        valores = []
        if orgao:
            valores = _valores(
                "SELECT valor FROM pericias WHERE categoria=? AND orgao=?",
                (categoria, orgao))
        if len(valores) < minimo_amostra:
            valores = _valores(
                "SELECT valor FROM pericias WHERE categoria=?", (categoria,))
    finally:
        con.close()
    if len(valores) < minimo_amostra:
        return {}
    ref = {"mediana": statistics.median(valores), "n": float(len(valores))}
    if len(valores) >= 2:
        ref["desvio_padrao"] = statistics.pstdev(valores)
    return ref


@dataclass
class PerfilFornecedor:
    cnpj: str
    total_pericias: int
    risco_medio: float
    criticos_e_altos: int
    confirmados: int
    descartados: int


def perfil_fornecedor(cnpj: str) -> PerfilFornecedor | None:
    """Histórico de risco do fornecedor — reincidência vira contexto pericial."""
    if not cnpj:
        return None
    con = _conectar()
    try:
        row = con.execute(
            "SELECT COUNT(*), AVG(risco_score),"
            " SUM(CASE WHEN classificacao IN ('crítico','alto') THEN 1 ELSE 0 END),"
            " SUM(CASE WHEN veredito_perito='confirmado' THEN 1 ELSE 0 END),"
            " SUM(CASE WHEN veredito_perito='descartado' THEN 1 ELSE 0 END)"
            " FROM pericias WHERE cnpj=?", (cnpj,)
        ).fetchone()
    finally:
        con.close()
    if not row or not row[0]:
        return None
    return PerfilFornecedor(
        cnpj=cnpj, total_pericias=int(row[0]),
        risco_medio=round(float(row[1] or 0), 1),
        criticos_e_altos=int(row[2] or 0),
        confirmados=int(row[3] or 0), descartados=int(row[4] or 0),
    )


def estatisticas() -> dict:
    """Visão geral da memória (para o painel e o relatório do ciclo)."""
    con = _conectar()
    try:
        total, com_achado, confirmadas = con.execute(
            "SELECT COUNT(*),"
            " SUM(CASE WHEN achados != '[]' THEN 1 ELSE 0 END),"
            " SUM(CASE WHEN veredito_perito='confirmado' THEN 1 ELSE 0 END)"
            " FROM pericias").fetchone()
        categorias = con.execute(
            "SELECT categoria, COUNT(*) FROM pericias WHERE categoria != ''"
            " GROUP BY categoria ORDER BY 2 DESC LIMIT 10").fetchall()
    finally:
        con.close()
    return {
        "total_pericias": int(total or 0),
        "com_achados": int(com_achado or 0),
        "confirmadas_pelo_perito": int(confirmadas or 0),
        "categorias_mais_periciadas": [
            {"categoria": c, "n": n} for c, n in categorias
        ],
    }
