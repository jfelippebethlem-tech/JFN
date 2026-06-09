# -*- coding: utf-8 -*-
"""
gen_router_tools — gera as TOOL-SPECS (function-calling) do Yoda a partir do capabilities.yaml (JFN 2.0, Onda 1).

Cada capacidade vira uma ferramenta que o LLM do gateway pode chamar (tool-calling nativo), substituindo o
roteamento por keyword. Apenas capacidades com status PRONTO viram ferramentas ATIVAS; as "ONDA N" entram
desabilitadas (o roteador NÃO pode chamá-las — evita o bug histórico de inventar ferramenta inexistente).

Saída: JSON em ~/.hermes/jfn_tools.json (lido pelo gateway) + cópia versionada em data/jfn_tools.json.
NUNCA editar o JSON à mão — é derivado. Rodar no pre-commit p/ não divergir.

Uso: cd ~/JFN && PYTHONPATH=. .venv/bin/python -m tools.gen_router_tools
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
_YAML = _REPO / "capabilities.yaml"
_OUT_REPO = _REPO / "data" / "jfn_tools.json"
_OUT_HERMES = Path.home() / ".hermes" / "jfn_tools.json"

# mapeia o tipo declarado em args -> JSON Schema (heurístico; args do YAML são descritivos)
def _param_schema(desc) -> dict:
    d = str(desc).lower()
    if d.startswith("int") or "int=" in d or "int " in d:
        return {"type": "integer"}
    if d.startswith("bool") or "bool" in d:
        return {"type": "boolean"}
    if "list" in d:
        return {"type": "array", "items": {"type": "string"}}
    return {"type": "string"}


def _tool_spec(cap: dict) -> dict:
    """Converte uma capacidade num tool-spec estilo function-calling (compatível OpenAI/Anthropic)."""
    args = cap.get("args") or {}
    props, required = {}, []
    for nome, desc in args.items():
        props[nome] = {**_param_schema(desc), "description": str(desc)}
        if "obrigatorio" in str(desc).lower():
            required.append(nome)
    descricao = cap.get("descricao", "")
    if cap.get("quando_usar"):
        descricao += f" — usar quando: {cap['quando_usar']}"
    # COMO CHAMAR (o gateway monta curl via LLM; sem isto ele chuta o método → 405). Ex.: [GET /api/cartel].
    if cap.get("tipo") == "http" and cap.get("rota"):
        descricao += f" — chamar: {cap.get('metodo', 'GET')} {cap['rota']} (base http://127.0.0.1:8000)"
    elif cap.get("comando"):
        descricao += f" — chamar (cli): {cap['comando']}"
    return {
        "type": "function",
        "function": {
            "name": cap["id"],
            "description": descricao,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
        "_meta": {"agente": cap.get("agente"), "dominio": cap.get("dominio"),
                  "tipo": cap.get("tipo"), "rota": cap.get("rota"), "comando": cap.get("comando"),
                  "metodo": cap.get("metodo"), "status": cap.get("status"),
                  "enviar_telegram": cap.get("enviar_telegram")},
    }


def gerar() -> dict:
    doc = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    caps = doc.get("capacidades", [])
    ativas = [_tool_spec(c) for c in caps if c.get("status") == "PRONTO"]
    futuras = [c["id"] for c in caps if str(c.get("status", "")).startswith("ONDA")]
    payload = {
        "_gerado_de": "capabilities.yaml (NÃO editar à mão)",
        "versao": doc.get("meta", {}).get("versao"),
        "base_http": doc.get("meta", {}).get("base_http"),
        "tools": ativas,                 # só PRONTO viram ferramentas chamáveis
        "futuras_desabilitadas": futuras,  # registradas, mas o roteador NÃO chama
        "politica_modelo": doc.get("politica_modelo", {}),
    }
    out = json.dumps(payload, ensure_ascii=False, indent=2)
    _OUT_REPO.parent.mkdir(parents=True, exist_ok=True)
    _OUT_REPO.write_text(out, encoding="utf-8")
    try:
        _OUT_HERMES.parent.mkdir(parents=True, exist_ok=True)
        _OUT_HERMES.write_text(out, encoding="utf-8")
    except Exception:
        pass
    return {"tools_ativas": len(ativas), "futuras": len(futuras),
            "saida": [str(_OUT_REPO), str(_OUT_HERMES)]}


if __name__ == "__main__":
    r = gerar()
    print(f"✅ gen_router_tools: {r['tools_ativas']} ferramentas ativas (PRONTO), "
          f"{r['futuras']} futuras desabilitadas → {r['saida'][0]}")
