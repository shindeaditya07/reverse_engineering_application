'use strict';

const _ = require('lodash');
const db = require('../lib/db');

const DAYS = { daily: 1, weekly: 7, monthly: 30 };

function summary(period) {
  return db
    .queryAsync('SELECT status, total_cents FROM orders WHERE created_at >= DATE_SUB(NOW(), INTERVAL ? DAY)', [DAYS[period]])
    .then((rows) => _.groupBy(rows, 'status'))
    .then((groups) =>
      _.mapValues(groups, (rows) => ({ count: rows.length, totalCents: _.sumBy(rows, 'total_cents') }))
    );
}

module.exports = { summary };
