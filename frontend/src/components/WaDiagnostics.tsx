import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { api } from "@/src/api";
import { Icon } from "@/src/components/Icon";
import { Sheet } from "@/src/components/Sheet";
import { Button, Card } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import type { ConnectionCheck, WaStatus, WebhookLogEntry } from "@/src/types";

const useStyles = makeStyles((colors) => ({
  card: { padding: 14, marginBottom: 12 },
  title: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: colors.muted, textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 8 },
  kv: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 5, gap: 12 },
  k: { fontFamily: fonts.text, fontSize: 13, color: colors.muted },
  v: { fontFamily: fonts.text, fontSize: 13, color: colors.onSurface, fontWeight: "600", flexShrink: 1, textAlign: "right" },
  hint: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, lineHeight: 17 },
  step: { flexDirection: "row", gap: 8, marginTop: 6 },
  stepNum: { width: 18, height: 18, borderRadius: 9, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  stepNumText: { fontFamily: fonts.text, fontSize: 11, fontWeight: "700", color: colors.onBrandTertiary },
  stepText: { flex: 1, fontFamily: fonts.text, fontSize: 12, color: colors.onSurface, lineHeight: 17 },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  badgeText: { fontFamily: fonts.text, fontSize: 11, fontWeight: "700" },
  logRow: { paddingVertical: 10, gap: 4 },
  logHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  logTime: { fontFamily: fonts.mono, fontSize: 11, color: colors.muted, flex: 1 },
  logText: { fontFamily: fonts.text, fontSize: 13, color: colors.onSurface },
  logDetail: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, lineHeight: 16 },
  raw: { fontFamily: fonts.mono, fontSize: 10, color: colors.onSurfaceTertiary, backgroundColor: colors.surfaceTertiary, padding: 8, borderRadius: 6, marginTop: 4 },
  divider: { height: 1, backgroundColor: colors.divider },
  result: { padding: 10, borderRadius: 8, marginTop: 10, gap: 4 },
  resultText: { fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
}));

const OUTCOME_LABEL: Record<string, string> = {
  accepted: "Processing",
  processed: "Reply gaya ✓",
  clarify: "Bot ne sawaal pucha",
  ignored: "Ignore kiya",
  not_owner: "Number whitelist mein nahi",
  paired: "Pairing ho gayi ✓",
  duplicate: "Duplicate",
  invalid_token: "Galat webhook token",
  bad_signature: "Signature mismatch",
  send_failed: "Entry saved, reply fail",
  error: "Error",
};

