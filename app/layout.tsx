import type { Metadata } from "next";
import { Noto_Sans_SC, Noto_Serif_SC } from "next/font/google";
import { headers } from "next/headers";
import "./globals.css";

const sans = Noto_Sans_SC({
  variable: "--font-sans",
  subsets: ["latin"],
  display: "swap",
});

const serif = Noto_Serif_SC({
  variable: "--font-serif",
  subsets: ["latin"],
  display: "swap",
});

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("host");
  const protocol = requestHeaders.get("x-forwarded-proto") ?? "https";
  const imageUrl = host ? `${protocol}://${host}/og.png` : undefined;

  return {
    title: "复盘驾驶舱｜刺大布局模型",
    description: "围绕首板出身、原始任务、布局关系和地位变化组织每日复盘。",
    openGraph: imageUrl
      ? {
          title: "复盘驾驶舱",
          description: "先看任务，再看地位。让每日复盘有证据、有布局。",
          images: [{ url: imageUrl, width: 1200, height: 630 }],
          type: "website",
        }
      : undefined,
  };
}

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className={`${sans.variable} ${serif.variable}`}>{children}</body>
    </html>
  );
}
