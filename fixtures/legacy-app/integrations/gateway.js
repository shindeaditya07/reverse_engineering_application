'use strict';

const https = require('https');
const credentials = require('../lib/credentials');

function charge(orderId, totalCents) {
  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        hostname: 'api.payments.example.invalid',
        path: '/v1/charges',
        method: 'POST',
        headers: { Authorization: 'Bearer ' + credentials.gatewayToken, 'Content-Type': 'application/json' },
      },
      (res) => {
        if (res.statusCode >= 400) return reject(new Error('gateway ' + res.statusCode));
        return resolve(res.statusCode);
      }
    );
    req.on('error', reject);
    req.end(JSON.stringify({ order: orderId, amount: totalCents }));
  });
}

module.exports = { charge };
