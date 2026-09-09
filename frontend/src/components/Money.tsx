import { Text, type TextStyle } from "react-native";

import { balanceLabel, formatINR } from "@/src/format";
import { fonts, useTheme } from "@/src/theme";
import type { LedgerKind } from "@/src/types";

type Props = {
  value: number;
  size?: number;
  colored?: boolean; // green for +, red for -
  showLabel?: boolean; // "lena hai" / "dena hai" (party) or "in hand" (cash/bank)
  kind?: LedgerKind;
  tone?: "debit" | "credit" | "neutral";
  style?: TextStyle;
  testID?: string;
};

export function Money({ value, size = 16, colored = true, showLabel = false, kind = "party", tone, style, testID }: Props) {
  const { colors } = useTheme();
  let color = colors.onSurface;
  if (tone === "debit") color = colors.error;
  else if (tone === "credit") color = colors.success;
  else if (colored) {
    if (value > 0.004) color = kind === "party" ? colors.success : colors.onSurface;
    else if (value < -0.004) color = colors.error;
    else color = colors.muted;
  }
  return (
    <Text testID={testID} style={[{ fontFamily: fonts.mono, fontSize: size, color, fontVariant: ["tabular-nums"] }, style]} numberOfLines={1}>
      {formatINR(value)}
      {showLabel ? <Text style={{ fontFamily: fonts.text, fontSize: Math.max(11, size * 0.65), color: colors.muted }}>  {balanceLabel(value, kind)}</Text> : null}
    </Text>
  );
}
