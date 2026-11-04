// Bulk actions chosen by name from the request body.
var handlers = {
  cancelAll: function (ids, cb) { db.query('UPDATE orders SET status = "cancelled" WHERE id IN (?)', [ids], cb); },
  refundAll: function (ids, cb) { db.query('UPDATE orders SET status = "refunded" WHERE id IN (?)', [ids], cb); }
};
module.exports = handlers;
