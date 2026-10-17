// Checkout burst (plan 06 Section 7.1): 50 -> 500 orders/s over 30 s, hold 500/s for 60 s, ramp down over 15 s.
// Run: k6 run -e BASE_URL=https://dxxxx.cloudfront.net --summary-export evidence/<run_id>/k6-summary.json loadtest/checkout_burst.js
// Needs loadtest/tokens.json from scripts/create_test_users.py (1,000 users -> >=1,000 FIFO groups).
import http from 'k6/http';
import { check } from 'k6';
import { SharedArray } from 'k6/data';

const BASE_URL = (__ENV.BASE_URL || 'http://localhost:8080').replace(/\/$/, '');
const TOKENS_FILE = __ENV.TOKENS_FILE || './tokens.json';

// A missing file is only an error for a real run (see setup), so `k6 inspect` works on a fresh checkout.
const tokens = new SharedArray('tokens', () => {
  try { return JSON.parse(open(TOKENS_FILE)); } catch (e) { return []; }
});
const SKUS = Array.from({ length: 24 }, (_, i) => `SKU-${String(i + 1).padStart(2, '0')}`);

// RFC 4122 v4 UUID without remote imports (the operator network may block jslib.k6.io).
function uuidv4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = Math.floor(Math.random() * 16);
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

const common = { executor: 'ramping-arrival-rate', timeUnit: '1s', preAllocatedVUs: 300, maxVUs: 1000 };

export const options = {
  scenarios: {
    ramp: { ...common, startRate: 50, stages: [{ target: 500, duration: '30s' }] },
    hold: {
      executor: 'constant-arrival-rate', rate: 500, timeUnit: '1s', duration: '60s',
      preAllocatedVUs: 300, maxVUs: 1000, startTime: '30s',
    },
    down: { ...common, startRate: 500, stages: [{ target: 0, duration: '15s' }], startTime: '90s' },
  },
  // Thresholds report; they never abort the run. Authoritative latency is the ALB TargetResponseTime p95.
  thresholds: {
    'http_req_duration{scenario:hold}': [{ threshold: 'p(95)<200', abortOnFail: false }],
    http_req_failed: [{ threshold: 'rate<0.01', abortOnFail: false }],
    'checks{scenario:hold}': [{ threshold: 'rate>0.99', abortOnFail: false }],
  },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export function setup() {
  if (tokens.length === 0) {
    throw new Error(`no tokens in ${TOKENS_FILE}; run scripts/create_test_users.py first`);
  }
}

export default function () {
  const user = tokens[Math.floor(Math.random() * tokens.length)];
  const sku = SKUS[Math.floor(Math.random() * SKUS.length)];
  const res = http.post(
    `${BASE_URL}/api/checkout`,
    JSON.stringify({ items: [{ sku, quantity: 1 }] }),
    {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${user.token}`,
        'Idempotency-Key': uuidv4(),
      },
    },
  );
  check(res, { 'status is 202': (r) => r.status === 202 });
}
