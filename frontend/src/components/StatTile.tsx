import { Text, View } from "react-native";

import { Icon, type IconName } from "@/src/components/Icon";
import { Money } from "@/src/components/Money";
import { fonts, makeStyles, useTheme } from "@/src/theme";

const useStyles = makeStyles((colors) => ({
  tile: {
    flex: 1,
    minWidth: 200,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 20,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  label: { fontFamily: fonts.text, fontSize: 12, fontWeight: "600", color: colors.muted, textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 8 },
  count: { fontFamily: fonts.mono, fontSize: 28, color: colors.onSurface },
  sub: { fontFamily: fonts.text, fontSize: 12, color: colors.muted, marginTop: 4 },
  iconWrap: { width: 48, height: 48, borderRadius: 14, alignItems: "center", justifyContent: "center" },
}));

type Tone = "success" | "error" | "brand" | "neutral";

/** Desktop dashboard stat card: label + big number + tinted icon. */
export function StatTile({
  label,
  value,
  count,
  sub,
  tone = "neutral",
  icon,
  testID,
}: {
  label: string;
  value?: number;
  count?: number | string;
  sub?: string;
  tone?: Tone;
  icon: IconName;
  testID?: string;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const fg = { success: colors.success, error: colors.error, brand: colors.onBrandTertiary, neutral: colors.onSurfaceTertiary }[tone];
  const bg = { success: colors.successSoft, error: colors.errorSoft, brand: colors.brandTertiary, neutral: colors.surfaceTertiary }[tone];
  return (
    <View style={styles.tile}>
      <View style={{ flex: 1 }}>
        <Text style={styles.label}>{label}</Text>
        {value !== undefined ? (
          <Money
            testID={testID}
            value={value}
            size={Math.abs(value) >= 10000000 ? 22 : 26}
            colored={false}
            style={{ color: tone === "success" || tone === "error" ? fg : value < -0.004 ? colors.error : colors.onSurface }}
          />
        ) : (
          <Text style={styles.count} testID={testID}>
            {count}
          </Text>
        )}
        {sub ? <Text style={styles.sub}>{sub}</Text> : null}
      </View>
      <View style={[styles.iconWrap, { backgroundColor: bg }]}>
        <Icon name={icon} size={22} color={fg} />
      </View>
    </View>
  );
}
