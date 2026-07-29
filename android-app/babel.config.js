module.exports = function (api) {
  api.cache(true);
  return {
    presets: [
      ["babel-preset-expo", { jsxImportSource: "nativewind" }],
      "nativewind/babel",
    ],
    // react-native-worklets plugin (Reanimated v4) must be last.
    plugins: ["react-native-worklets/plugin"],
  };
};
