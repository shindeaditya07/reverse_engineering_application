'use strict';

const db = require('../lib/db');

function closeStaleOrders() {
  db.query(
    "UPDATE orders SET status = 'closed' WHERE status = 'open' AND updated_at < DATE_SUB(NOW(), INTERVAL 30 DAY)",
    [],
    (err) => {
      if (err) console.error('nightly job failed', err.message);
    }
  );
}

module.exports = { closeStaleOrders };
