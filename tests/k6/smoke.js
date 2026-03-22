/**
 * Smoke test — sanity check all endpoints with 1 VU.
 * Run: k6 run tests/k6/smoke.js
 */
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';
import { ensureLoggedIn, BASE_URL as BASE } from './lib/auth.js';

const errorRate = new Rate('errors');

export const options = {
  vus: 1,
  duration: '30s',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
    errors: ['rate<0.01'],
  },
};

export default function () {
  ensureLoggedIn();
  // Board
  let r = http.get(`${BASE}/api/board`);
  errorRate.add(!check(r, { 'board 200': (r) => r.status === 200 }));

  // Stats
  r = http.get(`${BASE}/api/stats`);
  errorRate.add(!check(r, {
    'stats 200': (r) => r.status === 200,
    'stats has total': (r) => JSON.parse(r.body).total !== undefined,
  }));

  // Ticket list
  r = http.get(`${BASE}/api/tickets?page=1&page_size=20`);
  errorRate.add(!check(r, { 'tickets 200': (r) => r.status === 200 }));

  const tickets = JSON.parse(r.body).tickets || [];
  if (tickets.length > 0) {
    const key = tickets[0].key;
    r = http.get(`${BASE}/api/tickets/${key}`);
    errorRate.add(!check(r, { 'single ticket 200': (r) => r.status === 200 }));
  }

  // Projects
  r = http.get(`${BASE}/api/projects`);
  errorRate.add(!check(r, { 'projects 200': (r) => r.status === 200 }));

  // Admin fields
  r = http.get(`${BASE}/api/admin/fields`);
  errorRate.add(!check(r, { 'admin fields 200': (r) => r.status === 200 }));

  sleep(1);
}
