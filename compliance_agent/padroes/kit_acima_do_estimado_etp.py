"""kit_acima_do_estimado_etp — preço unitário contratado/registrado acima da estimativa do próprio ETP/TR, por item.

Origem: EBN (SEI-030001/063630/2025) e Brasil Comércio (SEI-030001/087803/2025): kit de uniforme estimado no ETP em
R$ 278,41 (ID SIGA 184730) e registrado/contratado a R$ 306,50 e R$ 309,80.

Leitura (à prova do extrator ingênuo — memória extrator-ingenuo-fabrica-o-sinal):
  • o item é casado pelo ID do catálogo SIGA ("ID: 184730", "(ID - 184730)") — nunca por semelhança de descrição;
  • o preço só vale quando a TRINCA quantidade × unitário = total fecha (±0,5%) logo depois do ID: número solto
    (código de item, CNPJ, página) não fecha a conta e fica fora;
  • estimativa = ETP/TR/pesquisa; contratado = contrato/extrato/ata. Havendo mais de uma estimativa para o ID, vale a
    MAIOR (a mais favorável ao órgão: estimativa atualizada no TR afasta o achado).
Grau: unitário contratado > maior estimativa em ≥ 5% → forte; 1% a 5% → médio.
Lei 14.133 art. 59 III (proposta acima do orçamento estimado é desclassificada); Dec. RJ 48.843/2023.
"""
from __future__ import annotations

import re

from compliance_agent.padroes import _carona_comum as cc

ID = "kit_acima_do_estimado_etp"
VICIO = "homologado_acima_estimado"  # knowledge/catalogo_vicios.py
RX_ID = re.compile(r"\bID\s*[:\-–]?\s*(\d{5,7})\b")
RX_NUM = re.compile(r"(?<![\d.,/])(\d{1,3}(?:\.\d{3})+(?:,\d{1,10})?|\d+(?:,\d{1,10})?)(?![\d.,]*\d/|\.\d)")
_ESTIM = ("etp", "tr", "pesquisa")
_CONTR = ("contrato", "ata")
LIMIAR_MEDIO = 0.01
LIMIAR_FORTE = 0.05


