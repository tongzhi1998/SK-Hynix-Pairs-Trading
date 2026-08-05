import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Hynix basis dashboard shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Hynix Basis — OKX Pair Monitor<\/title>/i);
  assert.match(html, /Hynix Basis/);
  assert.match(html, /mark price only/i);
  assert.match(html, /10 × SKHY MARK ÷ SKHYNIX MARK − 1/);
  assert.match(html, /FIVE-MINUTE DIFFERENCE HISTORY/);
  assert.match(html, /ADR premium \/ discount/);
  assert.match(html, /Funding rates/);
  assert.match(html, /3\/day/);
  assert.doesNotMatch(html, /Normalized pair|ROLLING Z-SCORE/);
  assert.match(html, /PAIR START/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/);
});

test("keeps OKX data access in the Python service", async () => {
  const [page, dashboard, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/dashboard.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(page, /<Dashboard \/>/);
  assert.match(dashboard, /NEXT_PUBLIC_API_BASE_URL/);
  assert.match(dashboard, /\/api\/v1\/snapshot/);
  assert.match(dashboard, /ctx\.setTransform\(1, 0, 0, 1, 0, 0\)/);
  assert.match(dashboard, /premium_pct/);
  assert.match(dashboard, /axisTimestamp/);
  assert.match(dashboard, /pointermove/);
  assert.match(dashboard, /funding_points/);
  assert.match(dashboard, /SKHYNIX and SKHY settled funding rate chart/);
  assert.match(dashboard, /Hover or use arrow keys for values/);
  assert.match(dashboard, /CURRENT RATE COLLECTS IN/);
  assert.match(dashboard, /leg\.funding\.funding_time/);
  assert.match(dashboard, /Asia\/Shanghai/);
  assert.match(dashboard, /Korea: previous close · SPY\/QQQ: trailing 24h/);
  assert.doesNotMatch(dashboard, /Korea \/ EWY proxy|EWY-USDT-SWAP/);
  assert.doesNotMatch(dashboard, /query2\.finance\.yahoo\.com/);
  assert.doesNotMatch(dashboard, /countdown\(leg\.funding\.next_funding_time/);
  assert.doesNotMatch(dashboard, /www\.okx\.com|bidPx|askPx|lastPx/);
  assert.match(layout, /Hynix Basis — OKX Pair Monitor/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
});
