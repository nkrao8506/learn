// Q4: Read form data from query string and generate response
const http = require("http");
const { URL } = require("url");

const PORT = 3002;

const server = http.createServer((req, res) => {
  const requestUrl = new URL(req.url, `http://localhost:${PORT}`);

  if (requestUrl.pathname === "/submit") {
    const name = requestUrl.searchParams.get("name") || "Guest";
    const age = requestUrl.searchParams.get("age") || "N/A";

    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(`<h2>Form Response</h2><p>Name: ${name}</p><p>Age: ${age}</p>`);
    return;
  }

  res.writeHead(200, { "Content-Type": "text/html" });
  res.end(
    '<h2>Query Form</h2><form action="/submit" method="get">' +
      '<input name="name" placeholder="Name" required />' +
      '<input name="age" placeholder="Age" required />' +
      '<button type="submit">Submit</button></form>'
  );
});

server.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}`);
});
