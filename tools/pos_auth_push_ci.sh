#!/usr/bin/env bash
# Cadeia pós-autorização: escopo -> push -> Actions -> rascunho da BASE-FALHAS-CI.
#
# POR QUE EXISTE. O push desta branch exige escopo `workflow` no token (o lote toca
# `.github/workflows/testes.yml` já no commit mais antigo, então não há subconjunto que suba sem
# ele). Conseguir esse escopo é device flow — um humano colando um código no navegador, sem
# contorno automático. Todo o RESTO da cadeia é mecânico, e é o que este script faz de uma vez:
# assim que a autorização existir, sobra um comando em vez de seis passos manuais.
#
# O QUE ELE NÃO FAZ, DE PROPÓSITO: não escreve em tests/BASE-FALHAS-CI.txt. Gera um RASCUNHO em
# /tmp para leitura. Toda linha que entra naquele arquivo é uma falha que o CI tolera para sempre;
# absorver falha sem ler é exatamente como o teto de `except: pass` chegou vermelho em 157 vindo de
# outra sessão. O próprio cabeçalho do arquivo manda ler linha por linha — então quem lê é gente.
set -uo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo /home/ubuntu/JFN)" || exit 1
BRANCH=$(git branch --show-current)
RASCUNHO=/tmp/BASE-FALHAS-CI.rascunho.txt

# 1 · escopo, na FONTE (a API), nunca no cache do gh
escopos=$(gh api -i user 2>/dev/null | grep -i '^x-oauth-scopes:' || true)
echo "escopos do token: ${escopos:-<não obtidos>}"
if ! printf '%s' "$escopos" | grep -q 'workflow'; then
  cat >&2 <<'FIM'

BLOQUEADO: o token não tem escopo `workflow`.

  gh auth refresh -h github.com -s workflow     # device flow: exige o código no navegador
  ou um PAT clássico com repo+workflow, que de quebra fecha a rotação pendente.

FIM
  exit 3
fi

# 2 · varredura de credencial antes de empurrar (nada de segredo saindo da VM)
if git diff "@{u}..HEAD" --name-only 2>/dev/null \
   | grep -qiE '(^|/)\.env|auth\.json|\.pem$|\.key$|secret|credential'; then
  echo "ABORTADO: há arquivo com cara de credencial no conjunto a empurrar." >&2
  git diff "@{u}..HEAD" --name-only | grep -iE '(^|/)\.env|auth\.json|\.pem$|\.key$|secret|credential' >&2
  exit 4
fi

# 3 · push
echo "empurrando $(git rev-list --count @{u}..HEAD) commits em $BRANCH…"
git push origin "$BRANCH" || exit 5

# 4 · esperar o Actions — ancorado em ARTEFATO (o status da run), nunca em pgrep,
#     que nesta casa já casou a própria linha de comando e travou 4h14.
echo "aguardando a run de testes.yml…"
run=""
for _ in $(seq 1 60); do
  run=$(gh run list --workflow=testes.yml --branch "$BRANCH" --limit 1 \
          --json databaseId,status,conclusion 2>/dev/null)
  printf '%s' "$run" | grep -q '"status":"completed"' && break
  sleep 30
done
id=$(printf '%s' "$run" | sed -n 's/.*"databaseId":\([0-9]*\).*/\1/p')
[ -z "$id" ] && { echo "nenhuma run encontrada — verifique o Actions à mão" >&2; exit 6; }
echo "run $id: $(printf '%s' "$run" | sed -n 's/.*"conclusion":"\([^"]*\)".*/\1/p')"

# 5 · rascunho das falhas, para LEITURA humana
tmp=$(mktemp -d)
gh run download "$id" -D "$tmp" 2>/dev/null || gh run view "$id" --log-failed > "$tmp/log.txt" 2>/dev/null
grep -rhE '^(FAILED|ERROR)' "$tmp" 2>/dev/null | sed 's/ - .*//' | sort -u > "$RASCUNHO"
n=$(grep -c '' "$RASCUNHO" 2>/dev/null || echo 0)
rm -rf "$tmp"

echo
echo "RASCUNHO com $n falhas em $RASCUNHO"
echo "Leia linha por linha. Só então:"
echo "  cat $RASCUNHO >> tests/BASE-FALHAS-CI.txt"
echo "Cada linha vira falha tolerada para sempre — nenhuma entra sem ser lida."
