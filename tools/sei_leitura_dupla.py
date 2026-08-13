#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lê cada processo DUAS vezes — por regra e por IA — e confronta as duas leituras.

POR QUE DUAS. A leitura determinística (regex) é barata, reproduzível e não inventa; mas só acha o
que foi previsto, e cala diante de qualquer forma nova de escrever a mesma coisa. A leitura
interpretativa (LLM) generaliza e resume; mas é cara, varia entre chamadas e — este é o risco real
— pode inventar com cara de resposta. Nenhuma das duas basta.

O VALOR NÃO ESTÁ NA MÉDIA DAS DUAS: ESTÁ NA DISCORDÂNCIA. Onde as duas concordam, o fato está
duplamente confirmado e ninguém precisa ler. Onde discordam, ou a regra é estreita ou a IA inventou
— e é exatamente ali que a leitura humana vale o tempo. Este módulo existe para produzir essa fila.

Confrontado contra gabarito conferido à mão em 2026-08-12 (`tools/sei_confronto_llm`): com contexto
suficiente, o modelo `:free` acertou 14 de 14 fatos com **zero invenção**; com contexto cortado,
omitiu 5 e continuou sem inventar. Ou seja, a IA falha por OMISSÃO — que a regra cobre — e a regra
falha por ESTREITEZA — que a IA cobre. As duas juntas fecham o vão.

O SUBJETIVO SAI SEPARADO, e não se mistura com o fato. A IA também responde perguntas de juízo (o
que o processo faz, o que chama atenção, o que falta nos autos). Isso vai para um campo próprio,
`interpretacao`, marcado como opinião a conferir — nunca somado ao que é fato confrontável.

    PYTHONPATH=. .venv/bin/python -m tools.sei_leitura_dupla --processo 030001/075841/2024
    PYTHONPATH=. .venv/bin/python -m tools.sei_leitura_dupla --amostra 5 --gravar
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from tools.sei_confronto_llm import texto_do_processo

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"
_ARQ = _REPO / "data" / "sei_arquivo"

# ── LEITURA DETERMINÍSTICA ──────────────────────────────────────────────────────────────────────
# Cada padrão devolve o valor MAIS FREQUENTE no processo, não o primeiro: documento administrativo
# repete o dado central em despacho, empenho e contrato, e o que aparece uma vez só costuma ser
# citação de outro processo. Frequência é o desempate honesto — e o módulo guarda quantas vezes,
# para quem quiser conferir.
_PADROES: dict[str, str] = {
    # `00000000 - SEM CONTRATO` é o texto LITERAL do SIAFE para despesa sem instrumento, e é fato
    # fiscal, não ruído: apareceu em 4 dos 15 primeiros processos lidos, e a regra não via nenhum —
    # quem via era a IA. Pagamento sem contrato é justamente o que se quer enxergar.
    "contrato": r"[Cc]ontrato[^\n]{0,24}n[º°o.]{0,3}\s*(\d{1,4}/20\d{2})|(0{6,8}\s*-\s*SEM CONTRATO)",
    # O DISPOSITIVO QUE INTERESSA VEM COLADO À LEI. Duas correções medidas na amostra de 2026-08-13,
    # em direções opostas:
    #   · estreita demais — exigia algarismo romano e calava diante de "art. 37, caput" e de
    #     "art. 74" solto, que a IA achou e ela não;
    #   · larga demais — ao aceitar `§`, passou a devolver "art. 5, § 2" (boilerplate de cláusula)
    #     num processo cujo dispositivo real é o art. 74 da Lei 14.133.
    # A âncora que separa os dois casos é a LEI citada por perto: dispositivo de contratação vem
    # sempre com ela ("art. 75, VIII, da Lei nº 14.133/2021"). Sem lei ao redor, é cláusula
    # contratual, não fundamento — e não entra.
    "dispositivo": (r"[Aa]rt\.?\s*(\d{1,3})\s*[º°]?\s*,?\s*(?:inciso\s*)?([IVXLC]*|caput)"
                    r"[^\n]{0,40}?(?:Lei|LEI|Constitui[çc])"),
    "processos_citados": r"\b(\d{6}/\d{6}(?:\.\d)?/\d{4})\b",
    "cnpjs": r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b",
    "valores": r"R\$\s?([\d.]{4,18},\d{2})",
    "datas": r"\b(\d{2}/\d{2}/20\d{2})\b",
    "pregao": r"[Pp]reg[ãa]o[^\n]{0,24}n[º°o.]{0,3}\s*(\d{1,4}/20\d{2})",
}


