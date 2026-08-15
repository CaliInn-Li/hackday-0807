import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  description: string;
  action?: ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps): JSX.Element {
  return (
    <div className="empty-state">
      <div className="empty-mark">∅</div>
      <div>
        <h3>{title}</h3>
        <p className="muted">{description}</p>
        {action}
      </div>
    </div>
  );
}
