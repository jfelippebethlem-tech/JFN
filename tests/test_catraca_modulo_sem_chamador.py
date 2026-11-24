# -*- coding: utf-8 -*-
"""CATRACA — módulo de `compliance_agent/` que NINGUÉM de produção importa nem agenda.

A família "construído, testado, nunca rodado" é a que mais reincide nesta casa (catálogo de falhas; 6 casos até
julho, mais três depois da primeira catraca, e a passada final de 20/11/2026 ainda achou ~30 módulos com dezenas de
testes verdes e nenhum chamador). `test_ferramenta_tem_quem_a_rode` cobre as ferramentas que alguém LEMBROU de pôr
na tabela; o módulo novo que nasce órfão não está em tabela nenhuma.

Aqui a regra é mecânica e vale para todo módulo, sem lista de lembrados: um módulo de `compliance_agent/` precisa de
pelo menos UM destes, fora de `tests/`:
  • ser importado por outro arquivo .py do repositório (import estático, inclusive relativo e `from pacote import mod`);
  • ser citado por nome (`compliance_agent.x.y` ou `compliance_agent/x/y.py`) em shell, yaml, unit do systemd ou texto
    de código (é como entram o `-m` do cron, a propagação e o `importlib` por string).

O que já era órfão em 20/11/2026 está em `tests/baseline_modulos_sem_chamador.txt` — é DÍVIDA NOMEADA, não licença:
a lista só pode encolher. Módulo novo sem chamador falha aqui, antes do push, com a instrução do que fazer.
"""
import functools
import os
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PACOTE = "compliance_agent"
BASELINE = Path(__file__).with_name("baseline_modulos_sem_chamador.txt")
_FORA = {".git", ".venv", "node_modules", ".claude", "data", "graphify-out", ".gitnexus", "__pycache__", "static"}
_TEXTO = {".sh", ".yaml", ".yml", ".service", ".timer", ".toml", ".cfg", ".json"}


def _arquivos():
    """os.walk com poda: `data/` tem milhões de arquivos na VM — nunca descer nele."""
    for raiz, dirs, nomes in os.walk(RAIZ):
        dirs[:] = [d for d in dirs if d not in _FORA]
        for n in nomes:
            if n.endswith(".py") or os.path.splitext(n)[1] in _TEXTO:
                yield Path(raiz) / n


def _modulo_de(p: Path) -> str:
    partes = list(p.relative_to(RAIZ).with_suffix("").parts)
    if partes[-1] == "__init__":
        partes.pop()
    return ".".join(partes)


_IMPORT = re.compile(r"^[ \t]*from[ \t]+(\.*)([\w.]*)[ \t]+import[ \t]+(\([^)]*\)|[^\n#]+)|^[ \t]*import[ \t]+([^\n#]+)", re.M)


def _nomes(lista: str) -> list[str]:
    return [n.split(" as ")[0].strip() for n in lista.strip("() \t").replace("\n", " ").split(",") if n.strip()]


def _importados(p: Path, fonte: str) -> set[str]:
    """Nomes de módulo que o arquivo importa, absolutos (o relativo é resolvido pela posição do arquivo).
    Por expressão regular, não por AST: são ~3 mil arquivos e a catraca tem de caber no portão."""
    pacote = list(p.relative_to(RAIZ).parts[:-1])
    out = set()
    for m in _IMPORT.finditer(fonte):
        if m.group(4):
            out |= set(_nomes(m.group(4)))
            continue
        nivel = len(m.group(1))
        base = (pacote[: len(pacote) - nivel + 1] if nivel else []) + [x for x in m.group(2).split(".") if x]
        nome = ".".join(base)
        out.add(nome)
        out |= {f"{nome}.{n}" for n in _nomes(m.group(3))}          # `from pacote import modulo`
    return out


# Pacotes cujos módulos são carregados por DESCOBERTA (pkgutil/importlib sobre o diretório), não por import escrito:
# o chamador é o carregador. Entrar aqui exige que o carregador exista e rode — por isso a lista é curta e nomeada.
_PLUGINS = {
    "compliance_agent.padroes": "tools/padroes_varrer descobre cada detector do diretório",
    # 24/11/2026 (O4.2): o runner caseiro de database/migrations/ saiu — o carregador agora é o Alembic,
    # pelo `script_location` que database/migrar.py monta (env.py + uma revisão por arquivo em versions/).
    "compliance_agent.database.alembic": "env.py carregado pelo Alembic (migrar._config)",
    "compliance_agent.database.alembic.versions": "revisões descobertas pelo Alembic no diretório",
}
_CITACAO = re.compile(rf"{PACOTE}(?:[./]\w+)+")


def _citados(texto: str) -> set[str]:
    """`compliance_agent.x.y`, `compliance_agent/x/y.py` e `compliance_agent.x.y.funcao` → {x, x.y, x.y.funcao}."""
    out = set()
    for m in set(_CITACAO.findall(texto)):
        partes = m.replace("/", ".").removesuffix(".py").split(".")
        out |= {".".join(partes[:i]) for i in range(2, len(partes) + 1)}
    return out


@functools.lru_cache(maxsize=1)
def orfaos() -> frozenset[str]:
    modulos = {_modulo_de(p): p for p in (RAIZ / PACOTE).rglob("*.py")
               if p.name not in ("__init__.py", "__main__.py") and "__pycache__" not in p.parts}
    usados: set[str] = set()
    for p in _arquivos():
        if p.relative_to(RAIZ).parts[0] == "tests":
            continue
        # config/jobs.yaml é o INVENTÁRIO do que rodava (O1.1 da Esteira Única): cita todo módulo do crontab
        # antigo, inclusive os aposentados — citar no inventário não é chamar (24/11/2026).
        if p.relative_to(RAIZ).as_posix() == "config/jobs.yaml":
            continue
        if p.suffix == ".py":
            fonte = p.read_text(encoding="utf-8", errors="replace")
            proprio = _modulo_de(p)
            # citação por string no PRÓPRIO arquivo não conta (docstring com o comando de uso não é chamador)
            usados |= {m for m in _importados(p, fonte) | _citados(fonte) if m != proprio}
        elif p.suffix in _TEXTO and p.stat().st_size < 2_000_000:
            usados |= _citados(p.read_text(encoding="utf-8", errors="replace"))
    return frozenset(m for m in modulos if m not in usados and m.rsplit(".", 1)[0] not in _PLUGINS)


def _baseline() -> set[str]:
    return {ln.split("#")[0].strip() for ln in BASELINE.read_text(encoding="utf-8").splitlines()
            if ln.split("#")[0].strip()}


def test_modulo_novo_sem_chamador_nao_entra():
    novos = sorted(orfaos() - _baseline())
    assert not novos, (
        "Módulo(s) de compliance_agent/ sem NENHUM chamador de produção (só teste o exercita):\n  "
        + "\n  ".join(novos)
        + "\n\nÉ a família 'construído, testado, nunca rodado'. Antes do push, UMA destas:\n"
          "  1. ligar: quem chama em produção? (rota, derivado em config/propagacao.yaml, sweep do cron);\n"
          "  2. se é entrega que espera decisão do dono, some à baseline COM o motivo na mesma linha (# …);\n"
          "  3. se não vai ser ligado, não commite o módulo.")


def test_baseline_so_encolhe():
    """Quem ganhou chamador (ou foi apagado) sai da baseline — senão a dívida nomeada vira lista morta."""
    sobrando = sorted(_baseline() - orfaos())
    assert not sobrando, ("Estes já têm chamador ou não existem mais; tire-os de "
                          f"{BASELINE.name}:\n  " + "\n  ".join(sobrando))