def _f(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _trinca(janela: str) -> tuple[float, float, float, str] | None:
    """Primeira (qtd, unitário, total) com qtd × unit ≈ total (±0,5%) entre números consecutivos (até 1 de folga)."""
    nums = [(m.group(1), m.start(), m.end()) for m in RX_NUM.finditer(janela)]
    vals = []
    for s, a, b in nums:
        try:
            vals.append((_f(s), s, a, b))
        except ValueError:
            continue
    for i in range(len(vals)):
        q = vals[i][0]
        if q < 1 or q != int(q):
            continue
        for j in range(i + 1, min(i + 3, len(vals))):
            pu = vals[j][0]
            if pu <= 0 or "," not in vals[j][1]:
                continue
            for k in range(j + 1, min(j + 3, len(vals))):
                tot = vals[k][0]
                if tot > 0 and abs(q * pu - tot) <= max(0.005 * tot, 0.05):
                    return q, pu, tot, re.sub(r"\s+", " ", janela[vals[i][2]: vals[k][3]])
    return None


def precos_por_id(d: cc.Doc) -> dict[str, tuple[float, float, str]]:
    """{id_siga: (unitário, quantidade, trecho)} do documento — só onde a trinca fecha."""
    out: dict[str, tuple[float, float, str]] = {}
    ms = list(RX_ID.finditer(d.texto))
    for n, m in enumerate(ms):
        fim = ms[n + 1].start() if n + 1 < len(ms) else len(d.texto)
        jan = d.texto[m.end(): min(fim, m.end() + 700)]
        tr = _trinca(jan)
        if tr and m.group(1) not in out:
            out[m.group(1)] = (tr[1], tr[0], f'ID {m.group(1)} … "{tr[3][:160]}"')
    return out


def avaliar(ds: list[cc.Doc]) -> list[dict]:
    est: dict[str, list] = {}
    con: dict[str, list] = {}
    for d in ds:
        tp = cc.tipo_doc(d.titulo)
        if tp not in _ESTIM + _CONTR:
            continue
        for idd, (pu, q, tr) in precos_por_id(d).items():
            (est if tp in _ESTIM else con).setdefault(idd, []).append((pu, q, f"{d.ref} ({d.titulo[:50]}) — {tr}"))
    out = []
    for idd, cs in con.items():
        if idd not in est:
            continue
        e_max = max(est[idd], key=lambda x: x[0])
        c_max = max(cs, key=lambda x: x[0])
        exc = c_max[0] / e_max[0] - 1
        if exc >= LIMIAR_MEDIO:
            out.append({"id_siga": idd, "estimado": e_max[0], "contratado": c_max[0], "excesso_pct": round(100 * exc, 2),
                        "grau": "forte" if exc >= LIMIAR_FORTE else "medio",
                        "prova": f"estimado: {e_max[2]} | contratado: {c_max[2]}",
                        "estimativas_vistas": len(est[idd])})
    return out


def varrer(limite: int | None = None) -> dict:
    todos = cc.tags()[: limite or None]
    universo = sem_texto = sem_par = 0
    brutos = []
    cc.refs_em_paralelo(todos)
    pedidos = []
    for t in todos:
        tipos = {cc.tipo_doc(r.titulo) for r in cc.refs(t)}
        if not (tipos & set(_ESTIM) and tipos & set(_CONTR)):
            sem_par += 1
            continue
        pedidos.append((t, _ESTIM + _CONTR))
    for t, ds in cc.docs_em_paralelo(pedidos):
        if not ds:
            sem_texto += 1
            continue
        universo += 1
        r = avaliar(ds)
        if r:
            brutos.append((t, r, ds))
    obs = cc.ob_pagas({cc.canon(t) for t, _, _ in brutos})
    achados = []
    for t, itens, ds in brutos:
        itens.sort(key=lambda x: -x["excesso_pct"])
        ob = obs.get(cc.canon(t))
        achados.append({
            "processo": cc.canon(t), "grau": itens[0]["grau"], "sinal": "unitario_acima_do_estimado",
            "itens": itens, "prova": " || ".join(f"ID {i['id_siga']}: R$ {i['contratado']:,.2f} × estimado R$ "
                                                   f"{i['estimado']:,.2f} (+{i['excesso_pct']}%) — {i['prova']}"
                                                   for i in itens[:4]),
            "orgao": cc.orgao(ds), "credor": cc.credor_principal(ob),
            "valor_pago_ob": ob["total"] if ob else None, "obs": (ob or {}).get("obs", [])[:20],
            "porque": ("Inocente possível: estimativa atualizada no edital (não juntado) ou negociação justificada nos "
                       "autos do certame; preço de ata de outro processo. Não afasta: o próprio ETP/TR juntado estima "
                       "abaixo do que foi registrado/contratado (art. 59 III da Lei 14.133)."),
            "fonte": "SEI (ETP/TR × contrato/ata, casados pelo ID SIGA) + SIAFE (_ob_paga, piso)"})
    ordem = {"forte": 0, "medio": 1, "fraco": 2}
    achados.sort(key=lambda a: (ordem[a["grau"]], -(a["valor_pago_ob"] or 0)))
    cc.ligar(achados, VICIO, lambda a: a.get("grau") == "forte")
    return cc.resultado(ID, universo, {"processos_no_acervo": len(todos),
                                       "sem_texto": sem_texto, "sem_par_estimativa_e_contrato": sem_par,
                                       "nota": "só itens com ID SIGA e trinca qtd×unit=total nas DUAS pontas; ata sem "
                                               "coluna total não entra (o contrato entra)."}, achados)
