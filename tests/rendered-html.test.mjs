import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const html = await readFile("app/page.tsx", "utf8");

test("页面包含产品核心信息", () => {
  assert.match(html, /复盘驾驶舱/);
  assert.match(html, /首板出身/);
  assert.match(html, /RAG 证据链/);
  assert.match(html, /今日复盘/);
  assert.match(html, /布局分析/);
  assert.match(html, /知识库/);
  assert.match(html, /历史文档/);
  assert.match(html, /开始 RAG 布局分析/);
  assert.match(html, /自爬取当日复盘/);
});

test("页面不再包含脚手架预览", () => {
  assert.doesNotMatch(html, /codex-preview/);
  assert.doesNotMatch(html, /Your site is taking shape/);
});
