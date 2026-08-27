export interface User { id: string; email: string; name?: string; created_at: string }
export interface Dataset { id: string; name: string; original_filename: string; file_type: string; file_size: number; row_count: number; column_count: number; quality_score: number; created_at: string; updated_at: string }
export interface DatasetColumn { id: string; name: string; data_type: string; null_count: number; null_percentage: number; unique_count: number; min_value?: string; max_value?: string; mean_value?: number; median_value?: number; std_value?: number }
export interface Message { id: string; role: string; content: string; generated_code?: string; execution_status?: string; created_at: string; results: any[]; charts: any[] }
export interface Session { id: string; title: string; dataset_id: string; dataset_name?: string; created_at: string; updated_at: string; messages?: Message[]; message_count?: number }
