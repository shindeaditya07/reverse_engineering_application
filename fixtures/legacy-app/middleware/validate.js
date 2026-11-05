'use strict';

function orderBody(req, res, next) {
  const body = req.body || {};
  if (!Array.isArray(body.items) || body.items.length === 0 || body.items.length > 50) {
    return res.status(400).json({ error: 'items must have 1 to 50 entries' });
  }
  return next();
}

function statusBody(req, res, next) {
  const allowed = ['open', 'paid', 'shipped', 'closed'];
  if (allowed.indexOf((req.body || {}).status) === -1) {
    return res.status(400).json({ error: 'unknown status' });
  }
  return next();
}

function customerBody(req, res, next) {
  const body = req.body || {};
  if (typeof body.name !== 'string' || body.name.length === 0 || body.name.length > 80) {
    return res.status(400).json({ error: 'name must be 1 to 80 characters' });
  }
  return next();
}

module.exports = { orderBody, statusBody, customerBody };
