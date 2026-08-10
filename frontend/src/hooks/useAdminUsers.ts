import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { userService } from "../services/userService";
import type { SensitivityLevel } from "../types/security";
import type { User, UserRole } from "../types/users";

type UserChanges = {
  role?: UserRole;
  is_active?: boolean;
  clearance_level?: SensitivityLevel;
};

export function useAdminUsers(enabled: boolean) {
  const queryClient = useQueryClient();
  const users = useQuery({
    queryKey: queryKeys.users,
    queryFn: userService.list,
    enabled,
  });
  const invitation = useMutation({
    mutationFn: ({ email, role }: { email: string; role: UserRole }) =>
      userService.invite(email, role),
  });
  const update = useMutation({
    mutationFn: ({ target, changes }: { target: User; changes: UserChanges }) =>
      userService.update(target.id, changes),
    onSuccess: (updated) => {
      queryClient.setQueryData<User[]>(queryKeys.users, (current = []) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    },
  });
  const removal = useMutation({
    mutationFn: ({ id, hard }: { id: string; hard: boolean }) =>
      hard ? userService.deletePermanently(id) : userService.removeAccess(id),
    onSuccess: (_result, variables) => {
      queryClient.setQueryData<User[]>(queryKeys.users, (current = []) =>
        current.filter((item) => item.id !== variables.id),
      );
    },
  });
  const error = invitation.error ?? update.error ?? removal.error ?? users.error;

  return {
    users: users.data ?? [],
    loading: users.isLoading,
    refreshing: users.isFetching && !users.isLoading,
    busy: invitation.isPending || update.isPending || removal.isPending,
    error: error instanceof Error ? error.message : null,
    errorObject: error,
    refresh: users.refetch,
    invite: (email: string, role: UserRole) => invitation.mutateAsync({ email, role }),
    update: (target: User, changes: UserChanges) => update.mutateAsync({ target, changes }),
    remove: (id: string, hard: boolean) => removal.mutateAsync({ id, hard }),
  };
}
