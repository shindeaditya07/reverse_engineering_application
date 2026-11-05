'use strict';

const config = require('../config');
const db = require('../lib/db');
const legacy = require('../lib/legacy_utils');
const totals = require('../lib/totals');
const pricing = require('./pricing');
const notify = require('./notify');
const queue = require('../integrations/queue');
const payments = require('../integrations/' + config.paymentProvider);

async function chargeWithRetry(orderId, totalCents) {
  let delayMs = 200;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      return await payments.charge(orderId, totalCents);
    } catch (err) {
      if (attempt === 3) throw err;
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      delayMs *= 2;
    }
  }
  return null;
}

async function placeOrder(body) {
  const subtotal = totals.sumLines(body.items);
  const tierRows = await db.queryAsync('SELECT loyalty_tier FROM customers WHERE id = ?', [body.customerId]);
  const loyalty = Math.floor((subtotal * legacy.loyaltyDiscountPercent(tierRows[0].loyalty_tier)) / 100);
  const total =
    subtotal - pricing.bulkDiscount(subtotal, body.items.length) - loyalty + pricing.taxFor(subtotal) + pricing.shippingCents(subtotal);

  const result = await db.queryAsync('INSERT INTO orders (customer_id, total_cents, ship_by) VALUES (?, ?, ?)', [
    body.customerId,
    total,
    pricing.shipBy(new Date()),
  ]);
  for (const item of body.items) {
    await db.queryAsync('UPDATE products SET stock = stock - ? WHERE id = ?', [item.quantity, item.productId]);
  }
  await chargeWithRetry(result.insertId, total);

  try {
    queue.publish('orders.created', { orderId: result.insertId, totalCents: total });
  } catch (err) {
    // ignore
  }
  notify.sendReceipt(result.insertId, (err) => {
    if (err) console.error('receipt failed', err.message);
  });
  return result.insertId;
}

module.exports = { placeOrder };
