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
_FATOS = {
    "contrato": "número do contrato que ampara os pagamentos",
    "dispositivo": "dispositivo legal do enquadramento (artigo e inciso)",
    "pregao": "número do pregão/licitação citado, se houver",
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
        return {"estado": "nao_parseei", "bruto": bruto[:300]}
    return {"estado": "ok", "fatos": {k: d.get(k, "") for k in _FATOS},
            "interpretacao": {k: d.get(k, "") for k in _JUIZO}}


def _norm(v) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^0-9A-Za-z]", "", t).upper()


def confrontar(proc: str, *, max_chars: int = 250_000, gerar=None) -> dict:
    """Lê pelos dois caminhos e devolve o laudo com a FILA DE DISCORDÂNCIA."""
    texto = texto_do_processo(proc, max_chars=max_chars)
    if not texto:
        return {"ok": False, "processo": proc, "erro": "processo não está no acervo"}
    _m = re.search(r"/(\d{4})$", proc)
    det = extrair_deterministico(texto, ano_proc=int(_m.group(1)) if _m else 0)
    ia = extrair_interpretativo(texto, proc, gerar=gerar)
    acordo, discordancia = {}, {}
    for campo in _FATOS:
        v_det = det.get(campo, {}).get("valor", "")
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
        elif n_det in n_ia or n_ia in n_det:
            estado = "acordo"
        else:
            estado = "discordam"
        (acordo if estado == "acordo" else discordancia)[campo] = {
            "regra": v_det, "ia": v_ia, "estado": estado,
            "ocorrencias_regra": det.get(campo, {}).get("ocorrencias", 0)}
    return {"ok": True, "processo": proc, "chars": len(texto), "truncado": len(texto) >= max_chars,
            "deterministico": det, "ia": ia, "acordo": acordo, "discordancia": discordancia,
            "n_acordo": len(acordo), "n_discordancia": len(discordancia),
            "ressalva": ("Acordo entre regra e IA é fato duplamente confirmado; discordância é fila "
                         "de leitura humana, não veredito. O campo `interpretacao` é OPINIÃO a "
                         "conferir e nunca vira achado sozinho.")}


def _gravar(con: sqlite3.Connection, laudo: dict) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS sei_leitura_dupla (
        numero_sei TEXT PRIMARY KEY, chars INTEGER, truncado INTEGER,
        n_acordo INTEGER, n_discordancia INTEGER, deterministico TEXT, ia TEXT,
        discordancia TEXT, lido_em TEXT)""")
    con.execute("INSERT OR REPLACE INTO sei_leitura_dupla VALUES (?,?,?,?,?,?,?,?,?)",
                (laudo["processo"], laudo["chars"], int(laudo["truncado"]), laudo["n_acordo"],
                 laudo["n_discordancia"], json.dumps(laudo["deterministico"], ensure_ascii=False),
                 json.dumps(laudo["ia"], ensure_ascii=False),
                 json.dumps(laudo["discordancia"], ensure_ascii=False),
                 datetime.now().isoformat(timespec="seconds")))
    con.commit()


def _pendentes(con: sqlite3.Connection, n: int) -> list[str]:
    """Processos do acervo ainda sem leitura dupla — os maiores primeiro (mais texto, mais fato)."""
    try:
        lidos = {r[0] for r in con.execute("SELECT numero_sei FROM sei_leitura_dupla")}
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
    a = ap.parse_args(argv)
    con = sqlite3.connect(str(_DB), timeout=120)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        alvos = [a.processo] if a.processo else _pendentes(con, a.amostra or 3)
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
            tot["discordancia"] += r["n_discordancia"]; tot[f"ia:{est}"] += 1
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
