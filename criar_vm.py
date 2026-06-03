"""
criar_vm.py — Cria a VM Oracle Cloud automaticamente.
Fica tentando até conseguir capacidade (erro comum no plano grátis).

Requisito: pip install oci cryptography
"""
import oci
import time
import sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
import glob
import os

# ── Configurações da sua conta Oracle ────────────────────────────────────────
CONFIG = {
    "user":        "ocid1.user.oc1..aaaaaaaamnwgebr5junqyaxiabqeihgvaotle5kob7fh33odx5w4myqyrfka",
    "fingerprint": "8a:59:ec:5a:a0:b1:dc:a3:59:4b:63:9d:10:8f:68:ee",
    "tenancy":     "ocid1.tenancy.oc1..aaaaaaaakr3tlyd2bjc2xpwuk5nrh5d2yzvpyna3i4k2dzw4ou6umol2lmrq",
    "region":      "sa-saopaulo-1",
    # Chave privada OCI — arquivo baixado do console Oracle
    # O script procura automaticamente o .pem na mesma pasta
    "key_file":    "",  # preenchido automaticamente abaixo
}

COMPARTMENT = CONFIG["tenancy"]
AD          = "CubR:SA-SAOPAULO-1-AD-1"
SHAPE       = "VM.Standard.A1.Flex"
INTERVALO   = 60   # segundos entre tentativas


def _achar_chave_oci():
    """Procura o arquivo .pem da chave OCI em várias pastas possíveis."""
    pasta_script = os.path.dirname(os.path.abspath(__file__))
    pasta_pai    = os.path.dirname(pasta_script)
    # Busca na pasta do script, pasta pai e C:\JFN (fallback Windows)
    dirs = [pasta_script, pasta_pai, r"C:\JFN", os.path.expanduser("~")]
    for d in dirs:
        candidatos = glob.glob(os.path.join(d, "*.pem"))
        privados = [c for c in candidatos if "public" not in c.lower()]
        if privados:
            return privados[0]
        if candidatos:
            return candidatos[0]
    return None


def gerar_ssh():
    pasta = os.path.dirname(os.path.abspath(__file__))
    destino = os.path.join(pasta, "vm_ssh_key.pem")
    chave = rsa.generate_private_key(65537, 2048, default_backend())
    priv  = chave.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption()).decode()
    pub   = chave.public_key().public_bytes(
                serialization.Encoding.OpenSSH,
                serialization.PublicFormat.OpenSSH).decode()
    with open(destino, "w") as f:
        f.write(priv)
    print(f"✅ Chave SSH salva em: {destino}  ← GUARDE ESSE ARQUIVO!")
    return pub


def achar_imagem(cc):
    imgs = cc.list_images(
        COMPARTMENT,
        operating_system="Canonical Ubuntu",
        operating_system_version="22.04",
    ).data
    arm = [i for i in imgs if "aarch64" in i.display_name.lower()]
    escolhidas = arm or imgs
    return escolhidas[0].id if escolhidas else None


def achar_subnet(vc):
    for vcn in vc.list_vcns(COMPARTMENT).data:
        for s in vc.list_subnets(COMPARTMENT, vcn_id=vcn.id).data:
            if not s.prohibit_internet_ingress:
                return s.id
    return None


def tentar(cc, img, sub, ssh_pub, n):
    print(f"\n🔄 Tentativa {n}  [{time.strftime('%H:%M:%S')}]")
    try:
        inst = cc.launch_instance(
            oci.core.models.LaunchInstanceDetails(
                compartment_id      = COMPARTMENT,
                availability_domain = AD,
                display_name        = "JFN-Agent",
                shape               = SHAPE,
                shape_config        = oci.core.models.LaunchInstanceShapeConfigDetails(
                                          ocpus=1, memory_in_gbs=6),
                source_details      = oci.core.models.InstanceSourceViaImageDetails(
                                          image_id=img, source_type="image"),
                create_vnic_details = oci.core.models.CreateVnicDetails(
                                          subnet_id=sub, assign_public_ip=True),
                metadata            = {"ssh_authorized_keys": ssh_pub},
            )
        ).data
        return inst
    except oci.exceptions.ServiceError as e:
        msg = getattr(e, "message", str(e))
        if "Out of capacity" in msg:
            print(f"   ⚠️  Sem capacidade ainda. Próxima tentativa em {INTERVALO}s...")
        else:
            print(f"   ❌ Erro inesperado: {msg}")
        return None
    except Exception as e:
        print(f"   ❌ {type(e).__name__}: {e}")
        return None


def main():
    print("=" * 55)
    print("  JFN Agent — criador automático de VM Oracle Cloud")
    print("=" * 55)

    # Localiza a chave OCI automaticamente
    chave = _achar_chave_oci()
    if not chave:
        sys.exit(
            "\n❌ Chave OCI não encontrada!\n"
            "   Coloque o arquivo .pem (chave privada) na mesma pasta que este script.\n"
            "   Exemplo: C:\\JFN\\jfelippebethlemgmail.com...pem"
        )
    print(f"\n🔑 Usando chave OCI: {os.path.basename(chave)}")
    CONFIG["key_file"] = chave

    cc = oci.core.ComputeClient(CONFIG)
    vc = oci.core.VirtualNetworkClient(CONFIG)

    print("\n🔑 Gerando chave SSH para a VM...")
    ssh_pub = gerar_ssh()

    print("🔍 Buscando imagem Ubuntu 22.04 ARM...")
    img = achar_imagem(cc)
    if not img:
        sys.exit("❌ Imagem Ubuntu 22.04 não encontrada na sua conta Oracle.")
    print(f"   ✅ {img[:60]}...")

    print("🔍 Buscando subnet pública...")
    sub = achar_subnet(vc)
    if not sub:
        sys.exit(
            "❌ Subnet não encontrada.\n"
            "   Volte ao console Oracle e crie uma VCN com subnet pública primeiro."
        )
    print(f"   ✅ {sub[:60]}...")

    print(f"\n🚀 Iniciando tentativas a cada {INTERVALO}s.")
    print("   Pressione Ctrl+C para parar.\n")

    n = 1
    while True:
        inst = tentar(cc, img, sub, ssh_pub, n)
        if inst:
            pasta = os.path.dirname(os.path.abspath(__file__))
            print(f"\n{'=' * 55}")
            print("  ✅  VM CRIADA COM SUCESSO!")
            print(f"  ID: {inst.id}")
            print("  Aguarde ~3 minutos e veja o IP no console Oracle.")
            print(f"  Chave SSH: {os.path.join(pasta, 'vm_ssh_key.pem')}")
            print(f"{'=' * 55}")
            break
        n += 1
        time.sleep(INTERVALO)


if __name__ == "__main__":
    main()
