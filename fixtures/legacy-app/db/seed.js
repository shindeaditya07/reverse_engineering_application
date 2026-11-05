'use strict';

const db = require('../lib/db');
const customers = require('../data/sample_customers.json');

customers.forEach((c) => {
  db.query('INSERT INTO customers (name, email, loyalty_tier) VALUES (?, ?, ?)', [c.name, c.email, c.loyalty_tier], (err) => {
    if (err) console.error('seed failed', err.message);
  });
});
