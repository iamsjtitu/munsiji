import { useWindowDimensions } from "react-native";

export const DESKTOP_MIN_WIDTH = 960;
export const CONTENT_MAX_WIDTH = 1240;
/** Horizontal page padding on desktop (mobile screens use 16). */
export const DESKTOP_PAD = 24;

/** True on wide screens (desktop browser / tablet landscape) where we show the sidebar shell. */
export function useIsDesktop(): boolean {
  const { width } = useWindowDimensions();
  return width >= DESKTOP_MIN_WIDTH;
}
