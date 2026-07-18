import { AnalysisResult } from "../lib/review-types";

type FrameworkTask = {
  id: string;
  name: string;
  role: string;
  task: string;
  position: string;
};

const frameworkTasks: FrameworkTask[] = [
  {
    id: "seed",
    name: "首板发起者",
    role: "进攻发起",
    task: "替板块打开空间，验证新增量",
    position: "前排试错",
  },
  {
    id: "core",
    name: "换手承接者",
    role: "承接中枢",
    task: "吸收抛压，为发起者提供持续性证明",
    position: "结构核心",
  },
  {
    id: "anchor",
    name: "情绪锚点",
    role: "风险定价",
    task: "提示周期强弱，决定进攻仓位上限",
    position: "外部锚点",
  },
  {
    id: "follower",
    name: "后排验证者",
    role: "扩散确认",
    task: "证明板块宽度，不承担打开高度的职责",
    position: "后排验证",
  },
];

type Props = {
  analysis: AnalysisResult | null;
  selectedId: string;
  onSelect: (id: string) => void;
  onGoToToday: () => void;
};

function cleanMarkdown(value: unknown) {
  return (typeof value === "string" ? value : "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/^[-*]\s+/gm, "• ")
    .trim();
}

export function AnalysisSection({
  analysis,
  selectedId,
  onSelect,
  onGoToToday,
}: Props) {
  const hasWordAnalysis = Boolean(analysis?.analysis.trim());
  const evidence = analysis?.sources ?? [];
  const sections = analysis?.sections ?? {};
  const coreJudgement = sections["今日核心判断"];
  const layoutText =
    sections["题材之间的任务关系"] ||
    sections["布局总图"] ||
    sections["地位演化和相互确认"];
  const taskText = sections["个股任务表"];
  const tomorrowText = sections["明日竞价确认条件"];
  const failureText = sections["判断失效条件"];
  const displayTasks = analysis?.tasks?.length
    ? analysis.tasks.slice(0, 4)
    : null;

  if (!analysis || !hasWordAnalysis) {
    return (
      <div className="page-empty">
        <span className="empty-symbol">未</span>
        <h3>还没有真实分析结果</h3>
        <p>Excel 可能已经生成；Word 布局分析需要模型额度可用后才能显示。</p>
        <button onClick={onGoToToday}>前往今日复盘</button>
      </div>
    );
  }

  return (
    <>
      <section className="judgement-card">
        <div className="judgement-topline">
          <span className="section-number">01</span>
          <span className="eyebrow">RAG 核心判断</span>
          <span className="confidence">引用 {evidence.length} 条资料</span>
        </div>
        <div className="judgement-grid">
          <div>
            <h3>
              {coreJudgement
                ? cleanMarkdown(coreJudgement).split("\n")[0]
                : "本次分析已完成"}
            </h3>
            <p className="analysis-text">
              {coreJudgement
                ? cleanMarkdown(coreJudgement)
                : cleanMarkdown(analysis.analysis)}
            </p>
          </div>
          <div className="decision-box">
            <span>核心约束</span>
            <strong>技术指标只能验证任务，不能替代布局关系</strong>
            <small>
              社区评论仅作补充；与本人原帖冲突时，以可核对的公开原文为准。
            </small>
          </div>
        </div>
      </section>
      <section className="panel relationship-panel">
        <div className="panel-heading">
          <div>
            <span className="section-number">02</span>
            <div>
              <span className="eyebrow">布局关系</span>
              <h3>本次检索分析</h3>
            </div>
          </div>
        </div>
        {layoutText && (
          <div className="generated-analysis">
            {cleanMarkdown(layoutText)}
          </div>
        )}
        <div
          className="relationship-map"
          aria-label="个股任务关系框架示意图"
        >
          {displayTasks
            ? displayTasks.map((task, index) => {
                const position = ["seed", "core", "anchor", "follower"][index];
                return (
                  <button
                    key={`${task.stock}-${index}`}
                    className={`map-node ${position} ${
                      selectedId === task.stock ? "selected" : ""
                    }`}
                    onClick={() => onSelect(task.stock)}
                  >
                    <small>{task.current_position || "任务节点"}</small>
                    <strong>{task.stock}</strong>
                    <span>{task.original_task}</span>
                  </button>
                );
              })
            : frameworkTasks.map((task) => (
                <button
                  key={task.id}
                  className={`map-node ${task.id} ${
                    selectedId === task.id ? "selected" : ""
                  }`}
                  onClick={() => onSelect(task.id)}
                >
                  <small>{task.role.slice(0, 2)}</small>
                  <strong>{task.name}</strong>
                  <span>{task.position}</span>
                </button>
              ))}
          <div className="relation-line line-a">
            <span>带动</span>
          </div>
          <div className="relation-line line-b">
            <span>反馈</span>
          </div>
          <div className="relation-line line-c">
            <span>验证</span>
          </div>
          <div className="map-center">
            <span>市场合力</span>
            <strong>任务迁移</strong>
          </div>
        </div>
      </section>
      <section className="panel matrix-panel">
        <div className="panel-heading">
          <div>
            <span className="section-number">03</span>
            <div>
              <span className="eyebrow">个股任务</span>
              <h3>模型提取的任务表</h3>
            </div>
          </div>
        </div>
        {analysis.tasks?.length ? (
          <div className="task-table-wrap">
            <table className="task-table analysis-task-table">
              <thead>
                <tr>
                  <th>个股</th>
                  <th>首板出身</th>
                  <th>原始任务</th>
                  <th>当前地位</th>
                  <th>协同 / 压制</th>
                  <th>完成信号</th>
                  <th>失败信号</th>
                </tr>
              </thead>
              <tbody>
                {analysis.tasks.map((task, index) => (
                  <tr
                    key={`${task.stock}-${index}`}
                    className={
                      selectedId === task.stock ? "selected-row" : ""
                    }
                    onClick={() => onSelect(task.stock)}
                  >
                    <td>
                      <strong>{task.stock}</strong>
                    </td>
                    <td>{task.origin}</td>
                    <td>{task.original_task}</td>
                    <td>{task.current_position}</td>
                    <td>{task.relations}</td>
                    <td>{task.success_signal}</td>
                    <td>{task.failure_signal}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="task-output">
            {taskText
              ? cleanMarkdown(taskText)
              : "本次模型没有按指定格式输出任务表，请以完整分析和证据链为准。"}
          </div>
        )}
      </section>
      <section className="tomorrow-grid">
        <article>
          <span className="eyebrow">明日竞价确认</span>
          <h3>完成任务需要出现什么</h3>
          <p className="analysis-text">
            {tomorrowText ? cleanMarkdown(tomorrowText) : "资料不足"}
          </p>
        </article>
        <article className="failure-card">
          <span className="eyebrow">失效条件</span>
          <h3>什么时候必须推翻当前判断</h3>
          <p className="analysis-text">
            {failureText ? cleanMarkdown(failureText) : "资料不足"}
          </p>
        </article>
      </section>
    </>
  );
}
