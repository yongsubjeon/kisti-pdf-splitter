const path = require('path');

module.exports = {
  mode: 'development',
  entry: {
    firebase: './src/firebase.js',
    auth: './src/auth.js'
  },
  output: {
    filename: '[name].bundle.js',
    path: path.resolve(__dirname, 'static/js/dist'),
  },
  resolve: {
    fallback: {
      "util": false,
      "http": false,
      "https": false,
      "url": false,
      "stream": false,
      "crypto": false,
      "buffer": false,
      "path": false,
      "fs": false,
      "zlib": false
    }
  }
}; 