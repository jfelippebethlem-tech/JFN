# -*- coding: utf-8 -*-
"""E11 `periciar` — a MESMA fonte e porta do E8 (O8.5, frente B1): o texto que o E4/E5 gravou (PG da captura), OCR só
com `confirmado` do E6, legado só como volta declarada, e leitura única por texto (o mesmo texto em 2 processos é
julgado 1×; os achados ancorados vêm da perícia de origem com a citação no documento de CADA processo).
Reproduz o achado da frente B2 (25/11/2026): sem a ponte do ensaio, o E11 lia `data/sei_arquivo` e os laudos saíam
INCERTO com 0 peça lida. LLM sempre FALSO. Só com JFN_EVIDENCIAS_DSN (VM-2), em esquemas temporários."""
import pytest

from compliance_agent.aplicacao.estagios import fatos as F
from compliance_agent.aplicacao.estagios import periciar as P
from compliance_agent.aplicacao.estagios import texto as T
from tests.fluxo_pg import precisa_pg
from tests.test_estagio_fatos_fonte import (NATIVO, PROC, _Contador, _decreto, _dois, _semear, cap,  # noqa: F401
                                            sem_legado)
from tests.test_estagio_periciar import _Juiz, pg  # noqa: F401 — fixture do esquema temporário do E11


@precisa_pg
def test_e11_le_as_pecas_pela_saida_do_estagio_e_nao_pelo_legado(cap, pg, sem_legado):
    _semear(cap, sem_legado / "t", _dois())
    antes = P.preparar(PROC, [])                          # sem o PG da captura = o que o E11 fazia: legado vazio
    assert antes.fora_da_porta == "sem acervo capturado" and not antes.originais
    p = P.preparar(PROC, [], con_cap=cap)
    assert p.fora_da_porta is None and p.fonte_texto == F.FONTE_ESTAGIO
    assert set(p.originais) == {"sei:111", "sei:222"} and p.fatias
    j = _Juiz()
    r = P.periciar(pg, PROC, j, fatos=[], ob_paga=10.0, cnpj="11222333000181", con_cap=cap)
    assert r["fonte_texto"] == F.FONTE_ESTAGIO and len(j.chamadas) == 1
    laudo = P.laudo_vigente(pg, PROC)
    assert laudo["laudo"]["cobertura"]["docs_julgados"] == 2
    c = P.conferir(pg, r, con_cap=cap)
    assert P.efeito_ok(c) and c["amostra"] >= 1


@precisa_pg
def test_e11_porta_barra_ocr_nao_confirmado_pelo_e6(cap, pg, sem_legado):
    _semear(cap, sem_legado / "t", _dois(e6="a_conferir"))
    p = P.preparar(PROC, [], con_cap=cap)
    assert p.fora_da_porta == "documento de OCR ainda não confirmado" and not p.fatias
    assert p.pecas_nao_lidas[0]["doc_id"] == "sei:222"


@precisa_pg
def test_e11_mesmo_texto_julgado_1x_e_achados_reaproveitados(cap, pg, sem_legado):
    p1, p2 = "999002/000031/2026", "999002/000032/2026"
    _semear(cap, sem_legado / "t", [_decreto("sei:701", "Decreto 48.692 (701)")], proc=p1)
    _semear(cap, sem_legado / "t", [_decreto("sei:801", "Anexo Decreto 48.692 (801)"),
                                   {"doc_id": "sei:802", "titulo": "Despacho (802)",
                                    "paginas": [(T.NATIVA, NATIVO)]}], proc=p2)
    j = _Juiz()
    with _Contador() as c:
        r1 = P.periciar(pg, p1, j, fatos=[], ob_paga=10.0, cnpj="11222333000181", con_cap=cap)
        assert len(c.lidos) == 1
        r2 = P.periciar(pg, p2, j, fatos=[], ob_paga=10.0, cnpj="11222333000181", con_cap=cap)
        assert len(c.lidos) == 2                          # em p2 só o despacho é aberto: o decreto já foi julgado
    assert r2["docs_reaproveitados"] == 1
    enviados = [d.documento_id for _, _, docs in j.chamadas[1:] for d in docs]
    assert "sei:801" not in enviados and "sei:802" in enviados
    a1 = P.laudo_vigente(pg, p1)["laudo"]["eixos"]["execucao"]["achados"][0]
    a2 = P.laudo_vigente(pg, p2)["laudo"]["eixos"]["execucao"]["achados_reaproveitados"][0]
    assert a2["doc_id"] == "sei:801" and a2["reaproveitado_de"] == {"processo": p1, "doc_id": "sei:701"}
    assert (a2["doc_sha"], a2["inicio"], a2["fim"], a2["citacao"]) == (a1["doc_sha"], a1["inicio"], a1["fim"],
                                                                      a1["citacao"])
    for r in (r1, r2):
        conf = P.conferir(pg, r, con_cap=cap)             # relê o texto do documento de cada processo
        assert P.efeito_ok(conf) and not conf["divergentes"]
