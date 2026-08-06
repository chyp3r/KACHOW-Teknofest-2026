import { useContext } from "react";
import { ThemeContext, type ThemeContextValue } from "../contexts/ThemeContext";

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value)
    throw new Error("useTheme, ThemeProvider içinde kullanılmalıdır.");
  return value;
}
