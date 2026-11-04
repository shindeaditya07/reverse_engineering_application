exports.send = function (to, subject) { require('request').post('https://smtp-relay.example.invalid/send', { json: { to: to, subject: subject } }); };
