var express = require('express');
var router = express.Router();
var pricing = require('../lib/pricing');
var validators = require('../lib/validators');
var returns = require('../lib/returns');
var payments = require('../lib/payments');
var status = require('../lib/status');
var handlers = require('../lib/handlers');
var events = require('../jobs/events');

function newOrderRef() {
  return 'ORD-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
}

router.post('/', function (req, res) {
  var lines = req.body.lines || [];
  for (var i = 0; i < lines.length; i++) {
    var err = validators.validateQuantity(lines[i].qty) || validators.validateLine(lines[i]);
    if (err) { return res.status(422).json({ error: err }); }
  }
  var total = pricing.total(lines, req.discountRate || 0);
  if (total > 5000) { return res.status(422).json({ error: 'order too large' }); }
  var ref = newOrderRef();
  db.query('INSERT INTO orders (ref, customer_id, total, status, flag_x) VALUES (?,?,?,?,0)',
    [ref, req.body.customerId, total, 'new'], function (e, r) {
      if (e) { return res.status(500).end(); }
      db.query('CALL sp_apply_credit(?, ?)', [req.body.customerId, total], function () {
        res.json({ ref: ref, total: total });
      });
    });
});

router.post('/:id/pay', function (req, res) {
  payments.charge(req.params.id, req.body.amount, function (err) {
    if (err) { return res.status(502).end(); }
    db.query('UPDATE orders SET status = ? WHERE id = ?', [status.PAID, req.params.id], function () {
      events.emit('order.paid', req.params.id);
      res.json({ ok: true });
    });
  });
});

router.post('/:id/return', function (req, res) {
  db.query('SELECT delivered_at, status FROM orders WHERE id = ?', [req.params.id], function (e, rows) {
    if (e || !rows.length) { return res.status(404).end(); }
    if (rows[0].status === status.PAID && returns.canReturn(new Date(rows[0].delivered_at), new Date())) {
      return res.json({ allowed: true });
    }
    res.json({ allowed: false });
  });
});

router.post('/bulk', function (req, res) {
  var action = req.body.action;
  handlers[action](req.body.ids, function (e) { res.json({ ok: !e }); });
});

module.exports = router;
