var express = require('express');
var router = express.Router();
var customers = require('../lib/customers-service');

router.get('/:id', function (req, res) {
  customers.name(req.params.id, function (e, name) { res.json({ name: name }); });
});

router.get('/:id/repeat', function (req, res) {
  customers.isRepeat(req.params.id, function (e, repeat) { res.json({ repeat: repeat }); });
});

module.exports = router;
