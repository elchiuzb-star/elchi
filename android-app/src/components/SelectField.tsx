import { useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { ChevronDown, X } from "@/components/icons";
import { useTheme } from "@/theme/ThemeProvider";

export type SelectOption = { value: number | string; label: string };

/** Dropdown field that opens a modal list. Replaces the web's native <select>. */
export function SelectField({
  label,
  value,
  options,
  placeholder,
  onChange,
  disabled = false,
}: {
  label?: string;
  value: number | string | "";
  options: SelectOption[];
  placeholder: string;
  onChange: (v: number | string) => void;
  disabled?: boolean;
}) {
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  const selected = options.find((o) => o.value === value);

  return (
    <View>
      {label ? <Text className="mb-1.5 text-xs text-muted-foreground">{label}</Text> : null}
      <Pressable
        onPress={() => !disabled && setOpen(true)}
        className="flex-row items-center justify-between rounded-xl border border-border bg-input px-4 py-3"
        style={{ opacity: disabled ? 0.6 : 1 }}
      >
        <Text className="flex-1 text-sm" style={{ color: selected ? colors.foreground : colors.mutedForeground }}>
          {selected ? selected.label : placeholder}
        </Text>
        <ChevronDown size={16} color={colors.mutedForeground} />
      </Pressable>

      <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
        <Pressable onPress={() => setOpen(false)} className="flex-1 justify-end" style={{ backgroundColor: "rgba(0,0,0,0.5)" }}>
          <Pressable onPress={() => {}} className="max-h-[70%] rounded-t-[24px] border-t border-border bg-card">
            <View className="flex-row items-center justify-between border-b border-border p-4">
              <Text className="text-base font-bold text-foreground">{placeholder}</Text>
              <Pressable onPress={() => setOpen(false)} className="h-8 w-8 items-center justify-center rounded-full bg-secondary">
                <X size={16} color={colors.foreground} />
              </Pressable>
            </View>
            <ScrollView>
              {options.map((o) => {
                const active = o.value === value;
                return (
                  <Pressable
                    key={String(o.value)}
                    onPress={() => {
                      onChange(o.value);
                      setOpen(false);
                    }}
                    className="border-b border-border px-4 py-3.5 active:bg-secondary"
                    style={{ backgroundColor: active ? `${colors.primary}1A` : "transparent" }}
                  >
                    <Text className="text-sm" style={{ color: active ? colors.primary : colors.foreground, fontWeight: active ? "600" : "400" }}>
                      {o.label}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}
