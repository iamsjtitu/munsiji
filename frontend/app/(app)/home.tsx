import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Header, HeaderButton } from "@/src/components/Header";
import { Icon } from "@/src/components/Icon";
import { Money } from "@/src/components/Money";
import { Sheet } from "@/src/components/Sheet";
import { Button, Card, EmptyState, Field } from "@/src/components/ui";
import { formatDate } from "@/src/format";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import type { Dashboard, Group } from "@/src/types";

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  hero: { marginHorizontal: 16, marginTop: 16, padding: 20, borderRadius: 20, backgroundColor: colors.surfaceInverse },
  heroLabel: { fontFamily: fonts.text, fontSize: 12, color: colors.onSurfaceInverse, opacity: 0.6, textTransform: "uppercase", letterSpacing: 0.6 },
  heroRow: { flexDirection: "row", gap: 16, marginTop: 12 },
  heroCol: { flex: 1 },
  heroSmall: { fontFamily: fonts.text, fontSize: 12, color: colors.onSurfaceInverse, opacity: 0.6, marginBottom: 4 },
  section: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: colors.muted, textTransform: "uppercase", letterSpacing: 0.6, marginHorizontal: 16, marginTop: 24, marginBottom: 8 },
  groupCard: { marginHorizontal: 16, marginBottom: 10, padding: 16, flexDirection: "row", alignItems: "center", gap: 14 },
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
}));

const GROUP_ICONS: Record<string, React.ComponentProps<typeof Icon>["name"]> = {
  investment: "landmark",
  staff: "users",
  expenses: "receipt",
  personal: "user",
  general: "folder",
};

export default function HomeScreen() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
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
            <Animated.View entering={FadeInDown.duration(300)} style={styles.hero} testID="dashboard-card">
              <Text style={styles.heroLabel}>Overall</Text>
              <View style={styles.heroRow}>
                <View style={styles.heroCol}>
                  <Text style={styles.heroSmall}>Lena hai</Text>
                  <Money testID="dashboard-total-lena" value={dash.data?.total_lena ?? 0} size={24} colored={false} style={{ color: colors.success }} />
                </View>
                <View style={styles.heroCol}>
                  <Text style={styles.heroSmall}>Dena hai</Text>
                  <Money testID="dashboard-total-dena" value={dash.data?.total_dena ?? 0} size={24} colored={false} style={{ color: colors.error }} />
                </View>
              </View>
              <Text style={[styles.heroSmall, { marginTop: 12 }]}>{dash.data?.ledger_count ?? 0} ledgers</Text>
            </Animated.View>
            <Text style={styles.section}>Groups</Text>
            {groups.isError ? (
              <Pressable onPress={refresh} testID="groups-retry">
                <EmptyState icon="wifi-off" title="Load nahi hua" text="Tap karke retry karo" />
              </Pressable>
            ) : null}
          </>
        }
        renderItem={({ item, index }) => (
          <Animated.View entering={FadeInDown.delay(index * 40).duration(250)}>
            <Pressable testID={`group-card-${item.id}`} onPress={() => router.push({ pathname: "/group/[id]", params: { id: item.id, name: item.name } })}>
              <Card style={styles.groupCard}>
                <View style={styles.groupIcon}>
                  <Icon name={GROUP_ICONS[item.name.toLowerCase()] ?? "folder"} size={22} color={colors.onBrandTertiary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.groupName}>{item.name}</Text>
                  <Text style={styles.groupMeta}>{item.ledger_count} ledgers</Text>
                </View>
                <Money value={item.balance} size={16} showLabel />
                <Icon name="chevron-right" size={18} color={colors.muted} />
              </Card>
            </Pressable>
          </Animated.View>
        )}
        ListEmptyComponent={groups.isLoading || groups.isError ? null : <EmptyState icon="folder-open" title="Koi group nahi" text="Naya group banao" testID="groups-empty" />}
        ListFooterComponent={
          dash.data && dash.data.recent.length > 0 ? (
            <>
              <Text style={styles.section}>Recent entries</Text>
              <Card style={{ marginHorizontal: 16 }}>
                {dash.data.recent.map((t, i) => (
                  <View key={t.id}>
                    {i > 0 && <View style={styles.divider} />}
                    <Pressable style={styles.recentRow} testID={`recent-txn-${t.id}`} onPress={() => router.push({ pathname: "/ledger/[id]", params: { id: t.ledger_id } })}>
                      <Icon name={t.direction === "debit" ? "arrow-up-right" : "arrow-down-left"} size={18} color={t.direction === "debit" ? colors.error : colors.success} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.recentName} numberOfLines={1}>
                          {t.ledger_name}
                        </Text>
                        <Text style={styles.recentMeta} numberOfLines={1}>
                          {formatDate(t.entry_date)} · {t.note || (t.direction === "debit" ? "Diya" : "Mila")} · {t.source}
                        </Text>
                      </View>
                      <Money value={t.amount} tone={t.direction} size={15} />
                    </Pressable>
                  </View>
                ))}
              </Card>
            </>
          ) : null
        }
      />
      <Pressable testID="add-group-fab" onPress={() => setAddOpen(true)} style={[styles.fab, { bottom: insets.bottom + 20 }]}>
        <Icon name="plus" size={20} color={colors.onBrandPrimary} />
        <Text style={styles.fabText}>Group</Text>
      </Pressable>

      <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="Naya Group" testID="add-group-sheet">
        <Field testID="group-name-input" label="Group ka naam" value={name} onChangeText={setName} placeholder="e.g. Suppliers" autoFocus />
        <Button testID="group-save-button" title="Save" onPress={() => addGroup.mutate()} loading={addGroup.isPending} disabled={!name.trim()} />
      </Sheet>
    </View>
  );
}
