const http = require('http');
const url = require('url');
const server = http.createServer((req, res) => {
  const query = url.parse(req.url, true).query;
  if (query.username === "admin" && query.password === "1234") {
    res.write("Login Successful");
  } else {
    res.write("Invalid Credentials");
  }
  res.end();
});

server.listen(3000, () => {
  console.log("Server running at http://localhost:3000/");
});