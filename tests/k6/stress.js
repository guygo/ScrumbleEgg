/**
 * Stress test — find the breaking point.
 * Run: k6 run tests/k6/stress.js
 *
 * Watch for:
 *   - error rate climbing above 5%
 *   - p(99) latency exceeding 5s
 *   - SQLite "database is locked" errors in server logs
 */
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import { ensureLoggedIn, BASE_URL as BASE } from './lib/auth.js';

const errors    = new Rate('errors');
const dbErrors  = new Rate('db_errors');
const latency   = new Trend('req_latency', true);

export const options = {
  stages: [
    { duration: '2m',  target: 20  },   // warm up
    { duration: '3m',  target: 50  },   // moderate stress
    { duration: '3m',  target: 100 },   // heavy stress
    { duration: '3m',  target: 150 },   // breaking point region
    { duration: '2m',  target: 0   },   // recovery
  ],
  thresholds: {
    // These WILL fail under stress — that's the point
    http_req_duration: ['p(95)<5000'],
    errors:            ['rate<0.30'],
  },
};

const HEADERS = { 'Content-Type': 'application/json' };

export default function () {
  ensureLoggedIn();
  const start = Date.now();

  // Mix of read/write — writes are the DB bottleneck
  const isWrite = Math.random() < 0.3;

  let r;
  if (isWrite) {
    r = http.post(
      `${BASE}/api/tickets`,
      JSON.stringify({
        title: `Stress test ${__VU}-${__ITER}`,
        priority: 'medium',
        ticket_type: 'task',
      }),
      { headers: HEADERS }
    );
  } else {
    r = http.get(`${BASE}/api/board`);
  }

  latency.add(Date.now() - start);

  const ok = check(r, { 'status ok': (r) => r.status < 500 });
  errors.add(!ok);

  // Detect DB lock errors specifically
  if (r.status === 500) {
    const body = r.body || '';
    dbErrors.add(body.includes('locked') || body.includes('database'));
  }

  sleep(0.1); // minimal think time to maximize pressure
}
