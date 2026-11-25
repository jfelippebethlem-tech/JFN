#!/bin/bash
# cifrar_backup.sh <arquivo>  — cifra um backup com `age` para as chaves SSH das 3 máquinas e PROVA a volta.
#
# Por quê (decisão delegada de 24/11/2026, vault/refatoracao/decisoes-delegadas-infra-20261124.md): os backups iam em
# claro para o Drive e o R2, e o compliance.db tem CPF de sócio. Destinatários = as chaves SSH QUE JÁ EXISTEM (VM-1,
# VM-2, it-campo; nenhuma chave nova): qualquer uma das 3 máquinas restaura com a própria chave privada.
#   decifrar:  age -d -i ~/.ssh/id_ed25519 <arquivo>.age > <arquivo>
#
# Prova do efeito (não da ação): decifra com a chave DESTA máquina e confere o sha256 contra o original; só então
# apaga o claro. Imprime, na última linha, o caminho do .age. Sem destinatários ou com a prova falhando: sai ≠ 0 e
# deixa o claro onde estava (o backup não sobe em claro, e nada se perde).
# Destinatários: $BACKUP_AGE_RECIPIENTS (padrão ~/.config/jfn/backup_age_recipients.txt, fora do repo — ADR-011).
set -uo pipefail
ARQ="${1:?uso: cifrar_backup.sh <arquivo>}"
REC="${BACKUP_AGE_RECIPIENTS:-$HOME/.config/jfn/backup_age_recipients.txt}"
ID="${BACKUP_AGE_IDENTITY:-$HOME/.ssh/id_ed25519}"
[ -s "$ARQ" ] || { echo "[cifrar] ⛔ $ARQ ausente ou vazio" >&2; exit 1; }
N=$(grep -c '^ssh-' "$REC" 2>/dev/null || true)
[ "${N:-0}" -ge 1 ] || { echo "[cifrar] ⛔ sem destinatários age em $REC — backup NÃO sobe em claro" >&2; exit 1; }
rm -f "$ARQ.age"
if ! ionice -c3 nice -n19 age -R "$REC" -o "$ARQ.age" "$ARQ"; then
  echo "[cifrar] ⛔ age falhou" >&2; rm -f "$ARQ.age"; exit 1
fi
H1=$(ionice -c3 nice -n19 sha256sum < "$ARQ" | cut -c1-64)
H2=$(ionice -c3 nice -n19 age -d -i "$ID" "$ARQ.age" | sha256sum | cut -c1-64)
if [ -z "$H1" ] || [ "$H1" != "$H2" ]; then
  echo "[cifrar] ⛔ a volta não confere (sha256 ${H1:0:12} ≠ ${H2:0:12}) — claro mantido, .age apagado" >&2
  rm -f "$ARQ.age"; exit 1
fi
rm -f "$ARQ"
echo "[cifrar] ✓ $N destinatário(s), volta conferida (sha256 ${H1:0:16})" >&2
echo "$ARQ.age"
