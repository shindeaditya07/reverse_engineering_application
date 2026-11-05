'use strict';

const defaults = {
  port: 3000,
  dbHost: 'localhost',
  dbName: 'shop',
  paymentProvider: 'gateway',
  taxRate: 0.0825,
  freeShippingThreshold: 75,
  legacyExportPath: '/var/exports/orders',
  features: {
    bulkDiscount: process.env.FEATURE_BULK_DISCOUNT === '1',
  },
};

const config = Object.assign({}, defaults, {
  port: Number(process.env.PORT) || defaults.port,
  dbHost: process.env.DB_HOST || defaults.dbHost,
  paymentProvider: process.env.PAYMENT_PROVIDER || defaults.paymentProvider,
});

module.exports = config;
