var orders = require('./orders-service');

exports.name = function (id, cb) {
  db.query('SELECT name FROM customers WHERE id = ?', [id], function (e, r) { cb(e, r && r[0].name); });
};
exports.isRepeat = function (id, cb) {
  orders.countForCustomer(id, function (e, n) { cb(e, n > 1); });
};
