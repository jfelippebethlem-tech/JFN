#!/usr/bin/env python3
"""Triagem pericial determinística dos contratos do FUNESBOM (CBMERJ) 2024+.
Não emite veredito de sobrepreço/direcionamento (exige corpus SEI). Prioriza p/ a fase documental.
Honestidade: indício != acusação; INDISPONÍVEL != 0."""
import sqlite3, re, collections, json
con = sqlite3.connect("file:/home/ubuntu/JFN/data/compliance.db?mode=ro", uri=True, timeout=30)
c = con.cursor()
UNI = "FUNESBOM - FUNDO ESPECIAL DO CORPO DE BOMBEIROS"

# Monopólio/utilidade (mesma lista vetada do reconcilia): inexigibilidade + alto valor são ESPERADOS,
# não suspeita. Sem isto o score premia o padrão de monopólio legítimo (Correios/Light/Ampla) —
# provado falso-alto na perícia Claude do Top-10. Down-weight: cap em 8 (deprioriza, não exclui).
LEGIT_MONOPOLIO = ["CORREIO", "TELEGRAFO", "ECT", "LIGHT", "AMPLA", "ENEL", "CEG", "CEDAE", "AGUAS",
                   "AGUA DE", "ENERGISA", "HELICOPTEROS DO BRASIL", "PETROBRAS", "IMPRENSA OFICIAL"]

def _legit_monopolio(forn: str) -> bool:
    return any(k in (forn or "").upper() for k in LEGIT_MONOPOLIO)

def br(v): return f"{(v or 0):,.2f}".replace(",","X").replace(".",",").replace("X",".")

# --- redes de sócios suspeitas (do achado anterior) ---
redes = {}
for nome, base, n, tot in c.execute("""SELECT nome_socio,cnpjs_basicos,n_fornecedores,total_recebido
        FROM rede_socios_fornecedores WHERE n_fornecedores>=2"""):
    for b in (base or "").split(","):
        redes.setdefault(b.strip(), []).append((nome, n, tot))

# --- contratos licitados 2024+ ---
contr = c.execute(f"""SELECT processo,sei_norm,ano_processo,data_contratacao,valor_contrato,
    criterio_julgamento,fornecedor,cnpj,objeto,valor_empenhado,valor_liquidado,valor_pago,vig_inicio,vig_fim
    FROM contratos_tcerj WHERE unidade=? AND CAST(ano_processo AS INT)>=2024 AND valor_contrato>0""",(UNI,)).fetchall()

# --- compras diretas (dispensa/inexigibilidade) 2024+ ---
diretas = c.execute(f"""SELECT processo,sei_norm,ano_processo,valor,objeto,enquadramento_legal,fornecedor
    FROM compras_diretas_tcerj WHERE unidade=? AND CAST(ano_processo AS INT)>=2024 AND valor>0""",(UNI,)).fetchall()

def cnpj_base(x): return re.sub(r"\D","",x or "")[:8]

# vencedor recorrente por nicho de objeto
def nicho(o):
    o=(o or "").upper()
    for k in ["VIATURA","AMBUL","APROXIMA","COMBUST","UNIFORME","FARDAMENT","ALIMENT","LIMPEZA",
              "VIGIL","MANUTEN","LOCACAO","MEDICAMENT","HOSPITAL","OXIGEN","PNEU","SEGURO",
              "HELICOPT","CAPACETE","MASCARA","EPI","COMUNICA","SOFTWARE","TECNOLOG","RADIO"]:
        if k in o: return k
    return "OUTROS"

forn_por_nicho = collections.defaultdict(lambda: collections.defaultdict(float))
for r in contr:
    forn_por_nicho[nicho(r[8])][cnpj_base(r[7])] += (r[4] or 0)

scored=[]
for (proc,sei,ano,dt,val,crit,forn,cnpj,obj,emp,liq,pago,vi,vf) in contr:
    flags=[]; score=0
    crit_u=(crit or "").upper()
    if "MENOR PRE" not in crit_u and crit:
        flags.append(f"criterio={crit[:25]}"); score+=15
    if (val or 0)>=10_000_000: flags.append("alto_valor>=10mi"); score+=20
    elif (val or 0)>=1_000_000: score+=8
    # reconciliação: pago muito acima do contrato (aditivo?) ou contrato sem pagamento
    if val and pago and pago>val*1.25: flags.append(f"pago>contrato({pago/val:.2f}x)"); score+=15
    # rede de sócios
    rb=redes.get(cnpj_base(cnpj))
    if rb: flags.append(f"rede_socio:{rb[0][0][:22]}({rb[0][1]}emp)"); score+=20
    # vencedor dominante no nicho
    nb=nicho(obj); tot_nicho=sum(forn_por_nicho[nb].values()); meu=forn_por_nicho[nb][cnpj_base(cnpj)]
    if tot_nicho>0 and meu/tot_nicho>0.6 and tot_nicho>5_000_000:
        flags.append(f"domina_nicho_{nb}({100*meu/tot_nicho:.0f}%)"); score+=12
    if _legit_monopolio(forn): flags.append("monopolio_legitimo"); score=min(score,8)
    scored.append((score,"LICITADO",proc,sei,ano,val,crit,forn,obj,flags))

for (proc,sei,ano,val,obj,enq,forn) in diretas:
    flags=["DISPENSA/INEXIG"]; score=10
    enq_u=(enq or "").upper()
    if "75" in enq_u and "VIII" in enq_u: flags.append("EMERGENCIA(75-VIII)"); score+=25
    if "74" in enq_u: flags.append("INEXIGIBILIDADE(74)"); score+=18
    if (val or 0)>=5_000_000: flags.append("alto_valor>=5mi"); score+=20
    elif (val or 0)>=1_000_000: score+=8
    rb=redes.get(cnpj_base(""))  # compras_diretas não traz cnpj
    if _legit_monopolio(forn): flags.append("monopolio_legitimo"); score=min(score,8)
    scored.append((score,"DIRETA",proc,sei,ano,val,enq,forn,obj,flags))

scored.sort(key=lambda x:-x[0])

tot_lic=sum(r[4] or 0 for r in contr); tot_dir=sum(r[2] or 0 for r in diretas)
print(f"Contratos licitados 2024+: {len(contr)}  soma R$ {br(tot_lic)}")
print(f"Compras diretas 2024+:     {len(diretas)} soma R$ {br(tot_dir)}")
print(f"Universo: {len(scored)} processos  R$ {br(tot_lic+tot_dir)}")
print(f"\nPriorizados (score>0): {sum(1 for x in scored if x[0]>0)}")
print("\n#### TOP 30 PRIORIZADOS P/ FASE DOCUMENTAL (Lex+SEI) ####")
for sc,tipo,proc,sei,ano,val,crit,forn,obj,flags in scored[:30]:
    p=(proc or "")[:32]
    print(f"[{sc:3}] {tipo:8} {p:33} R$ {br(val):>16}  {str(forn)[:26]:26} | {';'.join(flags)[:70]}")

# salva worklist json
out=[{"score":sc,"tipo":t,"processo":proc,"sei":sei,"ano":ano,"valor":val,
      "criterio":crit,"fornecedor":forn,"objeto":(obj or '')[:120],"flags":flags}
     for sc,t,proc,sei,ano,val,crit,forn,obj,flags in scored]
json.dump(out, open("/home/ubuntu/JFN/reports/_worklist_bombeiros.json","w"), ensure_ascii=False, indent=1)
print(f"\nworklist -> reports/_worklist_bombeiros.json ({len(out)} itens)")
