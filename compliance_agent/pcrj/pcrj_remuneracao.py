# -*- coding: utf-8 -*-
"""Consulta de REMUNERAÇÃO do servidor da Prefeitura do Rio (contrachequeapi.rio.gov.br).

O portal é JSF/PrimeFaces, mas o ``ViewState`` é client-side (gzip base64) → a busca
por NOME é replicável por POST puro (sem browser): rápido, paralelizável, VM-safe.
Não requer credencial (dado público); a cadeia TLS é incompleta → ``verify=False``.

A busca é por SUBSTRING no nome; o cruzamento (``cruzamento.py``) filtra por nome
NORMALIZADO idêntico. Sem CPF em nenhuma das bases → casamento por nome é INDÍCIO
(homônimo possível), nunca afirmação — honestidade dura do projeto.

Cada linha retornada traz: matrícula, nome, cargo/função, lotação (órgão/secretaria),
mês/ano, vantagens, descontos, valor líquido, datas de admissão/exoneração/inativação.
"""
from __future__ import annotations

import html
import re
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_BASE = "https://contrachequeapi.rio.gov.br"
_URL = _BASE + "/contrachequeapi/transparencia"
_COLS = ["matricula", "nome", "cargo", "lotacao", "mesano", "folha", "vantagens",
         "descontos", "valor_liquido", "acoes", "admissao", "exoneracao",
         "inativacao", "carga_horaria"]
_HDRS = {"Faces-Request": "partial/ajax", "X-Requested-With": "XMLHttpRequest",
         "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
         "Origin": _BASE, "Referer": _URL,
         "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def _texto(fragmento: str) -> str:
    t = re.sub(r"<[^>]+>", " ", fragmento or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


class Sessao:
    """Sessão HTTP com ViewState reaproveitado (stateless JSF). Renova sob demanda."""

    def __init__(self, timeout: int = 60, pausa: float = 0.0):
        self.timeout = timeout
        self.pausa = pausa                 # throttle pós-consulta (respeita o limite do servidor)
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": _HDRS["User-Agent"]})
        self._vs: str | None = None
        self._action: str | None = None

    def _renovar(self) -> None:
        h = self.s.get(_URL, verify=False, timeout=self.timeout).text
        self._vs = re.search(r'name="javax.faces.ViewState"[^>]*value="([^"]+)"', h).group(1)
        self._action = re.search(r'id="tabView:formFiltro"[^>]*action="([^"]+)"', h).group(1)

    def consultar_nome(self, nome: str, mes: int, ano: int,
                       tentativas: int = 2) -> list[dict] | None:
        """Retorna as linhas (dicts) da remuneração cujo nome CONTÉM ``nome`` na competência.

        ``None`` = erro/indisponível (degrada honesto, não confunde com 'nada encontrado' []).
        """
        for tent in range(tentativas):
            try:
                if not self._vs:
                    self._renovar()
                data = {
                    "javax.faces.partial.ajax": "true",
                    "javax.faces.source": "tabView:formFiltro:btnConsultar",
                    "javax.faces.partial.execute": "tabView:formFiltro",
                    "javax.faces.partial.render": "tabView:formFiltro divResultados growl",
                    "tabView:formFiltro:btnConsultar": "tabView:formFiltro:btnConsultar",
                    "tabView:formFiltro": "tabView:formFiltro",
                    "tabView:formFiltro:matriculaField:txtMatricula": "",
                    "tabView:formFiltro:nomeField:txtNome": nome,
                    "tabView:formFiltro:mesAnoField:txtMes_input": str(mes),
                    "tabView:formFiltro:mesAnoField:txtAno_input": str(ano),
                    "javax.faces.ViewState": self._vs,
                }
                r = self.s.post(_BASE + self._action, data=data, headers=_HDRS,
                                verify=False, timeout=self.timeout)
                if r.status_code != 200 or "partial-response" not in r.text[:200]:
                    self._vs = None
                    time.sleep(1.5 + tent)
                    continue
                # Atualiza o ViewState devolvido (JSF pode rotacioná-lo).
                nvs = re.search(r'<update id="javax.faces.ViewState"><!\[CDATA\[(.*?)\]\]>', r.text, re.S)
                if nvs:
                    self._vs = nvs.group(1)
                # SEM divResultados = a consulta NÃO rodou (throttle/erro) ≠ 'nada encontrado'.
                # Honestidade dura (INDISPONÍVEL≠0): backoff e retenta; nunca devolve [] aqui.
                if '<update id="divResultados">' not in r.text:
                    self._vs = None
                    time.sleep(2.0 + 2 * tent)
                    continue
                if self.pausa:
                    time.sleep(self.pausa)
                return self._parse(r.text)
            except requests.RequestException:
                self._vs = None
                time.sleep(1.5 + tent)
        return None

    @staticmethod
    def _parse(xml: str) -> list[dict]:
        m = re.search(r'<update id="divResultados"><!\[CDATA\[(.*?)\]\]></update>', xml, re.S)
        if not m:
            return []
        body = m.group(1)
        linhas: list[dict] = []
        for tr in re.findall(r'<tr[^>]*data-ri="\d+"[^>]*>(.*?)</tr>', body, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(cells) < 9:
                continue
            vals = [_texto(c) for c in cells]
            vals += [""] * (len(_COLS) - len(vals))
            linhas.append(dict(zip(_COLS, vals)))
        return linhas


def competencia_mais_recente(sondar_nome: str = "SILVA") -> tuple[int, int]:
    """Descobre a competência (mês,ano) mais recente COM dados, testando meses decrescentes."""
    sess = Sessao()
    from datetime import datetime, timezone
    hoje = datetime.now(timezone.utc)
    for ano in (hoje.year, hoje.year - 1):
        for mes in range(12, 0, -1):
            if ano == hoje.year and mes > hoje.month:
                continue
            linhas = sess.consultar_nome(sondar_nome, mes, ano)
            if linhas:
                return mes, ano
    return 5, 2025
