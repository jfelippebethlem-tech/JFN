"""
Carregador único de credenciais do JFN.

Problema que resolve: cada entrypoint (JFN.bat, server.py, scheduler.py,
checar.py) carregava um arquivo diferente — uns `.env`, outros `.env.txt`.
No Windows é comum o Bloco de Notas salvar como `.env.txt` sem avisar, então
precisamos aceitar os dois. Este módulo centraliza isso.

Regra:
  - Carrega `.env` e depois `.env.txt` (o que existir), da raiz do projeto.
  - NÃO sobrescreve variáveis já definidas no ambiente (precedência: ambiente
    do processo > .env > .env.txt).
  - Idempotente: pode ser chamado várias vezes sem efeito colateral.
"""

import os
from pathlib import Path

# Raiz do projeto = pasta que contém este pacote (…/JFN)
_RAIZ = Path(__file__).resolve().parents[1]

# Ordem de tentativa. `.env` primeiro (canônico), `.env.txt` como fallback Windows.
_ARQUIVOS = (".env", ".env.txt")


def _aplicar(caminho: Path) -> int:
    """Lê um arquivo KEY=VALUE e popula os.environ sem sobrescrever. Retorna nº de chaves."""
    n = 0
    try:
        # utf-8-sig remove o BOM que o Bloco de Notas do Windows insere.
        for linha in caminho.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, _, valor = linha.partition("=")
            chave = chave.strip()
            valor = valor.strip().strip('"').strip("'")
            if chave and chave not in os.environ:
                os.environ[chave] = valor
                n += 1
    except Exception:
        pass
    return n


# Aliases de credencial: o .env pode usar os nomes PT (SEI_USUARIO/SEI_SENHA), mas
# vários módulos leem os nomes EN (SEI_USER/SEI_PASS). Espelha um no outro (sem
# sobrescrever) p/ não cair em senha VAZIA por descasamento (bug real pós-migração).
_ALIASES = {
    "SEI_USER": "SEI_USUARIO",
    "SEI_PASS": "SEI_SENHA",
}


def _aplicar_aliases() -> None:
    for canonico, alt in _ALIASES.items():
        a, b = os.environ.get(canonico), os.environ.get(alt)
        if a and not b:
            os.environ[alt] = a
        elif b and not a:
            os.environ[canonico] = b


def carregar_env(raiz: Path | None = None) -> list[str]:
    """
    Carrega `.env` e `.env.txt` da raiz do projeto para os.environ.
    Retorna a lista de arquivos que foram efetivamente lidos.
    """
    base = raiz or _RAIZ
    lidos: list[str] = []
    for nome in _ARQUIVOS:
        caminho = base / nome
        if caminho.exists():
            _aplicar(caminho)
            lidos.append(nome)
    _aplicar_aliases()
    return lidos


# Compatibilidade: nomes alternativos usados por alguns módulos.
load_env = carregar_env
load_env_files = carregar_env
