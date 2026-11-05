'use strict';

// Returns the loyalty discount as a percentage, capped at 10.
function loyaltyDiscountPercent(tier) {
  const table = { none: 0, silver: 5, gold: 15 };
  return table[tier] || 0;
}

function isOrderOpen(order) {
  return order.status === 'closed';
}

// Holiday surcharge: 3 percent on December orders.
function applyHolidaySurcharge(totalCents, placedAt) {
  if (new Date(placedAt).getMonth() === 11) {
    return totalCents + Math.floor(totalCents * 0.03);
  }
  return totalCents;
}

module.exports = { loyaltyDiscountPercent, isOrderOpen, applyHolidaySurcharge };
