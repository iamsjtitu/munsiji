import { ActivityIndicator, Pressable, Text, TextInput, View, type TextInputProps, type ViewStyle } from "react-native";

import { Icon, type IconName } from "@/src/components/Icon";
import { fonts, makeStyles, useTheme } from "@/src/theme";

const useStyles = makeStyles((colors) => ({
  btn: { height: 48, borderRadius: 12, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 8, paddingHorizontal: 16 },
  primary: { backgroundColor: colors.brandPrimary },
  secondary: { backgroundColor: colors.surfaceTertiary },
  danger: { backgroundColor: colors.errorSoft },
  ghost: { backgroundColor: "transparent", borderWidth: 1, borderColor: colors.border },
  btnText: { fontFamily: fonts.text, fontSize: 15, fontWeight: "600" },
  onPrimary: { color: colors.onBrandPrimary },
  onSecondary: { color: colors.onSurface },
  onDanger: { color: colors.error },
  onGhost: { color: colors.onSurface },
  label: { fontFamily: fonts.text, fontSize: 12, fontWeight: "600", color: colors.muted, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 },
  input: {
    height: 48,
    borderRadius: 12,
    backgroundColor: colors.surfaceTertiary,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: 14,
    fontFamily: fonts.text,
    fontSize: 15,
    color: colors.onSurface,
  },
  mono: { fontFamily: fonts.mono, fontSize: 18 },
  field: { marginBottom: 16 },
  seg: { flexDirection: "row", backgroundColor: colors.surfaceTertiary, borderRadius: 12, padding: 4 },
  segItem: { flex: 1, height: 40, borderRadius: 9, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 6 },
  segText: { fontFamily: fonts.text, fontSize: 14, fontWeight: "600", color: colors.muted },
  chip: {
    height: 36,
    paddingHorizontal: 14,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  chipOn: { backgroundColor: colors.surfaceInverse, borderColor: colors.surfaceInverse },
  chipText: { fontFamily: fonts.text, fontSize: 13, color: colors.onSurface },
  chipTextOn: { color: colors.onSurfaceInverse },
  empty: { alignItems: "center", justifyContent: "center", padding: 32, gap: 8 },
  emptyIcon: { width: 64, height: 64, borderRadius: 32, backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center", marginBottom: 8 },
  emptyTitle: { fontFamily: fonts.text, fontSize: 16, fontWeight: "700", color: colors.onSurface },
  emptyText: { fontFamily: fonts.text, fontSize: 13, color: colors.muted, textAlign: "center", lineHeight: 19 },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: colors.border },
  row: { flexDirection: "row", alignItems: "center", minHeight: 52, paddingHorizontal: 16, paddingVertical: 12, gap: 12 },
  rowText: { flex: 1, fontFamily: fonts.text, fontSize: 15, color: colors.onSurface },
  divider: { height: 1, backgroundColor: colors.divider, marginLeft: 16 },
}));

type Variant = "primary" | "secondary" | "danger" | "ghost";

export function Button({
  title,
  onPress,
  variant = "primary",
  icon,
  loading,
  disabled,
  style,
  testID,
}: {
  title: string;
  onPress: () => void;
  variant?: Variant;
  icon?: IconName;
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
  testID: string;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const textStyle = { primary: styles.onPrimary, secondary: styles.onSecondary, danger: styles.onDanger, ghost: styles.onGhost }[variant];
  const iconColor = { primary: colors.onBrandPrimary, secondary: colors.onSurface, danger: colors.error, ghost: colors.onSurface }[variant];
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [styles.btn, styles[variant], style, (pressed || disabled) && { opacity: 0.7 }]}
    >
      {loading ? <ActivityIndicator color={iconColor} /> : icon ? <Icon name={icon} size={18} color={iconColor} /> : null}
      {!loading && <Text style={[styles.btnText, textStyle]}>{title}</Text>}
    </Pressable>
  );
}

export function Field({ label, mono, style, ...props }: TextInputProps & { label?: string; mono?: boolean; testID: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.field}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <TextInput placeholderTextColor={colors.muted} {...props} style={[styles.input, mono && styles.mono, props.multiline && { height: 88, paddingTop: 12 }, style]} />
    </View>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  testID,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; icon?: IconName; color?: string }[];
  testID: string;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.seg} testID={testID}>
      {options.map((o) => {
        const on = o.value === value;
        const activeColor = o.color ?? colors.onSurface;
        return (
          <Pressable
            key={o.value}
            testID={`${testID}-${o.value}`}
            onPress={() => onChange(o.value)}
            style={[styles.segItem, on && { backgroundColor: colors.surfaceSecondary, shadowColor: colors.surfaceInverse, shadowOpacity: 0.08, shadowRadius: 4, elevation: 1 }]}
          >
            {o.icon ? <Icon name={o.icon} size={16} color={on ? activeColor : colors.muted} /> : null}
            <Text style={[styles.segText, on && { color: activeColor }]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Chip({ label, selected, onPress, testID }: { label: string; selected: boolean; onPress: () => void; testID: string }) {
  const styles = useStyles();
  return (
    <Pressable testID={testID} onPress={onPress} style={[styles.chip, selected && styles.chipOn]}>
      <Text style={[styles.chipText, selected && styles.chipTextOn]}>{label}</Text>
    </Pressable>
  );
}

export function EmptyState({ icon, title, text, testID }: { icon: IconName; title: string; text?: string; testID?: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.empty} testID={testID}>
      <View style={styles.emptyIcon}>
        <Icon name={icon} size={28} color={colors.muted} />
      </View>
      <Text style={styles.emptyTitle}>{title}</Text>
      {text ? <Text style={styles.emptyText}>{text}</Text> : null}
    </View>
  );
}

export function Card({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  const styles = useStyles();
  return <View style={[styles.card, style]}>{children}</View>;
}

export function MenuRow({ icon, label, onPress, danger, testID }: { icon: IconName; label: string; onPress: () => void; danger?: boolean; testID: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <Pressable testID={testID} onPress={onPress} style={({ pressed }) => [styles.row, pressed && { backgroundColor: colors.surfaceTertiary }]}>
      <Icon name={icon} size={20} color={danger ? colors.error : colors.onSurface} />
      <Text style={[styles.rowText, danger && { color: colors.error }]}>{label}</Text>
      <Icon name="chevron-right" size={18} color={colors.muted} />
    </Pressable>
  );
}

export function Divider() {
  const styles = useStyles();
  return <View style={styles.divider} />;
}

export function Centered({ children }: { children: React.ReactNode }) {
  return <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 24 }}>{children}</View>;
}
