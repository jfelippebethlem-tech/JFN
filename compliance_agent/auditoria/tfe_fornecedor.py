# -*- coding: utf-8 -*-
"""
TFE FORNECEDOR — quanto um CNPJ recebeu do Estado do RJ, por mes (dado PUBLICO).

USO (uma linha):
    python tfe_fornecedor.py <CNPJ> <ANO>
ex: python tfe_fornecedor.py 19.088.605/0001-04 2025

Fonte: Transparencia Fiscal RJ (tfe.fazenda.rj.gov.br) — "Despesas de Fornecedor por Empenho".
NAO precisa login. Dirige o Chrome-ponte (porta 9222) porque o site tem anti-bot F5
(o navegador real resolve o cookie sozinho). So LEITURA. Ritmo humano.

Pre-requisito: um Chrome aberto com --remote-debugging-port=9222
(o mesmo que ja usamos para SEI/SIAFE).

Saida: tabela por mes + por orgao + total; salva bruto em data/sei_cache/.
ATENCAO: valor = EMPENHADO (comprometido), nao necessariamente pago.
"""
import logging
import sys
import os
import json
import time
import re
import collections
import urllib.request
import urllib.parse
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import websocket  # websocket-client

CDP = "http://127.0.0.1:9222"
FORM = "https://tfe.fazenda.rj.gov.br/tfe/web/fornecedor"


logger = logging.getLogger(__name__)


def _tab(substr="tfe.fazenda"):
    tabs = json.loads(urllib.request.urlopen(CDP + "/json/list", timeout=8).read())
    for x in tabs:
        if x.get("type") == "page" and substr in (x.get("url") or "") and x.get("webSocketDebuggerUrl"):
            return x
    return None


def _abrir(url):
    req = urllib.request.Request(CDP + "/json/new?" + urllib.parse.quote(url, safe=""), method="PUT")
    urllib.request.urlopen(req, timeout=8).read()


class Page:
    def __init__(self):
        t = _tab()
        if not t:
            _abrir(FORM); time.sleep(7); t = _tab()
        if not t:
            raise RuntimeError("Chrome-ponte (9222) sem aba TFE. Abra o Chrome com --remote-debugging-port=9222.")
        self.ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
        self.i = 0

    def call(self, method, params=None):
        self.i += 1; mid = self.i; self.ws.settimeout(30)
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == mid:
                return m

    def ev(self, e):
        return self.call("Runtime.evaluate", {"expression": e, "returnByValue": True}).get("result", {}).get("result", {}).get("value")

    def click_real(self, elem_id):
        rect = self.ev("(function(){var b=document.getElementById(%r);if(!b)return null;var r=b.getBoundingClientRect();return JSON.stringify({x:r.left+r.width/2,y:r.top+r.height/2})})()" % elem_id)
        if not rect:
            return False
        r = json.loads(rect)
        for tp in ("mouseMoved", "mousePressed", "mouseReleased"):
            p = {"type": tp, "x": r["x"], "y": r["y"]}
            if tp != "mouseMoved":
                p.update({"button": "left", "clickCount": 1})
            self.call("Input.dispatchMouseEvent", p); time.sleep(0.2)
        return True

    def renew(self):
        try: self.ws.close()
        except Exception as exc: logger.debug("ws.close no renew falhou: %s", exc)
        time.sleep(1)
        t = _tab(); self.ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=30, suppress_origin=True); self.i = 0


def _val(s):
    m = re.search(r"([\d\.]+,\d{2})", s or "")
    return float(m.group(1).replace(".", "").replace(",", ".")) if m else None


