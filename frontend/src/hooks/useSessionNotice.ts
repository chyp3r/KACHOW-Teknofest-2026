import { useState } from "react";
import { consumeSessionNotice } from "../services/apiClient";

export function useSessionNotice() {
  const [notice] = useState(consumeSessionNotice);
  return notice;
}
