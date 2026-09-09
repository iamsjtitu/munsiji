export type Group = {
  id: string;
  name: string;
  ledger_count: number;
  balance: number;
  lena: number;
  dena: number;
};

export type Ledger = {
  id: string;
  name: string;
  group_id: string;
  group_name?: string;
  aliases: string[];
  current_balance: number;
};

export type Direction = "debit" | "credit";

export type Transaction = {
  id: string;
  ledger_id: string;
  ledger_name?: string;
  amount: number;
  direction: Direction;
  note: string;
  entry_date: string;
  source: string;
  running_balance?: number;
};

export type Statement = {
  opening_balance: number;
  closing_balance: number;
  total_debit: number;
  total_credit: number;
  rows: Transaction[];
  ledger: Ledger;
};

export type WaMessage = {
  id: string;
  sender: string;
  text: string;
  reply: string | null;
  status: string;
  source: string;
  files: { url: string; filename: string; format: string }[];
  created_at: string;
};

export type Settings = {
  owner_number: string;
  owner_email: string;
  alerts_enabled: boolean;
  has_emergent_llm_key: boolean;
  emergent_llm_key_hint: string;
  has_emergent_email_key: boolean;
  emergent_email_key_hint: string;
  ai_configured: boolean;
  email_configured: boolean;
  has_wa9x_api_key: boolean;
  wa9x_api_key_hint: string;
  has_wa9x_webhook_secret: boolean;
  wa9x_webhook_secret_hint: string;
  provider: "mock" | "wa9x";
  wa9x_base_url: string;
  wa9x_instance_id: string;
  public_base_url: string;
  webhook_url: string;
  configured: boolean;
};

export type WaStatus = {
  provider: string;
  configured: boolean;
  owner_number: string;
  webhook_url: string;
  pending_question: string | null;
  last_whatsapp_at: string | null;
  last_webhook_at: string | null;
  last_webhook_outcome: string | null;
  webhook_hits_24h: number;
};

export type WebhookLogEntry = {
  id: string;
  received_at: string;
  processed_at: string | null;
  outcome: string;
  detail: string;
  sender: string;
  text: string;
  event: string;
  raw: string;
};

export type ConnectionCheck = {
  base_url: string;
  sessions: { name?: string; status?: string; phone?: string; id?: string }[];
  sessions_error: string | null;
  sent: boolean;
  send_error: string | null;
};

export type Dashboard = {
  total_lena: number;
  total_dena: number;
  ledger_count: number;
  recent: Transaction[];
};

export type UpdateStatus = { state: "idle" | "requested" | "updating" | "building" | "restarting" | "done" | "failed"; message?: string; commit?: string; updated_at?: string };

export type VersionInfo =
  | { supported: false }
  | {
      supported: true;
      branch: string;
      current: { commit: string; message: string; date: string };
      latest: { commit: string; message: string; date: string };
      behind: number;
      update_available: boolean;
      checked_at: string;
      status: UpdateStatus;
      auto_update: boolean;
      log: string[];
    };

export const UPDATE_BUSY_STATES = ["requested", "updating", "building", "restarting"];

export type MonthlySummary = {
  month: string;
  total_debit: number;
  total_credit: number;
  net: number;
  groups: { group_id: string; group_name: string; debit: number; credit: number; count: number }[];
  ledgers: {
    ledger_id: string;
    ledger_name: string;
    group_name: string;
    debit: number;
    credit: number;
    net: number;
    count: number;
    current_balance: number;
  }[];
};
