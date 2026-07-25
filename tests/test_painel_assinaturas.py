"""Toda aba do painel tem assinatura, e nenhuma foge da familia da esfera.

O v14 da a cada uma das 51 abas uma identidade propria — matiz, glifo, lema e
instrumento. A identidade sai de UMA tabela de dados, nao de 51 blocos de CSS
escritos a mao; e esta tabela e o unico ponto onde ela pode divergir.

Tres coisas travadas aqui, cada uma por um motivo:

1. COBERTURA — quem acrescentar aba e esquecer a assinatura recebe uma aba sem
   identidade, que e exatamente o defeito que o v14 existe para corrigir. Pego em
   teste, nao em revisao de codigo.
2. FAMILIA — a matiz da faceta e RELATIVA a esfera e limitada a +-34 graus. Sem
   esse teto o painel vira arco-iris e a esfera perde a voz. E a regra "restrained"
   do DESIGN.md, que nao se sustenta em 51 telas por disciplina do autor.
3. LIGACAO — sem `data-aba` no <body>, nenhuma regra por aba existe e as 51
   assinaturas morrem juntas, em silencio. Presenca nominal, custo zero.

Nao roda navegador: le o HTML. Vale na VM-2, que roda a suite sem Chrome.
"""

import json
import re
from pathlib import Path

from tools.painel_abas import abas

PAINEL = Path(__file__).resolve().parents[1] / "static" / "jfn-painel.html"
LIMITE_MATIZ = 34
INSTRUMENTOS = {"fila", "rede", "tempo", "moeda", "mapa", "pessoa"}


def _assinaturas() -> dict[str, dict]:
    fonte = PAINEL.read_text(encoding="utf-8")
    m = re.search(r"const ASSINATURA=\{(.*?)\n\};", fonte, re.S)
    assert m, "o painel perdeu o registro `const ASSINATURA={...}`"
    fora: dict[str, dict] = {}
    for aba, corpo in re.findall(r"(\w+):\{([^}]*)\}", m.group(1)):
        campos = dict(re.findall(r"(\w+):\s*(-?\d+|'[^']*')", corpo))
        fora[aba] = {
            k: int(v) if re.fullmatch(r"-?\d+", v) else v.strip("'")
            for k, v in campos.items()
        }
    return fora


def test_toda_aba_tem_assinatura():
    assinaturas, esperadas = _assinaturas(), abas()
    faltando = [a for a in esperadas if a not in assinaturas]
    sobrando = [a for a in assinaturas if a not in esperadas]
    assert not faltando, "aba sem assinatura (fica sem identidade na tela): " + ", ".join(faltando)
    assert not sobrando, "assinatura de aba que nao existe mais: " + ", ".join(sobrando)


def test_campos_obrigatorios_preenchidos():
    for aba, a in _assinaturas().items():
        for campo in ("h", "gl", "lema", "inst"):
            assert campo in a, f"{aba}: falta o campo `{campo}`"
        assert a["lema"].strip(), f"{aba}: lema vazio"
        assert not a["lema"].endswith("."), (
            f"{aba}: o lema e legenda de instrumento, nao frase — sem ponto final"
        )
        assert a["inst"] in INSTRUMENTOS, f"{aba}: instrumento `{a['inst']}` nao existe"


def test_matiz_fica_na_familia_da_esfera():
    fora_da_faixa = {
        aba: a["h"] for aba, a in _assinaturas().items() if abs(a["h"]) > LIMITE_MATIZ
    }
    assert not fora_da_faixa, (
        f"matiz de faceta fora de +-{LIMITE_MATIZ} graus da esfera — o painel vira "
        "arco-iris e a esfera perde a voz: " + json.dumps(fora_da_faixa, ensure_ascii=False)
    )


def test_ir_publica_a_aba_no_body():
    fonte = PAINEL.read_text(encoding="utf-8")
    assert "document.body.dataset.aba=id" in fonte, (
        "`ir()` parou de publicar a aba no <body> — as 51 assinaturas morrem juntas"
    )
    assert "_ESF_MATIZ" in fonte, "a matiz base por esfera sumiu"
