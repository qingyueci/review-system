import { BranchState } from "./review-api";

export type Stats = {
  core_posts: number;
  supplemental_posts: number;
  qa_pairs: number;
  community_comments: number;
  manual_chunks: number;
  chunks: number;
  last_sync: string;
};

export type Source = {
  level: string;
  title: string;
  published_at: string;
  source_url: string;
  excerpt: string;
  source_type: string;
};

export type AnalysisTask = {
  stock: string;
  origin: string;
  original_task: string;
  current_position: string;
  relations: string;
  success_signal: string;
  failure_signal: string;
};

export type AnalysisResult = {
  analysis: string;
  sections: Record<string, string>;
  tasks: AnalysisTask[];
  sources: Source[];
  document_base64: string;
  document_filename: string;
  excel_base64: string;
  excel_filename: string;
  branches: Record<"excel" | "word", BranchState>;
  warnings: string[];
};

export type GenerationMode = "both" | "excel" | "word";

export type HistoryDocument = {
  filename: string;
  modified_at: string;
  size: number;
  kind: "word" | "excel";
};

export type KnowledgePost = {
  title: string;
  published_at: string;
  views: number;
  reply_count: number;
  likes: number;
  scope: "top_year" | "recent_qa";
  body_truncated: boolean;
  capture_mode: string;
  url: string;
};
