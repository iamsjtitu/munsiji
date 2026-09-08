import { Modal, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Icon } from "@/src/components/Icon";
import { fonts, makeStyles, useTheme } from "@/src/theme";

const useStyles = makeStyles((colors) => ({
  backdrop: { flex: 1, backgroundColor: colors.backdrop, justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.surfaceSecondary,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    maxHeight: "90%",
    width: "100%",
    alignSelf: "center",
  },
  handle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginTop: 8 },
  head: { flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingTop: 12, paddingBottom: 4 },
  title: { flex: 1, fontFamily: fonts.text, fontSize: 18, fontWeight: "700", color: colors.onSurface },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  body: { paddingHorizontal: 16, paddingTop: 8 },
}));

export function Sheet({
  visible,
  onClose,
  title,
  children,
  testID,
}: {
  visible: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  testID?: string;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <View style={styles.backdrop}>
          <Pressable style={{ flex: 1 }} onPress={onClose} testID="sheet-backdrop" />
          <View style={styles.sheet} testID={testID}>
            <View style={styles.handle} />
            <View style={styles.head}>
              <Text style={styles.title}>{title}</Text>
              <Pressable onPress={onClose} style={styles.close} testID="sheet-close-button">
                <Icon name="x" size={22} color={colors.muted} />
              </Pressable>
            </View>
            <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={[styles.body, { paddingBottom: insets.bottom + 20 }]}>
              {children}
            </ScrollView>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}
