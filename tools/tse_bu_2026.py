"""Coleta e decodifica os Boletins de Urna (BU) de 2026 do RJ, seção por seção.

Fonte: resultados.tse.jus.br (arquivo-urna, pleito 3220 = 1º turno 04/10/2026).
O BU de 2026 não decodifica com a spec ASN.1 de 2022 (campos novos em Carga e no
topo da entidade); por isso o parse aqui é posicional sobre o TLV BER, validado
pela soma dos votos de cada cargo contra o comparecimento da seção.

Uso:  python tools/tse_bu_2026.py baixar     # baixa os .bu (retomável)
      python tools/tse_bu_2026.py parse      # grava o SQLite
"""
import json
import os
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3220"
DIR = os.path.expanduser("~/JFN/data/tse_cache/bu2026_rj")
DB = os.path.expanduser("~/JFN/data/tse_cache/eleicao2026_rj_secao.sqlite")
CARGOS = {1: "PRESIDENTE", 3: "GOVERNADOR", 5: "SENADOR", 6: "DEPUTADO FEDERAL", 7: "DEPUTADO ESTADUAL"}
TIPO_VOTO = {1: "nominal", 2: "branco", 3: "nulo", 4: "legenda", 5: "cargoSemCandidato"}


def _get(url, tentativas=4):
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception:
            if i == tentativas - 1:
                raise
            time.sleep(2 * (i + 1))


def secoes():
    cs = json.loads(_get(f"{BASE}/config/rj/rj-p003220-cs.json"))
    for mu in cs["abr"][0]["mu"]:
        for z in mu["zon"]:
            for s in z["sec"]:
                if "nsp" not in s:  # seção agregada: vota na urna da principal, não tem BU próprio
                    yield mu["cd"], z["cd"], s["ns"]


def baixar_uma(mzs):
    mun, zona, sec = mzs
    destino = f"{DIR}/{mun}-{zona}-{sec}.bu"
    if os.path.exists(destino):
        return "ja"
    pasta = f"{BASE}/dados/rj/{mun}/{zona}/{sec}"
    aux = json.loads(_get(f"{pasta}/p003220-rj-m{mun}-z{zona}-s{sec}-aux.json"))
    for h in aux["hashes"]:
        nm = next((a["nm"] for a in h["arq"] if a["tp"] == "bu"), None)
        if nm and h["st"] in ("Totalizado", "Recebido"):
            dado = _get(f"{pasta}/{h['hash']}/{nm}")
            with open(destino + ".tmp", "wb") as f:
                f.write(dado)
            os.replace(destino + ".tmp", destino)
            return "ok"
    with open(f"{DIR}/_sem_bu.txt", "a") as f:
        f.write(f"{mun};{zona};{sec};{aux.get('st')}\n")
    return "sem_bu"


def baixar():
    os.makedirs(DIR, exist_ok=True)
    lista = list(secoes())
    print(f"{len(lista)} seções", flush=True)
    cont, erros = {}, []
    with ThreadPoolExecutor(12) as ex:
        futs = {ex.submit(baixar_uma, s): s for s in lista}
        for i, fu in enumerate(futs, 1):
            try:
                r = fu.result()
            except Exception as e:
                r = "erro"
                erros.append((futs[fu], repr(e)[:120]))
            cont[r] = cont.get(r, 0) + 1
            if i % 1000 == 0:
                print(i, cont, flush=True)
    print("FIM", cont, flush=True)
    for e in erros[:20]:
        print("ERRO", e)


# ---------- decodificação BER posicional ----------
def _tlv(b, o):
    t = b[o]
    o += 1
    cls, cons, num = t >> 6, bool(t & 0x20), t & 0x1F
    if num == 0x1F:
        num = 0
        while True:
            x = b[o]
            o += 1
            num = (num << 7) | (x & 0x7F)
            if not x & 0x80:
                break
    n = b[o]
    o += 1
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(b[o:o + k], "big")
        o += k
    return (cls, cons, num), o, n


def _filhos(b, o, fim):
    while o < fim:
        tag, ini, n = _tlv(b, o)
        yield tag, ini, n
        o = ini + n


def _int(b, ini, n):
    return int.from_bytes(b[ini:ini + n], "big", signed=True)


U_SEQ, U_INT, U_ENUM, U_OCT = (0, True, 16), (0, False, 2), (0, False, 10), (0, False, 4)


