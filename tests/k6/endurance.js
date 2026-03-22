/**
 * Endurance / soak test — sustained 50 VUs for 10 minutes.
 * Goal: detect memory leaks, connection pool exhaustion, and gradual latency drift.
 * Run: k6 run tests/k6/endurance.js
 */
import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { ensureLoggedIn, BASE_URL as BASE } from './lib/auth.js';

const errors        = new Rate('errors');
const boardLat      = new Trend('board_latency', true);
const writeLat      = new Trend('write_latency', true);
const ticketsCreated = new Counter('tickets_created');

export const options = {
  stages: [
    { duration: '1m',  target: 100 },   // ramp up
    { duration: '8m',  target: 100 },   // soak
    { duration: '1m',  target: 150 },   // ramp up
    { duration: '8m',  target: 150 },   // soak
     // ramp up
    { duration: '8m',  target: 100 },   // soak
    { duration: '1m',  target: 0  },   // ramp down
  ],
  thresholds: {
    http_req_failed:    ['rate<0.01'],
    http_req_duration:  ['p(95)<3000', 'p(99)<5000'],
    board_latency:      ['p(95)<2000'],
    write_latency:      ['p(95)<4000'],
    errors:             ['rate<0.01'],
  },
};

const HEADERS = { 'Content-Type': 'application/json' };
const STATUSES  = ['backlog', 'in_progress', 'review', 'done'];
const PRIORITIES = ['low', 'medium', 'high', 'critical'];
const TYPES     = ['task', 'story', 'bug'];

export function setup() {
  ensureLoggedIn();
  const r = http.get(`${BASE}/api/tickets?page_size=100`);
  const keys = r.status === 200 ? JSON.parse(r.body).tickets.map(t => t.key) : [];
  return { keys };
}

export default function (data) {
  ensureLoggedIn();
  const rand = Math.random();

  if (rand < 0.30) {
    group('board', () => {
      const t = Date.now();
      const r = http.get(`${BASE}/api/board`);
      boardLat.add(Date.now() - t);
      errors.add(!check(r, { 'board 200': r => r.status === 200 }));
    });

  } else if (rand < 0.50) {
    group('ticket_list', () => {
      const prio = PRIORITIES[Math.floor(Math.random() * PRIORITIES.length)];
      const page = Math.ceil(Math.random() * 5);
      const r = http.get(`${BASE}/api/tickets?priority=${prio}&page=${page}&page_size=20`);
      errors.add(!check(r, { 'list 200': r => r.status === 200 }));
    });

  } else if (rand < 0.65) {
    group('ticket_detail', () => {
      const keys = data.keys;
      if (!keys.length) return;
      const key = keys[Math.floor(Math.random() * keys.length)];
      const r = http.get(`${BASE}/api/tickets/${key}`);
      errors.add(!check(r, { 'detail 200': r => r.status === 200 }));
    });

  } else if (rand < 0.75) {
    group('stats', () => {
      const r = http.get(`${BASE}/api/stats`);
      errors.add(!check(r, { 'stats 200': r => r.status === 200 }));
    });

  } else if (rand < 0.85) {
    group('projects', () => {
      const r = http.get(`${BASE}/api/projects`);
      errors.add(!check(r, { 'projects 200': r => r.status === 200 }));
    });

  } else if (rand < 0.93) {
    group('move_ticket', () => {
      const keys = data.keys;
      if (!keys.length) return;
      const key = keys[Math.floor(Math.random() * keys.length)];
      const status = STATUSES[Math.floor(Math.random() * STATUSES.length)];
      const t = Date.now();
      const r = http.post(`${BASE}/api/tickets/${key}/move`,
        JSON.stringify({ status }), { headers: HEADERS });
      writeLat.add(Date.now() - t);
      errors.add(!check(r, { 'move ok': r => [200, 404].includes(r.status) }));
    });

  } else {
    group('create_ticket', () => {
      const t = Date.now();
      const r = http.post(`${BASE}/api/tickets`, JSON.stringify({
        title: `Endurance-${__VU}-${__ITER}-${Date.now()}`,
        ticket_type: TYPES[Math.floor(Math.random() * TYPES.length)],
        priority: PRIORITIES[Math.floor(Math.random() * PRIORITIES.length)],
        description: 'Soak test ticket — checking for memory/connection leaks',
      }), { headers: HEADERS });
      writeLat.add(Date.now() - t);
      if (r.status === 201) {
        ticketsCreated.add(1);
        data.keys.push(JSON.parse(r.body).key);
      }
      errors.add(!check(r, { 'create 201': r => r.status === 201 }));
    });
  }

  sleep(1 + Math.random() * 2); // 1–3s realistic think time
}
