#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v61 fase 7b — baixa as FONTES OFICIAIS gratuitas dos cadastros territoriais e grava os CSVs
versionados em `compliance_agent/territorio/dados/` (cada linha com a sua fonte).

  distritos_rj.csv   IBGE, API de localidades v1 (estados/33/distritos) — distrito → município
  isp_unidades.csv   ISP-RJ, BaseDPEvolucaoMensalCisp.csv — DP (CISP) → município; BPM (AISP) → município
                     só quando a área é de UM município
  cnes_unidades.csv  Ministério da Saúde, API de dados abertos do CNES — hospitais, UPAs e pronto-socorros
                     do RJ + unidades básicas da capital (nome → município / AP)

  sedes_orgaos.csv   PNCP, cadastro de unidades do órgão (orgaos/42498600000171/unidades) — unidade compradora →
                     município de registro (a SEDE). Só serve ao grau `sede`, o mais fraco da atribuição.

NÃO baixado: Censo Escolar/INEP — `download.inep.gov.br` apresenta cadeia TLS que não valida nesta VM,
e baixar sem verificação de certificado não é aceitável. As escolas vêm do cadastro local do TSE.

Uso: .venv/bin/python tools/v61_territorio_fontes.py     (precisa de rede; ~2 min; educado com a API)
"""
from __future__ import annotations

import collections
import csv
import gzip
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from compliance_agent.territorio.geo import bairros, municipios, norm  # noqa: E402

DADOS = REPO / "compliance_agent" / "territorio" / "dados"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/csv,*/*"}


def _get(url: str, timeout: int = 90) -> bytes:
    for tent in range(3):
        try:
            dado = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
            return gzip.decompress(dado) if dado[:2] == b"\x1f\x8b" else dado       # o IBGE responde gzip sem pedir
        except OSError:
            time.sleep(2)
    raise SystemExit(f"falhou: {url}")


def distritos() -> None:
    d = json.loads(_get("https://servicodados.ibge.gov.br/api/v1/localidades/estados/33/distritos"))
    sedes = {norm(m["nome"]) for m in municipios()}
    linhas = [(norm(x["nome"]), x["nome"], str(x["municipio"]["id"]), x["municipio"]["nome"]) for x in d
              if norm(x["nome"]) != norm(x["municipio"]["nome"])]
    cnt = collections.Counter(r[0] for r in linhas)
    unicos = sorted(r for r in linhas if cnt[r[0]] == 1 and r[0] not in sedes)
    with open(DADOS / "distritos_rj.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["nome_norm", "distrito", "cod_ibge", "municipio", "fonte"])
        for r in unicos:
            w.writerow([*r, "IBGE — API de localidades v1 (estados/33/distritos)"])
    print(f"distritos: {len(unicos)} únicos de {len(d)}")


def isp() -> None:
    por_nome = {norm(m["nome"]): m["cod_ibge"] for m in municipios()}
    txt = _get("https://www.ispdados.rj.gov.br/Arquivos/BaseDPEvolucaoMensalCisp.csv").decode("latin-1")
    dp, bpm = collections.defaultdict(set), collections.defaultdict(set)
    for r in csv.DictReader(txt.splitlines(), delimiter=";"):
        if r["ano"] >= "2024":
            dp[r["cisp"]].add(norm(r["munic"]))
            bpm[r["aisp"]].add(norm(r["munic"]))
    fonte = "ISP-RJ — BaseDPEvolucaoMensalCisp.csv (2024+)"
    with open(DADOS / "isp_unidades.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tipo", "numero", "cod_ibge", "fonte"])
        for tipo, mapa, nota in (("DP", dp, "circunscrição da delegacia"), ("BPM", bpm, "AISP de município único")):
            for k, v in sorted(mapa.items(), key=lambda x: int(x[0])):
                if len(v) == 1 and next(iter(v)) in por_nome:
                    w.writerow([tipo, k, por_nome[next(iter(v))], f"{fonte} — {nota}"])
    print(f"ISP: {len(dp)} DPs, {len(bpm)} AISP lidas")


def cnes() -> None:
    def pega(params: str) -> list:
        regs, off = [], 0
        while True:
            e = json.loads(_get(f"https://apidadosabertos.saude.gov.br/cnes/estabelecimentos?{params}&limit=20&offset={off}", 40)).get("estabelecimentos") or []
            regs += e
            if len(e) < 20:
                return regs
            off += 20
            time.sleep(0.15)
    tudo = []
    for tipo in (5, 7, 73, 20, 21, 15, 62):
        tudo += pega(f"codigo_uf=33&codigo_tipo_unidade={tipo}&status=1")
    tudo += pega("codigo_municipio=330455&codigo_tipo_unidade=2&status=1")
    ibge = {m["cod_ibge"][:6]: m["cod_ibge"] for m in municipios()}
    ap_bairro = {norm(b["bairro"]): int(b["ap"]) for b in bairros()}
    fonte = "CNES — API de dados abertos do Ministério da Saúde (estabelecimentos ativos)"
    linhas = {}
    for e in tudo:
        nome = norm(e.get("nome_fantasia") or e.get("nome_razao_social"))
        cod = ibge.get(str(e.get("codigo_municipio")))
        if not nome or not cod:
            continue
        ap = ""
        m = re.search(r" AP (\d) ?(\d)$", nome)                # as unidades da SMS-Rio trazem a AP no nome ("… AP 51")
        if cod == "3304557":
            ap = m.group(1) if m else str(ap_bairro.get(norm(e.get("bairro_estabelecimento")), ""))
        base = re.sub(r" AP \d ?\d$", "", nome)
        base = re.sub(r"^(SES RJ|SMS RIO|SMS RJ|SMS|SEAP RJ|UERJ|SEPPEN CGSP RJ) ", "", base)
        base = re.sub(r"\bHOSP EST\b", "HOSPITAL ESTADUAL", base)
        base = re.sub(r"^CF ", "CLINICA DA FAMILIA ", base)
        base = re.sub(r"^CMS ", "CENTRO MUNICIPAL DE SAUDE ", base)
        base = re.sub(r"^UPA 24 ?H(?:ORAS)? ", "UPA ", base)
        if len(base.split()) < 2:
            continue
        linhas[(base, cod)] = [base, cod, ap, (e.get("descricao_esfera_administrativa") or "").strip(), e.get("codigo_cnes"), fonte]
    por_nome = collections.Counter(k[0] for k in linhas)
    with open(DADOS / "cnes_unidades.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["nome_norm", "cod_ibge", "ap", "esfera", "cnes", "fonte"])
        for (nome, _c), r in sorted(linhas.items()):
            if por_nome[nome] == 1:                              # nome que existe em 2 municípios não entra
                w.writerow(r)
    print(f"CNES: {sum(1 for k in linhas if por_nome[k[0]] == 1)} unidades de nome único (de {len(tudo)} lidas)")


# Unidades cujo cadastro no PNCP diz "Rio de Janeiro" mas cuja sede, segundo o próprio órgão, fica FORA da capital
# (ou do Estado). O cadastro diverge do endereço público: a linha sai SEM município e o grau `sede` não as atribui.
_SEDE_DIVERGENTE = ("UNIV EST DO NORTE FLUMINENSE", "INSTITUTO VITAL BRAZIL", "EMPR DE ASSIST TECN E EXT RURAL", "EMPR DE PESQUISA AGROPECUARIA",
                    "INSTITUTO DE PESCA", "DEPART RECURSOS MINERAIS", "AGRICULTURA", "REPRES DO GOV EM BSB", "IMPRENSA OFICIAL")


def sedes() -> None:
    from compliance_agent.territorio.atribui_estado import CNPJ_ESTADO, esfera_unidade
    us = json.loads(_get(f"https://pncp.gov.br/api/pncp/v1/orgaos/{CNPJ_ESTADO}/unidades", 120))
    validos = {m["cod_ibge"] for m in municipios()}
    por: dict[str, set] = collections.defaultdict(set)
    nomes = {}
    for u in us:
        n = norm(u.get("nomeUnidade"))
        if not n or esfera_unidade(u.get("nomeUnidade")) != "estadual":
            continue
        por[n].add(str((u.get("municipio") or {}).get("codigoIbge") or ""))
        nomes[n] = (u.get("nomeUnidade") or "").strip()
    fonte = "PNCP — cadastro de unidades do órgão 42.498.600/0001-71 (município de registro da unidade), lido em " + time.strftime("%d/%m/%Y")
    n_ok = 0
    with open(DADOS / "sedes_orgaos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["unidade_norm", "unidade", "cod_ibge", "situacao", "fonte"])
        for n, cods in sorted(por.items()):
            cod = next(iter(cods)) if len(cods) == 1 else ""
            if any(d in n for d in _SEDE_DIVERGENTE):
                w.writerow([n, nomes[n], "", "divergente", fonte + " — o cadastro diz capital, a sede pública do órgão não: NÃO atribuído"])
            elif cod in validos:
                w.writerow([n, nomes[n], cod, "pncp", fonte])
                n_ok += 1
            else:
                w.writerow([n, nomes[n], "", "sem_municipio", fonte + " — unidade em mais de um município ou fora do RJ"])
    print(f"sedes: {n_ok} unidades estaduais com município de registro (de {len(por)})")


if __name__ == "__main__":
    if sys.argv[1:] == ["sedes"]:
        sedes()
        sys.exit(0)
    distritos()
    isp()
    cnes()
    sedes()
