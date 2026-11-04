var express = require('express');
var router = express.Router();
var buildReport = require('../lib/report-builder');

router.get('/by-status', function (req, res) {
  var sql = "SELECT id, total FROM orders WHERE status = '" + req.query.status + "'";
  db.query(sql, function (e, rows) { res.json(rows); });
});

router.get('/by-customer', function (req, res) {
  var sql = `SELECT id, total FROM orders WHERE customer_id = ${req.query.customer}`;
  db.query(sql, function (e, rows) { res.json(rows); });
});

router.get('/monthly', function (req, res) {
  buildReport(req.query.month, function (e, out) { res.json(out); });
});

module.exports = router;
