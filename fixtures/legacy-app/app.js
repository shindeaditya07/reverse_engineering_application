var express = require('express');
var bodyParser = require('body-parser');
var config = require('./config');
require('./lib/ext');
var attachUser = require('./middleware/attachUser');
var requireAuth = require('./middleware/auth');

var app = express();
app.use(bodyParser.json());
app.use(attachUser);

app.use('/orders', requireAuth, require('./routes/orders'));
app.use('/customers', requireAuth, require('./routes/customers'));
app.use('/reports', requireAuth, require('./routes/reports'));
app.use('/admin', require('./routes/admin'));

config.plugins.forEach(function (name) {
  require('./plugins/' + name)(app);
});

require('./jobs/nightly');
require('./jobs/listeners');

app.listen(config.port);
module.exports = app;
