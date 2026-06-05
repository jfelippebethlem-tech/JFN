#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# iniciar.sh — inicia TUDO: Chrome debug + scheduler diário + Groq explorer
#
# Uso:
#   ./iniciar.sh            → inicia o scheduler (modo normal, 08:00 todo dia)
#   ./iniciar.sh --agora    → roda o ciclo de coleta imediatamente e sai
#   ./iniciar.sh --groq     → inicia o Groq explorer (explora SIAFE2 com IA)
#   ./iniciar.sh --analisar → mostra relatório do banco de dados
# ─────────────────────────────────────────────────────────────────────────────

set -e
cd "$(dirname "$0")"

# ── Cores ─────────────────────────────────────────────────────────────────────
B='\033[96m'; Y='\033[93m'; G='\033[92m'; R='\033[91m'; RST='\033[0m'; BOLD='\033[1m'

echo -e "${BOLD}${B}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║   JFN Compliance Agent — Auditoria SIAFE2 + DOERJ   ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${RST}"

# ── Verificar .env ─────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    echo -e "${R}  ERRO: arquivo .env não encontrado!${RST}"
    echo "  Crie o arquivo .env com:"
    echo "    SIAFE_USER=seu_cpf"
    echo "    SIAFE_PASS=sua_senha"
    exit 1
fi
source .env
echo -e "  ${G}✓${RST} .env carregado (usuário: $SIAFE_USER)"

# ── Inicializar banco de dados ─────────────────────────────────────────────────
echo -e "  ${G}✓${RST} Inicializando banco de dados..."
python -c "from compliance_agent.database.models import init_db; init_db(); print('  ✓ DB OK')"

# ── Verificar Chrome com debug port ───────────────────────────────────────────
CHROME_PORT=9222
if curl -s "http://127.0.0.1:${CHROME_PORT}/json/version" > /dev/null 2>&1; then
    echo -e "  ${G}✓${RST} Chrome já está aberto na porta ${CHROME_PORT}"
else
    echo -e "  ${Y}⚠${RST}  Chrome NÃO está aberto na porta ${CHROME_PORT}"
    echo ""
    echo "  Para habilitar coleta automática do SIAFE2, abra o Chrome assim:"
    echo -e "  ${B}  google-chrome --remote-debugging-port=9222 &${RST}"
    echo "  (ou use o atalho já configurado no Windows)"
    echo ""
    echo "  Continuando sem Chrome — coleta SIAFE2 será pulada."
fi

# ── Dispatch por argumento ─────────────────────────────────────────────────────
case "${1:-}" in

  --agora)
    echo -e "\n  ${BOLD}${Y}Rodando ciclo de coleta AGORA...${RST}"
    python -m compliance_agent.scheduler
    echo -e "\n  ${G}Pronto! Veja o resultado:${RST}"
    python analisar.py
    ;;

  --groq)
    echo -e "\n  ${BOLD}${Y}Iniciando Groq Explorer (IA autônoma no SIAFE2)...${RST}"
    if ! curl -s "http://127.0.0.1:${CHROME_PORT}/json/version" > /dev/null 2>&1; then
        echo -e "  ${R}ERRO: Chrome não está aberto. Abra o Chrome com --remote-debugging-port=9222 primeiro.${RST}"
        exit 1
    fi
    python -m siafe_agent.llm.groq_explorer
    ;;

  --analisar)
    echo ""
    python analisar.py --tudo
    ;;

  --obs)
    echo ""
    python analisar.py --obs
    ;;

  *)
    echo -e "\n  ${BOLD}${Y}Iniciando scheduler diário (executa todos os dias às 08:00)...${RST}"
    echo -e "  ${DIM}Pressione Ctrl+C para parar.${RST}\n"
    python -m compliance_agent.scheduler --loop
    ;;

esac
