# -*- coding: utf-8 -*-
"""As catracas ESTÁTICAS das regras de qualidade — registro único.

Cada catraca = (regra, onde procurar, como achar o defeito). O teste (`tests/test_regra_*.py`) e a ferramenta que
aperta a base (`python -m compliance_agent.qualidade base --apertar`) leem o MESMO registro: catraca e base não
divergem (CST-09). Todas contam por arquivo versionado e só deixam a dívida descer (ver `catraca.py`).

Este módulo e os testes de regra ficam fora das varreduras: eles ESCREVEM os padrões que as catracas procuram.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from compliance_agent.qualidade import catraca, verificadores

REPO = catraca.REPO
_FORA = ("compliance_agent/qualidade/", "tests/", "docs/", "_SANDBOX/", "_PROTEGIDO/", "graphify-out/")


def _fora(rel: str) -> bool:
    return rel.startswith(_FORA)


@dataclass(frozen=True)
class Catraca:
    nome: str
    regra: str
    o_que: str
    padroes: tuple
    achar: Callable[[str, str], list]
    prefiltro: str = ""      # regex POSIX estendida para `git grep -lIE`: só abre em Python o arquivo candidato

    def atual(self, repo: Path = REPO) -> dict[str, int]:
        if self.prefiltro:
            arqs = catraca.candidatos(self.prefiltro, self.padroes, repo)
        else:
            arqs = catraca.versionados(self.padroes, repo)
        return catraca.contar([a for a in arqs if not _fora(a)], self.achar, repo)

    def excesso(self, repo: Path = REPO, base: Path = catraca.BASE) -> list[str]:
        return catraca.cresceu(self.atual(repo), catraca.ler_base(self.nome, base))


# ── PAD-08 · linguagem acusatória em rótulo fixo do painel ───────────────────────────────────────────────
_RE_STR_JS = re.compile(r"""(['"`])((?:\\.|(?!\1).)*)\1""", re.S)
_RE_COMENT_JS = re.compile(r"^\s*(//|\*|/\*)")


def achar_linguagem(rel: str, texto: str) -> list:
    """Termo acusatório sem qualificador de indício dentro de string de interface (JS/HTML)."""
    out = []
    for linha in texto.splitlines():
        if _RE_COMENT_JS.match(linha):
            continue
        trechos = [m.group(2) for m in _RE_STR_JS.finditer(linha)] if rel.endswith(".js") else [linha]
        for t in trechos:
            if " " not in t.strip():        # identificador/chave de objeto ('fantasma', 'aba-laranjas') não é rótulo
                continue
            out += verificadores.linguagem_acusatoria(re.sub(r"<[^>]+>", " ", t))
    return out


# ── CNF-02 · soma de OB só com OB paga ───────────────────────────────────────────────────────────────────
_RE_FROM_OB = re.compile(r"FROM\s+ob_orcamentaria_siafe", re.I)
# `=\s*'Contabilizado'` sozinho: o filtro pode vir sobre uma EXPRESSÃO de status efetivo (`({st_ef})='Contabilizado'`)
_RE_FILTRO_OB = re.compile(r"_OB_PAGA|OB_PAGA|=\s*'Contabilizado'|status\s*=\s*\?|_contabilizadas|SQL_OB_PAGA", re.I)
MARCA_OB_LIVRE = "ob-qualquer-status"       # comentário que declara: esta consulta é metadado/cobertura, não soma


def achar_ob_sem_filtro(rel: str, texto: str) -> list:
    linhas = texto.splitlines()
    out = []
    for i, linha in enumerate(linhas):
        if _RE_FROM_OB.search(linha):
            janela = "\n".join(linhas[i:i + 4])
            antes = "\n".join(linhas[max(0, i - 3):i + 1])
            if not _RE_FILTRO_OB.search(janela) and MARCA_OB_LIVRE not in antes:
                out.append(f"{rel}:{i + 1}")
    return out


# ── CNF-03 · sanção só pelo módulo de abrangência ────────────────────────────────────────────────────────
_RE_SANCAO_SQL = re.compile(r"(?:FROM|JOIN)\s+(?:db\.)?(sancoes_federais|sancoes_tce\w*|ceis|cnep)\b", re.I)
_RE_SANCAO_OK = re.compile(r"sancao_abrangencia|sancao_impeditiva|veda_ente|vigente_em")


def achar_sancao_sem_alcance(rel: str, texto: str) -> list:
    if _RE_SANCAO_OK.search(texto):
        return []
    return [m.group(0) for m in _RE_SANCAO_SQL.finditer(texto)]


# ── CNF-06 / CST-09 · teto legal em fonte única ──────────────────────────────────────────────────────────
def _tetos_canonicos() -> list[str]:
    from compliance_agent.limites_dispensa import LIMITES
    vals = {v for info in LIMITES.values() for k, v in info.items() if k in ("obras", "compras")}
    vals -= {50000.0, 100000.0}             # valores redondos demais para identificar um teto (falso positivo)
    out = []
    for v in sorted(vals):
        inteiro, cent = f"{v:.2f}".split(".")
        out += [rf"{inteiro}\.{cent}", rf"{inteiro[:-3]}\.{inteiro[-3:]},{cent}", rf"{inteiro[:-3]}_{inteiro[-3:]}\.{cent}"]
    return out


_RE_TETO = None


def achar_teto_copiado(rel: str, texto: str) -> list:
    global _RE_TETO
    if _RE_TETO is None:
        _RE_TETO = re.compile(r"(?<![\d.,_])(" + "|".join(_tetos_canonicos()) + r")(?![\d])")
    if rel.endswith("limites_dispensa.py"):
        return []
    return _RE_TETO.findall(texto)


# ── CNF-08 · CPF em arquivo versionado  ·  CNF-14 · segredo em arquivo versionado ────────────────────────
def achar_cpf(rel: str, texto: str) -> list:
    return verificadores.cpf_exposto(texto)


_RE_SEGREDO = re.compile(r"(sk-ant-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}|ghp_[A-Za-z0-9]{36}|gsk_[A-Za-z0-9]{40,}|"
                         r"github_pat_[A-Za-z0-9_]{40,}|\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b|nvapi-[A-Za-z0-9_-]{40,}|"
                         r"sk-or-v1-[a-f0-9]{40,})")


def achar_segredo(rel: str, texto: str) -> list:
    return _RE_SEGREDO.findall(texto)


# ── CNF-10 · chave de API paga só no módulo com teto ─────────────────────────────────────────────────────
_RE_CHAVE_PAGA = re.compile(r"ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|anthropic\.env|OPENAI_API_KEY")
_API_PERMITIDO = ("compliance_agent/llm/claude_api.py", "compliance_agent/llm/claude_motor.py")


def achar_chave_paga(rel: str, texto: str) -> list:
    return [] if rel in _API_PERMITIDO else _RE_CHAVE_PAGA.findall(texto)


# ── PAD-12 · grau fixado por CNPJ dentro do código ───────────────────────────────────────────────────────
_RE_CNPJ_LIT = re.compile(r"""['"](\d{14}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})['"]""")


def cnpj_valido(d: str) -> bool:
    d = re.sub(r"\D", "", d)
    if len(d) != 14 or d == d[0] * 14:
        return False
    for n, pesos in ((12, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)), (13, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))):
        r = sum(int(d[i]) * pesos[i] for i in range(n)) % 11
        if int(d[n]) != (0 if r < 2 else 11 - r):
            return False
    return True


