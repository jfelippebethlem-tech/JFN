#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""receita_mes — qual é o mês mais recente do dump CNPJ da Receita, e o refresh andou ou congelou?

O DEFEITO QUE ISTO FECHA. `baixar_receita_dump.sh` tinha `MES="2026-05"` fixo. O cron mensal
re-baixou maio em 05/09, 05/10 e 05/11, e as três execuções terminaram com "VALIDACAO=OK" e contagens
idênticas — enquanto a Receita já publicava até 2026-10. A validação só conferia que as tabelas não
estavam vazias; uma base CONGELADA passava. Aqui ficam (1) a leitura da listagem WebDAV que resolve o
mês mais recente e (2) a decisão que faz o passo 7 do refresh falhar quando o mês não andou.

Fonte: share público Nextcloud `arquivos.receitafederal.gov.br` (usuário = token do share, senha
vazia), PROPFIND Depth 1 na raiz do WebDAV devolve as pastas `AAAA-MM/`.

Uso:
  python -m tools.receita_mes mais-recente                  # imprime AAAA-MM (rc=1 se indisponível)
  python -m tools.receita_mes decidir BAIXADO ANTERIOR RECEITA   # rc=0 OK, rc=1 congelado ('' = desconhecido)
"""
from __future__ import annotations

import base64
import re
import sys
import urllib.request

_WEBDAV = "https://arquivos.receitafederal.gov.br/public.php/webdav/"
_SHARE = "YggdBLfdninEJX9"  # token PÚBLICO do share (não é credencial: senha vazia, link aberto)
_RE_PASTA = re.compile(r"/webdav/(\d{4}-\d{2})/?<")


def mes_mais_recente(xml: str) -> str | None:
    """Maior pasta `AAAA-MM/` da resposta PROPFIND; None se não houver nenhuma."""
    meses = _RE_PASTA.findall(xml or "")
    return max(meses) if meses else None


def listar_receita(timeout: int = 60) -> str | None:
    """Faz o PROPFIND e devolve o mês mais recente publicado; None se a listagem falhar."""
    req = urllib.request.Request(_WEBDAV, method="PROPFIND", headers={
        "Depth": "1",
        "Authorization": "Basic " + base64.b64encode(f"{_SHARE}:".encode()).decode(),
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — host fixo e público
            return mes_mais_recente(r.read().decode("utf-8", "ignore"))
    except (OSError, ValueError) as e:  # rede/HTTP/timeout: quem chama decide; não se inventa mês
        print(f"[receita_mes] listagem indisponível: {str(e)[:120]}", file=sys.stderr)
        return None


def decidir_validacao_mes(baixado: str, anterior: str | None, receita: str | None) -> tuple[bool, str]:
    """Falha só quando o refresh NÃO andou havendo para onde andar.

    Congelado = o mês baixado é o mesmo que já estava carregado (`fonte_mes` antes do refresh) E a
    Receita tem mês mais novo. Re-executar o mesmo mês sem nada novo publicado é legítimo; listagem
    indisponível não autoriza afirmar congelamento (INDISPONÍVEL ≠ OK, mas também ≠ falha medida).
    """
    if not receita:
        return True, (f"mes_baixado={baixado} anterior={anterior or '-'} receita=INDISPONIVEL "
                      "(listagem falhou; congelamento NÃO aferido)")
    if baixado == (anterior or "") and receita > baixado:
        return False, (f"CONGELADO: mes_baixado={baixado} igual ao já carregado, e a Receita "
                       f"publicou {receita}")
    return True, f"mes_baixado={baixado} anterior={anterior or '-'} receita={receita}"


def main(argv: list[str]) -> int:
    if argv[:1] == ["mais-recente"]:
        m = listar_receita()
        if not m:
            return 1
        print(m)
        return 0
    if argv[:1] == ["decidir"] and len(argv) == 4:
        ok, motivo = decidir_validacao_mes(argv[1], argv[2] or None, argv[3] or None)
        print(motivo)
        return 0 if ok else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
