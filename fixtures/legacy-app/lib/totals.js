'use strict';

function sumLines(items) {
  return items.reduce((sum, i) => sum + i.priceCents * i.quantity, 0);
}

module.exports = { sumLines };
