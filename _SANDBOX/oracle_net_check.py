# -*- coding: utf-8 -*-
"""Diagnostica a rede da VM Oracle: a Security List libera a porta 22?"""
import sys, os, glob
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
import oci

CONFIG = {
    "user":        "ocid1.user.oc1..aaaaaaaamnwgebr5junqyaxiabqeihgvaotle5kob7fh33odx5w4myqyrfka",
    "fingerprint": "8a:59:ec:5a:a0:b1:dc:a3:59:4b:63:9d:10:8f:68:ee",
    "tenancy":     "ocid1.tenancy.oc1..aaaaaaaakr3tlyd2bjc2xpwuk5nrh5d2yzvpyna3i4k2dzw4ou6umol2lmrq",
    "region":      "sa-saopaulo-1",
    "key_file":    "",
}
COMPARTMENT = CONFIG["tenancy"]
INSTANCE = "ocid1.instance.oc1.sa-saopaulo-1.antxeljrffbealycxhtwysvzhjip26x5bzujvlhwb25lwdnqwoujw7palrxa"

def achar_chave():
    for d in [r"C:\JFN\jfn", r"C:\JFN", os.path.expanduser("~")]:
        for pat in ["oci_key*.pem*","*.pem","*.pem.txt"]:
            for c in sorted(glob.glob(os.path.join(d,pat))):
                if "public" in c.lower() or "vm_ssh" in c.lower(): continue
                try: head=open(c,"r",errors="ignore").read(200)
                except Exception: continue
                if "OPENSSH" in head: continue
                if "PRIVATE KEY" in head: return c
    return None
CONFIG["key_file"]=achar_chave()

cc=oci.core.ComputeClient(CONFIG); vc=oci.core.VirtualNetworkClient(CONFIG)
vnics=cc.list_vnic_attachments(compartment_id=COMPARTMENT, instance_id=INSTANCE).data
subnet_id=None
for va in vnics:
    if va.vnic_id:
        v=vc.get_vnic(va.vnic_id).data
        subnet_id=v.subnet_id
        print("VNIC public_ip:", v.public_ip, "| subnet:", subnet_id[-12:])
sub=vc.get_subnet(subnet_id).data
print("Subnet:", sub.display_name, "| VCN:", sub.vcn_id[-12:])
print("Security Lists:", len(sub.security_list_ids))
porta22_ok=False
for sl_id in sub.security_list_ids:
    sl=vc.get_security_list(sl_id).data
    print(" SL:", sl.display_name)
    for r in sl.ingress_security_rules:
        desc=""
        if r.tcp_options and r.tcp_options.destination_port_range:
            pr=r.tcp_options.destination_port_range
            desc="TCP %s-%s"%(pr.min,pr.max)
            if pr.min<=22<=pr.max: porta22_ok=True
        else:
            desc="proto=%s (todas portas)"%r.protocol
            if r.protocol in ("all","6"): pass
        print("   ingress de", r.source, "->", desc)
print("\n>>> PORTA 22 LIBERADA NA SECURITY LIST?", "SIM" if porta22_ok else "NAO")
print("SUBNET_ID="+subnet_id)
print("SL_IDS="+",".join(sub.security_list_ids))
