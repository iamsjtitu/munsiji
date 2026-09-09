import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Header, HeaderButton, useHeaderButtonStyle } from "@/src/components/Header";
import { Icon } from "@/src/components/Icon";
import { Money } from "@/src/components/Money";
import { Sheet } from "@/src/components/Sheet";
import { Button, EmptyState, Field } from "@/src/components/ui";
import { DESKTOP_PAD, useIsDesktop } from "@/src/hooks/useLayout";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import type { Group, Ledger } from "@/src/types";

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  listCard: { backgroundColor: colors.surfaceSecondary, borderLeftWidth: 1, borderRightWidth: 1, borderColor: colors.border },
  firstRow: { borderTopWidth: 1, borderTopLeftRadius: 12, borderTopRightRadius: 12 },
  lastRow: { borderBottomWidth: 1, borderBottomLeftRadius: 12, borderBottomRightRadius: 12 },
  searchWrap: { paddingHorizontal: 16, paddingBottom: 12 },
  search: {
    height: 40,
    borderRadius: 10,
    backgroundColor: colors.surfaceTertiary,
    paddingHorizontal: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  searchInput: { flex: 1, fontFamily: fonts.text, fontSize: 14, color: colors.onSurface, height: 40 },
  row: { flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingVertical: 14, gap: 12 },
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: fonts.text, fontSize: 15, fontWeight: "700", color: colors.onSurfaceTertiary },
  name: { fontFamily: fonts.text, fontSize: 15, fontWeight: "600", color: colors.onSurface },
  meta: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, marginTop: 2 },
  label: { fontFamily: fonts.text, fontSize: 11, color: colors.muted, textAlign: "right", marginTop: 2 },
  divider: { height: 1, backgroundColor: colors.divider, marginLeft: 67 },
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
    elevation: 5,
    shadowColor: colors.surfaceInverse,
    shadowOpacity: 0.2,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
  },
  fabText: { fontFamily: fonts.text, fontSize: 15, fontWeight: "700", color: colors.onBrandPrimary },
}));

