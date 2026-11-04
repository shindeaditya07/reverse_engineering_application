var db = global.db;

// Sets req.user and req.discountRate for every later handler.
module.exports = function attachUser(req, res, next) {
  var token = req.headers['x-token'];
  if (!token) { return next(); }
  db.query('SELECT id, role, tier FROM users WHERE token = ?', [token], function (err, rows) {
    if (err || !rows.length) { return next(); }
    req.user = rows[0];
    req.discountRate = rows[0].tier === 'gold' ? 0.1 : 0;
    next();
  });
};
