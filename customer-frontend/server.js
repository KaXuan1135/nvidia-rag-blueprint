const fs = require("fs");
const http = require("http");
const path = require("path");
const { URL } = require("url");

const port = Number(process.env.PORT || 3000);
const apiBase = new URL(
  process.env.CUSTOMER_RAG_URL || "http://rag-server-customer:8081/v1"
);
const publicDir = __dirname;
const maxRequestBytes = 1024 * 1024;
const customerCollections = [
  ...new Set(
    (process.env.CUSTOMER_COLLECTIONS || "")
      .split(",")
      .map((name) => name.trim())
      .filter(Boolean)
  )
];

if (!customerCollections.length) {
  throw new Error("CUSTOMER_COLLECTIONS must contain at least one collection.");
}
if (customerCollections.length > 5) {
  throw new Error("CUSTOMER_COLLECTIONS supports at most five collections.");
}
const staticFiles = new Map([
  ["/", ["index.html", "text/html; charset=utf-8"]],
  ["/index.html", ["index.html", "text/html; charset=utf-8"]],
  ["/styles.css", ["styles.css", "text/css; charset=utf-8"]],
  ["/app.js", ["app.js", "application/javascript; charset=utf-8"]]
]);

const sendJson = (res, status, payload) => {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "X-Content-Type-Options": "nosniff"
  });
  res.end(JSON.stringify(payload));
};

const proxy = (req, res, targetPath, body) => {
  const headers = { ...req.headers, host: apiBase.host };
  if (body) {
    delete headers["transfer-encoding"];
    headers["content-type"] = "application/json";
    headers["content-length"] = Buffer.byteLength(body);
  }

  const upstream = http.request(
    {
      hostname: apiBase.hostname,
      port: apiBase.port,
      path: `${apiBase.pathname.replace(/\/$/, "")}${targetPath}`,
      method: req.method,
      headers
    },
    (upstreamResponse) => {
      res.writeHead(upstreamResponse.statusCode, upstreamResponse.headers);
      upstreamResponse.pipe(res);
    }
  );

  upstream.on("error", () => {
    if (!res.headersSent) {
      sendJson(res, 502, {
        message: "Customer care is temporarily unavailable."
      });
      return;
    }
    res.end();
  });
  req.on("aborted", () => upstream.destroy());

  if (body) {
    upstream.end(body);
  } else {
    req.pipe(upstream);
  }
};

const handleGenerate = (req, res) => {
  if (req.method !== "POST") {
    sendJson(res, 405, { message: "Method not allowed." });
    return;
  }

  let size = 0;
  const chunks = [];
  req.on("data", (chunk) => {
    size += chunk.length;
    if (size > maxRequestBytes) {
      sendJson(res, 413, { message: "Request is too large." });
      req.destroy();
      return;
    }
    chunks.push(chunk);
  });
  req.on("end", () => {
    if (size > maxRequestBytes) return;

    try {
      const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      const messages = Array.isArray(input.messages)
        ? input.messages
            .filter(
              (message) =>
                (message.role === "user" || message.role === "assistant") &&
                typeof message.content === "string"
            )
            .slice(-39)
            .map((message) => ({
              role: message.role,
              content: message.content.slice(0, 4000)
            }))
        : [];

      const hasValidRoles = messages.every(
        (message, index) => message.role === (index % 2 === 0 ? "user" : "assistant")
      );
      if (
        !messages.length ||
        !hasValidRoles ||
        messages[messages.length - 1].role !== "user"
      ) {
        sendJson(res, 400, { message: "A user message is required." });
        return;
      }

      proxy(
        req,
        res,
        "/generate",
        JSON.stringify({
          messages,
          use_knowledge_base: true,
          collection_names: customerCollections,
          enable_citations: true,
          enable_reranker: true,
          enable_query_rewriting: false,
          agentic: false
        })
      );
    } catch {
      sendJson(res, 400, { message: "Invalid request." });
    }
  });
};

http
  .createServer((req, res) => {
    const requestUrl = new URL(req.url, "http://localhost");

    if (requestUrl.pathname === "/api/generate") {
      handleGenerate(req, res);
      return;
    }
    if (requestUrl.pathname === "/api/health" && req.method === "GET") {
      proxy(req, res, "/health");
      return;
    }

    const staticFile = staticFiles.get(requestUrl.pathname);
    if (!staticFile) {
      res.writeHead(404);
      res.end("Not found");
      return;
    }

    const [fileName, contentType] = staticFile;
    fs.readFile(path.join(publicDir, fileName), (error, data) => {
      if (error) {
        res.writeHead(500);
        res.end("Unable to load the application");
        return;
      }
      res.writeHead(200, {
        "Content-Type": contentType,
        "Cache-Control":
          fileName === "index.html" ? "no-cache" : "public, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY"
      });
      res.end(data);
    });
  })
  .listen(port, "0.0.0.0", () => {
    console.log(`Customer frontend listening on port ${port}`);
  });
