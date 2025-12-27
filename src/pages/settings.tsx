import {
  Card,
  CardBody,
  CardHeader,
  Chip,
  Divider,
  Input,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  Select,
  SelectItem,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
  Textarea,
  Tooltip,
  useDisclosure
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  getConfig,
  pricingApi,
  saveConfig,
  secretsApi,
  sshGenerateKey,
  sshKeyCandidates,
  sshPublicKey,
  useColabPricingCalculation,
  useUpdateColabGpuPricing,
  useUpdateColabSubscription
} from "../lib/tauri-api";
import type { ColabGpuPricing, Currency, SecretMeta, SecretSuggestion, TrainshConfig } from "../lib/types";

// ============================================================
// Currency Helpers
// ============================================================

const CURRENCIES: { value: Currency; label: string; symbol: string }[] = [
  { value: "USD", label: "US Dollar", symbol: "$" },
  { value: "JPY", label: "Japanese Yen", symbol: "¥" },
  { value: "HKD", label: "Hong Kong Dollar", symbol: "HK$" },
  { value: "CNY", label: "Chinese Yuan", symbol: "¥" },
  { value: "EUR", label: "Euro", symbol: "€" },
  { value: "GBP", label: "British Pound", symbol: "£" },
  { value: "KRW", label: "Korean Won", symbol: "₩" },
  { value: "TWD", label: "Taiwan Dollar", symbol: "NT$" }
];

function getCurrencySymbol(currency: Currency): string {
  return CURRENCIES.find((c) => c.value === currency)?.symbol ?? "$";
}

function formatPrice(price: number, currency?: Currency, decimals = 4): string {
  const symbol = currency ? getCurrencySymbol(currency) : "$";
  return `${symbol}${price.toFixed(decimals)}`;
}

// ============================================================
// Icons
// ============================================================

