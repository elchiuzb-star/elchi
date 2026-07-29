import { useCallback, useState } from "react";
import { RefreshControl } from "react-native";
import { useTheme } from "@/theme/ThemeProvider";

/**
 * Swipe-down-to-refresh for any ScrollView/FlatList.
 *
 * Pass a reload function (ideally one that returns a promise, e.g. useAsync's
 * `reload` or useDriverData's `reload`) and spread the returned element onto the
 * list's `refreshControl` prop. The spinner shows until the reload settles.
 *
 *   const refresh = usePullRefresh(reload);
 *   <ScrollView refreshControl={refresh}>…</ScrollView>
 */
export function usePullRefresh(reload: () => void | Promise<unknown>) {
  const { colors } = useTheme();
  const [refreshing, setRefreshing] = useState(false);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await reload();
    } finally {
      setRefreshing(false);
    }
  }, [reload]);

  return (
    <RefreshControl
      refreshing={refreshing}
      onRefresh={onRefresh}
      tintColor={colors.primary}
      colors={[colors.primary]}
      progressBackgroundColor={colors.card}
    />
  );
}
