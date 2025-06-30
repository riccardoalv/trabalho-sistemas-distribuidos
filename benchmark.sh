#!/usr/bin/env bash

set -euo pipefail
shopt -s lastpipe

ALGORITHMS=(brute-force boyer-moore kmp)
CONFIGS=(
  "1 1"   # workers threads
  "1 4"
  "2 4"
  "5 4"
)

REPEATS=1          # vezes por config
REQS=10           # requisições por frase
CONC=1            # conexões paralelas hey

PHRASES=(
  "love and friendship"
  "to be or not to be"
  "the quick brown fox"
  "romeo and juliet"
  "sherlock holmes"
  "quantum flutter paradox"
  "zyzzyva insect taxonomy"
  "cryptozoological oddity"
  "pneumonoultramicroscopicsilicovolcanoconiosis theory"
  "floccinaucinihilipilification debate"
  "love"
  "time"
  "king"
  "data"
  "algorithm"
  "gryphon"
  "sesquipedalian"
  "xylophilous"
  "antidisestablishmentarianism"
  "ultracrepidarian"
)

LOGDIR="logs"

mkdir -p "$LOGDIR"

urlencode() { python - <<'PY' "$1"
import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))
PY
}

wait_ready() {
  local -i tries=30
  until curl -s -o /dev/null "http://localhost:8080/search?q=test" || (( --tries == 0 )); do
    sleep 1
  done
}

for ALG in "${ALGORITHMS[@]}"; do
  export SEARCH_ALGORITHM="$ALG"
  for cfg in "${CONFIGS[@]}"; do
    read -r WORKERS THREADS <<<"$cfg"
    export WORKER_COUNT="$WORKERS"
    export THREADS_PER_WORKER="$THREADS"

    for ((run=1; run<=REPEATS; run++)); do
      TAG="${ALG}_${WORKERS}w_${THREADS}t_run${run}"
      LOG="${LOGDIR}/${TAG}.log"
      echo -e "\n▶️  Starting $TAG" | tee -a "$LOG"

      docker compose up -d --build
      wait_ready

      for phrase in "${PHRASES[@]}"; do
        enc=$(urlencode "$phrase")
        echo -e "\n🔹 Query: \"$phrase\"  (${REQS} reqs)" | tee -a "$LOG"
        hey -n "$REQS" -c "$CONC" \
          "http://localhost:8080/search?q=${enc}" \
          | sed "s/^/[${phrase}] /" >> "$LOG"
      done

      docker compose down -v
      echo "✅ Finished $TAG" | tee -a "$LOG"
    done
  done
done

echo -e "\n🏁 Benchmarks completos — logs em '${LOGDIR}/'."
