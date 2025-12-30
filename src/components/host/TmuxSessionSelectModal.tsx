import { Chip, Divider, Input, Listbox, ListboxItem, Modal, ModalBody, ModalContent, ModalFooter, ModalHeader, Spinner } from "@nextui-org/react";
import { useState } from "react";
import type { RemoteTmuxSession } from "../../lib/tauri-api";
import { Button } from "../ui";

function IconTerminal({ className }: { className?: string }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 17l6-6-6-6" />
      <path d="M12 19h8" />
    </svg>
  );
}

export function TmuxSessionSelectModal({
  sessions,
  isOpen,
  onClose,
  onSelect,
  onCreate,
  isLoading,
}: {
  sessions: RemoteTmuxSession[];
  isOpen: boolean;
  onClose: () => void;
  onSelect: (sessionName: string) => void;
  onCreate: (sessionName: string) => void;
  isLoading: boolean;
}) {
  const [newSessionName, setNewSessionName] = useState("");

  const handleCreate = () => {
    const name = newSessionName.trim() || "main";
    onCreate(name);
  };

  return (
    <Modal isOpen={isOpen} onOpenChange={(open) => !open && onClose()} isDismissable={true} size="md">
      <ModalContent>
        <ModalHeader className="flex items-center gap-2">
          <IconTerminal />
          Select Tmux Session
        </ModalHeader>
        <ModalBody className="gap-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Spinner size="lg" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="text-center py-4">
              <p className="text-foreground/60 mb-4">No tmux sessions running on this host.</p>
              <p className="text-sm text-foreground/50">A new session will be created when you connect.</p>
            </div>
          ) : (
            <>
              <p className="text-sm text-foreground/60">
                Found {sessions.length} existing session{sessions.length > 1 ? "s" : ""}. Select one to attach:
              </p>
              <Listbox
                aria-label="Tmux sessions"
                selectionMode="single"
                onAction={(key) => onSelect(String(key))}
                className="p-0"
              >
                {sessions.map((s) => (
                  <ListboxItem
                    key={s.name}
                    description={
                      <span className="flex items-center gap-2">
                        <span>{s.windows} window{s.windows !== 1 ? "s" : ""}</span>
                        {s.attached && (
                          <Chip size="sm" color="success" variant="flat" className="h-5">
                            attached
                          </Chip>
                        )}
                      </span>
                    }
                    className="py-3"
                  >
                    <span className="font-mono font-medium">{s.name}</span>
                  </ListboxItem>
                ))}
              </Listbox>
              <Divider />
            </>
          )}

          <div>
            <p className="text-sm font-medium mb-2">Or create a new session:</p>
            <div className="flex gap-2">
              <Input
                labelPlacement="inside"
                placeholder="Session name (default: main)"
                value={newSessionName}
                onValueChange={setNewSessionName}
                size="sm"
                className="flex-1"
                classNames={{ input: "font-mono" }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreate();
                }}
              />
              <Button
                color="primary"
                size="sm"
                onPress={handleCreate}
                className="min-w-[80px]"
              >
                Create
              </Button>
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="flat" onPress={onClose}>
            Cancel
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
