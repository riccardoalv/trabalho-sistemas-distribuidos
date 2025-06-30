"""
search_worker.py
─────────────────────────────────────────────────────────────────────────────
• Micro-serviço HTTP que procura um padrão de texto em vários arquivos.
• Algoritmo escolhível por variável de ambiente: brute-force | boyer-moore | kmp
• Exporte métricas no formato Prometheus.
"""

from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List

from flask import Flask, jsonify, request
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# ────────────────────────────── Configuração ────────────────────────────── #
THREADS: int = int(os.getenv("THREADS_PER_WORKER", "8"))
print(THREADS)
ALGO: str = os.getenv("SEARCH_ALGORITHM", "brute-force").lower()


# ────────────────────────────── Algoritmos ──────────────────────────────── #
def brute_force(text: str, pattern: str) -> int:
    """Contagem ingênua: percorre todo o texto (O(n·m))."""
    if not pattern:
        return 0
    m, n = len(pattern), len(text)
    hits = 0
    for i in range(n - m + 1):
        if text[i : i + m] == pattern:
            hits += 1
    return hits


def boyer_moore(text: str, pattern: str) -> int:
    """Versão simplificada que devolve quantidade de acertos."""
    m, n = len(pattern), len(text)
    if m == 0:
        return 0
    # Tabela de últimos índices
    last: Dict[str, int] = {ch: idx for idx, ch in enumerate(pattern)}
    hits, i = 0, m - 1  # ponteiro no texto
    while i < n:
        k = m - 1  # ponteiro no padrão
        j = i  # backup do cursor no texto para reiniciar busca
        while k >= 0 and text[j] == pattern[k]:
            j -= 1
            k -= 1
        if k == -1:  # padrão completo encontrado
            hits += 1
            i += m  # pula alinhamento inteiro (não-sobreposto)
        else:
            skip = max(1, k - last.get(text[i], -1))
            i += skip
    return hits


def kmp(text: str, pattern: str) -> int:
    """Knuth-Morris-Pratt devolvendo o total de ocorrências."""
    if not pattern:
        return 0

    # Pré-processa LPS
    lps: List[int] = [0] * len(pattern)
    length = 0
    for i in range(1, len(pattern)):
        while length and pattern[i] != pattern[length]:
            length = lps[length - 1]
        if pattern[i] == pattern[length]:
            length += 1
            lps[i] = length

    # Percorre texto
    hits = j = 0
    for ch in text:
        while j and ch != pattern[j]:
            j = lps[j - 1]
        if ch == pattern[j]:
            j += 1
            if j == len(pattern):
                hits += 1
                j = lps[j - 1]
    return hits


ALGORITHMS: Dict[str, Callable[[str, str], int]] = {
    "brute-force": brute_force,
    "boyer-moore": boyer_moore,
    "kmp": kmp,
}
SEARCH_FN: Callable[[str, str], int] = ALGORITHMS.get(ALGO, brute_force)


# ──────────────────────────── Métricas Prometheus ───────────────────────── #
class Metrics:
    def __init__(self, algorithm: str):
        self.labels = {"algorithm": algorithm}
        self.requests = Counter(
            "worker_requests_total", "Total de buscas recebidas", ["algorithm"]
        )
        self.latency = Histogram(
            "worker_latency_seconds", "Latência da busca", ["algorithm"]
        )
        self.active_threads = Gauge("worker_threads_active", "Threads ativas")
        Info("worker_algo", "Algoritmo em uso").info(self.labels)

    def observe(self):
        # snapshot de threads vivas
        self.active_threads.set(threading.active_count())

    def inc_requests(self):
        self.requests.labels(**self.labels).inc()


metrics = Metrics(ALGO)

# ──────────────────────────── Servidor Flask ────────────────────────────── #
app = Flask(__name__)
pool = ThreadPoolExecutor(max_workers=THREADS)


def count_in_file(path: Path, pattern: str) -> int:
    """Lê o arquivo inteiro em minúsculas e conta ocorrências de *pattern*."""
    try:
        with path.open("r", errors="ignore") as f:
            return SEARCH_FN(f.read().lower(), pattern)
    except Exception:
        return 0  # falha ao ler arquivo → 0 hits


@app.post("/search")
def batch_search():
    """Ex: POST /search  { "q": "needle", "files": ["a.txt", "b.txt"] }"""
    data = request.get_json(silent=True) or {}
    query: str = data.get("q", "").lower()
    files: List[str] = data.get("files", [])

    if not query or not files:
        return jsonify(error='esperado JSON com "q" e "files"'), 400

    # Caminhos absolutos para segurança
    file_paths = [Path(p) for p in files]

    metrics.observe()
    with metrics.latency.labels(**metrics.labels).time():
        counts = list(pool.map(count_in_file, file_paths, [query] * len(file_paths)))

    metrics.inc_requests()

    hits = [{"file": str(p), "count": c} for p, c in zip(files, counts) if c > 0]
    return jsonify(hits=hits, total_hits=sum(c for c in counts)), 200


@app.get("/metrics")
def prometheus_metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


# ──────────────────────────────── Main ───────────────────────────────────── #
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
