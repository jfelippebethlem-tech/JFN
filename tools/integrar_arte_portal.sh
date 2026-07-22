#!/bin/bash
# Integra uma arte de fundo (gerada no site do Higgsfield pelo dono) ao portal
# do painel JFN e ao polimonitor. Uso:
#   bash tools/integrar_arte_portal.sh "<URL-da-imagem>"
# ou, se a imagem chegou pelo Yoda:
#   bash tools/integrar_arte_portal.sh /home/ubuntu/.hermes/cache/images/img_XXXX.jpg
set -e
SRC="$1"
[ -z "$SRC" ] && { echo "uso: $0 <url-ou-caminho-da-imagem>"; exit 1; }

DEST_JFN=/home/ubuntu/JFN/static/assets/portal-arte.jpg
DEST_POLI=/home/ubuntu/polimonitor/public/portal-arte.jpg

echo "→ obtendo arte de: $SRC"
if [[ "$SRC" == http* ]]; then
  curl -fsSL --max-time 60 "$SRC" -o "$DEST_JFN"
else
  cp "$SRC" "$DEST_JFN"
fi

# valida que é imagem de verdade (não HTML de erro)
file "$DEST_JFN" | grep -qiE "image|JPEG|PNG" || { echo "!! não é imagem — abortado"; rm -f "$DEST_JFN"; exit 2; }
cp "$DEST_JFN" "$DEST_POLI"
SZ=$(du -h "$DEST_JFN" | cut -f1)
echo "✓ arte salva: $DEST_JFN e $DEST_POLI ($SZ)"
echo "  agora peça ao Claude para ligá-la como camada de fundo do portal (atrás do shader)."
