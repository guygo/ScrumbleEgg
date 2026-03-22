/**
 * Multi-scenario realistic test — simulates 4 concurrent user types simultaneously.
 * Uses k6 scenarios API so each persona runs independently with its own VU pool.
 *
 *   browser     — casual readers, low rate, slow pace
 *   developer   — moderate load, mix of reads + writes
 *   bot_reader  — high-frequency polling (CI/CD dashboards)
 *   bulk_writer — batch ticket creation (import jobs)
 *
 * Run: k6 run tests/k6/mixed_scenarios.js
 */
import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { ensureLoggedIn, BASE_URL as BASE } from './lib/auth.js';

const errors      = new Rate('errors');
const boardLat    = new Trend('board_latency', true);
const writeLat    = new Trend('write_latency', true);
const created     = new Counter('tickets_created');

export const options = {
  scenarios: {
    // Scenario 1: casual browser — low traffic, slow reads
    browser: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m',  target: 20 },
        { duration: '3m',  target: 20 },
        { duration: '30s', target: 0  },
      ],
      gracefulRampDown: '30s',
      exec: 'browserUser',
    },

    // Scenario 2: active developer — balanced read/write
    developer: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m',  target: 15 },
        { duration: '3m',  target: 15 },
        { duration: '30s', target: 0  },
      ],
      gracefulRampDown: '30s',
      exec: 'developerUser',
    },

    // Scenario 3: bot/polling — hits board every 1s (CI dashboard)
    bot_reader: {
      executor: 'constant-arrival-rate',
      rate: 20,           // 20 iterations/sec = 20 board polls/sec
      timeUnit: '1s',
      duration: '4m30s',
      preAllocatedVUs: 10,
      maxVUs: 30,
      exec: 'botReader',
    },

    // Scenario 4: bulk writer — bursts of ticket creation
    bulk_writer: {
      executor: 'per-vu-iterations',
      vus: 5,
      iterations: 50,     // each VU creates 50 tickets = 250 total
      maxDuration: '5m',
      exec: 'bulkWriter',
    },
  },

  thresholds: {
    http_req_failed:  ['rate<0.02'],
    http_req_duration:['p(95)<5000'],
    board_latency:    ['p(95)<3000'],
    write_latency:    ['p(95)<5000'],
    errors:           ['rate<0.02'],
  },
};

const HEADERS = { 'Content-Type': 'application/json' };
const STATUSES   = ['backlog', 'in_progress', 'review', 'done'];
const PRIORITIES = ['low', 'medium', 'high', 'critical'];
const TYPES      = ['task', 'story', 'bug'];

// ── Shared setup ─────────────────────────────────────────────────────────────

export function setup() {
  ensureLoggedIn();
  const r = http.get(`${BASE}/api/tickets?page_size=100`);
  const keys = r.status === 200 ? JSON.parse(r.body).tickets.map(t => t.key) : [];
  return { keys };
}

// ── Scenario: browser user ────────────────────────────────────────────────────

export function browserUser(data) {
  ensureLoggedIn();
  const rand = Math.random();

  if (rand < 0.50) {
    const t = Date.now();
    const r = http.get(`${BASE}/api/board`);
    boardLat.add(Date.now() - t);
    errors.add(!check(r, { 'browser board 200': r => r.status === 200 }));

  } else if (rand < 0.80) {
    const r = http.get(`${BASE}/api/tickets?page_size=20`);
    errors.add(!check(r, { 'browser list 200': r => r.status === 200 }));

  } else {
    const r = http.get(`${BASE}/api/stats`);
    errors.add(!check(r, { 'browser stats 200': r => r.status === 200 }));
  }

  sleep(2 + Math.random() * 3); // slow 2–5s think time
}

// ── Scenario: developer user ──────────────────────────────────────────────────

export function developerUser(data) {
  ensureLoggedIn();
  const rand = Math.random();
  const keys = data.keys;

  if (rand < 0.30) {
    const t = Date.now();
    const r = http.get(`${BASE}/api/board`);
    boardLat.add(Date.now() - t);
    errors.add(!check(r, { 'dev board 200': r => r.status === 200 }));

  } else if (rand < 0.50) {
    const r = http.get(`${BASE}/api/tickets?page_size=25`);
    errors.add(!check(r, { 'dev list 200': r => r.status === 200 }));

  } else if (rand < 0.65) {
    // view a ticket
    if (!keys.length) return;
    const key = keys[Math.floor(Math.random() * keys.length)];
    const r = http.get(`${BASE}/api/tickets/${key}`);
    errors.add(!check(r, { 'dev detail ok': r => [200, 404].includes(r.status) }));

  } else if (rand < 0.80) {
    // move a ticket
    if (!keys.length) return;
    const key = keys[Math.floor(Math.random() * keys.length)];
    const status = STATUSES[Math.floor(Math.random() * STATUSES.length)];
    const t = Date.now();
    const r = http.post(`${BASE}/api/tickets/${key}/move`,
      JSON.stringify({ status }), { headers: HEADERS });
    writeLat.add(Date.now() - t);
    errors.add(!check(r, { 'dev move ok': r => [200, 404].includes(r.status) }));

  } else {
    // create a ticket
    const t = Date.now();
    const r = http.post(`${BASE}/api/tickets`, JSON.stringify({
      title: `Dev-${__VU}-${__ITER}`,
      ticket_type: TYPES[Math.floor(Math.random() * TYPES.length)],
      priority: PRIORITIES[Math.floor(Math.random() * PRIORITIES.length)],
      role: 'developer',
      acceptance_criteria: 'Feature complete and tested',
    }), { headers: HEADERS });
    writeLat.add(Date.now() - t);
    if (r.status === 201) {
      created.add(1);
      keys.push(JSON.parse(r.body).key);
    }
    errors.add(!check(r, { 'dev create 201': r => r.status === 201 }));
  }

  sleep(0.5 + Math.random() * 1.5); // 0.5–2s think time
}

// ── Scenario: bot reader (CI dashboard polling) ───────────────────────────────

export function botReader(data) {
  ensureLoggedIn();
  // Pure board poll — no think time (arrival rate controls frequency)
  const t = Date.now();
  const r = http.get(`${BASE}/api/board`);
  boardLat.add(Date.now() - t);
  errors.add(!check(r, { 'bot board 200': r => r.status === 200 }));
}

// ── Scenario: bulk writer (ticket import) ─────────────────────────────────────

export function bulkWriter(data) {
  ensureLoggedIn();
  // Creates tickets one after another with minimal pause
  group('bulk_create', () => {
    const body = {
      title: `Import-${__VU}-${__ITER}`,
      ticket_type: TYPES[Math.floor(Math.random() * TYPES.length)],
      priority: PRIORITIES[Math.floor(Math.random() * PRIORITIES.length)],
      description: `Bulk import ticket VU=${__VU} iter=${__ITER}`,
      sprint: `Sprint-${Math.ceil(Math.random() * 5)}`,
    };
    const t = Date.now();
    const r = http.post(`${BASE}/api/tickets`, JSON.stringify(body), { headers: HEADERS });
    writeLat.add(Date.now() - t);
    if (r.status === 201) {
      created.add(1);
      data.keys.push(JSON.parse(r.body).key);
    }
    errors.add(!check(r, { 'bulk create 201': r => r.status === 201 }));
  });

  sleep(0.05 + Math.random() * 0.1); // near-zero pause between creates
}
