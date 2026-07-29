import "./global.css";

import { StatusBar } from "expo-status-bar";
import { NavigationContainer } from "@react-navigation/native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { ThemeProvider, useTheme } from "@/theme/ThemeProvider";
import { I18nProvider } from "@/i18n/i18n";
import { SessionProvider } from "@/auth/SessionProvider";
import { RootNavigator } from "@/navigation/RootNavigator";

function ThemedApp() {
  const { scheme, navTheme } = useTheme();
  return (
    <NavigationContainer theme={navTheme}>
      <StatusBar style={scheme === "dark" ? "light" : "dark"} />
      <SessionProvider>
        <RootNavigator />
      </SessionProvider>
    </NavigationContainer>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <I18nProvider>
          <ThemedApp />
        </I18nProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}
