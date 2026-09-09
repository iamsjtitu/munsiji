import { Redirect } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Platform, Pressable, Text, View } from "react-native";
import Animated, { useAnimatedStyle, useSharedValue, withSequence, withTiming } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth";
import { Icon } from "@/src/components/Icon";
import { Sheet } from "@/src/components/Sheet";
import { Button, Field } from "@/src/components/ui";
import { useIsDesktop } from "@/src/hooks/useLayout";
import { fonts, makeStyles, useTheme } from "@/src/theme";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "del"];

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  rootDesktop: { alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceTertiary },
  card: {
    width: 400,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: colors.border,
    paddingBottom: 24,
    shadowColor: colors.surfaceInverse,
    shadowOpacity: 0.08,
    shadowRadius: 30,
    shadowOffset: { width: 0, height: 12 },
    elevation: 6,
  },
  top: { flex: 1, alignItems: "center", justifyContent: "center", gap: 12 },
  topDesktop: { flexGrow: 0, flexShrink: 0, flexBasis: "auto", paddingTop: 28, paddingBottom: 8 },
  logo: { width: 72, height: 72, borderRadius: 24, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center", marginBottom: 8 },
  brand: { fontFamily: fonts.text, fontSize: 26, fontWeight: "800", color: colors.onSurface, letterSpacing: -0.5 },
  tagline: { fontFamily: fonts.text, fontSize: 14, color: colors.muted },
  prompt: { fontFamily: fonts.text, fontSize: 14, color: colors.onSurfaceTertiary, marginTop: 24 },
  dots: { flexDirection: "row", gap: 16, marginTop: 8, height: 20, alignItems: "center" },
  dot: { width: 14, height: 14, borderRadius: 7, borderWidth: 1.5, borderColor: colors.borderStrong },
  dotOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  error: { fontFamily: fonts.text, fontSize: 13, color: colors.error, marginTop: 12, height: 18 },
  pad: { paddingHorizontal: 32, paddingTop: 8 },
  padRow: { flexDirection: "row", justifyContent: "space-between", marginBottom: 12 },
  key: { width: 76, height: 76, borderRadius: 38, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  keyText: { fontFamily: fonts.mono, fontSize: 26, color: colors.onSurface },
  serverBtn: { position: "absolute", right: 12, width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  serverHint: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, lineHeight: 17, marginBottom: 12 },
}));

export default function PinScreen() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { ready, authed, login, serverUrl, defaultServerUrl, setServerUrl } = useAuth();
  const isDesktop = useIsDesktop();
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [serverOpen, setServerOpen] = useState(false);
  const [serverInput, setServerInput] = useState("");
  const shake = useSharedValue(0);
  const shakeStyle = useAnimatedStyle(() => ({ transform: [{ translateX: shake.value }] }));

  const press = useCallback(
    (k: string) => {
      if (busy) return;
      setError("");
      if (k === "del") return setPin((p) => p.slice(0, -1));
      setPin((p) => (p.length < 4 ? p + k : p));
    },
    [busy],
  );

  // Desktop/web: physical keyboard types the PIN
  useEffect(() => {
    if (Platform.OS !== "web" || typeof window === "undefined" || !ready || authed) return;
    const onKey = (e: KeyboardEvent) => {
      if (serverOpen) return;
      if (/^[0-9]$/.test(e.key)) press(e.key);
      else if (e.key === "Backspace") press("del");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [press, serverOpen, ready, authed]);

  useEffect(() => {
    if (pin.length !== 4 || busy) return;
    setBusy(true);
    login(pin)
      .catch((e: Error) => {
        setError(e.message || "Galat PIN");
        shake.value = withSequence(withTiming(-10, { duration: 50 }), withTiming(10, { duration: 50 }), withTiming(-6, { duration: 50 }), withTiming(0, { duration: 50 }));
        setPin("");
      })
      .finally(() => setBusy(false));
  }, [pin, busy, login, shake]);

  if (!ready) {
    return (
      <View style={[styles.root, { alignItems: "center", justifyContent: "center" }]}>
        <ActivityIndicator color={colors.brandPrimary} />
      </View>
    );
  }
  if (authed) return <Redirect href="/home" />;

  return (
    <View style={[styles.root, { paddingTop: insets.top, paddingBottom: insets.bottom + 16 }, isDesktop && styles.rootDesktop]} testID="pin-screen">
      <View style={isDesktop ? styles.card : { flex: 1 }}>
        <View style={[styles.top, isDesktop && styles.topDesktop]}>
          <View style={styles.logo}>
            <Icon name="notebook-pen" size={34} color={colors.onBrandPrimary} />
          </View>
          <Text style={styles.brand}>Munsiji</Text>
          <Text style={styles.tagline}>Aapka personal WhatsApp munim</Text>
          <Text style={styles.prompt}>Enter PIN</Text>
          <Animated.View style={[styles.dots, shakeStyle]} testID="pin-dots">
            {[0, 1, 2, 3].map((i) => (
              <View key={i} style={[styles.dot, i < pin.length && styles.dotOn]} />
            ))}
          </Animated.View>
          <Text style={styles.error} testID="pin-error">
            {busy ? "Checking..." : error}
          </Text>
        </View>
        <View style={styles.pad}>
          {[0, 1, 2, 3].map((r) => (
            <View key={r} style={styles.padRow}>
              {KEYS.slice(r * 3, r * 3 + 3).map((k, i) =>
                k === "" ? (
                  <View key={`e${i}`} style={{ width: 76 }} />
                ) : (
                  <Pressable
                    key={k}
                    testID={`pin-key-${k}`}
                    onPress={() => press(k)}
                    style={({ pressed }) => [styles.key, pressed && { backgroundColor: colors.surfaceTertiary }]}
                  >
                    {k === "del" ? <Icon name="delete" size={24} color={colors.onSurface} /> : <Text style={styles.keyText}>{k}</Text>}
                  </Pressable>
                ),
              )}
            </View>
          ))}
        </View>
      </View>
      <Pressable
        testID="pin-server-button"
        style={[styles.serverBtn, { top: insets.top + 8 }]}
        onPress={() => {
          setServerInput(serverUrl);
          setServerOpen(true);
        }}
      >
        <Icon name="server" size={20} color={colors.muted} />
      </Pressable>
      <Sheet visible={serverOpen} onClose={() => setServerOpen(false)} title="Server" testID="server-sheet">
        <Text style={styles.serverHint}>Apne VPS ka URL daalo (e.g. https://munsiji.app). Khaali chhodo to default server use hoga{defaultServerUrl ? ` (${defaultServerUrl})` : ""}.</Text>
        <Text style={[styles.serverHint, { color: colors.error }]}>⚠ Sirf apna hi server URL daalo — galat/anjaan server pe aapka PIN aur data chala jaayega. Sirf https:// URL.</Text>
        <Field testID="pin-server-url-input" label="Server URL" value={serverInput} onChangeText={setServerInput} placeholder={defaultServerUrl || "https://your-vps.com"} autoCapitalize="none" keyboardType="url" autoFocus />
        <Button
          testID="pin-server-url-save"
          title="Save"
          onPress={() =>
            void setServerUrl(serverInput)
              .then(() => {
                setServerOpen(false);
                setError("");
              })
              .catch((e: Error) => setError(e.message))
          }
        />
      </Sheet>
    </View>
  );
}
