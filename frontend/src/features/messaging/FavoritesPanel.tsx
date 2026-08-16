import { MessageSquarePlus, Star } from "lucide-react";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Surface";
import { useFavorites } from "../../hooks/useFavorites";
import { PersonResultRow } from "./PersonResultRow";

export function FavoritesPanel({
  onMessage,
  messagingUserId,
}: {
  onMessage: (userId: string) => void;
  //: The favorite currently being messaged (disables its own button while
  //: the DM open request for it is in flight) -- `null` otherwise.
  messagingUserId?: string | null;
}) {
  const favorites = useFavorites();

  if (favorites.loading) {
    return (
      <div className="centered-state" role="status">
        <Spinner label="Favoriler yükleniyor" />
        Favoriler yükleniyor…
      </div>
    );
  }

  if (favorites.favorites.length === 0) {
    return (
      <EmptyState
        compact
        icon={Star}
        title="Henüz favori kullanıcınız yok"
        description="Arama sonuçlarındaki yıldız simgesiyle bir kullanıcıyı favorilerinize ekleyebilirsiniz."
      />
    );
  }

  return (
    <div className="person-list" role="list" aria-label="Favori kullanıcılar">
      {favorites.favorites.map((favorite) => (
        <PersonResultRow
          key={favorite.id}
          username={favorite.username}
          email={favorite.email}
          isFavorite
          onToggleFavorite={() => void favorites.remove(favorite.favorite_user_id)}
          action={
            <Button
              size="sm"
              variant="outline"
              leadingIcon={<MessageSquarePlus />}
              loading={messagingUserId === favorite.favorite_user_id}
              onClick={() => onMessage(favorite.favorite_user_id)}
            >
              Mesaj
            </Button>
          }
        />
      ))}
    </div>
  );
}
