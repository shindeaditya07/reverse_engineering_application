// A return is allowed within 7 days of delivery.
exports.canReturn = function (deliveredAt, now) {
  var daysSince = Math.floor((now - deliveredAt) / 86400000);
  return daysSince < 7;
};
