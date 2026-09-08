import { Lucide } from "@react-native-vector-icons/lucide";
import type { ComponentProps } from "react";

export type IconName = ComponentProps<typeof Lucide>["name"];

export function Icon({ name, size = 20, color }: { name: IconName; size?: number; color: string }) {
  return <Lucide name={name} size={size} color={color} />;
}
