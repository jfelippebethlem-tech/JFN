# -*- coding: utf-8 -*-
"""
AUDITORIA PROFUNDA DE FORNECEDOR — orquestrador de 1 comando (para IA fraca rodar).

USO:
    python -m compliance_agent.auditoria.auditar_fornecedor <CNPJ> [ano1 ano2 ...]
EX:
    python -m compliance_agent.auditoria.auditar_fornecedor 19.088.605/0001-04 2025 2026

O QUE FAZ (sozinho, fonte PÚBLICA, sem login):
  - Consulta a Transparência Fiscal RJ (TFE) por CNPJ, em cada ano;
  - Agrega: quanto recebeu (empenhado) POR MÊS, POR ÓRGÃO;
  - Extrai do histórico: CONTRATOS (CTT/Contrato nº) e PROCESSOS (SEI-...);
  - Gera relatório .md em reports/ e dados brutos em data/sei_cache/.

PRÉ-REQUISITO: um Chrome aberto com  --remote-debugging-port=9222
  (o TFE tem anti-bot F5; o navegador real resolve o cookie. Sem login.)

Para a etapa MAIS PROFUNDA (lista OFICIAL de contratos + valor PAGO no SIAFE),
veja PASSO-A-PASSO.md (precisa de login SIAFE) e o módulo siafe_contratos.py.

Regras: só LEITURA, ritmo humano (pausas), nunca expõe segredos.
"""
import sys
import os
import re
import json
import time
import collections
import urllib.request
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CDP = "http://127.0.0.1:9222"
TFE_FORM = "https://tfe.fazenda.rj.gov.br/tfe/web/fornecedor"
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE = os.path.join(_ROOT, "data", "sei_cache")
REPORTS = os.path.join(_ROOT, "reports")

# ── CDP mínimo (sem dependências pesadas) ─────────────────────────────────────
import websocket  # websocket-client


def _http(path, method="GET"):
    req = urllib.request.Request(CDP + path, method=method)
    return urllib.request.urlopen(req, timeout=8).read()


def _cdp_alive():
    try:
        _http("/json/version"); return True
    except Exception:
        return False


def _tab_tfe():
    tabs = json.loads(_http("/json/list"))
    for t in tabs:
        if t.get("type") == "page" and "tfe.fazenda" in (t.get("url") or "") and t.get("webSocketDebuggerUrl"):
            return t
    return None


def _abrir(url):
    _http("/json/new?" + urllib.parse.quote(url, safe=""), "PUT")


class Aba:
    def __init__(self):
        t = _tab_tfe()
        if not t:
            _abrir(TFE_FORM); time.sleep(7); t = _tab_tfe()
        if not t:
            raise RuntimeError("Sem aba TFE. Abra o Chrome com --remote-debugging-port=9222.")
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

    def click_id(self, elem_id):
        r = self.ev("(function(){var b=document.getElementById(%r);if(!b)return null;var c=b.getBoundingClientRect();return JSON.stringify({x:c.left+c.width/2,y:c.top+c.height/2})})()" % elem_id)
        if not r:
            return False
        c = json.loads(r)
        for tp in ("mouseMoved", "mousePressed", "mouseReleased"):
            p = {"type": tp, "x": c["x"], "y": c["y"]}
            if tp != "mouseMoved":
                p.update({"button": "left", "clickCount": 1})
            self.call("Input.dispatchMouseEvent", p); time.sleep(0.2)
        return True

    def renew(self):
        try:
            self.ws.close()
        except Exception:
            pass
        time.sleep(1)
        t = _tab_tfe()
        self.ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=30, suppress_origin=True); self.i = 0


def _valor(s):
    m = re.search(r"([\d\.]+,\d{2})", s or "")
    return float(m.group(1).replace(".", "").replace(",", ".")) if m else 0.0


CONTR_RE = re.compile(r"(?:CONTRATO|CTT)\b[\s.]*[Nn]?[\sºo°.:]*\s*(\d{1,4}(?:/\d{2,4}){1,2})", re.I)
PROC_RE = re.compile(r"SEI[\-\s]?(\d{6}/\d{6}/\d{4})", re.I)


def consulta_tfe(cnpj, ano):
    """Roda a consulta TFE 'Despesas de Fornecedor por Empenho' p/ 1 ano. Retorna linhas (lista de listas)."""
    _abrir(TFE_FORM); time.sleep(7)
    a = Aba()
    a.ev("(function(){var r=[...document.querySelectorAll('input[name=tipoConsultaFornecedor]')].find(x=>x.value=='1');if(r){r.checked=true;r.click&&r.click();r.dispatchEvent(new Event('change',{bubbles:true}))}})()")
    time.sleep(0.4)
    a.ev("var c=document.getElementById('cnpj');if(c){c.value=%r;c.dispatchEvent(new Event('input',{bubbles:true}));c.dispatchEvent(new Event('change',{bubbles:true}))}" % cnpj)
    for sid, v in [("mesInicial", "01"), ("anoInicial", str(ano)), ("mesFinal", "12"), ("anoFinal", str(ano))]:
        a.ev("var s=document.getElementById(%r);if(s){s.value=%r;s.dispatchEvent(new Event('change',{bubbles:true}))}" % (sid, v))
    time.sleep(0.5)
    print("  [TFE] consultando %s em %s..." % (cnpj, ano))
    a.click_id("btnSalvar")
    a.ev("var b=document.getElementById('btnSalvar');b&&b.onclick&&b.onclick()")
    time.sleep(8); a.renew()
    rows = a.ev("""(function(){var t=[...document.querySelectorAll('table')].sort((a,b)=>b.querySelectorAll('tr').length-a.querySelectorAll('tr').length)[0];if(!t)return '[]';var o=[];for(var tr of t.querySelectorAll('tr')){var c=[...tr.querySelectorAll('td')].map(td=>(td.textContent||'').replace(/\\s+/g,' ').trim());if(c.length>=5)o.push(c);}return JSON.stringify(o)})()""")
    try:
        return json.loads(rows or "[]")
    except Exception:
        return []


