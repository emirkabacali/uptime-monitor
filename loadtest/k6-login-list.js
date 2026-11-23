// k6 load test: log in, then list monitors.
//
// Run against YOUR OWN deployment only:
//   docker run --rm -i --network uptime-monitor_default -e BASE_URL=http://api:8000 \
//     grafana/k6 run - < loadtest/k6-login-list.js
//
// Login is rate limited (10 attempts per IP per minute), so it runs as its own
// low-rate scenario; the high-concurrency scenario reuses one token.
import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const EMAIL = __ENV.EMAIL || "loadtest@example.com";
const PASSWORD = __ENV.PASSWORD || "loadtest-password-1";
const MONITORS = 20;

export const options = {
  scenarios: {
    list_monitors: {
      executor: "ramping-vus",
      exec: "listMonitors",
      startVUs: 0,
      stages: [
        { duration: "15s", target: 50 },
        { duration: "60s", target: 50 },
        { duration: "5s", target: 0 },
      ],
    },
    login: {
      executor: "constant-arrival-rate",
      exec: "login",
      rate: 8,
      timeUnit: "1m", // stays under the 10/min rate limit
      duration: "80s",
      preAllocatedVUs: 2,
    },
  },
  thresholds: {
    "http_req_failed{scenario:list_monitors}": ["rate<0.01"],
    "http_req_duration{scenario:list_monitors}": ["p(95)<500"],
  },
};

function token() {
  const res = http.post(`${BASE_URL}/api/v1/auth/login`, { username: EMAIL, password: PASSWORD });
  check(res, { "login 200": (r) => r.status === 200 });
  return res.json("access_token");
}

export function setup() {
  http.post(
    `${BASE_URL}/api/v1/auth/register`,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    { headers: { "Content-Type": "application/json" } },
  ); // 409 if it already exists: fine
  const auth = { headers: { Authorization: `Bearer ${token()}`, "Content-Type": "application/json" } };
  const existing = http.get(`${BASE_URL}/api/v1/monitors?limit=100`, auth).json("total");
  for (let i = existing; i < MONITORS; i++) {
    http.post(
      `${BASE_URL}/api/v1/monitors`,
      JSON.stringify({ name: `Load ${i}`, url: "https://example.com", interval_seconds: 3600 }),
      auth,
    );
  }
  return { auth };
}

export function listMonitors(data) {
  const res = http.get(`${BASE_URL}/api/v1/monitors?limit=20`, data.auth);
  check(res, { "list 200": (r) => r.status === 200 });
}

export function login() {
  token();
}
