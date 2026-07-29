// Dynamic config: starts from app.json and injects the Google Maps Android key
// from the environment so the key stays in .env (gitignored) rather than in the
// tracked app.json.
module.exports = ({ config }) => ({
  ...config,
  android: {
    ...config.android,
    config: {
      ...(config.android && config.android.config),
      googleMaps: {
        apiKey: process.env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY || "",
      },
    },
  },
});
