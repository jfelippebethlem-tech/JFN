# -*- coding: utf-8 -*-
"""
Smoke de imports — rede de segurança para refatorações (Fase 3 da campanha de otimização).

Importa TODOS os módulos dos pacotes core e falha se algum quebrar no import (ImportError, SyntaxError,
NameError em top-level, etc.). É barato e pega regressões de import — o tipo de quebra que dedup de login /
split de monólitos pode introduzir. NÃO testa comportamento; só que tudo carrega.

Denylist: módulos que fazem trabalho PESADO/efeito colateral no import (ex.: easyocr→torch) ficam de fora p/
o smoke ser rápido e determinístico; eles têm cobertura própria ou são lazy.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_PACOTES = ["compliance_agent", "siafe_agent"]
# módulos que puxam deps pesadas no import (OCR/torch) ou são scripts de debug — fora do smoke
_DENY = {
    "compliance_agent.captcha_solver",          # easyocr → torch (~750MB) no import
    "compliance_agent.notifications.test_telegram",
}


# Extras OPCIONAIS: `requirements-sei.txt` declara, no próprio cabeçalho, que o core roda só
# com `requirements.txt` — logo, a ausência destes não é regressão. A VM-2 montou uma venv só
# com o core e levou 4 falhas por `websocket` e `selenium`, que escondiam a falha de verdade no
# meio do ruído. Extra ausente vira `skip` COM O NOME; qualquer outro ImportError continua
# falhando (ver tests/test_imports_smoke_extras.py).
EXTRAS_OPCIONAIS = {"websocket", "selenium", "webdriver_manager", "easyocr", "cv2", "pytesseract"}


def extra_opcional_faltando(exc: BaseException) -> str | None:
    """Nome do extra opcional que faltou, ou `None` se o erro é outro (e deve falhar)."""
    if not isinstance(exc, ModuleNotFoundError) or not exc.name:
        return None
    raiz = exc.name.split(".")[0]
    return raiz if raiz in EXTRAS_OPCIONAIS else None


def _modulos():
    mods = []
    for pkg_nome in _PACOTES:
        try:
            pkg = importlib.import_module(pkg_nome)
        except Exception:  # pragma: no cover - pacote raiz tem que importar
            mods.append(pkg_nome)
            continue
        for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg_nome + "."):
            nome = info.name
            if nome in _DENY or nome.rsplit(".", 1)[-1].startswith("test_"):
                continue
            mods.append(nome)
    return sorted(set(mods))


@pytest.mark.parametrize("modulo", _modulos())
def test_modulo_importa(modulo):
    """Cada módulo core importa sem erro — extra opcional ausente pula, declarando o nome."""
    try:
        importlib.import_module(modulo)
    except ModuleNotFoundError as exc:
        extra = extra_opcional_faltando(exc)
        if not extra:
            raise
        pytest.skip(f"{modulo} depende do extra opcional '{extra}' "
                    f"(requirements-sei.txt, não instalado nesta máquina)")
