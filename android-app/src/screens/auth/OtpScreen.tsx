import { useEffect, useRef, useState } from "react";
import { Keyboard, Pressable, Text, TextInput, View } from "react-native";
import { ArrowRight, RefreshCw as ArrowsClockwise, CircleAlert as WarningCircle } from "lucide-react-native";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { getUzbekErrorMessage } from "@/utils/errors";
import { BackButton, PrimaryButton } from "@/components/buttons";

// Must match the backend's otp_length. The approved Elchi template uses 4.
const OTP_LENGTH = Number(process.env.EXPO_PUBLIC_OTP_LENGTH) || 4;

export function OtpScreen({
  phone,
  onVerify,
  onResend,
  devOtp,
  onBack,
}: {
  phone: string;
  onVerify: (code: string) => Promise<void>;
  onResend: () => Promise<string | undefined>;
  devOtp?: string;
  onBack: () => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const inputRef = useRef<TextInput>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [resend, setResend] = useState(59);
  const [focused, setFocused] = useState(true);

  useEffect(() => {
    if (resend <= 0) return;
    const id = setInterval(() => setResend((s) => s - 1), 1000);
    return () => clearInterval(id);
  }, [resend]);

  const complete = code.length === OTP_LENGTH;

  async function verify() {
    const c = code.replace(/\D/g, "");
    if (c.length < OTP_LENGTH) {
      setError(t("otpError"));
      return;
    }
    setLoading(true);
    setError("");
    try {
      await onVerify(c);
    } catch (e) {
      setError(getUzbekErrorMessage(e));
      setLoading(false);
    }
  }

  // Submit as soon as the code is complete, so the user never has to press the
  // button (this also covers Android SMS autofill filling all digits at once).
  // The submitted value is remembered so a rejected code isn't retried in a
  // loop; editing the code clears it and allows another attempt.
  const autoSubmitted = useRef<string | null>(null);

  useEffect(() => {
    if (code.length !== OTP_LENGTH) {
      autoSubmitted.current = null;
      return;
    }
    if (loading || autoSubmitted.current === code) return;
    autoSubmitted.current = code;
    Keyboard.dismiss();
    void verify();
  }, [code, loading]);

  async function resendCode() {
    setError("");
    try {
      await onResend();
      setResend(59);
    } catch (e) {
      setError(getUzbekErrorMessage(e));
    }
  }

  return (
    <View className="flex-1 bg-background px-6 pb-6 pt-6">
      <BackButton onPress={onBack} />

      <View className="mt-6 items-center">
        <Text style={{ fontSize: 22, fontWeight: "700", color: colors.foreground }}>
          {t("otpTitle")}
        </Text>
        <Text className="mt-1.5 text-sm text-muted-foreground">{t("otpDesc")}</Text>
        <Text
          className="mt-1 text-sm"
          style={{ fontWeight: "600", color: colors.foreground }}
        >
          {phone}
        </Text>
      </View>

      {/* Segmented OTP: one hidden input drives the visible boxes. */}
      <Pressable className="relative mt-8" onPress={() => inputRef.current?.focus()}>
        <TextInput
          ref={inputRef}
          autoFocus
          keyboardType="number-pad"
          textContentType="oneTimeCode"
          autoComplete="sms-otp"
          importantForAutofill="yes"
          value={code}
          onChangeText={(v) => {
            setCode(v.replace(/\D/g, "").slice(0, OTP_LENGTH));
            setError("");
          }}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          maxLength={OTP_LENGTH}
          style={{ position: "absolute", width: 1, height: 1, opacity: 0 }}
        />
        <View className="flex-row justify-between">
          {Array.from({ length: OTP_LENGTH }).map((_, i) => {
            const char = code[i] ?? "";
            const isCurrent = focused && i === code.length;
            const borderColor = error
              ? colors.destructive
              : char || isCurrent
                ? colors.primary
                : colors.border;
            return (
              <View
                key={i}
                style={{
                  width: 56,
                  height: 56,
                  borderRadius: 28,
                  alignItems: "center",
                  justifyContent: "center",
                  borderWidth: char || isCurrent || error ? 2 : 1,
                  borderColor,
                  backgroundColor: error
                    ? `${colors.destructive}0D`
                    : char
                      ? `${colors.primary}1A`
                      : colors.input,
                }}
              >
                <Text style={{ fontSize: 18, fontWeight: "700", color: colors.foreground }}>
                  {char}
                </Text>
              </View>
            );
          })}
        </View>
      </Pressable>

      {error ? (
        <View className="mt-3 flex-row items-center justify-center" style={{ gap: 4 }}>
          <WarningCircle size={11} color={colors.destructive} />
          <Text style={{ fontSize: 12, color: colors.destructive }}>{error}</Text>
        </View>
      ) : null}

      {/* Dev OTP helper — only present when the backend runs in dev mode. */}
      {devOtp ? (
        <Pressable
          onPress={() => {
            setCode(devOtp.replace(/\D/g, "").slice(0, OTP_LENGTH));
            setError("");
          }}
          className="mt-4 self-center rounded-full px-3 py-1.5"
          style={{ backgroundColor: `${colors.primary}1A` }}
        >
          <Text style={{ fontSize: 12, fontWeight: "600", color: colors.primary }}>
            Demo OTP: {devOtp}
          </Text>
        </Pressable>
      ) : null}

      <View className="mt-5 items-center">
        {resend > 0 ? (
          <Text style={{ fontSize: 12, color: colors.mutedForeground }}>
            {t("otpResendIn")} 0:{resend.toString().padStart(2, "0")}
          </Text>
        ) : (
          <Pressable onPress={resendCode} className="flex-row items-center" style={{ gap: 4 }}>
            <ArrowsClockwise size={11} color={colors.primary} />
            <Text style={{ fontSize: 12, fontWeight: "500", color: colors.primary }}>
              {t("otpResend")}
            </Text>
          </Pressable>
        )}
      </View>

      <View className="mt-7">
        <PrimaryButton
          label={t("otpVerify")}
          onPress={verify}
          loading={loading}
          disabled={!complete}
          rightIcon={<ArrowRight size={18} color={colors.primaryForeground} />}
        />
      </View>
    </View>
  );
}
