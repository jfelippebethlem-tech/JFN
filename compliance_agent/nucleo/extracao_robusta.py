"""
Extração robusta com IA fraca — o antídoto para "IA fraca não entende tudo".

FILOSOFIA
---------
Não se pede a uma IA fraca (llama-8b, qwen-free, gemma) que "faça a perícia".
Pede-se só o que ela faz de forma confiável: LER um texto e DEVOLVER campos
factuais. Todo o resto — validação, decisão de risco, base legal — é código.

Esta camada torna a extração confiável mesmo com modelos fracos por 4 técnicas:

  1. SCHEMA ESTRITO   — descreve-se cada campo, tipo e exemplo no prompt; a IA
                        é forçada a devolver só JSON.
  2. REPARO           — se a IA embrulha o JSON em texto/```, extrai-se o objeto;
                        se falta campo, tenta-se de novo pedindo só o que faltou.
  3. VALIDAÇÃO DET.   — cada valor passa pelos validadores de dossie.py
                        (CNPJ, datas, reais). Campo que não valida é descartado,
                        não "chutado".
  4. AUTOCONSISTÊNCIA — para campos críticos (valor, CNPJ), roda-se a extração N
                        vezes e adota-se o valor majoritário. Um erro aleatório
                        de um modelo fraco é diluído pela votação.

A função de LLM é injetada (``llm_fn``), então isto não acopla a um provedor.
No sistema real, passe ``compliance_agent.llm.free_llm.best_free_chat``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from compliance_agent.nucleo.dossie import (
    cnpj_valido, cpf_valido, para_data, para_reais,
)


# Tipo da função de LLM: (prompt, system) -> texto.
LLMFn = Callable[[str, str], str]


@dataclass
class Campo:
    """Descreve um campo a extrair, com tipo e validador determinístico."""

    nome: str
    tipo: str                 # texto | reais | data | cnpj | cpf | inteiro | booleano
    descricao: str
    exemplo: str = ""
    critico: bool = False     # se True, usa autoconsistência (votação)


def _validar_campo(campo: Campo, valor: Any) -> tuple[bool, Any]:
    """Valida/normaliza um valor conforme o tipo. Retorna (ok, valor_normalizado)."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return False, None
    t = campo.tipo
    if t == "reais":
        v = para_reais(valor)
        return (v is not None), v
    if t == "data":
        v = para_data(valor)
        return (v is not None), (v.isoformat() if v else None)
    if t == "cnpj":
        n = re.sub(r"\D", "", str(valor))
        return cnpj_valido(n), n
    if t == "cpf":
        n = re.sub(r"\D", "", str(valor))
        return cpf_valido(n), n
    if t == "inteiro":
        try:
            return True, int(float(str(valor).replace(",", ".")))
        except (ValueError, TypeError):
            return False, None
    if t == "booleano":
        s = str(valor).strip().lower()
        if s in ("true", "sim", "yes", "1", "verdadeiro"):
            return True, True
        if s in ("false", "não", "nao", "no", "0", "falso"):
            return True, False
        return False, None
    # texto
    return True, str(valor).strip()


def _montar_prompt(texto: str, campos: list[Campo], faltantes: list[str] | None = None) -> str:
    alvo = [c for c in campos if (faltantes is None or c.nome in faltantes)]
    linhas = []
    for c in alvo:
        ex = f'  exemplo: {c.exemplo}' if c.exemplo else ""
        linhas.append(f'- "{c.nome}" ({c.tipo}): {c.descricao}{ex}')
    esquema = "\n".join(linhas)
    exemplo_json = "{" + ", ".join(f'"{c.nome}": ...' for c in alvo) + "}"
    return (
        "Extraia os campos abaixo do DOCUMENTO. Responda APENAS com um objeto JSON "
        "válido, sem explicação, sem markdown. Use null quando o campo não constar.\n\n"
        f"CAMPOS:\n{esquema}\n\n"
        f"FORMATO EXATO DA RESPOSTA:\n{exemplo_json}\n\n"
        f"DOCUMENTO:\n\"\"\"\n{texto[:6000]}\n\"\"\"\n"
    )