def extrair_deterministico(texto: str, ano_proc: int = 0) -> dict:
    """Fatos por REGRA. Devolve `{campo: {valor, ocorrencias, alternativas}}`.

    `alternativas` existe porque um processo cita outros: mostrar só o vencedor esconderia que
    havia dois candidatos próximos — e é justamente aí que a leitura humana decide.
    """
    out: dict = {}
    for campo, pad in _PADROES.items():
        achados = re.findall(pad, texto or "")
        if campo == "contrato":
            achados = [a or b for a, b in achados] if achados and isinstance(achados[0], tuple) else achados
            achados = ["SEM CONTRATO" if "SEM CONTRATO" in str(x).upper() else x for x in achados]
        if campo == "dispositivo":
            achados = [f"art. {a}, {b}".rstrip(", ") for a, b in achados]
        c = Counter(str(x) for x in achados if str(x).strip())
        if not c:
            out[campo] = {"valor": "", "ocorrencias": 0, "alternativas": []}
            continue
        ordenada = c.most_common()
        if campo == "valores":
            # Para dinheiro a frequência é a pergunta errada: o valor que importa é o MAIOR
            # (o total do empenho), e o repetido costuma ser a parcela ou o centavo do rodapé.
            ordenada = sorted(c.items(),
                              key=lambda kv: -float(kv[0].replace(".", "").replace(",", ".")))
        if campo in ("contrato", "pregao") and ano_proc:
            # FREQUÊNCIA SOZINHA ESCOLHE O CONTRATO ERRADO. Medido no `030001/075841/2024`: a regra
            # devolvia `08/2018` — um contrato ANTIGO citado no histórico — enquanto o instrumento
            # do processo é o `31/2024`. Documento administrativo cita o passado mais vezes do que
            # nomeia o presente. O desempate passa a exigir ano >= ano do processo, caindo para a
            # frequência pura só quando nenhum candidato satisfaz.
            recentes = [(v, n) for v, n in ordenada
                        if (m := re.search(r"/(20\d{2})$", v)) and int(m.group(1)) >= ano_proc]
            if recentes:
                ordenada = recentes + [x for x in ordenada if x not in recentes]
        (v, n), *resto = ordenada
        out[campo] = {"valor": v, "ocorrencias": n,
                      "alternativas": [{"valor": a, "ocorrencias": b} for a, b in resto[:4]]}
    return out


# ── LEITURA INTERPRETATIVA ──────────────────────────────────────────────────────────────────────
# O CONJUNTO DE CAMPOS TEM DE CASAR COM O TIPO DE PROCESSO. Medido nos 23 primeiros: **29 das 56
# divergências eram `nenhum_dos_dois`** — nem regra nem IA acharam, porque a maioria do acervo é
# processo de PAGAMENTO e ANULAÇÃO DE EMPENHO, que não tem pregão nem contrato próprio. Perguntar
# só por contrato e pregão enche a fila de campos que aquele processo nunca teve, e isso não é
# divergência: é pergunta errada.
#
# `valor` e `favorecido` existem em praticamente todo processo de despesa, e são justamente o que
# a fiscalização persegue — quem recebeu e quanto.
_FATOS = {
    "contrato": "número do contrato que ampara os pagamentos",
    "dispositivo": "dispositivo legal do enquadramento (artigo e inciso)",
    "pregao": "número do pregão/licitação citado, se houver",
    "valor": "o MAIOR valor em reais que aparece no processo",
    "favorecido": "o CNPJ do favorecido/credor do pagamento",
}
_JUIZO = {
    "o_que_e": "em uma frase, o que este processo faz",
    "chama_atencao": "o que num processo assim mereceria conferência de um fiscal, citando o "
                     "trecho que sustenta cada ponto",
    "o_que_falta": "que documento ESPERADO para esse tipo de processo não aparece nos autos",
}
_SISTEMA = (
    "Você lê processos administrativos brasileiros para fins de fiscalização. Responda SOMENTE JSON. "
    "Nos campos de FATO use EXATAMENTE o texto do documento e responda \"NAO_CONSTA\" se não houver "
    "— nunca invente. Nos campos de JUÍZO, cite o trecho dos autos que sustenta cada afirmação; se "
    "não houver base no texto, diga que não há."
)


