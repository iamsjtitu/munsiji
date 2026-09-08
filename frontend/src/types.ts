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
  provider: "mock" | "wa9x";
  wa9x_base_url: string;
  wa9x_api_key: string;
  wa9x_instance_id: string;
  wa9x_send_path: string;
  wa9x_send_doc_path: string;
  public_base_url: string;
  webhook_url: string;
  configured: boolean;
};

export type Dashboard = {
  total_lena: number;
  total_dena: number;
  ledger_count: number;
  recent: Transaction[];
};

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
