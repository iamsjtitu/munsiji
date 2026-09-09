import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Header } from "@/src/components/Header";
import { Icon } from "@/src/components/Icon";
import { Money } from "@/src/components/Money";
import { StatTile } from "@/src/components/StatTile";
import { Card, Chip, EmptyState } from "@/src/components/ui";
import { formatINR, monthOptions } from "@/src/format";
import { DESKTOP_PAD, useIsDesktop } from "@/src/hooks/useLayout";
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
  sectionDesk: { marginHorizontal: 0, marginTop: 0, marginBottom: 12 },
  row: { flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingVertical: 12, gap: 12 },
  name: { fontFamily: fonts.text, fontSize: 15, fontWeight: "600", color: colors.onSurface },
  meta: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, marginTop: 2 },
  divider: { height: 1, backgroundColor: colors.divider, marginLeft: 16 },
  small: { fontFamily: fonts.mono, fontSize: 12 },
  deskBody: { padding: DESKTOP_PAD, gap: 28 },
  statsRow: { flexDirection: "row", gap: 16 },
  deskColumns: { flexDirection: "row", gap: 24, alignItems: "flex-start" },
}));

export default function SummaryScreen() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const isDesktop = useIsDesktop();
  const months = useMemo(() => monthOptions(12), []);
  const [month, setMonth] = useState(months[0].key);
  const q = useQuery({ queryKey: ["summary", month], queryFn: () => api.get<MonthlySummary>(`/summary/monthly?month=${month}`) });
  const d = q.data;
  const monthLabel = months.find((m) => m.key === month)?.label ?? "";

  const groupsCard = d && d.groups.length > 0 ? (
    <Card style={isDesktop ? undefined : { marginHorizontal: 16 }}>
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
  ) : null;

  const ledgersCard = d && d.ledgers.length > 0 ? (
    <Card style={isDesktop ? undefined : { marginHorizontal: 16 }}>
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
  ) : null;

  const accountsCard = d && d.accounts.length > 0 ? (
    <Card style={isDesktop ? undefined : { marginHorizontal: 16 }} testID="summary-accounts">
      {d.accounts.map((a, i) => (
        <View key={a.ledger_id}>
          {i > 0 && <View style={styles.divider} />}
          <Pressable style={styles.row} testID={`summary-account-${a.ledger_id}`} onPress={() => router.push({ pathname: "/ledger/[id]", params: { id: a.ledger_id } })}>
            <Icon name={a.kind === "cash" ? "wallet" : "landmark"} size={18} color={colors.muted} />
            <View style={{ flex: 1 }}>
              <Text style={styles.name}>{a.ledger_name}</Text>
              <Text style={styles.meta}>
                {a.count} entries · abhi {formatINR(a.current_balance)}
              </Text>
            </View>
            <View style={{ alignItems: "flex-end" }}>
              <Text style={[styles.small, { color: colors.success }]}>In {a.in.toLocaleString("en-IN")}</Text>
              <Text style={[styles.small, { color: colors.error }]}>Out {a.out.toLocaleString("en-IN")}</Text>
            </View>
          </Pressable>
        </View>
      ))}
    </Card>
  ) : null;

  const states = (
    <>
      {q.isError ? (
        <Pressable onPress={() => q.refetch()} testID="summary-retry">
          <EmptyState icon="wifi-off" title="Load nahi hua" text="Tap karke retry karo" />
        </Pressable>
      ) : null}
      {d && d.ledgers.length === 0 && d.accounts.length === 0 ? <EmptyState icon="calendar" title="Is mahine koi entry nahi" testID="summary-empty" /> : null}
    </>
  );

  return (
    <View style={styles.root} testID="summary-screen">
      <Header title="Monthly Summary" back={!isDesktop} subtitle={isDesktop ? "Mahine ka Dr / Cr hisab, group aur ledger wise" : undefined}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={[styles.chipRow, isDesktop && { paddingHorizontal: DESKTOP_PAD }]} style={{ flexGrow: 0 }}>
          {months.map((m) => (
            <Chip key={m.key} testID={`summary-month-${m.key}`} label={m.label} selected={month === m.key} onPress={() => setMonth(m.key)} />
          ))}
        </ScrollView>
      </Header>
      {isDesktop ? (
        <ScrollView contentContainerStyle={[styles.deskBody, { paddingBottom: 40 }]}>
          <View style={styles.statsRow} testID="summary-hero">
            <StatTile label={`Diya (Dr) · ${monthLabel}`} value={d?.total_debit ?? 0} tone="error" icon="arrow-up-right" testID="summary-total-debit" />
            <StatTile label={`Mila (Cr) · ${monthLabel}`} value={d?.total_credit ?? 0} tone="success" icon="arrow-down-left" testID="summary-total-credit" />
            <StatTile label="Net" value={d?.net ?? 0} tone="brand" icon="scale" sub={d ? (d.net >= 0 ? "lena hai" : "dena hai") : undefined} />
          </View>
          {states}
          {groupsCard || ledgersCard ? (
            <View style={styles.deskColumns}>
              <View style={{ flex: 1 }}>
                <Text style={[styles.section, styles.sectionDesk]}>By group</Text>
                {groupsCard}
                {accountsCard ? (
                  <>
                    <Text style={[styles.section, styles.sectionDesk, { marginTop: 24 }]}>Cash / Bank</Text>
                    {accountsCard}
                  </>
                ) : null}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[styles.section, styles.sectionDesk]}>By ledger</Text>
                {ledgersCard}
              </View>
            </View>
          ) : accountsCard ? (
            <View>
              <Text style={[styles.section, styles.sectionDesk]}>Cash / Bank</Text>
              {accountsCard}
            </View>
          ) : null}
        </ScrollView>
      ) : (
        <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}>
          <View style={styles.hero} testID="summary-hero">
            <Text style={styles.heroLabel}>{monthLabel}</Text>
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
          {states}
          {groupsCard ? (
            <>
              <Text style={styles.section}>By group</Text>
              {groupsCard}
              <Text style={[styles.section, { marginTop: 24 }]}>By ledger</Text>
              {ledgersCard}
            </>
          ) : null}
          {accountsCard ? (
            <>
              <Text style={[styles.section, { marginTop: 24 }]}>Cash / Bank</Text>
              {accountsCard}
            </>
          ) : null}
        </ScrollView>
      )}
    </View>
  );
}
