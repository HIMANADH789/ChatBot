export interface Document {
  doc_id: string;
  client_id: string;
  filename: string;
  file_type: string;
  file_size_bytes: number;
  status: "processing" | "ready" | "failed";
  error_message?: string;
  chunks_count: number;
  uploaded_at: string;
  processed_at?: string;
}

export interface Source {
  doc_id: string;
  filename: string;
  chunk_index: number;
  score: number;
  text_preview: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  timestamp?: string;
}

export interface ChatResponse {
  response: string;
  sources: Source[];
  session_id: string;
}

export interface QueryLog {
  client_id: string;
  session_id: string;
  query: string;
  response: string;
  channel?: string;
  cache_hit?: boolean;
  sources: Source[];
  response_time_ms: number;
  llm_provider: string;
  created_at: string;
}

export interface WebhookLog {
  id: string;
  client_id: string;
  channel: string;
  timestamp: string;
  sender_id?: string;
  sender_name?: string;
  message_in?: string;
  response_out?: string;
  response_time_ms?: number;
  status: string;
  raw_payload?: any;
  outgoing_payload?: any;
  meta_status?: number;
  meta_response?: any;
  metadata?: Record<string, any>;
  error?: string;
  traceback?: string;
}

export interface User {
  email: string;
  client_id: string;
  role: string;
}

// ── Setup types ────────────────────────────────────────────────────────────────

export type SetupChannel = "widget" | "web_api" | "whatsapp" | "facebook" | "telegram" | "slack";

export interface SetupSummary {
  channel: SetupChannel;
  label: string;
  emoji: string;
  enabled: boolean;
  rate_limit_rpm: number;
  rate_limit_rpd: number;
  max_queries_per_session: number;
  token_set?: boolean; // only for widget / web_api
  context_mode?: "none" | "adaptive" | "full" | string;
  context_instructions?: string;
  context_capacity?: number;
}

export interface ChannelStats {
  channel: string;
  total_queries: number;
  queries_today: number;
  avg_response_time_ms: number;
  input_tokens: number;
  output_tokens: number;
  cache_hits: number;
  top_queries: { query: string; count: number }[];
  daily_trend: { date: string; count: number }[];
}

// ── Analytics types ────────────────────────────────────────────────────────────

export interface UsageStats {
  total_queries: number;
  queries_today: number;
  avg_response_time_ms: number;
  top_queries: { query: string; count: number }[];
  channel_breakdown: { channel: string; total_queries: number; avg_response_time_ms: number; input_tokens: number; output_tokens: number }[];
  daily_trend: { date: string; count: number }[];
  remaining_llm_quota: number;
}

export interface SubMenu {
  id: string;
  label: string;
  sub_questions: string[];
}

export interface MenuOption {
  id: string;
  label: string;
  submenus: SubMenu[];
}

export interface MenuNode {
  id: string;
  label: string;
  description?: string;
  descriptor_tag?: string;
  frequency?: "only_once" | "always" | "on_intent" | string;
  action_question?: string;
  children?: MenuNode[];
}

export interface WhatsAppMedia {
  image_url?: string;
  caption?: string;
}

export interface NodeOption {
  option_number: string;
  button_text: string;
  target_type: "NAVIGATE_MENU" | "TRIGGER_RAG" | string;
  target_id?: string;
  rag_prompt?: string;
}

export interface MenuGraphNode {
  node_id: string;
  menu_number: string;
  title: string;
  whatsapp_media?: WhatsAppMedia;
  options: NodeOption[];
  frequency?: "always" | "only_once" | string;
  direct_answer?: string;
}

export interface MenuGraphValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  node_count: number;
  root_node_id: string;
}

export interface ContextImage {
  id: string;
  title: string;
  image_path: string;
  descriptor_tag: string;
  caption?: string;
  frequency?: "only_once" | "always" | "on_intent" | string;
}

export interface DescriptiveRule {
  id: string;
  title: string;
  trigger_type: "on_first_turn" | "on_intent" | "always" | string;
  prompt_directive: string;
  target_menu_id?: string;
  target_image_id?: string;
}

export interface CompiledProfile {
  client_id: string;
  channel: string;
  version_hash: string;
  compiled_at: string;
  compiled_system_prompt: string;
  welcome_message: string;
  theme_color: string;
  chatbot_title: string;
  menu_tree: MenuNode[];
  context_images: ContextImage[];
  descriptive_rules: DescriptiveRule[];
  context_config: {
    mode: string;
    instructions: string;
    capacity: number;
  };
}

export interface ClientSettings {
  welcome_message?: string;
  theme_color?: string;
  chatbot_title?: string;
  custom_widget_script?: string;
  menu_options?: MenuOption[];
  menu_tree?: MenuNode[];
  menu_graph_nodes?: MenuGraphNode[];
  menu_graph_root_node_id?: string;
  context_images?: ContextImage[];
  descriptive_rules?: DescriptiveRule[];
  system_prompt?: string;
  max_history_turns?: number;
  context_mode?: "none" | "adaptive" | "full" | string;
  context_instructions?: string;
  context_capacity?: number;
  compiled_profiles?: Record<string, CompiledProfile>;
  last_compiled_at?: string;
  setups?: Record<string, Record<string, unknown>>;
}

export interface ClientRecord {
  client_id: string;
  name: string;
  domain?: string;
  created_at?: string;
  settings?: ClientSettings;
}

export interface ClientUsageSummary {
  client_id: string;
  name: string;
  created_at?: string;
  total_queries: number;
  queries_this_month: number;
  queries_today: number;
  avg_response_time_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  document_count: number;
}

export interface SuperAdminOverview {
  clients: ClientUsageSummary[];
  total_clients: number;
  platform_total_queries: number;
  platform_total_input_tokens: number;
  platform_total_output_tokens: number;
  platform_channel_breakdown: Record<string, number>;
}

export interface SuperAdminClientDetail extends UsageStats {
  total_input_tokens: number;
  total_output_tokens: number;
  document_count: number;
  logs: QueryLog[];
  logs_total: number;
  logs_page: number;
  logs_page_size: number;
}

// Keep for backward compat
export type ClientSettingsFull = ClientSettings;