def extrair_interpretativo(texto: str, proc: str, *, gerar=None) -> dict:
    if gerar is None:
        from compliance_agent.llm.camada_triagem import gerar_triagem
        gerar = gerar_triagem()
    campos = "\n".join(f'- "{k}": {v}' for k, v in {**_FATOS, **_JUIZO}.items())
    bruto = gerar(f"PROCESSO {proc}:\n\n{texto}\n\nResponda em JSON:\n{campos}", _SISTEMA) or ""
    if not bruto:
        return {"estado": "indisponivel", "motivo": "IA sem cota — NÃO mediu (≠ nada a apontar)"}
    # UM PROCESSO RUIM NÃO DERRUBA O LOTE. Um modelo `:free` devolveu JSON com vírgula faltando e o
    # `json.loads` estourou no meio da amostra, matando os cinco processos seguintes. A doutrina já
    # é da casa (o sweep do SEI a aplica); faltava aqui. Resposta impossível de ler vira
    # `nao_parseei`, que é um ESTADO — e estado se conta, exceção derruba.
    d = {}
    try:
        from compliance_agent.llm.json_resposta import extrair_json
        d = extrair_json(bruto) or {}
    except ImportError:
        m = re.search(r"\{.*\}", bruto, re.S)
        try:
            d = json.loads(m.group(0)) if m else {}
        except ValueError:
            d = {}
    except ValueError:
        d = {}
    if not isinstance(d, dict) or not d:
        # RESPOSTA CORTADA NÃO É RESPOSTA PERDIDA. Medido em 37 processos: **9 (24%) caíam em
        # `nao_parseei` — e ao abrir o bruto, o modelo tinha respondido CERTO.** O JSON começa
        # correto e é cortado no meio porque `chama_atencao` (lista de objetos) estoura o limite de
        # saída antes de fechar a chave. Eu descartava contrato, dispositivo e pregão já
        # preenchidos por causa de um `}` que faltou.
        #
        # A salvação é conservadora: só aceita par `"campo": "valor"` com a aspa de fechamento
        # PRESENTE — sem ela o valor pode estar cortado no meio, e meio valor é pior que nenhum.
        # Vira `ok_parcial`, não `ok`: quem lê o laudo tem de saber que veio de resposta truncada.
        salvos = {}
        for k in {**_FATOS, **_JUIZO}:
            if m := re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)"' % re.escape(k), bruto):
                salvos[k] = m.group(1)
        if salvos:
            return {"estado": "ok_parcial",
                    "fatos": {k: salvos.get(k, "") for k in _FATOS},
                    "interpretacao": {k: salvos.get(k, "") for k in _JUIZO},
                    "salvos_de_resposta_cortada": sorted(salvos)}
        return {"estado": "nao_parseei", "bruto": bruto[:300]}
    return {"estado": "ok", "fatos": {k: d.get(k, "") for k in _FATOS},
            "interpretacao": {k: d.get(k, "") for k in _JUIZO}}


def _norm(v) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^0-9A-Za-z]", "", t).upper()


def _dispositivo(v: str) -> tuple:
    """(lei, artigo, inciso) — dispositivo legal não se compara por texto, se compara por peça."""
    t = str(v or "")
    lei = m.group(1).replace(".", "") if (m := re.search(r"(?:Lei|LEI)[^\d]{0,12}(\d[\d.]{2,9})", t)) else ""
    art = m.group(1) if (m := re.search(r"[Aa]rt(?:igo|\.)?\s*(\d{1,3})", t)) else ""
    inc = m.group(1).upper() if (m := re.search(
        r"[Aa]rt(?:igo|\.)?\s*\d{1,3}\s*[º°]?\s*,?\s*(?:inciso\s*)?\b([IVXLC]{1,6})\b", t)) else ""
    return (lei, art, inc)


def _mesmo_dispositivo(a: str, b: str) -> bool:
    """MESMA RESPOSTA ESCRITA DIFERENTE NÃO É BRIGA. `art. 75, VIII` e
    `Lei nº 14.133/2021, Art. 75º, VIII` são o mesmo dispositivo — e caíam como discordância porque
    o `º` vira `O` na normalização e quebra a comparação por substring. Eram **19 das 23 brigas**.

    A comparação certa é por peça. A LEI entra na conta quando os dois a citam: art. 75 da 14.133 e
    art. 75 da 8.666 são dispositivos diferentes, e tratá-los como iguais seria pior que o defeito
    original. Quando só um lado cita a lei, comparam-se artigo e inciso — o que o texto deu.
    """
    la, aa, ia_ = _dispositivo(a)
    lb, ab, ib = _dispositivo(b)
    if not aa or not ab or aa != ab:
        return False
    if la and lb and la != lb:
        return False
    return not (ia_ and ib) or ia_ == ib


