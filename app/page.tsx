"use client";

import { ChangeEvent, useMemo, useState } from "react";

type Task = {
  id: string;
  name: string;
  role: string;
  origin: string;
  task: string;
  position: string;
  relation: string;
  state: "推进" | "观察" | "受阻";
  signal: string;
  failure: string;
};

const tasks: Task[] = [
  {
    id: "seed-a",
    name: "首板种子 A",
    role: "进攻发起",
    origin: "低位主动首板",
    task: "替板块打开高度，验证新增量是否愿意接力",
    position: "前排试错",
    relation: "带动换手核心 B；受情绪锚点 C 反馈约束",
    state: "推进",
    signal: "竞价不弱、首轮分歧主动回封",
    failure: "被同题材后排反卡且无法夺回主动权",
  },
  {
    id: "core-b",
    name: "换手核心 B",
    role: "承接中枢",
    origin: "分歧换手首板",
    task: "吸收抛压，为发起者提供持续性证明",
    position: "结构核心",
    relation: "承接首板种子 A；压制跟风 D 的地位上升",
    state: "观察",
    signal: "分歧放量但不失去板块成交中心",
    failure: "缩量加速后首次分歧无承接",
  },
  {
    id: "anchor-c",
    name: "情绪锚点 C",
    role: "风险定价",
    origin: "逆势辨识度首板",
    task: "提示周期强弱，决定进攻仓位上限",
    position: "外部锚点",
    relation: "不直接争龙头，但影响 A、B 的溢价预期",
    state: "受阻",
    signal: "弱转强并带动亏钱效应收敛",
    failure: "高开低走，负反馈扩散到前排",
  },
  {
    id: "follower-d",
    name: "后排跟随 D",
    role: "扩散确认",
    origin: "题材助攻首板",
    task: "证明板块宽度，不承担打开高度的职责",
    position: "后排验证",
    relation: "依赖 A、B；若主动卡位则需重新评估任务",
    state: "观察",
    signal: "核心稳定后仍有独立承接",
    failure: "只在核心封死后被动脉冲",
  },
];

const evidenceByTask: Record<
  string,
  Array<{ level: string; title: string; excerpt: string; tag: string }>
> = {
  "seed-a": [
    {
      level: "刺大本人回复",
      title: "先看它从哪里出身",
      excerpt:
        "首板不是一个价格标签，而是市场第一次给它分配任务。后续强弱要围绕任务是否完成来判断。",
      tag: "本人观点",
    },
    {
      level: "历史原帖",
      title: "布局先于单点强弱",
      excerpt:
        "个股的地位来自它在整个队形里的作用：谁开路、谁承接、谁确认、谁负责风险提示。",
      tag: "核心原帖",
    },
    {
      level: "人工整理体系",
      title: "首板出身核对表",
      excerpt: "主动性、板块位置、时间节点、分歧程度，四项共同决定原始任务。",
      tag: "体系文档",
    },
  ],
  "core-b": [
    {
      level: "刺大本人回复",
      title: "换手不是目的，承接才是",
      excerpt:
        "观察它有没有接住分歧、有没有继续维持板块成交重心，而不是机械比较换手率。",
      tag: "本人观点",
    },
    {
      level: "社区精选观点",
      title: "承接中枢的识别",
      excerpt: "当发起者出现波动时，仍能稳定队形的个股，才有资格被重新定级。",
      tag: "高赞评论",
    },
  ],
  "anchor-c": [
    {
      level: "刺大本人回复",
      title: "负反馈也是任务",
      excerpt:
        "有些票不是用来进攻的，而是用来告诉你市场愿不愿意继续付风险溢价。",
      tag: "本人观点",
    },
    {
      level: "人工整理体系",
      title: "锚点只决定仓位上限",
      excerpt: "风险锚点转强不等于直接买入，它首先改变的是对整体布局的容错判断。",
      tag: "体系文档",
    },
  ],
  "follower-d": [
    {
      level: "历史原帖",
      title: "后排的价值在验证",
      excerpt:
        "助攻首先证明题材宽度。只有在关键节点主动站出来，它的任务才可能升级。",
      tag: "核心原帖",
    },
    {
      level: "社区精选观点",
      title: "避免把跟风看成补涨核心",
      excerpt: "区分主动卡位与核心封死后的被动脉冲，二者承担的市场任务完全不同。",
      tag: "高赞评论",
    },
  ],
};

