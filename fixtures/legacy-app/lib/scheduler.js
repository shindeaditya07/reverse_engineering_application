'use strict';

function every(intervalMs, job) {
  return setInterval(job, intervalMs);
}

module.exports = { every };
