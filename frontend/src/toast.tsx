import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { Text, View } from "react-native";
import Animated, { FadeInDown, FadeOutDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { fonts, makeStyles } from "@/src/theme";

type ToastType = "success" | "error" | "info";
type ToastState = { message: string; type: ToastType } | null;

const ToastContext = createContext<{ show: (message: string, type?: ToastType) => void }>({ show: () => {} });

const useStyles = makeStyles((colors) => ({
  wrap: { position: "absolute", left: 16, right: 16, alignItems: "center" },
  toast: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 12,
    maxWidth: 480,
    width: "100%",
    shadowColor: colors.surfaceInverse,
    shadowOpacity: 0.15,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  success: { backgroundColor: colors.surfaceInverse },
  error: { backgroundColor: colors.error },
  info: { backgroundColor: colors.surfaceInverse },
  text: { color: colors.onSurfaceInverse, fontFamily: fonts.text, fontSize: 14 },
}));

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<ToastState>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const insets = useSafeAreaInsets();
  const styles = useStyles();

  const show = useCallback((message: string, type: ToastType = "info") => {
    if (timer.current) clearTimeout(timer.current);
    setToast({ message, type });
    timer.current = setTimeout(() => setToast(null), 2800);
  }, []);

  const value = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {toast && (
        <View pointerEvents="none" style={[styles.wrap, { bottom: insets.bottom + 24 }]}>
          <Animated.View entering={FadeInDown.duration(200)} exiting={FadeOutDown.duration(200)} style={[styles.toast, styles[toast.type]]} testID="toast">
            <Text style={styles.text}>{toast.message}</Text>
          </Animated.View>
        </View>
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
