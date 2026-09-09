import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { ActivityIndicator, Platform, Pressable, Text, View } from "react-native";
import Animated, { FadeInDown, FadeOutUp } from "react-native-reanimated";

import { api } from "@/src/api";
import { Icon } from "@/src/components/Icon";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import { useToast } from "@/src/toast";
import { UPDATE_BUSY_STATES, type VersionInfo } from "@/src/types";

const useStyles = makeStyles((colors) => ({
  bar: {
    marginHorizontal: 16,
    marginTop: 12,
    padding: 12,
    borderRadius: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.brandSecondary,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
  },
  barFailed: { backgroundColor: colors.errorSoft, borderColor: colors.error },
  title: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: colors.onBrandSecondary },
  text: { fontFamily: fonts.text, fontSize: 12, color: colors.onBrandSecondary, marginTop: 1 },
  btn: { height: 36, paddingHorizontal: 14, borderRadius: 999, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center", flexShrink: 0 },
  btnText: { fontFamily: fonts.text, fontSize: 13, fontWeight: "700", color: colors.onBrandPrimary },
}));

export function useVersion() {
  return useQuery({
    queryKey: ["system-version"],
    queryFn: () => api.get<VersionInfo>("/system/version"),
    refetchInterval: (q) => {
      const d = q.state.data;
      return d?.supported && UPDATE_BUSY_STATES.includes(d.status.state) ? 4000 : 5 * 60 * 1000;
    },
    retry: false,
  });
}

export function useRequestUpdate() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: () => api.post("/system/update"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system-version"] });
      toast.show("Update shuru — 2-6 min lagenge", "success");
    },
    onError: (e: Error) => toast.show(e.message, "error"),
  });
}

/** Reloads the web app once an update finishes; shows a toast on native. */
export function useUpdateDoneWatcher(data: VersionInfo | undefined) {
  const wasBusy = useRef(false);
  const toast = useToast();
  useEffect(() => {
    if (!data?.supported) return;
    const busy = UPDATE_BUSY_STATES.includes(data.status.state);
    if (wasBusy.current && !busy) {
      if (data.status.state === "done") {
        toast.show("Update ho gaya — naya version live hai", "success");
        if (Platform.OS === "web") setTimeout(() => globalThis.location?.reload(), 1200);
      } else if (data.status.state === "failed") {
        toast.show("Update fail hua — Settings mein log dekho", "error");
      }
    }
    wasBusy.current = busy;
  }, [data, toast]);
}

export function UpdateBanner() {
  const styles = useStyles();
  const { colors } = useTheme();
  const { data } = useVersion();
  const update = useRequestUpdate();
  useUpdateDoneWatcher(data);

  if (!data?.supported) return null;
  const state = data.status.state;
  const busy = UPDATE_BUSY_STATES.includes(state);
  if (!data.update_available && !busy && state !== "failed") return null;

  return (
    <Animated.View entering={FadeInDown.duration(250)} exiting={FadeOutUp.duration(200)} style={[styles.bar, state === "failed" && styles.barFailed]} testID="update-banner">
      {busy ? <ActivityIndicator color={colors.brandPrimary} /> : <Icon name={state === "failed" ? "circle-alert" : "download"} size={20} color={state === "failed" ? colors.error : colors.brandPrimary} />}
      <View style={{ flex: 1 }}>
        <Text style={styles.title} numberOfLines={1}>
          {busy ? "Update chal raha hai…" : state === "failed" ? "Update fail hua" : `Naya update available (${data.behind} commit${data.behind > 1 ? "s" : ""})`}
        </Text>
        <Text style={styles.text} numberOfLines={2}>
          {busy ? data.status.message : state === "failed" ? data.status.message : data.latest.message || data.latest.commit}
        </Text>
      </View>
      {!busy ? (
        <Pressable testID="update-banner-button" style={styles.btn} onPress={() => update.mutate()} disabled={update.isPending}>
          <Text style={styles.btnText}>{state === "failed" ? "Retry" : "Update karo"}</Text>
        </Pressable>
      ) : null}
    </Animated.View>
  );
}
