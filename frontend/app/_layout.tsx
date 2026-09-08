import { QueryClientProvider } from "@tanstack/react-query";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator, LogBox, View } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AuthProvider } from "@/src/auth";
import { ErrorBoundary } from "@/src/components/error-boundary";
import { queryClient } from "@/src/query-client";
import { ToastProvider } from "@/src/toast";
import { useTheme } from "@/src/theme";

// Disable logbox errors etc so that users can see the app
// and agent works as expected.
LogBox.ignoreAllLogs(true);

export default function RootLayout() {
  const { colors } = useTheme();
  const [loaded] = useFonts({
    PlusJakartaSans: require("../assets/fonts/PlusJakartaSans-Regular.ttf"),
    JetBrainsMono: require("../assets/fonts/JetBrainsMono-Regular.ttf"),
  });

  // One app level ErrorBoundary; a render crash shows a reload screen
  // instead of a blank app.
  return (
    <ErrorBoundary>
      <GestureHandlerRootView style={{ flex: 1 }}>
        <SafeAreaProvider>
          <KeyboardProvider>
            <QueryClientProvider client={queryClient}>
              <AuthProvider>
                <ToastProvider>
                  <StatusBar style="dark" />
                  {loaded ? (
                    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.surface } }} />
                  ) : (
                    <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface }}>
                      <ActivityIndicator color={colors.brandPrimary} />
                    </View>
                  )}
                </ToastProvider>
              </AuthProvider>
            </QueryClientProvider>
          </KeyboardProvider>
        </SafeAreaProvider>
      </GestureHandlerRootView>
    </ErrorBoundary>
  );
}
