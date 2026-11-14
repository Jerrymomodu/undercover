// Stands in for the agent's service in the end-to-end tests: it accepts each claim
// the backend asks it to resume, listed at /api/resumed, and each run the backend
// asks it to start, listed with what it was sent at /api/started.
import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";

const resumed: string[] = [];
const started: { path: string; body: unknown }[] = [];
const STARTS = new Set(["/api/dispatches", "/api/evaluations"]);

function reply(response: ServerResponse, status: number, body: unknown) {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  let text = "";
  for await (const chunk of request) text += String(chunk);
  return JSON.parse(text);
}

createServer((request, response) => {
  const path = request.url ?? "";
  const resume = /^\/api\/claims\/([^/]+)\/resume$/.exec(path);
  if (request.method === "POST" && resume) {
    resumed.push(decodeURIComponent(resume[1]));
    reply(response, 202, { status: "accepted" });
  } else if (request.method === "POST" && STARTS.has(path)) {
    void readJson(request).then((body) => {
      started.push({ path, body });
      reply(response, 202, { status: "accepted" });
    });
  } else if (path === "/api/resumed") {
    reply(response, 200, resumed);
  } else if (path === "/api/started") {
    reply(response, 200, started);
  } else if (path === "/api/health") {
    reply(response, 200, { status: "ok" });
  } else {
    reply(response, 404, { detail: "Not found" });
  }
}).listen(Number(process.env.PORT), "127.0.0.1");
