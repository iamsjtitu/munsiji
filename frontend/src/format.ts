import dayjs from "dayjs";

import type { LedgerKind } from "@/src/types";

export function formatINR(amount: number, withSymbol = true): string {
  const abs = Math.abs(amount);
  const whole = Math.floor(abs);
  const frac = Math.round((abs - whole) * 100);
  let s = String(whole);
  if (s.length > 3) {
    const tail = s.slice(-3);
    let head = s.slice(0, -3);
    const parts: string[] = [];
    while (head.length > 2) {
      parts.unshift(head.slice(-2));
      head = head.slice(0, -2);
    }
    if (head) parts.unshift(head);
    s = parts.join(",") + "," + tail;
  }
  if (frac) s += "." + String(frac).padStart(2, "0");
  return (withSymbol ? "₹" : "") + s;
}

export function balanceLabel(balance: number, kind: LedgerKind = "party"): string {
  if (kind === "cash" || kind === "bank") {
    const what = kind === "cash" ? "in hand" : "in bank";
    return balance < -0.004 ? `minus (${what})` : what;
  }
  if (balance > 0.004) return "lena hai";
  if (balance < -0.004) return "dena hai";
  return "settled";
}

/** Labels for the two directions depending on ledger kind (party: diya/mila, money account: in/out). */
export function directionLabels(kind: LedgerKind = "party"): { debit: string; credit: string } {
  if (kind === "cash" || kind === "bank") return { debit: "Jama (In)", credit: "Nikla (Out)" };
  return { debit: "Diya (Dr)", credit: "Mila (Cr)" };
}

export function formatDate(iso: string, fmt = "DD MMM YY"): string {
  return dayjs(iso).format(fmt);
}

export function todayISO(): string {
  return dayjs().format("YYYY-MM-DD");
}

export function monthOptions(count = 12): { key: string; label: string }[] {
  const out: { key: string; label: string }[] = [];
  for (let i = 0; i < count; i++) {
    const d = dayjs().subtract(i, "month");
    out.push({ key: d.format("YYYY-MM"), label: d.format("MMM YY") });
  }
  return out;
}
