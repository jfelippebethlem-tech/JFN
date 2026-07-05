#!/bin/bash
# delegar_llm.sh "<prompt>" -> resposta do modelo forte do desktop (RAPIDO, direto na tailnet)
# exit 2 = desktop offline (use seu proprio modelo); exit 3 = erro
DESK=100.75.118.110
"$HOME/JFN/tools/desktop_disponivel.sh" || exit 2
PJ=$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$1" 2>/dev/null)
R=$(curl -s -m 120 "http://$DESK:11434/api/generate" -d "{\"model\":\"qwen3-coder-32k\",\"prompt\":$PJ,\"stream\":false}" 2>/dev/null)
ANS=$(echo "$R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('response',''))" 2>/dev/null)
[ -n "$ANS" ] && { echo "$ANS"; exit 0; }
exit 3
