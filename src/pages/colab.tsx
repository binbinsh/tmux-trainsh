import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { copyText } from "@/lib/clipboard";
import { getConfig, sshPublicKey, termOpenSshTmux } from "@/lib/tauri-api";
import type { SshSpec } from "@/lib/types";
import { DataTable, ActionButton, type ColumnDef } from "@/components/shared/DataTable";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  Button,
  Input,
  Textarea,
  Separator,
  Badge,
  Label,
} from "@/components/ui";
import { cn } from "@/lib/utils";

type ColabSession = {
  id: string;
  title: string;
  hostname: string;
  user: string;
  tmux_session: string;
  cloudflared_path: string;
  created_at: string;
};

const SESSIONS_KEY = "doppio.colabSessions";

function safeUuid(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
}

function loadSessions(): ColabSession[] {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed as ColabSession[];
  } catch {
    return [];
  }
}

function saveSessions(sessions: ColabSession[]) {
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

export function ColabPage() {
  const cfgQuery = useQuery({
    queryKey: ["config"],
    queryFn: getConfig
  });

  const [sessions, setSessions] = useState<ColabSession[]>([]);
  const [newTitle, setNewTitle] = useState("colab");
  const [newHostname, setNewHostname] = useState("");
  const [newUser, setNewUser] = useState("root");
  const [newTmux, setNewTmux] = useState("doppio");
  const [newCloudflared, setNewCloudflared] = useState("/opt/homebrew/bin/cloudflared");
  const [sessError, setSessError] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);

  const [manualPubKey, setManualPubKey] = useState<string>("");
  const [manualToken, setManualToken] = useState<string>("");
  const [manualError, setManualError] = useState<string | null>(null);
  const [manualLoadingKey, setManualLoadingKey] = useState(false);

  useEffect(() => {
    const loaded = loadSessions();
    setSessions(loaded);
  }, []);

  useEffect(() => {
    saveSessions(sessions);
  }, [sessions]);

  const sshKeyPath = useMemo(() => cfgQuery.data?.vast.ssh_key_path ?? null, [cfgQuery.data]);

  const handleOpenTerminal = async (s: ColabSession) => {
    if (!sshKeyPath) return;
    setOpeningId(s.id);
    try {
      const proxy = `${s.cloudflared_path} access ssh --hostname ${s.hostname}`;
      const ssh: SshSpec = {
        host: s.hostname,
        port: 22,
        user: s.user,
        keyPath: sshKeyPath,
        extraArgs: ["-o", `ProxyCommand=${proxy}`]
      };
      await termOpenSshTmux({
        ssh,
        tmuxSession: s.tmux_session,
        title: `Colab · ${s.title}`,
        cols: 120,
        rows: 32
      });
    } finally {
      setOpeningId(null);
    }
  };

  const sessionColumns: ColumnDef<ColabSession>[] = useMemo(() => [
    {
      key: "title",
      header: "Title",
      render: (s) => <span className="text-sm">{s.title}</span>,
    },
    {
      key: "hostname",
      header: "Hostname",
      render: (s) => <span className="font-mono text-xs">{s.hostname}</span>,
    },
    {
      key: "tmux",
      header: "tmux",
      render: (s) => <span className="font-mono text-xs">{s.tmux_session}</span>,
    },
    {
      key: "actions",
      header: "",
      render: (s) => (
        <div className="flex flex-wrap gap-2">
          <ActionButton
            label="Open in Terminal"
            variant="default"
            disabled={!sshKeyPath}
            isLoading={openingId === s.id}
            onClick={() => void handleOpenTerminal(s)}
          />
          <ActionButton
            label="Copy SSH Config"
            variant="outline"
            onClick={async () => {
              const snippet = [
                `Host ${s.hostname}`,
                `  User ${s.user}`,
                `  ProxyCommand ${s.cloudflared_path} access ssh --hostname %h`
              ].join("\n");
              await copyText(snippet);
            }}
          />
          <ActionButton
            label="Remove"
            variant="destructive"
            onClick={() => setSessions((prev) => prev.filter((x) => x.id !== s.id))}
          />
        </div>
      ),
    },
  ], [sshKeyPath, openingId]);

  const manualColabCell = useMemo(() => {
    const pub = manualPubKey.trim() || "PASTE_YOUR_SSH_PUBLIC_KEY_HERE";
    const tok = manualToken.trim() || "PASTE_YOUR_CLOUDFLARED_TUNNEL_TOKEN_HERE";
    return `%%bash
set -euo pipefail

# 1) Install sshd + deps
apt-get update -qq
apt-get install -y -qq openssh-server curl
mkdir -p /var/run/sshd
ssh-keygen -A

# 2) authorized_keys (key-only login)
mkdir -p /root/.ssh
chmod 700 /root/.ssh
cat > /root/.ssh/authorized_keys <<'EOF'
${pub}
EOF
chmod 600 /root/.ssh/authorized_keys

# 3) sshd config (listen on 2222)
grep -q '^Port 2222$' /etc/ssh/sshd_config || echo 'Port 2222' >> /etc/ssh/sshd_config
grep -q '^PasswordAuthentication no$' /etc/ssh/sshd_config || echo 'PasswordAuthentication no' >> /etc/ssh/sshd_config
grep -q '^PermitRootLogin yes$' /etc/ssh/sshd_config || echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config

# 4) start sshd
/usr/sbin/sshd -p 2222
ss -tlnp | grep 2222 || true

# 5) install cloudflared binary
curl -fsSL -o /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /usr/local/bin/cloudflared
cloudflared --version

# 6) start tunnel (keep it running)
export CF_TUNNEL_TOKEN="${tok}"
nohup cloudflared tunnel --no-autoupdate run --token "$CF_TUNNEL_TOKEN" > /content/cloudflared.log 2>&1 &
sleep 1
tail -n 30 /content/cloudflared.log || true
`;
  }, [manualPubKey, manualToken]);

  return (
    <div className="doppio-page">
      <div className="doppio-page-content space-y-6">
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardTitle>Colab sessions</CardTitle>
              <CardDescription>
                用 cloudflared + SSH 把 Colab 当作"远端机"（可在 Terminal 里直接 attach tmux）。
              </CardDescription>
            </div>
            <div className="text-xs text-muted-foreground">
              SSH key: <span className="font-mono">{sshKeyPath ?? "(not set)"}</span>
            </div>
          </CardHeader>
          <Separator />
          <CardContent className="space-y-4 pt-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
              <div className="space-y-1">
                <Label htmlFor="colab-title" className="text-sm font-medium">Title</Label>
                <Input id="colab-title" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="colab" />
              </div>
              <div className="space-y-1">
                <Label htmlFor="colab-hostname" className="text-sm font-medium">Hostname</Label>
                <Input
                  id="colab-hostname"
                  value={newHostname}
                  onChange={(e) => setNewHostname(e.target.value)}
                  placeholder="colab-ssh.example.com"
                />
                <p className="text-xs text-muted-foreground">Cloudflare Tunnel 的 SSH hostname</p>
              </div>
              <div className="space-y-1">
                <Label htmlFor="colab-user" className="text-sm font-medium">User</Label>
                <Input id="colab-user" value={newUser} onChange={(e) => setNewUser(e.target.value)} placeholder="root" />
              </div>
              <div className="space-y-1">
                <Label htmlFor="colab-tmux" className="text-sm font-medium">tmux session</Label>
                <Input id="colab-tmux" value={newTmux} onChange={(e) => setNewTmux(e.target.value)} placeholder="doppio" />
              </div>
              <div className="space-y-1">
                <Label htmlFor="colab-cloudflared" className="text-sm font-medium">cloudflared path</Label>
                <Input
                  id="colab-cloudflared"
                  value={newCloudflared}
                  onChange={(e) => setNewCloudflared(e.target.value)}
                  placeholder="/opt/homebrew/bin/cloudflared"
                />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={() => {
                  setSessError(null);
                  if (!newHostname.trim()) {
                    setSessError("Hostname is required.");
                    return;
                  }
                  const s: ColabSession = {
                    id: safeUuid(),
                    title: newTitle.trim() || "colab",
                    hostname: newHostname.trim(),
                    user: newUser.trim() || "root",
                    tmux_session: newTmux.trim() || "doppio",
                    cloudflared_path: newCloudflared.trim() || "/opt/homebrew/bin/cloudflared",
                    created_at: new Date().toISOString()
                  };
                  setSessions((prev) => [s, ...prev]);
                }}
              >
                Add session
              </Button>
              {sessError ? <div className="text-sm text-destructive">{sessError}</div> : null}
            </div>

            <DataTable
              data={sessions}
              columns={sessionColumns}
              rowKey={(s) => s.id}
              emptyContent="No sessions"
              compact
            />

            <div className="text-xs text-muted-foreground">
              Setup manual 在本页下方（包含 sshd + cloudflared + 本地 ProxyCommand）。
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardTitle>Setup manual (cloudflared SSH)</CardTitle>
              <CardDescription>
                目标：让 Colab 暴露一个 SSH 服务（sshd:2222），通过 Cloudflare Tunnel + Access 从本地连接。
              </CardDescription>
            </div>
            <Button
              variant="outline"
              disabled={!sshKeyPath || manualLoadingKey}
              onClick={async () => {
                if (!sshKeyPath) return;
                setManualError(null);
                setManualLoadingKey(true);
                try {
                  const pk = await sshPublicKey(sshKeyPath);
                  setManualPubKey(pk);
                } catch (e) {
                  const msg = e instanceof Error ? e.message : String(e);
                  setManualError(msg);
                } finally {
                  setManualLoadingKey(false);
                }
              }}
            >
              {manualLoadingKey && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Load public key from Settings
            </Button>
          </CardHeader>
          <Separator />
          <CardContent className="space-y-4 pt-4">
            {manualError ? <div className="text-sm text-destructive">Manual error: {manualError}</div> : null}

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor="colab-ssh-pubkey" className="text-sm font-medium">SSH public key (authorized_keys)</Label>
                <Input
                  id="colab-ssh-pubkey"
                  value={manualPubKey}
                  onChange={(e) => setManualPubKey(e.target.value)}
                  placeholder="ssh-ed25519 AAAA... user@host"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="colab-tunnel-token" className="text-sm font-medium">Cloudflared tunnel token (optional, not stored)</Label>
                <Input
                  id="colab-tunnel-token"
                  type="password"
                  value={manualToken}
                  onChange={(e) => setManualToken(e.target.value)}
                  placeholder="PASTE_TUNNEL_TOKEN"
                />
              </div>
            </div>

            <div className="text-sm text-muted-foreground space-y-2">
              <div className="font-semibold">1) Cloudflare Dashboard（一次性）</div>
              <div className="text-xs">
                在 Cloudflare Zero Trust 创建 Tunnel，并添加 SSH route：Hostname 例如 <span className="font-mono">colab-ssh.example.com</span>，
                Service 选 SSH，URL 填 <span className="font-mono">localhost:2222</span>。参考：`https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/use-cases/ssh/ssh-cloudflared-authentication/`
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-sm font-semibold">2) Colab Notebook（每次会话）</div>
              <div className="space-y-1">
                <Label htmlFor="colab-one-cell" className="text-sm font-medium">One cell (bash)</Label>
                <Textarea
                  id="colab-one-cell"
                  value={manualColabCell}
                  readOnly
                  className="font-mono text-xs min-h-[300px]"
                />
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  onClick={async () => {
                    await copyText(manualColabCell);
                  }}
                >
                  Copy cell
                </Button>
              </div>
            </div>

            <div className="text-sm text-muted-foreground space-y-2">
              <div className="font-semibold">3) 本地连接</div>
              <div className="text-xs">
                安装 <span className="font-mono">cloudflared</span>，并按 session 的 "Copy ssh config" 把 ProxyCommand 写入{" "}
                <span className="font-mono">~/.ssh/config</span>，然后 <span className="font-mono">ssh root@&lt;hostname&gt;</span>。
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
