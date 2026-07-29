import { useCallback, useEffect, useState } from "react";
import { BackHandler } from "react-native";
import type { Role } from "@/core/types";
import { Screen } from "@/components/Screen";
import { useSession } from "@/auth/SessionProvider";
import { sessionRequestOtp, sessionVerifyOtp } from "@/data/session";
import { SplashScreen } from "./SplashScreen";
import { OnboardingScreen } from "./OnboardingScreen";
import { RoleSelectScreen } from "./RoleSelectScreen";
import { PhoneScreen } from "./PhoneScreen";
import { OtpScreen } from "./OtpScreen";

type Step = "splash" | "onboarding" | "role-select" | "phone" | "otp";

// Which step the hardware back button returns to (splash/onboarding = exit app).
const BACK_TO: Partial<Record<Step, Step>> = {
  "role-select": "onboarding",
  phone: "role-select",
  otp: "phone",
};

/**
 * Auth state machine: splash → onboarding → role-select → phone → otp.
 * On a verified OTP it hands the role to the SessionProvider, which swaps the
 * navigator over to the (role's) app.
 */
export function AuthFlow() {
  const { login } = useSession();
  const [step, setStep] = useState<Step>("splash");
  const [role, setRole] = useState<Role>("client");
  const [phone, setPhone] = useState("");
  const [devOtp, setDevOtp] = useState<string | undefined>();

  const goBack = useCallback(() => {
    const prev = BACK_TO[step];
    if (prev) {
      setStep(prev);
      return true;
    }
    return false; // let the OS handle it (exit app)
  }, [step]);

  useEffect(() => {
    const sub = BackHandler.addEventListener("hardwareBackPress", goBack);
    return () => sub.remove();
  }, [goBack]);

  async function requestOtpFor(p: string) {
    setPhone(p);
    const res = await sessionRequestOtp(role, p);
    setDevOtp(res.devOtp);
    setStep("otp");
  }

  async function resendOtp() {
    const res = await sessionRequestOtp(role, phone);
    setDevOtp(res.devOtp);
    return res.devOtp;
  }

  async function verifyOtpFor(code: string) {
    await sessionVerifyOtp(role, phone, code);
    login(role);
  }

  return (
    <Screen edges={step === "splash" ? [] : ["top", "bottom"]}>
      {step === "splash" && <SplashScreen onDone={() => setStep("onboarding")} />}
      {step === "onboarding" && (
        <OnboardingScreen onContinue={() => setStep("role-select")} />
      )}
      {step === "role-select" && (
        <RoleSelectScreen
          onSelect={(r) => {
            setRole(r);
            setStep("phone");
          }}
          onBack={() => setStep("onboarding")}
        />
      )}
      {step === "phone" && (
        <PhoneScreen role={role} onSubmit={requestOtpFor} onBack={() => setStep("role-select")} />
      )}
      {step === "otp" && (
        <OtpScreen
          phone={phone}
          onVerify={verifyOtpFor}
          onResend={resendOtp}
          devOtp={devOtp}
          onBack={() => setStep("phone")}
        />
      )}
    </Screen>
  );
}
