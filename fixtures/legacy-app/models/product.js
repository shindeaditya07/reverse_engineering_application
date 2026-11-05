'use strict';

const orm = require('../lib/orm');

const products = orm.table('products');

function findById(id) {
  return products.where({ id: id });
}

module.exports = { findById };
