# -*- coding: utf-8 -*-
"""
Cotações da pesquisa de preços lidas dos AUTOS → contexto do P2 (cotações combinadas / orçamento de fachada).

POR QUE EXISTE. O P2 (`detectores/p2_cotacoes_combinadas`) estava no REGISTRO, testado e sem caller que lhe desse
`cotacoes`: ninguém montava a lista — sétimo "construído, testado, nunca rodado" da casa. As cotações estão no
acervo do SEI (pesquisa de preços, propostas, mapas), e o contato de cada cotante está na base da Receita local.

COMO SE RECONHECE UM COTANTE — regras medidas no acervo em 31/10/2026 (6.086 processos):
  • documento de pesquisa de preço/proposta/cotação com UM SÓ CNPJ privado = a cotação daquele fornecedor. CNPJ
    citado de passagem não é cotante: a versão que juntava todos os CNPJs do documento achou 13 "pares ligados" e o
    maior era uma página de site com as duas empresas do Grupo Orzil — uma fonte, não duas cotações;
  • pessoa jurídica de direito público (natureza 1xxx) fica fora; filiais do mesmo CNPJ básico contam uma vez;
  • ENDEREÇO só com a SALA: QUATTUOR, JESBAN e CONSTRUIR "dividiam" a Av. Pastor Martin Luther King 126 — salas
    1213, 1301 e 1316 do mesmo complexo. Mesmo prédio não é vínculo ([[ninho-mesma-sala-nao-predio]]);
  • e-mail de contabilidade vira CONTADOR (o P2 o gradua fraco, exculpatória regional), e o telefone desse cadastro
    também — é o do escritório, não o da empresa.
Resultado: 115 processos com 2+ cotantes de documento próprio; 2 com vínculo forte (GRANÁ 298 × GUARAILHA,
mesmo telefone, cotando na SEPM e na SECC).
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

_RECEITA = Path(os.environ.get("JFN_RECEITA_DB") or Path(__file__).resolve().parents[2] / "data" / "receita_estab.db")
_CNPJ = re.compile(r"\b(\d{2})\.?(\d{3})\.?(\d{3})/?(\d{4})-?(\d{2})\b")
_TITULO = re.compile(r"pesquisa de pre|cota[cç][aã]o|or[cç]amento|mapa comparativo|planilha comparativa|proposta", re.I)
_TIPOS = ("pesquisa_precos", "planilha_preco", "proposta")
_EMAIL_CONTADOR = re.compile(r"contab|contador|escritorio|assessoria", re.I)


def cnpj_valido(c: str) -> bool:
    if len(c) != 14 or len(set(c)) == 1:
        return False
    def dv(n: str, pesos: list[int]) -> str:
        r = sum(int(a) * b for a, b in zip(n, pesos)) % 11
        return "0" if r < 2 else str(11 - r)
    p = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return c[12] == dv(c[:12], p) and c[13] == dv(c[:13], [6] + p)


def _cadastro(con: sqlite3.Connection, cnpj: str) -> dict | None:
    r = con.execute("SELECT e.telefone1, e.correio_eletronico, e.endereco_norm, TRIM(COALESCE(e.complemento, '')), "
                    "m.natureza_cod, m.razao_social FROM estabelecimentos e LEFT JOIN empresas m "
                    "ON m.cnpj_basico = e.cnpj_basico WHERE e.cnpj = ?", (cnpj,)).fetchone()
    if not r:
        return None
    tel, email, end, compl, nat, razao = r
    contador = email if email and _EMAIL_CONTADOR.search(email) else ""
    return {"publico": str(nat or "").startswith("1"), "razao": razao or "",
            # cadastro feito pelo CONTADOR (e-mail dele): o telefone também é do escritório — FORTALEZA AMBIENTAL ×
            # ÁGUAS DE PÁDUA "dividiam" o telefone da cmmcontabilidade. Vira contador (fraco), não telefone comum.
            "contato": {"telefone": "" if contador else (tel or ""), "email": "" if contador else (email or ""),
                        # sem sala não se afirma "mesmo lugar": prédio comercial tem centenas de CNPJs
                        "endereco": f"{end} | {compl}" if end and compl else "",
                        "contador": contador}}


def montar_cotacoes(docs: list[dict], receita: Path | None = None) -> list[dict]:
    """`docs` = [{ref, tipo, texto}] → [{cnpj, razao, contato, contador, evidencia}] dos cotantes de documento próprio."""
    alvo = [d for d in docs or [] if d.get("tipo") in _TIPOS or _TITULO.search(str(d.get("ref") or ""))]
    if not alvo:
        return []
    caminho = receita or _RECEITA
    if not caminho.exists():
        return []
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        cache: dict[str, dict | None] = {}
        cotantes: dict[str, dict] = {}
        for d in alvo:
            achados = {"".join(g) for g in _CNPJ.findall(d.get("texto") or "")}
            privados = []
            for c in sorted(x for x in achados if cnpj_valido(x)):
                if c not in cache:
                    cache[c] = _cadastro(con, c)
                if cache[c] and not cache[c]["publico"]:
                    privados.append(c)
            if len(privados) != 1:
                continue                         # citação de passagem ou matriz com vários: não é cotação de um
            c = privados[0]
            if c[:8] in {k[:8] for k in cotantes}:
                continue
            info = cache[c]
            cotantes[c] = {"cnpj": c, "razao": info["razao"], "contato": info["contato"],
                           "contador": info["contato"]["contador"], "evidencia": str(d.get("ref") or "")}
        return list(cotantes.values())
    finally:
        con.close()
