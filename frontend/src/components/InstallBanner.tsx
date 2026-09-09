import { useEffect, useState } from "react";
import { Platform, Pressable, Text, View } from "react-native";
import Animated, { FadeInDown, FadeOutUp } from "react-native-reanimated";

import { Icon } from "@/src/components/Icon";
import { useIsDesktop } from "@/src/hooks/useLayout";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import { storage } from "@/src/utils/storage";

const DISMISS_KEY = "munsiji_install_dismissed";

type BeforeInstallPromptEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: "accepted" | "dismissed" }> };

const useStyles = makeStyles((colors) => ({
  bar: {
    marginHorizontal: 16,
    marginTop: 12,
    padding: 12,
    borderRadius: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.surfaceInverse,
  },
  iconWrap: { width: 40, height: 40, borderRadius: 10, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: colors.onSurfaceInverse },
  text: { fontFamily: fonts.text, fontSize: 12, color: colors.onSurfaceInverse, opacity: 0.75, marginTop: 1, lineHeight: 16 },
  btn: { height: 36, paddingHorizontal: 14, borderRadius: 999, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center", flexShrink: 0 },
  btnText: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: colors.onBrandPrimary },
  close: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
}));

function isStandalone(): boolean {
  if (Platform.OS !== "web" || typeof window === "undefined") return true;
  const nav = window.navigator as Navigator & { standalone?: boolean };
  return window.matchMedia?.("(display-mode: standalone)").matches || nav.standalone === true;
}

function isIOS(): boolean {
  if (typeof navigator === "undefined") return false;
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

/** Web only: "Install Munsiji on your phone" bar (Android/desktop prompt, iOS instructions). */
export function InstallBanner() {
  const styles = useStyles();
  const { colors } = useTheme();
  const isDesktop = useIsDesktop();
  const [promptEvent, setPromptEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [visible, setVisible] = useState(false);
  const [ios, setIos] = useState(false);

  useEffect(() => {
    if (Platform.OS !== "web" || isStandalone()) return;
    let active = true;
    const onPrompt = (e: Event) => {
      e.preventDefault();
      if (!active) return;
      setPromptEvent(e as BeforeInstallPromptEvent);
      setVisible(true);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", () => setVisible(false));
    (async () => {
      const dismissed = await storage.getItem<boolean>(DISMISS_KEY, false);
      if (!active || dismissed) {
        active = false;
        return;
      }
      if (isIOS()) {
        setIos(true);
        setVisible(true);
      }
    })();
    return () => {
      active = false;
      window.removeEventListener("beforeinstallprompt", onPrompt);
    };
  }, []);

  if (Platform.OS !== "web" || !visible || isDesktop) return null;

  const dismiss = () => {
    setVisible(false);
    void storage.setItem(DISMISS_KEY, true);
  };
  const install = async () => {
    if (!promptEvent) return;
    await promptEvent.prompt();
    const { outcome } = await promptEvent.userChoice;
    if (outcome === "accepted") setVisible(false);
  };

  return (
    <Animated.View entering={FadeInDown.duration(250)} exiting={FadeOutUp.duration(200)} style={styles.bar} testID="install-banner">
      <View style={styles.iconWrap}>
        <Icon name="smartphone" size={20} color={colors.onBrandPrimary} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.title}>Phone pe app jaisa install karo</Text>
        <Text style={styles.text} numberOfLines={2}>
          {ios ? "Safari mein Share (⬆) → “Add to Home Screen” dabao" : "Home screen pe icon — full-screen, bina browser bar"}
        </Text>
      </View>
      {promptEvent ? (
        <Pressable testID="install-banner-button" style={styles.btn} onPress={() => void install()}>
          <Text style={styles.btnText}>Install</Text>
        </Pressable>
      ) : null}
      <Pressable testID="install-banner-close" style={styles.close} onPress={dismiss}>
        <Icon name="x" size={18} color={colors.onSurfaceInverse} />
      </Pressable>
    </Animated.View>
  );
}
