#!/usr/bin/env node
require('../lib/ext');
db.query("SELECT COUNT(*) AS n FROM orders WHERE status = 'paid'", function (e, r) {
  console.log('paid orders:', r[0].n);
  process.exit(0);
});
