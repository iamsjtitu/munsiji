import dayjs from "dayjs";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { Button, Chip, Field, Segmented } from "@/src/components/ui";
import { todayISO } from "@/src/format";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import type { Direction, Transaction } from "@/src/types";

export type TxnValues = { amount: number; direction: Direction; note: string; entry_date: string };

const useStyles = makeStyles((colors) => ({
  label: { fontFamily: fonts.text, fontSize: 12, fontWeight: "600", color: colors.muted, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 },
  error: { fontFamily: fonts.text, fontSize: 13, color: colors.error, marginBottom: 12 },
  chips: { flexDirection: "row", gap: 8, marginBottom: 8 },
}));

export function TxnForm({
  initial,
  onSubmit,
  onDelete,
  submitting,
}: {
  initial?: Transaction;
  onSubmit: (v: TxnValues) => void;
  onDelete?: () => void;
  submitting?: boolean;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [direction, setDirection] = useState<Direction>(initial?.direction ?? "debit");
  const [amount, setAmount] = useState(initial ? String(initial.amount) : "");
  const [note, setNote] = useState(initial?.note ?? "");
  const [date, setDate] = useState(initial ? dayjs(initial.entry_date).format("YYYY-MM-DD") : todayISO());
  const [error, setError] = useState("");

  const submit = () => {
    const amt = parseFloat(amount.replace(/,/g, ""));
    if (!amt || amt <= 0) return setError("Sahi amount daalo");
    if (!dayjs(date, "YYYY-MM-DD", true).isValid() && !/^\d{4}-\d{2}-\d{2}$/.test(date)) return setError("Date YYYY-MM-DD format mein daalo");
    setError("");
    onSubmit({ amount: amt, direction, note: note.trim(), entry_date: date });
  };

  const yesterday = dayjs().subtract(1, "day").format("YYYY-MM-DD");

  return (
    <View>
      <View style={{ marginBottom: 16 }}>
        <Text style={styles.label}>Type</Text>
        <Segmented
          testID="txn-direction"
          value={direction}
          onChange={setDirection}
          options={[
            { value: "debit", label: "Diya (Dr)", icon: "arrow-up-right", color: colors.error },
            { value: "credit", label: "Mila (Cr)", icon: "arrow-down-left", color: colors.success },
          ]}
        />
      </View>
      <Field testID="txn-amount-input" label="Amount (₹)" mono keyboardType="decimal-pad" value={amount} onChangeText={setAmount} placeholder="0" autoFocus />
      <Field testID="txn-note-input" label="Note" value={note} onChangeText={setNote} placeholder="e.g. salary, advance, cash" />
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
