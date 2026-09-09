import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Switch, Text, View } from "react-native";
import { KeyboardAwareScrollView, KeyboardStickyView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Header } from "@/src/components/Header";
import { Button, Card, Field, Segmented } from "@/src/components/ui";
import { useRequestUpdate, useUpdateDoneWatcher, useVersion } from "@/src/components/UpdateBanner";
import { formatDate } from "@/src/format";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import { UPDATE_BUSY_STATES, type Settings } from "@/src/types";

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  section: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: colors.muted, textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 8, marginTop: 8 },
  card: { padding: 16, marginBottom: 16 },
  hint: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, lineHeight: 17, marginBottom: 12 },
  code: { fontFamily: fonts.mono, fontSize: 12, color: colors.onSurface, backgroundColor: colors.surfaceTertiary, padding: 10, borderRadius: 8, marginBottom: 12 },
  sticky: { padding: 16, backgroundColor: colors.surfaceSecondary, borderTopWidth: 1, borderTopColor: colors.border },
  kv: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 6 },
  k: { fontFamily: fonts.text, fontSize: 13, color: colors.muted },
  v: { fontFamily: fonts.mono, fontSize: 13, color: colors.onSurface, maxWidth: "60%", textAlign: "right" },
  badge: { alignSelf: "flex-start", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, marginBottom: 12 },
  badgeText: { fontFamily: fonts.text, fontSize: 12, fontWeight: "700" },
  switchRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 10 },
  switchText: { fontFamily: fonts.text, fontSize: 14, color: colors.onSurface, flex: 1, paddingRight: 12 },
  log: { fontFamily: fonts.mono, fontSize: 10, color: colors.onSurfaceTertiary, backgroundColor: colors.surfaceTertiary, padding: 10, borderRadius: 8, marginTop: 12 },
  btnRow: { flexDirection: "row", gap: 8, marginTop: 8 },
}));

