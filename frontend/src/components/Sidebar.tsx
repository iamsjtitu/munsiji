import { usePathname, useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth";
import { Icon, type IconName } from "@/src/components/Icon";
import { fonts, makeStyles, useTheme } from "@/src/theme";

const NAV: { href: "/home" | "/whatsapp" | "/summary" | "/settings"; label: string; icon: IconName; match: string[] }[] = [
  { href: "/home", label: "Home", icon: "landmark", match: ["/home", "/group", "/ledger"] },
  { href: "/whatsapp", label: "WhatsApp", icon: "message-circle", match: ["/whatsapp"] },
  { href: "/summary", label: "Summary", icon: "calendar", match: ["/summary"] },
  { href: "/settings", label: "Settings", icon: "settings", match: ["/settings"] },
];

const useStyles = makeStyles((colors) => ({
  side: { width: 240, backgroundColor: colors.surfaceSecondary, borderRightWidth: 1, borderRightColor: colors.border, paddingHorizontal: 12 },
  brand: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 8, paddingVertical: 20 },
  logo: { width: 40, height: 40, borderRadius: 12, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  brandText: { fontFamily: fonts.text, fontSize: 18, fontWeight: "800", color: colors.onSurface, letterSpacing: -0.3 },
  brandSub: { fontFamily: fonts.text, fontSize: 11, color: colors.muted },
  item: { flexDirection: "row", alignItems: "center", gap: 12, height: 44, paddingHorizontal: 12, borderRadius: 10, marginBottom: 4 },
  itemOn: { backgroundColor: colors.brandTertiary },
  itemText: { fontFamily: fonts.text, fontSize: 14, fontWeight: "600", color: colors.onSurfaceTertiary },
  itemTextOn: { color: colors.onBrandTertiary },
  footer: { marginTop: "auto", paddingBottom: 16 },
  hint: { fontFamily: fonts.text, fontSize: 11, color: colors.muted, paddingHorizontal: 12, marginTop: 8, lineHeight: 15 },
}));

/** Desktop-only left navigation (rendered by app/(app)/_layout.tsx on wide screens). */
export function Sidebar() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const pathname = usePathname();
  const { logout } = useAuth();

  return (
    <View style={[styles.side, { paddingTop: insets.top, paddingBottom: insets.bottom }]} testID="sidebar">
      <View style={styles.brand}>
        <View style={styles.logo}>
          <Icon name="notebook-pen" size={22} color={colors.onBrandPrimary} />
        </View>
        <View>
          <Text style={styles.brandText}>Munsiji</Text>
          <Text style={styles.brandSub}>WhatsApp munim</Text>
        </View>
      </View>
      {NAV.map((n) => {
        const on = n.match.some((m) => pathname === m || pathname.startsWith(m + "/"));
        return (
          <Pressable
            key={n.href}
            testID={`sidebar-${n.label.toLowerCase()}`}
            onPress={() => router.navigate(n.href)}
            style={({ pressed }) => [styles.item, on && styles.itemOn, pressed && !on && { backgroundColor: colors.surfaceTertiary }]}
          >
            <Icon name={n.icon} size={20} color={on ? colors.onBrandTertiary : colors.muted} />
            <Text style={[styles.itemText, on && styles.itemTextOn]}>{n.label}</Text>
          </Pressable>
        );
      })}
      <View style={styles.footer}>
        <Pressable testID="sidebar-logout" onPress={() => void logout()} style={({ pressed }) => [styles.item, pressed && { backgroundColor: colors.surfaceTertiary }]}>
          <Icon name="log-out" size={20} color={colors.muted} />
          <Text style={styles.itemText}>Logout</Text>
        </Pressable>
        <Text style={styles.hint}>Phone pe bhi yahi app: munsiji.app kholke &quot;Install&quot; dabao.</Text>
      </View>
    </View>
  );
}
