import { Check, MessageSquarePlus, Search, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Input, Select } from "../../components/FormControls";
import { Spinner } from "../../components/Surface";
import { useFavorites } from "../../hooks/useFavorites";
import { useUserSearch } from "../../hooks/useUserSearch";
import { queryKeys } from "../../query/queryKeys";
import { unitsService } from "../../services/unitsService";
import { ASSIGNABLE_ROLE_LABELS } from "../../types/users";
import type { UserRole } from "../../types/users";
import { FavoritesPanel } from "./FavoritesPanel";
import { PersonResultRow } from "./PersonResultRow";

export interface PersonPickerBodyProps {
  excludeUserIds?: string[];
  //: "message": each row's action opens a DM immediately (the conversation
  //: list's "Kişiler" drawer, and the new-conversation dialog's DM tab).
  //: "select": each row toggles membership in `selectedUserIds` instead,
  //: nothing navigates (group creation / add-participants).
  mode: "message" | "select";
  onMessage?: (userId: string) => void;
  messagingUserId?: string | null;
  selectedUserIds?: string[];
  onToggleSelect?: (userId: string) => void;
}

// The shared body of both `UserSearchDrawer` (a side `Drawer`, browsing
// entry point) and `NewConversationDialog`'s DM/group tabs (a centered
// `Dialog`) -- filters, favorites-when-empty, and the result list are
// identical in both; only the surrounding chrome differs.
export function PersonPickerBody({
  excludeUserIds = [],
  mode,
  onMessage,
  messagingUserId = null,
  selectedUserIds = [],
  onToggleSelect,
}: PersonPickerBodyProps) {
  const [unitId, setUnitId] = useState("");
  const [role, setRole] = useState<UserRole | "">("");
  const search = useUserSearch(unitId, role);
  const favorites = useFavorites();
  const unitsQuery = useQuery({
    queryKey: queryKeys.units,
    queryFn: () => unitsService.list(),
    staleTime: 5 * 60_000,
  });

  const excluded = new Set(excludeUserIds);
  const showingFavorites = search.query.trim().length === 0;
  const results = search.results.filter((user) => !excluded.has(user.id));

  const rowAction = (userId: string, isSelected: boolean) => {
    if (mode === "select") {
      return (
        <Button
          size="sm"
          variant={isSelected ? "primary" : "outline"}
          leadingIcon={isSelected ? <Check /> : <UserPlus />}
          onClick={() => onToggleSelect?.(userId)}
        >
          {isSelected ? "Seçildi" : "Seç"}
        </Button>
      );
    }
    return (
      <Button
        size="sm"
        variant="outline"
        leadingIcon={<MessageSquarePlus />}
        loading={messagingUserId === userId}
        onClick={() => onMessage?.(userId)}
      >
        Mesaj
      </Button>
    );
  };

  return (
    <div className="person-picker">
      <div className="user-search-filters">
        <Input
          leadingIcon={<Search />}
          aria-label="Kullanıcı ara"
          placeholder="İsim veya e-posta ile ara"
          value={search.query}
          onChange={(event) => search.setQuery(event.target.value)}
        />
        <div className="user-search-filter-row">
          <Select
            aria-label="Birime göre filtrele"
            controlSize="sm"
            value={unitId}
            onChange={(event) => setUnitId(event.target.value)}
          >
            <option value="">Tüm birimler</option>
            {(unitsQuery.data ?? []).map((unit) => (
              <option key={unit.id} value={unit.id}>
                {unit.name}
              </option>
            ))}
          </Select>
          <Select
            aria-label="Role göre filtrele"
            controlSize="sm"
            value={role}
            onChange={(event) => setRole(event.target.value as UserRole | "")}
          >
            <option value="">Tüm roller</option>
            {(Object.keys(ASSIGNABLE_ROLE_LABELS) as Exclude<UserRole, "root">[]).map((value) => (
              <option key={value} value={value}>
                {ASSIGNABLE_ROLE_LABELS[value]}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {showingFavorites && mode === "message" ? (
        <FavoritesPanel onMessage={(userId) => onMessage?.(userId)} messagingUserId={messagingUserId} />
      ) : showingFavorites && excluded.size === 0 && results.length === 0 && !search.loading ? (
        <EmptyState
          compact
          icon={Users}
          title="Aramaya başlayın"
          description="İsim veya e-posta yazarak eklemek istediğiniz kişiyi bulun."
        />
      ) : search.isSearching ? (
        <p className="user-search-hint">En az {search.minLength} karakter yazın.</p>
      ) : search.loading ? (
        <div className="centered-state" role="status">
          <Spinner label="Kullanıcılar aranıyor" />
          Aranıyor…
        </div>
      ) : results.length === 0 ? (
        <EmptyState
          compact
          icon={Users}
          title="Sonuç bulunamadı"
          description="Farklı bir isim, birim veya rol ile tekrar deneyin."
        />
      ) : (
        <div className="person-list" role="list" aria-label="Arama sonuçları">
          {results.map((user) => (
            <PersonResultRow
              key={user.id}
              username={user.username}
              email={user.email}
              role={user.role}
              unitName={user.unit_name}
              isFavorite={favorites.favoriteIds.has(user.id) || user.is_favorite}
              onToggleFavorite={() =>
                void (favorites.favoriteIds.has(user.id) || user.is_favorite
                  ? favorites.remove(user.id)
                  : favorites.add(user.id))
              }
              action={rowAction(user.id, selectedUserIds.includes(user.id))}
            />
          ))}
        </div>
      )}
    </div>
  );
}
