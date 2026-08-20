import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { unitsService } from "../services/unitsService";
import type { Unit } from "../types/units";

export function useUnitManagement(selectedUnitId?: string) {
  const queryClient = useQueryClient();
  const units = useQuery({ queryKey: queryKeys.units, queryFn: unitsService.list });
  const members = useQuery({
    queryKey: queryKeys.unitMembers(selectedUnitId ?? ""),
    queryFn: () => unitsService.members(selectedUnitId!),
    enabled: Boolean(selectedUnitId),
  });
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: queryKeys.units });
  const invalidateMembers = () => {
    if (selectedUnitId) void queryClient.invalidateQueries({ queryKey: queryKeys.unitMembers(selectedUnitId) });
  };
  const create = useMutation({ mutationFn: unitsService.create, onSuccess: invalidate });
  const update = useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: Partial<Pick<Unit, "name" | "description" | "is_active">> }) => unitsService.update(id, changes),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: unitsService.remove, onSuccess: invalidate });
  const addMember = useMutation({
    mutationFn: ({ unitId, userId, isPrimary, roleInUnit }: { unitId: string; userId: string; isPrimary: boolean; roleInUnit?: string }) =>
      unitsService.addMember(unitId, { user_id: userId, is_primary: isPrimary, role_in_unit: roleInUnit || null }),
    onSuccess: invalidateMembers,
  });
  const removeMember = useMutation({
    mutationFn: ({ unitId, userId }: { unitId: string; userId: string }) => unitsService.removeMember(unitId, userId),
    onSuccess: invalidateMembers,
  });
  return {
    units: units.data ?? [], members: members.data ?? [], loading: units.isLoading,
    membersLoading: members.isLoading, error: units.error ?? members.error ?? create.error ?? update.error ?? remove.error ?? addMember.error ?? removeMember.error,
    busy: create.isPending || update.isPending || remove.isPending || addMember.isPending || removeMember.isPending,
    create: create.mutateAsync, update: update.mutateAsync, remove: remove.mutateAsync,
    addMember: addMember.mutateAsync, removeMember: removeMember.mutateAsync,
  };
}
