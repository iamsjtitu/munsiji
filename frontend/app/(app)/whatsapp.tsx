import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Linking, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Header, HeaderButton } from "@/src/components/Header";
import { Icon } from "@/src/components/Icon";
import { EmptyState } from "@/src/components/ui";
import { WaDiagnosticsSheet } from "@/src/components/WaDiagnostics";
import { formatDate } from "@/src/format";
import { DESKTOP_PAD, useIsDesktop } from "@/src/hooks/useLayout";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import type { WaMessage, WaStatus } from "@/src/types";

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  banner: { marginHorizontal: 16, marginBottom: 8, padding: 10, borderRadius: 10, flexDirection: "row", alignItems: "center", gap: 8 },
  bannerOk: { backgroundColor: colors.brandTertiary },
  bannerWarn: { backgroundColor: colors.surfaceTertiary },
  bannerText: { flex: 1, fontFamily: fonts.text, fontSize: 12, color: colors.onSurfaceTertiary, lineHeight: 17 },
  list: { padding: 16, gap: 10 },
  bubbleIn: { alignSelf: "flex-end", maxWidth: "82%", backgroundColor: colors.brandSecondary, borderRadius: 16, borderBottomRightRadius: 4, paddingHorizontal: 14, paddingVertical: 10 },
  bubbleOut: { alignSelf: "flex-start", maxWidth: "88%", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: 16, borderBottomLeftRadius: 4, paddingHorizontal: 14, paddingVertical: 10 },
  bubbleDesk: { maxWidth: "65%" },
  inText: { fontFamily: fonts.text, fontSize: 15, color: colors.onBrandSecondary, lineHeight: 21 },
  outText: { fontFamily: fonts.text, fontSize: 15, color: colors.onSurface, lineHeight: 21 },
  meta: { fontFamily: fonts.text, fontSize: 10, color: colors.muted, marginTop: 4 },
  file: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8, padding: 8, borderRadius: 8, backgroundColor: colors.brandTertiary },
  fileText: { fontFamily: fonts.text, fontSize: 13, color: colors.onBrandTertiary, fontWeight: "600" },
  inputBar: { flexDirection: "row", alignItems: "flex-end", gap: 8, paddingHorizontal: 12, paddingTop: 8, backgroundColor: colors.surfaceSecondary, borderTopWidth: 1, borderTopColor: colors.border },
  input: { flex: 1, minHeight: 44, maxHeight: 120, borderRadius: 22, backgroundColor: colors.surfaceTertiary, paddingHorizontal: 16, paddingVertical: 11, fontFamily: fonts.text, fontSize: 15, color: colors.onSurface },
  send: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  status: { fontFamily: fonts.text, fontSize: 10, color: colors.muted, marginTop: 2, alignSelf: "flex-start" },
}));

