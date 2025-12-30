import {
  Card,
  CardBody,
  CardHeader,
  Input,
  Link,
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
  Tooltip,
  useDisclosure
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { AppIcon } from "../components/AppIcon";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { copyText } from "../lib/clipboard";
import { open } from "@tauri-apps/plugin-shell";
import {
  getConfig,
  pricingApi,
  saveConfig,
  secretsApi,
  sshKeyCandidates,
  sshSecretKeyCandidates,
  sshPrivateKey,
  sshPublicKey,
  useFetchExchangeRates,
  useColabPricingCalculation,
  usePricingSettings,
  useUpdateColabGpuPricing,
  useUpdateColabSubscription,
  useUpdateDisplayCurrency
} from "../lib/tauri-api";
import type { ColabGpuPricing, Currency, SecretMeta, SecretSuggestion, TrainshConfig } from "../lib/types";
import { CURRENCIES, formatPriceWithRates, getCurrencySymbol } from "../lib/currency";

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
  return <AppIcon name="vast" className={className} alt="Vast.ai" />;
}

function IconBeaker({ className }: { className?: string }) {
  return <AppIcon name="colab" className={className} alt="Google Colab" />;
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
// Section Card Component - Using unified doppio-card style
// ============================================================

type SectionIconType = "settings" | "server" | "beaker" | "key";

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
  const IconComponent = {
    settings: IconSettings,
    server: IconServer,
    beaker: IconBeaker,
    key: IconKey,
  }[icon];

  return (
    <div className="doppio-card">
      <div className="flex justify-between items-start gap-3 p-4 border-b border-divider">
        <div className="flex gap-3 items-center">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
            <IconComponent className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h3 className="text-base font-semibold">{title}</h3>
            {subtitle && <p className="text-xs text-foreground/50">{subtitle}</p>}
          </div>
        </div>
        {actions}
      </div>
      <div className="p-4">
        {children}
      </div>
    </div>
  );
}

// ============================================================
// Main Settings Page
// ============================================================

const SCAMALYTICS_SIGNUP_URL = "https://scamalytics.com/ip/api/enquiry?monthly_api_calls=5000";

