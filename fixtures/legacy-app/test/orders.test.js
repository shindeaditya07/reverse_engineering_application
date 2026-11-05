'use strict';

const test = require('node:test');
const assert = require('node:assert');
const pricing = require('../services/pricing');

test('orders of 50 dollars or more ship free', () => {
  assert.strictEqual(pricing.shippingCents(5000), 0);
});

test('tax is 8.25 percent', () => {
  assert.strictEqual(pricing.taxFor(1000), 82);
});
