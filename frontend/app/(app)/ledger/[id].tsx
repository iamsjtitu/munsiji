import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { FlatList, Linking, Pressable, RefreshControl, ScrollView, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Header, HeaderButton, useHeaderButtonStyle } from "@/src/components/Header";
import { Icon } from "@/src/components/Icon";
import { Money } from "@/src/components/Money";
import { Sheet } from "@/src/components/Sheet";
import { TxnForm, type TxnValues } from "@/src/components/TxnForm";
import { Button, Chip, Divider, EmptyState, Field, MenuRow, Segmented } from "@/src/components/ui";
import { formatDate, formatINR, monthOptions } from "@/src/format";
import { DESKTOP_PAD, useIsDesktop } from "@/src/hooks/useLayout";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import type { Group, Ledger, Statement, Transaction } from "@/src/types";

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  balanceBar: { paddingHorizontal: 16, paddingBottom: 12, flexDirection: "row", alignItems: "flex-end", justifyContent: "space-between" },
  balLabel: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, marginBottom: 2 },
  actions: { flexDirection: "row", gap: 8 },
  actionBtn: { height: 40, paddingHorizontal: 12, borderRadius: 10, backgroundColor: colors.surfaceTertiary, flexDirection: "row", alignItems: "center", gap: 6 },
  actionText: { fontFamily: fonts.text, fontSize: 13, fontWeight: "600", color: colors.onSurface },
  chipRow: { height: 56, gap: 8, paddingHorizontal: 16, alignItems: "center" },
  tableHead: { flexDirection: "row", paddingHorizontal: 16, paddingVertical: 8, backgroundColor: colors.surfaceTertiary, borderBottomWidth: 1, borderBottomColor: colors.border },
  th: { fontFamily: fonts.text, fontSize: 11, fontWeight: "700", color: colors.muted, textTransform: "uppercase", letterSpacing: 0.4 },
  row: { flexDirection: "row", paddingHorizontal: 16, paddingVertical: 10, alignItems: "center", backgroundColor: colors.surfaceSecondary },
  colDate: { width: 56 },
  colPart: { flex: 1, paddingRight: 8 },
  colAmt: { width: 92, alignItems: "flex-end" },
  colBal: { width: 96, alignItems: "flex-end" },
  colDateDesk: { width: 90 },
  colAmtDesk: { width: 140 },
  colBalDesk: { width: 150 },
  date: { fontFamily: fonts.mono, fontSize: 11, color: colors.muted },
  dateDay: { fontFamily: fonts.mono, fontSize: 14, color: colors.onSurface },
  particulars: { fontFamily: fonts.text, fontSize: 14, color: colors.onSurface },
  source: { fontFamily: fonts.text, fontSize: 11, color: colors.muted, marginTop: 1 },
  drcr: { fontFamily: fonts.text, fontSize: 10, color: colors.muted },
  openRow: { flexDirection: "row", paddingHorizontal: 16, paddingVertical: 10, justifyContent: "space-between", backgroundColor: colors.surfaceSecondary },
  openText: { fontFamily: fonts.text, fontSize: 13, color: colors.muted, fontStyle: "italic" },
  totals: { flexDirection: "row", paddingHorizontal: 16, paddingVertical: 12, backgroundColor: colors.surfaceTertiary, borderTopWidth: 1, borderTopColor: colors.border },
  totalLabel: { fontFamily: fonts.text, fontSize: 12, fontWeight: "700", color: colors.onSurface },
  divider: { height: 1, backgroundColor: colors.divider },
  fab: {
    position: "absolute",
    right: 16,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
    elevation: 5,
    shadowColor: colors.surfaceInverse,
    shadowOpacity: 0.2,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
  },
  pickRow: { flexDirection: "row", alignItems: "center", paddingVertical: 12, gap: 12 },
  pickText: { flex: 1, fontFamily: fonts.text, fontSize: 15, color: colors.onSurface },
  hint: { fontFamily: fonts.text, fontSize: 13, color: colors.muted, marginBottom: 12, lineHeight: 19 },
  switchRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 12, marginBottom: 8 },
  switchText: { fontFamily: fonts.text, fontSize: 15, color: colors.onSurface },
  link: { flexDirection: "row", alignItems: "center", gap: 8, padding: 12, borderRadius: 10, backgroundColor: colors.brandTertiary, marginTop: 12 },
  linkText: { flex: 1, fontFamily: fonts.text, fontSize: 14, color: colors.onBrandTertiary, fontWeight: "600" },
}));

