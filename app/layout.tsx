import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "复盘驾驶舱｜刺大布局模型",
  description: "围绕首板出身、原始任务、布局关系和地位变化组织每日复盘。",
  openGraph: {
    title: "复盘驾驶舱",
    description: "先看任务，再看地位。让每日复盘有证据、有布局。",
    images: [{ url: "/og.png", width: 1200, height: 630 }],
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
