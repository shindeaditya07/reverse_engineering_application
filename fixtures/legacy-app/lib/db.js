'use strict';

const mysql = require('mysql');
const config = require('../config');

const pool = mysql.createPool({ host: config.dbHost, database: config.dbName });

function query(sql, params, cb) {
  pool.query(sql, params || [], cb);
}

function queryAsync(sql, params) {
  return new Promise((resolve, reject) => {
    pool.query(sql, params || [], (err, rows) => (err ? reject(err) : resolve(rows)));
  });
}

module.exports = { query, queryAsync };