def pagamento_do_processo(proc: str) -> dict:
    """O que o processo PAGOU, pela Ordem Bancária — não pelo que o texto diz.

    MEDIDO, e é por isso que este bloco existe: extrair o favorecido do texto por regex acerta **36%**
    (13 de 36 processos com OB vinculada, conferido contra `ordens_bancarias`). A variante por
    vizinhança ganha um caso — 39%, ruído. E o TETO de qualquer régua de texto é **58%**: em 42% dos
    processos o CNPJ de quem recebeu não está escrito ali. Não é régua estreita, é fonte errada.

    A regra nº 2 da casa já dizia onde está a verdade: **OB = pagamento**. Com a junção por
    `numero_sei` consertada (era 0,2% do acervo, agora 62%), a fonte canônica ficou alcançável.

    O confronto muda de natureza para melhor: em vez de duas leituras do mesmo texto, passa a ser o
    que o processo DIZ contra o que foi PAGO — que é a pergunta da fiscalização.
    """
    from compliance_agent.correlacao_sei import obs_por_processo
    obs = obs_por_processo(proc)
    if not obs:
        return {"tem_ob": False}
    porc: Counter = Counter()
    for o in obs:
        porc[(str(o.get("favorecido_cpf") or ""), str(o.get("favorecido_nome") or ""))] += o.get("valor") or 0
    (cpf, nome), val = max(porc.items(), key=lambda kv: kv[1])
    return {"tem_ob": True, "n_obs": len(obs), "total": sum(o.get("valor") or 0 for o in obs),
            "maior_favorecido": cpf, "maior_favorecido_nome": nome, "maior_valor": val,
            "n_favorecidos": len(porc),
            # O CONJUNTO, não só o maior. Um processo do acervo paga 1.199 favorecidos (repasse do
            # PNAE às escolas): ali "o favorecido" não tem resposta única, e cobrar da IA o MAIOR
            # fabricaria briga onde ela acertou um dos legítimos. A conferência certa é pertinência.
            "favorecidos": {re.sub(r"\D", "", c) for c, _ in porc}}


