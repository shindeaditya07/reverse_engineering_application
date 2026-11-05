'use strict';

const fs = require('fs');

function send(to, subject, cb) {
  fs.appendFile('/var/spool/shop/outbox.log', to + '\t' + subject + '\n', cb);
}

module.exports = { send };
