import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const html = await readFile("app/page.tsx", "utf8");
const apiClient = await readFile("app/lib/review-api.ts", "utf8");
const components = await Promise.all([
  "TodayReviewSection.tsx",
  "AnalysisSection.tsx",
  "KnowledgeSection.tsx",
  "HistoryDocumentsSection.tsx",
].map((name) => readFile(`app/components/${name}`, "utf8")));
const appSource = [html, apiClient, ...components].join("\n");
const errorPage = await readFile("app/error.tsx", "utf8");
const globalErrorPage = await readFile("app/global-error.tsx", "utf8");

test("页面包含产品核心信息", () => {
  assert.match(appSource, /复盘驾驶舱/);
  assert.match(appSource, /首板出身/);
  assert.match(appSource, /RAG 证据链/);
  assert.match(appSource, /今日复盘/);
  assert.match(appSource, /布局分析/);
  assert.match(appSource, /知识库/);
  assert.match(appSource, /历史文档/);
  assert.match(appSource, /自爬取当日复盘/);
  assert.match(appSource, /生成 Excel \+ Word/);
  assert.match(appSource, /Excel 完整整理/);
  assert.match(appSource, /Word 核心分析/);
  assert.match(appSource, /只生成 Excel/);
  assert.match(appSource, /只生成 Word/);
  assert.match(appSource, /只重试/);
  assert.match(appSource, /运行记录/);
  assert.match(appSource, /模型消耗/);
});

test("页面不再包含脚手架预览", () => {
  assert.doesNotMatch(html, /codex-preview/);
  assert.doesNotMatch(html, /Your site is taking shape/);
});

test("耗时操作使用后台任务和进度轮询", () => {
  assert.match(appSource, /\/api\/fetch-review-async/);
  assert.match(appSource, /\/api\/analyze-async/);
  assert.match(appSource, /\/api\/jobs\/recent/);
  assert.match(appSource, /\/api\/runs/);
  assert.match(appSource, /\/retry/);
  assert.match(appSource, /waitForJob/);
  assert.match(appSource, /review-active-generation/);
  assert.match(appSource, /不会重复调用模型/);
  assert.doesNotMatch(appSource, /180_000/);
});

test("分析结果异常时不会直接白屏", () => {
  assert.match(html, /normalizeAnalysisResult/);
  assert.match(errorPage, /重新加载复盘驾驶舱/);
  assert.match(globalErrorPage, /分析任务和已经生成的 Word 不会丢失/);
});
