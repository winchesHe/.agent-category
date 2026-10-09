import { Badge } from "@/components/ui/badge";
import { ExternalLink } from "lucide-react";
import { inlineTokens } from "./inline-tokens";

export function RichText({ children }: { children?: string | null }) {
  const tokens = inlineTokens(children ?? "");
  return <>{tokens.map((token, index) => {
    if (token.kind === "text") return token.value;
    if (token.kind === "link") {
      return (
        <Badge key={index} variant="outline" asChild className="ev-inline-link">
          <a href={token.value} target="_blank" rel="noopener noreferrer" title={token.value}>
            {token.label}
            <ExternalLink aria-hidden="true" />
          </a>
        </Badge>
      );
    }
    const commit = /^[0-9a-f]{40}$/.test(token.value);
    return (
      <Badge key={index} variant="secondary" asChild className="ev-inline-code">
        <code title={commit ? token.value : undefined} aria-label={commit ? token.value : undefined}>
          {commit ? token.value.slice(0, 8) : token.value}
        </code>
      </Badge>
    );
  })}</>;
}
