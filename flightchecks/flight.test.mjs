import assert from "node:assert/strict";
import { test } from "node:test";
import { runPlan } from "./runner.mjs";

const plan = {"claims":[{"id":"c_15781d32ac","kind":"file_exists","occurrences":[{"location":{"endOffset":9659,"kind":"file","lineEnd":258,"lineStart":258,"path":"README.md","sourceId":"readme_fd06f39f16e3","startOffset":9641},"quote":"[LICENSE](LICENSE)"}],"params":{"path":"LICENSE"},"sourceId":"readme_fd06f39f16e3","tier":"static"},{"id":"c_1caf70d0fd","kind":"file_exists","occurrences":[{"location":{"endOffset":5647,"kind":"file","lineEnd":138,"lineStart":137,"path":"README.md","sourceId":"readme_fd06f39f16e3","startOffset":5630},"quote":"screenshots/1.png"},{"location":{"endOffset":5667,"kind":"file","lineEnd":138,"lineStart":137,"path":"README.md","sourceId":"readme_fd06f39f16e3","startOffset":5650},"quote":"screenshots/1.png"}],"params":{"path":"screenshots/1.png"},"sourceId":"readme_fd06f39f16e3","tier":"static"},{"id":"c_330c464309","kind":"cli_flag","occurrences":[{"location":{"endOffset":2551,"kind":"file","lineEnd":52,"lineStart":40,"path":"README.md","sourceId":"readme_fd06f39f16e3","startOffset":2543},"quote":"--no-gui"}],"params":{"flag":"--no-gui"},"sourceId":"readme_fd06f39f16e3","tier":"static"},{"id":"c_5b3a00d31b","kind":"file_exists","occurrences":[{"location":{"endOffset":6569,"kind":"file","lineEnd":173,"lineStart":173,"path":"README.md","sourceId":"readme_fd06f39f16e3","startOffset":6545},"quote":"x_news_station/README.md"},{"location":{"endOffset":6596,"kind":"file","lineEnd":173,"lineStart":173,"path":"README.md","sourceId":"readme_fd06f39f16e3","startOffset":6572},"quote":"x_news_station/README.md"},{"location":{"endOffset":7309,"kind":"file","lineEnd":188,"lineStart":188,"path":"README.md","sourceId":"readme_fd06f39f16e3","startOffset":7285},"quote":"x_news_station/README.md"},{"location":{"endOffset":7336,"kind":"file","lineEnd":188,"lineStart":188,"path":"README.md","sourceId":"readme_fd06f39f16e3","startOffset":7312},"quote":"x_news_station/README.md"}],"params":{"path":"x_news_station/README.md"},"sourceId":"readme_fd06f39f16e3","tier":"static"},{"id":"c_6969e14796","kind":"file_exists","occurrences":[{"location":{"endOffset":5724,"kind":"file","lineEnd":138,"lineStart":137,"path":"README.md","sourceId":"readme_fd06f39f16e3","startOffset":5707},"quote":"screenshots/2.png"},{"location":{"endOffset":5744,"kind":"file","lineEnd":138,"lineStart":137,"path":"README.md","sourceId":"readme_fd06f39f16e3","startOffset":5727},"quote":"screenshots/2.png"}],"params":{"path":"screenshots/2.png"},"sourceId":"readme_fd06f39f16e3","tier":"static"}],"repo":"huss2342/x_news_station","sourceHashes":{"readme_fd06f39f16e3":"ee4ca6d9c86b7b23642d861b5d0ad943e2ef5e48f017e93238ad6b2b1327db94"}};
const results = await runPlan(plan);
const byIndex = plan.claims.map((claim) => results[claim.id]);

test("README.md:258  [LICENSE](LICENSE)", { skip: byIndex[0]?.status === "unverified" || byIndex[0]?.status === "skipped" }, () => {
  const result = byIndex[0];
  assert.ok(result, "Runner returned no result");
  assert.ok(result.status === "pass" || result.status === "flaky", [result.expected, result.actual].join("\n"));
});

test("README.md:137  screenshots/1.png", { skip: byIndex[1]?.status === "unverified" || byIndex[1]?.status === "skipped" }, () => {
  const result = byIndex[1];
  assert.ok(result, "Runner returned no result");
  assert.ok(result.status === "pass" || result.status === "flaky", [result.expected, result.actual].join("\n"));
});

test("README.md:40  --no-gui", { skip: byIndex[2]?.status === "unverified" || byIndex[2]?.status === "skipped" }, () => {
  const result = byIndex[2];
  assert.ok(result, "Runner returned no result");
  assert.ok(result.status === "pass" || result.status === "flaky", [result.expected, result.actual].join("\n"));
});

test("README.md:173  x_news_station/README.md", { skip: byIndex[3]?.status === "unverified" || byIndex[3]?.status === "skipped" }, () => {
  const result = byIndex[3];
  assert.ok(result, "Runner returned no result");
  assert.ok(result.status === "pass" || result.status === "flaky", [result.expected, result.actual].join("\n"));
});

test("README.md:137  screenshots/2.png", { skip: byIndex[4]?.status === "unverified" || byIndex[4]?.status === "skipped" }, () => {
  const result = byIndex[4];
  assert.ok(result, "Runner returned no result");
  assert.ok(result.status === "pass" || result.status === "flaky", [result.expected, result.actual].join("\n"));
});