const navItems = ["今日复盘", "布局分析", "知识库", "历史文档"];

export default function Home() {
  const [activeNav, setActiveNav] = useState("今日复盘");
  const [selectedId, setSelectedId] = useState("seed-a");
  const [fileName, setFileName] = useState("未选择文件");
  const [notice, setNotice] = useState("");

  const selectedTask = useMemo(
    () => tasks.find((task) => task.id === selectedId) ?? tasks[0],
    [selectedId],
  );
  const evidence = evidenceByTask[selectedTask.id];

  function showPending(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 3200);
  }

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) {
      setFileName(file.name);
      setNotice(`已载入「${file.name}」，接入分析服务后可生成正式复盘。`);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">刺</div>
          <div>
            <div className="brand-line">
              <h1>复盘驾驶舱</h1>
              <span className="beta">布局模型 · 界面预览</span>
            </div>
            <p>不追着价格解释，先判断每只个股在队形里承担什么任务</p>
          </div>
        </div>
        <div className="top-actions">
          <div className="knowledge-status">
            <span className="pulse-dot" />
            <div>
              <strong>知识库已就绪</strong>
              <small>4,723 条可检索证据</small>
            </div>
          </div>
          <button className="btn btn-secondary" onClick={() => showPending("同步入口已预留，部署本地服务后启用。")}>
            同步知识库
          </button>
          <button className="btn btn-primary" onClick={() => showPending("分析入口已预留，当前展示的是结构化演示数据。")}>
            开始分析
          </button>
        </div>
      </header>

      <div className="workspace">
        <aside className="sidebar">
          <nav aria-label="主要功能">
            {navItems.map((item, index) => (
              <button key={item} className={`nav-item ${activeNav === item ? "active" : ""}`} onClick={() => setActiveNav(item)}>
                <span className="nav-index">0{index + 1}</span>
                <span>{item}</span>
              </button>
            ))}
          </nav>
          <div className="sidebar-divider" />
          <div className="library-card">
            <span className="eyebrow">RAG 知识构成</span>
            <dl>
              <div><dt>核心原帖</dt><dd>20</dd></div>
              <div><dt>本人回复</dt><dd>4,306</dd></div>
              <div><dt>社区精选</dt><dd>342</dd></div>
              <div><dt>人工体系切片</dt><dd>14</dd></div>
            </dl>
            <div className="source-note">已纳入《延边刺客短线打板体系》</div>
          </div>
          <p className="sidebar-foot">最近整理 · 2026.07.18</p>
        </aside>

        <section className="main-column">
          <div className="context-bar">
            <div>
              <span className="eyebrow">2026.07.18 · 周六</span>
              <h2>{activeNav}</h2>
            </div>
            <div className="context-tools">
              <label className="file-picker">
                <input type="file" accept=".docx,.txt,.md" onChange={handleFile} />
                <span>导入每日复盘</span>
              </label>
              <span className="file-name" title={fileName}>{fileName}</span>
            </div>
          </div>

          <section className="judgement-card">
            <div className="judgement-topline">
              <span className="section-number">01</span>
              <span className="eyebrow">核心判断 · 演示数据</span>
              <span className="confidence">结构置信度 78%</span>
            </div>
            <div className="judgement-grid">
              <div>
                <h3>当前不是选“最强”，而是确认谁在完成开路任务</h3>
                <p>首板种子 A 负责打开空间，换手核心 B 负责承接分歧。若 A 失去主动、B 仍稳住成交中心，地位可能在盘中发生迁移。</p>
              </div>
              <div className="decision-box">
                <span>明日首要验证</span>
                <strong>A 的主动性是否仍领先于 B 的承接价值</strong>
                <small>先看竞价队形，再决定仓位，不预设唯一龙头。</small>
              </div>
            </div>
          </section>

          <section className="panel relationship-panel">
            <div className="panel-heading">
              <div>
                <span className="section-number">02</span>
                <div><span className="eyebrow">布局关系图</span><h3>任务如何在队形中传递</h3></div>
              </div>
              <div className="legend">
                <span><i className="dot amber" />核心任务</span>
                <span><i className="dot green" />推进</span>
                <span><i className="dot red" />受阻</span>
              </div>
            </div>
            <div className="relationship-map" aria-label="个股任务关系示意图">
              {tasks.map((task) => (
                <button key={task.id} className={`map-node ${task.id.split("-")[0]} ${selectedId === task.id ? "selected" : ""}`} onClick={() => setSelectedId(task.id)}>
                  <small>{task.role.slice(0, 2)}</small>
                  <strong>{task.name}</strong>
                  <span>{task.position}</span>
                </button>
              ))}
              <div className="relation-line line-a"><span>带动</span></div>
              <div className="relation-line line-b"><span>反馈</span></div>
              <div className="relation-line line-c"><span>验证</span></div>
              <div className="map-center"><span>市场合力</span><strong>任务迁移</strong></div>
            </div>
          </section>

          <section className="panel matrix-panel">
            <div className="panel-heading">
              <div>
                <span className="section-number">03</span>
                <div><span className="eyebrow">任务矩阵</span><h3>从首板出身追踪地位变化</h3></div>
              </div>
              <span className="hint">点击行查看对应证据</span>
            </div>
            <div className="task-table-wrap">
              <table className="task-table">
                <thead>
                  <tr><th>对象 / 角色</th><th>首板出身</th><th>原始任务</th><th>当前位置</th><th>协同 / 压制</th><th>状态</th></tr>
                </thead>
                <tbody>
                  {tasks.map((task) => (
                    <tr key={task.id} className={selectedId === task.id ? "selected-row" : ""} onClick={() => setSelectedId(task.id)}>
                      <td><strong>{task.name}</strong><small>{task.role}</small></td>
                      <td>{task.origin}</td>
                      <td>{task.task}</td>
                      <td>{task.position}</td>
                      <td>{task.relation}</td>
                      <td><span className={`state state-${task.state}`}>{task.state}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="tomorrow-grid">
            <article>
              <span className="eyebrow">明日竞价确认</span>
              <h3>{selectedTask.name} · 完成任务的信号</h3>
              <p>{selectedTask.signal}</p>
            </article>
            <article className="failure-card">
              <span className="eyebrow">失效条件</span>
              <h3>什么时候必须推翻当前判断</h3>
              <p>{selectedTask.failure}</p>
            </article>
          </section>
        </section>

        <aside className="evidence-panel">
          <div className="evidence-header"><span className="eyebrow">RAG 证据链</span><span className="evidence-count">{evidence.length} 条</span></div>
          <h2>{selectedTask.name}</h2>
          <p className="evidence-intro">回答必须先引用刺大原始语境，再用体系文档校正；社区观点只作补充。</p>
          <div className="evidence-list">
            {evidence.map((item, index) => (
              <article className="evidence-item" key={`${item.title}-${index}`}>
                <div className="evidence-meta"><span>{item.level}</span><span className={index === 0 ? "primary-tag" : ""}>{item.tag}</span></div>
                <h3>{item.title}</h3>
                <p>“{item.excerpt}”</p>
                <button onClick={() => showPending("原文定位入口已预留，接入本地知识库后可直接跳转。")}>查看原文定位 →</button>
              </article>
            ))}
          </div>
          <div className="evidence-rule">
            <strong>证据优先级</strong>
            <ol><li>刺大本人回复</li><li>历史原帖</li><li>人工整理体系</li><li>社区精选观点</li></ol>
          </div>
          <button className="export-button" onClick={() => showPending("Word 导出将在接入本地生成服务后启用。")}>
            <span>生成今日复盘文档</span><small>接入本地服务后启用</small>
          </button>
        </aside>
      </div>
      {notice && <div className="toast" role="status">{notice}</div>}
    </main>
  );
}
