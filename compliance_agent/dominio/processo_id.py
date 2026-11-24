# -*- coding: utf-8 -*-
"""Chave canônica do PROCESSO — uma função para as grafias todas (plano mestre v2, §3.1).

Chave canônica (a de `evidencias.processos.processo`, do campo `processo` de 16.594 dos 16.598 manifests do
`data/sei_arquivo` e da pasta do acervo com `/`→`_`):

    SEI-RJ   `UUUUUU/NNNNNN/AAAA`  — unidade 6 dígitos, sequencial 6 dígitos com zeros, ano 4 dígitos
    SEI.RIO  `PCRJ:UUUUU.NNNNNN/AAAA-DD` — protocolo do SEI municipal como `pcrj.sei_prefeitura` o escreve

`chave_processo(texto)` devolve uma das duas ou `None` ("não sei qual processo é" nunca casa com nada).

Grafias SEI-RJ aceitas (todas medidas em 24/11/2026 em `ob_orcamentaria_siafe`, `nl_siafe`, `ne_siafe`,
`ordens_bancarias`, `contratos_tcerj` e nos manifests):
- com ou sem prefixo, em qualquer caixa: `SEI-`, `SEI `, `SEI`, `sei-`, `Sei `, `S-`, `I-`, `SE-`, `EI-`, `S07-`;
- ano com 2 dígitos (`/24` → `2024`) — o SIAFE grava dos dois jeitos;
- sequencial sem os zeros à esquerda (`/5954/`, `/00007/`) ou com zeros a mais (`/0001106/`, até 6 significativos);
- espaços em volta das barras; barra dobrada (`//`); `_` no lugar da barra (nome da pasta do acervo);
- 16 dígitos corridos (`chave_sei` da perícia); 12 dígitos + `/AAAA` ou `/AA` (`SEI-080001002471/2024`);
- unidade com UM zero a mais à esquerda (`SEI-0080004/002071/24` → `080004`): o valor é o mesmo;
- depois de `SEI`, hífen ou espaço como separador (`SEI 330002 031566 2024`, como `pericia_contabil.chave_sei`);
- sufixo de desdobramento depois do sequencial: `-1`, `-01`, `A`, `-A`, `/2/`, `/A/` (TCE-RJ e SIAFE). O sufixo
  NÃO entra na chave do processo (o número SEI-RJ não tem sufixo; ele identifica o ajuste dentro do processo) e
  fica em `ProcessoId.sufixo`.

Recusadas de propósito (`None`), por não identificarem UM processo SEI-RJ sem palpite:
- unidade com 5 dígitos (`SEI-08000/007404/2022`: o zero caído pode estar em qualquer posição — `ob_processo`
  só a resolve contra uma lista de pedidos, e assim continua);
- numeração antiga `E-NN/NNN/NNNNNN/AAAA`, `PGE/…`, a forma `SEI-EE/OOO/NNNNNN/AAAA` (equivalência com
  `EE0OOO` não provada) e o processo sem ano (`SEI-070020/0002`);
- ano com 3 dígitos (`/022`) ou com dígitos a mais (`/20214`), sequencial com 7+ dígitos significativos,
  unidade de 7 dígitos que não começa por zero (`SEI-2100106/…`) e unidade colada a outro dígito;
- ponto, vírgula ou hífen como separador sem o prefixo `SEI` (`SEI-070002.019349/2023`, `520003-000009/2026`):
  o ponto é o separador do SEI.RIO e o hífen o do dígito verificador — aceitar daria chave a número de outro sistema.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Sufixo de desdobramento entre o sequencial e o ano.
_SUF = r"(?P<suf>\s*-\s*\d{1,2}|\s*-?\s*[A-Z]|\s*/\s*[A-Z0-9](?=\s*/))?"
_ANO = r"(?P<ano>\d{4}|\d{2})(?!\d)"

# A unidade não vem colada a dígito nem logo depois de outro segmento numérico ("E-09/102510/4000/2001" não vira
# unidade 102510; "SEI-080002/000408/1/2024" não vira unidade 000408 — o `_chave_processo` do lex fazia isso).
# Um zero a mais à esquerda ("SEI-0080004/002071/24", "0300001/000003/2026") é grafia: o valor é o mesmo.
_INICIO = r"(?<!\d)(?<!\d/)(?<!\d_)0?"
# A. separado por barra/sublinhado.
_RX_SEP = re.compile(_INICIO + r"(?P<u>\d{6})\s*[/_]+\s*0*(?P<seq>\d{1,6})" + _SUF + r"\s*[/_]+\s*" + _ANO, re.I)
# B. depois de "SEI", hífen/espaço também separam (paridade com `pericia_contabil.chave_sei`), sequencial cheio.
_RX_PREFIXO = re.compile(r"SEI[\s\-]*(?P<u>\d{6})[\s/\-]*(?P<seq>\d{6})[\s/\-]*" + _ANO, re.I)
# C. 12 dígitos corridos + /AAAA (ou /AA).
_RX_COLADO = re.compile(_INICIO + r"(?P<u>\d{6})(?P<seq>\d{6})\s*/\s*" + _ANO)
# D. 16 dígitos e nada mais.
_RX_16 = re.compile(r"^(?P<u>\d{6})(?P<seq>\d{6})(?P<ano>\d{4})$")

# SEI.RIO: 5–6 dígitos . 6 dígitos / ano - 2 dígitos verificadores (o de `pcrj.sei_prefeitura`), sem dígito colado.
_RX_PCRJ = re.compile(r"(?<!\d)(\d{5,6})\s*\.\s*(\d{6})\s*/\s*(\d{4})\s*-\s*(\d{2})(?!\d)")
PREFIXO_PCRJ = "PCRJ:"


@dataclass(frozen=True)
class ProcessoId:
    """Processo SEI-RJ decomposto. `sequencial` é int (os zeros à esquerda são grafia, não identidade)."""
    unidade: str
    sequencial: int
    ano: str
    sufixo: str = ""

    @property
    def canonica(self) -> str:
        """`UUUUUU/NNNNNN/AAAA` — a chave."""
        return f"{self.unidade}/{self.sequencial:06d}/{self.ano}"

    @property
    def legivel(self) -> str:
        """`SEI-UUUUUU/NNNNNN/AAAA` — a forma do SEI-RJ, para exibir."""
        return "SEI-" + self.canonica

    @property
    def pasta(self) -> str:
        """`UUUUUU_NNNNNN_AAAA` — o nome da pasta em `data/sei_arquivo`."""
        return self.canonica.replace("/", "_")

    @property
    def digitos(self) -> str:
        """16 dígitos (`pericia_contabil.chave_sei`)."""
        return self.canonica.replace("/", "")

    @property
    def curta(self) -> str:
        """`UUUUUU/N/AAAA`, sequencial sem zeros — a chave legada de `tools.lex_execucao._chave_processo`
        (e de `ob_processo`, `foto_quantitativo`, `lex_fatos`). Só para casar com dado legado."""
        return f"{self.unidade}/{self.sequencial}/{self.ano}"


def _ano4(a: str) -> str:
    return a if len(a) == 4 else "20" + a


def _sufixo(s: str | None) -> str:
    return re.sub(r"[\s/\-]", "", s or "").upper()


def analisar(texto) -> ProcessoId | None:
    """Primeiro número de processo SEI-RJ do texto, decomposto; `None` se não houver (ver grafias no módulo)."""
    s = str(texto or "").strip().lstrip("*").strip()
    if not s:
        return None
    m = _RX_16.match(s)
    if m:
        return ProcessoId(m["u"], int(m["seq"]), m["ano"])
    m = _RX_SEP.search(s)
    if m:
        return ProcessoId(m["u"], int(m["seq"]), _ano4(m["ano"]), _sufixo(m["suf"]))
    m = _RX_PREFIXO.search(s) or _RX_COLADO.search(s)
    if m:
        return ProcessoId(m["u"], int(m["seq"]), _ano4(m["ano"]))
    return None


def chave_pcrj(texto) -> str | None:
    """`PCRJ:UUUUU.NNNNNN/AAAA-DD` (espaços em volta dos separadores tolerados); `None` se não houver."""
    m = _RX_PCRJ.search(str(texto or ""))
    return f"{PREFIXO_PCRJ}{m[1]}.{m[2]}/{m[3]}-{m[4]}" if m else None


def chave_processo(texto) -> str | None:
    """A chave canônica: `PCRJ:…` se o texto traz um protocolo SEI.RIO; senão `UUUUUU/NNNNNN/AAAA`; senão `None`.
    Idempotente: a chave devolvida, passada de novo, devolve ela mesma."""
    pcrj = chave_pcrj(texto)
    if pcrj:
        return pcrj
    p = analisar(texto)
    return p.canonica if p else None


def pasta(texto) -> str | None:
    """Nome da pasta no acervo (`UUUUUU_NNNNNN_AAAA`) ou `None`."""
    p = analisar(texto)
    return p.pasta if p else None


def legivel(texto) -> str | None:
    """`SEI-UUUUUU/NNNNNN/AAAA` ou `None`."""
    p = analisar(texto)
    return p.legivel if p else None
