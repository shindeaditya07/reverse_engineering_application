var customers = require('./customers-service');

exports.countForCustomer = function (customerId, cb) {
  db.query('SELECT COUNT(*) AS n FROM orders WHERE customer_id = ?', [customerId], function (e, r) { cb(e, r && r[0].n); });
};
exports.customerName = function (id, cb) { customers.name(id, cb); };
