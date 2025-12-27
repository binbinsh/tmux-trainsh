import {
  Card,
  CardBody,
  CardHeader,
  Divider,
  Input,
  Spinner,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
  Textarea
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { getConfig, sshPublicKey, termOpenSshTmux } from "../lib/tauri-api";
import type { SshSpec, TrainshConfig } from "../lib/types";

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

  // Colab sessions
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
    <div className="h-full p-6 overflow-auto">
      <div className="max-w-7xl mx-auto space-y-6">
        <Card>
          <CardHeader className="flex items-start justify-between gap-4">
            <div>
              <div className="text-lg font-semibold">Colab sessions</div>
              <div className="text-sm text-foreground/70">
                用 cloudflared + SSH 把 Colab 当作“远端机”（可在 Terminal 里直接 attach tmux）。
              </div>
            </div>
            <div className="text-xs text-foreground/60">
              SSH key: <span className="font-mono">{sshKeyPath ?? "(not set)"}</span>
            </div>
          </CardHeader>
          <Divider />
          <CardBody className="gap-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
              <Input label="Title" value={newTitle} onValueChange={setNewTitle} placeholder="colab" />
              <Input
                label="Hostname"
                value={newHostname}
                onValueChange={setNewHostname}
                placeholder="colab-ssh.example.com"
                description="Cloudflare Tunnel 的 SSH hostname"
              />
              <Input label="User" value={newUser} onValueChange={setNewUser} placeholder="root" />
              <Input label="tmux session" value={newTmux} onValueChange={setNewTmux} placeholder="doppio" />
              <Input
                label="cloudflared path"
                value={newCloudflared}
                onValueChange={setNewCloudflared}
                placeholder="/opt/homebrew/bin/cloudflared"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                color="primary"
                variant="flat"
                onPress={() => {
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
              {sessError ? <div className="text-sm text-danger">{sessError}</div> : null}
            </div>

            <Table removeWrapper aria-label="Colab sessions table">
              <TableHeader>
                <TableColumn>Title</TableColumn>
                <TableColumn>Hostname</TableColumn>
                <TableColumn>tmux</TableColumn>
                <TableColumn>Actions</TableColumn>
              </TableHeader>
              <TableBody emptyContent="No sessions">
                {sessions.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="text-sm">{s.title}</TableCell>
                    <TableCell className="font-mono text-xs">{s.hostname}</TableCell>
                    <TableCell className="font-mono text-xs">{s.tmux_session}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          color="primary"
                          variant="flat"
                          isDisabled={!sshKeyPath}
                          isLoading={openingId === s.id}
                          onPress={async () => {
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
                          }}
                        >
                          Open in Terminal
                        </Button>
                        <Button
                          size="sm"
                          variant="flat"
                          onPress={async () => {
                            const snippet = [
                              `Host ${s.hostname}`,
                              `  User ${s.user}`,
                              `  ProxyCommand ${s.cloudflared_path} access ssh --hostname %h`
                            ].join("\n");
                            await navigator.clipboard.writeText(snippet);
                          }}
                        >
                          Copy ssh config
                        </Button>
                        <Button
                          size="sm"
                          color="danger"
                          variant="flat"
                          onPress={() => setSessions((prev) => prev.filter((x) => x.id !== s.id))}
                        >
                          Remove
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            <div className="text-xs text-foreground/60">
              Setup manual 在本页下方（包含 sshd + cloudflared + 本地 ProxyCommand）。
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader className="flex items-start justify-between gap-4">
            <div>
              <div className="text-lg font-semibold">Setup manual (cloudflared SSH)</div>
              <div className="text-sm text-foreground/70">
                目标：让 Colab 暴露一个 SSH 服务（sshd:2222），通过 Cloudflare Tunnel + Access 从本地连接。
              </div>
            </div>
            <Button
              variant="flat"
              isDisabled={!sshKeyPath || manualLoadingKey}
              isLoading={manualLoadingKey}
              onPress={async () => {
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
              Load public key from Settings
            </Button>
          </CardHeader>
          <Divider />
          <CardBody className="gap-4">
            {manualError ? <div className="text-sm text-danger">Manual error: {manualError}</div> : null}

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <Input
                label="SSH public key (authorized_keys)"
                value={manualPubKey}
                onValueChange={setManualPubKey}
                placeholder="ssh-ed25519 AAAA... user@host"
              />
              <Input
                label="Cloudflared tunnel token (optional, not stored)"
                type="password"
                value={manualToken}
                onValueChange={setManualToken}
                placeholder="PASTE_TUNNEL_TOKEN"
              />
            </div>

            <div className="text-sm text-foreground/70 grid gap-2">
              <div className="font-semibold">1) Cloudflare Dashboard（一次性）</div>
              <div className="text-xs">
                在 Cloudflare Zero Trust 创建 Tunnel，并添加 SSH route：Hostname 例如 <span className="font-mono">colab-ssh.example.com</span>，
                Service 选 SSH，URL 填 <span className="font-mono">localhost:2222</span>。参考：`https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/use-cases/ssh/ssh-cloudflared-authentication/`
              </div>
            </div>

            <div className="grid gap-2">
              <div className="text-sm font-semibold">2) Colab Notebook（每次会话）</div>
              <Textarea
                label="One cell (bash)"
                value={manualColabCell}
                minRows={12}
                classNames={{ input: "font-mono text-xs" }}
                readOnly
              />
              <div className="flex gap-2">
                <Button
                  variant="flat"
                  onPress={async () => {
                    await navigator.clipboard.writeText(manualColabCell);
                  }}
                >
                  Copy cell
                </Button>
              </div>
            </div>

            <div className="text-sm text-foreground/70 grid gap-2">
              <div className="font-semibold">3) 本地连接</div>
              <div className="text-xs">
                安装 <span className="font-mono">cloudflared</span>，并按 session 的 "Copy ssh config" 把 ProxyCommand 写入{" "}
                <span className="font-mono">~/.ssh/config</span>，然后 <span className="font-mono">ssh root@&lt;hostname&gt;</span>。
              </div>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}


