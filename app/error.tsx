"use client";

import { useEffect } from "react";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("复盘驾驶舱页面异常", error);
  }, [error]);

  function recover() {
    reset();
    window.location.reload();
  }

  return (
    <main className="recovery-shell">
      <section className="recovery-card">
        <span className="recovery-mark">刺</span>
        <p className="eyebrow">页面自动保护</p>
        <h1>分析结果还在，本页需要重新加载</h1>
        <p>
          已生成的 Word 会保留在“历史文档”。重新加载不会重复调用模型。
        </p>
        <button onClick={recover}>重新加载复盘驾驶舱</button>
      </section>
    </main>
  );
}
