import { BranchState } from "./review-api";

export type Stats = {
  core_posts: number;
  supplemental_posts: number;
  archived_posts: number;
  qa_pairs: number;
  retrievable_qa: number;
  semantic_duplicates: number;
  semantic_model: string;
  semantic_cleaned_at: string;
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
  retrieval_score?: number;
  retrieval_mode?: string;
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
  source_text: string;
  source_title: string;
  source_url: string;
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
  scope: "top_year" | "recent_qa" | "recent_archive";
  body_truncated: boolean;
  capture_mode: string;
  url: string;
};

export type RunRecord = {
  job_id: string;
  status: "pending" | "running" | "succeeded" | "failed";
  message: string;
  review_date: string;
  filename: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  retry_of: string;
  branches: AnalysisResult["branches"];
  sources: Array<{
    title: string;
    source_type: string;
    source_url: string;
    retrieval_score: number;
  }>;
  excel_filename: string;
  document_filename: string;
};
