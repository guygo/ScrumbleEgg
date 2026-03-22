# Scrumbleeggs — k6 Load Tests

Benchmarks for finding performance limits and DB bottlenecks.

## Prerequisites

Install k6:
```bash
brew install k6          # macOS
# or
docker pull grafana/k6   # Docker
```

Start the server before running:
```bash
python -m uvicorn scrumbleeggs.web.app:app --host 0.0.0.0 --port 8000 --reload
```

## Tests

| Script | VUs | Duration | Purpose |
|---|---|---|---|
| `smoke.js` | 1 | 30s | Sanity check — all endpoints return 200 |
| `load.js` | 10→30 | 5m | Sustained realistic team usage |
| `stress.js` | 20→150 | 13m | Find the breaking point |
| `spike.js` | 5→100 | 3m | Sudden traffic burst |
| `scenarios/board_session.js` | 10→20 | 5m | Full developer session flow |

## Running

```bash
chmod +x tests/k6/run.sh

./tests/k6/run.sh smoke     # quick sanity (30s)
./tests/k6/run.sh load      # team usage (5m)
./tests/k6/run.sh stress    # break it (13m)
./tests/k6/run.sh spike     # spike test (3m)
./tests/k6/run.sh session   # realistic session (5m)
./tests/k6/run.sh all       # everything
```

## What to Watch

### SQLite Bottlenecks
SQLite uses file-level write locking. Bottlenecks appear as:
- `database is locked` errors in server logs
- p(99) write latency > 5s under stress
- Error rate spike exactly when concurrent writes exceed WAL buffer

**Key metrics to compare pre/post optimization:**
- `write_latency p(95)` — time for POST /api/tickets
- `board_latency p(95)` — time for GET /api/board
- `http_req_failed rate` — error rate under load

### Read vs Write Scaling
SQLite WAL mode allows concurrent reads. Expect:
- Reads: scale to 50+ concurrent VUs with stable latency
- Writes: degrade sharply above ~20 concurrent writers
- Mixed (80/20): stable to ~40 VUs, degrades above that

### Thresholds
| Metric | Green | Yellow | Red |
|---|---|---|---|
| p(95) GET latency | <200ms | <800ms | >1s |
| p(95) POST latency | <500ms | <1500ms | >3s |
| Error rate | <1% | <5% | >10% |

## Output Example

```
✓ board ok
✓ stats ok
✓ ticket created

checks.........................: 99.87% ✓ 2997 ✗ 4
data_received..................: 12 MB  39 kB/s
http_req_duration..............: avg=145ms min=12ms med=98ms max=2.1s p(90)=312ms p(95)=487ms
board_latency..................: avg=89ms  min=9ms  med=62ms  max=890ms
write_latency..................: avg=312ms min=45ms med=287ms max=1.8s
tickets_created................: 342
```
