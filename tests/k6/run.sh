#!/usr/bin/env bash
# Run all scrumbleeggs k6 benchmarks.
# Usage:
#   ./tests/k6/run.sh smoke        — sanity check only
#   ./tests/k6/run.sh load         — sustained load test
#   ./tests/k6/run.sh stress       — find the breaking point
#   ./tests/k6/run.sh spike        — spike test
#   ./tests/k6/run.sh session      — realistic board session
#   ./tests/k6/run.sh all          — run all in sequence

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_URL="${BASE_URL:-http://localhost:8000}"

check_server() {
  if ! curl -sf "${BASE_URL}/api/stats" > /dev/null 2>&1; then
    echo "ERROR: Server not reachable at ${BASE_URL}"
    echo "Start it with: python -m uvicorn scrumbleeggs.web.app:app --reload"
    exit 1
  fi
  echo "Server OK at ${BASE_URL}"
}

run_test() {
  local name="$1"
  local file="$2"
  echo ""
  echo "════════════════════════════════════════"
  echo "  Running: ${name}"
  echo "════════════════════════════════════════"
  k6 run --env BASE_URL="${BASE_URL}" "${file}"
}

check_server

case "${1:-smoke}" in
  smoke)   run_test "Smoke"    "${DIR}/smoke.js" ;;
  load)    run_test "Load"     "${DIR}/load.js" ;;
  stress)  run_test "Stress"   "${DIR}/stress.js" ;;
  spike)   run_test "Spike"    "${DIR}/spike.js" ;;
  session) run_test "Session"  "${DIR}/scenarios/board_session.js" ;;
  all)
    run_test "Smoke"   "${DIR}/smoke.js"
    run_test "Load"    "${DIR}/load.js"
    run_test "Spike"   "${DIR}/spike.js"
    run_test "Session" "${DIR}/scenarios/board_session.js"
    # Stress last — it deliberately breaks things
    run_test "Stress"  "${DIR}/stress.js"
    ;;
  *)
    echo "Unknown test: $1"
    echo "Usage: $0 [smoke|load|stress|spike|session|all]"
    exit 1
    ;;
esac
