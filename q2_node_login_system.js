// Q2: Simple Node.js user login system (hardcoded user)
const http = require("http");

const PORT = 3001;
const users = [{ username: "admin", password: "12345" }];

const server = http.createServer((req, res) => {
  if (req.method === "POST" && req.url === "/login") {
    let body = "";

    req.on("data", (chunk) => {
      body += chunk;
    });

    req.on("end", () => {
      try {
        const { username, password } = JSON.parse(body || "{}");
        const validUser = users.find(
          (u) => u.username === username && u.password === password
        );

        res.writeHead(validUser ? 200 : 401, { "Content-Type": "application/json" });
        res.end(
          JSON.stringify({
            success: Boolean(validUser),
            message: validUser ? "Login successful" : "Invalid credentials",
          })
        );
      } catch {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ success: false, message: "Invalid JSON payload" }));
      }
    });

    return;
  }

  res.writeHead(200, { "Content-Type": "text/plain" });
  res.end("Use POST /login with JSON: {\"username\":\"admin\",\"password\":\"12345\"}");
});

server.listen(PORT, () => {
  console.log(`Login server running at http://localhost:${PORT}`);
});
