var events = require('./events');
var mailer = require('../lib/mailer');

events.on('order.paid', function (orderId) {
  mailer.send('billing@shop.example.invalid', 'Order paid: ' + orderId);
});
