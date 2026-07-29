import { View } from "react-native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { useSession } from "@/auth/SessionProvider";
import { AuthFlow } from "@/screens/auth/AuthFlow";
import { ClientApp } from "@/screens/client/ClientApp";
import { DriverApp } from "@/screens/driver/DriverApp";

/** Routes to the correct role app once authenticated. */
function RoleApp() {
  const { authedRole } = useSession();
  return authedRole === "driver" ? <DriverApp /> : <ClientApp />;
}

export type RootStackParamList = {
  Auth: undefined;
  Home: undefined;
};

const Stack = createNativeStackNavigator<RootStackParamList>();

/**
 * Top-level gate. While the session is resolving we render nothing (the native
 * splash covers it); then we swap between the auth flow and the role app based
 * on whether a session is active — the idiomatic React Navigation auth pattern.
 */
export function RootNavigator() {
  const { status, authedRole } = useSession();

  if (status === "loading") {
    return <View className="flex-1 bg-background" />;
  }

  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      {authedRole ? (
        <Stack.Screen name="Home" component={RoleApp} />
      ) : (
        <Stack.Screen name="Auth" component={AuthFlow} />
      )}
    </Stack.Navigator>
  );
}
