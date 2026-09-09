import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { FlatList, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Header, HeaderButton, useHeaderButtonStyle } from "@/src/components/Header";
import { Icon } from "@/src/components/Icon";
import { Money } from "@/src/components/Money";
import { Sheet } from "@/src/components/Sheet";
import { InstallBanner } from "@/src/components/InstallBanner";
import { StatTile } from "@/src/components/StatTile";
import { UpdateBanner } from "@/src/components/UpdateBanner";
import { Button, Card, EmptyState, Field } from "@/src/components/ui";
import { formatDate, formatINR, balanceLabel } from "@/src/format";
import { DESKTOP_PAD, useIsDesktop } from "@/src/hooks/useLayout";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import type { Dashboard, Group, Transaction } from "@/src/types";

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  hero: { marginHorizontal: 16, marginTop: 16, padding: 20, borderRadius: 20, backgroundColor: colors.surfaceInverse },
  heroLabel: { fontFamily: fonts.text, fontSize: 12, color: colors.onSurfaceInverse, opacity: 0.6, textTransform: "uppercase", letterSpacing: 0.6 },
  heroRow: { flexDirection: "row", gap: 16, marginTop: 12 },
  heroCol: { flex: 1 },
  heroSmall: { fontFamily: fonts.text, fontSize: 12, color: colors.onSurfaceInverse, opacity: 0.6, marginBottom: 4 },
  section: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: colors.muted, textTransform: "uppercase", letterSpacing: 0.6, marginHorizontal: 16, marginTop: 24, marginBottom: 8 },
  sectionDesk: { marginHorizontal: 0, marginTop: 0, marginBottom: 12 },
  groupCard: { marginHorizontal: 16, marginBottom: 10, padding: 16, flexDirection: "row", alignItems: "center", gap: 14 },
  groupCardDesk: { flexBasis: "47%", flexGrow: 1 },
  groupCardInnerDesk: { marginHorizontal: 0, marginBottom: 0, padding: 18, borderRadius: 16 },
  groupIcon: { width: 44, height: 44, borderRadius: 12, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  groupName: { fontFamily: fonts.text, fontSize: 16, fontWeight: "700", color: colors.onSurface },
  groupMeta: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, marginTop: 2 },
  recentRow: { flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingVertical: 12, gap: 12 },
  recentName: { fontFamily: fonts.text, fontSize: 14, fontWeight: "600", color: colors.onSurface },
  recentMeta: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, marginTop: 2 },
  fab: {
    position: "absolute",
    right: 16,
    height: 52,
    paddingHorizontal: 20,
    borderRadius: 26,
    backgroundColor: colors.brandPrimary,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    shadowColor: colors.surfaceInverse,
    shadowOpacity: 0.2,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 5,
  },
  fabText: { fontFamily: fonts.text, fontSize: 15, fontWeight: "700", color: colors.onBrandPrimary },
  divider: { height: 1, backgroundColor: colors.divider, marginLeft: 16 },
  // desktop dashboard
  deskBody: { padding: DESKTOP_PAD, gap: 28 },
  statsRow: { flexDirection: "row", gap: 16 },
  deskColumns: { flexDirection: "row", gap: 24, alignItems: "flex-start" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
}));

const GROUP_ICONS: Record<string, React.ComponentProps<typeof Icon>["name"]> = {
  investment: "landmark",
  staff: "users",
  expenses: "receipt",
  personal: "user",
  general: "folder",
  accounts: "wallet",
};

function GroupCard({ item, desktop }: { item: Group; desktop: boolean }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  return (
    <Pressable
      testID={`group-card-${item.id}`}
      onPress={() => router.push({ pathname: "/group/[id]", params: { id: item.id, name: item.name } })}
      style={desktop ? styles.groupCardDesk : undefined}
    >
      {({ pressed }) => (
        <Card style={[styles.groupCard, desktop && styles.groupCardInnerDesk, pressed && { backgroundColor: colors.surfaceTertiary }]}>
          <View style={styles.groupIcon}>
            <Icon name={GROUP_ICONS[item.name.toLowerCase()] ?? "folder"} size={22} color={colors.onBrandTertiary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.groupName} numberOfLines={1}>
              {item.name}
            </Text>
            <Text style={styles.groupMeta}>{item.ledger_count} ledgers</Text>
          </View>
          {desktop ? (
            <View style={{ alignItems: "flex-end" }}>
              <Money value={item.account_balance ?? item.balance} size={16} kind={item.account_balance != null ? "cash" : "party"} />
              <Text style={styles.groupMeta}>{item.account_balance != null ? "in hand" : balanceLabel(item.balance)}</Text>
            </View>
          ) : (
            <Money value={item.account_balance ?? item.balance} size={16} showLabel kind={item.account_balance != null ? "cash" : "party"} />
          )}
          <Icon name="chevron-right" size={18} color={colors.muted} />
        </Card>
      )}
    </Pressable>
  );
}

