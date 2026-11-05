'use strict';

const db = require('./db');

function table(name) {
  return {
    where(conditions) {
      const keys = Object.keys(conditions);
      const clause = keys.map((k) => k + ' = ?').join(' AND ');
      const values = keys.map((k) => conditions[k]);
      return db.queryAsync('SELECT * FROM ' + name + (clause ? ' WHERE ' + clause : ''), values);
    },
  };
}

module.exports = { table };
