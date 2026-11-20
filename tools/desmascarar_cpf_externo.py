#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""desmascarar_cpf_externo — camada 3 (externa, POR ALVO) do desmascaramento de CPF de sócio do QSA.

Estado medido em 19/11/2026 (sondas do it-campo, rede residencial, uma requisição por fonte):
nenhuma fonte pública que devolva CPF por NOME passou nos critérios da casa (sem captcha, ToS/robots
permitindo, pública e oficial) — ver `FONTES_AVALIADAS`. Por isso `--executar` só roda fonte que esteja em
`FONTES_AUTORIZADAS` (hoje VAZIA): captcha não se contorna, vira FILA HUMANA.

Modos:
  --fila N        monta `data/cpf_fila_humana.json`: os N sócios mascarados ainda sem CPF conferido, das
                  empresas com MAIS OB PAGA no SIAFE (Regra 2), com a máscara e o nº de candidatos — nada de CPF.
  --confirmar     o humano (noVNC, resolvendo o captcha ele mesmo) achou um CPF numa fonte pública: digita-o
                  (stdin oculto, nunca na linha de comando), e só grava se os 6 dígitos do meio baterem a máscara
                  do QSA (anti-homônimo, `confirmar_cpf`). Registra a consulta SEM o CPF.
  (padrão)        dry-run por alvo (--cnpj ou --nome/--doc): mostra o espaço de candidatos, sem consulta externa.

LGPD: CPF completo só no banco (`socios_fornecedor.cpf_resolvido`); log/tela/registro só com máscara.
Uso:
  PYTHONPATH=. .venv/bin/python -m tools.desmascarar_cpf_externo --fila 200
  PYTHONPATH=. .venv/bin/python -m tools.desmascarar_cpf_externo --confirmar --cnpj 05707413000124 \\
      --nome "FULANO DE TAL" --fonte tjrj_consulta_publica_humano
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compliance_agent import cpf_externo as ce  # noqa: E402
from compliance_agent.credor_institucional import natureza_fora  # noqa: E402
from compliance_agent.resolucao_cpf import _digitos, _norm, confirmar_cpf  # noqa: E402

from compliance_agent.collectors.arquivos import dir_dados  # noqa: E402

_DB = dir_dados() / "compliance.db"
_FILA = dir_dados() / "cpf_fila_humana.json"

# Fontes externas avaliadas em 19/11/2026 (sonda do it-campo; da VM-1 várias nem respondem — datacenter).
FONTES_AVALIADAS = {
    "tjrj_consulta_publica": "busca por nome da parte EXISTE, mas exige reCAPTCHA/hCaptcha → só fila humana",
    "trt1_pje_consulta": "sem busca por nome; detalhe do processo exige desafio (tokenDesafio/captcha) → fora",
    "trf2_eproc_consulta_publica": "consulta pública exige captcha → só fila humana",
    "escavador": "robots.txt proíbe /busca → fora (ToS)",
    "jusbrasil": "devolve página de captcha (anti-robô) já no robots.txt → fora",
    "querido_diario_api": "api.queridodiario.ok.org.br sem resposta (000) da VM-1 e do it-campo → INDISPONÍVEL",
    "datajud_cnj": "só metadados, sem parte nem CPF → fora (limites_de_fonte)",
    "receita_situacao_cadastral": "exige data de nascimento + hCaptcha → fora",
    "situacao_cadastral_com": "espelho não oficial da Receita, Cloudflare/captcha → fora (nunca fonte não oficial)",
}
FONTES_AUTORIZADAS: dict[str, object] = {}   # nome → provider; vazio até uma fonte passar nos critérios


def _con(ro: bool = True) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{_DB}?mode=ro" if ro else str(_DB), uri=ro, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    con.row_factory = sqlite3.Row
    return con


def _mask(doc: str) -> str:
    d = _digitos(doc)
    return f"***.{d[:3]}.{d[3:6]}-**" if len(d) == 6 else "?"


