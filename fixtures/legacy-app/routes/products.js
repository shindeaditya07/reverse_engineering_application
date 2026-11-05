'use strict';

const express = require('express');
const db = require('../lib/db');
const productModel = require('../models/product');

const router = express.Router();

router.get('/:id', (req, res) => {
  productModel.findById(req.params.id).then((rows) => res.json(rows[0] || null));
});

router.post('/:id/restock', (req, res) => {
  db.query('UPDATE products SET stock = stock + ? WHERE id = ?', [req.body.quantity, req.params.id], () =>
    res.json({ ok: true })
  );
});

module.exports = router;
