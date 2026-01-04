import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import {
  downloadRemoteDir,
  getConfig,
  jobFetchGpu,
  jobGetExitCode,
  jobTailLogs,
  vastAttachSshKey,
  vastDestroyInstance,
  vastListInstances,
  vastRunJob
} from "@/lib/tauri-api";
import type { RunVastJobInput } from "@/lib/tauri-api";
import type { GpuRow, RemoteJobMeta, VastInstance } from "@/lib/types";
import { DataTable, type ColumnDef } from "@/components/shared/DataTable";
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
  Switch,
  Label,
  Badge,
} from "@/components/ui";

export function JobPage() {
  const cfgQuery = useQuery({
    queryKey: ["config"],
    queryFn: getConfig
  });
  const instQuery = useQuery({
    queryKey: ["vastInstances"],
    queryFn: vastListInstances,
    refetchInterval: 30_000,
    staleTime: 20_000,
    retry: 1,
  });

  // Job spec (Vast)
  const [projectDir, setProjectDir] = useState("");
  const [command, setCommand] = useState("");
  const [workdir, setWorkdir] = useState<string>("");
  const [outputDir, setOutputDir] = useState<string>(""); // remote_output_dir or model_output_dir
  const [hfHome, setHfHome] = useState<string>("");
  const [includeData, setIncludeData] = useState(false);
  const [includeModels, setIncludeModels] = useState(false);
  const [includeDotenv, setIncludeDotenv] = useState(false);
  const [extraExcludes, setExtraExcludes] = useState<string>("");

  const [instanceId, setInstanceId] = useState<string>("");
  const [sync, setSync] = useState(true);

  const [meta, setMeta] = useState<RemoteJobMeta | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const [localDownloadDir, setLocalDownloadDir] = useState<string>("");
  const [autoDownload, setAutoDownload] = useState(true);
  const [autoDestroy, setAutoDestroy] = useState(true);
  const [autoStatus, setAutoStatus] = useState<string | null>(null);
  const autoTriggeredRef = useRef(false);

  const runMut = useMutation({
    mutationFn: (input: RunVastJobInput) => vastRunJob(input)
  });

  const selectedInstance = useMemo(() => {
    const id = Number(instanceId);
    if (!Number.isFinite(id)) return null;
    return (instQuery.data ?? []).find((x) => x.id === id) ?? null;
  }, [instanceId, instQuery.data]);

  const effectiveHfHome = useMemo(() => {
    if (hfHome.trim()) return hfHome.trim();
    return cfgQuery.data?.colab.hf_home ?? "";
  }, [hfHome, cfgQuery.data]);

  const exitQuery = useQuery({
    queryKey: ["jobExitCode", meta?.remote.job_dir ?? null],
    queryFn: async () => {
      if (!meta) return null;
      return await jobGetExitCode({ ssh: meta.ssh, jobDir: meta.remote.job_dir });
    },
    enabled: !!meta,
    refetchInterval: meta ? 3_000 : false
  });

  const logsQuery = useQuery({
    queryKey: ["jobLogs", meta?.remote.log_path ?? null],
    queryFn: async () => {
      if (!meta) return [];
      return await jobTailLogs({ ssh: meta.ssh, logPath: meta.remote.log_path, lines: 200 });
    },
    enabled: !!meta,
    refetchInterval: meta && exitQuery.data == null ? 2_000 : false
  });

  const gpuQuery = useQuery({
    queryKey: ["jobGpu", meta?.ssh.host ?? null, meta?.ssh.port ?? null],
    queryFn: async () => {
      if (!meta) return [];
      return await jobFetchGpu({ ssh: meta.ssh });
    },
    enabled: !!meta,
    refetchInterval: meta && exitQuery.data == null ? 5_000 : false
  });

  useEffect(() => {
    if (!meta) return;
    const exit = exitQuery.data;
    if (exit == null) return;
    if (autoTriggeredRef.current) return;
    autoTriggeredRef.current = true;

    (async () => {
      try {
        if (autoDownload) {
          const remoteDir = meta.remote.output_dir;
          if (!remoteDir) throw new Error("remote.output_dir is null");
          const localDir = localDownloadDir.trim();
          if (!localDir) throw new Error("local download dir is empty");
          setAutoStatus("Downloading outputs…");
          await downloadRemoteDir({ ssh: meta.ssh, remoteDir: remoteDir, localDir: localDir, delete: false });
        }
        if (autoDestroy) {
          const id = Number(instanceId);
          if (Number.isFinite(id)) {
            setAutoStatus("Destroying instance…");
            await vastDestroyInstance(id);
          }
        }
        setAutoStatus("Done");
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setAutoStatus(`Auto action failed: ${msg}`);
      }
    })();
  }, [autoDestroy, autoDownload, exitQuery.data, instanceId, localDownloadDir, meta]);

  async function onRun() {
    setRunError(null);
    setMeta(null);
    setAutoStatus(null);
    autoTriggeredRef.current = false;

    const id = Number(instanceId);
    if (!Number.isFinite(id) || id <= 0) {
      setRunError("Please select a valid instance id.");
      return;
    }

    try {
      await vastAttachSshKey(id);
      await new Promise((r) => setTimeout(r, 1200));

      const input: RunVastJobInput = {
        project_dir: projectDir.trim(),
        command: command.trim(),
        instance_id: id,
        workdir: workdir.trim() ? workdir.trim() : null,
        remote_output_dir: outputDir.trim() ? outputDir.trim() : null,
        hf_home: effectiveHfHome.trim() ? effectiveHfHome.trim() : null,
        sync,
        include_data: includeData,
        include_models: includeModels,
        include_dotenv: includeDotenv,
        extra_excludes: extraExcludes.trim() ? extraExcludes.trim() : null
      } as any;

      const out = await runMut.mutateAsync(input);
      setMeta(out);

      const jobName = out.remote.job_dir.split("/").slice(-1)[0] ?? "job";
      const defaultLocal = projectDir.trim() ? `${projectDir.trim()}/doppio-output/${jobName}` : `./doppio-output/${jobName}`;
      setLocalDownloadDir((prev) => (prev.trim() ? prev : defaultLocal));
    } catch (err) {
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : err instanceof Error
            ? err.message
            : String(err);
      setRunError(msg);
    }
  }

  function renderInstanceHint(inst: VastInstance | null) {
    if (!inst) return <div className="text-xs text-foreground/60">Select an instance.</div>;
    return (
      <div className="text-xs text-foreground/60">
        SSH: {inst.ssh_host && inst.ssh_port ? `${inst.ssh_host}:${inst.ssh_port}` : "-"} · GPU:{" "}
        {inst.gpu_name ? `${inst.num_gpus ?? ""} ${inst.gpu_name}` : "-"}
      </div>
    );
  }

  const logsText = useMemo(() => (logsQuery.data ?? []).join("\n"), [logsQuery.data]);
  const gpuRows = useMemo<GpuRow[]>(() => gpuQuery.data ?? [], [gpuQuery.data]);

  // GPU table columns for DataTable
  const gpuColumns: ColumnDef<GpuRow>[] = useMemo(() => [
    {
      key: "index",
      header: "Index",
      render: (r) => <span className="font-mono text-xs">{r.index}</span>,
    },
    {
      key: "name",
      header: "Name",
      render: (r) => <span className="text-sm">{r.name}</span>,
    },
    {
      key: "util",
      header: "Util",
      render: (r) => <span className="text-sm">{r.util_gpu}%</span>,
    },
    {
      key: "mem",
      header: "Mem",
      render: (r) => (
        <span className="text-sm">
          {r.mem_used}/{r.mem_total} MiB ({r.util_mem}%)
        </span>
      ),
    },
    {
      key: "temp",
      header: "Temp",
      render: (r) => <span className="text-sm">{r.temp}°C</span>,
    },
    {
      key: "power",
      header: "Power",
      render: (r) => <span className="text-sm">{r.power} W</span>,
    },
  ], []);

  return (
    <div className="doppio-page">
      <div className="doppio-page-content space-y-6">
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardTitle>Run</CardTitle>
              <CardDescription>
                上传项目 → tmux 启动训练 → 轮询日志/GPU → 完成后自动下载/销毁。
              </CardDescription>
            </div>
            <Button onClick={onRun} disabled={runMut.isPending}>
              {runMut.isPending ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Running...</> : "Run on Vast"}
            </Button>
          </CardHeader>
          <Separator />
          <CardContent className="space-y-6 pt-4">
            {cfgQuery.isLoading ? (
              <div className="flex items-center gap-3 py-4">
                <Loader2 className="h-4 w-4 animate-spin" />
                <div className="text-sm text-muted-foreground">Loading config…</div>
              </div>
            ) : null}

            <section className="grid gap-4">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Project Dir</Label>
                  <Input
                    value={projectDir}
                    onChange={(e) => setProjectDir(e.target.value)}
                    placeholder="/path/to/your/project"
                  />
                  <p className="text-xs text-muted-foreground">
                    会自动排除 .git/node_modules/src-tauri/target 等；可通过 extra excludes 再排除。
                  </p>
                </div>
                <div className="space-y-2">
                  <Label>Instance ID</Label>
                  <Input
                    value={instanceId}
                    onChange={(e) => setInstanceId(e.target.value)}
                    placeholder="e.g. 123456"
                  />
                  <p className="text-xs text-muted-foreground">
                    从 Vast.ai Instances 页面复制（需要实例处于可 SSH 状态）。
                  </p>
                </div>
              </div>
              {renderInstanceHint(selectedInstance)}

              <div className="space-y-2">
                <Label>Command</Label>
                <Input
                  value={command}
                  onChange={(e) => setCommand(e.target.value)}
                  placeholder="python train.py --config configs/xxx.yaml"
                />
                <p className="text-xs text-muted-foreground">
                  会在远端用 bash -lc 执行，并通过 tee 写入 train.log。
                </p>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <div className="space-y-2">
                  <Label>Workdir (optional)</Label>
                  <Input
                    value={workdir}
                    onChange={(e) => setWorkdir(e.target.value)}
                    placeholder="."
                  />
                  <p className="text-xs text-muted-foreground">相对于项目根目录的子目录；留空=项目根目录。</p>
                </div>
                <div className="space-y-2">
                  <Label>Output dir (optional)</Label>
                  <Input
                    value={outputDir}
                    onChange={(e) => setOutputDir(e.target.value)}
                    placeholder="outputs"
                  />
                  <p className="text-xs text-muted-foreground">
                    远端输出目录（留空则 job_dir/output；支持绝对路径或相对 workdir）。
                  </p>
                </div>
                <div className="space-y-2">
                  <Label>HF_HOME (optional)</Label>
                  <Input
                    value={hfHome}
                    onChange={(e) => setHfHome(e.target.value)}
                    placeholder={cfgQuery.data?.colab.hf_home ?? "~/.cache/huggingface"}
                  />
                  <p className="text-xs text-muted-foreground">
                    留空则使用 Settings → Colab 的 hf_home 或默认 ~/.cache/huggingface。
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="flex items-center gap-2">
                  <Switch checked={sync} onCheckedChange={setSync} id="sync-switch" />
                  <Label htmlFor="sync-switch">Sync project (upload & extract)</Label>
                </div>
                <div className="space-y-2">
                  <Label>Extra excludes (optional)</Label>
                  <Input
                    value={extraExcludes}
                    onChange={(e) => setExtraExcludes(e.target.value)}
                    placeholder="checkpoints, wandb"
                  />
                  <p className="text-xs text-muted-foreground">逗号/换行分隔，作为打包排除前缀。</p>
                </div>
              </div>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <div className="flex items-center gap-2">
                  <Switch checked={includeData} onCheckedChange={setIncludeData} id="include-data" />
                  <Label htmlFor="include-data">Include data/</Label>
                </div>
                <div className="flex items-center gap-2">
                  <Switch checked={includeModels} onCheckedChange={setIncludeModels} id="include-models" />
                  <Label htmlFor="include-models">Include models/</Label>
                </div>
                <div className="flex items-center gap-2">
                  <Switch checked={includeDotenv} onCheckedChange={setIncludeDotenv} id="include-dotenv" />
                  <Label htmlFor="include-dotenv">Include .env (unsafe)</Label>
                </div>
              </div>

              <Separator />

              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <div className="space-y-2">
                  <Label>Local download dir</Label>
                  <Input
                    value={localDownloadDir}
                    onChange={(e) => setLocalDownloadDir(e.target.value)}
                    placeholder="/path/to/save/outputs"
                  />
                  <p className="text-xs text-muted-foreground">用于下载远端 output dir。</p>
                </div>
                <div className="flex items-center gap-2">
                  <Switch checked={autoDownload} onCheckedChange={setAutoDownload} id="auto-download" />
                  <Label htmlFor="auto-download">Auto download on finish</Label>
                </div>
                <div className="flex items-center gap-2">
                  <Switch checked={autoDestroy} onCheckedChange={setAutoDestroy} id="auto-destroy" />
                  <Label htmlFor="auto-destroy">Auto destroy instance on finish</Label>
                </div>
              </div>
            </section>

            {(runError || meta) && (
              <section className="grid gap-4">
                <Separator />
                {runError ? <div className="text-sm text-destructive">Run failed: {runError}</div> : null}
                {meta ? (
                  <>
                    <div className="text-sm grid gap-1">
                      <div>
                        <span className="font-semibold">tmux session:</span>{" "}
                        <span className="font-mono">{meta.remote.tmux_session}</span>
                      </div>
                      <div>
                        <span className="font-semibold">job_dir:</span>{" "}
                        <span className="font-mono text-xs">{meta.remote.job_dir}</span>
                      </div>
                      <div>
                        <span className="font-semibold">workdir:</span>{" "}
                        <span className="font-mono text-xs">{meta.remote.workdir}</span>
                      </div>
                      <div>
                        <span className="font-semibold">log:</span>{" "}
                        <span className="font-mono text-xs">{meta.remote.log_path}</span>
                      </div>
                      <div>
                        <span className="font-semibold">output_dir:</span>{" "}
                        <span className="font-mono text-xs">{meta.remote.output_dir ?? "-"}</span>
                      </div>
                      <div>
                        <span className="font-semibold">meta:</span>{" "}
                        <span className="font-mono text-xs">{meta.local_meta_path}</span>
                      </div>
                      <div>
                        <span className="font-semibold">exit code:</span>{" "}
                        {exitQuery.isLoading ? (
                          "…"
                        ) : exitQuery.data == null ? (
                          <Badge variant="secondary">running</Badge>
                        ) : (
                          exitQuery.data
                        )}
                      </div>
                      {autoStatus ? <div className="text-xs text-muted-foreground">Auto: {autoStatus}</div> : null}
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        disabled={!meta.remote.output_dir || !localDownloadDir.trim()}
                        onClick={async () => {
                          if (!meta.remote.output_dir) return;
                          await downloadRemoteDir({
                            ssh: meta.ssh,
                            remoteDir: meta.remote.output_dir,
                            localDir: localDownloadDir.trim(),
                            delete: false
                          });
                        }}
                      >
                        Download outputs
                      </Button>
                      <Button
                        variant="destructive"
                        onClick={async () => {
                          const id = Number(instanceId);
                          if (!Number.isFinite(id)) return;
                          if (!confirm(`Destroy instance ${id}?`)) return;
                          await vastDestroyInstance(id);
                        }}
                      >
                        Destroy instance
                      </Button>
                      <Button variant="outline" onClick={() => logsQuery.refetch()}>
                        Refresh logs
                      </Button>
                      <Button variant="outline" onClick={() => gpuQuery.refetch()}>
                        Refresh GPU
                      </Button>
                    </div>

                    <Separator />

                    <div className="grid gap-3">
                      <div className="text-sm font-semibold">GPU</div>
                      <DataTable
                        data={gpuRows}
                        columns={gpuColumns}
                        rowKey={(r) => `${r.index}-${r.name}`}
                        emptyContent="No GPU data"
                        compact
                      />
                    </div>

                    <Separator />

                    <div className="grid gap-3">
                      <div className="text-sm font-semibold">Logs (tail -n 200)</div>
                      <Textarea
                        value={logsText}
                        readOnly
                        className="font-mono text-xs min-h-[300px]"
                      />
                    </div>
                  </>
                ) : null}
              </section>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

