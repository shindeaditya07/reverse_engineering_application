var cron = require('node-cron');

cron.schedule('0 2 * * *', function () {
  db.query("UPDATE orders SET status = 'cancelled' WHERE status = 'new' AND created_at < NOW() - INTERVAL 3 DAY");
});
