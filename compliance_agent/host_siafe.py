# -*- coding: utf-8 -*-
"""host_siafe — o SIAFE só aceita UMA sessão por IP; esta trava impede a segunda.

O FATO OPERACIONAL (dono, 2026-07-28): **o SIAFE-1 e o SIAFE-2 só permitem login de um IP por
vez.** Uma segunda máquina logando não apenas falha: ela DERRUBA a sessão da primeira. Numa
coleta noturna de horas, isso significa perder a janela inteira — e o sintoma chega como
"coletou zero" no dia seguinte, sem nada dizendo por quê.

POR QUE ISTO É CÓDIGO E NÃO UMA NOTA. A restrição é invisível: nada no coletor sinaliza que ele
não pode rodar em duas máquinas. Com a carga sendo distribuída entre a VM-1 e a VM-2, um
`rsync` do repositório e um cron copiado bastam para quebrá-la sem que ninguém perceba. Regra
que depende de alguém lembrar é regra que vai ser esquecida.

COMO FUNCIONA. O arquivo `data/.siafe_host` guarda o hostname da máquina autorizada. Ele é
criado no host que já coleta, e a ausência do arquivo é tratada como AUTORIZAÇÃO — nunca como
bloqueio: uma instalação nova não pode ficar sem coletar por causa de um arquivo que ninguém
criou ainda. O bloqueio só acontece quando o arquivo existe e aponta para OUTRA máquina, que é
exatamente o caso perigoso.
"""
from __future__ import annotations

import logging
import os
import pathlib
import socket

logger = logging.getLogger(__name__)

MARCADOR = pathlib.Path(os.environ.get("JFN_SIAFE_HOST_FILE", "data/.siafe_host"))


def host_atual() -> str:
    return socket.gethostname().strip()


def host_autorizado() -> str | None:
    """Hostname autorizado, ou `None` quando nenhum foi designado."""
    try:
        valor = MARCADOR.read_text().strip()
    except OSError:
        return None
    return valor or None


def designar(host: str | None = None) -> str:
    """Marca esta máquina (ou a informada) como a única autorizada a logar no SIAFE."""
    alvo = (host or host_atual()).strip()
    MARCADOR.parent.mkdir(parents=True, exist_ok=True)
    MARCADOR.write_text(alvo + "\n")
    logger.info("SIAFE: host autorizado passa a ser %s", alvo)
    return alvo


def pode_coletar() -> tuple[bool, str]:
    """`(autorizado, motivo)`. Sem marcador, autoriza — ausência não é proibição."""
    autorizado = host_autorizado()
    atual = host_atual()
    if autorizado is None:
        return True, f"nenhum host designado; {atual} assume a coleta"
    if autorizado == atual:
        return True, f"{atual} é o host designado"
    return False, (
        f"coleta BLOQUEADA em {atual}: o host designado é {autorizado}. O SIAFE aceita uma "
        f"sessão por IP — logar daqui DERRUBARIA a sessão de {autorizado} e faria a coleta em "
        f"curso perder a janela. Para transferir de propósito: "
        f"python -m compliance_agent.host_siafe --designar")


def exigir_autorizacao() -> None:
    """Levanta se esta máquina não pode coletar. Chame no início de qualquer coletor SIAFE."""
    ok, motivo = pode_coletar()
    if not ok:
        raise RuntimeError(motivo)
    logger.debug("SIAFE: %s", motivo)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--designar", action="store_true",
                    help="marca ESTA máquina como a autorizada a logar no SIAFE")
    a = ap.parse_args()
    if a.designar:
        print(f"host autorizado: {designar()}")
        return 0
    ok, motivo = pode_coletar()
    print(f"host atual      : {host_atual()}")
    print(f"host autorizado : {host_autorizado() or '(nenhum designado)'}")
    print(f"pode coletar    : {'SIM' if ok else 'NÃO'} — {motivo}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
