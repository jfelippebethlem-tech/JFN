# -*- coding: utf-8 -*-
"""Checa Internet Gateway + rota default da VM Oracle."""
import sys, os, glob
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
import oci
CONFIG = {
    "user":"ocid1.user.oc1..aaaaaaaamnwgebr5junqyaxiabqeihgvaotle5kob7fh33odx5w4myqyrfka",
    "fingerprint":"8a:59:ec:5a:a0:b1:dc:a3:59:4b:63:9d:10:8f:68:ee",
    "tenancy":"ocid1.tenancy.oc1..aaaaaaaakr3tlyd2bjc2xpwuk5nrh5d2yzvpyna3i4k2dzw4ou6umol2lmrq",
    "region":"sa-saopaulo-1","key_file":"",
}
COMP=CONFIG["tenancy"]
SUBNET="ocid1.subnet.oc1.sa-saopaulo-1.aaaaaaaajzo4hyo6oaigouj6tzpd2d4v2dd5iedbb2ot256r4nafjh7mln5q"
def chave():
    for d in [r"C:\JFN\jfn",r"C:\JFN",os.path.expanduser("~")]:
        for pat in ["oci_key*.pem*","*.pem","*.pem.txt"]:
            for c in sorted(glob.glob(os.path.join(d,pat))):
                if "public" in c.lower() or "vm_ssh" in c.lower(): continue
                try: h=open(c,"r",errors="ignore").read(200)
                except Exception: continue
                if "OPENSSH" in h: continue
                if "PRIVATE KEY" in h: return c
CONFIG["key_file"]=chave()
vc=oci.core.VirtualNetworkClient(CONFIG)
sub=vc.get_subnet(SUBNET).data
vcn_id=sub.vcn_id
print("VCN:", vcn_id[-12:], "| route_table:", sub.route_table_id[-12:])
# Internet Gateway existe e habilitado?
igws=vc.list_internet_gateways(compartment_id=COMP, vcn_id=vcn_id).data
print("Internet Gateways:", len(igws))
igw_id=None
for g in igws:
    print("  IGW:", g.display_name, "| enabled:", g.is_enabled)
    if g.is_enabled: igw_id=g.id
# rota default existe?
rt=vc.get_route_table(sub.route_table_id).data
print("Regras de rota:", len(rt.rules))
tem_default=False
for r in rt.rules:
    print("   destino", r.destination, "->", r.network_entity_id[-20:])
    if r.destination in ("0.0.0.0/0",): tem_default=True
print("\n>>> ROTA DEFAULT (0.0.0.0/0) EXISTE?", "SIM" if tem_default else "NAO")
print("IGW_ID="+(igw_id or "NENHUM_HABILITADO"))
print("ROUTE_TABLE_ID="+sub.route_table_id)
