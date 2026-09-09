import { useQuery } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { api } from "@/src/api";
import { Button, Chip, Field, Segmented } from "@/src/components/ui";
import { directionLabels, todayISO } from "@/src/format";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import type { Direction, LedgerKind, TagCount, Transaction, TxnMode } from "@/src/types";

export type TxnValues = { amount: number; direction: Direction; note: string; entry_date: string; mode: TxnMode | "keep"; tags: string[] };

const useStyles = makeStyles((colors) => ({
  label: { fontFamily: fonts.text, fontSize: 12, fontWeight: "600", color: colors.muted, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 },
  hint: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, marginTop: 6, marginBottom: 12, lineHeight: 16 },
  error: { fontFamily: fonts.text, fontSize: 13, color: colors.error, marginBottom: 12 },
  chips: { flexDirection: "row", gap: 8, marginBottom: 8 },
  tagRow: { flexDirection: "row", gap: 8, alignItems: "flex-end", marginBottom: 4 },
}));

const QUICK_TAGS = ["petrol", "staff", "bijli", "rent", "maal", "transport", "khana", "repair", "personal"];

export function TxnForm({
  initial,
  kind = "party",
  onSubmit,
  onDelete,
  submitting,
}: {
  initial?: Transaction;
  kind?: LedgerKind;
  onSubmit: (v: TxnValues) => void;
  onDelete?: () => void;
  submitting?: boolean;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const isAccount = kind === "cash" || kind === "bank";
  const otherKind: TxnMode = kind === "bank" ? "cash" : "bank";
  const otherName = otherKind === "bank" ? "Bank" : "Cash";
  const [direction, setDirection] = useState<Direction>(initial?.direction ?? "debit");
  const [amount, setAmount] = useState(initial ? String(initial.amount) : "");
  const [note, setNote] = useState(initial?.note ?? "");
  const [date, setDate] = useState(initial ? dayjs(initial.entry_date).format("YYYY-MM-DD") : todayISO());
  // existing entries keep their linked cash/bank side unless the user changes it; account ledgers default to no link
  const [mode, setMode] = useState<TxnMode | "keep">(initial ? "keep" : isAccount ? "none" : "cash");
  const [tags, setTags] = useState<string[]>(initial?.tags ?? []);
  const [tagInput, setTagInput] = useState("");
  const [error, setError] = useState("");
  const labels = directionLabels(kind);
  const tagQuery = useQuery({ queryKey: ["tags"], queryFn: () => api.get<TagCount[]>("/tags"), staleTime: 60_000 });
  const quickTags = Array.from(new Set([...(tagQuery.data ?? []).slice(0, 6).map((t) => t.tag), ...QUICK_TAGS, ...tags])).slice(0, 12);

  const toggleTag = (t: string) => setTags((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : cur.length < 5 ? [...cur, t] : cur));
  const addCustomTag = () => {
    const t = tagInput.trim().toLowerCase().replace(/^#/, "");
    if (t) toggleTag(t);
    setTagInput("");
  };

  const submit = () => {
    const amt = parseFloat(amount.replace(/,/g, ""));
    if (!amt || amt <= 0) return setError("Sahi amount daalo");
    if (!dayjs(date, "YYYY-MM-DD", true).isValid() && !/^\d{4}-\d{2}-\d{2}$/.test(date)) return setError("Date YYYY-MM-DD format mein daalo");
    setError("");
    onSubmit({ amount: amt, direction, note: note.trim(), entry_date: date, mode, tags });
  };

  const yesterday = dayjs().subtract(1, "day").format("YYYY-MM-DD");
  const moneyOut = isAccount ? direction === "credit" : direction === "debit";

  return (
    <View>
      <View style={{ marginBottom: 16 }}>
        <Text style={styles.label}>Type</Text>
        <Segmented
          testID="txn-direction"
          value={direction}
          onChange={setDirection}
          options={[
            { value: "debit", label: labels.debit, icon: isAccount ? "arrow-down-left" : "arrow-up-right", color: isAccount ? colors.success : colors.error },
            { value: "credit", label: labels.credit, icon: isAccount ? "arrow-up-right" : "arrow-down-left", color: isAccount ? colors.error : colors.success },
          ]}
        />
      </View>
      <Field testID="txn-amount-input" label="Amount (₹)" mono keyboardType="decimal-pad" value={amount} onChangeText={setAmount} placeholder="0" autoFocus />
      <Field testID="txn-note-input" label="Note" value={note} onChangeText={setNote} placeholder={isAccount ? "e.g. opening balance, ATM withdrawal" : "e.g. salary, advance, cash"} />
      <View style={{ marginBottom: 4 }}>
        <Text style={styles.label}>{isAccount ? (moneyOut ? "Paisa kahan gaya" : "Paisa kahan se aaya") : `Paisa kahan se ${moneyOut ? "gaya" : "aaya"}`}</Text>
        <Segmented
          testID="txn-mode"
          value={mode}
          onChange={(v) => setMode(v as TxnMode | "keep")}
          options={
            isAccount
              ? [
                  ...(initial ? [{ value: "keep", label: initial.via ? `${initial.via} (same)` : "Same", icon: "lock" as const }] : []),
                  { value: "none", label: "Sirf yahan", icon: "minus" },
                  { value: otherKind, label: `${otherName} ${moneyOut ? "me" : "se"}`, icon: otherKind === "bank" ? "landmark" : "wallet" },
                ]
              : [
                  ...(initial ? [{ value: "keep", label: initial.via ? `${initial.via} (same)` : "Koi nahi (same)", icon: "lock" as const }] : []),
                  { value: "cash", label: "Cash", icon: "wallet" },
                  { value: "bank", label: "Bank", icon: "landmark" },
                  { value: "none", label: "Koi nahi", icon: "minus" },
                ]
          }
        />
        <Text style={styles.hint}>
          {mode === "keep"
            ? "Pehle jaisa hi linked rahega; amount/date badle to wahan bhi update hoga."
            : isAccount
              ? mode === "none"
                ? "Sirf is account mein entry (opening balance, kharcha, adjustment)."
                : `Transfer: ${otherName} ${moneyOut ? "me jama hoga" : "se kat jaayega"} aur yahan ${moneyOut ? "se nikla" : "aaya"} — dono side auto.`
              : mode === "none"
                ? "Sirf party ka hisab badlega — Cash/Bank pe asar nahi (opening balance, udhaar maal, salary due)."
                : `Auto: ${mode === "cash" ? "Cash" : "Bank"} account ${moneyOut ? "se kat jaayega" : "mein jud jaayega"} (double entry).`}
        </Text>
      </View>
      <Text style={styles.label}>Category / tags</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips} keyboardShouldPersistTaps="handled">
        {quickTags.map((t) => (
          <Chip key={t} testID={`txn-tag-${t}`} label={`#${t}`} selected={tags.includes(t)} onPress={() => toggleTag(t)} />
        ))}
      </ScrollView>
      <View style={styles.tagRow}>
        <View style={{ flex: 1 }}>
          <Field testID="txn-tag-input" value={tagInput} onChangeText={setTagInput} placeholder="apna tag likho, e.g. mandi" autoCapitalize="none" onSubmitEditing={addCustomTag} returnKeyType="done" />
        </View>
        <Button testID="txn-tag-add" title="Add" variant="secondary" onPress={addCustomTag} disabled={!tagInput.trim()} style={{ marginBottom: 16, height: 48, paddingHorizontal: 16 }} />
      </View>
      <Text style={styles.label}>Date</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        <Chip testID="txn-date-today" label="Aaj" selected={date === todayISO()} onPress={() => setDate(todayISO())} />
        <Chip testID="txn-date-yesterday" label="Kal" selected={date === yesterday} onPress={() => setDate(yesterday)} />
      </ScrollView>
      <Field testID="txn-date-input" mono value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" autoCapitalize="none" />
      {error ? <Text style={styles.error} testID="txn-form-error">{error}</Text> : null}
      <Button testID="txn-submit-button" title={initial ? "Update Entry" : "Save Entry"} onPress={submit} loading={submitting} />
      {onDelete ? <Button testID="txn-delete-button" title="Delete Entry" variant="danger" icon="trash-2" onPress={onDelete} style={{ marginTop: 12 }} /> : null}
    </View>
  );
}
