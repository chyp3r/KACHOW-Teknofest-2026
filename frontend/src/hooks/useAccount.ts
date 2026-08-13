import { useMutation } from "@tanstack/react-query";
import { userService } from "../services/userService";

export function useAccount() {
  const password = useMutation({
    mutationFn: ({ currentPassword, newPassword }: { currentPassword: string; newPassword: string }) =>
      userService.changePassword(currentPassword, newPassword),
  });
  return {
    changingPassword: password.isPending,
    passwordChanged: password.isSuccess,
    error: password.error instanceof Error ? password.error.message : null,
    errorObject: password.error,
    changePassword: password.mutateAsync,
    reset: password.reset,
  };
}
