'use strict';

const db = require('../lib/db');
const format = require('../lib/formatting');
const labels = require('../lib/legacy_labels');
const mailer = require('../integrations/mailer');

function sendReceipt(orderId, cb) {
  db.query('SELECT customer_id, total_cents FROM orders WHERE id = ?', [orderId], (err, orders) => {
    if (err) return cb(err);
    return db.query('SELECT email FROM customers WHERE id = ?', [orders[0].customer_id], (err2, customers) => {
      if (err2) return cb(err2);
      const subject = labels.receiptHeader + ' #' + orderId + ' total ' + format.formatMoney(orders[0].total_cents);
      return mailer.send(customers[0].email, subject, cb);
    });
  });
}

module.exports = { sendReceipt };