def auditar(cnpj_in, anos):
    cnpj = cnpj_in.strip()
    digits = re.sub(r"\D", "", cnpj)
    os.makedirs(CACHE, exist_ok=True); os.makedirs(REPORTS, exist_ok=True)
    if not _cdp_alive():
        print("ERRO: Chrome-ponte (9222) nao esta no ar. Abra o Chrome com --remote-debugging-port=9222.")
        return
    por_ano = {}
    for ano in anos:
        data = consulta_tfe(cnpj, ano)
        json.dump(data, open(os.path.join(CACHE, "tfe_%s_%s.json" % (digits, ano)), "w", encoding="utf-8"), ensure_ascii=False)
        mes = collections.defaultdict(lambda: [0, 0.0]); org = collections.defaultdict(float)
        contr = collections.defaultdict(float); procs = set(); tot = 0.0; n = 0
        for c in data:
            if len(c) < 9 or not re.search(r"\d{2}/\d{2}/\d{4}", " ".join(c[:2])):
                continue
            v = _valor(c[8]); tot += v; n += 1
            md = re.search(r"(\d{2})/(\d{2})/(\d{4})", " ".join(c[:2]))
            if md:
                k = "%s/%s" % (md.group(2), md.group(3)); mes[k][0] += 1; mes[k][1] += v
            if c[4].strip() if len(c) > 4 else False:
                org[c[4]] += v
            h = c[7] if len(c) > 7 else ""
            mc = CONTR_RE.search(h);  mp = PROC_RE.search(h)
            if mc: contr[mc.group(1)] += v
            if mp: procs.add("SEI-" + mp.group(1))
        por_ano[ano] = {"total": tot, "n": n, "mes": dict(mes), "org": dict(org),
                        "contr": dict(contr), "procs": sorted(procs)}
        time.sleep(3)  # ritmo humano entre anos
    _relatorio(cnpj, digits, por_ano)


def _relatorio(cnpj, digits, por_ano):
    out = os.path.join(REPORTS, "auditoria_%s.md" % digits)
    L = ["# Auditoria de fornecedor — CNPJ %s" % cnpj,
         "Fonte: Transparência Fiscal RJ (TFE) — empenhado (público). Gerado automaticamente.", ""]
    for ano in sorted(por_ano):
        d = por_ano[ano]
        L.append("## %s — %d empenhos — R$ %s (empenhado)" % (ano, d["n"], _f(d["total"])))
        L.append("\n### Por mês")
        L.append("| Mês | Empenhos | R$ |\n|---|---:|---:|")
        for m in sorted(d["mes"]):
            L.append("| %s | %d | %s |" % (m, d["mes"][m][0], _f(d["mes"][m][1])))
        L.append("\n### Por órgão (top 12)")
        L.append("| Órgão | R$ |\n|---|---:|")
        for o, v in sorted(d["org"].items(), key=lambda x: -x[1])[:12]:
            if o.strip(): L.append("| %s | %s |" % (o[:48], _f(v)))
        L.append("\n### Contratos citados no histórico (%d)" % len(d["contr"]))
        for k, v in sorted(d["contr"].items(), key=lambda x: -x[1]):
            L.append("- Contrato %s — R$ %s" % (k, _f(v)))
        L.append("\n### Processos SEI (%d): %s\n" % (len(d["procs"]), ", ".join(d["procs"])))
    L.append("---\n> ⚠️ Valores EMPENHADOS (não necessariamente pagos). Lista OFICIAL de contratos e valor PAGO: ver PASSO-A-PASSO.md (etapa SIAFE).")
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print("\n=== RELATÓRIO GERADO: %s ===" % out)
    for ano in sorted(por_ano):
        d = por_ano[ano]
        print("  %s: R$ %s | %d contratos | %d processos SEI" % (ano, _f(d["total"]), len(d["contr"]), len(d["procs"])))


def _f(x): return "{:,.2f}".format(x)


def main():
    if len(sys.argv) < 2:
        print("Uso: python -m compliance_agent.auditoria.auditar_fornecedor <CNPJ> [anos...]")
        print("Ex.: python -m compliance_agent.auditoria.auditar_fornecedor 19.088.605/0001-04 2025 2026")
        return
    cnpj = sys.argv[1]
    anos = sys.argv[2:] or ["2025", "2026"]
    auditar(cnpj, anos)


if __name__ == "__main__":
    main()
