import { nextui } from "@nextui-org/theme";
import type { Config } from "tailwindcss";

export default {
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
    "./node_modules/@nextui-org/theme/dist/**/*.{js,ts,jsx,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        // Monokai Light Theme Colors
        monokai: {
          bg: "#FFFFFF",
          fg: "#000000",
          selection: "#C2E8FF",
          lineHighlight: "#A5A5A5",
          comment: "#9F9F8F",
          string: "#F25A00",
          keyword: "#F92672",
          class: "#6AAF19",
          type: "#28C6E4",
          number: "#AE81FF",
          param: "#FD971F",
          find: "#FFE792",
          // Dark mode colors
          darkBg: "#272822",
          darkFg: "#F8F8F2",
          darkSelection: "#49483E",
        },
      },
    }
  },
  darkMode: "class",
  plugins: [
    nextui({
      themes: {
        light: {
          colors: {
            // Monokai Light based color scheme
            background: "#FFFFFF",
            foreground: "#272822",
            // Content colors - for cards, inputs, etc. with better contrast
            content1: "#FFFFFF",
            content2: "#FAFAF8",
            content3: "#F5F5F2",
            content4: "#EBEBEA",
            // Default colors - for buttons, chips with better visibility
            default: {
              50: "#FAFAF8",
              100: "#F5F5F2",
              200: "#EBEBEA",
              300: "#DDDDD8",
              400: "#C8C8C0",
              500: "#A0A098",
              600: "#787870",
              700: "#505048",
              800: "#383830",
              900: "#272822",
              DEFAULT: "#EBEBEA",
              foreground: "#272822",
            },
            // Divider with more contrast
            divider: "#D8D8D0",
            primary: {
              50: "#FEE7F0",
              100: "#FDCEE0",
              200: "#FB9DC1",
              300: "#F96CA2",
              400: "#F73B83",
              500: "#F92672", // Monokai keyword pink
              600: "#C71E5B",
              700: "#951744",
              800: "#630F2D",
              900: "#310816",
              DEFAULT: "#F92672",
              foreground: "#FFFFFF",
            },
            secondary: {
              50: "#E8F5E9",
              100: "#C8E6C9",
              200: "#A5D6A7",
              300: "#81C784",
              400: "#6AAF19", // Monokai class green
              500: "#5D9916",
              600: "#4E8013",
              700: "#3F6610",
              800: "#304D0C",
              900: "#213408",
              DEFAULT: "#6AAF19",
              foreground: "#FFFFFF",
            },
            success: {
              50: "#E8F5E9",
              100: "#C8E6C9",
              200: "#A5D6A7",
              300: "#81C784",
              400: "#A6E22E", // Monokai green
              500: "#8BC520",
              600: "#70A018",
              700: "#557A12",
              800: "#3A540C",
              900: "#1F2E06",
              DEFAULT: "#A6E22E",
              foreground: "#000000",
            },
            warning: {
              50: "#FFF8E1",
              100: "#FFECB3",
              200: "#FFE082",
              300: "#FFD54F",
              400: "#FD971F", // Monokai param orange
              500: "#E68619",
              600: "#CC7514",
              700: "#B3640F",
              800: "#99530A",
              900: "#664205",
              DEFAULT: "#FD971F",
              foreground: "#000000",
            },
            danger: {
              50: "#FFEBEE",
              100: "#FFCDD2",
              200: "#EF9A9A",
              300: "#E57373",
              400: "#F92672", // Use Monokai pink for danger
              500: "#E01E5B",
              600: "#C11849",
              700: "#A21237",
              800: "#820E2C",
              900: "#620A21",
              DEFAULT: "#F92672",
              foreground: "#FFFFFF",
            },
            focus: "#66D9EF", // Monokai cyan
          },
        },
        dark: {
          colors: {
            // Monokai Dark based color scheme
            background: "#272822",
            foreground: "#F8F8F2",
            // Content colors for dark mode
            content1: "#31322C",
            content2: "#3B3C36",
            content3: "#45463E",
            content4: "#4F5046",
            // Default colors for dark mode
            default: {
              50: "#4F5046",
              100: "#45463E",
              200: "#3B3C36",
              300: "#31322C",
              400: "#272822",
              500: "#1E1F1A",
              600: "#161712",
              700: "#0E0F0A",
              800: "#060702",
              900: "#000000",
              DEFAULT: "#3B3C36",
              foreground: "#F8F8F2",
            },
            divider: "#49483E",
            primary: {
              50: "#FEE7F0",
              100: "#FDCEE0",
              200: "#FB9DC1",
              300: "#F96CA2",
              400: "#F73B83",
              500: "#F92672",
              600: "#C71E5B",
              700: "#951744",
              800: "#630F2D",
              900: "#310816",
              DEFAULT: "#F92672",
              foreground: "#FFFFFF",
            },
            secondary: {
              50: "#E8F5E9",
              100: "#C8E6C9",
              200: "#A5D6A7",
              300: "#81C784",
              400: "#6AAF19",
              500: "#5D9916",
              600: "#4E8013",
              700: "#3F6610",
              800: "#304D0C",
              900: "#213408",
              DEFAULT: "#6AAF19",
              foreground: "#FFFFFF",
            },
            success: {
              50: "#E8F5E9",
              100: "#C8E6C9",
              200: "#A5D6A7",
              300: "#81C784",
              400: "#A6E22E",
              500: "#8BC520",
              600: "#70A018",
              700: "#557A12",
              800: "#3A540C",
              900: "#1F2E06",
              DEFAULT: "#A6E22E",
              foreground: "#000000",
            },
            warning: {
              50: "#FFF8E1",
              100: "#FFECB3",
              200: "#FFE082",
              300: "#FFD54F",
              400: "#FD971F",
              500: "#E68619",
              600: "#CC7514",
              700: "#B3640F",
              800: "#99530A",
              900: "#664205",
              DEFAULT: "#FD971F",
              foreground: "#000000",
            },
            danger: {
              50: "#FFEBEE",
              100: "#FFCDD2",
              200: "#EF9A9A",
              300: "#E57373",
              400: "#F92672",
              500: "#E01E5B",
              600: "#C11849",
              700: "#A21237",
              800: "#820E2C",
              900: "#620A21",
              DEFAULT: "#F92672",
              foreground: "#FFFFFF",
            },
            focus: "#66D9EF",
          },
        },
      },
    }),
  ],
} satisfies Config;


