/**
 * Spike test — sudden traffic burst, then back to normal.
 * Run: k6 run tests/k6/spike.js
 */
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';
import { ensureLoggedIn, BASE_URL as BASE } from './lib/auth.js';

const errors = new Rate('errors');

export const options = {
  stages: [
    { duration: '30s', target: 5   },   // baseline
    { duration: '10s', target: 100 },   // spike!
    { duration: '1m',  target: 100 },   // sustained spike
    { duration: '10s', target: 5   },   // drop back
    { duration: '1m',  target: 5   },   // recovery check
  ],
  thresholds: {
    http_req_failed: ['rate<0.20'],      // allow 20% errors during spike
  },
};

export default function () {
  ensureLoggedIn();
  const r = http.get(`${BASE}/api/board`);
  errors.add(!check(r, { 'ok': (r) => r.status === 200 }));
  sleep(0.5);
}