def consultar(cnpj, ano):
    _abrir(FORM); time.sleep(7)
    p = Page()
    # Fornecedor Especifico
    p.ev("(function(){var r=[...document.querySelectorAll('input[name=tipoConsultaFornecedor]')].find(x=>x.value=='1');if(r){r.checked=true;r.click&&r.click();r.dispatchEvent(new Event('change',{bubbles:true}))}})()")
    time.sleep(0.4)
    p.ev("var c=document.getElementById('cnpj');if(c){c.value=%r;c.dispatchEvent(new Event('input',{bubbles:true}));c.dispatchEvent(new Event('change',{bubbles:true}))}" % cnpj)
    for sid, v in [("mesInicial", "01"), ("anoInicial", str(ano)), ("mesFinal", "12"), ("anoFinal", str(ano))]:
        p.ev("var s=document.getElementById(%r);if(s){s.value=%r;s.dispatchEvent(new Event('change',{bubbles:true}))}" % (sid, v))
    time.sleep(0.5)
    print("[TFE] consultando CNPJ %s em %s ..." % (cnpj, ano))
    p.click_real("btnSalvar")
    p.ev("var b=document.getElementById('btnSalvar');b&&b.onclick&&b.onclick()")
    time.sleep(8)
    p.renew()
    rows = p.ev("""(function(){var tbls=[...document.querySelectorAll('table')];var best=null,mx=0;for(var tb of tbls){var rs=tb.querySelectorAll('tr');if(rs.length>mx){mx=rs.length;best=tb}}if(!best)return '[]';var out=[];for(var tr of best.querySelectorAll('tr')){var cells=[...tr.querySelectorAll('td')].map(td=>(td.textContent||'').replace(/\\s+/g,' ').trim());if(cells.length>=5)out.push(cells);}return JSON.stringify(out)})()""")
    data = json.loads(rows or "[]")
    # salva bruto
    cache = os.environ.get("JFN_DATA_DIR") and os.path.join(os.environ["JFN_DATA_DIR"], "sei_cache") \
        or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "sei_cache")
    os.makedirs(cache, exist_ok=True)
    safe = re.sub(r"\D", "", cnpj)
    json.dump(data, open(os.path.join(cache, "tfe_%s_%s.json" % (safe, ano)), "w", encoding="utf-8"), ensure_ascii=False)
    # agrega (valor = coluna Total, idx 8, quando ha 9 colunas; senao ultimo monetario)
    por_mes = collections.defaultdict(lambda: [0, 0.0]); por_org = collections.defaultdict(float)
    contratos = collections.defaultdict(float); processos = collections.defaultdict(float)
    total = 0.0; n = 0
    for c in data:
        md = re.search(r"(\d{2})/(\d{2})/(\d{4})", " ".join(c[:2]) if len(c) >= 2 else "")
        if not md:
            continue
        if len(c) >= 9:
            val = _val(c[8])
        else:
            val = next((v for v in (_val(x) for x in reversed(c)) if v is not None), 0.0)
        if not val:
            continue
        por_mes["%s/%s" % (md.group(2), md.group(3))][0] += 1
        por_mes["%s/%s" % (md.group(2), md.group(3))][1] += val
        if len(c) > 4 and c[4].strip(): por_org[c[4]] += val
        hist = c[7] if len(c) > 7 else " ".join(c)
        mc = re.search(r"(?:CONTRATO|CTT)\b[\s.]*[Nn]?[\sºo°.:]*\s*(\d{1,4}(?:/\d{2,4}){1,2})", hist, re.I)
        if mc: contratos[mc.group(1)] += val
        mp = re.search(r"SEI[\-\s]?(\d{6}/\d{6}/\d{4})", hist, re.I)
        if mp: processos["SEI-" + mp.group(1)] += val
        total += val; n += 1
    return por_mes, por_org, contratos, processos, total, n


def main():
    if len(sys.argv) < 3:
        print("Uso: python tfe_fornecedor.py <CNPJ> <ANO>"); return
    cnpj, ano = sys.argv[1], sys.argv[2]
    por_mes, por_org, contratos, processos, total, n = consultar(cnpj, ano)
    print("\n===== EMPENHADO POR MES (%s, %s) =====" % (cnpj, ano))
    for mes in sorted(por_mes):
        print("  %s: %2d empenhos | R$ %15s" % (mes, por_mes[mes][0], "{:,.2f}".format(por_mes[mes][1])))
    print("  TOTAL: %d empenhos | R$ %s" % (n, "{:,.2f}".format(total)))
    print("\n===== POR ORGAO (top 10) =====")
    for o, v in sorted(por_org.items(), key=lambda x: -x[1])[:10]:
        print("  R$ %15s  %s" % ("{:,.2f}".format(v), o[:55]))
    print("\n===== CONTRATOS (nº no historico) =====")
    for k, v in sorted(contratos.items(), key=lambda x: -x[1]):
        print("  Contrato %-14s R$ %15s" % (k, "{:,.2f}".format(v)))
    print("\n===== PROCESSOS SEI (%d) =====" % len(processos))
    print("  " + ", ".join(sorted(processos.keys())))
    print("\n(ATENCAO: valores EMPENHADOS, nao necessariamente pagos. Empenhos sem nº de")
    print(" contrato/processo no historico precisam ser abertos no SIAFE - 2a etapa.)")


if __name__ == "__main__":
    main()
