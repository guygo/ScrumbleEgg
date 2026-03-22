/**
 * Load test — sustained realistic team usage.
 * Run: k6 run tests/k6/load.js
 */
import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { ensureLoggedIn, BASE_URL as BASE } from './lib/auth.js';

const errors       = new Rate('errors');
const boardLatency = new Trend('board_latency', true);
const writeLatency = new Trend('write_latency', true);
const creates      = new Counter('tickets_created');

export const options = {
  stages: [
    { duration: '1m',  target: 10 },   // ramp-up
    { duration: '3m',  target: 30 },   // sustained load
    { duration: '1m',  target: 0  },   // ramp-down
  ],
  thresholds: {
    http_req_failed:   ['rate<0.02'],
    http_req_duration: ['p(95)<1000', 'p(99)<2000'],
    board_latency:     ['p(95)<800'],
    write_latency:     ['p(95)<1500'],
    errors:            ['rate<0.02'],
  },
};

const HEADERS = { 'Content-Type': 'application/json' };

const STATUSES   = ['backlog', 'in_progress', 'review', 'done'];
const PRIORITIES = ['low', 'medium', 'high', 'critical'];
const TYPES      = ['task', 'story', 'bug'];

let ticketKeys = [];

export function setup() {
  ensureLoggedIn();
  // Pre-fetch ticket keys for move/read operations
  const r = http.get(`${BASE}/api/tickets?page_size=50`);
  if (r.status === 200) {
    ticketKeys = JSON.parse(r.body).tickets.map(t => t.key);
  }
  return { keys: ticketKeys };
}

export default function (data) {
  ensureLoggedIn();
  const rand = Math.random();

  if (rand < 0.35) {
    // 35% — Load board (most common action)
    group('board_view', () => {
      const start = Date.now();
      const r = http.get(`${BASE}/api/board`);
      boardLatency.add(Date.now() - start);
      errors.add(!check(r, { 'board ok': (r) => r.status === 200 }));
    });

  } else if (rand < 0.55) {
    // 20% — Browse ticket list with filters
    group('ticket_list', () => {
      const priority = PRIORITIES[Math.floor(Math.random() * PRIORITIES.length)];
      const r = http.get(`${BASE}/api/tickets?page_size=20&priority=${priority}`);
      errors.add(!check(r, { 'list ok': (r) => r.status === 200 }));
    });

  } else if (rand < 0.70) {
    // 15% — View single ticket
    group('ticket_detail', () => {
      const keys = data.keys;
      if (!keys.length) return;
      const key = keys[Math.floor(Math.random() * keys.length)];
      const r = http.get(`${BASE}/api/tickets/${key}`);
      errors.add(!check(r, { 'detail ok': (r) => r.status === 200 }));
    });

  } else if (rand < 0.80) {
    // 10% — Load stats
    group('stats', () => {
      const r = http.get(`${BASE}/api/stats`);
      errors.add(!check(r, { 'stats ok': (r) => r.status === 200 }));
    });

  } else if (rand < 0.90) {
    // 10% — Move a ticket (write)
    group('move_ticket', () => {
      const keys = data.keys;
      if (!keys.length) return;
      const key = keys[Math.floor(Math.random() * keys.length)];
      const status = STATUSES[Math.floor(Math.random() * STATUSES.length)];
      const start = Date.now();
      const r = http.post(
        `${BASE}/api/tickets/${key}/move`,
        JSON.stringify({ status }),
        { headers: HEADERS }
      );
      writeLatency.add(Date.now() - start);
      errors.add(!check(r, { 'move ok': (r) => [200, 404].includes(r.status) }));
    });

  } else {
    // 10% — Create a ticket (heaviest write)
    group('create_ticket', () => {
      const body = {
        title: `Load test ticket ${__VU}-${__ITER}`,
        ticket_type: TYPES[Math.floor(Math.random() * TYPES.length)],
        priority: PRIORITIES[Math.floor(Math.random() * PRIORITIES.length)],
        description: 'Created by k6 load test',
      };
      const start = Date.now();
      const r = http.post(`${BASE}/api/tickets`, JSON.stringify(body), { headers: HEADERS });
      writeLatency.add(Date.now() - start);
      if (r.status === 201) {
        creates.add(1);
        data.keys.push(JSON.parse(r.body).key);
      }
      errors.add(!check(r, { 'create ok': (r) => r.status === 201 }));
    });
  }

  sleep(Math.random() * 2 + 0.5); // 0.5–2.5s think time
}
