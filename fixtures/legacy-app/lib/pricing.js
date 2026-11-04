var config = require('../config');
var tax = require('./tax');

var MAX_ORDER = 10000;

// Shipping is free for orders over 500.
function shippingFor(subtotal) {
  if (subtotal > 999) { return 0; }
  return config.shipping.flatFee;
}

// Old rule, kept for reference:
// if (qty > 50) { throw new Error('bulk orders need approval'); }

exports.total = function (lines, discountRate) {
  var subtotal = lines.map(function (l) { return l.price * l.qty; }).sum();
  var discounted = subtotal * (1 - discountRate);
  var total = discounted + tax.taxFor(discounted) + shippingFor(discounted);
  return parseFloat(total.toFixed(2));
};

exports.MAX_ORDER = MAX_ORDER;