type SheetMode = null | "add" | "edit" | "export" | "menu" | "rename" | "move" | "merge" | "kind";
type ExportFormat = "pdf" | "excel" | "csv";

export default function LedgerScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const isDesktop = useIsDesktop();
  const headerBtn = useHeaderButtonStyle();
  const padX = { paddingHorizontal: isDesktop ? DESKTOP_PAD : 16 };
  const colDate = [styles.colDate, isDesktop && styles.colDateDesk];
  const colAmt = [styles.colAmt, isDesktop && styles.colAmtDesk];
  const colBal = [styles.colBal, isDesktop && styles.colBalDesk];
  const openExport = () => {
    setExportUrl(null);
    setMode("export");
  };

  const [month, setMonth] = useState<string>("all");
  const [mode, setMode] = useState<SheetMode>(null);
  const [editing, setEditing] = useState<Transaction | null>(null);
  const [fmt, setFmt] = useState<ExportFormat>("pdf");
  const [sendWa, setSendWa] = useState(false);
  const [exportUrl, setExportUrl] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [search, setSearch] = useState("");

  const months = useMemo(() => monthOptions(12), []);
  const stmtQuery = useQuery({
    queryKey: ["statement", id, month],
    queryFn: () => api.get<Statement>(`/ledgers/${id}/statement${month === "all" ? "" : `?month=${month}`}`),
  });
  const groups = useQuery({ queryKey: ["groups"], queryFn: () => api.get<Group[]>("/groups") });
  const allLedgers = useQuery({ queryKey: ["ledgers", "all"], queryFn: () => api.get<Ledger[]>("/ledgers"), enabled: mode === "merge" });

  const stmt = stmtQuery.data;
  const ledger = stmt?.ledger;
  const kind = ledger?.kind ?? "party";
  const isAccount = kind === "cash" || kind === "bank";
  const groupName = groups.data?.find((g) => g.id === ledger?.group_id)?.name ?? "";

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["statement"] }); // also refreshes the linked Cash/Bank statement
    qc.invalidateQueries({ queryKey: ["ledgers"] });
    qc.invalidateQueries({ queryKey: ["groups"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const onErr = (e: Error) => toast.show(e.message, "error");

  const addTxn = useMutation({
    mutationFn: (v: TxnValues) => api.post("/transactions", { ...v, ledger_id: id }),
    onSuccess: () => {
      invalidateAll();
      setMode(null);
      toast.show("Entry save ho gayi", "success");
    },
    onError: onErr,
  });
  const editTxn = useMutation({
    mutationFn: (v: TxnValues) => api.patch(`/transactions/${editing?.id}`, v),
    onSuccess: () => {
      invalidateAll();
      setMode(null);
      toast.show("Entry update ho gayi", "success");
    },
    onError: onErr,
  });
  const delTxn = useMutation({
    mutationFn: () => api.del(`/transactions/${editing?.id}`),
    onSuccess: () => {
      invalidateAll();
      setMode(null);
      toast.show("Entry delete ho gayi", "success");
    },
    onError: onErr,
  });
  const exportMut = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { format: fmt, send_whatsapp: sendWa };
      if (month !== "all") {
        const [y, m] = month.split("-").map(Number);
        body.date_from = `${month}-01`;
        const last = new Date(y, m, 0).getDate();
        body.date_to = `${month}-${String(last).padStart(2, "0")}`;
      }
      return api.post<{ url: string; sent: boolean; send_error?: string }>(`/ledgers/${id}/export`, body);
    },
    onSuccess: (d) => {
      setExportUrl(d.url);
      if (sendWa) toast.show(d.sent ? "WhatsApp pe bhej diya" : `WhatsApp send fail: ${d.send_error ?? ""}`, d.sent ? "success" : "error");
      else toast.show("File ready hai", "success");
    },
    onError: onErr,
  });
  const patchLedger = useMutation({
    mutationFn: (body: Partial<Ledger>) => api.patch(`/ledgers/${id}`, body),
    onSuccess: () => {
      invalidateAll();
      setMode(null);
      toast.show("Ledger update ho gaya", "success");
    },
    onError: onErr,
  });
  const mergeMut = useMutation({
    mutationFn: (target: string) => api.post(`/ledgers/${id}/merge`, { target_ledger_id: target }),
    onSuccess: () => {
      invalidateAll();
      setMode(null);
      toast.show("Merge ho gaya", "success");
      router.back();
    },
    onError: onErr,
  });
  const delLedger = useMutation({
    mutationFn: () => api.del(`/ledgers/${id}`),
    onSuccess: () => {
      invalidateAll();
      setMode(null);
      toast.show("Ledger delete ho gaya", "success");
      router.back();
    },
    onError: onErr,
  });

  const rows = stmt?.rows ?? [];
  const mergeCandidates = (allLedgers.data ?? []).filter((l) => l.id !== id && (!search || l.name.toLowerCase().includes(search.toLowerCase())));

  return (
    <View style={styles.root} testID="ledger-screen">
      <Header
        title={ledger?.name ?? "Ledger"}
        subtitle={groupName ? `${groupName}${ledger?.aliases.length ? ` · aka ${ledger.aliases.slice(0, 2).join(", ")}` : ""}` : undefined}
        right={
          <>
            {isDesktop ? <Button testID="ledger-export-button" title="Export" icon="file-down" variant="secondary" onPress={openExport} style={headerBtn} /> : null}
            {isDesktop ? <Button testID="add-txn-fab" title="Nayi Entry" icon="plus" onPress={() => setMode("add")} style={headerBtn} /> : null}
            <HeaderButton icon="more-vertical" testID="ledger-menu-button" onPress={() => setMode("menu")} />
          </>
        }
      >
        <View style={[styles.balanceBar, padX]}>
          <View>
            <Text style={styles.balLabel}>{month === "all" ? "Current balance" : "Closing balance"}</Text>
            <Money testID="ledger-balance" value={stmt?.closing_balance ?? ledger?.current_balance ?? 0} size={isDesktop ? 30 : 26} showLabel kind={ledger?.kind ?? "party"} />
          </View>
          {!isDesktop ? (
            <View style={styles.actions}>
              <Pressable testID="ledger-export-button" style={styles.actionBtn} onPress={openExport}>
                <Icon name="file-down" size={16} color={colors.onSurface} />
                <Text style={styles.actionText}>Export</Text>
              </Pressable>
            </View>
          ) : null}
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={[styles.chipRow, padX]} style={{ flexGrow: 0 }}>
          <Chip testID="month-chip-all" label="All" selected={month === "all"} onPress={() => setMonth("all")} />
          {months.map((m) => (
            <Chip key={m.key} testID={`month-chip-${m.key}`} label={m.label} selected={month === m.key} onPress={() => setMonth(m.key)} />
          ))}
        </ScrollView>
        <View style={[styles.tableHead, padX]}>
          <Text style={[styles.th, ...colDate]}>Date</Text>
          <Text style={[styles.th, styles.colPart]}>Particulars</Text>
          <Text style={[styles.th, ...colAmt, { textAlign: "right" }]}>{isAccount ? "In / Out" : "Dr / Cr"}</Text>
          <Text style={[styles.th, ...colBal, { textAlign: "right" }]}>Balance</Text>
        </View>
      </Header>

      <FlatList
        data={rows}
        keyExtractor={(t) => t.id}
        refreshControl={<RefreshControl refreshing={stmtQuery.isFetching && !stmtQuery.isLoading} onRefresh={() => stmtQuery.refetch()} tintColor={colors.brandPrimary} />}
        contentContainerStyle={{ paddingBottom: insets.bottom + 96 }}
        ItemSeparatorComponent={() => <View style={styles.divider} />}
        ListHeaderComponent={
          stmt && month !== "all" ? (
            <View style={[styles.openRow, padX]}>
              <Text style={styles.openText}>Opening balance</Text>
              <Money value={stmt.opening_balance} size={13} />
            </View>
          ) : null
        }
        ListEmptyComponent={
          stmtQuery.isLoading ? null : stmtQuery.isError ? (
            <Pressable onPress={() => stmtQuery.refetch()} testID="statement-retry">
              <EmptyState icon="wifi-off" title="Load nahi hua" text="Tap karke retry karo" />
            </Pressable>
          ) : (
            <EmptyState icon="notebook" title="Koi entry nahi" text="WhatsApp pe bhejo ya + se manual entry karo" testID="statement-empty" />
          )
        }
        renderItem={({ item }) => (
          <Pressable
            testID={`txn-row-${item.id}`}
            onPress={() => {
              setEditing(item);
              setMode("edit");
            }}
            style={({ pressed }) => [styles.row, padX, pressed && { backgroundColor: colors.surfaceTertiary }]}
          >
            <View style={colDate}>
              <Text style={styles.dateDay}>{formatDate(item.entry_date, "DD")}</Text>
              <Text style={styles.date}>{formatDate(item.entry_date, "MMM YY")}</Text>
            </View>
            <View style={styles.colPart}>
              <Text style={styles.particulars} numberOfLines={2}>
                {item.note || (isAccount ? (item.direction === "debit" ? "Jama" : "Nikla") : item.direction === "debit" ? "Diya" : "Mila")}
              </Text>
              <Text style={styles.source}>
                {item.source === "whatsapp" ? "via WhatsApp" : item.source === "simulate" ? "via test chat" : "manual"}
                {item.via ? ` · ${isAccount ? "↔" : "from"} ${item.via}` : ""}
                {item.tags?.length ? ` · ${item.tags.map((t) => `#${t}`).join(" ")}` : ""}
              </Text>
            </View>
            <View style={colAmt}>
              <Money value={item.amount} tone={isAccount ? (item.direction === "debit" ? "credit" : "debit") : item.direction} size={isDesktop ? 15 : 14} />
              <Text style={styles.drcr}>{isAccount ? (item.direction === "debit" ? "In" : "Out") : item.direction === "debit" ? "Dr" : "Cr"}</Text>
            </View>
            <View style={colBal}>
              <Money value={item.running_balance ?? 0} size={isDesktop ? 15 : 14} colored={false} />
            </View>
          </Pressable>
        )}
        ListFooterComponent={
          stmt && rows.length > 0 ? (
            <View style={[styles.totals, padX]} testID="statement-totals">
              <Text style={[styles.totalLabel, { flex: 1 }]}>Total</Text>
              <View style={{ alignItems: "flex-end", width: 110 }}>
                <Text style={{ fontFamily: fonts.mono, fontSize: 12, color: colors.error }}>Dr {formatINR(stmt.total_debit, false)}</Text>
                <Text style={{ fontFamily: fonts.mono, fontSize: 12, color: colors.success }}>Cr {formatINR(stmt.total_credit, false)}</Text>
              </View>
            </View>
          ) : null
        }
      />

      {!isDesktop ? (
        <Pressable testID="add-txn-fab" onPress={() => setMode("add")} style={[styles.fab, { bottom: insets.bottom + 20 }]}>
          <Icon name="plus" size={26} color={colors.onBrandPrimary} />
        </Pressable>
      ) : null}

      <Sheet visible={mode === "add"} onClose={() => setMode(null)} title={isAccount ? `${ledger?.name} Entry` : "Manual Entry"} testID="add-txn-sheet">
        <TxnForm kind={kind} onSubmit={(v) => addTxn.mutate(v)} submitting={addTxn.isPending} />
      </Sheet>

      <Sheet visible={mode === "edit"} onClose={() => setMode(null)} title="Entry Edit" testID="edit-txn-sheet">
        {editing ? <TxnForm kind={kind} initial={editing} onSubmit={(v) => editTxn.mutate(v)} onDelete={() => delTxn.mutate()} submitting={editTxn.isPending || delTxn.isPending} /> : null}
        {editing?.via ? <Text style={styles.hint}>Ye entry {editing.via} se linked hai — delete karne pe wahan se bhi hat jaayegi.</Text> : null}
      </Sheet>

      <Sheet visible={mode === "export"} onClose={() => setMode(null)} title="Statement Export" testID="export-sheet">
        <Text style={styles.hint}>{month === "all" ? "Poora ledger export hoga." : `${months.find((m) => m.key === month)?.label} ka statement export hoga.`}</Text>
        <Segmented
          testID="export-format"
          value={fmt}
          onChange={setFmt}
          options={[
            { value: "pdf", label: "PDF" },
            { value: "excel", label: "Excel" },
            { value: "csv", label: "CSV" },
          ]}
        />
        <View style={styles.switchRow}>
          <Text style={styles.switchText}>WhatsApp pe bhi bhejo</Text>
          <Switch testID="export-send-whatsapp-switch" value={sendWa} onValueChange={setSendWa} trackColor={{ true: colors.brandPrimary, false: colors.border }} />
        </View>
        <Button testID="export-generate-button" title="Generate" icon="file-down" onPress={() => exportMut.mutate()} loading={exportMut.isPending} />
        {exportUrl ? (
          <Pressable testID="export-open-link" style={styles.link} onPress={() => Linking.openURL(exportUrl)}>
            <Icon name="download" size={18} color={colors.onBrandTertiary} />
            <Text style={styles.linkText}>File download / open karo</Text>
            <Icon name="chevron-right" size={18} color={colors.onBrandTertiary} />
          </Pressable>
        ) : null}
      </Sheet>

      <Sheet visible={mode === "menu"} onClose={() => setMode(null)} title="Ledger Options" testID="ledger-menu-sheet">
        <MenuRow
          icon="pencil"
          label="Rename ledger"
          testID="ledger-rename-option"
          onPress={() => {
            setNewName(ledger?.name ?? "");
            setMode("rename");
          }}
        />
        <Divider />
        <MenuRow icon="folder" label="Group change karo" testID="ledger-move-option" onPress={() => setMode("move")} />
        <Divider />
        <MenuRow
          icon={isAccount ? "user" : "wallet"}
          label={isAccount ? "Party ledger banao (Cash/Bank nahi)" : "Ye Cash/Bank account hai"}
          testID="ledger-kind-option"
          onPress={() => setMode("kind")}
        />
        <Divider />
        <MenuRow
          icon="git-merge"
          label="Dusre ledger mein merge karo"
          testID="ledger-merge-option"
          onPress={() => {
            setSearch("");
            setMode("merge");
          }}
        />
        <Divider />
        <MenuRow icon="trash-2" label="Ledger delete karo" danger testID="ledger-delete-option" onPress={() => delLedger.mutate()} />
      </Sheet>

      <Sheet visible={mode === "rename"} onClose={() => setMode(null)} title="Rename Ledger" testID="rename-ledger-sheet">
        <Field testID="ledger-rename-input" label="Naya naam" value={newName} onChangeText={setNewName} autoFocus />
        <Button testID="ledger-rename-save" title="Save" onPress={() => patchLedger.mutate({ name: newName })} loading={patchLedger.isPending} disabled={!newName.trim()} />
      </Sheet>

      <Sheet visible={mode === "kind"} onClose={() => setMode(null)} title="Ledger ka type" testID="ledger-kind-sheet">
        <Text style={styles.hint}>
          Party = insaan/firm (lena hai / dena hai). Cash / Bank = aapka paisa jahan rakha hai — party entries ka paisa automatically yahan se jud/kat jaata hai.
        </Text>
        <Segmented
          testID="ledger-kind"
          value={kind}
          onChange={(v) => patchLedger.mutate({ kind: v })}
          options={[
            { value: "party", label: "Party", icon: "user" },
            { value: "cash", label: "Cash", icon: "wallet" },
            { value: "bank", label: "Bank", icon: "landmark" },
          ]}
        />
      </Sheet>

      <Sheet visible={mode === "move"} onClose={() => setMode(null)} title="Group Select Karo" testID="move-ledger-sheet">
        {(groups.data ?? []).map((g) => (
          <Pressable key={g.id} testID={`move-group-${g.id}`} style={styles.pickRow} onPress={() => patchLedger.mutate({ group_id: g.id })}>
            <Icon name={g.id === ledger?.group_id ? "check" : "folder"} size={20} color={g.id === ledger?.group_id ? colors.brandPrimary : colors.muted} />
            <Text style={styles.pickText}>{g.name}</Text>
          </Pressable>
        ))}
      </Sheet>

      <Sheet visible={mode === "merge"} onClose={() => setMode(null)} title="Merge Into" testID="merge-ledger-sheet">
        <Text style={styles.hint}>Is ledger ki saari entries chune gaye ledger mein chali jaayengi aur balance auto-recalculate hoga. Ye ledger uska alias ban jaayega.</Text>
        <Field testID="merge-search-input" value={search} onChangeText={setSearch} placeholder="Ledger dhundo" />
        {mergeCandidates.slice(0, 30).map((l) => (
          <Pressable key={l.id} testID={`merge-target-${l.id}`} style={styles.pickRow} onPress={() => mergeMut.mutate(l.id)} disabled={mergeMut.isPending}>
            <Icon name="git-merge" size={18} color={colors.muted} />
            <Text style={styles.pickText}>{l.name}</Text>
            <Money value={l.current_balance} size={13} />
          </Pressable>
        ))}
        {mergeCandidates.length === 0 && !allLedgers.isLoading ? <Text style={styles.hint}>Koi dusra ledger nahi mila.</Text> : null}
      </Sheet>
    </View>
  );
}
