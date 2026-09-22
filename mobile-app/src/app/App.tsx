/**
 * The client application.
 *
 * This file used to carry 1,700 lines of a screen-by-screen prototype above a single live line. Nothing
 * rendered it and nothing imported from it: `main.tsx` mounted the default export, which was - and is -
 * `ConnectedApp`. It survived because the design system pointed at it as "the reference design".
 *
 * That reference moved. The visual language this product is built in was designed in the frozen reference
 * client (`frontend/`), and it is `frontend/src/styles/theme.css` and `frontend/src/app/App.tsx` that
 * `styles/theme.css` and `ui/mobile.tsx` are now ported from. Keeping a second, older and differently-styled
 * prototype here would guarantee exactly the drift it was supposed to prevent: two answers to "what does a
 * card look like", one of them dead and neither marked as such.
 *
 * The prototype is in git (`git show cbf2875:mobile-app/src/app/App.tsx`) if a screen ever needs to be read
 * back out of it.
 */
export { ConnectedApp as default } from "./ConnectedApp";
