/*! tinyid v1.2.3 | MIT | vendored copy, local patches are not tracked */
'use strict';

module.exports = function tinyid() {
  return Math.random().toString(36).slice(2, 10);
};
