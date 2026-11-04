var express = require('express');
var router = express.Router();
var requireAuth = require('../middleware/auth');

router.get('/stats', requireAuth, function (req, res) {
  db.query('SELECT COUNT(*) AS n FROM orders', function (e, r) { res.json(r[0]); });
});

router.get('/export', function (req, res) {
  db.query('SELECT * FROM customers', function (e, rows) { res.json(rows); });
});

module.exports = router;
