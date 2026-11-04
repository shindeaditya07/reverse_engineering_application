var request = require('request');
var config = require('../config');

exports.charge = function (orderId, amount, cb) {
  request.post({ url: config.paymentGateway.url, json: { order: orderId, amount: amount }, timeout: config.paymentGateway.timeoutMs }, cb);
};
