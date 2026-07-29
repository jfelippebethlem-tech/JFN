# -*- coding: utf-8 -*-
"""Detector C8 — agente público no QSA da contratada (conflito de interesses).

Fecha a lacuna `servidor_socio` do catálogo canônico, que estava `parcial` com a nota exata do
problema: *"folha × QSA em cruzamentos_intel, corroboração por fragmento de CPF — **fora do
REGISTRO**"*. A leitura existia e era boa; o que não existia era o grau de flag, a escalada e o
painel adversarial que só chegam a quem passa pelo pipeline de detector.

TRÊS SITUAÇÕES JURIDICAMENTE DISTINTAS, e tratá-las como uma só era o risco:

  1. **Impedimento do art. 9º** — o servidor é do PRÓPRIO órgão contratante. A Lei 14.133/2021
     art. 9º, I e §1º veda a participação de agente público do órgão na licitação, direta ou
     indiretamente. É vedação objetiva: `teste_objetivo='violado'`.
  2. **Vedação de gerência** — o servidor ADMINISTRA empresa privada. O art. 117, X da Lei 8.112
     (e os estatutos estaduais que o espelham) proíbe a gerência, ainda que a empresa contrate com
     outro órgão. Grave, mas é ilícito funcional, não impedimento licitatório.
  3. **Mero quotista** — participação societária sem gerência pode ser LÍCITA. Tratá-la como as
     duas anteriores produziria acusação contra servidor que herdou cotas.

O CASAMENTO, e o detalhe que faz a diferença: as duas fontes mascaram o CPF em JANELAS
DIFERENTES — a RFB publica os dígitos D4–D9 (`***364817**`) e a folha de pagamento publica D3–D8
(`XX000057XXX`). O trecho comparável é D4–D8, cinco dígitos. Compará-los como se estivessem
alinhados descartaria como "homônimo" quase todo casamento verdadeiro. O detector recebe os
fragmentos já extraídos e aplica a mesma regra de `cruzamentos_intel.socio_servidor`, que já
acerta isso — aqui não se reimplementa nada, apenas se gradua.

Régua (âncoras no CÓDIGO):
  • gerência + mesmo órgão contratante ............ 'critico' (1.0), teste_objetivo='violado'
  • mesmo órgão contratante, sem gerência ......... 'forte'
  • gerência, órgão diverso ....................... 'forte'
  • quotista sem gerência, órgão diverso .......... 'medio'
  • casamento só por NOME (sem fragmento) ......... rebaixa um nível e declara
  • fragmento de CPF CONFLITANTE .................. descartado (homônimo)
  • sem lista de sócios ou de servidores ........... nao_avaliavel (INDISPONÍVEL ≠ 0)
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from typing import Any

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora

# Qualificações da RFB que caracterizam GERÊNCIA (não mero quotista).
_RX_GERENCIA = re.compile(r"ADMINISTRADOR|DIRETOR|PRESIDENTE|GERENTE|TITULAR|S[ÓO]CIO-ADMIN")
# Rebaixamento por falta de corroboração documental.
_MENOS_UM = {"critico": "forte", "forte": "medio", "medio": "fraco"}


def _norm(s: Any) -> str:
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]+", " ", t)).strip()


def _frag(doc: Any) -> str:
    """Os 6 dígitos visíveis de um CPF mascarado; '' quando não é máscara de CPF."""
    d = re.sub(r"\D", "", str(doc or ""))
    return d if len(d) == 6 else ""


def casa_fragmento(frag_socio: str, frag_folha: str) -> bool | None:
    """As duas janelas se sobrepõem em D4–D8. `None` = um dos lados não tem fragmento.

    A RFB mostra D4–D9 e a folha D3–D8; o trecho comum é D4–D8, ou seja, os cinco PRIMEIROS
    dígitos do fragmento da RFB contra os cinco ÚLTIMOS do fragmento da folha. Comparar as
    strings inteiras como se fossem a mesma janela é o erro que descartaria o casamento certo.
    """
    if not frag_socio or not frag_folha:
        return None
    return frag_socio[0:5] == frag_folha[1:6]


def montar_ctx_servidores(con: sqlite3.Connection, nomes: list[str]) -> list[dict]:
    """Servidores da folha cujos nomes batem com os do QSA — no formato que o C8 consome."""
    alvo = {_norm(n) for n in nomes if _norm(n)}
    if not alvo:
        return []
    try:
        linhas = con.execute(
            "SELECT nome, cpf, orgao_nome, cargo, vinculo, fonte FROM registros_folha "
            "WHERE COALESCE(nome,'') <> ''").fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"nome": r[0], "cpf": r[1], "orgao": r[2], "cargo": r[3], "vinculo": r[4],
             "fonte": r[5]} for r in linhas if _norm(r[0]) in alvo]


class C8ServidorSocio(Detector):
    """Detector C8 — agente público no quadro societário da contratada."""

    id = "C8"
    nome = "Servidor público no QSA da contratada"
    familia = "perfil"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        socios = contexto.get("socios")
        servidores = contexto.get("servidores")
        if not socios or servidores is None:
            res.motivo_refutacao = (
                "nao_avaliavel: sem QSA da contratada ou sem lista de servidores "
                "(INDISPONÍVEL ≠ 0) — usar montar_ctx_servidores antes")
            return res

        orgao_contratante = _norm(contexto.get("orgao_contratante"))
        por_nome: dict[str, list[dict]] = {}
        for s in servidores:
            por_nome.setdefault(_norm(s.get("nome")), []).append(s)

        achados, homonimos = [], 0
        for socio in socios:
            nome = _norm(socio.get("nome") or socio.get("nome_socio"))
            cands = por_nome.get(nome)
            if not nome or not cands:
                continue
            frag_s = _frag(socio.get("doc") or socio.get("cpf") or socio.get("doc_socio"))
            escolhido, corroborado, conflitou = None, False, False
            for c in cands:
                bate = casa_fragmento(frag_s, _frag(c.get("cpf")))
                if bate is True:
                    escolhido, corroborado = c, True
                    break
                if bate is False:
                    conflitou = True
                elif escolhido is None:
                    escolhido = c            # só o nome — vale, mas rebaixado
            if escolhido is None:
                # todos os candidatos têm fragmento e TODOS conflitam ⇒ homônimo, não achado
                if conflitou:
                    homonimos += 1
                continue
            achados.append({
                "socio": socio.get("nome") or socio.get("nome_socio"),
                "qualificacao": socio.get("qualificacao") or socio.get("qualificacao_txt") or "",
                "gerencia": bool(_RX_GERENCIA.search(
                    _norm(socio.get("qualificacao") or socio.get("qualificacao_txt")))),
                "orgao_servidor": escolhido.get("orgao") or "",
                "cargo": escolhido.get("cargo") or "", "vinculo": escolhido.get("vinculo") or "",
                "corroborado_por_cpf": corroborado,
                "mesmo_orgao": bool(orgao_contratante
                                    and orgao_contratante == _norm(escolhido.get("orgao"))),
            })

        res.valores = {"n_socios": len(socios), "n_achados": len(achados),
                       "homonimos_descartados": homonimos,
                       "orgao_contratante_informado": bool(orgao_contratante)}

        if not achados:
            res.status = "descartado"
            res.motivo_refutacao = (
                f"nenhum sócio consta na folha ({homonimos} homônimo(s) descartado(s) por "
                "fragmento de CPF conflitante)" if homonimos else
                "nenhum sócio da contratada consta nas folhas de pagamento coletadas")
            return res

        # o mais grave manda: art. 9º primeiro, depois gerência, depois corroboração
        achados.sort(key=lambda a: (not a["mesmo_orgao"], not a["gerencia"],
                                    not a["corroborado_por_cpf"]))
        a = achados[0]
        if a["mesmo_orgao"] and a["gerencia"]:
            nivel, fundamento = "critico", "Lei 14.133/2021 art. 9º, I e §1º (impedimento)"
        elif a["mesmo_orgao"] or a["gerencia"]:
            nivel = "forte"
            fundamento = ("Lei 14.133/2021 art. 9º, I (agente do órgão contratante)"
                          if a["mesmo_orgao"] else
                          "vedação estatutária de gerência de empresa privada (Lei 8.112 art. 117, X "
                          "e estatutos estaduais correlatos)")
        else:
            nivel = "medio"
            fundamento = ("participação societária SEM gerência e em órgão diverso — pode ser "
                          "lícita; apurar impedimento concreto")

        if not a["corroborado_por_cpf"]:
            nivel = _MENOS_UM.get(nivel, nivel)

        res.score = ancora(nivel)
        res.status = "confirmado"
        # Só o impedimento do art. 9º é teste objetivo; gerência e quotista exigem apuração.
        res.valores["teste_objetivo"] = ("violado" if (a["mesmo_orgao"] and a["gerencia"]
                                                      and a["corroborado_por_cpf"])
                                         else "nao_aferivel")
        res.evidencia = [(
            f"{a['socio']} consta no QSA como '{a['qualificacao'] or 'sócio'}' e na folha de "
            f"{a['orgao_servidor'] or 'órgão não identificado'} como {a['cargo'] or 'servidor'} "
            f"({a['vinculo'] or 'vínculo não declarado'}) — {fundamento}. Casamento "
            + ("corroborado por fragmento de CPF (janelas D4–D8)."
               if a["corroborado_por_cpf"] else
               "APENAS POR NOME, sem fragmento de CPF para corroborar: grau rebaixado um nível, "
               "conferir CPF completo antes de qualquer imputação.")
        )]
        if len(achados) > 1:
            res.evidencia.append(f"Outros {len(achados) - 1} sócio(s) da contratada também "
                                 "constam em folha pública.")
        return res
