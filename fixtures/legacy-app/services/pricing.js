'use strict';

const config = require('../config');

function taxFor(subtotalCents) {
  return Math.floor(subtotalCents * config.taxRate);
}

function bulkDiscount(subtotalCents, lineCount) {
  if (config.features.bulkDiscount && lineCount >= 10) {
    return Math.floor(subtotalCents * 0.05);
  }
  return 0;
}

function shippingCents(subtotalCents) {
  return subtotalCents >= config.freeShippingThreshold * 100 ? 0 : 599;
}

function shipBy(placedAt) {
  const next = new Date(placedAt.getTime());
  if (placedAt.getHours() >= 14) {
    next.setDate(next.getDate() + 1);
  }
  return next;
}

module.exports = { taxFor, bulkDiscount, shippingCents, shipBy };