function IconSettings({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

function IconServer({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
    </svg>
  );
}

function IconBeaker({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
    </svg>
  );
}

function IconKey({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
    </svg>
  );
}

function IconCopy({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
    </svg>
  );
}

function IconEdit({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
    </svg>
  );
}

function IconTrash({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
    </svg>
  );
}

function IconEye({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

function IconEyeOff({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
    </svg>
  );
}

function IconX({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

// ============================================================
// Section Card Component
// ============================================================

type SectionIconType = "settings" | "server" | "beaker" | "key";

const SECTION_STYLES: Record<SectionIconType, { bg: string; color: string }> = {
  settings: { bg: "bg-slate-500/10", color: "text-slate-600 dark:text-slate-400" },
  server: { bg: "bg-blue-500/10", color: "text-blue-600 dark:text-blue-400" },
  beaker: { bg: "bg-amber-500/10", color: "text-amber-600 dark:text-amber-400" },
  key: { bg: "bg-rose-500/10", color: "text-rose-600 dark:text-rose-400" },
};

function SectionCard({ 
  title, 
  subtitle, 
  icon, 
  children,
  actions
}: { 
  title: string; 
  subtitle?: string; 
  icon: SectionIconType;
  children: React.ReactNode;
  actions?: React.ReactNode;
}) {
  const style = SECTION_STYLES[icon];
  
  const IconComponent = {
    settings: IconSettings,
    server: IconServer,
    beaker: IconBeaker,
    key: IconKey,
  }[icon];
  
  return (
    <Card className="bg-content1 shadow-md border border-divider/50">
      <CardHeader className="flex justify-between items-start gap-3 pb-3 border-b border-divider/30">
        <div className="flex gap-3 items-center">
          <div className={`w-10 h-10 rounded-xl ${style.bg} flex items-center justify-center`}>
            <IconComponent className={`w-5 h-5 ${style.color}`} />
          </div>
          <div>
            <h3 className="text-base font-semibold">{title}</h3>
            {subtitle && <p className="text-xs text-foreground/50">{subtitle}</p>}
          </div>
        </div>
        {actions}
      </CardHeader>
      <CardBody className="pt-4">
        {children}
      </CardBody>
    </Card>
  );
}

// ============================================================
// Main Settings Page
// ============================================================

export function SettingsPage() {
  const cfgQuery = useQuery({
    queryKey: ["config"],
    queryFn: getConfig
  });
  const keysQuery = useQuery({
    queryKey: ["sshKeyCandidates"],
    queryFn: sshKeyCandidates
  });

  const [draft, setDraft] = useState<TrainshConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const [pubKey, setPubKey] = useState<string>("");
  const [pubKeyError, setPubKeyError] = useState<string | null>(null);
  const [pubKeyLoading, setPubKeyLoading] = useState(false);

  const genModal = useDisclosure();
  const [genPath, setGenPath] = useState("~/.ssh/doppio_ed25519");
  const [genComment, setGenComment] = useState("doppio");
  const [genLoading, setGenLoading] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  useEffect(() => {
    if (cfgQuery.data) {
      setDraft(cfgQuery.data);
    }
  }, [cfgQuery.data]);

  const isDirty = useMemo(() => {
    if (!draft || !cfgQuery.data) return false;
    return JSON.stringify(draft) !== JSON.stringify(cfgQuery.data);
  }, [draft, cfgQuery.data]);

  async function onSave() {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    try {
      await saveConfig(draft);
      setSavedAt(new Date().toLocaleString());
      await cfgQuery.refetch();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setSaveError(msg);
    } finally {
      setSaving(false);
    }
  }

  const isLoading = cfgQuery.isLoading || !draft;

  if (isLoading) {
  return (
      <div className="h-full flex items-center justify-center">
          <Spinner size="lg" />
        </div>
    );
  }

  if (cfgQuery.error) {
    return (
      <div className="h-full p-6">
        <Card>
          <CardBody>
            <div className="text-sm text-danger">
              Failed to load config: {(cfgQuery.error as Error)?.message ?? "Unknown error"}
            </div>
          </CardBody>
        </Card>
            </div>
    );
  }

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-4xl mx-auto p-6 space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Settings</h1>
            <p className="text-sm text-foreground/50">Configuration saved locally</p>
          </div>
          <div className="flex items-center gap-3">
            {savedAt && !saveError && (
              <span className="text-xs text-success flex items-center gap-1">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
                Saved {savedAt}
              </span>
            )}
            {saveError && (
              <span className="text-xs text-danger">Failed: {saveError}</span>
            )}
            <Button
              size="sm"
              variant="flat"
              isDisabled={saving || !cfgQuery.data}
              onPress={() => cfgQuery.data && setDraft(cfgQuery.data)}
            >
              Reset
            </Button>
            <Button 
              size="sm"
              color="primary" 
              isLoading={saving} 
              isDisabled={!draft || saving || !isDirty} 
              onPress={onSave}
            >
              Save Changes
            </Button>
          </div>
        </div>

        {/* Section 1: General */}
        <SectionCard icon="settings" title="General" subtitle="Default paths and preferences">
                <Input
            label="HuggingFace Cache (HF_HOME)"
                  value={draft.colab.hf_home ?? ""}
                  onValueChange={(v) =>
              setDraft({ ...draft, colab: { ...draft.colab, hf_home: v.trim() ? v : null } })
                  }
                  placeholder="~/.cache/huggingface"
            description="Default HF_HOME for remote training (leave empty for system default)"
                  size="sm"
            variant="flat"
            classNames={{ inputWrapper: "bg-content2" }}
          />
        </SectionCard>

        {/* Section 2: Vast.ai (API + SSH + Pricing) */}
        <SectionCard icon="server" title="Vast.ai" subtitle="API key, SSH settings, and pricing rates">
          <div className="space-y-6">
            {/* API & Console */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Input
                    label="API Key"
                    type="password"
                    value={draft.vast.api_key ?? ""}
                    onValueChange={(v) =>
                  setDraft({ ...draft, vast: { ...draft.vast, api_key: v.trim() ? v : null } })
                    }
                description="For Vast.ai Console API"
                    size="sm"
                variant="flat"
                classNames={{ inputWrapper: "bg-content2" }}
                  />
                  <Input
                    label="Console URL"
                    value={draft.vast.url}
                    onValueChange={(v) =>
                  setDraft({ ...draft, vast: { ...draft.vast, url: v } })
                    }
                    size="sm"
                variant="flat"
                classNames={{ inputWrapper: "bg-content2" }}
                  />
                </div>

            <Divider />

            {/* SSH Settings */}
            <div>
              <h4 className="text-sm font-medium mb-3">SSH Settings</h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Input
                    label="SSH User"
                    value={draft.vast.ssh_user}
                    onValueChange={(v) =>
                    setDraft({ ...draft, vast: { ...draft.vast, ssh_user: v } })
                    }
                    size="sm"
                  variant="flat"
                  classNames={{ inputWrapper: "bg-content2" }}
                  />
                  <Input
                    label="SSH Key Path"
                    value={draft.vast.ssh_key_path ?? ""}
                    onValueChange={(v) =>
                    setDraft({ ...draft, vast: { ...draft.vast, ssh_key_path: v.trim() ? v : null } })
                    }
                    placeholder="~/.ssh/id_ed25519"
                    size="sm"
                  variant="flat"
                  classNames={{ inputWrapper: "bg-content2" }}
                  />
                </div>

              {/* Detected Keys */}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-xs text-foreground/50">Detected keys:</span>
                    {keysQuery.isLoading ? (
                  <Spinner size="sm" />
                    ) : keysQuery.data && keysQuery.data.length > 0 ? (
                      keysQuery.data.map((p) => (
                    <Chip
                          key={p}
                          size="sm"
                          variant={draft.vast.ssh_key_path === p ? "solid" : "flat"}
                          color={draft.vast.ssh_key_path === p ? "primary" : "default"}
                      className="cursor-pointer"
                      onClick={() => setDraft({ ...draft, vast: { ...draft.vast, ssh_key_path: p } })}
                        >
                          {p.split("/").slice(-2).join("/")}
                    </Chip>
                      ))
                    ) : (
                  <span className="text-xs text-foreground/40">none</span>
                    )}
                  </div>

              {/* SSH Key Actions */}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      variant="flat"
                      isDisabled={!draft.vast.ssh_key_path || pubKeyLoading}
                      isLoading={pubKeyLoading}
                      onPress={async () => {
                        if (!draft.vast.ssh_key_path) return;
                        setPubKeyError(null);
                        setPubKey("");
                        setPubKeyLoading(true);
                        try {
                          const key = await sshPublicKey(draft.vast.ssh_key_path);
                          setPubKey(key);
                        } catch (e) {
                      setPubKeyError(e instanceof Error ? e.message : String(e));
                        } finally {
                          setPubKeyLoading(false);
                        }
                      }}
                    >
                  Show Public Key
                    </Button>
                <Button size="sm" variant="flat" onPress={() => genModal.onOpen()}>
                  Generate New Key
                    </Button>
                    <Button
                      size="sm"
                      variant="flat"
                      isDisabled={!pubKey.trim()}
                  onPress={() => navigator.clipboard.writeText(pubKey.trim())}
                    >
                  Copy Public Key
                    </Button>
                <span className="text-xs text-foreground/50">
                  Add to Vast.ai Console → Account → SSH Keys
                    </span>
                  </div>

              {pubKeyError && <div className="mt-2 text-xs text-danger">{pubKeyError}</div>}
                {pubKey.trim() && (
                  <Textarea
                  className="mt-3"
                    value={pubKey}
                    minRows={2}
                    isReadOnly
                  variant="flat"
                  classNames={{ input: "font-mono text-xs", inputWrapper: "bg-content2" }}
                  />
                )}
            </div>

            <Divider />

            {/* Vast Pricing Rates */}
                <VastPricingSection />
              </div>
        </SectionCard>

        {/* Section 3: Google Colab (Subscription + GPU Pricing) */}
        <SectionCard icon="beaker" title="Google Colab" subtitle="Subscription pricing and GPU compute unit rates">
                <ColabPricingSection />
        </SectionCard>

        {/* Section 4: Secrets */}
        <SectionCard icon="key" title="Secrets" subtitle="API keys and tokens stored securely in OS keychain">
                <SecretsSection />
        </SectionCard>

      {/* Generate SSH Key Modal */}
        <Modal isOpen={genModal.isOpen} onOpenChange={genModal.onOpenChange}>
        <ModalContent>
          {(onClose) => (
            <>
                <ModalHeader>Generate SSH Key</ModalHeader>
                <ModalBody className="gap-4">
                <Input
                    label="Key Path"
                  value={genPath}
                  onValueChange={setGenPath}
                  placeholder="~/.ssh/doppio_ed25519"
                    description="Will run ssh-keygen -t ed25519; only ~/.ssh paths allowed"
                    variant="bordered"
                />
                <Input
                    label="Comment"
                  value={genComment}
                  onValueChange={setGenComment}
                  placeholder="doppio"
                    variant="bordered"
                />
                  {genError && <div className="text-sm text-danger">{genError}</div>}
              </ModalBody>
              <ModalFooter>
                <Button variant="flat" onPress={onClose} isDisabled={genLoading}>
                  Cancel
                </Button>
                <Button
                  color="primary"
                  isLoading={genLoading}
                  onPress={async () => {
                    setGenError(null);
                    setGenLoading(true);
                    try {
                      const info = await sshGenerateKey({
                        path: genPath.trim(),
                          comment: genComment.trim() || null
                      });
                      if (draft) {
                        setDraft({ ...draft, vast: { ...draft.vast, ssh_key_path: info.private_key_path } });
                      }
                      setPubKey(info.public_key);
                      await keysQuery.refetch();
                      onClose();
                    } catch (e) {
                        setGenError(e instanceof Error ? e.message : String(e));
                    } finally {
                      setGenLoading(false);
                    }
                  }}
                >
                  Generate
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
      </div>
    </div>
  );
}

// ============================================================
// Vast.ai Pricing Section
// ============================================================

function VastPricingSection() {
  const pricingQuery = useQuery({
    queryKey: ["pricing"],
    queryFn: pricingApi.get
  });

  const settings = pricingQuery.data;

  if (pricingQuery.isLoading) {
    return <Spinner size="sm" />;
  }

  if (!settings?.vast_rates) {
    return null;
  }

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium">Default Pricing Rates</h4>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="flex justify-between items-center p-3 bg-content2 rounded-lg">
          <span className="text-sm text-foreground/60">Storage</span>
          <span className="font-mono text-sm">${settings.vast_rates.storage_per_gb_month}/GB/mo</span>
        </div>
        <div className="flex justify-between items-center p-3 bg-content2 rounded-lg">
          <span className="text-sm text-foreground/60">Egress</span>
          <span className="font-mono text-sm">${settings.vast_rates.network_egress_per_gb}/GB</span>
        </div>
        <div className="flex justify-between items-center p-3 bg-content2 rounded-lg">
          <span className="text-sm text-foreground/60">Ingress</span>
          <span className="font-mono text-sm">${settings.vast_rates.network_ingress_per_gb}/GB</span>
        </div>
      </div>
      <p className="text-xs text-foreground/40">
        GPU hourly rates are fetched from Vast.ai API per instance.
      </p>
    </div>
  );
}

// ============================================================
// Colab Pricing Section (Subscription + GPU Pricing together)
// ============================================================

function ColabPricingSection() {
  const queryClient = useQueryClient();
  const pricingQuery = useQuery({ queryKey: ["pricing"], queryFn: pricingApi.get });
  const calculationQuery = useColabPricingCalculation();
  const updateSubscription = useUpdateColabSubscription();
  const updateGpuPricing = useUpdateColabGpuPricing();

  const [subName, setSubName] = useState("");
  const [subPrice, setSubPrice] = useState("");
  const [subCurrency, setSubCurrency] = useState<Currency>("USD");
  const [subUnits, setSubUnits] = useState("");
  const [gpuList, setGpuList] = useState<ColabGpuPricing[]>([]);
  const [newGpuName, setNewGpuName] = useState("");
  const [newGpuUnits, setNewGpuUnits] = useState("");

  useEffect(() => {
    if (pricingQuery.data) {
      const { subscription, gpu_pricing } = pricingQuery.data.colab;
      setSubName(subscription.name);
      setSubPrice(subscription.price.toString());
      setSubCurrency(subscription.currency);
      setSubUnits(subscription.total_units.toString());
      setGpuList(gpu_pricing);
    }
  }, [pricingQuery.data]);

  const handleSaveSubscription = async () => {
    const price = parseFloat(subPrice);
    const units = parseFloat(subUnits);
    if (isNaN(price) || isNaN(units) || price <= 0 || units <= 0) return;
    await updateSubscription.mutateAsync({
      name: subName.trim() || "Colab Pro",
      price,
      currency: subCurrency,
      total_units: units
    });
  };

  const handleSaveGpuPricing = async () => {
    await updateGpuPricing.mutateAsync(gpuList);
  };

  const handleAddGpu = () => {
    const units = parseFloat(newGpuUnits);
    if (!newGpuName.trim() || isNaN(units) || units <= 0) return;
    setGpuList((prev) => [...prev, { gpu_name: newGpuName.trim(), units_per_hour: units }]);
    setNewGpuName("");
    setNewGpuUnits("");
  };

  const calculation = calculationQuery.data;

  if (pricingQuery.isLoading) {
    return <Spinner size="lg" className="mx-auto" />;
  }

  return (
    <div className="space-y-6">
      {/* Subscription Settings */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-medium">Subscription</h4>
          <Button
            size="sm"
            color="primary"
            variant="flat"
            onPress={handleSaveSubscription}
            isLoading={updateSubscription.isPending}
          >
            Save
          </Button>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Input
            label="Plan Name"
            value={subName}
            onValueChange={setSubName}
            placeholder="Colab Pro"
            size="sm"
            variant="flat"
            classNames={{ inputWrapper: "bg-content2" }}
          />
          <Input
            label="Price"
            type="number"
            value={subPrice}
            onValueChange={setSubPrice}
            placeholder="11.99"
            startContent={<span className="text-foreground/50 text-xs">{getCurrencySymbol(subCurrency)}</span>}
            size="sm"
            variant="flat"
            classNames={{ inputWrapper: "bg-content2" }}
          />
          <Select
            label="Currency"
            selectedKeys={[subCurrency]}
            onSelectionChange={(keys) => {
              const selected = Array.from(keys)[0] as Currency;
              if (selected) setSubCurrency(selected);
            }}
            size="sm"
            variant="flat"
            classNames={{ trigger: "bg-content2" }}
          >
            {CURRENCIES.map((c) => (
              <SelectItem key={c.value} textValue={`${c.symbol} ${c.label}`}>
                {c.symbol} {c.label}
              </SelectItem>
            ))}
          </Select>
          <Input
            label="Compute Units"
            type="number"
            value={subUnits}
            onValueChange={setSubUnits}
            placeholder="100"
            size="sm"
            variant="flat"
            classNames={{ inputWrapper: "bg-content2" }}
          />
        </div>

        {calculation && (
          <div className="flex justify-between items-center p-3 bg-success/10 rounded-lg">
            <span className="text-sm text-foreground/70">Price per compute unit</span>
            <span className="font-mono font-semibold text-success">
              {formatPrice(calculation.price_per_unit_usd, "USD")}
            </span>
          </div>
        )}
      </div>

      <Divider />

      {/* GPU Pricing Table */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-medium">GPU Pricing</h4>
            <Button
              size="sm"
              color="primary"
            variant="flat"
              onPress={handleSaveGpuPricing}
              isLoading={updateGpuPricing.isPending}
              isDisabled={gpuList.length === 0}
            >
              Save
            </Button>
        </div>

        <Table removeWrapper aria-label="GPU pricing" classNames={{ base: "max-h-[280px] overflow-auto" }}>
          <TableHeader>
            <TableColumn>GPU</TableColumn>
            <TableColumn width={90}>Units/Hr</TableColumn>
            <TableColumn width={100}>Units/24Hr</TableColumn>
            <TableColumn width={85}>USD/Hr</TableColumn>
            <TableColumn width={95}>USD/24Hr</TableColumn>
            <TableColumn width={40}> </TableColumn>
          </TableHeader>
          <TableBody emptyContent="No GPUs configured">
            {gpuList.map((gpu, idx) => {
              const calcGpu = calculation?.gpu_prices.find((g) => g.gpu_name === gpu.gpu_name);
              return (
                <TableRow key={idx}>
                  <TableCell>
                    <Input
                      value={gpu.gpu_name}
                      onValueChange={(v) => {
                        if (v.trim()) {
                          setGpuList((prev) => prev.map((g, i) => (i === idx ? { ...g, gpu_name: v } : g)));
                        }
                      }}
                      size="sm"
                      variant="underlined"
                      classNames={{ input: "font-semibold", inputWrapper: "h-8" }}
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      type="number"
                      value={gpu.units_per_hour.toString()}
                      onValueChange={(v) => {
                        const val = parseFloat(v);
                        if (!isNaN(val) && val > 0) {
                          setGpuList((prev) => prev.map((g, i) => (i === idx ? { ...g, units_per_hour: val } : g)));
                        }
                      }}
                      size="sm"
                      variant="underlined"
                      classNames={{ input: "text-center w-14", inputWrapper: "h-8" }}
                    />
                  </TableCell>
                  <TableCell className="font-mono text-foreground/60">
                    {(gpu.units_per_hour * 24).toFixed(1)}
                  </TableCell>
                  <TableCell className="font-mono text-success">
                    {calcGpu ? formatPrice(calcGpu.price_usd_per_hour, "USD") : "-"}
                  </TableCell>
                  <TableCell className="font-mono text-warning">
                    {calcGpu ? formatPrice(calcGpu.price_usd_per_hour * 24, "USD", 2) : "-"}
                  </TableCell>
                  <TableCell>
                    <Button
                      isIconOnly
                      size="sm"
                      variant="light"
                      color="danger"
                      onPress={() => setGpuList((prev) => prev.filter((_, i) => i !== idx))}
                    >
                      <IconX className="w-4 h-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>

        {/* Add new GPU */}
        <div className="flex items-end gap-3">
          <Input
            label="New GPU"
            value={newGpuName}
            onValueChange={setNewGpuName}
            placeholder="e.g., A100"
            size="sm"
            variant="flat"
            classNames={{ inputWrapper: "bg-content2", base: "flex-1" }}
          />
          <Input
            label="Units/Hr"
            type="number"
            value={newGpuUnits}
            onValueChange={setNewGpuUnits}
            placeholder="12.29"
            size="sm"
            variant="flat"
            classNames={{ inputWrapper: "bg-content2", base: "w-28" }}
          />
          <Button
            color="primary"
            variant="flat"
            size="sm"
            onPress={handleAddGpu}
            isDisabled={!newGpuName.trim() || !newGpuUnits.trim()}
          >
            Add
          </Button>
        </div>

        {calculation && (
          <p className="text-xs text-foreground/40">
            Based on {calculation.subscription.name} at{" "}
            {formatPrice(calculation.subscription.price, calculation.subscription.currency, 2)} for{" "}
            {calculation.subscription.total_units} compute units
          </p>
        )}
      </div>
    </div>
  );
}

// ============================================================
// Secrets Section
// ============================================================

function SecretsSection() {
  const queryClient = useQueryClient();

  const secretsQuery = useQuery({ queryKey: ["secrets"], queryFn: secretsApi.list });
  const suggestionsQuery = useQuery({ queryKey: ["secretSuggestions"], queryFn: secretsApi.suggestions });

  const upsertMutation = useMutation({
    mutationFn: secretsApi.upsert,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["secrets"] })
  });
  const deleteMutation = useMutation({
    mutationFn: secretsApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["secrets"] })
  });

  const { isOpen, onOpen, onOpenChange, onClose } = useDisclosure();
  const [editName, setEditName] = useState("");
  const [editValue, setEditValue] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [showValue, setShowValue] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const openAddModal = (suggestion?: SecretSuggestion) => {
    setIsEditing(false);
    setEditName(suggestion?.name || "");
    setEditValue("");
    setEditDescription(suggestion?.description || "");
    setShowValue(false);
    onOpen();
  };

  const openEditModal = async (secret: SecretMeta) => {
    setIsEditing(true);
    setEditName(secret.name);
    setEditDescription(secret.description || "");
    setShowValue(false);
    try {
      const full = await secretsApi.get(secret.name);
      setEditValue(full.value);
    } catch {
      setEditValue("");
    }
    onOpen();
  };

  const secrets = secretsQuery.data || [];
  const suggestions = suggestionsQuery.data || [];
  const unusedSuggestions = suggestions.filter((s) => !secrets.find((sec) => sec.name === s.name));

  if (secretsQuery.isLoading) {
    return <Spinner size="lg" className="mx-auto" />;
  }

  return (
    <div className="space-y-4">
      {/* Info banner */}
      <div className="p-3 bg-primary/10 rounded-lg flex items-start gap-2">
        <IconKey className="w-4 h-4 mt-0.5 text-primary flex-shrink-0" />
        <p className="text-sm text-foreground/80">
          <strong>Secure Storage:</strong> Secrets are stored in your OS keychain.
          Use <code className="px-1 py-0.5 bg-content2 rounded text-xs font-mono">${"{secret:name}"}</code> syntax in recipes.
        </p>
      </div>

      {/* Secrets list */}
      {secrets.length === 0 ? (
        <div className="text-sm text-foreground/50 py-4 text-center">No secrets configured</div>
      ) : (
        <div className="space-y-2">
          {secrets.map((secret) => (
            <div key={secret.name} className="flex items-center gap-2 p-3 bg-content2 rounded-lg">
              <div className="flex-1 min-w-0">
                <div className="font-mono text-sm truncate">{secret.name}</div>
                {secret.description && (
                  <div className="text-xs text-foreground/50 truncate">{secret.description}</div>
                )}
              </div>
              <span className="text-xs text-foreground/40">
                {new Date(secret.updated_at).toLocaleDateString()}
              </span>
              <Tooltip content="Copy reference">
                <Button
                  size="sm"
                  variant="light"
                  isIconOnly
                  onPress={() => navigator.clipboard.writeText(`\${secret:${secret.name}}`)}
                >
                  <IconCopy className="w-4 h-4" />
                </Button>
              </Tooltip>
              <Button size="sm" variant="light" isIconOnly onPress={() => openEditModal(secret)}>
                <IconEdit className="w-4 h-4" />
              </Button>
              <Button
                size="sm"
                variant="light"
                color="danger"
                isIconOnly
                onPress={() => setDeleteTarget(secret.name)}
              >
                <IconTrash className="w-4 h-4" />
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Quick add buttons */}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" color="primary" variant="flat" onPress={() => openAddModal()}>
          + Add Secret
        </Button>
        {unusedSuggestions.slice(0, 6).map((s) => (
          <Tooltip key={s.name} content={s.description}>
            <Button size="sm" variant="bordered" onPress={() => openAddModal(s)}>
              + {s.label}
            </Button>
          </Tooltip>
        ))}
      </div>

      {/* Add/Edit Modal */}
      <Modal isOpen={isOpen} onOpenChange={onOpenChange}>
        <ModalContent>
          {(onClose) => (
            <>
              <ModalHeader>{isEditing ? "Edit Secret" : "Add Secret"}</ModalHeader>
              <ModalBody className="gap-4">
                <Input
                  label="Name"
                  value={editName}
                  onValueChange={setEditName}
                  placeholder="github/token"
                  description="Use forward slashes to organize (e.g., github/token)"
                  isReadOnly={isEditing}
                  variant="bordered"
                />
                <Input
                  label="Value"
                  type={showValue ? "text" : "password"}
                  value={editValue}
                  onValueChange={setEditValue}
                  placeholder="Enter API key or token"
                  variant="bordered"
                  endContent={
                    <Button size="sm" variant="light" isIconOnly onPress={() => setShowValue(!showValue)}>
                      {showValue ? <IconEyeOff className="w-4 h-4" /> : <IconEye className="w-4 h-4" />}
                    </Button>
                  }
                />
                <Input
                  label="Description (optional)"
                  value={editDescription}
                  onValueChange={setEditDescription}
                  placeholder="What is this secret used for?"
                  variant="bordered"
                />
              </ModalBody>
              <ModalFooter>
                <Button variant="flat" onPress={onClose}>Cancel</Button>
                <Button
                  color="primary"
                  isLoading={upsertMutation.isPending}
                  isDisabled={!editName.trim() || !editValue.trim()}
                  onPress={async () => {
                    await upsertMutation.mutateAsync({
                      name: editName.trim(),
                      value: editValue.trim(),
                      description: editDescription.trim() || null
                    });
                    onClose();
                  }}
                >
                  Save
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>

      {/* Delete Modal */}
      <Modal isOpen={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <ModalContent>
          {() => (
            <>
              <ModalHeader>Delete Secret</ModalHeader>
              <ModalBody>
                <p>Are you sure you want to delete <strong className="font-mono">{deleteTarget}</strong>?</p>
                <p className="text-sm text-foreground/60">
                  This will remove it from your OS keychain. Recipes that reference this secret will fail.
                </p>
              </ModalBody>
              <ModalFooter>
                <Button variant="flat" onPress={() => setDeleteTarget(null)}>Cancel</Button>
                <Button
                  color="danger"
                  isLoading={deleteMutation.isPending}
                  onPress={async () => {
                    if (deleteTarget) {
                      await deleteMutation.mutateAsync(deleteTarget);
                      setDeleteTarget(null);
                    }
                  }}
                >
                  Delete
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
    </div>
  );
}
