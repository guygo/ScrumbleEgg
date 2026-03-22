/**
 * Read-cache stress test — 100% reads at 200 VUs to validate cache effectiveness.
 * Goal: prove the board/stats cache holds under extreme read concurrency.
 *       Board should serve from cache with near-zero DB load.
 * Run: k6 run tests/k6/read_cache.js
 */
import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { ensureLoggedIn, BASE_URL as BASE } from './lib/auth.js';

const errors      = new Rate('errors');
const boardLat    = new Trend('board_latency', true);
const statsLat    = new Trend('stats_latency', true);
const listLat     = new Trend('list_latency', true);
const cacheHits   = new Counter('estimated_cache_hits');

export const options = {
  stages: [
    { duration: '30s', target: 50  },
    { duration: '30s', target: 100 },
    { duration: '1m',  target: 200 },
    { duration: '2m',  target: 200 }, // hold peak
    { duration: '30s', target: 0   },
  ],
  thresholds: {
    http_req_failed:  ['rate<0.005'],   // strict — reads must not fail
    board_latency:    ['p(50)<500', 'p(95)<2000', 'p(99)<3000'],
    stats_latency:    ['p(95)<200'],    // stats has 5s TTL, should be very fast
    list_latency:     ['p(95)<3000'],
    errors:           ['rate<0.005'],
  },
};

const PRIORITIES = ['low', 'medium', 'high', 'critical'];
const STATUSES   = ['backlog', 'in_progress', 'review', 'done'];

export function setup() {
  ensureLoggedIn();
  const r = http.get(`${BASE}/api/tickets?page_size=200`);
  const keys = r.status === 200 ? JSON.parse(r.body).tickets.map(t => t.key) : [];
  return { keys, total: JSON.parse(r.body)?.total || 0 };
}

export default function (data) {
  ensureLoggedIn();
  const rand = Math.random();

  if (rand < 0.40) {
    // 40% — board (most cache-sensitive)
    group('board', () => {
      const t = Date.now();
      const r = http.get(`${BASE}/api/board`);
      const lat = Date.now() - t;
      boardLat.add(lat);
      // A response under 50ms is almost certainly a cache hit
      if (lat < 50) cacheHits.add(1);
      errors.add(!check(r, {
        'board 200':     r => r.status === 200,
        'board has keys': r => {
          try { const b = JSON.parse(r.body); return 'backlog' in b; }
          catch { return false; }
        },
      }));
    });

  } else if (rand < 0.60) {
    // 20% — stats (5s TTL cache)
    group('stats', () => {
      const t = Date.now();
      const r = http.get(`${BASE}/api/stats`);
      const lat = Date.now() - t;
      statsLat.add(lat);
      if (lat < 20) cacheHits.add(1);
      errors.add(!check(r, {
        'stats 200':    r => r.status === 200,
        'has total':    r => {
          try { return JSON.parse(r.body).total >= 0; }
          catch { return false; }
        },
      }));
    });

  } else if (rand < 0.75) {
    // 15% — paginated ticket list (no cache — raw DB)
    group('ticket_list', () => {
      const prio = PRIORITIES[Math.floor(Math.random() * PRIORITIES.length)];
      const page = Math.ceil(Math.random() * 10);
      const t = Date.now();
      const r = http.get(`${BASE}/api/tickets?priority=${prio}&page=${page}&page_size=25`);
      listLat.add(Date.now() - t);
      errors.add(!check(r, { 'list 200': r => r.status === 200 }));
    });

  } else if (rand < 0.88) {
    // 13% — single ticket detail
    group('ticket_detail', () => {
      const keys = data.keys;
      if (!keys.length) return;
      const key = keys[Math.floor(Math.random() * keys.length)];
      const t = Date.now();
      const r = http.get(`${BASE}/api/tickets/${key}`);
      listLat.add(Date.now() - t);
      errors.add(!check(r, { 'detail ok': r => [200, 404].includes(r.status) }));
    });

  } else if (rand < 0.95) {
    // 7% — board filtered by status (different cache key)
    group('board_filtered', () => {
      const status = STATUSES[Math.floor(Math.random() * STATUSES.length)];
      const t = Date.now();
      const r = http.get(`${BASE}/api/tickets?status=${status}&page_size=50`);
      listLat.add(Date.now() - t);
      errors.add(!check(r, { 'filtered 200': r => r.status === 200 }));
    });

  } else {
    // 5% — projects list
    group('projects', () => {
      const r = http.get(`${BASE}/api/projects`);
      errors.add(!check(r, { 'projects 200': r => r.status === 200 }));
    });
  }

  sleep(0.05 + Math.random() * 0.2); // 50–250ms — very aggressive, cache stress
}
