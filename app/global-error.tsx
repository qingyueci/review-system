"use client";

export default function GlobalError() {
  return (
    <html lang="zh-CN">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "#f4f1eb",
          color: "#1f2824",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <main
          style={{
            width: "min(560px, calc(100% - 40px))",
            padding: "40px",
            border: "1px solid #d8d2c7",
            borderRadius: "18px",
            background: "#fffdf9",
            boxShadow: "0 18px 50px rgba(31, 40, 36, 0.09)",
          }}
        >
          <div
            style={{
              width: "48px",
              height: "48px",
              display: "grid",
              placeItems: "center",
              marginBottom: "24px",
              borderRadius: "12px",
              background: "#a94739",
              color: "white",
              fontWeight: 800,
            }}
          >
            刺
          </div>
          <h1 style={{ margin: "0 0 12px", fontSize: "26px" }}>
            页面需要重新加载
          </h1>
          <p style={{ margin: "0 0 28px", color: "#68706c", lineHeight: 1.7 }}>
            分析任务和已经生成的 Word 不会丢失。
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              border: 0,
              borderRadius: "10px",
              padding: "13px 20px",
              background: "#a94739",
              color: "white",
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            重新加载复盘驾驶舱
          </button>
        </main>
      </body>
    </html>
  );
}
