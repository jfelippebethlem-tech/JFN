# -*- coding: utf-8 -*-
"""Confronto MEDIDO entre a leitura do Claude, a da LLM gratuita e a da régua determinística.

POR QUE ESTE ARQUIVO EXISTE. A leitura dupla (regra × LLM grátis) extrai sinal da DIVERGÊNCIA entre
os dois — e divergência só enxerga campo que alguém perguntou. Os dois maiores achados de leitura
desta sessão vieram de fora dela, de um terceiro leitor sem o formulário na mão:

  · a **Ata de Registro de Preços**, instrumento presente em 21% do acervo e que ninguém perguntava
    (a LLM respondia `contrato: NAO_CONSTA` e estava CERTA — só que o instrumento existia);
  · a **regra tributária da planilha de retenção** (`Art. 2º-A da IN RFB nº 1234`), que fundamenta
    RETENÇÃO DE IMPOSTO com a mesma fórmula do fundamento da despesa, e entrava limpa.

Nos dois casos os dois leitores CONCORDAVAM, e o laudo saía completo e errado por omissão.

E o confronto corta os dois lados: num processo dei como falso positivo um ARP que a régua achara, e
o texto de fato trazia `ade- são de ata de registro de preços nº 007/2022`, quebrado por hifenização
de linha. **Eu li um trecho; ela leu o documento.** A leitura do Claude não é gabarito automático —
é a terceira opinião, e vale pelo que sobrevive à conferência.

O gabarito ACUMULA: cada rodada acrescenta processos lidos à mão, e o placar é recalculado sobre
todos. Sem isso, cada confronto morre na rodada em que aconteceu e vira anedota.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_GAB = _REPO / "data" / "gabaritos_sei.json"
_DB = _REPO / "data" / "compliance.db"

# Só os campos objetivamente conferíveis. `o_que_e` e `chama_atencao` são juízo — entram no laudo,
# não no placar, porque discordância de redação não é erro de leitura.
CAMPOS = ("contrato", "pregao", "arp", "dispositivo", "favorecido")


def _so_digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


# `?` = NÃO CONFERI. Distinção que o primeiro placar exigiu: eu havia marcado `NAO_CONSTA` no
# `favorecido` de vários processos onde simplesmente não fui atrás do CNPJ, e a régua — que o tira
# da Ordem Bancária, fonte canônica — apareceu com 33% de acerto. Gabarito que afirma AUSÊNCIA onde
# o leitor apenas NÃO OLHOU pune justamente quem acertou. Campo com `?` sai do placar.
NAO_CONFERI = "?"


def _ausente(v) -> bool:
    """Afirma que não há? `00000000 - SEM CONTRATO` afirma, e tem dígitos.

    A versão anterior exigia a string EXATA e por isso não reconhecia o literal do SIAFE — que
    começa com `00000000` e portanto passava por `_so_digitos`. Efeito medido: 15 dos 26 "erros" da
    LLM em `contrato` eram ela dizendo `00000000 - SEM CONTRATO` contra um gabarito `NAO_CONSTA`.
    A mesma coisa, contada como divergência — exatamente o defeito que abriu esta sessão, agora
    dentro da ferramenta que julga os outros.
    """
    t = str(v).strip().upper()
    if "SEM CONTRATO" in t or "NAO_CONSTA" in t or "NÃO CONSTA" in t:
        return True
    return _so_digitos(v) == "" or t in {"NÃO_CONSTA", "N/A", "NONE", "NULL", ""}


def concorda(a, b) -> bool:
    """Mesma resposta, tolerando grafia — `PE 008/23` × `008/23`, `R$ 1.000,00` × `1000.00`.

    Ausência casa com ausência: `NAO_CONSTA`, vazio e `SEM CONTRATO` afirmam a mesma coisa, e tratar
    isso como divergência foi o defeito que afogou 61 das 77 primeiras linhas da fila.
    """
    if _ausente(a) and _ausente(b):
        return True
    if _ausente(a) or _ausente(b):
        return False
    da, db = _so_digitos(a), _so_digitos(b)
    return da == db or da in db or db in da


def conferir(proc: str, max_chars: int = 150_000) -> dict:
    """Todos os instrumentos que o documento INTEIRO menciona, por tipo.

    NASCEU DE UM VIÉS MEDIDO. Eu montava o gabarito lendo TRECHOS, e em CINCO casos escrevi
    `NAO_CONSTA` onde o documento tinha o instrumento — sempre na mesma direção, sempre subestimando
    o leitor bom. Um gabarito enviesado para a ausência levaria a "consertar" régua que está certa,
    que é o erro mais caro possível numa ferramenta de fiscalização.

    A busca por documento inteiro elimina o viés e é mais rápida que ler recorte. Usar ANTES de
    escrever qualquer `NAO_CONSTA`.
    """
    from tools.sei_confronto_llm import texto_do_processo
    from tools.sei_leitura_dupla import extrair_deterministico
    texto = texto_do_processo(proc, max_chars=max_chars) or ""
    if not texto:
        return {}
    # USA O EXTRATOR, NÃO O PADRÃO CRU. A primeira versão rodava `_PADROES` direto e exibia o que a
    # régua DESCARTA: `com fundamento nos art. 28º` — o rodapé da assinatura eletrônica — aparecia
    # em quase todo processo, já filtrado no extrator. Ferramenta de REFERÊNCIA que mostra ruído
    # descartado induz ao erro quem monta o gabarito, e o gabarito é o que julga todos os leitores.
    #
    # `dispositivo` entra porque é o campo MENOS medido (18 de 71) e o mais disputado
    # (LLM 77% × régua 33%): sem conferir, a medida do campo mais controverso fica a mais rasa.
    m = re.search(r"/(\d{4})$", proc)
    det = extrair_deterministico(texto, ano_proc=int(m.group(1)) if m else 0)
    de_para = {"favorecido": "cnpjs", "valor": "valores"}
    achados: dict = {}
    for campo in ("contrato", "arp", "pregao", "tac", "dispositivo"):
        d = det.get(de_para.get(campo, campo)) or {}
        vals = ([d["valor"]] if d.get("valor") else []) + [a["valor"] for a in d.get("alternativas", [])]
        achados[campo] = vals[:6]
    return achados


def carregar() -> dict:
    if not _GAB.exists():
        return {}
    try:
        d = json.loads(_GAB.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def gravar(proc: str, respostas: dict, fonte: str = "claude") -> dict:
    """Acrescenta (ou corrige) a leitura do Claude para um processo. Read-modify-write no disco.

    Relê o arquivo ANTES de escrever: gravar índice sem reler apaga trabalho alheio — a casa já
    perdeu 22 processos assim.
    """
    d = carregar()
    d[proc] = {**{k: respostas.get(k, "") for k in CAMPOS}, "fonte": fonte}
    _GAB.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def auto_conferir(proc: str) -> dict | None:
    """Preenche o gabarito onde o julgamento não acrescenta nada: UM candidato só.

    Quando o documento traz um único número de instrumento, "qual é" não é juízo, é leitura — e a
    minha leitura à mão erra MAIS que a régua nesse caso (cinco `NAO_CONSTA` falsos). Automatizar
    aqui amplia a cobertura do confronto sem inventar referência.

    CIRCULARIDADE DECLARADA: como os candidatos vêm da régua, uma entrada assim NÃO mede a régua —
    ela concorda consigo mesma por construção. Mede a LLM, que não participou da conferência. Por
    isso a entrada é marcada `fonte="conferido"`, e o placar separa as duas populações.

    Campo com VÁRIOS candidatos volta `?`: ali a pergunta não tem resposta única, e escolher seria
    inventar. Campo sem nenhum volta `NAO_CONSTA` — a régua varreu o documento inteiro.
    """
    achados = conferir(proc)
    if not achados:
        return None
    r = {}
    for campo in ("contrato", "pregao", "arp"):
        vals = achados.get(campo) or []
        r[campo] = vals[0] if len(vals) == 1 else (NAO_CONFERI if vals else "NAO_CONSTA")
    r["dispositivo"] = NAO_CONFERI      # juízo, não leitura — nunca automatizar
    r["favorecido"] = NAO_CONFERI       # vem da OB, não do texto
    return r


def favorecido_pela_ob(proc: str) -> str | None:
    """Quem o processo PAGOU, pela Ordem Bancária — gabarito de `favorecido` sem gastar IA.

    A linha do `auto_conferir` já dizia "favorecido vem da OB, não do texto" e deixava `?`. Esta é a
    outra metade: a regra nº 2 da casa (OB = pagamento = verdade) dá uma TERCEIRA fonte, independente
    dos dois leitores, e por isso — ao contrário da conferência automática — ela pontua os DOIS sem
    circularidade nenhuma.

    MEDIDO em 2026-08-14, nos 32 casos de discordância com OB vinculada: a régua bate com a OB em 13,
    a LLM em 4. Isso INVERTE o que o placar dizia (LLM 100% × régua 75%), que vinha de um gabarito de
    quatro casos — amostra pequena demais para sustentar a conclusão oposta.

    DUAS RECUSAS, e é o que impede a fonte canônica de virar gabarito errado:
      · **repasse fundo-a-fundo** — em 9 dos 32 a OB pagou a Fundo/Prefeitura, e ali quem RECEBE não
        é quem foi CONTRATADO. Cobrar do leitor o CNPJ do fundo seria exigir a resposta errada;
      · **vários favorecidos** — processo que pagou a mais de um não tem resposta única, e escolher
        o maior seria inventar critério que o documento não tem.

    RESSALVA DE FONTE, medida e declarada: `obs_por_processo` lê o ESPELHO TFE, não o SIAFE. A regra
    da casa manda usar SIAFE para o CAMPO — mas o espelho é quem tem cobertura (o SIAFE guarda ~21%
    das OBs dele). Medida a concordância entre os dois sobre A QUAL PROCESSO cada OB pertence, com a
    chave completa `(numero_ob, exercicio, ug)`: **94% concordam, 5% divergem** (10.037 OBs). Este
    gabarito herda esse 5% de risco de atribuição — o que é aceitável para MEDIR leitor, e não seria
    para acusar. Achado que dependa de uma OB isolada tem de ser reconferido no SIAFE antes de sair.
    """
    from tools.sei_leitura_dupla import pagamento_do_processo

    pg = pagamento_do_processo(proc)
    if not pg.get("tem_ob") or pg.get("n_favorecidos") != 1:
        return None
    nome = str(pg.get("maior_favorecido_nome") or "")
    if re.search(r"fundo|prefeitura|municip|secretaria|estado\s+d", nome, re.I):
        return None                      # repasse, não contratação — ver docstring
    cnpj = re.sub(r"\D", "", str(pg.get("maior_favorecido") or ""))
    return cnpj if len(cnpj) == 14 else None


def preencher_favorecido_pela_ob(procs: list[str]) -> int:
    """Grava o favorecido da OB nos processos onde ela decide. Devolve quantos preencheu."""
    d = carregar()
    n = 0
    for proc in procs:
        cnpj = favorecido_pela_ob(proc)
        if not cnpj:
            continue
        entrada = dict(d.get(proc) or {k: NAO_CONFERI for k in CAMPOS})
        if entrada.get("favorecido") == cnpj and entrada.get("fonte_favorecido") == "ob":
            continue
        entrada["favorecido"] = cnpj
        entrada["fonte_favorecido"] = "ob"        # independente dos dois leitores: pontua ambos
        entrada.setdefault("fonte", "ob")
        d[proc] = entrada
        n += 1
    if n:
        _GAB.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return n


_COD_SIAFE = re.compile(r"^\s*(\d{2})(\d{6})\b")      # `21000251`, `21000251 - CONTRATO DE GESTÃO`


def outro_sistema_de_identificacao(alvo: str, valor: str) -> bool:
    """A resposta designa o instrumento no código do SIAFE, não na forma `NNN/AAAA` do documento.

    MEDIDO em 2026-08-14: 31 dos 71 "erros" da LLM em `contrato` não têm a forma `NNN/AAAA`. Abrindo
    os documentos, as DUAS formas convivem no mesmo processo:
        `21000251` ↔ `CONTRATO DE GESTÃO Nº 002/2021`
        `22002069` ↔ `Contrato Nº 043/2022`
        `25039141` ↔ `CONTRATO SEEDUC nº 02/2025`
    e o prefixo de dois dígitos é o ano, batendo nos três. É o mesmo formato do literal que a casa já
    reconhece em `00000000 - SEM CONTRATO`. A LLM não leu outro contrato: leu o mesmo, no sistema de
    identificação do SIAFE.

    POR QUE "NÃO MEDI" E NÃO "ACERTOU". Procurei a tabela que ligasse os dois códigos e **não existe
    no banco** — nenhuma coluna guarda `21000251`. A sequência (`000251`) não deriva do número do
    documento (`002`), então não há aritmética que prove a identidade; só o ano bate. Com evidência
    forte e prova ausente, a casa declara em vez de forçar: o campo sai da conta da IA, como já
    acontece com `nao_perguntado`. Contar como acerto seria premiar o que não provei; contar como
    erro seria punir quem respondeu certo noutro sistema — e foi o que o placar vinha fazendo.
    """
    m = _COD_SIAFE.match(str(valor or ""))
    if not m:
        return False
    ano_alvo = re.search(r"/\s*(\d{2})?(\d{2})\s*$", str(alvo or ""))
    return bool(ano_alvo and m.group(1) == ano_alvo.group(2))


def placar_por_unidade(campo: str = "favorecido", minimo: int = 30) -> list:
    """O mesmo placar, quebrado por UNIDADE — porque o agregado se move com a FILA, não com o leitor.

    MEDIDO três vezes, sempre a mesma armadilha: o número agregado caiu 8 pontos em `favorecido` e eu
    quase tratei como regressão do leitor. Quebrando por recência, a LLM tinha ido de 76% para **34%**
    enquanto a RÉGUA fazia 184/184 no mesmo lote — e a causa era composição: o lote recente era 34%
    da UG 260007 contra 13% no anterior, e 8% da 330003, que era ZERO. A fila entrou em unidades
    quase ausentes até então.

    Antes disso a régua "subiu" de 36% para 86% (o gabarito da OB só cobre processo de UM favorecido
    não-fundo, que é o fácil), e caiu 14-19 pontos quando entraram os 372 processos recuperados do
    cache. Nas TRÊS vezes o leitor não tinha mudado.

    Por isso esta função existe: "a LLM faz 70% em favorecido" é frase sem sentido sem dizer sobre
    QUAL população. `minimo` corta unidades com amostra pequena demais para significar coisa alguma.
    """
    gab = carregar()
    if not gab:
        return []
    con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=60)
    try:
        linhas = {r[0]: (r[1], r[2]) for r in con.execute(
            "SELECT numero_sei, deterministico, ia FROM sei_leitura_dupla")}
    finally:
        con.close()
    de_para = {"favorecido": "cnpjs", "arp": "arp"}
    por_ug: dict = {}
    for proc, esperado in gab.items():
        linha = linhas.get(proc)
        if not linha:
            continue
        alvo = str(esperado.get(campo, "")).strip()
        if not alvo or alvo == NAO_CONFERI:
            continue
        ug = proc[:6]
        d = por_ug.setdefault(ug, {"ia_ok": 0, "ia_n": 0, "re_ok": 0, "re_n": 0})
        det = json.loads(linha[0] or "{}")
        ia = (json.loads(linha[1] or "{}").get("fatos") or {})
        if campo in ia:
            d["ia_n"] += 1
            d["ia_ok"] += 1 if concorda(alvo, ia.get(campo, "")) else 0
        v_re = (det.get(de_para.get(campo, campo)) or {}).get("valor", "")
        d["re_n"] += 1
        d["re_ok"] += 1 if concorda(alvo, v_re) else 0
    saida = [(ug, v) for ug, v in por_ug.items() if v["re_n"] >= minimo]
    saida.sort(key=lambda x: -x[1]["re_n"])
    return saida


def placar() -> dict:
    """Quanto a LLM grátis e a régua acertam CONTRA a leitura do Claude, campo a campo."""
    gab = carregar()
    if not gab:
        return {"ok": False, "erro": "gabarito vazio"}
    con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=60)
    try:
        linhas = {r[0]: r for r in con.execute(
            "SELECT numero_sei, deterministico, ia FROM sei_leitura_dupla")}
    finally:
        con.close()
    r = {"processos": 0, "ia": {}, "regra": {}, "conferidos": 0}
    de_para = {"favorecido": "cnpjs", "arp": "arp"}
    for proc, esperado in gab.items():
        linha = linhas.get(proc)
        if not linha:
            continue
        automatico = esperado.get("fonte") == "conferido"
        r["processos"] += 1
        r["conferidos"] += 1 if automatico else 0
        det = json.loads(linha[1] or "{}")
        ia = (json.loads(linha[2] or "{}").get("fatos") or {})
        fatos_ia = ia if isinstance(ia, dict) else {}
        for campo in CAMPOS:
            alvo = esperado.get(campo, "")
            if str(alvo).strip() == NAO_CONFERI:
                continue                      # não conferi: não conta a favor nem contra ninguém
            # CAMPO QUE A IA NUNCA FOI PERGUNTADA NÃO CONTA CONTRA ELA. `arp` e `tac` entraram no
            # formulário no meio da sessão: as leituras anteriores não têm a chave, e o placar as
            # penalizava como se ela tivesse calado. Medido: **19 dos 20 "erros" em `arp` eram
            # isso** — a fila já tratava o caso (`nao_perguntado`), o placar não.
            #
            # A marca é a CHAVE FALTANDO: o extrator preenche todo campo perguntado, mesmo vazio.
            # Pula SÓ a pontuação da IA — a régua respondeu e continua sendo medida. Pular o campo
            # inteiro (primeira tentativa) derrubou o denominador dela de 43 para 7 e apagou medida
            # boa: quem não foi perguntada foi a IA, não ela.
            ia_perguntada = campo in fatos_ia
            v_ia = ia.get(campo, "")
            # RESPOSTA NOUTRO SISTEMA DE IDENTIFICAÇÃO não é resposta errada — ver a função.
            if ia_perguntada and outro_sistema_de_identificacao(alvo, v_ia):
                ia_perguntada = False
                r.setdefault("outro_sistema", {})
                r["outro_sistema"][campo] = r["outro_sistema"].get(campo, 0) + 1
            v_re = (det.get(de_para.get(campo, campo)) or {}).get("valor", "")
            # entrada automática NÃO pontua a régua: os candidatos vieram dela, e ela concordaria
            # consigo mesma. Pontua só a LLM, que não participou da conferência.
            #
            # A CIRCULARIDADE É POR CAMPO, NÃO POR PROCESSO. `favorecido` vindo da OB é terceira
            # fonte — não saiu de nenhum dos dois leitores — e por isso pontua os DOIS mesmo numa
            # entrada automática. Tratar o processo inteiro como circular apagaria justamente a
            # única medida independente que existe no confronto.
            circular = automatico and not (
                campo == "favorecido" and esperado.get("fonte_favorecido") == "ob")
            pares = ((("ia", v_ia),) if ia_perguntada else ()) if circular else (
                ((("ia", v_ia),) if ia_perguntada else ()) + (("regra", v_re),))
            for quem, valor in pares:
                b = r[quem].setdefault(campo, {"acerto": 0, "erro": 0})
                b["acerto" if concorda(alvo, valor) else "erro"] += 1
    return {"ok": True, **r}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--gravar", help="processo a registrar (com --campos)")
    ap.add_argument("--campos", help='JSON: {"contrato":"85/2022","arp":"NAO_CONSTA",...}')
    ap.add_argument("--placar", action="store_true")
    ap.add_argument("--por-unidade", metavar="CAMPO", nargs="?", const="favorecido",
                    help="placar quebrado por UG (o agregado se move com a fila, não com o leitor)")
    ap.add_argument("--conferir", help="lista os instrumentos que o processo INTEIRO menciona")
    ap.add_argument("--favorecido-ob", action="store_true",
                    help="preenche `favorecido` pela OB (fonte canônica) em todo processo lido")
    a = ap.parse_args(argv)
    if a.por_unidade:
        campo = a.por_unidade
        linhas = placar_por_unidade(campo)
        if not linhas:
            print(f"sem unidade com amostra suficiente para `{campo}`", file=sys.stderr)
            return 1
        print(f"placar de `{campo}` POR UNIDADE (amostra >= 30)\n")
        print(f"{'UG':8}{'LLM grátis':>16}{'régua':>16}")
        for ug, v in linhas:
            ia = f"{v['ia_ok']}/{v['ia_n']} ({100*v['ia_ok']//max(v['ia_n'],1)}%)"
            re_ = f"{v['re_ok']}/{v['re_n']} ({100*v['re_ok']//max(v['re_n'],1)}%)"
            print(f"{ug:8}{ia:>16}{re_:>16}")
        return 0
    if a.favorecido_ob:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=60)
        try:
            procs = [r[0] for r in con.execute("SELECT numero_sei FROM sei_leitura_dupla")]
        finally:
            con.close()
        print(f"favorecido preenchido pela OB: {preencher_favorecido_pela_ob(procs)} de {len(procs)}")
        return 0
    if a.conferir:
        for campo, v in conferir(a.conferir).items():
            print(f"  {campo:9}: {v if v else 'NENHUM no documento inteiro'}")
        return 0
    if a.gravar and a.campos:
        d = gravar(a.gravar, json.loads(a.campos))
        print(f"gabarito: {len(d)} processos lidos pelo Claude")
        return 0
    p = placar()
    if not p.get("ok"):
        print(p.get("erro"), file=sys.stderr)
        return 1
    print(f"placar contra a leitura do Claude — {p['processos']} processos\n")
    print(f"{'campo':12} {'LLM grátis':>14}   {'régua':>14}")
    for campo in CAMPOS:
        i, g = p["ia"].get(campo, {}), p["regra"].get(campo, {})
        ti, tg = i.get("acerto", 0) + i.get("erro", 0), g.get("acerto", 0) + g.get("erro", 0)
        pi = f"{i.get('acerto',0)}/{ti} ({100*i.get('acerto',0)//max(ti,1)}%)"
        pg = f"{g.get('acerto',0)}/{tg} ({100*g.get('acerto',0)//max(tg,1)}%)"
        print(f"{campo:12} {pi:>14}   {pg:>14}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
