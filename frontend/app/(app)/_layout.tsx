import { Redirect, Stack } from "expo-router";
import { View } from "react-native";

import { useAuth } from "@/src/auth";
import { Sidebar } from "@/src/components/Sidebar";
import { CONTENT_MAX_WIDTH, useIsDesktop } from "@/src/hooks/useLayout";
import { useTheme } from "@/src/theme";

export default function AppLayout() {
  const { ready, authed } = useAuth();
  const { colors } = useTheme();
  const isDesktop = useIsDesktop();
  if (ready && !authed) return <Redirect href="/" />;

  const stack = <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.surface }, animation: isDesktop ? "fade" : "default" }} />;
  if (!isDesktop) return stack;

  // Desktop shell: left sidebar + centered content column
  return (
    <View style={{ flex: 1, flexDirection: "row", backgroundColor: colors.surface }} testID="desktop-shell">
      <Sidebar />
      <View style={{ flex: 1, alignItems: "center" }}>
        <View style={{ flex: 1, width: "100%", maxWidth: CONTENT_MAX_WIDTH }}>{stack}</View>
      </View>
    </View>
  );
}
