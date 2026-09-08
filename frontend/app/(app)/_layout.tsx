import { Redirect, Stack } from "expo-router";

import { useAuth } from "@/src/auth";
import { useTheme } from "@/src/theme";

export default function AppLayout() {
  const { ready, authed } = useAuth();
  const { colors } = useTheme();
  if (ready && !authed) return <Redirect href="/" />;
  return <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.surface } }} />;
}
