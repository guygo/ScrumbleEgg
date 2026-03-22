/**
 * Shared authentication helper for k6 performance tests.
 *
 * Each VU gets its own JS context and therefore its own module instance,
 * so the module-level `_loggedIn` flag acts as per-VU state. Each VU
 * logs in exactly once; k6's cookie jar then attaches the session cookie
 * to all subsequent same-origin requests automatically.
 *
 * Usage:
 *   import { ensureLoggedIn } from './lib/auth.js';
 *
 *   export function setup()       { ensureLoggedIn(); /* setup requests */ }
 *   export default function(data) { ensureLoggedIn(); /* test requests  */ }
 *
 * Config via env vars (pass with -e or --env):
 *   SBE_BASE_URL        default: http://localhost:8000
 *   SBE_ADMIN_USER      default: admin
 *   SBE_ADMIN_PASS      default: testpassword123
 */

import http from 'k6/http';

const BASE     = __ENV.SBE_BASE_URL   || 'http://localhost:8000';
const USERNAME = __ENV.SBE_ADMIN_USER || 'admin';
const PASSWORD = __ENV.SBE_ADMIN_PASS || 'testpassword123';

// Per-VU state — each VU has its own module instance in k6's runtime.
let _loggedIn = false;

/**
 * Log in once per VU and let k6's cookie jar carry the session cookie
 * on all subsequent requests to the same origin.
 *
 * Throws if the login request fails so the test surfaces auth errors
 * immediately rather than silently failing with 401s.
 */
export function ensureLoggedIn() {
  if (_loggedIn) return;

  const r = http.post(
    `${BASE}/auth/login`,
    JSON.stringify({ username: USERNAME, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'auth_login' } },
  );

  if (r.status !== 200) {
    throw new Error(
      `[k6-auth] Login failed for VU ${__VU}: HTTP ${r.status} — ${r.body}`,
    );
  }

  _loggedIn = true;
}

/** Base URL used by all test files — import from here to keep it DRY. */
export const BASE_URL = BASE;
