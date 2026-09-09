import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Icon } from "@/src/components/Icon";
import { useIsDesktop } from "@/src/hooks/useLayout";
import { fonts, makeStyles, useTheme } from "@/src/theme";

const useStyles = makeStyles((colors) => ({
  wrap: { backgroundColor: colors.surfaceSecondary, borderBottomWidth: 1, borderBottomColor: colors.border },
  row: { height: 56, flexDirection: "row", alignItems: "center", paddingHorizontal: 8, gap: 4 },
  rowDesktop: { height: 72, paddingHorizontal: 16 },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: 22 },
  titleWrap: { flex: 1, paddingHorizontal: 8 },
  title: { fontFamily: fonts.text, fontSize: 20, fontWeight: "700", color: colors.onSurface },
  titleDesktop: { fontSize: 24, letterSpacing: -0.3 },
  subtitle: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, marginTop: 1 },
  subtitleDesktop: { fontSize: 13, marginTop: 2 },
  actions: { flexDirection: "row", alignItems: "center" },
  actionsDesktop: { gap: 8, paddingRight: 8 },
  headerBtn: { height: 40, paddingHorizontal: 14, borderRadius: 10 },
}));

/** Compact button style for primary actions placed in the desktop header (`right` slot). */
export function useHeaderButtonStyle() {
  return useStyles().headerBtn;
}

export function HeaderButton({ icon, onPress, testID }: { icon: React.ComponentProps<typeof Icon>["name"]; onPress: () => void; testID: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <Pressable testID={testID} onPress={onPress} hitSlop={4} style={({ pressed }) => [styles.back, pressed && { backgroundColor: colors.surfaceTertiary }]}>
      <Icon name={icon} size={22} color={colors.onSurface} />
    </Pressable>
  );
}

export function Header({
  title,
  subtitle,
  back = true,
  right,
  children,
}: {
  title: string;
  subtitle?: string;
  back?: boolean;
  right?: React.ReactNode;
  children?: React.ReactNode;
}) {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const router = useRouter();
  const isDesktop = useIsDesktop();
  return (
    <View style={[styles.wrap, { paddingTop: insets.top }]}>
      <View style={[styles.row, isDesktop && styles.rowDesktop]}>
        {back ? <HeaderButton icon="arrow-left" testID="header-back-button" onPress={() => (router.canGoBack() ? router.back() : router.replace("/home"))} /> : <View style={{ width: isDesktop ? 16 : 8 }} />}
        <View style={styles.titleWrap}>
          <Text style={[styles.title, isDesktop && styles.titleDesktop]} numberOfLines={1} testID="header-title">
            {title}
          </Text>
          {subtitle ? (
            <Text style={[styles.subtitle, isDesktop && styles.subtitleDesktop]} numberOfLines={1}>
              {subtitle}
            </Text>
          ) : null}
        </View>
        <View style={[styles.actions, isDesktop && styles.actionsDesktop]}>{right}</View>
      </View>
      {children}
    </View>
  );
}