function RecentList({ recent }: { recent: Transaction[] }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  if (recent.length === 0) return <EmptyState icon="notebook" title="Abhi koi entry nahi" text="WhatsApp pe hisab bhejo ya ledger mein manual entry karo" />;
  return (
    <>
      {recent.map((t, i) => {
        const acct = t.ledger_kind === "cash" || t.ledger_kind === "bank";
        const moneyIn = acct ? t.direction === "debit" : t.direction === "credit";
        const verb = acct ? (t.direction === "debit" ? "Jama" : "Nikla") : t.direction === "debit" ? "Diya" : "Mila";
        return (
          <View key={t.id}>
            {i > 0 && <View style={styles.divider} />}
            <Pressable
              style={({ pressed }) => [styles.recentRow, pressed && { backgroundColor: colors.surfaceTertiary }]}
              testID={`recent-txn-${t.id}`}
              onPress={() => router.push({ pathname: "/ledger/[id]", params: { id: t.ledger_id } })}
            >
              <Icon name={moneyIn ? "arrow-down-left" : "arrow-up-right"} size={18} color={moneyIn ? colors.success : colors.error} />
              <View style={{ flex: 1 }}>
                <Text style={styles.recentName} numberOfLines={1}>
                  {t.ledger_name}
                </Text>
                <Text style={styles.recentMeta} numberOfLines={1}>
                  {formatDate(t.entry_date)} · {t.note || verb} · {t.source}
                  {t.via ? ` · via ${t.via}` : ""}
                  {t.tags?.length ? ` · #${t.tags[0]}` : ""}
                </Text>
              </View>
              <Money value={t.amount} tone={moneyIn ? "credit" : "debit"} size={15} />
            </Pressable>
          </View>
        );
      })}
    </>
  );
}

