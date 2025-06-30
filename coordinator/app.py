"""
coordinator.py
─────────────────────────────────────────────────────────────────────────────
• Recebe ?q=<texto>, divide o corpus e despacha para N workers /search.
• Agrega todos os resultados e expõe métricas Prometheus.
"""

from __future__ import annotations

import glob
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import cycle
from pathlib import Path
from typing import List

import requests
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
WORKER_URLS: List[str] = [
    u.strip()
    for u in os.getenv("WORKERS", "http://worker:8000").split(",")
    if u.strip()
]
BATCH: int = int(os.getenv("BATCH_SIZE", "0"))  # 0 → divisão em partes iguais
CORPUS: List[str] = sorted(glob.glob("/data/**/*.txt", recursive=True))
DEFAULT_TIMEOUT = int(os.getenv("WORKER_TIMEOUT", "120"))  # segundos
MAX_PARALLEL = int(os.getenv("PARALLEL_CALLS", str(len(WORKER_URLS) or 1)))


# ────────────────────────────── Métricas ────────────────────────────────── #
class Metrics:
    def __init__(self) -> None:
        self.reqs = Counter("coord_requests_total", "Total de buscas recebidas")
        self.errors = Counter("coord_requests_errors", "Erros no coordinator")
        self.inflight = Gauge("coord_inflight", "Requisições em andamento")
        self.latency = Histogram(
            "coord_total_latency_seconds", "Latência total da busca"
        )
        Info("coord_info", "Coordinator info").info({"workers": str(len(WORKER_URLS))})

    # helpers -------------------------------------------------------------- #
    def observe_start(self):
        self.reqs.inc()
        self.inflight.inc()
        return time.time()

    def observe_end(self, started: float, error: bool = False):
        self.latency.observe(time.time() - started)
        if error:
            self.errors.inc()
        self.inflight.dec()


metrics = Metrics()


# ────────────────────────────── Utilidades ──────────────────────────────── #
def slice_corpus(batch: int, corpus: List[str], n_workers: int) -> List[List[str]]:
    """Devolve lista de fatias (chunks) do corpus para cada worker."""
    if batch > 0:
        return [corpus[i : i + batch] for i in range(0, len(corpus), batch)]
    # fatiamento round-robin balanceado
    return [corpus[i::n_workers] for i in range(n_workers)]


def call_worker(session: requests.Session, url: str, q: str, files: List[str]) -> dict:
    """Dispara POST /search para um único worker."""
    resp = session.post(
        f"{url.rstrip('/')}/search",
        json={"q": q, "files": files},
        timeout=DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()  # {"hits":[{"file":..,"count":..}, ...], "total_hits": N}


# ────────────────────────────── Flask App ───────────────────────────────── #
app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=MAX_PARALLEL)
worker_cycle = cycle(WORKER_URLS)  # round-robin infinito


@app.get("/search")
def search():
    q: str = (request.args.get("q") or "").strip()
    if not q:
        return jsonify(error="faltou parâmetro ?q="), 400
    if not CORPUS:
        return jsonify(error="corpus vazio ou não montado em /data"), 500

    started = metrics.observe_start()

    try:
        chunks = slice_corpus(BATCH, CORPUS, len(WORKER_URLS))
        if not chunks:
            return jsonify(hits=[], total_hits=0)

        # Chama workers em paralelo
        fut_to_worker = {}
        session = requests.Session()
        for chunk in chunks:
            url = next(worker_cycle)
            fut = executor.submit(call_worker, session, url, q, chunk)
            fut_to_worker[fut] = url

        aggregated_hits: List[dict] = []
        for fut in as_completed(fut_to_worker):
            data = fut.result()  # propagate HTTP errors
            aggregated_hits.extend(data.get("hits", []))

        # Agrupar hits duplicados (mesmo arquivo pode aparecer em mais de um pedaço)
        grouped: dict[str, int] = {}
        for item in aggregated_hits:
            grouped[item["file"]] = grouped.get(item["file"], 0) + item["count"]

        total_hits = sum(grouped.values())
        # Ordena por contagem desc.
        hits_sorted = [
            {"file": f, "count": c}
            for f, c in sorted(grouped.items(), key=lambda x: (-x[1], x[0]))
        ]

        metrics.observe_end(started)
        return jsonify(hits=hits_sorted, total_hits=total_hits), 200

    except Exception as exc:
        metrics.observe_end(started, error=True)
        return jsonify(error=str(exc)), 500


@app.get("/metrics")
def prometheus_metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


# ──────────────────────────────── Main ──────────────────────────────────── #
if __name__ == "__main__":
    # threaded=True aqui só afeta o WSGI do Flask; chamadas externas já estão em pool
    app.run(host="0.0.0.0", port=8080, threaded=True)