function OutcomeBadge({ outcome }: { outcome: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const good = outcome === "processed" || outcome === "clarify" || outcome === "paired";
  const bad = ["invalid_token", "bad_signature", "send_failed", "error", "not_owner"].includes(outcome);
  const bg = good ? colors.successSoft : bad ? colors.errorSoft : colors.surfaceTertiary;
  const fg = good ? colors.success : bad ? colors.error : colors.onSurfaceTertiary;
  return (
    <View style={[styles.badge, { backgroundColor: bg }]}>
      <Text style={[styles.badgeText, { color: fg }]}>{OUTCOME_LABEL[outcome] ?? outcome}</Text>
    </View>
  );
}

function LogRow({ e }: { e: WebhookLogEntry }) {
  const styles = useStyles();
  const [open, setOpen] = useState(false);
  return (
    <Pressable style={styles.logRow} onPress={() => setOpen((o) => !o)} testID={`webhook-log-${e.id}`}>
      <View style={styles.logHead}>
        <Text style={styles.logTime}>{dayjs(e.received_at).format("DD MMM, HH:mm:ss")}</Text>
        <OutcomeBadge outcome={e.outcome} />
      </View>
      {e.text ? (
        <Text style={styles.logText} numberOfLines={open ? undefined : 1}>
          {e.sender ? `${e.sender}: ` : ""}
          {e.text}
        </Text>
      ) : null}
      {e.detail ? <Text style={styles.logDetail}>{e.detail}</Text> : null}
      {open && e.raw ? (
        <Text style={styles.raw} selectable>
          {e.raw}
        </Text>
      ) : null}
    </Pressable>
  );
}

/** Owner-facing wa.9x troubleshooting: connection test + every webhook hit that reached the server. */
export function WaDiagnosticsSheet({ visible, onClose, status }: { visible: boolean; onClose: () => void; status: WaStatus | undefined }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const qc = useQueryClient();
  const log = useQuery({ queryKey: ["wa-webhook-log"], queryFn: () => api.get<WebhookLogEntry[]>("/whatsapp/webhook-log?limit=20"), enabled: visible, refetchInterval: visible ? 5000 : false });
  const check = useMutation({
    mutationFn: () => api.post<ConnectionCheck>("/whatsapp/check-connection"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wa-messages"] }),
  });
  const pairing = useMutation({
    mutationFn: () => api.post<{ code: string; expires_at: string }>("/whatsapp/pairing-code"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wa-status"] }),
  });
  const removeId = useMutation({
    mutationFn: (id: string) => api.del(`/whatsapp/owner-ids/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wa-status"] }),
  });
  const r = check.data;
  const live = status?.provider === "wa9x";
  const lidSeen = (log.data ?? []).some((e) => e.outcome === "not_owner" && e.sender.length >= 14);
  const pairingCode = status?.pairing_code ?? null;

  return (
    <Sheet visible={visible} onClose={onClose} title="wa.9x Connection Check" testID="wa-diagnostics-sheet">
      <Card style={styles.card} testID="wa-diag-status">
        <Text style={styles.title}>Status</Text>
        <View style={styles.kv}>
          <Text style={styles.k}>Provider</Text>
          <Text style={styles.v}>{live ? "wa.9x live" : "Mock (test)"}</Text>
        </View>
        <View style={styles.kv}>
          <Text style={styles.k}>API key</Text>
          <Text style={[styles.v, { color: status?.configured ? colors.success : colors.error }]}>{status?.configured ? "Set hai" : "NOT SET"}</Text>
        </View>
        <View style={styles.kv}>
          <Text style={styles.k}>Owner number (whitelist)</Text>
          <Text style={[styles.v, { fontFamily: fonts.mono }]}>{status?.owner_number}</Text>
        </View>
        {(status?.owner_ids ?? []).map((id) => (
          <View key={id} style={styles.kv} testID={`wa-owner-id-${id}`}>
            <Text style={styles.k}>Linked WhatsApp ID</Text>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Text style={[styles.v, { fontFamily: fonts.mono }]}>{id}</Text>
              <Pressable onPress={() => removeId.mutate(id)} hitSlop={8} testID={`wa-owner-id-remove-${id}`}>
                <Icon name="x" size={16} color={colors.muted} />
              </Pressable>
            </View>
          </View>
        ))}
        <View style={styles.kv}>
          <Text style={styles.k}>Last webhook</Text>
          <Text style={styles.v} testID="wa-diag-last-webhook">
            {status?.last_webhook_at ? `${dayjs(status.last_webhook_at).format("DD MMM, HH:mm")} · ${OUTCOME_LABEL[status.last_webhook_outcome ?? ""] ?? status.last_webhook_outcome}` : "Abhi tak koi nahi aaya"}
          </Text>
        </View>
        <View style={styles.kv}>
          <Text style={styles.k}>Webhook hits (24h)</Text>
          <Text style={[styles.v, { fontFamily: fonts.mono }]}>{status?.webhook_hits_24h ?? 0}</Text>
        </View>
      </Card>

      <Card style={[styles.card, lidSeen && !pairingCode && (status?.owner_ids ?? []).length === 0 ? { borderColor: colors.warning } : undefined]} testID="wa-diag-pairing">
        <Text style={styles.title}>Pairing (agar aapka number pehchana nahi ja raha)</Text>
        <Text style={styles.hint}>
          Naye WhatsApp mein sender kabhi phone number ki jagah ek lambi ID (LID, e.g. 1369…) ke roop mein aata hai — tab whitelist match nahi hota. Fix: neeche code banao aur apne WhatsApp se bot number ko wahi code bhejo. Us ID ko owner maan liya jaayega.
        </Text>
        {lidSeen && (status?.owner_ids ?? []).length === 0 ? (
          <Text style={[styles.hint, { color: colors.warning, marginTop: 6, fontWeight: "700" }]} testID="wa-lid-warning">
            Webhook log mein LID wala message dikha — pairing zaroori hai.
          </Text>
        ) : null}
        {pairingCode ? (
          <View style={[styles.result, { backgroundColor: colors.brandTertiary, alignItems: "center" }]} testID="wa-pairing-code">
            <Text style={[styles.resultText, { color: colors.onBrandTertiary }]}>Bot number ko ye code WhatsApp karo (15 min valid):</Text>
            <Text selectable style={{ fontFamily: fonts.mono, fontSize: 34, letterSpacing: 6, color: colors.onBrandTertiary, marginVertical: 4 }}>
              {pairingCode}
            </Text>
            <Text style={[styles.resultText, { color: colors.onBrandTertiary }]}>Bhejne ke baad yahan &quot;Pairing ho gayi ✓&quot; dikhega aur WhatsApp pe confirmation aayegi.</Text>
          </View>
        ) : null}
        <Button
          testID="wa-pairing-button"
          title={pairingCode ? "Naya code banao" : "Pairing code banao"}
          icon="link"
          variant={pairingCode ? "ghost" : "secondary"}
          style={{ marginTop: 10 }}
          onPress={() => pairing.mutate()}
          loading={pairing.isPending}
        />
        {pairing.isError ? <Text style={[styles.hint, { color: colors.error, marginTop: 8 }]}>{(pairing.error as Error).message}</Text> : null}
      </Card>

      <Card style={styles.card} testID="wa-diag-test">
        <Text style={styles.title}>1. Sending test (app → WhatsApp)</Text>
        <Text style={styles.hint}>Owner number pe ek test message jaayega. Isse API key + connected session verify hoti hai.</Text>
        <Button
          testID="wa-check-connection-button"
          title="Test message bhejo"
          icon="send"
          variant="secondary"
          style={{ marginTop: 10 }}
          onPress={() => check.mutate()}
          loading={check.isPending}
          disabled={!live}
        />
        {!live ? <Text style={[styles.hint, { marginTop: 8, color: colors.warning }]}>Settings mein provider &quot;wa.9x live&quot; karke Save karo.</Text> : null}
        {check.isError ? (
          <View style={[styles.result, { backgroundColor: colors.errorSoft }]} testID="wa-check-error">
            <Text style={[styles.resultText, { color: colors.error }]}>{(check.error as Error).message}</Text>
          </View>
        ) : null}
        {r ? (
          <View style={[styles.result, { backgroundColor: r.sent ? colors.successSoft : colors.errorSoft }]} testID="wa-check-result">
            <Text style={[styles.resultText, { color: r.sent ? colors.success : colors.error, fontWeight: "700" }]}>{r.sent ? "✓ Test message bhej diya — WhatsApp check karo" : `✗ Send fail: ${r.send_error || "unknown error"}`}</Text>
            <Text style={[styles.resultText, { color: colors.onSurfaceTertiary }]}>API: {r.base_url}</Text>
            {r.sessions_error ? (
              <Text style={[styles.resultText, { color: colors.error }]}>Sessions: {r.sessions_error}</Text>
            ) : r.sessions.length === 0 ? (
              <>
                <Text style={[styles.resultText, { color: colors.onSurfaceTertiary }]}>
                  Is API key pe koi connected WhatsApp session nahi mila — wa.9x → Sessions mein check karo ki bot number &quot;connected&quot; hai aur API key usi account/session ki hai.
                </Text>
                {r.sessions_raw ? (
                  <Text style={styles.raw} selectable>
                    wa.9x /v1/sessions → {r.sessions_raw}
                  </Text>
                ) : null}
              </>
            ) : (
              r.sessions.map((s, i) => (
                <Text key={s.id ?? i} style={[styles.resultText, { color: colors.onSurfaceTertiary }]}>
                  Session: {s.name ?? "-"} · {s.phone ?? "-"} · {s.status ?? "-"}
                </Text>
              ))
            )}
          </View>
        ) : null}
      </Card>

      <Card style={styles.card} testID="wa-diag-log">
        <Text style={styles.title}>2. Receiving (WhatsApp → app) · webhook log</Text>
        {log.data && log.data.length > 0 ? (
          log.data.map((e, i) => (
            <View key={e.id}>
              {i > 0 && <View style={styles.divider} />}
              <LogRow e={e} />
            </View>
          ))
        ) : (
          <View testID="wa-diag-empty">
            <Text style={styles.hint}>Server tak abhi ek bhi webhook nahi pahuncha. Check karo:</Text>
            {[
              "wa.9x dashboard → Settings → Inbound Webhook: yahan Munsiji Settings ka poora Webhook URL (token ke saath) paste karo, Save.",
              'wa.9x → apni session/number → "Receive Messages" toggle ON ho.',
              "Jo number wa.9x se linked hai (bot) usko apne owner number se message karo — khud ko message karne pe webhook nahi aata.",
              'wa.9x Settings mein "Test" button dabao — yahan log mein entry dikhni chahiye.',
            ].map((t, i) => (
              <View key={i} style={styles.step}>
                <View style={styles.stepNum}>
                  <Text style={styles.stepNumText}>{i + 1}</Text>
                </View>
                <Text style={styles.stepText}>{t}</Text>
              </View>
            ))}
          </View>
        )}
      </Card>
    </Sheet>
  );
}