def registrar_consulta(con: sqlite3.Connection, nome: str, doc: str, fonte: str, modo: str, resultado: str,
                       n_consultas: int, motivo: str) -> None:
    """Registro de cada consulta externa/humana: fonte, data, resultado — o alvo vai como hash, NUNCA o CPF."""
    con.execute("CREATE TABLE IF NOT EXISTS cpf_consulta_externa (em TEXT, alvo_hash TEXT, fonte TEXT, modo TEXT, "
                "resultado TEXT, n_consultas INTEGER, motivo TEXT)")
    alvo = hashlib.sha256(f"{_norm(nome)}|{_digitos(doc)}".encode()).hexdigest()[:16]
    con.execute("INSERT INTO cpf_consulta_externa VALUES (?,?,?,?,?,?,?)",
                (dt.datetime.now().isoformat(timespec="seconds"), alvo, fonte, modo, resultado, n_consultas,
                 motivo[:300]))
    con.commit()


# Natureza jurídica (tabela da Receita) que NÃO entra na fila humana: diretor de ente público, estatal ou companhia
# aberta é cargo de mercado/governo, não sócio de fachada — 71 das 200 vagas eram diretores do Banco do Brasil (19/11/2026).
# natureza_fora: régua única em compliance_agent/credor_institucional.py (1xxx · 2011 · 2038 · 2046 · 3328).
POR_EMPRESA = 3


def priorizar(fila: list[dict], natureza: dict[str, str], n: int, por_empresa: int = POR_EMPRESA) -> list[dict]:
    """Ordena pela OB paga, tira natureza pública/aberta e limita sócios por empresa (variedade de alvos)."""
    out, cont = [], {}
    for it in sorted(fila, key=lambda x: -x["ob_paga_siafe"]):
        if natureza_fora(natureza.get(it["cnpj"][:8])):
            continue
        if cont.get(it["cnpj"], 0) >= por_empresa:
            continue
        cont[it["cnpj"]] = cont.get(it["cnpj"], 0) + 1
        out.append(it)
        if len(out) >= n:
            break
    return out


