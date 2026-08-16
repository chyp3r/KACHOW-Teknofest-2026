import type { RefObject } from "react";
import { Drawer } from "../../components/Overlay";
import { PersonPickerBody, type PersonPickerBodyProps } from "./PersonPickerBody";

export function UserSearchDrawer({
  open,
  onClose,
  returnFocusRef,
  ...pickerProps
}: PersonPickerBodyProps & {
  open: boolean;
  onClose: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
}) {
  return (
    <Drawer
      open={open}
      id="user-search-drawer"
      className="user-search-drawer"
      title="Kişiler"
      closeLabel="Kişiler panelini kapat"
      onClose={onClose}
      returnFocusRef={returnFocusRef}
    >
      <PersonPickerBody {...pickerProps} />
    </Drawer>
  );
}
