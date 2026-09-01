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
const dragonComponent = await readFile("app/components/DragonSection.tsx", "utf8");
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
  assert.match(appSource, /增量更新近期 10 篇/);
  assert.match(appSource, /降级归档/);
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

test("首板布局保持独立 API 与页面状态边界", () => {
  assert.match(html, /activeNav === "首板布局"/);
  assert.match(html, /<DragonSection/);
  assert.match(dragonComponent, /const DRAGON_API = "\/api\/dragon"/);
  assert.match(dragonComponent, /仅访问 \/api\/dragon\/\*/);
  assert.match(dragonComponent, /确认作为今日布局结论/);
  assert.match(dragonComponent, /抓取数据并生成首板布局结论/);
  assert.match(dragonComponent, /"\/snapshot"/);
  assert.match(dragonComponent, /"\/analyze-async"/);
  assert.match(dragonComponent, /"\/jobs\/"/);
  assert.match(dragonComponent, /炸板标记/);
  assert.doesNotMatch([apiClient, ...components].join("\n"), /\/api\/dragon\//);
});

test("首板快照沿用旧模块爬虫原文并保留来源", () => {
  assert.match(html, /currentReviewText=\{crawledText\}/);
  assert.match(html, /currentReviewSourceUrl=\{crawledSource\}/);
  assert.match(dragonComponent, /source_url: snapshot\.source_url/);
  assert.match(dragonComponent, /currentReviewSourceTitle/);
  assert.match(dragonComponent, /原文来源未载入/);
  assert.match(html, /当日 API 复盘分析/);
  assert.match(html, /刺大复盘原文/);
});

test("布局分析结果自动带入首板布局草稿", () => {
  assert.match(html, /buildDragonGeneratedReview/);
  assert.match(html, /generatedReview=\{dragonGeneratedReview\}/);
  assert.match(dragonComponent, /布局分析生成结果已自动带入/);
  assert.match(dragonComponent, /重新载入布局分析结果/);
  assert.match(dragonComponent, /载入原始复盘文本供修改/);
});

test("首板候选支持通过状态与硬性失败原因分层", () => {
  assert.match(dragonComponent, /候选通过状态/);
  assert.match(dragonComponent, /不通过原因归类/);
  assert.match(dragonComponent, /candidateFailureReasons/);
  assert.match(dragonComponent, /\/rule-versions\//);
  assert.match(dragonComponent, /method: "DELETE"/);
});
