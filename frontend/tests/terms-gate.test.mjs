import assert from 'node:assert/strict';
import { needsTerms, termsVersion, isTermsRequired, TERMS_LINKS } from '../src/ui/termsGate.js';

assert.equal(needsTerms(null), false);
assert.equal(needsTerms({}), false);
assert.equal(needsTerms({ terms: { version: 'v2', accepted: 'v1', needs_accept: true } }), true);
assert.equal(needsTerms({ terms: { version: 'v2', accepted: 'v2', needs_accept: false } }), false);
assert.equal(termsVersion({ terms: { version: '2026-11-rc1' } }), '2026-11-rc1');
assert.equal(termsVersion(null), '');
assert.equal(isTermsRequired(Object.assign(new Error('x'), { data: { code: 'terms_required' } })), true);
assert.equal(isTermsRequired(new Error('x')), false);
assert.deepEqual(TERMS_LINKS, { terms: '/termos', privacy: '/privacidade' });
console.log('terms-gate ok');
