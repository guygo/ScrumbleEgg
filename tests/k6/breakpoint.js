/**
 * Breakpoint test — ramps forever until the server breaks.
 * Goal: find the exact VU count where errors exceed 5% or p95 > 10s.
 * Run: k6 run tests/k6/breakpoint.js
 */
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import { ensureLoggedIn, BASE_URL as BASE } from './lib/auth.js';

const errors      = new Rate('errors');
const boardLat    = new Trend('board_latency', true);

export const options = {
  // Ramp from 0 → 400 VUs over 8 minutes. Abort conditions trigger early.
  stages: [
    { duration: '1m',  target: 25  },
    { duration: '1m',  target: 50  },
    { duration: '1m',  target: 100 },
    { duration: '1m',  target: 150 },
    { duration: '1m',  target: 200 },
    { duration: '1m',  target: 250 },
    { duration: '1m',  target: 300 },
    { duration: '1m',  target: 400 },
  ],
  thresholds: {
    // Abort the test if these are ever breached — this IS the breakpoint
    http_req_failed:   [{ threshold: 'rate<0.15', abortOnFail: true, delayAbortEval: '10s' }],
    http_req_duration: [{ threshold: 'p(95)<10000', abortOnFail: true, delayAbortEval: '10s' }],
  },
};

const HEADERS = { 'Content-Type': 'application/json' };
const TYPES   = ['task', 'story', 'bug'];
const PRIOS   = ['low', 'medium', 'high', 'critical'];

export function setup() {
  ensureLoggedIn();
  const r = http.get(`${BASE}/api/tickets?page_size=100`);
  const keys = r.status === 200 ? JSON.parse(r.body).tickets.map(t => t.key) : [];
  return { keys };
}

export default function (data) {
  ensureLoggedIn();
  const rand = Math.random();

  if (rand < 0.50) {
    // 50% board — heaviest cached read
    const t = Date.now();
    const r = http.get(`${BASE}/api/board`);
    boardLat.add(Date.now() - t);
    errors.add(!check(r, { 'board 200': r => r.status === 200 }));

  } else if (rand < 0.75) {
    // 25% ticket list
    const r = http.get(`${BASE}/api/tickets?page_size=25`);
    errors.add(!check(r, { 'list 200': r => r.status === 200 }));

  } else if (rand < 0.90) {
    // 15% single ticket
    const keys = data.keys;
    if (keys.length) {
      const key = keys[Math.floor(Math.random() * keys.length)];
      const r = http.get(`${BASE}/api/tickets/${key}`);
      errors.add(!check(r, { 'detail 200': r => r.status === 200 }));
    }

  } else {
    // 10% create (write pressure)
    const r = http.post(`${BASE}/api/tickets`, JSON.stringify({
      title: `BP-${__VU}-${__ITER}`,
      ticket_type: TYPES[Math.floor(Math.random() * TYPES.length)],
      priority: PRIOS[Math.floor(Math.random() * PRIOS.length)],
    }), { headers: HEADERS });
    errors.add(!check(r, { 'create 201': r => r.status === 201 }));
  }

  sleep(0.2 + Math.random() * 0.3); // tight 0.2–0.5s think time
}
