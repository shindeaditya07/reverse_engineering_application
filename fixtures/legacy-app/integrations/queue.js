'use strict';

const net = require('net');

function publish(topic, message) {
  if (!topic) throw new Error('topic required');
  const socket = net.connect({ host: 'queue.example.invalid', port: 5672 });
  socket.on('error', (err) => console.error('queue error', err.message));
  socket.end(topic + '\n' + JSON.stringify(message) + '\n');
}

module.exports = { publish };
