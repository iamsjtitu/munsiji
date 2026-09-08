import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { KeyboardAwareScrollView, KeyboardStickyView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Header } from "@/src/components/Header";
import { Button, Card, Field, Segmented } from "@/src/components/ui";
import { fonts, makeStyles } from "@/src/theme";
import { useToast } from "@/src/toast";
import type { Settings } from "@/src/types";

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  section: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: colors.muted, textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 8, marginTop: 8 },
  card: { padding: 16, marginBottom: 16 },
  hint: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, lineHeight: 17, marginBottom: 12 },
  code: { fontFamily: fonts.mono, fontSize: 12, color: colors.onSurface, backgroundColor: colors.surfaceTertiary, padding: 10, borderRadius: 8, marginBottom: 12 },
  sticky: { padding: 16, backgroundColor: colors.surfaceSecondary, borderTopWidth: 1, borderTopColor: colors.border },
}));

export default function SettingsScreen() {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const qc = useQueryClient();
  const toast = useToast();
  const { logout } = useAuth();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/settings") });

  const [form, setForm] = useState<Partial<Settings>>({});
  const [oldPin, setOldPin] = useState("");
  const [newPin, setNewPin] = useState("");

  useEffect(() => {
    if (settings.data) setForm(settings.data);
  }, [settings.data]);

  const set = (k: keyof Settings) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const save = useMutation({
    mutationFn: () => {
      const { webhook_url: _w, configured: _c, ...body } = form as Settings;
      return api.put<Settings>("/settings", body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["wa-status"] });
      toast.show("Settings save ho gayi", "success");
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });

  const changePin = useMutation({
    mutationFn: () => api.put("/settings/pin", { old_pin: oldPin, new_pin: newPin }),
    onSuccess: () => {
      setOldPin("");
      setNewPin("");
      toast.show("PIN badal gaya", "success");
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
          <Field testID="settings-api-key" label="wa.9x API Key" value={form.wa9x_api_key ?? ""} onChangeText={set("wa9x_api_key")} placeholder="API key" autoCapitalize="none" secureTextEntry />
          <Field testID="settings-instance-id" label="Instance ID (optional)" value={form.wa9x_instance_id ?? ""} onChangeText={set("wa9x_instance_id")} placeholder="instance id" autoCapitalize="none" />
          <Field testID="settings-send-path" label="Send text path" value={form.wa9x_send_path ?? ""} onChangeText={set("wa9x_send_path")} placeholder="/send-message" autoCapitalize="none" />
          <Field testID="settings-send-doc-path" label="Send document path" value={form.wa9x_send_doc_path ?? ""} onChangeText={set("wa9x_send_doc_path")} placeholder="/send-media" autoCapitalize="none" />
          <Text style={styles.hint}>Webhook URL — wa.9x dashboard mein incoming message webhook yahan point karo:</Text>
          <Text selectable style={styles.code} testID="settings-webhook-url">
            {settings.data?.webhook_url ?? "..."}
          </Text>
          <Field testID="settings-public-url" label="Public base URL (files ke liye)" value={form.public_base_url ?? ""} onChangeText={set("public_base_url")} placeholder="https://your-app.emergent.host" autoCapitalize="none" keyboardType="url" />
        </Card>

        <Text style={styles.section}>Whitelist</Text>
        <Card style={styles.card}>
          <Text style={styles.hint}>Sirf is number ke messages process honge (country code ke saath, e.g. 917205930002).</Text>
          <Field testID="settings-owner-number" label="Owner WhatsApp number" value={form.owner_number ?? ""} onChangeText={set("owner_number")} keyboardType="phone-pad" mono />
        </Card>

        <Text style={styles.section}>Security</Text>
        <Card style={styles.card}>
          <Field testID="settings-old-pin" label="Purana PIN" value={oldPin} onChangeText={setOldPin} keyboardType="number-pad" secureTextEntry maxLength={6} mono />
          <Field testID="settings-new-pin" label="Naya PIN (4-6 digit)" value={newPin} onChangeText={setNewPin} keyboardType="number-pad" secureTextEntry maxLength={6} mono />
          <Button testID="settings-change-pin-button" title="PIN badlo" variant="secondary" icon="lock" onPress={() => changePin.mutate()} loading={changePin.isPending} disabled={oldPin.length < 4 || newPin.length < 4} />
        </Card>

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
