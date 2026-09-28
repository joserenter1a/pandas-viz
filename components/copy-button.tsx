"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

export function CopyButton({
  text,
  label,
  size = "sm",
  variant = "outline",
}: {
  text: string;
  label?: string;
  size?: "sm" | "xs" | "icon-xs";
  variant?: "outline" | "ghost" | "default";
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked (e.g. insecure context): nothing sensible to fall back to
    }
  };
  const Icon = copied ? Check : Copy;
  return (
    <Button size={size} variant={variant} onClick={copy} disabled={!text} aria-label={label ?? "Copy"}>
      <Icon />
      {label && (copied ? "Copied" : label)}
    </Button>
  );
}