def confrontar(proc: str, *, max_chars: int = 250_000, gerar=None) -> dict:
    """Lê pelos dois caminhos e devolve o laudo com a FILA DE DISCORDÂNCIA."""
    texto = texto_do_processo(proc, max_chars=max_chars)
    if not texto:
        return {"ok": False, "processo": proc, "erro": "processo não está no acervo"}
    _m = re.search(r"/(\d{4})$", proc)
    det = extrair_deterministico(texto, ano_proc=int(_m.group(1)) if _m else 0)
    ia = extrair_interpretativo(texto, proc, gerar=gerar)
    pago = pagamento_do_processo(proc)
    if pago.get("tem_ob"):
        # A OB PREPONDERA sobre o regex para dinheiro e favorecido — é a fonte canônica da casa.
        det["cnpjs"] = {"valor": pago["maior_favorecido"], "ocorrencias": pago["n_obs"],
                        "fonte": "ordem bancária", "alternativas": []}
        det["valores"] = {"valor": f"{pago['total']:,.2f}".replace(",", "§").replace(".", ",")
                          .replace("§", "."), "ocorrencias": pago["n_obs"],
                          "fonte": "ordem bancária", "alternativas": []}
    acordo, discordancia, ausencia = {}, {}, {}
    _DE_PARA = {"valor": "valores", "favorecido": "cnpjs"}   # o nome da pergunta ≠ o do padrão
    for campo in _FATOS:
        v_det = det.get(_DE_PARA.get(campo, campo), {}).get("valor", "")
        v_ia = (ia.get("fatos") or {}).get(campo, "")
        n_det, n_ia = _norm(v_det), _norm(v_ia)
        # CAMPO NUMÉRICO EXIGE NÚMERO. A IA respondeu "Pregão Eletrônico" — a modalidade, não o
        # número — e isso entrava como se fosse achado que a regra perdeu. Sem dígito e sem o token
        # de ausência do SIAFE, não é resposta para `contrato`/`pregao`.
        # E MÁSCARA NÃO É NÚMERO: a IA devolveu "0XX/2023" — placeholder do próprio documento —
        # e com dígito ele passaria como resposta.
        _mascara = bool(re.search(r"[Xx]{2,}", str(v_ia)))
        _sem_digito = campo in ("contrato", "pregao") and (
            _mascara or (not re.search(r"\d", str(v_ia))
                         and "SEM CONTRATO" not in str(v_ia).upper()))
        if not n_ia or _sem_digito or n_ia in ("NONE", "NULL", "NA") or "NAOCONSTA" in n_ia:
            estado = "so_regra" if n_det else "nenhum_dos_dois"
        elif not n_det:
            estado = "so_ia"
        elif campo == "favorecido" and pago.get("tem_ob") and \
                re.sub(r"\D", "", str(v_ia)) in pago["favorecidos"]:
            estado = "acordo"     # acertou UM dos que de fato receberam — basta
        elif campo == "dispositivo" and _mesmo_dispositivo(v_det, v_ia):
            estado = "acordo"
        elif n_det in n_ia or n_ia in n_det:
            estado = "acordo"
        else:
            estado = "discordam"
        # OS DOIS DIZEREM "NÃO EXISTE" NÃO É DIVERGÊNCIA. Medido em 31 processos: das 77 linhas na
        # fila, **61 eram a IA respondendo `NAO_CONSTA` com a regra vazia** — a MESMA resposta, posta
        # na fila de leitura humana como se os leitores brigassem. Isso inflava a divergência e
        # afogava o sinal de verdade, que são as 16 linhas onde alguém achou algo.
        #
        # Mas também não é acordo: acordo é os dois acharem o MESMO valor. Concordar sobre ausência
        # é o terceiro estado — o mesmo veredito de três valores que o painel já usa (OK/FALHOU/NÃO
        # MEDI): declarar que não há o que comparar em vez de fingir um dos dois extremos.
        destino = (acordo if estado == "acordo"
                   else ausencia if estado == "nenhum_dos_dois" else discordancia)
        destino[campo] = {
            "regra": v_det, "ia": v_ia, "estado": estado,
            "ocorrencias_regra": det.get(campo, {}).get("ocorrencias", 0)}
    return {"ok": True, "processo": proc, "chars": len(texto), "truncado": len(texto) >= max_chars,
            "deterministico": det, "ia": ia, "pagamento": pago,
            "acordo": acordo, "discordancia": discordancia,
            "ausencia_concorde": ausencia,
            "n_acordo": len(acordo), "n_discordancia": len(discordancia),
            "n_ausencia": len(ausencia),
            "ressalva": ("Acordo entre regra e IA é fato duplamente confirmado; ausência concorde é "
                         "campo que o processo não tem (não é briga entre leitores); discordância é fila "
                         "de leitura humana, não veredito. O campo `interpretacao` é OPINIÃO a "
                         "conferir e nunca vira achado sozinho.")}


# CARIMBO DA RÉGUA. As primeiras 31 linhas foram medidas contando "os dois dizem que não existe"
# como DIVERGÊNCIA — 61 das 77 linhas da fila eram isso. A régua mudou; as linhas antigas não. Somar
# as duas no painel seria misturar medidas silenciosamente, que é o vício de mentir por omissão.
# O carimbo deixa a rota DECLARAR quantas vieram da régua velha em vez de fingir que é tudo igual.
REGUA = "2026-08-13/ausencia-concorde"


def _gravar(con: sqlite3.Connection, laudo: dict) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS sei_leitura_dupla (
        numero_sei TEXT PRIMARY KEY, chars INTEGER, truncado INTEGER,
        n_acordo INTEGER, n_discordancia INTEGER, deterministico TEXT, ia TEXT,
        discordancia TEXT, lido_em TEXT)""")
    existentes = {r[1] for r in con.execute("PRAGMA table_info(sei_leitura_dupla)")}
    for col, tipo in (("n_ausencia", "INTEGER"), ("ausencia_concorde", "TEXT"), ("regua", "TEXT")):
        if col not in existentes:
            con.execute(f"ALTER TABLE sei_leitura_dupla ADD COLUMN {col} {tipo}")
    con.execute("""INSERT OR REPLACE INTO sei_leitura_dupla
        (numero_sei, chars, truncado, n_acordo, n_discordancia, deterministico, ia,
         discordancia, lido_em, n_ausencia, ausencia_concorde, regua)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (laudo["processo"], laudo["chars"], int(laudo["truncado"]), laudo["n_acordo"],
                 laudo["n_discordancia"], json.dumps(laudo["deterministico"], ensure_ascii=False),
                 json.dumps(laudo["ia"], ensure_ascii=False),
                 json.dumps(laudo["discordancia"], ensure_ascii=False),
                 datetime.now().isoformat(timespec="seconds"), laudo["n_ausencia"],
                 json.dumps(laudo["ausencia_concorde"], ensure_ascii=False), REGUA))
    con.commit()