def _extrair_json(bruto: str) -> dict:
    """Extrai o primeiro objeto JSON de uma resposta possivelmente suja."""
    if not bruto:
        return {}
    # remove cercas de código
    bruto = re.sub(r"```(?:json)?", "", bruto)
    # tenta objeto inteiro
    try:
        return json.loads(bruto.strip())
    except (ValueError, TypeError):
        pass
    # busca o maior trecho {...}
    m = re.search(r"\{.*\}", bruto, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except (ValueError, TypeError):
            # última tentativa: normaliza aspas simples
            try:
                return json.loads(m.group(0).replace("'", '"'))
            except (ValueError, TypeError):
                return {}
    return {}


@dataclass
class ResultadoExtracao:
    dados: dict[str, Any]              # campos validados
    faltando: list[str]               # críticos não obtidos
    avisos: list[str]                 # campos rejeitados por validação
    tentativas: int


def extrair(
    texto: str,
    campos: list[Campo],
    llm_fn: LLMFn,
    *,
    votos_criticos: int = 3,
    max_reparos: int = 1,
    system: str = "Você é um extrator de dados factuais de documentos públicos. Só devolve JSON.",
) -> ResultadoExtracao:
    """
    Extrai ``campos`` de ``texto`` usando ``llm_fn``, com validação determinística,
    reparo e autoconsistência nos campos críticos.

    Nunca levanta exceção por causa da IA: devolve o que validou + o que faltou.
    """
    dados: dict[str, Any] = {}
    avisos: list[str] = []
    tentativas = 0

    def _uma_passada(faltantes: list[str] | None) -> dict:
        nonlocal tentativas
        tentativas += 1
        prompt = _montar_prompt(texto, campos, faltantes)
        try:
            bruto = llm_fn(prompt, system)
        except Exception as e:  # IA indisponível/erro de rede: segue sem ela
            avisos.append(f"IA indisponível na extração: {e}")
            return {}
        return _extrair_json(bruto)

    # 1ª passada: todos os campos.
    obj = _uma_passada(None)
    for c in campos:
        if c.nome in obj:
            ok, v = _validar_campo(c, obj[c.nome])
            if ok:
                dados[c.nome] = v
            elif obj[c.nome] not in (None, "", "null"):
                avisos.append(f"Campo {c.nome!r} rejeitado na validação ({c.tipo}).")

    # 2. Reparo: repete só os faltantes (uma ou mais rodadas).
    reparos = 0
    while reparos < max_reparos:
        faltantes = [c.nome for c in campos if c.nome not in dados]
        if not faltantes:
            break
        reparos += 1
        obj = _uma_passada(faltantes)
        for c in campos:
            if c.nome in faltantes and c.nome in obj:
                ok, v = _validar_campo(c, obj[c.nome])
                if ok:
                    dados[c.nome] = v

    # 3. Autoconsistência nos campos críticos: vota o valor majoritário.
    for c in campos:
        if not c.critico or votos_criticos <= 1:
            continue
        contagem: dict[str, int] = {}
        valores: dict[str, Any] = {}
        # inclui o valor já obtido como um voto
        if c.nome in dados:
            chave = str(dados[c.nome])
            contagem[chave] = contagem.get(chave, 0) + 1
            valores[chave] = dados[c.nome]
        for _ in range(votos_criticos - 1):
            obj = _uma_passada([c.nome])
            if c.nome in obj:
                ok, v = _validar_campo(c, obj[c.nome])
                if ok:
                    chave = str(v)
                    contagem[chave] = contagem.get(chave, 0) + 1
                    valores[chave] = v
        if contagem:
            vencedor = max(contagem, key=lambda k: contagem[k])
            dados[c.nome] = valores[vencedor]
            if len(contagem) > 1:
                avisos.append(
                    f"Campo crítico {c.nome!r} decidido por votação "
                    f"({contagem[vencedor]}/{sum(contagem.values())} votos)."
                )

    faltando = [c.nome for c in campos if c.critico and c.nome not in dados]
    return ResultadoExtracao(dados=dados, faltando=faltando,
                             avisos=avisos, tentativas=tentativas)
