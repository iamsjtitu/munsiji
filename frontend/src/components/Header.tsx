import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Icon } from "@/src/components/Icon";
import { fonts, makeStyles, useTheme } from "@/src/theme";

const useStyles = makeStyles((colors) => ({
  wrap: { backgroundColor: colors.surfaceSecondary, borderBottomWidth: 1, borderBottomColor: colors.border },
  row: { height: 56, flexDirection: "row", alignItems: "center", paddingHorizontal: 8, gap: 4 },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: 22 },
  titleWrap: { flex: 1, paddingHorizontal: 8 },
  title: { fontFamily: fonts.text, fontSize: 20, fontWeight: "700", color: colors.onSurface },
  subtitle: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, marginTop: 1 },
  actions: { flexDirection: "row", alignItems: "center" },
}));

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
  return (
    <View style={[styles.wrap, { paddingTop: insets.top }]}>
      <View style={styles.row}>
        {back ? <HeaderButton icon="arrow-left" testID="header-back-button" onPress={() => (router.canGoBack() ? router.back() : router.replace("/home"))} /> : <View style={{ width: 8 }} />}
        <View style={styles.titleWrap}>
          <Text style={styles.title} numberOfLines={1} testID="header-title">
            {title}
          </Text>
          {subtitle ? (
            <Text style={styles.subtitle} numberOfLines={1}>
              {subtitle}
            </Text>
          ) : null}
        </View>
        <View style={styles.actions}>{right}</View>
      </View>
      {children}
    </View>
  );
}