export default function WhatsAppScreen() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const qc = useQueryClient();
  const toast = useToast();
  const isDesktop = useIsDesktop();
  const [text, setText] = useState("");
  const [diagOpen, setDiagOpen] = useState(false);
  const scroll = useRef<ScrollView>(null);

  const messages = useQuery({ queryKey: ["wa-messages"], queryFn: () => api.get<WaMessage[]>("/whatsapp/messages?limit=60"), refetchInterval: 8000 });
  const status = useQuery({ queryKey: ["wa-status"], queryFn: () => api.get<WaStatus>("/whatsapp/status"), refetchInterval: 15000 });

  const send = useMutation({
    mutationFn: (t: string) => api.post<{ reply: string | null; status: string }>("/whatsapp/simulate", { text: t }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wa-messages"] });
      qc.invalidateQueries({ queryKey: ["wa-status"] });
      qc.invalidateQueries({ queryKey: ["groups"] });
      qc.invalidateQueries({ queryKey: ["ledgers"] });
      qc.invalidateQueries({ queryKey: ["statement"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  useEffect(() => {
    const t = setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 100);
    return () => clearTimeout(t);
  }, [messages.data?.length, send.isPending]);

  const submit = () => {
    const t = text.trim();
    if (!t) return;
    setText("");
    send.mutate(t);
  };

  const s = status.data;
  const live = s?.provider === "wa9x";
  const liveOk = live && s?.configured;

  return (
    <View style={styles.root} testID="whatsapp-screen">
      <Header
        title="WhatsApp Munim"
        subtitle={s ? `${live ? "wa.9x live" : "Mock mode"} · ${s.owner_number}` : undefined}
        back={!isDesktop}
        right={<HeaderButton icon="activity" testID="wa-diagnostics-button" onPress={() => setDiagOpen(true)} />}
      />
      <KeyboardAvoidingView behavior="translate-with-padding" style={{ flex: 1 }} keyboardVerticalOffset={0}>
        <ScrollView ref={scroll} contentContainerStyle={[styles.list, isDesktop && { padding: DESKTOP_PAD }]} keyboardShouldPersistTaps="handled" testID="wa-message-list">
          {s ? (
            <Pressable onPress={() => setDiagOpen(true)} style={[styles.banner, liveOk ? styles.bannerOk : styles.bannerWarn]} testID="wa-status-banner">
              <Icon name={liveOk ? "check" : "info"} size={16} color={colors.onSurfaceTertiary} />
              <Text style={styles.bannerText}>
                {liveOk
                  ? s.last_webhook_at
                    ? `wa.9x connected · last webhook ${formatDate(s.last_webhook_at, "DD MMM, HH:mm")} (${s.webhook_hits_24h} hits/24h). Yahan type karke bot test bhi kar sakte ho.`
                    : "wa.9x key set hai, par abhi tak koi webhook nahi aaya. Tap karke connection check karo."
                  : live
                    ? "wa.9x live hai par API key set nahi — Settings → WhatsApp mein daalo."
                    : "Mock mode: wa.9x key Settings mein daalo. Tab tak yahan type karke bot test karo — entries real ledger mein jaati hain."}
              </Text>
              <Icon name="chevron-right" size={16} color={colors.muted} />
            </Pressable>
          ) : null}
          {s?.pending_question ? (
            <View style={[styles.banner, styles.bannerWarn]} testID="wa-pending-banner">
              <Icon name="circle-alert" size={16} color={colors.warning} />
              <Text style={styles.bannerText}>Bot jawab ka wait kar raha hai: {s.pending_question}</Text>
            </View>
          ) : null}
          {messages.data?.length === 0 ? (
            <EmptyState icon="message-circle" title="Abhi koi message nahi" text={'Try karo: "Biki [Mill] - 50000, Investment account"'} testID="wa-empty" />
          ) : null}
          {(messages.data ?? []).map((m) => (
            <View key={m.id} testID={`wa-msg-${m.id}`}>
              <View style={[styles.bubbleIn, isDesktop && styles.bubbleDesk]}>
                <Text style={styles.inText}>{m.text}</Text>
                <Text style={[styles.meta, { textAlign: "right" }]}>
                  {formatDate(m.created_at, "DD MMM, HH:mm")} · {m.source === "simulate" ? "test" : "whatsapp"}
                </Text>
              </View>
              {m.reply ? (
                <View style={[styles.bubbleOut, isDesktop && styles.bubbleDesk, { marginTop: 6 }]}>
                  <Text style={styles.outText}>{m.reply}</Text>
                  {m.files?.map((f) => (
                    <Pressable key={f.url} style={styles.file} onPress={() => Linking.openURL(f.url)} testID="wa-file-link">
                      <Icon name="file-down" size={16} color={colors.onBrandTertiary} />
                      <Text style={styles.fileText}>{f.filename}</Text>
                    </Pressable>
                  ))}
                  {m.status !== "processed" ? <Text style={styles.status}>{m.status}</Text> : null}
                </View>
              ) : null}
            </View>
          ))}
          {send.isPending ? (
            <View style={styles.bubbleOut}>
              <Text style={[styles.outText, { color: colors.muted }]}>Munsiji soch raha hai…</Text>
            </View>
          ) : null}
        </ScrollView>
        <View style={[styles.inputBar, { paddingBottom: insets.bottom + 8 }, isDesktop && { paddingHorizontal: DESKTOP_PAD, paddingTop: 12, paddingBottom: 16 }]}>
          <TextInput
            testID="wa-input"
            style={styles.input}
            value={text}
            onChangeText={setText}
            placeholder='e.g. "10000 - biki mill"'
            placeholderTextColor={colors.muted}
            multiline
            onSubmitEditing={submit}
            blurOnSubmit
          />
          <Pressable testID="wa-send-button" onPress={submit} style={[styles.send, (!text.trim() || send.isPending) && { opacity: 0.5 }]} disabled={!text.trim() || send.isPending}>
            <Icon name="send" size={18} color={colors.onBrandPrimary} />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
      <WaDiagnosticsSheet visible={diagOpen} onClose={() => setDiagOpen(false)} status={s} />
    </View>
  );
}
