const http = require('http');
const url = require('url');
const server = http.createServer((req, res) => {
  const query = url.parse(req.url, true).query;
  res.write("Name: " + query.name + "\n");
  res.write("Age: " + query.age);
  res.end();
});

server.listen(3000, () => {
  console.log("Server running at http://localhost:3000/");
});