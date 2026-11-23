"""Bancada OCR 23/11/2026 — Surya × Unlimited-OCR × Tesseract × RapidOCR, mesmas páginas, gabarito = texto NATIVO.

Entradas (de it-campo:~/jfn-gpu/bench_digitos, PNG 200 dpi gerados em 18/11): gabarito.json, textos_<motor>.json,
paginas.json (as 40 páginas da bancada), tempos_unlimited.json. Regras de número = as de bench_digitos.py (valor,
cnpj, data, numero ≥ 6 dígitos), com CNPJ exigindo DV válido no gabarito.
Métricas por motor e por combinação (interseção = 'os motores concordam'):
  acerto_%      números do gabarito lidos exatos
  inventado_%   números emitidos que NÃO estão na página (por 100 emitidos) — a métrica que decide a trava
  omitido_%     100 − acerto
  trocado       inventado que difere de um verdadeiro ausente em 1–2 dígitos (troca de dígito)
  CER/WER       distância de edição normalizada (texto inteiro, espaços colapsados, marcação removida)
  vazio         saída com < 20 caracteres
    python medir.py <dir> [motor1,motor2,...]     # 23/11: lista de motores (padrão: os 4 da 1ª bancada)
"""
import json
import re
import statistics
import sys
from pathlib import Path

from rapidfuzz.distance import Levenshtein

D = Path(sys.argv[1])
RX = {"valor": re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})*,\d{2}(?![\d,])"),
      "cnpj": re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)"),
      "data": re.compile(r"(?<!\d)\d{2}/\d{2}/\d{4}(?!\d)"),
      "numero": re.compile(r"(?<![\d.,/])\d{6,}(?![\d,/])")}


def _dig(s):
    return re.sub(r"\D", "", s)


def sem_layout(t):
    """Tira a marcação de layout do Unlimited-OCR (<|det|>tipo [caixa]<|/det|>) e tags HTML de tabela."""
    t = re.sub(r"<\|det\|>.*?<\|/det\|>", "\n", t or "", flags=re.S)
    t = re.sub(r"</t[dh]>", " | ", t)
    return re.sub(r"<(br|/p|/tr|/li|/h\d|/div)[^>]*>", "\n", t).replace("<", " <")


def numeros(t):
    t = re.sub(r"<[^>]+>", " ", sem_layout(t))
    out = {cl: {_dig(m.group()) for m in rx.finditer(t)} for cl, rx in RX.items()}
    out["numero"] -= out["cnpj"] | {d for d in out["valor"]}
    return out


def eh_troca(e, falt):
    return any(len(e) == len(f) and 1 <= sum(a != b for a, b in zip(e, f)) <= 2 for f in falt)


def limpo(t):
    t = re.sub(r"<[^>]+>", " ", sem_layout(t))
    t = re.sub(r"[|#*`_>]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


gab = json.loads((D / "gabarito.json").read_text())
COR = {k: v for k, v in json.loads((D / "gabarito_correcoes.json").read_text()).items() if not k.startswith("_")} \
    if (D / "gabarito_correcoes.json").exists() else {}


def verdade(k):
    v = numeros(gab[k])
    for cl, xs in COR.get(k, {}).items():
        v[cl] |= set(xs)
    return v
pags = json.loads((D / "paginas.json").read_text())
mot = {m: json.loads((D / f"textos_{m}.json").read_text())
       for m in (sys.argv[2].split(",") if len(sys.argv) > 2 else ("surya", "unlimited", "tesseract", "rapidocr"))
       if (D / f"textos_{m}.json").exists()}
tipos = json.loads((D / "tipos.json").read_text()) if (D / "tipos.json").exists() else {}
ks = [k for k in pags if all(k in t for t in mot.values())]
nomes = list(mot)
combos = nomes + [f"{a}∩{b}" for i, a in enumerate(nomes) for b in nomes[i + 1:]]
combos += [f"{a}∩{b}∩{c}" for i, a in enumerate(nomes) for j, b in enumerate(nomes[i + 1:], i + 1)
           for c in nomes[j + 1:]]


def medir(chaves, combo):
    s = {cl: [0, 0, 0, 0] for cl in RX}
    for k in chaves:
        v = verdade(k)
        partes = [numeros(mot[m][k]) for m in combo.split("∩")]
        for cl in RX:
            e = set.intersection(*[p[cl] for p in partes])
            falt, errados = v[cl] - e, e - v[cl]
            s[cl][0] += len(v[cl]); s[cl][1] += len(v[cl] & e); s[cl][2] += len(e)
            s[cl][3] += sum(eh_troca(x, falt) for x in errados)
    tot = [sum(x[i] for x in s.values()) for i in range(4)]
    r = {"paginas": len(chaves), "verdadeiros": tot[0], "emitidos": tot[2],
         "acerto_%": round(100 * tot[1] / max(tot[0], 1), 1),
         "inventado_%": round(100 * (tot[2] - tot[1]) / max(tot[2], 1), 2), "inventados": tot[2] - tot[1],
         "omitido_%": round(100 - 100 * tot[1] / max(tot[0], 1), 1), "trocados": tot[3],
         **{f"{cl}_acerto_%": round(100 * x[1] / max(x[0], 1), 1) for cl, x in s.items()},
         **{f"{cl}_inventados": x[2] - x[1] for cl, x in s.items()},
         **{f"n_{cl}": x[0] for cl, x in s.items()}}
    if "∩" not in combo:
        cer = [Levenshtein.normalized_distance(limpo(mot[combo][k]), limpo(gab[k])) for k in chaves]
        wer = [Levenshtein.normalized_distance(limpo(mot[combo][k]).split(), limpo(gab[k]).split()) for k in chaves]
        r.update({"CER_%": round(100 * statistics.mean(cer), 1), "WER_%": round(100 * statistics.mean(wer), 1),
                  "vazios": sum(len(limpo(mot[combo][k])) < 20 for k in chaves)})
    return r


out = {}
for rot, chaves in [("todas", ks), ("real", [k for k in ks if k.startswith("real")]),
                    ("suja", [k for k in ks if k.startswith("suja")])]:
    for c in combos:
        out[f"{rot}/{c}"] = medir(chaves, c)
por_tipo = {}
for t in sorted({tipos.get(k, "?") for k in ks}):
    ch = [k for k in ks if tipos.get(k, "?") == t]
    por_tipo[t] = {m: medir(ch, m) for m in nomes}
(D / "resultado_bancada.json").write_text(json.dumps({"metricas": out, "por_tipo": por_tipo, "paginas": ks},
                                                     ensure_ascii=False, indent=1))
for k, v in out.items():
    if k.startswith("todas/"):
        print(f"{k:<40} acerto {v['acerto_%']:>5}%  inventado {v['inventado_%']:>5}% ({v['inventados']})  "
              f"trocados {v['trocados']}" + (f"  CER {v['CER_%']}%  WER {v['WER_%']}%  vazios {v['vazios']}"
                                             if "CER_%" in v else ""))

# lista dos inventados por motor/combinação (para a conferência VISUAL do gabarito)
lista = {}
for c in combos:
    itens = []
    for k in ks:
        v = verdade(k)
        partes = [numeros(mot[m][k]) for m in c.split("∩")]
        for cl in RX:
            for x in sorted(set.intersection(*[p[cl] for p in partes]) - v[cl]):
                itens.append([k, cl, x])
    lista[c] = itens
(D / "inventados.json").write_text(json.dumps(lista, ensure_ascii=False, indent=1))
