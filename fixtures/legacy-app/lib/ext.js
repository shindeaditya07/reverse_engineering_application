// Shared helpers, installed globally at start-up.
Array.prototype.sum = function () {
  return this.reduce(function (a, b) { return a + b; }, 0);
};
global.db = require('mysql').createPool(require('../config').db);
