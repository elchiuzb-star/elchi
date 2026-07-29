// A synchronous, localStorage-shaped façade over expo-secure-store so the
// token-storage modules ported from the web app keep their original sync API.
//
// expo-secure-store (SDK 52+) exposes synchronous getItem/setItem; deletion is
// only available async, so removeItem fires-and-forgets deleteItemAsync while
// immediately blanking the value so a subsequent sync getItem reflects it.
import * as SecureStore from "expo-secure-store";

export const secureStore = {
  getItem(key: string): string | null {
    try {
      const value = SecureStore.getItem(key);
      return value === "" ? null : value;
    } catch {
      return null;
    }
  },

  setItem(key: string, value: string): void {
    try {
      SecureStore.setItem(key, value);
    } catch {
      // no-op: SecureStore unavailable (e.g. web preview)
    }
  },

  removeItem(key: string): void {
    try {
      // Blank synchronously so an immediate getItem sees it gone…
      SecureStore.setItem(key, "");
      // …then drop the entry entirely in the background.
      void SecureStore.deleteItemAsync(key);
    } catch {
      // no-op
    }
  },
};
