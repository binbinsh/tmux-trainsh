import { Navbar, NavbarContent, NavbarItem } from "@nextui-org/react";
import { Link, Outlet } from "@tanstack/react-router";

function NavLink(props: { to: string; label: string }) {
  return (
    <NavbarItem>
      <Link
        to={props.to}
        className="text-sm text-foreground/80 hover:text-foreground data-[status=active]:text-foreground data-[status=active]:font-semibold"
        activeProps={{ "data-status": "active" }}
      >
        {props.label}
      </Link>
    </NavbarItem>
  );
}

// Legacy layout - kept for backward compatibility
export function AppLayout() {
  return (
    <div className="h-full flex flex-col">
      <Navbar maxWidth="full" className="border-b border-divider">
        <NavbarContent justify="start" className="gap-4">
          <NavLink to="/dashboard" label="Dashboard" />
          <NavLink to="/hosts" label="Hosts" />
          <NavLink to="/sessions" label="Sessions" />
          <NavLink to="/vast" label="Vast.ai" />
          <NavLink to="/colab" label="Colab" />
          <NavLink to="/job" label="Run" />
          <NavLink to="/terminal" label="Terminal" />
          <NavLink to="/settings" label="Settings" />
        </NavbarContent>
      </Navbar>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
