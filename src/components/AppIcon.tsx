import cloudflareIcon from "../assets/icons/cloudflare.svg";
import googleColabIcon from "../assets/icons/google-colab.svg";
import googleDriveIcon from "../assets/icons/google-drive.svg";
import sshIcon from "../assets/icons/ssh.ico";
import sambaIcon from "../assets/icons/samba.ico";
import vastAiIcon from "../assets/icons/vast-ai.png";
import hostServerIcon from "../assets/icons/host-server.svg";

const ICONS = {
  cloudflare: cloudflareIcon,
  colab: googleColabIcon,
  googledrive: googleDriveIcon,
  host: hostServerIcon,
  ssh: sshIcon,
  smb: sambaIcon,
  vast: vastAiIcon,
} as const;

export type AppIconName = keyof typeof ICONS;

export function AppIcon({
  name,
  className,
  alt,
  title,
}: {
  name: AppIconName;
  className?: string;
  alt?: string;
  title?: string;
}) {
  return (
    <img
      src={ICONS[name]}
      alt={alt ?? title ?? name}
      title={title}
      className={`object-contain ${className ?? ""}`.trim()}
      draggable={false}
    />
  );
}