export default function HomeScreen() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const isDesktop = useIsDesktop();
  const headerBtn = useHeaderButtonStyle();
  const [addOpen, setAddOpen] = useState(false);
  const [name, setName] = useState("");

  const groups = useQuery({ queryKey: ["groups"], queryFn: () => api.get<Group[]>("/groups") });
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("/dashboard") });

  const addGroup = useMutation({
    mutationFn: () => api.post<Group>("/groups", { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["groups"] });
      setAddOpen(false);
      setName("");
      toast.show("Group ban gaya", "success");
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const refreshing = groups.isFetching || dash.isFetching;
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["groups"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const addSheet = (
    <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="Naya Group" testID="add-group-sheet">
      <Field testID="group-name-input" label="Group ka naam" value={name} onChangeText={setName} placeholder="e.g. Suppliers" autoFocus />
      <Button testID="group-save-button" title="Save" onPress={() => addGroup.mutate()} loading={addGroup.isPending} disabled={!name.trim()} />
    </Sheet>
  );

  const groupsEmpty = groups.isError ? (
    <Pressable onPress={refresh} testID="groups-retry">
      <EmptyState icon="wifi-off" title="Load nahi hua" text="Tap karke retry karo" />
    </Pressable>
  ) : !groups.isLoading && (groups.data ?? []).length === 0 ? (
    <EmptyState icon="folder-open" title="Koi group nahi" text="Naya group banao" testID="groups-empty" />
  ) : null;

  if (isDesktop) {
    return (
      <View style={styles.root} testID="home-screen">
        <Header
          title="Dashboard"
          subtitle="Aapka WhatsApp munim — poora hisab ek nazar mein"
          back={false}
          right={<Button testID="add-group-fab" title="Naya Group" icon="plus" onPress={() => setAddOpen(true)} style={headerBtn} />}
        />
        <ScrollView contentContainerStyle={{ paddingBottom: 40 }} refreshControl={<RefreshControl refreshing={refreshing && !groups.isLoading} onRefresh={refresh} tintColor={colors.brandPrimary} />}>
          <UpdateBanner />
          <View style={styles.deskBody}>
            <Animated.View entering={FadeInDown.duration(300)} style={{ gap: 16 }} testID="dashboard-card">
              <View style={styles.statsRow}>
                <StatTile label="Cash in hand" value={dash.data?.cash_in_hand ?? 0} tone="brand" icon="wallet" testID="dashboard-cash" />
                {(dash.data?.bank_balance ?? 0) !== 0 || (dash.data?.accounts ?? []).some((a) => a.kind === "bank") ? (
                  <StatTile label="Bank" value={dash.data?.bank_balance ?? 0} tone="brand" icon="landmark" testID="dashboard-bank" />
                ) : null}
                <StatTile label="Parties" count={dash.data?.ledger_count ?? 0} sub={`${groups.data?.length ?? 0} groups`} tone="neutral" icon="notebook" testID="dashboard-ledger-count" />
              </View>
              <View style={styles.statsRow}>
                <StatTile label="Lena hai" value={dash.data?.total_lena ?? 0} tone="success" icon="arrow-down-left" testID="dashboard-total-lena" />
                <StatTile label="Dena hai" value={dash.data?.total_dena ?? 0} tone="error" icon="arrow-up-right" testID="dashboard-total-dena" />
                <StatTile label="Net (lena − dena)" value={(dash.data?.total_lena ?? 0) - (dash.data?.total_dena ?? 0)} tone="neutral" icon="scale" testID="dashboard-net" />
              </View>
            </Animated.View>
            <View style={styles.deskColumns}>
              <View style={{ flex: 3 }}>
                <Text style={[styles.section, styles.sectionDesk]}>Groups</Text>
                <View style={styles.grid}>
                  {(groups.data ?? []).map((g) => (
                    <GroupCard key={g.id} item={g} desktop />
                  ))}
                </View>
                {groupsEmpty}
              </View>
              <View style={{ flex: 2 }}>
                <Text style={[styles.section, styles.sectionDesk]}>Recent entries</Text>
                <Card>
                  <RecentList recent={dash.data?.recent ?? []} />
                </Card>
              </View>
            </View>
          </View>
        </ScrollView>
        {addSheet}
      </View>
    );
  }

  return (
    <View style={styles.root} testID="home-screen">
      <Header
        title="Munsiji"
        subtitle="Aapka WhatsApp munim"
        back={false}
        right={
          <>
            <HeaderButton icon="message-circle" testID="home-whatsapp-button" onPress={() => router.push("/whatsapp")} />
            <HeaderButton icon="calendar" testID="home-summary-button" onPress={() => router.push("/summary")} />
            <HeaderButton icon="settings" testID="home-settings-button" onPress={() => router.push("/settings")} />
          </>
        }
      />
      <FlatList
        data={groups.data ?? []}
        keyExtractor={(g) => g.id}
        refreshControl={<RefreshControl refreshing={refreshing && !groups.isLoading} onRefresh={refresh} tintColor={colors.brandPrimary} />}
        contentContainerStyle={{ paddingBottom: insets.bottom + 96 }}
        ListHeaderComponent={
          <>
            <UpdateBanner />
            <InstallBanner />
            <Animated.View entering={FadeInDown.duration(300)} style={styles.hero} testID="dashboard-card">
              <Text style={styles.heroLabel}>Cash in hand</Text>
              <Money testID="dashboard-cash" value={dash.data?.cash_in_hand ?? 0} size={30} colored={false} style={{ color: (dash.data?.cash_in_hand ?? 0) < 0 ? colors.error : colors.onSurfaceInverse, marginTop: 4 }} />
              {(dash.data?.accounts ?? []).some((a) => a.kind === "bank") ? (
                <Text style={[styles.heroSmall, { marginTop: 4 }]}>
                  Bank: <Text style={{ color: colors.onSurfaceInverse, fontFamily: fonts.mono }}>{formatINR(dash.data?.bank_balance ?? 0)}</Text>
                </Text>
              ) : null}
              <View style={styles.heroRow}>
                <View style={styles.heroCol}>
                  <Text style={styles.heroSmall}>Lena hai</Text>
                  <Money testID="dashboard-total-lena" value={dash.data?.total_lena ?? 0} size={22} colored={false} style={{ color: colors.success }} />
                </View>
                <View style={styles.heroCol}>
                  <Text style={styles.heroSmall}>Dena hai</Text>
                  <Money testID="dashboard-total-dena" value={dash.data?.total_dena ?? 0} size={22} colored={false} style={{ color: colors.error }} />
                </View>
              </View>
              <Text style={[styles.heroSmall, { marginTop: 12 }]}>{dash.data?.ledger_count ?? 0} parties</Text>
            </Animated.View>
            <Text style={styles.section}>Groups</Text>
            {groups.isError ? groupsEmpty : null}
          </>
        }
        renderItem={({ item, index }) => (
          <Animated.View entering={FadeInDown.delay(index * 40).duration(250)}>
            <GroupCard item={item} desktop={false} />
          </Animated.View>
        )}
        ListEmptyComponent={groups.isError ? null : groupsEmpty}
        ListFooterComponent={
          dash.data && dash.data.recent.length > 0 ? (
            <>
              <Text style={styles.section}>Recent entries</Text>
              <Card style={{ marginHorizontal: 16 }}>
                <RecentList recent={dash.data.recent} />
              </Card>
            </>
          ) : null
        }
      />
      <Pressable testID="add-group-fab" onPress={() => setAddOpen(true)} style={[styles.fab, { bottom: insets.bottom + 20 }]}>
        <Icon name="plus" size={20} color={colors.onBrandPrimary} />
        <Text style={styles.fabText}>Group</Text>
      </Pressable>
      {addSheet}
    </View>
  );
}
