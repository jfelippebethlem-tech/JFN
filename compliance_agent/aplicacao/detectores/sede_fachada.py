# -*- coding: utf-8 -*-
"""E10 · `e10.c_sede_fachada` — sede de fachada por CONVERGÊNCIA de sinais já gravados (SOMBRA ⚖️, O5.3 fatia 2).

Porta a regra única de três sweeps da família C (fachada), SEM rede nesta fatia (nada de Nominatim, Overpass, Street
View ou Places — o que a captura gravou é o insumo; insumo ausente = INDISPONÍVEL, contado, nunca "limpo"):

  sede real (`tools/sweep_sede_real.py` → `verificacao_sede_real`)   SINAL-BASE quando apurável e o veredito é
      `suspeita` ou `forte_suspeita`; `apuravel = 0` (não dá para saber) é INDISPONÍVEL, nunca acusação.
  endereço (`tools/endereco_sweep.py` → `endereco_verificacao`)    2º SINAL quando `INDICIO` (baldio, município
      divergente, não resolvido, residencial). Só conta como segundo sinal — sozinho não marca ninguém (a regra do
      sweep: a verificação de endereço só roda nos já marcados). OSM ausente (`INDISPONIVEL`) ≠ baldio.
  Street View (`tools/fachada_streetview_sweep.py` → `verificacao_sede`)  2º SINAL quando a classe visual é adversa
      (baldio, residência, barraco, rural, via sem lote, fechado) e a foto NÃO foi confirmada pelo Google Places
      (`coerencia_google = 'confirma'` afasta). A imagem > 60% branca já foi rejeitada na captura (não vira classe);
      a herança por prédio (`predio_key`) já está gravada. Foto comercial/galpão é CONTRAPROVA: afasta o disparo.

Regra (decisão do dono 4, 24/11/2026 — versão 2): INDICIO = sinal-base ∧ (endereço ∨ foto adversa) ∧ ¬ contraprova,
com **dois sinais independentes e NÃO residenciais**. Imóvel residencial não é sinal (sede no domicílio do sócio é
lícita para empresa pequena): a foto `casa_residencial`/`predio_residencial`, o endereço cujo indício é ser
residencial e a sede real que só se apoia em `complemento_residencial` contam como RESIDENCIAIS. Sinal-base + 2º sinal
em que a convergência só fecha com o residencial → `INCERTO` (achado de contexto, não indício). Um só sinal fica no
resumo (não vira achado). Elegibilidade (invariante 3): o veredito `fornecedor` da E9 é do CREDOR, lido na maior OB paga do mesmo CNPJ
(`chave_e9`); CNPJ sem OB paga fica fora do universo (não é fornecedor pago), contado.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter

from compliance_agent.aplicacao.detectores import Carga, Disparo, elegivel
from compliance_agent.cpf_cnpj import digitos as dig
from compliance_agent.dominio.achado import Fato, Papel
from compliance_agent.dominio.pagamento import ob_paga_sql
from compliance_agent.reporting.intel_base import reais

ID = "e10.c_sede_fachada"
UNIDADE = "ob_siafe"
VERSAO = "e10-csede-2"
SEDE_SINAL = ("suspeita", "forte_suspeita")
FOTO_ADVERSA = ("terreno_baldio", "casa_residencial", "predio_residencial", "construcao_precaria_barraco",
                "via_sem_lote_visivel", "area_aberta_rural", "estabelecimento_fechado_abandonado")
FOTO_CONTRA = ("comercial_industrial", "galpao_logistico")
FOTO_RESIDENCIAL = ("casa_residencial", "predio_residencial")
FOTO_NAO_CONFIAVEL = "sem_foto_confiavel"            # prefixo de `visual_fonte` que a captura grava (endereço impreciso)
SEDE_RESIDENCIAL = "complemento_residencial"       # id do sinal de `verificacao_sede_real.sinais`


def _tabela(con, sql: str, par: tuple = ()) -> dict | None:
    """{cnpj: linha} ou None quando a tabela não existe (INDISPONÍVEL ≠ vazio)."""
    try:
        return {dig(r[0]): r[1:] for r in con.execute(sql, par)}
    except sqlite3.OperationalError:
        return None


def _ler(con: sqlite3.Connection, cnpj: str | None = None) -> Carga:
    f, par = ("WHERE cnpj = ?", (cnpj,)) if cnpj else ("", ())
    sede = _tabela(con, f"SELECT cnpj, veredito, apuravel, score_suspeita, sinais FROM verificacao_sede_real {f}", par)
    end = _tabela(con, f"SELECT cnpj, status, nivel, evidencia FROM endereco_verificacao {f}", par)
    foto = _tabela(con, f"SELECT cnpj, visual_classe, coerencia_google, predio_key, visual_fonte "
                        f"FROM verificacao_sede {f}", par)
    docs = sorted({d for t in (sede, end, foto) if t for d in t if len(d) == 14})
    paga = ob_paga_sql(con)
    itens, sem_ob = [], 0
    for d in docs:
        r = con.execute(f"SELECT ug_emitente, numero_ob, exercicio, count(*) OVER (), sum(valor) OVER () "
                        f"FROM ob_orcamentaria_siafe WHERE credor = ? AND {paga} ORDER BY valor DESC LIMIT 1",
                        (d,)).fetchone()
        if not r:
            sem_ob += 1
            continue
        s, e, v = (sede or {}).get(d), (end or {}).get(d), (foto or {}).get(d)
        itens.append({"chave_e9": f"{r[0]}|{r[1]}|{r[2]}", "grupo": d, "cnpj": d, "n_ob": r[3],
                      "pago": round(float(r[4] or 0), 2),
                      "sede": None if s is None else {"veredito": s[0], "apuravel": s[1], "score": s[2], "sinais": s[3]},
                      "endereco": None if e is None else {"status": e[0], "nivel": e[1], "evidencia": e[2]},
                      "foto": None if v is None else {"classe": v[0], "coerencia": v[1], "predio": v[2],
                                                      "fonte": v[3]}})
    return Carga(itens=itens, contexto={
        "cnpjs_nas_verificacoes": len(docs), "cnpjs_sem_ob_paga": sem_ob,
        "insumo_indisponivel": [n for n, t in (("verificacao_sede_real", sede), ("endereco_verificacao", end),
                                               ("verificacao_sede", foto)) if t is None]})


def carregar(con: sqlite3.Connection, exercicio: int | None = None) -> Carga:
    return _ler(con)


def grupo_de(d: Disparo) -> str:
    return d.grupo


def carregar_grupo(con: sqlite3.Connection, grupo: str, exercicio: int | None = None) -> Carga:
    return _ler(con, grupo)


def sinais(c: dict) -> dict:
    """Leitura de cada insumo: True (sinal), False (contraprova/afastado), None (INDISPONÍVEL)."""
    s, e, v = c["sede"], c["endereco"], c["foto"]
    base = None if not s or not s["apuravel"] else s["veredito"] in SEDE_SINAL
    ende = None if not e or e["status"] not in ("INDICIO", "AFASTADO") else e["status"] == "INDICIO"
    # 27/11/2026 — regra única #70 (força da evidência): foto que a captura declarou NÃO confiável (endereço impreciso:
    # pode nem ser do imóvel) não acusa nem afasta — INDISPONÍVEL
    classe = "" if str((v or {}).get("fonte") or "").startswith(FOTO_NAO_CONFIAVEL) else ((v or {}).get("classe") or "")
    foto = (False if classe in FOTO_CONTRA else
            (v["coerencia"] != "confirma") if classe in FOTO_ADVERSA else None)
    return {"sede": base, "endereco": ende, "foto": foto}


def _ids_suspeita(sinais_json) -> list[str] | None:
    """ids dos sinais da sede real na direção `suspeita`; None quando o campo não é lido (não se presume nada)."""
    try:
        lst = json.loads(sinais_json) if isinstance(sinais_json, str) else sinais_json
    except ValueError:
        return None
    if not isinstance(lst, list):
        return None
    return [str(x.get("id")) for x in lst if isinstance(x, dict) and x.get("direcao") == "suspeita"]


def residenciais(c: dict) -> dict:
    """Qual sinal é RESIDENCIAL (não serve para a convergência — decisão do dono 4): foto de casa/prédio residencial,
    endereço cujo indício cita residência, sede real cujos sinais de suspeita são só `complemento_residencial`."""
    s, e, v = c["sede"], c["endereco"], c["foto"]
    ids = _ids_suspeita((s or {}).get("sinais"))
    return {"sede": bool(ids) and all(i == SEDE_RESIDENCIAL for i in ids),
            "endereco": "residen" in str((e or {}).get("evidencia") or "").lower(),
            "foto": ((v or {}).get("classe") or "") in FOTO_RESIDENCIAL}


def detectar(itens: list[dict], contexto: dict | None = None) -> list[Disparo]:
    out = []
    for c in sorted(itens, key=lambda c: c["cnpj"]):
        if not elegivel(c):
            continue
        sg = sinais(c)
        segundo = [k for k in ("endereco", "foto") if sg[k]]
        if not (sg["sede"] and segundo) or sg["foto"] is False:
            continue
        res = residenciais(c)
        nao_res = [k for k in ("sede", "endereco", "foto") if sg[k] and not res[k]]
        estado = "INDICIO" if len(nao_res) >= 2 else "INCERTO"
        fatos = [Fato(papel=Papel.SUPORTE, tipo="sede_real", fonte="verificacao_sede_real", referencia=c["cnpj"],
                      descricao=f"sede real: {c['sede']['veredito']} (score {c['sede']['score']})",
                      dados={"sinais": c["sede"]["sinais"]})]
        if sg["endereco"]:
            fatos.append(Fato(papel=Papel.SUPORTE, tipo="endereco", fonte="endereco_verificacao", referencia=c["cnpj"],
                              descricao=str(c["endereco"]["evidencia"] or "")[:240],
                              dados={"nivel": c["endereco"]["nivel"]}))
        if sg["foto"]:
            fatos.append(Fato(papel=Papel.SUPORTE, tipo="foto_fachada", fonte="verificacao_sede", referencia=c["cnpj"],
                              descricao=f"classe visual {c['foto']['classe']} (Places: {c['foto']['coerencia'] or '—'})",
                              dados={"predio_key": c["foto"]["predio"], "fonte": c["foto"]["fonte"]}))
        so_res = ("" if estado == "INDICIO" else
                  " A convergência só fecha com sinal RESIDENCIAL (imóvel residencial não é sinal de fachada: sede no "
                  "domicílio do sócio é lícita) — fica como contexto, sem indício.")
        out.append(Disparo(
            chave=c["cnpj"], grupo=c["cnpj"], estado=estado,
            motivo_estado="" if estado == "INDICIO" else "2º sinal só residencial (decisão do dono 4, 24/11/2026)",
            observacao=(f"O fornecedor {c['cnpj']} (pago em {c['n_ob']} OB, {reais(c['pago'])}) tem sede real "
                        f"{c['sede']['veredito']} e {' e '.join(segundo)} como 2º sinal registrado.{so_res} Sede "
                        "administrativa diversa do local de execução é a hipótese inocente; vistoria e leitura do "
                        "processo decidem. Fonte: verificacao_sede_real × endereco_verificacao × verificacao_sede."),
            entradas={"cnpj": c["cnpj"], "sinais": sg, "residenciais": res, "sede": c["sede"],
                      "endereco": c["endereco"], "foto": c["foto"], "e9": c.get("e9")},
            valores={"segundo_sinal": segundo, "nao_residenciais": nao_res, "pago": c["pago"], "n_ob": c["n_ob"]},
            evidencias=fatos))
    return out


def resumo(itens: list[dict], disparos: list[Disparo]) -> dict:
    por = Counter(c.get("e9") or "?:SEM_LINHA_E9" for c in itens)
    lido = {k: Counter() for k in ("sede", "endereco", "foto")}
    for c in itens:
        for k, v in sinais(c).items():
            lido[k]["sinal" if v else ("contra" if v is False else "INDISPONIVEL")] += 1
    indet = sum(n for k, n in por.items() if k.startswith("?"))
    so_um = sum(1 for c in itens if elegivel(c) and sum(bool(v) for v in sinais(c).values()) == 1)
    return {"fornecedores_pagos_verificados": len(itens), "por_veredito": dict(sorted(por.items())),
            "leitura_por_insumo": {k: dict(v) for k, v in lido.items()}, "um_sinal_so": so_um,
            "cobertura": round(1 - indet / len(itens), 4) if itens else None, "disparos": len(disparos),
            "por_estado": dict(sorted(Counter(d.estado for d in disparos).items())),
            "soma_disparos": round(sum(d.valores["pago"] for d in disparos), 2),
            "soma_indicio": round(sum(d.valores["pago"] for d in disparos if d.estado == "INDICIO"), 2)}
