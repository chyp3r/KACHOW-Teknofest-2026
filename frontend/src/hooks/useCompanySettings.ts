import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { companyService } from "../services/companyService";
import type { CompanyAdapter, CompanyProfile, CompanyRule } from "../types/management";

export function useCompanySettings(companyId: string | undefined) {
  const queryClient = useQueryClient();
  const enabled = Boolean(companyId);
  const profile = useQuery({ queryKey: queryKeys.companyProfile(companyId ?? ""), queryFn: () => companyService.profile(companyId!), enabled });
  const rules = useQuery({ queryKey: queryKeys.companyRules(companyId ?? ""), queryFn: () => companyService.rules(companyId!), enabled });
  const adapter = useQuery({ queryKey: queryKeys.companyAdapter(companyId ?? ""), queryFn: () => companyService.adapter(companyId!), enabled });
  const updateProfile = useMutation({
    mutationFn: (input: Omit<CompanyProfile, "company_id" | "version" | "updated_at">) => companyService.updateProfile(companyId!, input),
    onSuccess: (data) => queryClient.setQueryData(queryKeys.companyProfile(companyId!), data),
  });
  const updateRules = useMutation({
    mutationFn: (input: CompanyRule[]) => companyService.updateRules(companyId!, input),
    onSuccess: (data) => queryClient.setQueryData(queryKeys.companyRules(companyId!), data),
  });
  const updateAdapter = useMutation({
    mutationFn: (input: Pick<CompanyAdapter, "style_rules" | "preferred_examples" | "avoided_patterns">) => companyService.updateAdapter(companyId!, input),
    onSuccess: (data) => queryClient.setQueryData(queryKeys.companyAdapter(companyId!), data),
  });
  return {
    profile: profile.data, rules: rules.data, adapter: adapter.data,
    loading: profile.isLoading || rules.isLoading || adapter.isLoading,
    error: profile.error ?? rules.error ?? adapter.error ?? updateProfile.error ?? updateRules.error ?? updateAdapter.error,
    saving: updateProfile.isPending || updateRules.isPending || updateAdapter.isPending,
    updateProfile: updateProfile.mutateAsync, updateRules: updateRules.mutateAsync, updateAdapter: updateAdapter.mutateAsync,
  };
}
