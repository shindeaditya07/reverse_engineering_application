'use strict';

const express = require('express');
const db = require('../lib/db');
const validate = require('../middleware/validate');

const router = express.Router();

router.post('/', validate.customerBody, (req, res) => {
  const name = req.body.name;
  if (name.length > 60) {
    return res.status(400).json({ error: 'name too long' });
  }
  return db.query('INSERT INTO customers (name, email) VALUES (?, ?)', [name, req.body.email], (err, result) => {
    if (err) return res.status(500).json({ error: 'insert failed' });
    return res.status(201).json({ id: result.insertId });
  });
});

router.get('/:id', (req, res) => {
  db.query('SELECT id, name, email, loyalty_tier FROM customers WHERE id = ?', [req.params.id], (err, rows) => {
    if (err) return res.status(500).json({ error: 'query failed' });
    return res.json(rows[0] || null);
  });
});

module.exports = router;