def _pendentes(con: sqlite3.Connection, n: int) -> list[str]:
    """Processos do acervo ainda sem leitura dupla — os maiores primeiro (mais texto, mais fato)."""
    # LEITURA QUE FALHOU NÃO É LEITURA FEITA. Quem caiu em `nao_parseei` ficou gravado na tabela e,
    # por estar lá, nunca mais voltaria à fila — 9 processos (24%) sumiriam do acervo em silêncio,
    # justamente os que a salvação de resposta cortada agora recupera. `indisponivel` (IA sem cota)
    # entra pelo mesmo motivo: não medimos, e não medir não é nada a apontar.
    try:
        lidos = {r[0] for r in con.execute(
            "SELECT numero_sei FROM sei_leitura_dupla "
            "WHERE ia NOT LIKE '%\"nao_parseei\"%' AND ia NOT LIKE '%\"indisponivel\"%'")}
    except sqlite3.Error:
        lidos = set()
    cands = []
    for d in _ARQ.iterdir():
        if not d.is_dir():
            continue
        p = d.name.split("_")
        if len(p) < 3:
            continue
        proc = f"{p[0]}/{p[1]}/{p[2]}"
        if proc in lidos:
            continue
        t = d / "texto"
        cands.append((sum(f.stat().st_size for f in t.glob("*.txt")) if t.is_dir() else 0, proc))
    cands.sort(reverse=True)
    return [p for _, p in cands[:n]]


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--processo")
    ap.add_argument("--amostra", type=int, default=0, help="N processos ainda não lidos")
    ap.add_argument("--gravar", action="store_true")
    ap.add_argument("--max-chars", type=int, default=250_000)
    # FATIA PARA RODAR EM PARALELO SEM DUPLICAR. A leitura é presa a REDE (chamada de IA), não a
    # CPU: com um lote só, a VM fica em load 1,5 e o acervo de 2.357 levaria ~4 dias. Dois lotes
    # simultâneos, porém, chamariam `_pendentes` e receberiam A MESMA lista — trabalho e chamada de
    # IA em dobro pelo mesmo processo. A fatia `i/n` reparte a fila de forma determinística.
    ap.add_argument("--fatia", help="i/n — lê só a fatia i de n (ex.: 0/2 e 1/2 em paralelo)")
    a = ap.parse_args(argv)
    con = sqlite3.connect(str(_DB), timeout=120)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        if a.processo:
            alvos = [a.processo]
        elif a.fatia:
            i, n = (int(x) for x in a.fatia.split("/"))
            if not 0 <= i < n:
                raise SystemExit(f"--fatia {a.fatia}: i tem de estar em [0, n)")
            alvos = _pendentes(con, (a.amostra or 3) * n)[i::n]
        else:
            alvos = _pendentes(con, a.amostra or 3)
        tot = Counter()
        for proc in alvos:
            try:
                r = confrontar(proc, max_chars=a.max_chars)
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                print(f"  ⚠️  {proc}: {type(exc).__name__}: {str(exc)[:70]} — segue o lote")
                tot["erro"] += 1
                continue
            if not r.get("ok"):
                print(f"  ⚠️  {proc}: {r.get('erro')}"); continue
            est = r["ia"].get("estado")
            tot["processos"] += 1; tot["acordo"] += r["n_acordo"]
            tot["discordancia"] += r["n_discordancia"]; tot["ausencia"] += r["n_ausencia"]
            tot[f"ia:{est}"] += 1
            print(f"\n{proc} · {r['chars']:,} chars".replace(",", ".")
                  + (" (TRUNCADO)" if r["truncado"] else "") + f" · IA: {est}")
            for campo, d in {**r["acordo"], **r["discordancia"]}.items():
                marca = {"acordo": "✅", "discordam": "❗", "so_regra": "📏",
                         "so_ia": "🤖", "nenhum_dos_dois": "➖"}[d["estado"]]
                print(f"   {marca} {campo:12} regra={str(d['regra'])[:26]!r}")
                print(f"      {'':12} ia   ={str(d['ia'])[:60]!r}")
            interp = (r["ia"].get("interpretacao") or {})
            if interp.get("o_que_e"):
                print(f"   🧠 {str(interp['o_que_e'])[:150]}")
            if a.gravar:
                _gravar(con, r)
        print(f"\nresumo: {dict(tot)}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
