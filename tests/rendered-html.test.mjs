import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const html = await readFile("app/page.tsx", "utf8");
const errorPage = await readFile("app/error.tsx", "utf8");
const globalErrorPage = await readFile("app/global-error.tsx", "utf8");

test("页面包含产品核心信息", () => {
  assert.match(html, /复盘驾驶舱/);
  assert.match(html, /首板出身/);
  assert.match(html, /RAG 证据链/);
  assert.match(html, /今日复盘/);
  assert.match(html, /布局分析/);
  assert.match(html, /知识库/);
  assert.match(html, /历史文档/);
  assert.match(html, /自爬取当日复盘/);
  assert.match(html, /生成 Excel \+ Word/);
  assert.match(html, /Excel 完整整理/);
  assert.match(html, /Word 核心分析/);
  assert.match(html, /只生成 Excel/);
  assert.match(html, /只生成 Word/);
  assert.match(html, /只重试/);
});

test("页面不再包含脚手架预览", () => {
  assert.doesNotMatch(html, /codex-preview/);
  assert.doesNotMatch(html, /Your site is taking shape/);
});

test("耗时操作使用后台任务和进度轮询", () => {
  assert.match(html, /\/api\/fetch-review-async/);
  assert.match(html, /\/api\/analyze-async/);
  assert.match(html, /\/api\/jobs\/recent/);
  assert.match(html, /\/retry/);
  assert.match(html, /waitForJob/);
  assert.match(html, /review-active-generation/);
  assert.doesNotMatch(html, /180_000/);
});

test("分析结果异常时不会直接白屏", () => {
  assert.match(html, /normalizeAnalysisResult/);
  assert.match(errorPage, /重新加载复盘驾驶舱/);
  assert.match(globalErrorPage, /分析任务和已经生成的 Word 不会丢失/);
});
