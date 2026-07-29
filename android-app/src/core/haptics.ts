import * as Haptics from "expo-haptics";

// Fire-and-forget tactile feedback. Safe on any platform (errors swallowed).
export const haptics = {
  success: () => void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {}),
  warning: () => void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {}),
  error: () => void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {}),
  light: () => void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {}),
  selection: () => void Haptics.selectionAsync().catch(() => {}),
};
