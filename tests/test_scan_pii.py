"""Scanner de CPF para hooks (O0.5 do plano Esteira Única): impede CPF novo no repo público."""
from tools.scan_pii import achar_cpfs, cpf_valido


def _cpf(base9: str) -> str:
    """Gera CPF com DV válido a partir de 9 dígitos (fixture sintética, nunca dado real)."""
    d = [int(c) for c in base9]
    for _ in range(2):
        s = sum(v * p for v, p in zip(d, range(len(d) + 1, 1, -1)))
        r = (s * 10) % 11
        d.append(0 if r == 10 else r)
    return "".join(map(str, d))


def test_dv_valido_e_invalido():
    c = _cpf("123456789")
    assert cpf_valido(c)
    assert not cpf_valido(c[:-1] + str((int(c[-1]) + 1) % 10))
    assert not cpf_valido("11111111111")  # repetido não é CPF


def test_acha_formatado_e_cru():
    c = _cpf("987654321")
    fmt = f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"
    assert achar_cpfs(f"nome X cpf {fmt} fim") == [c]
    assert achar_cpfs(f'{{"cpf": "{c}"}}') == [c]


def test_nao_acusa_processo_sei_nem_chave_longa_nem_mascarado():
    c = _cpf("246813579")
    assert achar_cpfs("SEI-080002/010544/2024") == []
    assert achar_cpfs("chave NF 3" + c + "0000000000000000000000000000000000") == []  # dentro de número longo
    assert achar_cpfs(f"***.{c[3:6]}.{c[6:9]}-**") == []  # mascarado
    assert achar_cpfs("12345678901") == [] or not cpf_valido("12345678901")


def test_nao_acusa_digitos_dentro_de_hash_hex():
    # 25/11/2026 (O9.3): os `--hash=sha256:` dos requirements*.lock têm corridas de 11 dígitos entre letras a-f — o
    # lookbehind só olhava dígito e o pre-commit barrou 9 "CPFs" que eram pedaço de hash.
    c = _cpf("135792468")
    h = ("ab" + c + "cd").ljust(64, "e")
    assert achar_cpfs(f"    --hash=sha256:{h} \\") == []
    assert achar_cpfs(f"commit {h[:40]}") == []
    assert achar_cpfs(f"cpf {c} junto de hash {h}") == [c]  # CPF de verdade ao lado de um hash continua acusado
