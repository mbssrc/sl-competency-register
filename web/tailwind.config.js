/** @type {import('tailwindcss').Config} */

// Palette. These five ramps replace Tailwind's defaults so the whole app
// inherits the colour scheme of the lab's presentation deck
// (docs/presentation-deck.html, [data-theme="slate"]) without any template
// touching a bespoke class name.
//
// Each ramp is anchored on the deck's own tokens at the step the markup
// already uses it for, and the steps in between are interpolated in Oklab so
// the ramp stays perceptually even. Two steps are set by hand instead:
//
//   gray-500   the deck's two secondary inks belong to opposite modes
//              (--ink-2 on light, --ink-d2 on dark), so interpolating between
//              them lands step 500 in a dead zone. The app uses
//              text-gray-500 for light-mode text, so it is pinned dark
//              enough to clear 4.5:1 on the paper ground.
//   indigo-400 the dark-mode accent text; interpolation left it at 4.31:1
//              against the panel, so it is lifted to clear 4.5:1.
//
// Every colour pair the templates actually use clears 4.5:1 for text and
// 3:1 for icons and focus rings, in both modes. If you add anchors, re-check
// that before committing.

module.exports = {
  content: [
    "./apps/**/templates/**/*.html",
    "./templates/**/*.html",
    "./static/js/**/*.js",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // 'white' is deliberately left as pure white. Warming it to the
        // deck's --card (#FBFAF6) looks closer, but text-white sits on
        // bg-indigo-500 in 54 dark-mode buttons and the warm tone drops that
        // pair to 4.35:1. No single indigo-500 then satisfies both that text
        // and the focus ring's 3:1 against the dark panel, whereas pure white
        // clears both. The warmth carries anyway, from the #F2F0EA page
        // ground, the #D3D0C6 rules and the #16232A dark ground.
        // Neutral ground and ink. Dark surfaces live at 800-950,
        // light surfaces at 50-200, text at 500-700 and 300-400.
        gray: {
          50: "#FBFAF6",
          100: "#F2F0EA",
          200: "#E6E3DA",
          300: "#D3D0C6",
          400: "#A7BAC0",
          500: "#5E6F74",
          600: "#55646B",
          700: "#35454D",
          800: "#1E2E36",
          900: "#16232A",
          950: "#0E181D",
      },
      // Accent (--accent / --accent-d / --accent-soft).
      // Buttons, links, active navigation, focus rings.
      indigo: {
        50: "#EEE8F4",
        100: "#E0D4F0",
        200: "#CCBAE5",
        300: "#B9A0DA",
        400: "#A488C6",
        500: "#8769A9",
        600: "#6B4A8C",
        700: "#583D75",
        800: "#452F5F",
        900: "#33234A",
        950: "#231830",
      },
      // Caution (--caution / --caution-d / --caution-soft).
      // Self-assessed badges, partial coverage, warnings.
      amber: {
        50: "#FAF6EA",
        100: "#F2EBD8",
        200: "#EADDB6",
        300: "#E3CE92",
        400: "#D4B263",
        500: "#A68640",
        600: "#7A5C1C",
        700: "#644B17",
        800: "#4E3B13",
        900: "#3A2C0E",
        950: "#271D09",
      },
      // Not in the deck: the app needs a 'met' colour. Kept green
      // because it carries meaning, muted to match the palette.
      emerald: {
        50: "#E9F1EB",
        100: "#D6E7DA",
        200: "#B8D9C4",
        300: "#9ACBAE",
        400: "#6FB18E",
        500: "#4F8D6E",
        600: "#2F6B4F",
        700: "#275740",
        800: "#1F452F",
        900: "#17331F",
        950: "#0F2216",
      },
      // Not in the deck: the app needs a 'not met' colour. Same
      // reasoning as emerald.
      // Aliases. These carry the same meaning as the ramps above and were
      // the only "bad" and "good" families the templates still took from
      // Tailwind's defaults.
      rose: {
        50: "#F9EAE8",
        100: "#F2D7D4",
        200: "#E9BFBB",
        300: "#DFA8A2",
        400: "#D1908A",
        500: "#B7665E",
        600: "#9B3B33",
        700: "#7F302A",
        800: "#602520",
        900: "#431A16",
        950: "#2D110F",
      },
      green: {
        50: "#E9F1EB",
        100: "#D6E7DA",
        200: "#B8D9C4",
        300: "#9ACBAE",
        400: "#6FB18E",
        500: "#4F8D6E",
        600: "#2F6B4F",
        700: "#275740",
        800: "#1F452F",
        900: "#17331F",
        950: "#0F2216",
      },
      red: {
        50: "#F9EAE8",
        100: "#F2D7D4",
        200: "#E9BFBB",
        300: "#DFA8A2",
        400: "#D1908A",
        500: "#B7665E",
        600: "#9B3B33",
        700: "#7F302A",
        800: "#602520",
        900: "#431A16",
        950: "#2D110F",
      },
      },
    },
  },
  plugins: [],
}
