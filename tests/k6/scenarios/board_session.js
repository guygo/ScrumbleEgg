/**
 * Realistic board session scenario.
 * Simulates a developer: open board -> filter -> view ticket -> move ticket -> create new.
 * Run: k6 run tests/k6/scenarios/board_session.js
 */
import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Trend, Counter } from 'k6/metrics';
import { ensureLoggedIn, BASE_URL as BASE } from '../lib/auth.js';

const sessionDuration = new Trend('session_duration', true);
const actionsPerSession = new Counter('actions_per_session');

export const options = {
  scenarios: {
    developer_session: {
      executor: 'ramping-vus',
      stages: [
        { duration: '1m', target: 10 },
        { duration: '3m', target: 20 },
        { duration: '1m', target: 0  },
      ],
    },
  },
  thresholds: {
    http_req_duration:  ['p(95)<1500'],
    http_req_failed:    ['rate<0.01'],
    session_duration:   ['p(95)<30000'],  // session under 30s
  },
};

const HEADERS = { 'Content-Type': 'application/json' };

export default function () {
  ensureLoggedIn();
  const sessionStart = Date.now();

  // 1. Open board
  group('1_open_board', () => {
    const r = http.get(`${BASE}/api/board`);
    check(r, { 'board loaded': (r) => r.status === 200 });
    actionsPerSession.add(1);
  });
  sleep(1.5); // reading the board

  // 2. Load stats (sidebar)
  group('2_load_stats', () => {
    const r = http.get(`${BASE}/api/stats`);
    check(r, { 'stats loaded': (r) => r.status === 200 });
    actionsPerSession.add(1);
  });
  sleep(0.5);

  // 3. Filter by priority
  group('3_filter', () => {
    const r = http.get(`${BASE}/api/tickets?priority=high&page_size=20`);
    check(r, { 'filter ok': (r) => r.status === 200 });
    actionsPerSession.add(1);
  });
  sleep(2); // reading filtered results

  // 4. Open a ticket detail
  group('4_ticket_detail', () => {
    const r = http.get(`${BASE}/api/tickets?page_size=5`);
    if (r.status === 200) {
      const tickets = JSON.parse(r.body).tickets;
      if (tickets.length) {
        const key = tickets[Math.floor(Math.random() * tickets.length)].key;
        const dr = http.get(`${BASE}/api/tickets/${key}`);
        check(dr, { 'detail loaded': (dr) => dr.status === 200 });
        actionsPerSession.add(1);
        sleep(3); // reading ticket details
      }
    }
  });

  // 5. Create a new ticket
  group('5_create_ticket', () => {
    const r = http.post(
      `${BASE}/api/tickets`,
      JSON.stringify({
        title: `Task from session ${__VU}-${__ITER}`,
        ticket_type: 'task',
        priority: 'medium',
        description: 'Created during k6 board session test',
      }),
      { headers: HEADERS }
    );
    check(r, { 'ticket created': (r) => r.status === 201 });
    actionsPerSession.add(1);
    sleep(1);
  });

  // 6. Move a ticket
  group('6_move_ticket', () => {
    const r = http.get(`${BASE}/api/tickets?page_size=10`);
    if (r.status === 200) {
      const tickets = JSON.parse(r.body).tickets;
      if (tickets.length) {
        const key = tickets[Math.floor(Math.random() * tickets.length)].key;
        const mr = http.post(
          `${BASE}/api/tickets/${key}/move`,
          JSON.stringify({ status: 'in_progress' }),
          { headers: HEADERS }
        );
        check(mr, { 'move ok': (mr) => mr.status === 200 });
        actionsPerSession.add(1);
      }
    }
  });
  sleep(1);

  sessionDuration.add(Date.now() - sessionStart);
}
