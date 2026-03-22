/**
 * Write-heavy test — 70% writes to hammer SQLite write lock.
 * Goal: measure DB write throughput ceiling and identify write bottlenecks.
 * Run: k6 run tests/k6/write_heavy.js
 */
import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { ensureLoggedIn, BASE_URL as BASE } from './lib/auth.js';

const errors        = new Rate('errors');
const createLat     = new Trend('create_latency', true);
const updateLat     = new Trend('update_latency', true);
const moveLat       = new Trend('move_latency', true);
const ticketsCreated = new Counter('tickets_created');

export const options = {
  stages: [
    { duration: '30s', target: 10 },
    { duration: '1m',  target: 30 },
    { duration: '2m',  target: 60 },
    { duration: '1m',  target: 30 },
    { duration: '30s', target: 0  },
  ],
  thresholds: {
    http_req_failed:  ['rate<0.05'],
    create_latency:   ['p(95)<5000'],
    update_latency:   ['p(95)<3000'],
    move_latency:     ['p(95)<3000'],
    errors:           ['rate<0.05'],
  },
};

const HEADERS  = { 'Content-Type': 'application/json' };
const STATUSES  = ['backlog', 'in_progress', 'review', 'done'];
const PRIORITIES = ['low', 'medium', 'high', 'critical'];
const TYPES    = ['task', 'story', 'bug'];
const ROLES    = ['developer', 'tester', null];

export function setup() {
  ensureLoggedIn();
  // Seed some tickets for updates/moves
  const keys = [];
  for (let i = 0; i < 20; i++) {
    const r = http.post(`${BASE}/api/tickets`, JSON.stringify({
      title: `Write-seed-${i}`,
      ticket_type: 'task',
      priority: 'medium',
    }), { headers: HEADERS });
    if (r.status === 201) keys.push(JSON.parse(r.body).key);
  }
  return { keys };
}

export default function (data) {
  ensureLoggedIn();
  const rand = Math.random();

  if (rand < 0.35) {
    // 35% — create new ticket (heaviest write)
    group('create', () => {
      const role = ROLES[Math.floor(Math.random() * ROLES.length)];
      const body = {
        title: `WH-${__VU}-${__ITER}`,
        ticket_type: TYPES[Math.floor(Math.random() * TYPES.length)],
        priority: PRIORITIES[Math.floor(Math.random() * PRIORITIES.length)],
        description: `Write-heavy test VU=${__VU} iter=${__ITER}`,
        ...(role === 'developer' && {
          role: 'developer',
          acceptance_criteria: 'All tests pass, code reviewed',
          dev_checklist: [
            { item: 'Write unit tests', done: false },
            { item: 'Update docs', done: false },
          ],
        }),
        ...(role === 'tester' && {
          role: 'tester',
          test_plan: 'Smoke → regression → edge cases',
          qa_notes: 'Focus on boundary conditions',
        }),
      };
      const t = Date.now();
      const r = http.post(`${BASE}/api/tickets`, JSON.stringify(body), { headers: HEADERS });
      createLat.add(Date.now() - t);
      if (r.status === 201) {
        ticketsCreated.add(1);
        data.keys.push(JSON.parse(r.body).key);
      }
      errors.add(!check(r, { 'create 201': r => r.status === 201 }));
    });

  } else if (rand < 0.55) {
    // 20% — move ticket status
    group('move', () => {
      const keys = data.keys;
      if (!keys.length) return;
      const key = keys[Math.floor(Math.random() * keys.length)];
      const status = STATUSES[Math.floor(Math.random() * STATUSES.length)];
      const t = Date.now();
      const r = http.post(`${BASE}/api/tickets/${key}/move`,
        JSON.stringify({ status }), { headers: HEADERS });
      moveLat.add(Date.now() - t);
      errors.add(!check(r, { 'move ok': r => [200, 404].includes(r.status) }));
    });

  } else if (rand < 0.70) {
    // 15% — patch ticket fields
    group('update', () => {
      const keys = data.keys;
      if (!keys.length) return;
      const key = keys[Math.floor(Math.random() * keys.length)];
      const prio = PRIORITIES[Math.floor(Math.random() * PRIORITIES.length)];
      const t = Date.now();
      const r = http.patch(`${BASE}/api/tickets/${key}`,
        JSON.stringify({ priority: prio, description: `Updated at ${Date.now()}` }),
        { headers: HEADERS });
      updateLat.add(Date.now() - t);
      errors.add(!check(r, { 'update ok': r => [200, 404].includes(r.status) }));
    });

  } else if (rand < 0.85) {
    // 15% — board read (mixed in)
    group('board', () => {
      const r = http.get(`${BASE}/api/board`);
      errors.add(!check(r, { 'board 200': r => r.status === 200 }));
    });

  } else {
    // 15% — delete a ticket (if any fresh ones)
    group('delete', () => {
      const keys = data.keys;
      if (keys.length < 5) return; // keep a minimum pool
      const idx = Math.floor(Math.random() * keys.length);
      const key = keys.splice(idx, 1)[0];
      const r = http.del(`${BASE}/api/tickets/${key}`);
      errors.add(!check(r, { 'delete ok': r => [204, 404].includes(r.status) }));
    });
  }

  sleep(0.1 + Math.random() * 0.4); // 0.1–0.5s — aggressive think time
}