def decodificar(raw):
    """Devolve (ident, eleicoes) — eleicoes: [{id, aptos, cargos:[{tipo, comparecimento, cargo, votos:[(tipo,partido,numero,qtd)]}]}]."""
    # envelope: SEQ{cabecalho, fase, identificacao, tipoEnvelope, conteudo OCTET}
    _, ini, n = _tlv(raw, 0)
    partes = list(_filhos(raw, ini, ini + n))
    conteudo = None
    ident = {}
    for tag, i, k in partes:
        if tag == U_OCT:
            conteudo = raw[i:i + k]
        elif tag[0] == 2 and tag[1]:  # identificacao [n] CHOICE -> SEQ{municipioZona, local, secao}
            ints = []
            for t2, i2, k2 in _filhos(raw, i, i + k):
                if t2 == U_SEQ:
                    ints += [_int(raw, i3, k3) for _, i3, k3 in _filhos(raw, i2, i2 + k2)]
                elif t2 == U_INT:
                    ints.append(_int(raw, i2, k2))
                elif t2[1]:  # pode vir aninhado mais um nível
                    for t3, i3, k3 in _filhos(raw, i2, i2 + k2):
                        if t3 == U_SEQ:
                            ints += [_int(raw, i4, k4) for _, i4, k4 in _filhos(raw, i3, i3 + k3)]
                        elif t3 == U_INT:
                            ints.append(_int(raw, i3, k3))
            ident = dict(zip(("municipio", "zona", "local", "secao"), ints))
    b = conteudo
    _, ini, n = _tlv(b, 0)
    topo = list(_filhos(b, ini, ini + n))
    # a lista de eleições é o último SEQ grande cujo 1º filho é SEQ começando por INTEGER idEleicao
    eleicoes = []
    for tag, i, k in topo:
        if tag != U_SEQ:
            continue
        filhos = list(_filhos(b, i, i + k))
        if not filhos or filhos[0][0] != U_SEQ:
            continue
        cand = []
        ok = True
        for t2, i2, k2 in filhos:
            netos = list(_filhos(b, i2, i2 + k2))
            if t2 != U_SEQ or not netos or netos[0][0] != U_INT:
                ok = False
                break
            cand.append(netos)
        if ok and cand and _int(b, cand[0][0][1], cand[0][0][2]) > 6000:
            for netos in cand:
                el = {"id": _int(b, netos[0][1], netos[0][2]), "aptos": _int(b, netos[1][1], netos[1][2]), "cargos": []}
                seq_res = next(x for x in netos[1:] if x[0] == U_SEQ)
                for _, ir, kr in _filhos(b, seq_res[1], seq_res[1] + seq_res[2]):  # ResultadoVotacao
                    rv = list(_filhos(b, ir, ir + kr))
                    tipo = _int(b, rv[0][1], rv[0][2])
                    comp = _int(b, rv[1][1], rv[1][2])
                    for _, ic, kc in _filhos(b, rv[2][1], rv[2][1] + rv[2][2]):  # TotalVotosCargo
                        tc = list(_filhos(b, ic, ic + kc))
                        cod = _int(b, tc[0][1], tc[0][2])
                        votos = []
                        seq_v = next(x for x in tc if x[0] == U_SEQ)
                        for _, iv, kv in _filhos(b, seq_v[1], seq_v[1] + seq_v[2]):
                            tv, qtd, partido, numero = None, None, None, None
                            for t4, i4, k4 in _filhos(b, iv, iv + kv):
                                if t4 == (2, False, 1):
                                    tv = _int(b, i4, k4)
                                elif t4 == (2, False, 2):
                                    qtd = _int(b, i4, k4)
                                elif t4 == (2, True, 3):
                                    xs = [_int(b, i5, k5) for _, i5, k5 in _filhos(b, i4, i4 + k4)]
                                    partido = xs[0] if xs else None
                                    numero = xs[1] if len(xs) > 1 else None
                            votos.append((TIPO_VOTO.get(tv, str(tv)), partido, numero, qtd))
                        el["cargos"].append({"tipo": tipo, "comparecimento": comp, "cargo": cod, "votos": votos})
                eleicoes.append(el)
    return ident, eleicoes


def parse():
    con = sqlite3.connect(DB)
    con.executescript("""
    DROP TABLE IF EXISTS secao; DROP TABLE IF EXISTS voto;
    CREATE TABLE secao(municipio INT, zona INT, secao INT, local INT, eleicao INT, cargo INT,
                       aptos INT, comparecimento INT, soma_votos INT, PRIMARY KEY(municipio,zona,secao,eleicao,cargo));
    CREATE TABLE voto(municipio INT, zona INT, secao INT, cargo INT, tipo TEXT, partido INT, numero INT, qtd INT);
    """)
    falhas = 0
    arquivos = sorted(f for f in os.listdir(DIR) if f.endswith(".bu"))
    for j, f in enumerate(arquivos, 1):
        try:
            ident, els = decodificar(open(f"{DIR}/{f}", "rb").read())
            mun, zona, sec = (int(x) for x in f[:-3].split("-"))
            assert (ident.get("municipio"), ident.get("zona"), ident.get("secao")) == (mun, zona, sec), (ident, f)
            for el in els:
                for c in el["cargos"]:
                    soma = sum(v[3] for v in c["votos"])
                    con.execute("INSERT INTO secao VALUES(?,?,?,?,?,?,?,?,?)",
                                (mun, zona, sec, ident.get("local"), el["id"], c["cargo"], el["aptos"], c["comparecimento"], soma))
                    con.executemany("INSERT INTO voto VALUES(?,?,?,?,?,?,?,?)",
                                    [(mun, zona, sec, c["cargo"], *v) for v in c["votos"]])
        except Exception as e:
            falhas += 1
            print("FALHA", f, repr(e)[:150])
        if j % 5000 == 0:
            con.commit()
            print(j, flush=True)
    con.execute("CREATE INDEX ix_voto ON voto(cargo, numero)")
    con.commit()
    print(f"parse: {len(arquivos)} arquivos, {falhas} falhas")


if __name__ == "__main__":
    {"baixar": baixar, "parse": parse}[sys.argv[1]]()
