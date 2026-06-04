# -*- coding: utf-8 -*-
"""Pega o IP publico da VM Oracle pelo OCID. So leitura."""
import sys, os, glob
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import oci

CONFIG = {
    "user":        "ocid1.user.oc1..aaaaaaaamnwgebr5junqyaxiabqeihgvaotle5kob7fh33odx5w4myqyrfka",
    "fingerprint": "8a:59:ec:5a:a0:b1:dc:a3:59:4b:63:9d:10:8f:68:ee",
    "tenancy":     "ocid1.tenancy.oc1..aaaaaaaakr3tlyd2bjc2xpwuk5nrh5d2yzvpyna3i4k2dzw4ou6umol2lmrq",
    "region":      "sa-saopaulo-1",
    "key_file":    "",
}
COMPARTMENT = CONFIG["tenancy"]
INSTANCE = sys.argv[1] if len(sys.argv) > 1 else \
    "ocid1.instance.oc1.sa-saopaulo-1.antxeljrffbealycxhtwysvzhjip26x5bzujvlhwb25lwdnqwoujw7palrxa"


def achar_chave():
    dirs = [r"C:\JFN\jfn", r"C:\JFN", os.path.expanduser("~")]
    for d in dirs:
        for pat in ["oci_key*.pem*", "*api*key*.pem*", "*.pem", "*.pem.txt"]:
            for c in sorted(glob.glob(os.path.join(d, pat))):
                nome = c.lower()
                if "public" in nome or "vm_ssh" in nome:
                    continue
                try:
                    head = open(c, "r", errors="ignore").read(200)
                except Exception:
                    continue
                if "OPENSSH" in head:
                    continue
                if "PRIVATE KEY" in head:
                    return c
    return None


CONFIG["key_file"] = achar_chave()
if not CONFIG["key_file"]:
    print("ERRO: nao achei a chave da API OCI (.pem com PRIVATE KEY).")
    sys.exit(1)
print("Chave API:", CONFIG["key_file"])

cc = oci.core.ComputeClient(CONFIG)
vc = oci.core.VirtualNetworkClient(CONFIG)

# estado da instancia
inst = cc.get_instance(INSTANCE).data
print("Estado da VM:", inst.lifecycle_state, "| nome:", inst.display_name)

# acha o IP publico via VNIC
vnics = cc.list_vnic_attachments(compartment_id=COMPARTMENT, instance_id=INSTANCE).data
ip_pub = ip_priv = None
for va in vnics:
    if va.vnic_id:
        v = vc.get_vnic(va.vnic_id).data
        ip_pub = v.public_ip or ip_pub
        ip_priv = v.private_ip or ip_priv
print("IP PUBLICO:", ip_pub or "(ainda nao atribuido)")
print("IP PRIVADO:", ip_priv or "-")
