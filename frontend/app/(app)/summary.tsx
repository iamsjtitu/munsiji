import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Header } from "@/src/components/Header";
import { Icon } from "@/src/components/Icon";
import { Money } from "@/src/components/Money";
import { Card, Chip, EmptyState } from "@/src/components/ui";
import { monthOptions } from "@/src/format";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import type { MonthlySummary } from "@/src/types";

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  chipRow: { height: 56, gap: 8, paddingHorizontal: 16, alignItems: "center" },
  hero: { margin: 16, padding: 20, borderRadius: 20, backgroundColor: colors.surfaceInverse },
  heroLabel: { fontFamily: fonts.text, fontSize: 12, color: colors.onSurfaceInverse, opacity: 0.6, textTransform: "uppercase", letterSpacing: 0.6 },
  heroRow: { flexDirection: "row", gap: 16, marginTop: 12 },
  heroSmall: { fontFamily: fonts.text, fontSize: 12, color: colors.onSurfaceInverse, opacity: 0.6, marginBottom: 4 },
  section: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: colors.muted, textTransform: "uppercase", letterSpacing: 0.6, marginHorizontal: 16, marginTop: 8, marginBottom: 8 },
  row: { flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingVertical: 12, gap: 12 },
  name: { fontFamily: fonts.text, fontSize: 15, fontWeight: "600", color: colors.onSurface },
  meta: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, marginTop: 2 },
  divider: { height: 1, backgroundColor: colors.divider, marginLeft: 16 },
  small: { fontFamily: fonts.mono, fontSize: 12 },
}));

export default function SummaryScreen() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const months = useMemo(() => monthOptions(12), []);
  const [month, setMonth] = useState(months[0].key);
  const q = useQuery({ queryKey: ["summary", month], queryFn: () => api.get<MonthlySummary>(`/summary/monthly?month=${month}`) });
  const d = q.data;

  return (
    <View style={styles.root} testID="summary-screen">
      <Header title="Monthly Summary">
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow} style={{ flexGrow: 0 }}>
          {months.map((m) => (
            <Chip key={m.key} testID={`summary-month-${m.key}`} label={m.label} selected={month === m.key} onPress={() => setMonth(m.key)} />
          ))}
        </ScrollView>
      </Header>
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}>
        <View style={styles.hero} testID="summary-hero">
          <Text style={styles.heroLabel}>{months.find((m) => m.key === month)?.label}</Text>
          <View style={styles.heroRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.heroSmall}>Diya (Dr)</Text>
              <Money value={d?.total_debit ?? 0} size={22} colored={false} style={{ color: colors.error }} testID="summary-total-debit" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.heroSmall}>Mila (Cr)</Text>
              <Money value={d?.total_credit ?? 0} size={22} colored={false} style={{ color: colors.success }} testID="summary-total-credit" />
            </View>
          </View>
          <Text style={[styles.heroSmall, { marginTop: 12 }]}>Net: <Text style={{ color: colors.onSurfaceInverse, fontFamily: fonts.mono }}>{d ? (d.net >= 0 ? "+" : "-") : ""}₹{Math.abs(d?.net ?? 0).toLocaleString("en-IN")}</Text></Text>
        </View>

        {q.isError ? (
          <Pressable onPress={() => q.refetch()} testID="summary-retry">
            <EmptyState icon="wifi-off" title="Load nahi hua" text="Tap karke retry karo" />
          </Pressable>
        ) : null}
        {d && d.ledgers.length === 0 ? <EmptyState icon="calendar" title="Is mahine koi entry nahi" testID="summary-empty" /> : null}

        {d && d.groups.length > 0 ? (
          <>
            <Text style={styles.section}>By group</Text>
            <Card style={{ marginHorizontal: 16 }}>
              {d.groups.map((g, i) => (
                <View key={g.group_id}>
                  {i > 0 && <View style={styles.divider} />}
                  <Pressable style={styles.row} testID={`summary-group-${g.group_id}`} onPress={() => router.push({ pathname: "/group/[id]", params: { id: g.group_id, name: g.group_name } })}>
                    <Icon name="folder" size={18} color={colors.muted} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.name}>{g.group_name}</Text>
                      <Text style={styles.meta}>{g.count} entries</Text>
                    </View>
                    <View style={{ alignItems: "flex-end" }}>
                      <Text style={[styles.small, { color: colors.error }]}>Dr {g.debit.toLocaleString("en-IN")}</Text>
                      <Text style={[styles.small, { color: colors.success }]}>Cr {g.credit.toLocaleString("en-IN")}</Text>
                    </View>
                  </Pressable>
                </View>
              ))}
            </Card>
            <Text style={[styles.section, { marginTop: 24 }]}>By ledger</Text>
            <Card style={{ marginHorizontal: 16 }}>
              {d.ledgers.map((l, i) => (
                <View key={l.ledger_id}>
                  {i > 0 && <View style={styles.divider} />}
                  <Pressable style={styles.row} testID={`summary-ledger-${l.ledger_id}`} onPress={() => router.push({ pathname: "/ledger/[id]", params: { id: l.ledger_id } })}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.name} numberOfLines={1}>
                        {l.ledger_name}
                      </Text>
                      <Text style={styles.meta}>
                        {l.group_name} · {l.count} entries
                      </Text>
                    </View>
                    <View style={{ alignItems: "flex-end" }}>
                      <Money value={l.net} size={14} />
                      <Text style={styles.meta}>month net</Text>
                    </View>
                  </Pressable>
                </View>
              ))}
            </Card>
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}