export default function GroupScreen() {
  const { id, name: groupNameParam } = useLocalSearchParams<{ id: string; name?: string }>();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const isDesktop = useIsDesktop();
  const headerBtn = useHeaderButtonStyle();
  const pad = isDesktop ? DESKTOP_PAD : 16;
  const [q, setQ] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [name, setName] = useState("");
  const [aliases, setAliases] = useState("");

  const groups = useQuery({ queryKey: ["groups"], queryFn: () => api.get<Group[]>("/groups") });
  const group = groups.data?.find((g) => g.id === id);
  const groupName = group?.name ?? groupNameParam ?? "Group";
  const ledgers = useQuery({ queryKey: ["ledgers", id], queryFn: () => api.get<Ledger[]>(`/ledgers?group_id=${id}`) });

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (ledgers.data ?? []).filter((l) => !s || l.name.toLowerCase().includes(s) || l.aliases.some((a) => a.toLowerCase().includes(s)));
  }, [ledgers.data, q]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["ledgers"] });
    qc.invalidateQueries({ queryKey: ["groups"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const addLedger = useMutation({
    mutationFn: () =>
      api.post<Ledger>("/ledgers", {
        name,
        group_id: id,
        aliases: aliases
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      invalidate();
      setAddOpen(false);
      setName("");
      setAliases("");
      toast.show("Ledger ban gaya", "success");
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const rename = useMutation({
    mutationFn: () => api.patch(`/groups/${id}`, { name }),
    onSuccess: () => {
      invalidate();
      setRenameOpen(false);
      toast.show("Group rename ho gaya", "success");
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const remove = useMutation({
    mutationFn: () => api.del(`/groups/${id}`),
    onSuccess: () => {
      invalidate();
      toast.show("Group delete ho gaya", "success");
      router.back();
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  return (
    <View style={styles.root} testID="group-screen">
      <Header
        title={groupName}
        subtitle={`${ledgers.data?.length ?? 0} ledgers`}
        right={
          <>
            {isDesktop ? <Button testID="add-ledger-fab" title="Naya Ledger" icon="plus" onPress={() => setAddOpen(true)} style={headerBtn} /> : null}
            <HeaderButton
              icon="pencil"
              testID="group-rename-button"
              onPress={() => {
                setName(groupName);
                setRenameOpen(true);
              }}
            />
          </>
        }
      >
        <View style={[styles.searchWrap, { paddingHorizontal: pad }]}>
          <View style={[styles.search, isDesktop && { maxWidth: 420 }]}>
            <Icon name="search" size={16} color={colors.muted} />
            <TextInput testID="ledger-search-input" style={styles.searchInput} value={q} onChangeText={setQ} placeholder="Ledger dhundo" placeholderTextColor={colors.muted} />
          </View>
        </View>
      </Header>
      <FlatList
        data={filtered}
        keyExtractor={(l) => l.id}
        refreshControl={<RefreshControl refreshing={ledgers.isFetching && !ledgers.isLoading} onRefresh={() => ledgers.refetch()} tintColor={colors.brandPrimary} />}
        contentContainerStyle={{ padding: pad, paddingBottom: insets.bottom + 96 }}
        ItemSeparatorComponent={() => (
          <View style={styles.listCard}>
            <View style={styles.divider} />
          </View>
        )}
        ListEmptyComponent={
          ledgers.isLoading ? null : ledgers.isError ? (
            <Pressable onPress={() => ledgers.refetch()} testID="ledgers-retry">
              <EmptyState icon="wifi-off" title="Load nahi hua" text="Tap karke retry karo" />
            </Pressable>
          ) : (
            <EmptyState icon="notebook" title="Koi ledger nahi" text={q ? "Search se kuch nahi mila" : "WhatsApp pe entry bhejo ya + Ledger se banao"} testID="ledgers-empty" />
          )
        }
        renderItem={({ item, index }) => (
          <Pressable
            testID={`ledger-row-${item.id}`}
            onPress={() => router.push({ pathname: "/ledger/[id]", params: { id: item.id } })}
            style={({ pressed }) => [
              styles.row,
              styles.listCard,
              index === 0 && styles.firstRow,
              index === filtered.length - 1 && styles.lastRow,
              pressed && { backgroundColor: colors.surfaceTertiary },
            ]}
          >
            <View style={styles.avatar}>
              <Text style={styles.avatarText}>{item.name.slice(0, 1).toUpperCase()}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.name} numberOfLines={1}>
                {item.name}
              </Text>
              {item.aliases.length > 0 ? (
                <Text style={styles.meta} numberOfLines={1}>
                  aka {item.aliases.slice(0, 3).join(", ")}
                </Text>
              ) : null}
            </View>
            <View>
              <Money value={item.current_balance} size={16} />
              <Text style={styles.label}>{item.current_balance > 0 ? "lena hai" : item.current_balance < 0 ? "dena hai" : "settled"}</Text>
            </View>
          </Pressable>
        )}
      />
      {!isDesktop ? (
        <Pressable testID="add-ledger-fab" onPress={() => setAddOpen(true)} style={[styles.fab, { bottom: insets.bottom + 20 }]}>
          <Icon name="plus" size={20} color={colors.onBrandPrimary} />
          <Text style={styles.fabText}>Ledger</Text>
        </Pressable>
      ) : null}

      <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title={`Naya Ledger · ${groupName}`} testID="add-ledger-sheet">
        <Field testID="ledger-name-input" label="Party / Ledger naam" value={name} onChangeText={setName} placeholder="e.g. Biki [Mill]" autoFocus />
        <Field testID="ledger-aliases-input" label="Aliases (comma se alag)" value={aliases} onChangeText={setAliases} placeholder="biki, biki mill" autoCapitalize="none" />
        <Button testID="ledger-save-button" title="Save" onPress={() => addLedger.mutate()} loading={addLedger.isPending} disabled={!name.trim()} />
      </Sheet>

      <Sheet visible={renameOpen} onClose={() => setRenameOpen(false)} title="Group edit" testID="rename-group-sheet">
        <Field testID="group-rename-input" label="Group ka naam" value={name} onChangeText={setName} autoFocus />
        <Button testID="group-rename-save-button" title="Rename" onPress={() => rename.mutate()} loading={rename.isPending} disabled={!name.trim()} />
        <Button
          testID="group-delete-button"
          title="Group delete karo"
          variant="danger"
          icon="trash-2"
          onPress={() => remove.mutate()}
          loading={remove.isPending}
          style={{ marginTop: 12 }}
        />
      </Sheet>
    </View>
  );
}
