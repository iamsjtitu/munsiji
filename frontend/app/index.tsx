import { Redirect } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import Animated, { useAnimatedStyle, useSharedValue, withSequence, withTiming } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth";
import { Icon } from "@/src/components/Icon";
import { fonts, makeStyles, useTheme } from "@/src/theme";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "del"];

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  top: { flex: 1, alignItems: "center", justifyContent: "center", gap: 12 },
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
}));

export default function PinScreen() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { ready, authed, login } = useAuth();
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const shake = useSharedValue(0);
  const shakeStyle = useAnimatedStyle(() => ({ transform: [{ translateX: shake.value }] }));

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

  const press = (k: string) => {
    if (busy) return;
    setError("");
    if (k === "del") return setPin((p) => p.slice(0, -1));
    if (pin.length < 4) setPin((p) => p + k);
  };

  return (
    <View style={[styles.root, { paddingTop: insets.top, paddingBottom: insets.bottom + 16 }]} testID="pin-screen">
      <View style={styles.top}>
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
  );
}
