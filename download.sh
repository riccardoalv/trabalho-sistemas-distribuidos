#!/usr/bin/env bash
set -euo pipefail

DEST="./corpus"
mkdir -p "$DEST"
cd "$DEST"

for id in $(seq 1 100); do
  echo "⌛ Baixando ID $id…"
  success=false
  for suffix in "-0" "" "-8"; do                # tenta 3 formatos
    url="https://www.gutenberg.org/files/${id}/${id}${suffix}.txt"
    if wget -q --content-disposition --no-clobber "$url"; then
      echo "✓ OK: $(basename "$url")"
      success=true
      break
    fi
  done
  $success || echo "⚠️  ID $id não possui TXT público"
done

echo "🏁 Concluído — veja os arquivos em $DEST"