def _naturezas(cnpjs: set[str]) -> dict[str, str]:
    db = _DB.parent / "receita_estab.db"
    if not db.exists():
        return {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    try:
        bas = sorted({c[:8] for c in cnpjs})
        out = {}
        for i in range(0, len(bas), 500):
            lote = bas[i:i + 500]
            out.update(con.execute(f"SELECT cnpj_basico, natureza_cod FROM empresas WHERE cnpj_basico IN "
                                   f"({','.join('?' * len(lote))})", lote).fetchall())
        return out
    finally:
        con.close()


def montar_fila(n: int) -> list[dict]:
    """Sócios mascarados sem CPF conferido, ordenados pela OB PAGA (SIAFE) da empresa. Sem CPF na saída."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    con = _con()
    try:
        paga = _ob_paga(con)
        ob = {r[0]: (r[1], r[2]) for r in con.execute(
            f"SELECT credor, SUM(valor), COUNT(*) FROM ob_orcamentaria_siafe WHERE {paga} AND valor>0 "
            "AND length(credor)=14 GROUP BY credor")}
        fila = []
        for r in con.execute("SELECT cnpj, razao, socio_nome, socio_doc, qualificacao, cpf_pos3a9 FROM socios_fornecedor "
                             "WHERE socio_doc LIKE '%*%' AND (cpf_resolvido IS NULL OR cpf_resolvido='')"):
            v = ob.get(r["cnpj"])
            if not v:
                continue
            p39 = _digitos(r["cpf_pos3a9"] or "")
            fila.append({"cnpj": r["cnpj"], "empresa": r["razao"] or "", "socio": r["socio_nome"],
                         "cpf_mascarado": _mask(r["socio_doc"]), "qualificacao": r["qualificacao"] or "",
                         "ob_paga_siafe": round(v[0], 2), "n_ob": v[1],
                         "candidatos_validos": 100 if len(p39) == 7 else 1000,
                         "fonte_humana_sugerida": "TJRJ consulta pública por nome (captcha resolvido pelo humano)",
                         "status": "PENDENTE"})
        return priorizar(fila, _naturezas({f["cnpj"] for f in fila}), n)
    finally:
        con.close()


def confirmar_humano(cnpj: str, nome: str, cpf: str, fonte: str) -> dict:
    """Grava CPF achado por humano em fonte pública SÓ se bater a máscara do QSA do sócio (anti-homônimo)."""
    con = _con(ro=False)
    try:
        row = con.execute("SELECT rowid, socio_nome, socio_doc FROM socios_fornecedor WHERE cnpj=? AND socio_nome_norm=?",
                          (_digitos(cnpj), _norm(nome))).fetchone()
        if not row:
            row = next((r for r in con.execute("SELECT rowid, socio_nome, socio_doc FROM socios_fornecedor WHERE cnpj=?",
                                               (_digitos(cnpj),)) if _norm(r["socio_nome"]) == _norm(nome)), None)
        if not row:
            return {"gravado": False, "motivo": "sócio não encontrado no QSA desta empresa"}
        conf = confirmar_cpf(row["socio_nome"], cpf, row["socio_doc"])
        if not conf["confirmado"]:
            registrar_consulta(con, nome, row["socio_doc"], fonte, "humano", "REJEITADO", 1, conf["motivo"])
            return {"gravado": False, "motivo": conf["motivo"]}
        con.execute("UPDATE socios_fornecedor SET cpf_resolvido=?, cpf_fonte=?, cpf_confianca=?, cpf_resolvido_em=? "
                    "WHERE rowid=?", (conf["cpf"], f"humano:{fonte}", 0.9,
                                      dt.datetime.now().isoformat(timespec="seconds"), row["rowid"]))
        con.commit()
        registrar_consulta(con, nome, row["socio_doc"], fonte, "humano", "CONFIRMADO", 1,
                           "6 dígitos do meio batem a máscara do QSA")
        return {"gravado": True, "motivo": "CPF confere a máscara do QSA (1:1) — gravado só no banco",
                "cpf_mascarado": _mask(row["socio_doc"])}
    finally:
        con.close()


def _dry_run(nome: str, doc: str, pos3a9: str | None) -> None:
    cands = ce.candidatos_estreitados(doc, pos3a9)
    estreitado = len(_digitos(pos3a9 or "")) == 7 and len(cands) == 100
    print(f"• {nome}  [{_mask(doc)}]  → {len(cands)} candidatos válidos"
          f"{' (estreitado pela fusão de máscaras)' if estreitado else ''} — nenhuma consulta feita")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fila", type=int, default=0)
    ap.add_argument("--confirmar", action="store_true")
    ap.add_argument("--fonte", default="")
    ap.add_argument("--cnpj", default="")
    ap.add_argument("--nome", default="")
    ap.add_argument("--doc", default="")
    ap.add_argument("--pos3a9", default="")
    ap.add_argument("--executar", action="store_true", help="só com fonte em FONTES_AUTORIZADAS (hoje nenhuma)")
    a = ap.parse_args()

    if a.executar:
        print("RECUSADO: nenhuma fonte externa autorizada (todas exigem captcha, proíbem robô ou não respondem):")
        for f, m in FONTES_AVALIADAS.items():
            print(f"  - {f}: {m}")
        print("Use --fila para a fila humana (noVNC) e --confirmar para gravar o que o humano achar.")
        return 3
    if a.fila:
        fila = montar_fila(a.fila)
        _FILA.write_text(json.dumps({"gerado_em": dt.datetime.now().isoformat(timespec="seconds"),
                                     "criterio": "sócio mascarado sem CPF conferido × OB paga no SIAFE (desc.)",
                                     "fontes_avaliadas": FONTES_AVALIADAS, "itens": fila},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"fila humana: {len(fila)} alvos → {_FILA} (sem CPF; só máscara)")
        return 0
    if a.confirmar:
        if not (a.cnpj and a.nome and a.fonte):
            ap.error("--confirmar exige --cnpj, --nome e --fonte")
        cpf = getpass.getpass("CPF encontrado (não aparece na tela): ")
        print(json.dumps(confirmar_humano(a.cnpj, a.nome, cpf, a.fonte), ensure_ascii=False))
        return 0
    if a.cnpj:
        con = _con()
        try:
            rows = con.execute("SELECT socio_nome, socio_doc, cpf_pos3a9, cpf_resolvido FROM socios_fornecedor "
                               "WHERE cnpj=? AND socio_doc LIKE '%*%'", (_digitos(a.cnpj),)).fetchall()
        finally:
            con.close()
        pend = [r for r in rows if not (r["cpf_resolvido"] or "").strip()]
        print(f"CNPJ {a.cnpj}: {len(rows)} sócio(s) mascarado(s), {len(pend)} sem CPF conferido.")
        for r in pend:
            _dry_run(r["socio_nome"], r["socio_doc"], r["cpf_pos3a9"])
        return 0
    if a.nome and a.doc:
        _dry_run(a.nome, a.doc, a.pos3a9 or None)
        return 0
    ap.error("informe --fila N, --confirmar, --cnpj ou (--nome e --doc)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
