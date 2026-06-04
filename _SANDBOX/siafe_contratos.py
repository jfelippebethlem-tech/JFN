# -*- coding: utf-8 -*-
"""
SIAFE - lista TODOS os contratos de um contratado (nome/CNPJ) via Playwright NATIVO.
Resolve o filtro Oracle ADF (select_option dispara o PPR que renderiza o campo de valor).
Uso: python siafe_contratos.py "MGS CLEAN" 2025
Credenciais do .env (SIAFE_USUARIO/SIAFE_SENHA). So leitura.
"""
import sys, os, re, time, json
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
from playwright.sync_api import sync_playwright

EX={"2023":"4","2024":"3","2025":"2","2026":"1","2027":"0"}
def env(k):
    for ln in open(r"C:\Users\socah\AppData\Local\hermes\.env",encoding="utf-8",errors="replace"):
        if ln.startswith(k+"="): return ln.split("=",1)[1].strip()

def run(nome, ano):
    usuario=env("SIAFE_USUARIO"); senha=env("SIAFE_SENHA")
    with sync_playwright() as pw:
        br=pw.chromium.launch(headless=False)
        pg=br.new_page()
        def sel(i): return f'[id="{i}"]'
        def click_vis(i):
            # clica nas COORDENADAS do elemento VISIVEL (igual ao metodo CDP que funciona no ADF)
            c=pg.evaluate("""(id)=>{let els=[...document.querySelectorAll('[id=\"'+id+'\"]')];for(let e of els){let r=e.getBoundingClientRect();if(r.width>0&&r.height>0&&r.top>=0&&r.left>=0)return {x:r.left+r.width/2,y:r.top+r.height/2};}return null;}""", i)
            if not c: raise Exception("sem elemento visivel: "+i)
            pg.mouse.move(c["x"],c["y"]); pg.mouse.click(c["x"],c["y"])
        def click_text(txt):
            c=pg.evaluate("""(t)=>{let els=[...document.querySelectorAll('a,span,td,div')].filter(e=>(e.textContent||'').trim()===t);for(let e of els){let r=e.getBoundingClientRect();if(r.width>0&&r.height>0&&r.top>=0)return {x:r.left+r.width/2,y:r.top+r.height/2};}return null;}""", txt)
            if not c: return False
            pg.mouse.move(c["x"],c["y"]); pg.mouse.click(c["x"],c["y"]); return True
        print("[1] login...")
        pg.goto("https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp",wait_until="networkidle",timeout=40000)
        pg.fill(sel("loginBox:itxUsuario::content"),usuario)
        pg.fill(sel("loginBox:itxSenhaAtual::content"),senha)
        try: pg.select_option(sel("loginBox:cbxCliente::content"),"0")
        except Exception: pass
        pg.select_option(sel("loginBox:cbxExercicio::content"),EX.get(str(ano),"2"))
        pg.click(sel("loginBox:btnConfirmar"))
        pg.wait_for_load_state("networkidle",timeout=40000); time.sleep(3)
        print("    url:",pg.url[:60])
        # popup decreto
        try:
            ok=pg.get_by_text("OK",exact=True).first
            if ok.is_visible(timeout=2500): ok.click(); time.sleep(1)
        except Exception: pass
        # popup "sistema aberto em outra janela" -> Sim
        try:
            sim=pg.get_by_text("Sim",exact=True).first
            if sim.is_visible(timeout=1500): sim.click(); time.sleep(2)
        except Exception: pass
        print("[2] Execucao -> Contratos e Convenios -> Contrato")
        # topo "Execucao" (best-effort, por texto/coordenada)
        try: click_text("Execução"); time.sleep(2)
        except Exception: pass
        try:
            ok=pg.get_by_text("OK",exact=True).first
            if ok.is_visible(timeout=1500): ok.click(); time.sleep(1)
        except Exception: pass
        # sub-aba "Contratos e Convenios" (direto, por texto/coordenada)
        if not click_text("Contratos e Convênios"):
            click_vis("pt1:pt_np3:3:pt_cni4::disclosureAnchor")
        time.sleep(3)
        # item lateral "Contrato"
        if not click_text("Contrato"):
            click_vis("pt1:pt_np2:2:pt_cni3")
        pg.wait_for_load_state("networkidle",timeout=30000); time.sleep(3)
        pg.screenshot(path=r"C:\JFN\jfn\data\tmp\pw_contrato_grid.png")
        print("[3] abrir filtro + propriedade Nome do Contratado")
        click_vis("pt1:tblContrato:sdtFilter::disAcr"); time.sleep(2)
        pg.select_option(sel("pt1:tblContrato:table_rtfFilter:0:cbx_col_sel_rtfFilter::content"),"9")
        pg.wait_for_load_state("networkidle",timeout=20000); time.sleep(2)
        # operador "contem"
        try:
            pg.select_option(sel("pt1:tblContrato:table_rtfFilter:0:cbx_op_sel_rtfFilter::content"),label=re.compile("cont", re.I))
        except Exception:
            pg.select_option(sel("pt1:tblContrato:table_rtfFilter:0:cbx_op_sel_rtfFilter::content"),"7")
        pg.wait_for_load_state("networkidle",timeout=20000); time.sleep(2)
        # campo de valor: input de texto dentro da linha do filtro (apareceu apos PPR)
        vals=pg.locator('[id*="table_rtfFilter:0"] input[type="text"]')
        print("    inputs de valor no filtro:",vals.count())
        if vals.count()==0:
            pg.screenshot(path=r"C:\JFN\jfn\data\tmp\pw_sem_valor.png")
            print("    !! campo de valor nao apareceu"); br.close(); return
        vals.last.fill(nome)
        pg.keyboard.press("Enter")
        pg.wait_for_load_state("networkidle",timeout=25000); time.sleep(3)
        pg.screenshot(path=r"C:\JFN\jfn\data\tmp\pw_contrato_filtrado.png")
        print("[4] extrai contratos")
        # headers + linhas
        rows=pg.evaluate("""()=>{
          let tbls=[...document.querySelectorAll('table')],best=null,mx=0;
          for(let tb of tbls){let r=tb.querySelectorAll('tr');if(r.length>mx){mx=r.length;best=tb}}
          if(!best)return [];
          let out=[];
          for(let tr of best.querySelectorAll('tr')){
            let c=[...tr.querySelectorAll('td')].map(td=>(td.textContent||'').replace(/\\s+/g,' ').trim());
            if(c.length>=5)out.push(c);
          } return out;
        }""")
        os.makedirs(r"C:\JFN\jfn\data\sei_cache",exist_ok=True)
        json.dump(rows,open(r"C:\JFN\jfn\data\sei_cache\siafe_contratos_%s.json"%re.sub(r'\W','',nome),"w",encoding="utf-8"),ensure_ascii=False)
        print("    linhas extraidas:",len(rows))
        for c in rows[:30]:
            print("   ",c[:13])
        br.close()

if __name__=="__main__":
    nome=sys.argv[1] if len(sys.argv)>1 else "MGS CLEAN"
    ano=sys.argv[2] if len(sys.argv)>2 else "2025"
    run(nome,ano)