export function SettingsPage() {
  const cfgQuery = useQuery({
    queryKey: ["config"],
    queryFn: getConfig
  });
  const sshKeysQuery = useQuery({
    queryKey: ["sshKeyCandidates"],
    queryFn: sshKeyCandidates
  });
  const sshSecretKeysQuery = useQuery({
    queryKey: ["sshSecretKeyCandidates"],
    queryFn: sshSecretKeyCandidates
  });
  const fetchRates = useFetchExchangeRates();

  const [draft, setDraft] = useState<TrainshConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [isColabDirty, setIsColabDirty] = useState(false);
  const colabSaveRef = useRef<null | (() => Promise<void>)>(null);

  const sshKeyOptions = useMemo(() => {
    const secrets = sshSecretKeysQuery.data ?? [];
    const files = sshKeysQuery.data ?? [];
    return [...secrets, ...files];
  }, [sshKeysQuery.data, sshSecretKeysQuery.data]);

  const handleOpenScamalyticsSignup = useCallback(async (event?: MouseEvent<HTMLAnchorElement>) => {
    event?.preventDefault();
    try {
      await open(SCAMALYTICS_SIGNUP_URL);
    } catch (err) {
      console.error("Failed to open Scamalytics registration:", err);
    }
  }, []);

  useEffect(() => {
    if (cfgQuery.data) {
      setDraft({
        ...cfgQuery.data,
        vast: {
          ...cfgQuery.data.vast,
          ssh_user: cfgQuery.data.vast.ssh_user.trim() || "root",
          ssh_connection_preference: cfgQuery.data.vast.ssh_connection_preference ?? "proxy",
        },
        scamalytics: {
          ...cfgQuery.data.scamalytics,
          user: cfgQuery.data.scamalytics.user?.trim() || null,
          api_key: cfgQuery.data.scamalytics.api_key?.trim() || null,
          host: cfgQuery.data.scamalytics.host.trim() || "https://api11.scamalytics.com/v3/",
        }
      });
    }
  }, [cfgQuery.data]);

  const isDirty = useMemo(() => {
    if (!draft || !cfgQuery.data) return false;
    return JSON.stringify(draft) !== JSON.stringify(cfgQuery.data) || isColabDirty;
  }, [draft, cfgQuery.data, isColabDirty]);

  async function onSave() {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    try {
      const normalized: TrainshConfig = {
        ...draft,
        vast: {
          ...draft.vast,
          ssh_user: draft.vast.ssh_user.trim() || "root",
          ssh_key_path: draft.vast.ssh_key_path?.trim() || null,
          ssh_connection_preference: draft.vast.ssh_connection_preference === "direct" ? "direct" : "proxy",
        },
        scamalytics: {
          ...draft.scamalytics,
          user: draft.scamalytics.user?.trim() || null,
          api_key: draft.scamalytics.api_key?.trim() || null,
          host: draft.scamalytics.host.trim() || "https://api11.scamalytics.com/v3/",
        }
      };
      setDraft(normalized);
      await saveConfig(normalized);
      if (colabSaveRef.current) {
        await colabSaveRef.current();
      }
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
    <div className="doppio-page">
      <div className="doppio-page-content">
        {/* Header */}
        <div className="doppio-page-header">
          <div>
            <h1 className="doppio-page-title">Settings</h1>
            <p className="doppio-page-subtitle">Configuration saved locally</p>
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
              onPress={() => fetchRates.mutate()}
              isLoading={fetchRates.isPending}
            >
              Refresh Rates
            </Button>
            <Button
              size="sm"
              color="primary"
              isLoading={saving}
              isDisabled={!draft || saving || !isDirty}
              onPress={onSave}
            >
              Save
            </Button>
          </div>
        </div>

        <div className="space-y-6">

        <SectionCard icon="settings" title="General" subtitle="Default paths, preferences, and currency">
          <div className="space-y-4">
            <Input labelPlacement="inside" label="HuggingFace Cache (HF_HOME)"
            value={draft.colab.hf_home ?? ""}
            onValueChange={(v) =>
              setDraft({ ...draft, colab: { ...draft.colab, hf_home: v.trim() ? v : null } })
            }
            placeholder="~/.cache/huggingface"
            description="HF_HOME"
            size="sm"
            variant="flat"
            classNames={{ inputWrapper: "bg-content2" }} />
            <DisplayCurrencySection />
          </div>
        </SectionCard>

        <SectionCard icon="server" title="Vast.ai" subtitle="API key, SSH settings, and pricing rates">
          <div className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Input labelPlacement="inside" label="API Key"
                  type="password"
                  value={draft.vast.api_key ?? ""}
                  onValueChange={(v) =>
                                    setDraft({ ...draft, vast: { ...draft.vast, api_key: v.trim() ? v : null } })
                  }
                                  description="API key"
                  size="sm"
                                  variant="flat"
                                  classNames={{ inputWrapper: "bg-content2" }} />
                  <Input labelPlacement="inside" label="Console URL"
                  value={draft.vast.url}
                  onValueChange={(v) =>
                                    setDraft({ ...draft, vast: { ...draft.vast, url: v } })
                  }
                  size="sm"
                                  variant="flat"
                                  classNames={{ inputWrapper: "bg-content2" }} />
                </div>

            <VastPricingSection />
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Input labelPlacement="inside" label="SSH User"
              value={draft.vast.ssh_user}
              onValueChange={(v) =>
              setDraft({ ...draft, vast: { ...draft.vast, ssh_user: v || "root" } })
              }
              placeholder="root"
              size="sm"
                                variant="flat"
                                classNames={{ inputWrapper: "bg-content2" }} />
              <Select
                labelPlacement="inside"
                label="SSH Connection"
                selectedKeys={[draft.vast.ssh_connection_preference ?? "proxy"]}
                onSelectionChange={(keys) => {
                  const selected = (Array.from(keys)[0] as string | undefined) ?? "proxy";
                  setDraft({
                    ...draft,
                    vast: { ...draft.vast, ssh_connection_preference: selected === "direct" ? "direct" : "proxy" }
                  });
                }}
                size="sm"
                variant="flat"
                classNames={{ trigger: "bg-content2" }}
              >
                <SelectItem key="proxy" textValue="Proxy">
                  Proxy (sshX.vast.ai)
                </SelectItem>
                <SelectItem key="direct" textValue="Direct">
                  Direct (public IP + direct port)
                </SelectItem>
              </Select>
              <Select
                labelPlacement="inside"
                label="SSH Key"
                selectedKeys={draft.vast.ssh_key_path ? [draft.vast.ssh_key_path] : []}
                onSelectionChange={(keys) => {
                  const selected = Array.from(keys)[0] as string | undefined;
                  setDraft({
                    ...draft,
                    vast: { ...draft.vast, ssh_key_path: selected?.trim() ? selected : null }
                  });
                }}
                size="sm"
                variant="flat"
                classNames={{ trigger: "bg-content2" }}
                isDisabled={
                  (sshKeysQuery.isLoading || sshSecretKeysQuery.isLoading)
                    ? false
                    : sshKeyOptions.length === 0
                }
                placeholder={
                  sshKeysQuery.isLoading || sshSecretKeysQuery.isLoading
                    ? "Loading..."
                    : "Select a key (secret or ~/.ssh)"
                }
              >
                {sshKeyOptions.map((value) => {
                  const isSecret = value.startsWith("${secret:") && value.endsWith("}");
                  const label = isSecret ? value.slice("${secret:".length, -1) : (value.split("/").slice(-1)[0] ?? value);
                  return (
                    <SelectItem key={value} textValue={label}>
                      <span className="font-mono text-sm">{label}</span>
                      <span className="text-foreground/50 text-xs ml-2">
                        {isSecret ? "secret" : value}
                      </span>
                    </SelectItem>
                  );
                })}
              </Select>
            </div>
              </div>
        </SectionCard>

        <SectionCard icon="key" title="Scamalytics" subtitle="IP risk intelligence credentials">
          <div className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Input
                labelPlacement="inside"
                label="User"
                value={draft.scamalytics.user ?? ""}
                onValueChange={(v) =>
                  setDraft({ ...draft, scamalytics: { ...draft.scamalytics, user: v.trim() ? v : null } })
                }
                description="Account ID"
                size="sm"
                variant="flat"
                classNames={{ inputWrapper: "bg-content2" }}
              />
              <Input
                labelPlacement="inside"
                label="API Key"
                type="password"
                value={draft.scamalytics.api_key ?? ""}
                onValueChange={(v) =>
                  setDraft({ ...draft, scamalytics: { ...draft.scamalytics, api_key: v.trim() ? v : null } })
                }
                description="API key"
                size="sm"
                variant="flat"
                classNames={{ inputWrapper: "bg-content2" }}
              />
            </div>
            <p className="text-xs text-foreground/60">
              Need an API key?{" "}
              <Link
                href={SCAMALYTICS_SIGNUP_URL}
                target="_blank"
                rel="noopener noreferrer"
                color="primary"
                size="sm"
                onClick={handleOpenScamalyticsSignup}
              >
                Register for a Scamalytics API key
              </Link>
            </p>
          </div>
        </SectionCard>

        <SectionCard icon="beaker" title="Google Colab" subtitle="Subscription pricing and GPU compute unit rates">
                <ColabPricingSection
                  onDirtyChange={setIsColabDirty}
                  registerSave={(saveFn) => {
                    colabSaveRef.current = saveFn;
                  }}
                />
        </SectionCard>

        <SectionCard icon="key" title="Secrets" subtitle="SSH keys and tokens stored securely, Use {secret:name} syntax in recipes.">
          <div className="space-y-6">
            <SecretsSection />
          </div>
        </SectionCard>
        </div>

      </div>
    </div>
  );
}

// ============================================================
// Display Currency Section
// ============================================================

function DisplayCurrencySection() {
  const pricingQuery = usePricingSettings();
  const updateDisplayCurrency = useUpdateDisplayCurrency();

  if (pricingQuery.isLoading) {
    return <Spinner size="sm" />;
  }

  if (!pricingQuery.data) {
    return null;
  }

  const displayCurrency = pricingQuery.data.display_currency ?? "USD";
  const updatedAt = pricingQuery.data.exchange_rates.updated_at;

  return (
    <div className="space-y-3">
      <Select labelPlacement="inside" label="Default Currency"
      selectedKeys={[displayCurrency]}
      onSelectionChange={async (keys) => {
        const selected = Array.from(keys)[0] as Currency;
        if (!selected || selected === displayCurrency) return;
        await updateDisplayCurrency.mutateAsync(selected);
      }}
      size="sm"
      variant="flat"
      classNames={{ trigger: "bg-content2" }}>{CURRENCIES.map((c) => (
        <SelectItem key={c.value} textValue={`${c.symbol} ${c.label}`}>
          {c.symbol} {c.label}
        </SelectItem>
      ))}</Select>
      <p className="text-xs text-foreground/50">
        Exchange rates updated: {new Date(updatedAt).toLocaleString()}
      </p>
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

  const displayCurrency = settings.display_currency ?? "USD";
  const exchangeRates = settings.exchange_rates;
  const formatRate = (value: number, decimals = 4) =>
    formatPriceWithRates(value, "USD", displayCurrency, exchangeRates, decimals);

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="flex justify-between items-center p-3 bg-content2 rounded-lg">
          <span className="text-sm text-foreground/60">Storage</span>
          <span className="font-mono text-sm">{formatRate(settings.vast_rates.storage_per_gb_month)}/GB/mo</span>
        </div>
        <div className="flex justify-between items-center p-3 bg-content2 rounded-lg">
          <span className="text-sm text-foreground/60">Egress</span>
          <span className="font-mono text-sm">{formatRate(settings.vast_rates.network_egress_per_gb)}/GB</span>
        </div>
        <div className="flex justify-between items-center p-3 bg-content2 rounded-lg">
          <span className="text-sm text-foreground/60">Ingress</span>
          <span className="font-mono text-sm">{formatRate(settings.vast_rates.network_ingress_per_gb)}/GB</span>
        </div>
      </div>
      <p className="text-xs text-foreground/40">
        Default pricing rates apply to storage/egress/ingress. GPU hourly rates are fetched from Vast.ai API per
        instance.
      </p>
    </div>
  );
}

// ============================================================
// Colab Pricing Section (Subscription + GPU Pricing together)
// ============================================================

type ColabPricingSectionProps = {
  onDirtyChange?: (dirty: boolean) => void;
  registerSave?: (saveFn: () => Promise<void>) => void;
};

function ColabPricingSection({ onDirtyChange, registerSave }: ColabPricingSectionProps) {
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
  const displayCurrency = pricingQuery.data?.display_currency ?? "USD";
  const exchangeRates = pricingQuery.data?.exchange_rates;
  const formatUsd = (value: number, decimals = 4) =>
    formatPriceWithRates(value, "USD", displayCurrency, exchangeRates, decimals);

  const initialSubscription = pricingQuery.data?.colab.subscription;
  const initialGpuPricing = pricingQuery.data?.colab.gpu_pricing ?? [];

  const isSubscriptionDirty = useMemo(() => {
    if (!initialSubscription) return false;
    const price = Number(subPrice);
    const units = Number(subUnits);
    return (
      subName !== initialSubscription.name ||
      subCurrency !== initialSubscription.currency ||
      price !== initialSubscription.price ||
      units !== initialSubscription.total_units
    );
  }, [initialSubscription, subCurrency, subName, subPrice, subUnits]);

  const isGpuPricingDirty = useMemo(() => {
    if (!pricingQuery.data) return false;
    if (gpuList.length !== initialGpuPricing.length) return true;
    return gpuList.some((gpu, idx) => {
      const original = initialGpuPricing[idx];
      if (!original) return true;
      return (
        gpu.gpu_name !== original.gpu_name ||
        gpu.units_per_hour !== original.units_per_hour
      );
    });
  }, [gpuList, initialGpuPricing, pricingQuery.data]);

  const saveAll = useCallback(async () => {
    if (!pricingQuery.data) return;
    if (isSubscriptionDirty) {
      await handleSaveSubscription();
    }
    if (isGpuPricingDirty) {
      await handleSaveGpuPricing();
    }
  }, [handleSaveSubscription, handleSaveGpuPricing, isSubscriptionDirty, isGpuPricingDirty, pricingQuery.data]);

  useEffect(() => {
    onDirtyChange?.(isSubscriptionDirty || isGpuPricingDirty);
  }, [isSubscriptionDirty, isGpuPricingDirty, onDirtyChange]);

  useEffect(() => {
    registerSave?.(saveAll);
  }, [registerSave, saveAll]);

  if (pricingQuery.isLoading) {
    return <Spinner size="lg" className="mx-auto" />;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Input labelPlacement="inside" label="Plan Name"
          value={subName}
          onValueChange={setSubName}
          placeholder="Colab Pro"
          size="sm"
          variant="flat"
          classNames={{ inputWrapper: "bg-content2" }} />
          <Input labelPlacement="inside" label="Price"
          type="number"
          value={subPrice}
          onValueChange={setSubPrice}
          placeholder="11.99"
          startContent={<span className="text-foreground/50 text-xs">{getCurrencySymbol(subCurrency)}</span>}
          size="sm"
          variant="flat"
          classNames={{ inputWrapper: "bg-content2" }} />
          <Select labelPlacement="inside" label="Currency"
          selectedKeys={[subCurrency]}
          onSelectionChange={(keys) => {
            const selected = Array.from(keys)[0] as Currency;
            if (selected) setSubCurrency(selected);
          }}
          size="sm"
          variant="flat"
          classNames={{ trigger: "bg-content2" }}>{CURRENCIES.map((c) => (
            <SelectItem key={c.value} textValue={`${c.symbol} ${c.label}`}>
              {c.symbol} {c.label}
            </SelectItem>
          ))}</Select>
          <Input labelPlacement="inside" label="Compute Units"
          type="number"
          value={subUnits}
          onValueChange={setSubUnits}
          placeholder="100"
          size="sm"
          variant="flat"
          classNames={{ inputWrapper: "bg-content2" }} />
        </div>

        {calculation && (
          <div className="flex justify-between items-center p-3 bg-success/10 rounded-lg">
            <span className="text-sm text-foreground/70">Price per compute unit</span>
            <span className="font-mono font-semibold text-success">
              {formatUsd(calculation.price_per_unit_usd)}
            </span>
          </div>
        )}
      </div>

      <div className="space-y-4">
        <Table removeWrapper aria-label="GPU pricing" classNames={{ base: "max-h-[280px] overflow-auto" }}>
          <TableHeader>
            <TableColumn>GPU</TableColumn>
            <TableColumn width={90}>Units/Hr</TableColumn>
            <TableColumn width={100}>Units/24Hr</TableColumn>
            <TableColumn width={85}>{displayCurrency}/Hr</TableColumn>
            <TableColumn width={95}>{displayCurrency}/24Hr</TableColumn>
            <TableColumn width={40}> </TableColumn>
          </TableHeader>
          <TableBody emptyContent="No GPUs configured">
            {gpuList.map((gpu, idx) => {
              const calcGpu = calculation?.gpu_prices.find((g) => g.gpu_name === gpu.gpu_name);
              return (
                <TableRow key={idx}>
                  <TableCell>
                    <Input labelPlacement="inside" value={gpu.gpu_name}
                    onValueChange={(v) => {
                      if (v.trim()) {
                        setGpuList((prev) => prev.map((g, i) => (i === idx ? { ...g, gpu_name: v } : g)));
                      }
                    }}
                    size="sm"
                    variant="underlined"
                    classNames={{ input: "font-semibold", inputWrapper: "h-8" }} />
                  </TableCell>
                  <TableCell>
                    <Input labelPlacement="inside" type="number"
                    value={gpu.units_per_hour.toString()}
                    onValueChange={(v) => {
                      const val = parseFloat(v);
                      if (!isNaN(val) && val > 0) {
                        setGpuList((prev) => prev.map((g, i) => (i === idx ? { ...g, units_per_hour: val } : g)));
                      }
                    }}
                    size="sm"
                    variant="underlined"
                    classNames={{ input: "text-center w-14", inputWrapper: "h-8" }} />
                  </TableCell>
                  <TableCell className="font-mono text-foreground/60">
                    {(gpu.units_per_hour * 24).toFixed(1)}
                  </TableCell>
                  <TableCell className="font-mono text-success">
                    {calcGpu ? formatUsd(calcGpu.price_usd_per_hour) : "-"}
                  </TableCell>
                  <TableCell className="font-mono text-warning">
                    {calcGpu ? formatUsd(calcGpu.price_usd_per_hour * 24, 2) : "-"}
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

        <div className="flex items-end gap-3">
          <Input labelPlacement="inside" label="New GPU"
          value={newGpuName}
          onValueChange={setNewGpuName}
          placeholder="e.g., A100"
          size="sm"
          variant="flat"
          classNames={{ inputWrapper: "bg-content2", base: "flex-1" }} />
          <Input labelPlacement="inside" label="Units/Hr"
          type="number"
          value={newGpuUnits}
          onValueChange={setNewGpuUnits}
          placeholder="12.29"
          size="sm"
          variant="flat"
          classNames={{ inputWrapper: "bg-content2", base: "w-28" }} />
          <Button
            color="primary"
            variant="flat"
            size="sm"
            className="h-12 min-h-12"
            onPress={handleAddGpu}
            isDisabled={!newGpuName.trim() || !newGpuUnits.trim()}
          >
            Add
          </Button>
        </div>

        {calculation && (
          <p className="text-xs text-foreground/40">
            Based on {calculation.subscription.name} at{" "}
            {formatPriceWithRates(
              calculation.subscription.price,
              calculation.subscription.currency,
              displayCurrency,
              exchangeRates,
              2
            )}{" "}
            for{" "}
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

  const keysQuery = useQuery({
    queryKey: ["sshKeyCandidates"],
    queryFn: sshKeyCandidates
  });
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
  const [sshKeyError, setSshKeyError] = useState<string | null>(null);
  const [sshKeyAction, setSshKeyAction] = useState<{ path: string; kind: "public" | "private" } | null>(null);
  const [copyNotice, setCopyNotice] = useState<string | null>(null);
  const copyNoticeTimer = useRef<number | null>(null);

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
  const keyPaths = keysQuery.data || [];
  const showEmptyState = !keysQuery.isLoading && keyPaths.length === 0 && secrets.length === 0;

  const handleCopyKey = async (path: string, kind: "public" | "private") => {
    setSshKeyError(null);
    setSshKeyAction({ path, kind });
    try {
      const key = kind === "public" ? await sshPublicKey(path) : await sshPrivateKey(path);
      await copyText(key);
      const id = `ssh:${kind}:${path}`;
      if (copyNoticeTimer.current) {
        window.clearTimeout(copyNoticeTimer.current);
      }
      setCopyNotice(id);
      copyNoticeTimer.current = window.setTimeout(() => setCopyNotice(null), 1200);
    } catch (e) {
      setSshKeyError(e instanceof Error ? e.message : String(e));
    } finally {
      setSshKeyAction(null);
    }
  };

  useEffect(() => {
    return () => {
      if (copyNoticeTimer.current) {
        window.clearTimeout(copyNoticeTimer.current);
      }
    };
  }, []);

  if (secretsQuery.isLoading) {
    return <Spinner size="lg" className="mx-auto" />;
  }

  return (
    <div className="space-y-4">
      {showEmptyState ? (
        <div className="text-sm text-foreground/50 py-4 text-center">No secrets configured</div>
      ) : (
        <div className="space-y-2">
          {keysQuery.isLoading ? (
            <div className="flex items-center justify-center p-3 bg-content2 rounded-lg">
              <Spinner size="sm" />
            </div>
          ) : (
            keyPaths.map((path) => {
              const filename = path.split("/").slice(-1)[0] ?? path;
              const isPublicLoading =
                sshKeyAction?.path === path && sshKeyAction?.kind === "public";
              const isPrivateLoading =
                sshKeyAction?.path === path && sshKeyAction?.kind === "private";
              return (
                <div key={path} className="flex items-center gap-2 p-3 bg-content2 rounded-lg">
                  <div className="flex-1 min-w-0">
                    <div className="font-mono text-sm truncate">ssh/{filename}</div>
                    <div className="text-xs text-foreground/50 truncate">{path}</div>
                  </div>
                  <div className="flex items-center gap-1">
                    <Tooltip
                      content={
                        copyNotice === `ssh:private:${path}` ? "Copied" : "Copy private key"
                      }
                      isOpen={copyNotice === `ssh:private:${path}` ? true : undefined}
                    >
                      <Button
                        size="sm"
                        variant="light"
                        isIconOnly
                        isDisabled={sshKeyAction !== null}
                        isLoading={isPrivateLoading}
                        onPress={() => handleCopyKey(path, "private")}
                      >
                        <IconCopy className="w-4 h-4" />
                      </Button>
                    </Tooltip>
                    <Tooltip
                      content={
                        copyNotice === `ssh:public:${path}` ? "Copied" : "Copy public key"
                      }
                      isOpen={copyNotice === `ssh:public:${path}` ? true : undefined}
                    >
                      <Button
                        size="sm"
                        variant="light"
                        isIconOnly
                        isDisabled={sshKeyAction !== null}
                        isLoading={isPublicLoading}
                        onPress={() => handleCopyKey(path, "public")}
                      >
                        <IconCopy className="w-4 h-4" />
                      </Button>
                    </Tooltip>
                  </div>
                </div>
              );
            })
          )}
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
              <Tooltip
                content={
                  copyNotice === `secret:${secret.name}` ? "Copied" : "Copy reference"
                }
                isOpen={copyNotice === `secret:${secret.name}` ? true : undefined}
              >
                <Button
                  size="sm"
                  variant="light"
                  isIconOnly
                  onPress={async () => {
                    await copyText(`\${secret:${secret.name}}`);
                    const id = `secret:${secret.name}`;
                    if (copyNoticeTimer.current) {
                      window.clearTimeout(copyNoticeTimer.current);
                    }
                    setCopyNotice(id);
                    copyNoticeTimer.current = window.setTimeout(() => setCopyNotice(null), 1200);
                  }}
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

      {sshKeyError && <div className="text-xs text-danger">{sshKeyError}</div>}

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

      <Modal isOpen={isOpen} onOpenChange={onOpenChange}>
        <ModalContent>
          {(onClose) => (
            <>
              <ModalHeader>{isEditing ? "Edit Secret" : "Add Secret"}</ModalHeader>
              <ModalBody className="gap-4">
                <Input labelPlacement="inside" label="Name"
                value={editName}
                onValueChange={setEditName}
                placeholder="github/token"
                description="Use slashes"
                isReadOnly={isEditing}
                variant="bordered" />
                <Input labelPlacement="inside" label="Value"
                type={showValue ? "text" : "password"}
                value={editValue}
                onValueChange={setEditValue}
                placeholder="Enter API key or token"
                variant="bordered"
                endContent={
                  <Button size="sm" variant="light" isIconOnly onPress={() => setShowValue(!showValue)}>
                    {showValue ? <IconEyeOff className="w-4 h-4" /> : <IconEye className="w-4 h-4" />}
                  </Button>
                } />
                <Input labelPlacement="inside" label="Description (optional)"
                value={editDescription}
                onValueChange={setEditDescription}
                placeholder="What is this secret used for?"
                variant="bordered" />
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
