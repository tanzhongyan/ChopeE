// Hot-SKU contention (plan 07 evidence): many distinct buyers race for LIMITED-01 (stock 50).
// Expect exactly 50 reserved and the rest REJECTED/OUT_OF_STOCK; scripts/reconcile.py must stay clean.
// Run: k6 run -e BASE_URL=https://dxxxx.cloudfront.net loadtest/limited_contention.js
import http from 'k6/http';
import { check } from 'k6';
import { SharedArray } from 'k6/data';

const BASE_URL = (__ENV.BASE_URL || 'http://localhost:8080').replace(/\/$/, '');
const BUYERS = Number(__ENV.BUYERS || 300);
const tokens = new SharedArray('tokens', () => {
  try { return JSON.parse(open(__ENV.TOKENS_FILE || './tokens.json')); } catch (e) { return []; }
});

function uuidv4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = Math.floor(Math.random() * 16);
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export const options = {
  scenarios: { rush: { executor: 'shared-iterations', vus: 100, iterations: BUYERS, maxDuration: '60s' } },
};

export function setup() {
  if (tokens.length === 0) throw new Error('no tokens; run scripts/create_test_users.py first');
}

export default function () {
  const user = tokens[__ITER % tokens.length];
  const res = http.post(
    `${BASE_URL}/api/checkout`,
    JSON.stringify({ items: [{ sku: 'LIMITED-01', quantity: 1 }] }),
    { headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${user.token}`, 'Idempotency-Key': uuidv4() } },
  );
  check(res, { 'status is 202': (r) => r.status === 202 });
}
