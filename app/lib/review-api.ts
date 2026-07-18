const API_BASE = "http://127.0.0.1:8765";

export type BranchState = {
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  message: string;
};

export type Job<T = unknown> = {
  status: "pending" | "running" | "succeeded" | "failed";
  message: string;
  current: number;
  total: number;
  branches?: Record<"excel" | "word", BranchState>;
  result?: T;
};

export type PersistedJob<T = unknown> = Job<T> & {
  job_id: string;
  created_at: string;
  updated_at: string;
};

export type StartedJob = {
  job_id: string;
  status: string;
  reused?: boolean;
};

export async function requestLocal<T>(
  token: string,
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const { timeoutMs = 15_000, ...fetchInit } = init;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...fetchInit,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-Review-Token": token,
        ...(fetchInit.headers ?? {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `本机服务返回错误：${response.status}`);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("本机服务响应较慢，正在重新连接");
    }
    if (error instanceof TypeError) {
      throw new Error("本机服务连接中断，请重新双击启动器");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function waitForJob<T>(
  token: string,
  jobId: string,
  onUpdate: (job: Job<T>) => void,
): Promise<Job<T>> {
  let consecutiveFailures = 0;
  while (true) {
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
    let job: Job<T>;
    try {
      job = await requestLocal<Job<T>>(token, `/api/jobs/${jobId}`);
    } catch (error) {
      consecutiveFailures += 1;
      if (consecutiveFailures < 6) {
        onUpdate({
          status: "running",
          message: "本机服务响应较慢，仍在等待后台任务",
          current: 0,
          total: 1,
        });
        continue;
      }
      throw error;
    }
    consecutiveFailures = 0;
    onUpdate(job);
    if (job.status === "failed") {
      throw new Error(job.message || "后台任务执行失败");
    }
    if (job.status === "succeeded") {
      return job;
    }
  }
}
