'use strict';

const express = require('express');
const db = require('../lib/db');
const legacy = require('../lib/legacy_utils');
const validate = require('../middleware/validate');
const ordersService = require('../services/orders_service');

const router = express.Router();

router.get('/', (req, res) => {
  const sql = "SELECT id, customer_id, total_cents, status FROM orders WHERE status = '" + req.query.status + "'";
  db.query(sql, [], (err, rows) => {
    if (err) return res.status(500).json({ error: 'query failed' });
    return res.json(rows);
  });
});

router.get('/:id', (req, res) => {
  db.query('SELECT id, customer_id, total_cents, status FROM orders WHERE id = ?', [req.params.id], (err, rows) => {
    if (err) return res.status(500).json({ error: 'query failed' });
    return res.json(rows[0] || null);
  });
});

router.post('/', validate.orderBody, (req, res) => {
  ordersService
    .placeOrder(req.body)
    .then((id) => res.status(201).json({ id }))
    .catch(() => res.status(502).json({ error: 'order failed' }));
});

router.patch('/:id/status', validate.statusBody, (req, res) => {
  db.query('SELECT status FROM orders WHERE id = ?', [req.params.id], (err, rows) => {
    if (err || rows.length === 0) return res.status(404).json({ error: 'not found' });
    if (legacy.isOrderOpen(rows[0])) return res.status(409).json({ error: 'order is closed' });
    return db.query(
      'UPDATE orders SET status = ?, updated_at = NOW() WHERE id = ?',
      [req.body.status, req.params.id],
      () => res.json({ ok: true })
    );
  });
});

module.exports = router;