def achar_cnpj_literal(rel: str, texto: str) -> list:
    return [c for c in _RE_CNPJ_LIT.findall(texto) if cnpj_valido(c)]


# ── CNF-16 · matar processo por padrão de nome ───────────────────────────────────────────────────────────
_RE_PKILL = re.compile(r"^(?!\s*#).*\bpkill\s+(-\w+\s+)*-f\b", re.M)


def achar_pkill(rel: str, texto: str) -> list:
    return _RE_PKILL.findall(texto)


# ── COR-06 · agrupar pessoa só pelo CPF mascarado ────────────────────────────────────────────────────────
_RE_GRUPO_MASC = re.compile(r"GROUP\s+BY\s+[^\n\"']{0,80}?\bcpf(?:_mascarado|_masc|_frag)?\b(?![^\n\"']{0,80}\bnome)", re.I)
_RE_CAMPO_PJ = re.compile(r"favorecido_cpf|cpf_cnpj|cnpj", re.I)   # colunas de pessoa jurídica com "cpf" no nome


def achar_grupo_por_cpf(rel: str, texto: str) -> list:
    return [m.group(0) for m in _RE_GRUPO_MASC.finditer(texto) if not _RE_CAMPO_PJ.search(m.group(0))]


# ── CST-03 · motor do AO VIVO sem efeito declarado (não é por arquivo: é por motor) ──────────────────────
def motores_sem_efeito(repo: Path = REPO) -> dict[str, int]:
    arq = repo / "compliance_agent" / "aovivo" / "motores.yaml"
    motores = yaml.safe_load(arq.read_text(encoding="utf-8")).get("motores", [])
    return {m["id"]: 1 for m in motores if m.get("classe") == "motor" and not m.get("efeito")}


