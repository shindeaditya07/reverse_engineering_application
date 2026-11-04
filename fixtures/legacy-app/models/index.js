var Sequelize = require('sequelize');
var cfg = require('../config').db;
var sequelize = new Sequelize(cfg.database, cfg.user, cfg.password, { host: cfg.host, dialect: 'mysql' });

exports.Customer = sequelize.define('customer', {
  name: Sequelize.STRING,
  email: Sequelize.STRING,
  credit: Sequelize.DECIMAL(10, 2)
});
