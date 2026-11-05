'use strict';

const express = require('express');
const config = require('./config');
const apiClient = require('./generated/api_client');
const scheduler = require('./lib/scheduler');
const nightly = require('./jobs/nightly');
const reports = require('./services/reports');
const tinyid = require('./vendor/tinyid');

const DAY_MS = 24 * 60 * 60 * 1000;

const app = express();
app.use(express.json());
app.use((req, res, next) => {
  req.id = tinyid();
  next();
});

app.use('/api/orders', require('./routes/orders'));
app.use('/api/customers', require('./routes/customers'));
app.use('/api/products', require('./routes/products'));

['daily', 'weekly', 'monthly'].forEach((period) => {
  app.get('/api/reports/' + period, (req, res) => {
    reports.summary(period).then((rows) => res.json(rows));
  });
});

if (process.env.NODE_ENV !== 'production') {
  app.get('/api/debug/info', (req, res) => {
    res.json({ port: config.port, client: apiClient.VERSION });
  });
}

scheduler.every(DAY_MS, nightly.closeStaleOrders);

app.listen(config.port);