_PY = ("compliance_agent/*.py", "rotas/*.py", "tools/*.py", "server.py", "siafe_agent/*.py")
_SCRIPTS = ("*.sh", "*.py", "*.cmd", "*.ps1", "deploy/*")

CATRACAS = {c.nome: c for c in (
    Catraca("linguagem_painel", "PAD-08", "termo acusatório sem qualificador de indício em texto fixo do painel",
            ("static/js/src/*.js", "static/*.html"), achar_linguagem),
    Catraca("ob_sem_filtro_de_paga", "CNF-02", "consulta a ob_orcamentaria_siafe sem filtro de OB paga",
            _PY, achar_ob_sem_filtro),
    Catraca("sancao_sem_alcance", "CNF-03", "leitura de tabela de sanção fora do módulo de abrangência/vigência",
            _PY, achar_sancao_sem_alcance),
    Catraca("teto_legal_copiado", "CNF-06", "valor de teto legal copiado fora de limites_dispensa.py",
            _PY, achar_teto_copiado),
    Catraca("cpf_versionado", "CNF-08", "CPF com dígito verificador válido em arquivo versionado",
            ("*.py", "*.md", "*.json", "*.yaml", "*.yml", "*.js", "*.html", "*.txt", "*.csv", "*.sh"), achar_cpf,
            prefiltro=r"[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}|[Cc][Pp][Ff][^0-9]{0,20}[0-9]{11}"),
    Catraca("segredo_versionado", "CNF-14", "padrão de chave/token em arquivo versionado",
            ("*.py", "*.md", "*.json", "*.yaml", "*.yml", "*.js", "*.html", "*.txt", "*.sh", "*.cmd", "*.ps1"),
            achar_segredo, prefiltro=r"sk-ant-|AIza|ghp_|gsk_|github_pat_|[0-9]{8,10}:AA|nvapi-|sk-or-v1-"),
    Catraca("chave_paga_fora_do_teto", "CNF-10", "variável de chave de API paga lida fora do módulo com teto",
            _PY + ("*.sh",), achar_chave_paga),
    Catraca("cnpj_literal_no_codigo", "PAD-12", "CNPJ literal em código de detector, perícia ou rota",
            ("compliance_agent/*.py", "rotas/*.py"), achar_cnpj_literal),
    Catraca("pkill_por_padrao", "CNF-16", "processo morto por padrão de nome (pkill -f)", _SCRIPTS, achar_pkill),
    Catraca("grupo_por_cpf_mascarado", "COR-06", "agrupamento de pessoa física só pelo CPF, sem o nome",
            _PY, achar_grupo_por_cpf),
)}


def apertar(repo: Path = REPO, base: Path = catraca.BASE) -> dict[str, tuple[int, int]]:
    """Regrava as bases sem nunca subir. Devolve {catraca: (antes, depois)} em total de ocorrências."""
    out = {}
    for nome, c in CATRACAS.items():
        antes = sum(catraca.ler_base(nome, base).values())
        out[nome] = (antes, sum(catraca.gravar_base(nome, c.atual(repo), base).values()))
    antes = sum(catraca.ler_base("motores_sem_efeito", base).values())
    out["motores_sem_efeito"] = (antes, sum(catraca.gravar_base("motores_sem_efeito", motores_sem_efeito(repo), base).values()))
    return out
