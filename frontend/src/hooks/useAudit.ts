import { useMutation, useQuery } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { auditService, type AuditFilters } from "../services/auditService";

export function useAudit(companyId?: string, filters: AuditFilters = {}) {
  const scoped = { ...filters, companyId: filters.companyId ?? companyId };
  const list = useQuery({
    queryKey: [...queryKeys.audit(companyId), scoped.actorUserId ?? "", scoped.action ?? "", scoped.resourceType ?? ""],
    queryFn: () => auditService.list(scoped),
  });
  const verify = useMutation({ mutationFn: () => auditService.verify(companyId) });
  return {
    entries: list.data?.items ?? [], total: list.data?.total ?? 0, loading: list.isLoading,
    error: list.error ?? verify.error, verification: verify.data, verifying: verify.isPending,
    verify: verify.mutateAsync,
  };
}