function UpdatesCard() {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const version = useVersion();
  const update = useRequestUpdate();
  useUpdateDoneWatcher(version.data);
  const [showLog, setShowLog] = useState(false);

  const check = useMutation({
    mutationFn: () => api.get("/system/version?force=true"),
    onSuccess: (d) => {
      qc.setQueryData(["system-version"], d);
      toast.show("Check ho gaya", "success");
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });
  const autoUpdate = useMutation({
    mutationFn: (enabled: boolean) => api.put("/system/auto-update", { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["system-version"] }),
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const d = version.data;
  if (!d || !d.supported) {
    return (
      <Card style={styles.card} testID="updates-card">
        <Text style={styles.hint}>
          Update feature sirf self-hosted VPS install pe kaam karta hai (repo ka deploy/install.sh). Emergent preview mein Emergent khud deploy karta hai.
        </Text>
      </Card>
    );
  }
  const busy = UPDATE_BUSY_STATES.includes(d.status.state);
  const badgeBg = busy ? colors.surfaceTertiary : d.status.state === "failed" ? colors.errorSoft : d.update_available ? colors.brandSecondary : colors.successSoft;
  const badgeFg = busy ? colors.onSurfaceTertiary : d.status.state === "failed" ? colors.error : d.update_available ? colors.onBrandSecondary : colors.success;
  const badgeText = busy ? `${d.status.message ?? "Update chal raha hai"}…` : d.status.state === "failed" ? "Last update fail hua" : d.update_available ? `${d.behind} naya commit available` : "Up to date";

  return (
    <Card style={styles.card} testID="updates-card">
      <View style={[styles.badge, { backgroundColor: badgeBg }]}>
        <Text style={[styles.badgeText, { color: badgeFg }]} testID="updates-status">
          {badgeText}
        </Text>
      </View>
      <View style={styles.kv}>
        <Text style={styles.k}>Installed</Text>
        <Text style={styles.v} numberOfLines={1} testID="updates-current">
          {d.current.commit} · {d.current.message}
        </Text>
      </View>
      <View style={styles.kv}>
        <Text style={styles.k}>Installed on</Text>
        <Text style={styles.v}>{d.current.date ? formatDate(d.current.date, "DD MMM YY, HH:mm") : "-"}</Text>
      </View>
      <View style={styles.kv}>
        <Text style={styles.k}>Latest (GitHub · {d.branch})</Text>
        <Text style={styles.v} numberOfLines={1} testID="updates-latest">
          {d.latest.commit} · {d.latest.message}
        </Text>
      </View>
      <View style={styles.btnRow}>
        <Button testID="updates-check-button" title="Check karo" variant="secondary" icon="refresh-cw" onPress={() => check.mutate()} loading={check.isPending} style={{ flex: 1 }} />
        <Button
          testID="updates-update-button"
          title={d.status.state === "failed" ? "Retry update" : "Update now"}
          icon="download"
          onPress={() => update.mutate()}
          loading={update.isPending}
          disabled={busy || (!d.update_available && d.status.state !== "failed")}
          style={{ flex: 1 }}
        />
      </View>
      <View style={styles.switchRow}>
        <Text style={styles.switchText}>Auto-update (har 15 min GitHub check, naya commit → khud install)</Text>
        <Switch testID="updates-auto-switch" value={d.auto_update} onValueChange={(v) => autoUpdate.mutate(v)} trackColor={{ true: colors.brandPrimary, false: colors.border }} />
      </View>
      <Button testID="updates-log-toggle" title={showLog ? "Log hide karo" : "Update log dekho"} variant="ghost" onPress={() => setShowLog((s) => !s)} />
      {showLog ? (
        <Text style={styles.log} selectable testID="updates-log">
          {d.log.length ? d.log.join("\n") : "Abhi koi log nahi"}
        </Text>
      ) : null}
    </Card>
  );
}

function ServerCard() {
  const styles = useStyles();
  const toast = useToast();
  const { serverUrl, defaultServerUrl, setServerUrl } = useAuth();
  const [url, setUrl] = useState(serverUrl);
  useEffect(() => setUrl(serverUrl), [serverUrl]);
  return (
    <Card style={styles.card} testID="server-card">
      <Text style={styles.hint}>Ye app kis server se baat kare. Khaali = default ({defaultServerUrl || "same origin"}). Apne VPS ka URL daalo, e.g. https://munsiji.example.com — save ke baad dobara PIN login hoga.</Text>
      <Field testID="server-url-input" label="Server URL" value={url} onChangeText={setUrl} placeholder={defaultServerUrl || "https://your-vps.com"} autoCapitalize="none" keyboardType="url" />
      <View style={styles.btnRow}>
        <Button testID="server-url-reset" title="Default" variant="secondary" onPress={() => void setServerUrl("").then(() => toast.show("Default server set", "success"))} style={{ flex: 1 }} />
        <Button testID="server-url-save" title="Save & re-login" onPress={() => void setServerUrl(url).then(() => toast.show("Server URL save ho gaya", "success")).catch((e: Error) => toast.show(e.message, "error"))} disabled={url.trim() === serverUrl} style={{ flex: 1 }} />
      </View>
    </Card>
  );
}

export default function SettingsScreen() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const qc = useQueryClient();
  const toast = useToast();
  const { logout } = useAuth();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/settings") });

  const [form, setForm] = useState<Partial<Settings>>({});
  const [oldPin, setOldPin] = useState("");
  const [newPin, setNewPin] = useState("");
  const [llmKey, setLlmKey] = useState("");
  const [emailKey, setEmailKey] = useState("");
  const [waKey, setWaKey] = useState("");

  useEffect(() => {
    if (settings.data) setForm(settings.data);
  }, [settings.data]);

  const set = (k: keyof Settings) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const save = useMutation({
    mutationFn: () => {
      const {
        webhook_url: _w,
        configured: _c,
        has_emergent_llm_key: _a,
        emergent_llm_key_hint: _b,
        has_emergent_email_key: _d,
        emergent_email_key_hint: _e,
        ai_configured: _f,
        email_configured: _g,
        has_wa9x_api_key: _h,
        wa9x_api_key_hint: _i,
        ...body
      } = form as Settings;
      return api.put<Settings>("/settings", { ...body, emergent_llm_key: llmKey.trim(), emergent_email_key: emailKey.trim(), wa9x_api_key: waKey.trim() });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["wa-status"] });
      setLlmKey("");
      setEmailKey("");
      setWaKey("");
      toast.show("Settings save ho gayi", "success");
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const rotateWebhook = useMutation({
    mutationFn: () => api.post<Settings>("/settings/rotate-webhook-secret"),
    onSuccess: (d) => {
      qc.setQueryData(["settings"], d);
      qc.invalidateQueries({ queryKey: ["wa-status"] });
      toast.show("Naya webhook URL ban gaya — wa.9x mein update karo", "success");
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const testEmail = useMutation({
    mutationFn: () => api.post("/settings/test-email"),
    onSuccess: () => toast.show(`Test email bhej di: ${form.owner_email}`, "success"),
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const changePin = useMutation({
    mutationFn: () => api.put("/settings/pin", { old_pin: oldPin, new_pin: newPin }),
    onSuccess: () => {
      setOldPin("");
      setNewPin("");
      toast.show("PIN badal gaya — naye PIN se login karo", "success");
      setTimeout(() => void logout(), 900);
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  return (
    <View style={styles.root} testID="settings-screen">
      <Header title="Settings" />
      <KeyboardAwareScrollView bottomOffset={96} contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 96 }} keyboardShouldPersistTaps="handled">
        <Text style={styles.section}>WhatsApp (wa.9x)</Text>
        <Card style={styles.card}>
          <Text style={styles.hint}>Provider mode. Mock mode mein bot replies sirf app mein dikhenge (test ke liye). wa.9x mode mein real WhatsApp pe jayenge.</Text>
          <View style={{ marginBottom: 16 }}>
            <Segmented
              testID="settings-provider"
              value={form.provider ?? "mock"}
              onChange={(v) => setForm((f) => ({ ...f, provider: v }))}
              options={[
                { value: "mock", label: "Mock (test)" },
                { value: "wa9x", label: "wa.9x live" },
              ]}
            />
          </View>
          <Field testID="settings-base-url" label="wa.9x Base URL" value={form.wa9x_base_url ?? ""} onChangeText={set("wa9x_base_url")} placeholder="https://api.wa9x.example" autoCapitalize="none" keyboardType="url" />
          <Field
            testID="settings-api-key"
            label={`wa.9x API Key ${form.has_wa9x_api_key ? `· saved ${form.wa9x_api_key_hint}` : "· NOT SET"}`}
            value={waKey}
            onChangeText={setWaKey}
            placeholder={form.has_wa9x_api_key ? "Nayi key daalne ke liye type karo (hatane ke liye -)" : "API key"}
            autoCapitalize="none"
            secureTextEntry
          />
          <Field testID="settings-instance-id" label="Instance ID (optional)" value={form.wa9x_instance_id ?? ""} onChangeText={set("wa9x_instance_id")} placeholder="instance id" autoCapitalize="none" />
          <Field testID="settings-send-path" label="Send text path" value={form.wa9x_send_path ?? ""} onChangeText={set("wa9x_send_path")} placeholder="/send-message" autoCapitalize="none" />
          <Field testID="settings-send-doc-path" label="Send document path" value={form.wa9x_send_doc_path ?? ""} onChangeText={set("wa9x_send_doc_path")} placeholder="/send-media" autoCapitalize="none" />
          <Text style={styles.hint}>Webhook URL — wa.9x dashboard mein incoming message webhook yahan point karo. Isme secret token hai: kisi se share na karo. Bina sahi token wale requests reject hote hain.</Text>
          <Text selectable style={styles.code} testID="settings-webhook-url">
            {settings.data?.webhook_url ?? "..."}
          </Text>
          <Button testID="settings-rotate-webhook-button" title="Naya webhook token banao" variant="secondary" icon="refresh-cw" onPress={() => rotateWebhook.mutate()} loading={rotateWebhook.isPending} style={{ marginBottom: 16 }} />
          <Field testID="settings-public-url" label="Public base URL (files ke liye)" value={form.public_base_url ?? ""} onChangeText={set("public_base_url")} placeholder="https://your-app.emergent.host" autoCapitalize="none" keyboardType="url" />
        </Card>

        <Text style={styles.section}>Emergent Keys (AI & Email)</Text>
        <Card style={styles.card} testID="keys-card">
          <Text style={styles.hint}>
            Emergent Universal Key — WhatsApp messages ki AI parsing (Gemini) ke liye. Emergent Profile → Universal Key se copy karo. Email key alerts bhejne ke liye. Khaali chhodne pe purani value rehti hai; hatane ke liye sirf &quot;-&quot; likho.
          </Text>
          <Field
            testID="settings-llm-key"
            label={`Emergent LLM key ${form.has_emergent_llm_key ? `· saved ${form.emergent_llm_key_hint}` : form.ai_configured ? "· server .env se" : "· NOT SET"}`}
            value={llmKey}
            onChangeText={setLlmKey}
            placeholder={form.has_emergent_llm_key ? "Nayi key daalne ke liye type karo" : "sk-emergent-..."}
            autoCapitalize="none"
            secureTextEntry
          />
          <Field
            testID="settings-email-key"
            label={`Emergent Email key ${form.has_emergent_email_key ? `· saved ${form.emergent_email_key_hint}` : "· server .env se"}`}
            value={emailKey}
            onChangeText={setEmailKey}
            placeholder={form.has_emergent_email_key ? "Nayi key daalne ke liye type karo" : "ek_..."}
            autoCapitalize="none"
            secureTextEntry
          />
        </Card>

        <Text style={styles.section}>Email Alerts</Text>
        <Card style={styles.card} testID="email-card">
          <Text style={styles.hint}>Alerts is email pe jaate hain: galat PIN (5 baar → lock), wa.9x reply fail, AI parsing fail, server update fail. Har alert type max 1 baar / 30 min.</Text>
          <Field testID="settings-owner-email" label="Owner email" value={form.owner_email ?? ""} onChangeText={set("owner_email")} placeholder="admin@munsiji.com" autoCapitalize="none" keyboardType="email-address" />
          <View style={styles.switchRow}>
            <Text style={styles.switchText}>Email alerts on</Text>
            <Switch testID="settings-alerts-switch" value={form.alerts_enabled ?? true} onValueChange={(v) => setForm((f) => ({ ...f, alerts_enabled: v }))} trackColor={{ true: colors.brandPrimary, false: colors.border }} />
          </View>
          <Button testID="settings-test-email-button" title="Test email bhejo" variant="secondary" icon="send" onPress={() => testEmail.mutate()} loading={testEmail.isPending} disabled={!form.owner_email} />
        </Card>

        <Text style={styles.section}>Whitelist</Text>
        <Card style={styles.card}>
          <Text style={styles.hint}>Sirf is number ke messages process honge (country code ke saath, e.g. 917205930002).</Text>
          <Field testID="settings-owner-number" label="Owner WhatsApp number" value={form.owner_number ?? ""} onChangeText={set("owner_number")} keyboardType="phone-pad" mono />
        </Card>

        <Text style={styles.section}>Security</Text>
        <Card style={styles.card}>
          <Field testID="settings-old-pin" label="Purana PIN" value={oldPin} onChangeText={setOldPin} keyboardType="number-pad" secureTextEntry maxLength={8} mono />
          <Field testID="settings-new-pin" label="Naya PIN (4-8 digit, 6 recommended)" value={newPin} onChangeText={setNewPin} keyboardType="number-pad" secureTextEntry maxLength={8} mono />
          <Text style={styles.hint}>PIN badalne pe sab purane logins invalid ho jaate hain (dobara login).</Text>
          <Button testID="settings-change-pin-button" title="PIN badlo" variant="secondary" icon="lock" onPress={() => changePin.mutate()} loading={changePin.isPending} disabled={oldPin.length < 4 || newPin.length < 4} />
        </Card>

        <Text style={styles.section}>Server & Updates</Text>
        <UpdatesCard />
        <ServerCard />

        <Button testID="settings-logout-button" title="Logout" variant="ghost" icon="log-out" onPress={() => void logout()} />
      </KeyboardAwareScrollView>
      <KeyboardStickyView offset={{ closed: 0, opened: 0 }}>
        <View style={[styles.sticky, { paddingBottom: insets.bottom + 12 }]}>
          <Button testID="settings-save-button" title="Save Settings" icon="check" onPress={() => save.mutate()} loading={save.isPending} />
        </View>
      </KeyboardStickyView>
    </View>
  );
}
