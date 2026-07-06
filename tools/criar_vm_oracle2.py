#!/usr/bin/env python3
"""Cria uma VM Oracle A1.Flex (2 OCPU / 12 GB, Ubuntu ARM) em OUTRA conta Oracle, tentando
repetidamente até a capacidade liberar ("Out of host capacity"). Avisa no Telegram ao conseguir.

Config isolada (não mexe na conta principal): ~/.oci2/config  +  ~/.oci2/oci_api_key.pem
Cria VCN/subnet pública automaticamente se não houver. SSH keypair gerado em ~/.oci2/.

Uso: PYTHONPATH=. .venv/bin/python tools/criar_vm_oracle2.py
Pausar: criar ~/.oci2/.pause   ·   Parar: matar o processo.
"""
import os, sys, time, pathlib, datetime
import oci

OCI_DIR = pathlib.Path.home() / ".oci2"
CONFIG_FILE = str(OCI_DIR / "config")
SSH_PRIV = OCI_DIR / "vm_ssh_key"
SSH_PUB = OCI_DIR / "vm_ssh_key.pub"
PAUSE = OCI_DIR / ".pause"
LOG = pathlib.Path("/home/ubuntu/JFN/data/criar_vm_oracle2.log")

SHAPE = "VM.Standard.A1.Flex"
OCPUS = 2
MEM_GB = 12
BOOT_GB = 200           # Always Free: 200 GB de block storage no total (boot volume no teto do free)
DISPLAY = "JFN-Agent-2"
INTERVALO = 75          # s entre tentativas (evita throttle do launch)
TELEGRAM_A_CADA = 40    # avisa progresso no telegram a cada N tentativas

def log(m):
    linha = f"[{datetime.datetime.now():%F %T}] {m}"
    print(linha, flush=True)
    with open(LOG, "a") as f:
        f.write(linha + "\n")

def telegram(msg):
    try:
        import httpx
        sys.path.insert(0, "/home/ubuntu/JFN")
        from compliance_agent.envfile import carregar_env
        carregar_env()
        tok = os.environ.get("TELEGRAM_BOT_TOKEN"); chat = os.environ.get("TELEGRAM_CHAT_ID")
        if tok and chat:
            httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                       data={"chat_id": chat, "text": msg, "parse_mode": "Markdown"}, timeout=20)
    except Exception as e:
        log(f"(telegram falhou: {e})")

def gerar_ssh(cfg_signer):
    if SSH_PUB.exists():
        return SSH_PUB.read_text().strip()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    SSH_PRIV.write_bytes(k.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    SSH_PRIV.chmod(0o600)
    pub = k.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    SSH_PUB.write_text(pub + "\n")
    return pub

def achar_imagem(cc, comp):
    imgs = cc.list_images(comp, operating_system="Canonical Ubuntu",
                          shape=SHAPE, sort_by="TIMECREATED", sort_order="DESC").data
    # preferir 22.04 (LTS estável p/ ARM); senão a mais recente compatível
    for v in ("22.04", "24.04", "20.04"):
        for im in imgs:
            if v in (im.display_name or "") and "aarch64" in (im.display_name or "").lower() or v in (im.display_name or ""):
                return im.id
    return imgs[0].id if imgs else None

def garantir_subnet(vnc, comp):
    """Acha subnet pública; se não houver VCN/subnet, cria VCN+IG+route+subnet mínimos."""
    for vcn in vnc.list_vcns(comp).data:
        subs = vnc.list_subnets(comp, vcn_id=vcn.id).data
        for s in subs:
            if not s.prohibit_public_ip_on_vnic:
                return s.id
    log("nenhuma subnet pública — criando VCN/subnet…")
    vcn = vnc.create_vcn(oci.core.models.CreateVcnDetails(
        compartment_id=comp, cidr_block="10.0.0.0/16", display_name="jfn2-vcn")).data
    ig = vnc.create_internet_gateway(oci.core.models.CreateInternetGatewayDetails(
        compartment_id=comp, vcn_id=vcn.id, is_enabled=True, display_name="jfn2-ig")).data
    rt = vnc.create_route_table(oci.core.models.CreateRouteTableDetails(
        compartment_id=comp, vcn_id=vcn.id, display_name="jfn2-rt",
        route_rules=[oci.core.models.RouteRule(destination="0.0.0.0/0", network_entity_id=ig.id)])).data
    sub = vnc.create_subnet(oci.core.models.CreateSubnetDetails(
        compartment_id=comp, vcn_id=vcn.id, cidr_block="10.0.0.0/24", display_name="jfn2-subnet",
        route_table_id=rt.id, prohibit_public_ip_on_vnic=False)).data
    # libera SSH na security list default
    sl = vnc.get_security_list(vcn.default_security_list_id).data
    sl.ingress_security_rules.append(oci.core.models.IngressSecurityRule(
        protocol="6", source="0.0.0.0/0",
        tcp_options=oci.core.models.TcpOptions(destination_port_range=oci.core.models.PortRange(min=22, max=22))))
    vnc.update_security_list(vcn.default_security_list_id,
        oci.core.models.UpdateSecurityListDetails(ingress_security_rules=sl.ingress_security_rules))
    log(f"VCN/subnet criadas ({sub.id[:25]}…)")
    return sub.id

def main():
    if not os.path.exists(CONFIG_FILE):
        log(f"FALTA CONFIG: {CONFIG_FILE} (e a chave .pem). Veja instruções."); return
    cfg = oci.config.from_file(CONFIG_FILE, "DEFAULT")
    oci.config.validate_config(cfg)
    comp = cfg.get("compartment") or cfg["tenancy"]
    cc = oci.core.ComputeClient(cfg)
    vnc = oci.core.VirtualNetworkClient(cfg)
    idc = oci.identity.IdentityClient(cfg)
    ads = idc.list_availability_domains(cfg["tenancy"]).data
    log(f"conta OK. region={cfg['region']} ADs={[a.name for a in ads]}")
    ssh_pub = gerar_ssh(cfg)
    img = achar_imagem(cc, comp); log(f"imagem Ubuntu ARM: {img[:40]}…")
    sub = garantir_subnet(vnc, comp); log(f"subnet: {sub[:30]}…")
    telegram(f"🟠 *Oracle VM-2* — começando a tentar criar {DISPLAY} ({OCPUS} OCPU/{MEM_GB} GB, Ubuntu ARM) em {cfg['region']}. Aviso quando conseguir.")
    n = 0
    while True:
        if PAUSE.exists():
            time.sleep(60); continue
        n += 1
        for ad in ads:  # tenta cada AD (capacidade varia por AD)
            try:
                det = oci.core.models.LaunchInstanceDetails(
                    compartment_id=comp, availability_domain=ad.name, display_name=DISPLAY, shape=SHAPE,
                    shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=OCPUS, memory_in_gbs=MEM_GB),
                    source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=img, source_type="image", boot_volume_size_in_gbs=BOOT_GB),
                    create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=sub, assign_public_ip=True),
                    metadata={"ssh_authorized_keys": ssh_pub})
                inst = cc.launch_instance(det).data
                log(f"✅ CRIADA! id={inst.id}")
                telegram(f"✅ *Oracle VM-2 CRIADA!* ({OCPUS} OCPU/{MEM_GB} GB)\nAD: {ad.name}\nid: `{inst.id}`\nChave SSH: `~/.oci2/vm_ssh_key`\nPegando o IP público…")
                # espera ficar RUNNING e pega IP
                oci.wait_until(cc, cc.get_instance(inst.id), 'lifecycle_state', 'RUNNING', max_wait_seconds=600)
                vas = cc.list_vnic_attachments(comp, instance_id=inst.id).data
                ip = vnc.get_vnic(vas[0].vnic_id).data.public_ip if vas else "?"
                log(f"RUNNING ip={ip}")
                telegram(f"🟢 *VM-2 no ar!* IP `{ip}`\n`ssh -i ~/.oci2/vm_ssh_key ubuntu@{ip}`")
                return
            except oci.exceptions.ServiceError as e:
                m = (e.message or "").lower()
                if "capacity" in m:
                    continue  # tenta próximo AD; se todos cheios, dorme abaixo
                if e.status == 429:
                    log("throttle (429) — esperando mais"); time.sleep(120); break
                log(f"ERRO {e.status}: {e.message}")
                if e.status in (400, 401, 404) and "capacity" not in m:
                    telegram(f"⚠️ *VM-2* erro de config ({e.status}): {e.message[:120]} — preciso corrigir.")
                    return
        if n % TELEGRAM_A_CADA == 0:
            telegram(f"⏳ VM-2: {n} tentativas, Oracle ainda sem vaga (Out of host capacity). Continuo tentando.")
        log(f"tentativa {n}: sem vaga em nenhum AD — aguardo {INTERVALO}s")
        time.sleep(INTERVALO)

if __name__ == "__main__":
    main()
